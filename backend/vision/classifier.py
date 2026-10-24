"""The trained sticker colour classifier (Phase 11): a small CNN, run with OpenCV.

The HSV detector (``backend/core/color.py``) decides a sticker's colour from three
numbers: the median hue, saturation and brightness of a patch. That fails under some
lights (red vs orange under a warm bulb, white vs yellow in dim rooms). The CNN looks
at the whole 32 x 32 crop instead, and learned the colours from real, confirmed scans.

How it fits together::

    ml/train.py (PyTorch, on a laptop)  ->  ml/models/sticker_cnn.onnx  + sticker_cnn.json
                                                      |
    the app (no PyTorch)  ->  cv2.dnn.readNetFromONNX  ->  6 probabilities per sticker

- **ONNX** is a standard file format for trained models, so the app does not need
  PyTorch (about 1 GB) to use the model: OpenCV, already installed, runs it.
- **The metadata file** (``sticker_cnn.json``) says how the model was trained and
  tested: the colour order, the input format, and its accuracy against the HSV
  detector on scans it never saw.
- **"auto" mode** uses the CNN only if that test says it is at least as accurate as HSV.
  Otherwise the app keeps HSV, so a weak model can never make scanning worse.

The model outputs one score (a "logit") per colour; softmax turns them into
probabilities that add up to 1. The best probability is the confidence.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from backend.core.color import ColorScore
from backend.core.cube import COLOR_CODES

log = logging.getLogger(__name__)

MODEL_FILE = "sticker_cnn.onnx"
META_FILE = "sticker_cnn.json"
#: Bump when the metadata layout or the input format changes.
META_SCHEMA = 1
#: Below this probability the CNN's reading counts as uncertain ("low_confidence").
LOW_CONFIDENCE = 0.6
UNCERTAIN_LOW_CONFIDENCE = "low_confidence"
MODES = ("auto", "hsv", "cnn")


def softmax(logits: np.ndarray) -> np.ndarray:
    """Rows of scores -> rows of probabilities (subtracting the max avoids overflow)."""
    shifted = logits - logits.max(axis=1, keepdims=True)
    exp = np.exp(shifted)
    return exp / exp.sum(axis=1, keepdims=True)


def preprocess(crops: Sequence[np.ndarray], size: int, mean: float, std: float) -> np.ndarray:
    """BGR uint8 crops -> one float32 batch of shape (N, 3, size, size), as in training."""
    images = [
        image if image.shape[:2] == (size, size) else cv2.resize(image, (size, size), interpolation=cv2.INTER_AREA)
        for image in crops
    ]
    batch = np.stack(images).astype(np.float32) / 255.0  # (N, H, W, 3), channels in BGR order
    batch = (batch - mean) / std
    return np.ascontiguousarray(batch.transpose(0, 3, 1, 2))  # (N, 3, H, W): channels first


@dataclass(frozen=True)
class ClassifierInfo:
    """What sticker_cnn.json says about the model."""

    classes: Tuple[str, ...]
    size: int
    mean: float
    std: float
    accuracy: Optional[float]  # the CNN on the held-out test scans
    hsv_accuracy: Optional[float]  # the HSV detector on the same stickers
    beats_hsv: bool
    test_scans: int
    trained_at: str

    @classmethod
    def from_dict(cls, meta: Dict[str, Any]) -> "ClassifierInfo":
        if meta.get("schema") != META_SCHEMA:
            raise ValueError(f"{META_FILE} has schema {meta.get('schema')!r}, expected {META_SCHEMA}")
        classes = tuple(meta.get("classes") or ())
        if sorted(classes) != sorted(COLOR_CODES) or len(classes) != len(COLOR_CODES):
            raise ValueError(f"{META_FILE} must list the six colours, got {classes}")
        image = meta.get("input") or {}
        test = meta.get("test") or {}
        return cls(
            classes=classes,
            size=int(image.get("size", 32)),
            mean=float(image.get("mean", 0.5)),
            std=float(image.get("std", 0.25)),
            accuracy=test.get("cnnAccuracy"),
            hsv_accuracy=test.get("hsvAccuracy"),
            beats_hsv=bool(test.get("beatsHsv", False)),
            test_scans=int(test.get("scans", 0)),
            trained_at=str(meta.get("trainedAt", "")),
        )


class StickerClassifier:
    """Runs the ONNX model on sticker crops. One instance is shared by the detector."""

    def __init__(self, net: Any, info: ClassifierInfo) -> None:
        self._net = net
        self.info = info
        self._lock = threading.Lock()  # an OpenCV network must not run two inputs at once

    @classmethod
    def load(cls, model_dir: Path) -> "StickerClassifier":
        """Load the model and its metadata. Raises OSError or ValueError if they are unusable."""
        model_path, meta_path = Path(model_dir) / MODEL_FILE, Path(model_dir) / META_FILE
        if not model_path.is_file() or not meta_path.is_file():
            raise FileNotFoundError(f"No trained model in {model_dir} ({MODEL_FILE} + {META_FILE})")
        info = ClassifierInfo.from_dict(json.loads(meta_path.read_text("utf-8")))
        try:
            net = cv2.dnn.readNetFromONNX(str(model_path))
        except cv2.error as exc:
            raise ValueError(f"OpenCV could not load {MODEL_FILE}: {exc}") from exc
        classifier = cls(net, info)
        try:  # fail now, not mid-scan
            classifier.probabilities([np.zeros((info.size, info.size, 3), np.uint8)])
        except cv2.error as exc:
            raise ValueError(f"OpenCV could not run {MODEL_FILE}: {exc}") from exc
        return classifier

    def probabilities(self, crops: Sequence[np.ndarray]) -> np.ndarray:
        """One row of 6 probabilities per crop, in ``info.classes`` order."""
        if not crops:
            return np.zeros((0, len(self.info.classes)), np.float32)
        batch = preprocess(crops, self.info.size, self.info.mean, self.info.std)
        with self._lock:
            self._net.setInput(batch)
            logits = np.asarray(self._net.forward(), dtype=np.float32).reshape(len(crops), -1)
        if logits.shape[1] != len(self.info.classes):
            raise ValueError(f"The model gave {logits.shape[1]} scores per sticker, expected {len(self.info.classes)}")
        return softmax(logits)

    def rank(self, crops: Sequence[np.ndarray]) -> List[List[ColorScore]]:
        """Every colour for each crop, best first, like ``ColorProfile.rank`` does for HSV."""
        rankings: List[List[ColorScore]] = []
        for row in self.probabilities(crops):
            scores = [ColorScore(code, round(float(p), 3), float(p) >= LOW_CONFIDENCE) for code, p in zip(self.info.classes, row)]
            scores.sort(key=lambda score: -score.confidence)
            rankings.append(scores)
        return rankings


def cnn_uncertainty(ranking: Sequence[ColorScore]) -> Optional[str]:
    """``"low_confidence"`` when the CNN's best probability is below LOW_CONFIDENCE, else None."""
    if not ranking or ranking[0].confidence < LOW_CONFIDENCE:
        return UNCERTAIN_LOW_CONFIDENCE
    return None


