"""Training data for the Phase 11 colour classifier.

Every saved scan becomes one folder::

    ml/data/scans/<scan id>/
        scan.json            labels, detector predictions, confidences, lighting, settings
        U0.png ... B8.png    54 sticker crops, 32 x 32 pixels, as the camera saw them

Why it is built this way:

* **Labels are confirmed, not guessed.** A scan can only be saved once the cube
  passes full validation, and after any sticker the user corrected. The label of
  each crop is the colour in that confirmed cube, not the detector's guess.
* **Corrected stickers are marked.** Where the user had to fix the detector's
  colour, ``corrected`` is true. Those are the hard examples a classifier most
  needs to learn from.
* **Balanced by design.** Every real cube has nine stickers of each colour, so
  every scan adds exactly nine examples per class.
* **Privacy by design.** Only tiny sticker crops are kept, never full frames.
* **No half-written scans.** Files go to a temporary folder that is renamed only
  once everything is written.
"""

from __future__ import annotations

import copy
import json
import logging
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

import cv2
import numpy as np

from backend.core.cube import COLOR_CODES, FACE_ORDER

log = logging.getLogger(__name__)

#: Bump when the scan.json layout changes, so loaders can tell versions apart.
SCHEMA_VERSION = 1

#: Lighting tags, chosen by the user for each scan. Varied lighting is what makes
#: the classifier robust, so the dataset records it.
LIGHTING_OPTIONS: Dict[str, str] = {
    "daylight": "Daylight",
    "warm": "Warm indoor",
    "cool": "Cool indoor",
    "dim": "Dim",
    "glare": "Glare",
    "other": "Other",
}


def new_scan_id() -> str:
    """Sortable, unique folder name, e.g. ``20261020-084512-3f9a1c`` (UTC time)."""
    return time.strftime("%Y%m%d-%H%M%S", time.gmtime()) + "-" + uuid.uuid4().hex[:6]


def build_scan_record(
    lighting: str,
    labels: Mapping[str, Sequence[str]],
    readings: Mapping[str, Sequence[Mapping[str, Any]]],
    profile: str,
    camera: Mapping[str, Any],
    detector: Mapping[str, Any],
    scan_id: Optional[str] = None,
    color_model: str = "hsv",
) -> Dict[str, Any]:
    """Describe one confirmed scan as plain JSON-ready data.

    ``labels`` are the confirmed colours (face -> 9 codes). ``readings`` are the
    detector's sticker readings captured with the camera (``StickerReading.to_dict()``
    per sticker). ``color_model`` is the model that made ``predicted``: "hsv" or "cnn"
    (Phase 11); ``hsvPredicted`` is always the HSV detector's colour, so the HSV
    baseline can be measured on every scan. Raises ValueError if anything is missing
    or malformed.
    """
    if lighting not in LIGHTING_OPTIONS:
        raise ValueError(f"Unknown lighting {lighting!r}; use one of {', '.join(LIGHTING_OPTIONS)}")
    for face in FACE_ORDER:
        if len(labels.get(face, ())) != 9 or len(readings.get(face, ())) != 9:
            raise ValueError(f"Face {face} needs 9 labels and 9 readings")

    stickers: List[Dict[str, Any]] = []
    for face in FACE_ORDER:
        for index in range(9):
            label = labels[face][index]
            reading = readings[face][index]
            if label not in COLOR_CODES:
                raise ValueError(f"Label {label!r} at {face}{index} is not a colour code")
            stickers.append(
                {
                    "file": f"{face}{index}.png",
                    "face": face,
                    "index": index,
                    "label": label,
                    "predicted": reading["color"],
                    "hsvPredicted": reading.get("hsvColor") or reading["color"],
                    "corrected": reading["color"] != label,
                    "confidence": reading["confidence"],
                    "alternatives": list(reading.get("alternatives", [])),
                    "hsv": list(reading.get("hsv", [])),
                    "uncertain": reading.get("uncertain"),
                }
            )

    return {
        "schema": SCHEMA_VERSION,
        "id": scan_id or new_scan_id(),
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "lighting": lighting,
        "profile": profile,
        "colorModel": color_model,
        "camera": dict(camera),
        "detector": dict(detector),
        "centers": {face: labels[face][4] for face in FACE_ORDER},
        "counts": {
            "stickers": len(stickers),
            "corrected": sum(1 for sticker in stickers if sticker["corrected"]),
            "uncertain": sum(1 for sticker in stickers if sticker["uncertain"]),
        },
        "stickers": stickers,
    }


class DatasetStore:
    """Writes confirmed scans to disk and keeps running statistics about them."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._lock = threading.Lock()
        self._stats = self._empty_stats()
        for path in sorted(self.scans_dir.glob("*/scan.json")):
            if path.parent.name.startswith(".tmp-"):
                continue  # left over from a crash; never counted
            try:
                self._count(json.loads(path.read_text("utf-8")))
            except (OSError, ValueError, KeyError, TypeError) as exc:
                log.warning("Skipping unreadable dataset scan %s: %s", path, exc)

    @property
    def scans_dir(self) -> Path:
        return self.root / "scans"

    # ------------------------------------------------------------------
    def save(self, record: Mapping[str, Any], crops: Mapping[str, Sequence[np.ndarray]]) -> str:
        """Write one scan (54 PNGs + scan.json). Returns its id."""
        scan_id = str(record["id"])
        final = self.scans_dir / scan_id
        temp = self.scans_dir / f".tmp-{scan_id}"
        with self._lock:
            if final.exists():
                raise FileExistsError(f"Dataset scan {scan_id} already exists")
            temp.mkdir(parents=True, exist_ok=False)
            try:
                for sticker in record["stickers"]:
                    image = crops[sticker["face"]][sticker["index"]]
                    ok, png = cv2.imencode(".png", image)
                    if not ok:
                        raise OSError(f"Could not encode {sticker['file']}")
                    # imencode + write_bytes also works for non-ASCII Windows paths.
                    (temp / sticker["file"]).write_bytes(png.tobytes())
                (temp / "scan.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
                temp.rename(final)
            except BaseException:
                shutil.rmtree(temp, ignore_errors=True)
                raise
            self._count(record)
        return scan_id

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._stats)

    # ------------------------------------------------------------------
    @staticmethod
    def _empty_stats() -> Dict[str, Any]:
        return {
            "scans": 0,
            "stickers": 0,
            "corrected": 0,
            "uncertain": 0,
            "byLighting": {key: 0 for key in LIGHTING_OPTIONS},
            "byColor": {code: 0 for code in COLOR_CODES},
            "lastScanId": None,
        }

    def _count(self, record: Mapping[str, Any]) -> None:
        """Add one scan to the running statistics (caller holds the lock or is __init__)."""
        stats = self._stats
        stats["scans"] += 1
        stats["byLighting"][record["lighting"]] = stats["byLighting"].get(record["lighting"], 0) + 1
        for sticker in record["stickers"]:
            stats["stickers"] += 1
            stats["corrected"] += 1 if sticker["corrected"] else 0
            stats["uncertain"] += 1 if sticker.get("uncertain") else 0
            stats["byColor"][sticker["label"]] = stats["byColor"].get(sticker["label"], 0) + 1
        stats["lastScanId"] = record["id"]
