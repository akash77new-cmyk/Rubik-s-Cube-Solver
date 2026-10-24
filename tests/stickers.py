"""Synthetic sticker crops and dataset scans for the Phase 11 tests.

A crop is a 32 x 32 BGR image of one sticker under a simulated light: an overall
brightness, a colour cast (a warm bulb makes everything more orange), a soft
shading gradient and camera noise. ``write_scan`` saves 54 of them in the exact
layout of ``backend/services/dataset.py``, so ``ml/train.py`` can't tell them apart
from real scans.
"""

import json

import cv2
import numpy as np

from backend.core.color import ColorProfile
from backend.core.cube import COLOR_CODES, FACE_ORDER

#: A typical sticker colour (BGR) in neutral light.
BASE_BGR = {
    "W": (225, 228, 230),
    "Y": (40, 215, 235),
    "O": (30, 120, 245),
    "R": (45, 35, 190),
    "G": (75, 175, 35),
    "B": (185, 85, 15),
}

#: name -> (brightness, (blue, green, red) colour gains)
LIGHTS = {
    "daylight": (1.0, (1.0, 1.0, 1.0)),
    "warm": (0.9, (0.72, 0.95, 1.12)),
    "cool": (0.95, (1.12, 1.0, 0.86)),
    "dim": (0.55, (0.95, 1.0, 1.0)),
    "glare": (1.25, (1.0, 1.0, 1.0)),
}


def make_crop(code, light="daylight", rng=None, size=32):
    """One synthetic sticker crop (uint8 BGR)."""
    rng = rng or np.random.default_rng(0)
    brightness, gains = LIGHTS[light]
    colour = np.array(BASE_BGR[code], np.float32) * np.array(gains, np.float32) * brightness
    colour *= rng.uniform(0.92, 1.08)  # every scan's light is a little different
    ys, xs = np.mgrid[0:size, 0:size].astype(np.float32) / size
    angle = rng.uniform(0, 2 * np.pi)
    shading = 1.0 + 0.12 * ((xs - 0.5) * np.cos(angle) + (ys - 0.5) * np.sin(angle))
    image = colour[None, None, :] * shading[:, :, None]
    image += rng.normal(0, 6, image.shape)
    return np.clip(image, 0, 255).astype(np.uint8)


def hsv_reading(crop, profile=None):
    """What the HSV detector would read for this crop: (colour, confidence, best 3)."""
    profile = profile or ColorProfile.preset("default")
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV).reshape(-1, 3)
    h, s, v = (float(np.median(hsv[:, i])) for i in range(3))
    ranking = profile.rank(h, s, v)
    return ranking[0].code, ranking[0].confidence, [r.to_dict() for r in ranking[:3]], [int(h), int(s), int(v)]


def write_scan(root, scan_id, light="daylight", seed=0):
    """Save one synthetic scan (54 crops + scan.json) under ``root/scans/<scan_id>/``."""
    rng = np.random.default_rng(seed)
    folder = root / "scans" / scan_id
    folder.mkdir(parents=True)
    labels = [code for code in COLOR_CODES for _ in range(9)]
    rng.shuffle(labels)
    stickers = []
    for number, (face, index) in enumerate((f, i) for f in FACE_ORDER for i in range(9)):
        label = labels[number]
        crop = make_crop(label, light, rng)
        cv2.imwrite(str(folder / f"{face}{index}.png"), crop)
        predicted, confidence, alternatives, hsv = hsv_reading(crop)
        stickers.append({
            "file": f"{face}{index}.png", "face": face, "index": index, "label": label,
            "predicted": predicted, "hsvPredicted": predicted, "corrected": predicted != label,
            "confidence": confidence, "alternatives": alternatives, "hsv": hsv, "uncertain": None,
        })
    record = {
        "schema": 1, "id": scan_id, "createdAt": "2026-10-24T00:00:00Z", "lighting": "other",
        "profile": "default", "colorModel": "hsv", "camera": {}, "detector": {"cropSize": 32},
        "centers": {}, "counts": {"stickers": 54, "corrected": sum(s["corrected"] for s in stickers), "uncertain": 0},
        "stickers": stickers,
    }
    (folder / "scan.json").write_text(json.dumps(record), encoding="utf-8")
    return folder


def write_dataset(root, count=6, seed=0):
    """``count`` synthetic scans, cycling through the lights."""
    lights = list(LIGHTS)
    for number in range(count):
        write_scan(root, f"20261024-0000{number:02d}-synth", lights[number % len(lights)], seed + number)
    return root