def load_color_model(mode: str, model_dir: Path) -> Tuple[Optional[StickerClassifier], Dict[str, Any]]:
    """Pick the colour model for the scanner: ``(classifier or None, status for the UI)``.

    - ``hsv``: always the HSV detector.
    - ``cnn``: the CNN if it loads (for experiments, even if it lost to HSV), else HSV.
    - ``auto`` (default): the CNN only if it loads **and** was at least as accurate as HSV on
      its test scans (``beatsHsv`` in the metadata).
    """
    status: Dict[str, Any] = {"mode": mode, "active": "hsv", "reason": "", "model": None}
    if mode == "hsv":
        status["reason"] = "CUBE_COLOR_MODEL=hsv"
        return None, status
    try:
        classifier = StickerClassifier.load(model_dir)
    except (OSError, ValueError) as exc:
        status["reason"] = f"no usable trained model ({exc})"
        return None, status
    info = classifier.info
    status["model"] = {
        "trainedAt": info.trained_at,
        "testScans": info.test_scans,
        "cnnAccuracy": info.accuracy,
        "hsvAccuracy": info.hsv_accuracy,
        "beatsHsv": info.beats_hsv,
    }
    if mode == "auto" and not info.beats_hsv:
        status["reason"] = "the trained model was less accurate than HSV on its test scans"
        return None, status
    status["active"] = "cnn"
    status["reason"] = "CUBE_COLOR_MODEL=cnn" if mode == "cnn" else "the trained model was at least as accurate as HSV"
    return classifier, status
