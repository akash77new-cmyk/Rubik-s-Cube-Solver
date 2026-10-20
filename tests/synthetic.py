"""Synthetic camera frames for tests: a cube face painted where the detector samples."""

import cv2
import numpy as np

from backend.vision.overlay import COLOR_BGR

WIDTH, HEIGHT, SPACING = 960, 720, 96


def synthetic_face(codes) -> np.ndarray:
    """A dark 960x720 frame with 9 solid stickers (colour codes in reading order)."""
    frame = np.full((HEIGHT, WIDTH, 3), 28, np.uint8)
    for index, code in enumerate(codes):
        row, col = divmod(index, 3)
        x = WIDTH // 2 + (col - 1) * SPACING
        y = HEIGHT // 2 + (row - 1) * SPACING
        cv2.rectangle(frame, (x - 42, y - 42), (x + 42, y + 42), COLOR_BGR[code], -1)
    return frame
