"""HSV detection on a synthetic cube face, and the OpenCV overlays."""

import cv2
import numpy as np
import pytest

from backend.core.moves import Move
from backend.vision.detector import CROP_SIZE, FaceDetector
from backend.vision.overlay import COLOR_BGR, OverlayRenderer
from tests.synthetic import synthetic_face

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


@pytest.mark.parametrize(
    "notation, direction",
    [("U", "left"), ("U'", "right"), ("D", "right"), ("D'", "left"),
     ("R", "up"), ("R'", "down"), ("L", "down"), ("L'", "up")],
)
def test_straight_arrows_point_the_way_the_layer_moves(notation, direction):
    start, end = OverlayRenderer.linear_arrow_ends(Move.parse(notation), (480, 360), 100)
    dx, dy = end[0] - start[0], end[1] - start[1]
    assert {"left": dx < 0, "right": dx > 0, "up": dy < 0, "down": dy > 0}[direction]


def test_turn_back_hint_renders(overlay_setup):
    frame, _, overlay = overlay_setup
    drawn = overlay.draw_move(frame.copy(), Move("B"), turn_back=True)
    assert not np.array_equal(drawn, frame), "no hint was drawn"


def test_each_reading_has_a_crop_of_its_sticker():
    codes = ["R", "G", "B", "W", "Y", "O", "G", "R", "B"]
    result = FaceDetector(spacing=SPACING).detect(synthetic_face(codes))
    assert len(result.crops) == len(result.readings) == 9
    for code, crop in zip(codes, result.crops):
        assert crop.shape == (CROP_SIZE, CROP_SIZE, 3) and crop.dtype == np.uint8
        # The crop shows the sticker itself: its mean colour is the painted colour.
        mean = crop.reshape(-1, 3).mean(axis=0)
        assert np.abs(mean - np.array(COLOR_BGR[code])).max() < 3


def test_crops_come_from_the_raw_frame_and_are_not_broadcast():
    frame = synthetic_face(["W"] * 9)
    result = FaceDetector(spacing=SPACING).detect(frame)
    frame[:] = 0  # drawing on the frame afterwards (like the overlay) must not change crops
    assert result.crops[0].mean() > 200
    payload = result.to_dict()
    assert "crops" not in payload


def test_readings_carry_the_best_three_colours():
    result = FaceDetector(spacing=SPACING).detect(synthetic_face(["B"] * 9))
    reading = result.readings[0].to_dict()
    assert [a["color"] for a in reading["alternatives"]][0] == "B"
    assert len(reading["alternatives"]) == 3
    assert reading["alternatives"][0]["confidence"] == reading["confidence"]
    assert reading["uncertain"] is None
