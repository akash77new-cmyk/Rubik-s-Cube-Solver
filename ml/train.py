"""Train the sticker colour CNN on the scan dataset, test it, and export it to ONNX (Phase 11).

    python -m pip install -r requirements-ml.txt      # PyTorch + ONNX, once (training only)
    python ml/train.py                                # about a minute on a laptop CPU

What it does, in order:

1. **Load** every scan in ``ml/data/scans/``: 54 labelled 32 x 32 crops each (see
   ``ml/data/README.md``).
2. **Split by scan, not by sticker.** Stickers of one scan share its light and camera, so
   a test sticker from a scan the model trained on would make the score look better than
   it is. Whole scans go to the test set (about 1 in 5, at least 1).
3. **Train** a small CNN (about 24,000 numbers to learn) with **augmentation**: every
   epoch each crop is randomly rotated, flipped, shifted, made brighter or darker, given a
   slight colour cast and noise. A few hundred real crops then act like many thousands.
   Hue is never shifted: that would turn orange into red and make the label wrong.
4. **Test** on the held-out scans, against the HSV detector on the very same stickers
   (its colour is stored in each scan as ``hsvPredicted``).
5. **Export** to ``ml/models/sticker_cnn.onnx``, load it back with OpenCV (as the app
   will) and check that OpenCV and PyTorch give the same probabilities.
6. **Write** ``ml/models/sticker_cnn.json`` (how it was trained and tested; the app reads
   it) and the report ``docs/eval/classifier.md``.

The app uses the CNN in "auto" mode only if it was at least as accurate as HSV here.
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
import time
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # so "backend" imports work when run as a script

from backend.core.cube import COLOR_CODES, COLOR_NAMES  # noqa: E402
from backend.vision.classifier import META_FILE, META_SCHEMA, MODEL_FILE, StickerClassifier  # noqa: E402

try:
    import torch
    from torch import nn
except ImportError:  # pragma: no cover - the app itself never needs PyTorch
    sys.exit("Training needs PyTorch: python -m pip install -r requirements-ml.txt")

CLASSES: Tuple[str, ...] = tuple(COLOR_CODES)
SIZE = 32
MEAN, STD = 0.5, 0.25  # inputs are scaled to 0..1, then (x - MEAN) / STD
MIN_SCANS = 3


@dataclass
class Scan:
    id: str
    lighting: str
    images: np.ndarray  # (54, 32, 32, 3) uint8, BGR as saved
    labels: np.ndarray  # (54,) class indexes
    hsv: List[str]  # the HSV detector's colour per sticker


# --------------------------------------------------------------------------------------
# 1-2. Data
# --------------------------------------------------------------------------------------


def load_scans(data_dir: Path) -> List[Scan]:
    """Every complete scan under ``data_dir/scans``, oldest first."""
    scans: List[Scan] = []
    for meta_path in sorted((Path(data_dir) / "scans").glob("*/scan.json")):
        folder = meta_path.parent
        if folder.name.startswith(".tmp-"):
            continue  # a half-written scan
        record = json.loads(meta_path.read_text("utf-8"))
        if record.get("schema") != 1 or len(record.get("stickers", [])) != 54:
            print(f"  skipping {folder.name}: not a complete schema-1 scan")
            continue
        images, labels, hsv = [], [], []
        for sticker in record["stickers"]:
            # np.fromfile + imdecode also works for non-ASCII Windows paths (cv2.imread doesn't).
            image = cv2.imdecode(np.fromfile(str(folder / sticker["file"]), np.uint8), cv2.IMREAD_COLOR)
            if image is None:
                raise OSError(f"Could not read {folder / sticker['file']}")
            if image.shape[:2] != (SIZE, SIZE):
                image = cv2.resize(image, (SIZE, SIZE), interpolation=cv2.INTER_AREA)
            images.append(image)
            labels.append(CLASSES.index(sticker["label"]))
            hsv.append(sticker.get("hsvPredicted") or sticker["predicted"])
        scans.append(Scan(record["id"], record.get("lighting", "other"), np.stack(images), np.array(labels), hsv))
    return scans


def split_scans(scans: Sequence[Scan], test_count: int, seed: int) -> Tuple[List[Scan], List[Scan]]:
    """(train, test): whole scans, picked at random but the same every run for a seed."""
    order = list(scans)
    random.Random(seed).shuffle(order)
    return sorted(order[test_count:], key=lambda s: s.id), sorted(order[:test_count], key=lambda s: s.id)


def to_tensor(images: np.ndarray) -> "torch.Tensor":
    """uint8 (N, 32, 32, 3) BGR -> float (N, 3, 32, 32) in 0..1 (normalised later)."""
    return torch.from_numpy(images.astype(np.float32) / 255.0).permute(0, 3, 1, 2).contiguous()


def augment(batch: "torch.Tensor", generator: "torch.Generator") -> "torch.Tensor":
    """Random changes a real camera could make. ``batch`` is (N, 3, 32, 32) in 0..1."""
    n = batch.shape[0]
    out = torch.empty_like(batch)
    padded = nn.functional.pad(batch, (3, 3, 3, 3), mode="replicate")
    for i in range(n):  # rotation, flip and shift differ per crop
        dy, dx = (int(v) for v in torch.randint(0, 7, (2,), generator=generator))
        image = padded[i, :, dy:dy + SIZE, dx:dx + SIZE]
        image = torch.rot90(image, int(torch.randint(0, 4, (1,), generator=generator)), dims=(1, 2))
        if torch.rand(1, generator=generator) < 0.5:
            image = torch.flip(image, dims=(2,))
        out[i] = image
    brightness = torch.empty(n, 1, 1, 1).uniform_(0.6, 1.4, generator=generator)
    cast = torch.empty(n, 3, 1, 1).uniform_(0.9, 1.1, generator=generator)  # a slight tint, never a hue shift
    noise = torch.randn(out.shape, generator=generator) * 0.02
    return (out * brightness * cast + noise).clamp(0.0, 1.0)


def normalise(batch: "torch.Tensor") -> "torch.Tensor":
    return (batch - MEAN) / STD


# --------------------------------------------------------------------------------------
# 3. The model
# --------------------------------------------------------------------------------------


class StickerCNN(nn.Module):
    """Three small convolution blocks, then one score per colour.

    32x32x3 -> conv 16 -> pool -> 16x16 -> conv 32 -> pool -> 8x8 -> conv 64 -> average -> 6 scores.
    A convolution learns small colour/texture detectors that slide over the image; pooling
    halves the size; the global average turns the 8x8 map into one number per detector, so
    a glare spot or a dark corner moves the answer only a little.
    """

    def __init__(self) -> None:
        super().__init__()

        def block(cin: int, cout: int) -> nn.Sequential:
            return nn.Sequential(nn.Conv2d(cin, cout, 3, padding=1), nn.BatchNorm2d(cout), nn.ReLU())

        self.features = nn.Sequential(
            block(3, 16), nn.MaxPool2d(2),
            block(16, 32), nn.MaxPool2d(2),
            block(32, 64),
            nn.AdaptiveAvgPool2d(1), nn.Flatten(),
        )
        self.head = nn.Sequential(nn.Dropout(0.2), nn.Linear(64, len(CLASSES)))

    def forward(self, x: "torch.Tensor") -> "torch.Tensor":
        return self.head(self.features(x))


def train(model: StickerCNN, images: np.ndarray, labels: np.ndarray, epochs: int, seed: int) -> List[float]:
    """Train in place. Returns the average loss of each epoch."""
    generator = torch.Generator().manual_seed(seed)
    x, y = to_tensor(images), torch.from_numpy(labels).long()
    optimiser = torch.optim.AdamW(model.parameters(), lr=3e-3, weight_decay=1e-4)
    schedule = torch.optim.lr_scheduler.CosineAnnealingLR(optimiser, epochs)
    loss_fn = nn.CrossEntropyLoss(label_smoothing=0.05)
    losses: List[float] = []
    for _ in range(epochs):
        model.train()
        order = torch.randperm(len(x), generator=generator)
        total = 0.0
        for start in range(0, len(x), 64):
            index = order[start:start + 64]
            optimiser.zero_grad()
            loss = loss_fn(model(normalise(augment(x[index], generator))), y[index])
            loss.backward()
            optimiser.step()
            total += loss.item() * len(index)
        schedule.step()
        losses.append(total / len(x))
    return losses


def predict(model: StickerCNN, images: np.ndarray) -> np.ndarray:
    """Probabilities (N, 6) from PyTorch."""
    model.eval()
    with torch.no_grad():
        return torch.softmax(model(normalise(to_tensor(images))), dim=1).numpy()


# --------------------------------------------------------------------------------------
# 4. Testing
# --------------------------------------------------------------------------------------


def evaluate(test: Sequence[Scan], probabilities: np.ndarray) -> Dict[str, object]:
    labels = np.concatenate([scan.labels for scan in test])
    cnn = probabilities.argmax(axis=1)
    hsv = np.array([CLASSES.index(code) for scan in test for code in scan.hsv])
    confusion = np.zeros((len(CLASSES), len(CLASSES)), int)
    for truth, guess in zip(labels, cnn):
        confusion[truth, guess] += 1
    per_scan = []
    offset = 0
    for scan in test:
        n = len(scan.labels)
        per_scan.append({
            "id": scan.id,
            "lighting": scan.lighting,
            "cnnCorrect": int((cnn[offset:offset + n] == labels[offset:offset + n]).sum()),
            "hsvCorrect": int((hsv[offset:offset + n] == labels[offset:offset + n]).sum()),
            "stickers": n,
        })
        offset += n
    cnn_correct, hsv_correct = int((cnn == labels).sum()), int((hsv == labels).sum())
    return {
        "scans": len(test),
        "stickers": int(len(labels)),
        "cnnCorrect": cnn_correct,
        "hsvCorrect": hsv_correct,
        "cnnAccuracy": round(cnn_correct / len(labels), 4),
        "hsvAccuracy": round(hsv_correct / len(labels), 4),
        # "beats" = at least as accurate: on a tie the CNN is still used, since it also gives
        # real probabilities for the repair agent (see the README).
        "beatsHsv": cnn_correct >= hsv_correct,
        "fixedHsvMistakes": int(((hsv != labels) & (cnn == labels)).sum()),
        "newMistakes": int(((hsv == labels) & (cnn != labels)).sum()),
        "meanConfidence": round(float(probabilities.max(axis=1).mean()), 3),
        "perColor": {
            code: round(float(confusion[i, i] / max(1, confusion[i].sum())), 4) for i, code in enumerate(CLASSES)
        },
        "confusion": confusion.tolist(),
        "perScan": per_scan,
    }


# --------------------------------------------------------------------------------------
# 5-6. Export and reports
# --------------------------------------------------------------------------------------


def export_onnx(model: StickerCNN, path: Path) -> None:
    """Save the model as ONNX, with a batch size that can change (the app sends 9 crops).

    The classic exporter (``dynamo=False``, ONNX opset 13) is used on purpose: OpenCV 4.10
    can't load the newer exporter's files (tested), and this one loads in OpenCV 4.10 to 5.
    PyTorch marks it as deprecated, so that warning is hidden here.
    """
    model.eval()
    dummy = torch.zeros(1, 3, SIZE, SIZE)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        torch.onnx.export(
            model, (dummy,), str(path), input_names=["crops"], output_names=["logits"],
            dynamic_axes={"crops": {0: "n"}, "logits": {0: "n"}}, opset_version=13, dynamo=False,
        )


def git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                              text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def report_markdown(meta: Dict[str, object]) -> str:
    test = meta["test"]  # type: ignore[index]
    lines = [
        "# Sticker colour classifier: test report",
        "",
        f"Trained {meta['trainedAt']} on commit `{meta['commit']}` by `python ml/train.py` "
        f"(PyTorch {meta['torch']}). Made by the script; never edit the numbers by hand.",
        "",
        "## Data",
        "",
        f"{meta['train']['scans']} scans ({meta['train']['stickers']} stickers) to train, "  # type: ignore[index]
        f"{test['scans']} other scans ({test['stickers']} stickers) to test. Split by scan, so the test "
        "lights and camera positions were never seen in training.",
        "",
        "## Result",
        "",
        "| Model | Correct on the test scans | Accuracy |",
        "| --- | --- | --- |",
        f"| CNN | {test['cnnCorrect']}/{test['stickers']} | {test['cnnAccuracy']:.1%} |",
        f"| HSV detector (baseline) | {test['hsvCorrect']}/{test['stickers']} | {test['hsvAccuracy']:.1%} |",
        "",
        f"The CNN fixed {test['fixedHsvMistakes']} HSV mistake(s) and made {test['newMistakes']} new one(s). "
        f"Average confidence: {test['meanConfidence']:.0%}. "
        + ("It is at least as accurate as HSV, so the app uses it (CUBE_COLOR_MODEL=auto)."
           if test["beatsHsv"] else "It is less accurate than HSV, so the app keeps HSV (CUBE_COLOR_MODEL=auto)."),
        "",
        "| Test scan | Lighting | CNN | HSV |",
        "| --- | --- | --- | --- |",
    ]
    for scan in test["perScan"]:
        lines.append(f"| `{scan['id']}` | {scan['lighting']} | {scan['cnnCorrect']}/{scan['stickers']} | "
                     f"{scan['hsvCorrect']}/{scan['stickers']} |")
    lines += ["", "## Per colour (CNN)", "", "| Colour | Accuracy |", "| --- | --- |"]
    for code, accuracy in test["perColor"].items():
        lines.append(f"| {COLOR_NAMES[code]} | {accuracy:.1%} |")
    lines += ["", "## Confusion matrix (CNN; rows: true colour, columns: predicted)", "",
              "| | " + " | ".join(CLASSES) + " |", "|---" * (len(CLASSES) + 1) + "|"]
    for code, row in zip(CLASSES, test["confusion"]):
        lines.append(f"| **{code}** | " + " | ".join(str(v) for v in row) + " |")
    lines += [
        "",
        "## Model",
        "",
        f"{meta['parameters']:,} parameters, {meta['epochs']} epochs, input 32 x 32 BGR, "
        f"ONNX file {meta['onnxBytes']:,} bytes. OpenCV and PyTorch agree to within "
        f"{meta['onnxMaxDifference']:.1e} on the test crops. Training took {meta['trainSeconds']:.0f} s.",
        "",
        "With only a few test scans, one sticker moves the accuracy by about 1%: treat it as a rough "
        "number, and add scans in new lights to make it firmer.",
        "",
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] = ()) -> int:
    parser = argparse.ArgumentParser(description="Train the sticker colour CNN (Phase 11).")
    parser.add_argument("--data", type=Path, default=ROOT / "ml" / "data", help="dataset folder (has scans/)")
    parser.add_argument("--out", type=Path, default=ROOT / "ml" / "models", help="where the model goes")
    parser.add_argument("--report", type=Path, default=ROOT / "docs" / "eval" / "classifier.md")
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--test-scans", type=int, default=0, help="0 = about 1 in 5 scans, at least 1")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(list(argv) or None)

    scans = load_scans(args.data)
    if len(scans) < MIN_SCANS:
        print(f"Found {len(scans)} scan(s) in {args.data / 'scans'}; at least {MIN_SCANS} are needed "
              "(save more from the Scanner page).")
        return 1
    test_count = args.test_scans or max(1, round(len(scans) / 5))
    if not 1 <= test_count < len(scans):
        print(f"--test-scans must be between 1 and {len(scans) - 1}")
        return 1
    train_scans, test_scans = split_scans(scans, test_count, args.seed)
    print(f"{len(scans)} scans: {len(train_scans)} to train, {len(test_scans)} to test "
          f"({', '.join(s.id for s in test_scans)})")

    torch.manual_seed(args.seed)
    model = StickerCNN()
    images = np.concatenate([s.images for s in train_scans])
    labels = np.concatenate([s.labels for s in train_scans])
    started = time.time()
    losses = train(model, images, labels, args.epochs, args.seed)
    seconds = time.time() - started
    print(f"Trained {args.epochs} epochs in {seconds:.0f} s (loss {losses[0]:.3f} -> {losses[-1]:.3f})")

    test_images = np.concatenate([s.images for s in test_scans])
    probabilities = predict(model, test_images)
    result = evaluate(test_scans, probabilities)

    args.out.mkdir(parents=True, exist_ok=True)
    model_path = args.out / MODEL_FILE
    export_onnx(model, model_path)
    meta: Dict[str, object] = {
        "schema": META_SCHEMA,
        "classes": list(CLASSES),
        "input": {"size": SIZE, "order": "BGR", "mean": MEAN, "std": STD},
        "trainedAt": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
        "commit": git_commit(),
        "torch": torch.__version__.split("+")[0],
        "epochs": args.epochs,
        "seed": args.seed,
        "parameters": sum(p.numel() for p in model.parameters()),
        "trainSeconds": round(seconds, 1),
        "finalLoss": round(losses[-1], 4),
        "train": {"scans": len(train_scans), "stickers": int(len(labels)), "ids": [s.id for s in train_scans]},
        "test": result,
        "onnxBytes": model_path.stat().st_size,
    }
    (args.out / META_FILE).write_text(json.dumps(meta, indent=2), encoding="utf-8")

    # The app runs the model with OpenCV, not PyTorch: check that both give the same answers.
    opencv = StickerClassifier.load(args.out).probabilities(list(test_images))
    difference = float(np.abs(opencv - probabilities).max())
    meta["onnxMaxDifference"] = difference
    (args.out / META_FILE).write_text(json.dumps(meta, indent=2), encoding="utf-8")
    if difference > 1e-3:
        print(f"OpenCV and PyTorch disagree (max difference {difference:.4f}): the export is broken")
        return 1

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(report_markdown(meta), encoding="utf-8")
    print(f"Test: CNN {result['cnnCorrect']}/{result['stickers']} ({result['cnnAccuracy']:.1%}), "
          f"HSV {result['hsvCorrect']}/{result['stickers']} ({result['hsvAccuracy']:.1%}); "
          f"the app will use {'the CNN' if result['beatsHsv'] else 'HSV'} in auto mode")
    print(f"Wrote {model_path}, {args.out / META_FILE} and {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
