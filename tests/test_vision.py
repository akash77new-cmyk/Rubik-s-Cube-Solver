"""HSV detection on a synthetic cube face, and the OpenCV overlays."""

import cv2
import numpy as np
import pytest

from backend.core.moves import Move
from backend.vision.detector import FaceDetector
from backend.vision.overlay import COLOR_BGR, OverlayRenderer

WIDTH, HEIGHT, SPACING = 960, 720, 96


def _blank_frame() -> np.ndarray:
    return np.full((HEIGHT, WIDTH, 3), 28, np.uint8)


def test_synthetic_face_is_read_correctly_and_stably():
    codes = ["R", "G", "B", "W", "Y", "O", "G", "R", "B"]
    frame = _blank_frame()
    for index, code in enumerate(codes):
        row, col = divmod(index, 3)
        x = WIDTH // 2 + (col - 1) * SPACING
        y = HEIGHT // 2 + (row - 1) * SPACING
        cv2.rectangle(frame, (x - 42, y - 42), (x + 42, y + 42), COLOR_BGR[code], -1)

    detector = FaceDetector(spacing=SPACING, sample_radius=10)
    for _ in range(6):  # fill the stability window
        result = detector.detect(frame.copy())

    assert result.colors == codes
    assert result.stable


@pytest.fixture
def overlay_setup():
    frame = _blank_frame()
    result = FaceDetector(spacing=SPACING).detect(frame)
    return frame, result, OverlayRenderer("neon")


def test_hud_renders(overlay_setup):
    frame, result, overlay = overlay_setup
    for draw in (
        lambda f: overlay.draw_detection(f, result),
        lambda f: overlay.draw_scan_banner(f, "F", ["U", "R"], result),
        lambda f: overlay.draw_hud(f, 30.0, "scan"),
    ):
        drawn = draw(frame.copy())
        assert drawn.shape == frame.shape
        assert not np.array_equal(drawn, frame), "nothing was drawn"


@pytest.mark.parametrize("face", list("URFDLB"))
@pytest.mark.parametrize("modifier", ["", "'", "2"])
def test_all_18_move_arrows_render(overlay_setup, face, modifier):
    frame, _, overlay = overlay_setup
    drawn = overlay.draw_move(frame.copy(), Move(face, modifier), index=0, total=20)
    assert not np.array_equal(drawn, frame), "no arrow was drawn"


def test_turn_back_hint_renders(overlay_setup):
    frame, _, overlay = overlay_setup
    drawn = overlay.draw_move(frame.copy(), Move("B"), turn_back=True)
    assert not np.array_equal(drawn, frame), "no hint was drawn"
