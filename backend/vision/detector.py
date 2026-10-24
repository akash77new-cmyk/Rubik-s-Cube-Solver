"""HSV sticker detection for one visible cube face.

Pipeline per frame::

    BGR frame
      -> bilateral blur            (kill sensor noise, keep sticker edges crisp)
      -> BGR2HSV
      -> 9 patch samples on a 3x3 grid
      -> robust per-patch HSV (circular median hue, median S/V)
      -> a 32x32 crop of each sticker from the raw frame (training data, Phase 2)
      -> colour, confidence, runner-up colours, uncertain?  from ColorProfile.rank (HSV),
         or from the trained CNN on the crops when it is active (Phase 11)
      -> temporal stability check  (N identical consecutive reads)

Sampling a *patch* and taking the median - rather than the single centre pixel
the original script used - is what makes detection survive specular highlights
and webcam noise. The temporal stability check is what allows hands-free
auto-capture.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from backend.core.color import HUE_MAX, ColorProfile, ColorScore, uncertainty
from backend.core.cube import COLOR_NAMES
from backend.vision.classifier import StickerClassifier, cnn_uncertainty

#: Side length, in pixels, of the sticker crops saved for the Phase 11 classifier.
CROP_SIZE = 32
#: Crop window width as a fraction of the grid spacing (the sticker pitch). 0.6 keeps
#: the window inside the sticker, away from the black gaps around it.
CROP_FRACTION = 0.6


@dataclass
class StickerReading:
    """One of the nine sampled cells."""

    index: int
    row: int
    col: int
    x: int
    y: int
    hsv: Tuple[int, int, int]
    color: str
    confidence: float
    #: The best three colours, best first (``alternatives[0]`` is ``color``).
    alternatives: Tuple[ColorScore, ...] = ()
    #: ``None``, or why the reading is doubtful (see ``backend.core.color``).
    uncertain: Optional[str] = None
    #: The HSV detector's colour. The same as ``color`` unless the CNN is active; kept so
    #: the dataset can always measure the HSV baseline (Phase 11).
    hsv_color: Optional[str] = None

    def to_dict(self) -> Dict[str, object]:
        return {
            "index": self.index,
            "row": self.row,
            "col": self.col,
            "x": self.x,
            "y": self.y,
            "hsv": list(self.hsv),
            "color": self.color,
            "colorName": COLOR_NAMES.get(self.color, self.color),
            "confidence": self.confidence,
            "alternatives": [score.to_dict() for score in self.alternatives],
            "uncertain": self.uncertain,
            "hsvColor": self.hsv_color or self.color,
        }


@dataclass
class DetectionResult:
    """Everything detected in a single frame."""

    readings: List[StickerReading] = field(default_factory=list)
    bbox: Optional[Tuple[int, int, int, int]] = None
    quad: Optional[List[Tuple[int, int]]] = None
    stable: bool = False
    stability: float = 0.0
    timestamp: float = field(default_factory=time.time)
    #: One CROP_SIZE x CROP_SIZE BGR image per reading, in the same order.
    #: Kept out of to_dict(): images are saved to disk, never broadcast.
    crops: List[np.ndarray] = field(default_factory=list, repr=False)

    @property
    def colors(self) -> List[str]:
        return [r.color for r in self.readings]

    @property
    def mean_confidence(self) -> float:
        if not self.readings:
            return 0.0
        return round(sum(r.confidence for r in self.readings) / len(self.readings), 3)

    @property
    def min_confidence(self) -> float:
        return round(min((r.confidence for r in self.readings), default=0.0), 3)

    def to_dict(self) -> Dict[str, object]:
        return {
            "readings": [r.to_dict() for r in self.readings],
            "colors": self.colors,
            "meanConfidence": self.mean_confidence,
            "minConfidence": self.min_confidence,
            "bbox": list(self.bbox) if self.bbox else None,
            "quad": [list(p) for p in self.quad] if self.quad else None,
            "stable": self.stable,
            "stability": round(self.stability, 3),
            "timestamp": self.timestamp,
        }


def _circular_median_hue(hues: np.ndarray) -> float:
    """Median hue that behaves correctly across the 179/0 wrap (red stickers)."""
    if hues.size == 0:
        return 0.0
    angles = hues.astype(np.float32) * (2 * np.pi / (HUE_MAX + 1))
    mean_angle = np.arctan2(np.sin(angles).mean(), np.cos(angles).mean())
    # Rotate samples so the cluster sits around 0, take the median, rotate back.
    centred = np.angle(np.exp(1j * (angles - mean_angle)))
    median = float(np.median(centred)) + float(mean_angle)
    hue = (median / (2 * np.pi)) * (HUE_MAX + 1)
    return float(hue % (HUE_MAX + 1))


class FaceDetector:
    """Samples a 3x3 grid from the centre of the frame and classifies it."""

    def __init__(
        self,
        profile: Optional[ColorProfile] = None,
        spacing: int = 96,
        sample_radius: int = 10,
        offset_y: int = 0,
        stability_window: int = 6,
        classifier: Optional[StickerClassifier] = None,
    ) -> None:
        self.profile = profile or ColorProfile.preset("default")
        #: The trained CNN (Phase 11), or None: then HSV decides the colours.
        self.classifier = classifier
        self.spacing = spacing
        self.sample_radius = sample_radius
        self.offset_y = offset_y
        self._history: Deque[Tuple[str, ...]] = deque(maxlen=stability_window)

    # ------------------------------------------------------------------
    def configure(
        self,
        profile: Optional[ColorProfile] = None,
        spacing: Optional[int] = None,
        sample_radius: Optional[int] = None,
        offset_y: Optional[int] = None,
    ) -> None:
        if profile is not None:
            self.profile = profile
        if spacing is not None:
            self.spacing = max(24, int(spacing))
        if sample_radius is not None:
            self.sample_radius = max(2, int(sample_radius))
        if offset_y is not None:
            self.offset_y = int(offset_y)
        self._history.clear()

    def reset_stability(self) -> None:
        self._history.clear()

    # ------------------------------------------------------------------
    def grid_points(
        self, frame_shape: Sequence[int]
    ) -> List[Tuple[int, int, int, int, int]]:
        """Sample grid as ``(index, row, col, x, y)`` in pixel coordinates."""
        height, width = frame_shape[0], frame_shape[1]
        cx, cy = width // 2, height // 2 + self.offset_y
        points: List[Tuple[int, int, int, int, int]] = []
        for row in range(3):
            for col in range(3):
                x = int(cx + (col - 1) * self.spacing)
                y = int(cy + (row - 1) * self.spacing)
                points.append((row * 3 + col, row, col, x, y))
        return points

    # ------------------------------------------------------------------
    def detect(self, frame_bgr: np.ndarray) -> DetectionResult:
        """Run the full detection pipeline on one BGR frame."""
        height, width = frame_bgr.shape[:2]
        # Bilateral filtering smooths sticker interiors without bleeding colour
        # across the black gaps between them.
        smoothed = cv2.bilateralFilter(frame_bgr, 7, 60, 60)
        hsv = cv2.cvtColor(smoothed, cv2.COLOR_BGR2HSV)

        cx, cy = width // 2, height // 2 + self.offset_y
        radius = self.sample_radius
        cells = []  # (row, col, x, y, (h, s, v), HSV ranking)
        crops: List[np.ndarray] = []
        for row in range(3):
            for col in range(3):
                x = int(cx + (col - 1) * self.spacing)
                y = int(cy + (row - 1) * self.spacing)
                x = int(np.clip(x, radius, width - radius - 1))
                y = int(np.clip(y, radius, height - radius - 1))

                patch = hsv[y - radius : y + radius + 1, x - radius : x + radius + 1]
                if patch.size == 0:
                    continue
                flat = patch.reshape(-1, 3)
                h = _circular_median_hue(flat[:, 0])
                s = float(np.median(flat[:, 1]))
                v = float(np.median(flat[:, 2]))
                cells.append((row, col, x, y, (h, s, v), self.profile.rank(h, s, v)))
                # Crop from the raw frame: the overlay is drawn later, and the
                # classifier should learn from what the camera really saw.
                crops.append(self._crop(frame_bgr, x, y))

        # The CNN, when active, decides from the crops (one batch for all nine stickers).
        cnn = self.classifier.rank(crops) if self.classifier is not None and crops else None
        readings: List[StickerReading] = []
        for number, (row, col, x, y, (h, s, v), hsv_ranking) in enumerate(cells):
            ranking = cnn[number] if cnn is not None else hsv_ranking
            best = ranking[0]
            readings.append(
                StickerReading(
                    index=row * 3 + col,
                    row=row,
                    col=col,
                    x=x,
                    y=y,
                    hsv=(int(round(h)), int(round(s)), int(round(v))),
                    color=best.code,
                    confidence=best.confidence,
                    alternatives=tuple(ranking[:3]),
                    uncertain=cnn_uncertainty(ranking) if cnn is not None else uncertainty(ranking),
                    hsv_color=hsv_ranking[0].code,
                )
            )

        signature = tuple(r.color for r in readings)
        self._history.append(signature)
        matches = sum(1 for item in self._history if item == signature)
        stability = matches / self._history.maxlen if self._history.maxlen else 0.0
        stable = len(self._history) == self._history.maxlen and matches == len(
            self._history
        )

        quad = self._find_cube_quad(smoothed)
        bbox = self._grid_bbox(cx, cy)

        return DetectionResult(
            readings=readings,
            bbox=bbox,
            quad=quad,
            stable=stable,
            stability=stability,
            crops=crops,
        )

    # ------------------------------------------------------------------
    def _crop(self, frame_bgr: np.ndarray, x: int, y: int) -> np.ndarray:
        """A CROP_SIZE x CROP_SIZE colour image of the sticker centred at (x, y)."""
        half = max(self.sample_radius, int(self.spacing * CROP_FRACTION / 2))
        height, width = frame_bgr.shape[:2]
        x0, x1 = max(0, x - half), min(width, x + half + 1)
        y0, y1 = max(0, y - half), min(height, y + half + 1)
        return cv2.resize(
            frame_bgr[y0:y1, x0:x1], (CROP_SIZE, CROP_SIZE), interpolation=cv2.INTER_AREA
        )

    def _grid_bbox(self, cx: int, cy: int) -> Tuple[int, int, int, int]:
        half = int(self.spacing * 1.5)
        return (cx - half, cy - half, half * 2, half * 2)

    def _find_cube_quad(self, frame_bgr: np.ndarray) -> Optional[List[Tuple[int, int]]]:
        """Best-effort outline of the cube face, used for the on-screen contour."""
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 40, 120)
        edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)
        contours, _ = cv2.findContours(
            edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        if not contours:
            return None

        frame_area = frame_bgr.shape[0] * frame_bgr.shape[1]
        best: Optional[np.ndarray] = None
        best_area = 0.0
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < frame_area * 0.04 or area > frame_area * 0.9:
                continue
            perimeter = cv2.arcLength(contour, True)
            approx = cv2.approxPolyDP(contour, 0.04 * perimeter, True)
            if len(approx) != 4 or not cv2.isContourConvex(approx):
                continue
            x, y, w, h = cv2.boundingRect(approx)
            aspect = w / float(h) if h else 0
            if not 0.65 <= aspect <= 1.55:
                continue
            if area > best_area:
                best_area, best = area, approx

        if best is None:
            return None
        return [(int(p[0][0]), int(p[0][1])) for p in best]
