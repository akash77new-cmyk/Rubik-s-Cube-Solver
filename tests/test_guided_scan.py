"""Guided scanning through the real session: synthetic camera frames, real detector."""

import random

import cv2
import numpy as np
import pytest

from backend.config import SettingsStore
from backend.core.color import ProfileStore
from backend.core.cube import FACE_ORDER, CubeState, random_scramble
from backend.core.scanning import orientation_map, reorder
from backend.core.solver import SolverEngine
from backend.services.analytics import AnalyticsStore
from backend.services.dataset import DatasetStore
from backend.services.logbus import LogBus
from backend.services.session import SolveSession
from backend.vision.overlay import COLOR_BGR
from tests.synthetic import synthetic_face

STEADY = 6  # frames per face: the detector locks after 6 identical reads


@pytest.fixture
def cube():
    return CubeState.solved().apply_sequence(random_scramble(20, seed=21))


@pytest.fixture
def session(tmp_path):
    events = []
    s = SolveSession(
        settings=SettingsStore(tmp_path / "settings.json"),
        profiles=ProfileStore(tmp_path / "profiles.json"),
        solver=SolverEngine(),
        logs=LogBus(),
        analytics=AnalyticsStore(tmp_path / "history.json"),
        publish_event=lambda event, data: events.append((event, data)),
        publish_frame=lambda jpeg: None,
        dataset=DatasetStore(tmp_path / "dataset"),
    )
    s.events = events
    s.start_scan(open_camera=False)  # scan mode without opening a real camera
    return s


def show(session, colors, mirrored=False, frames=STEADY):
    """Hold one face (9 colour codes, as the camera should see it) in front of the camera."""
    frame = synthetic_face(colors)
    if mirrored:
        frame = cv2.flip(frame, 1)  # what a selfie-style preview does to the image
    for _ in range(frames):
        session._process_frame(frame.copy(), mirrored=mirrored)


def scanned_cube(session):
    return {face: session._scanned[face]["colors"] for face in FACE_ORDER}


def test_a_face_held_still_is_captured_once(session, cube):
    show(session, cube.face("U"), frames=30)  # one second of holding still
    assert list(session._scanned) == ["U"]


def test_faces_in_any_order_land_in_the_right_place(session, cube):
    order = random.Random(4).sample(FACE_ORDER, 6)
    for face in order:
        show(session, cube.face(face))
    assert scanned_cube(session) == {face: cube.face(face) for face in FACE_ORDER}
    assert session.snapshot()["validation"]["ok"]


def test_a_mirrored_camera_preview_is_read_correctly(session, cube):
    for face in FACE_ORDER:
        show(session, cube.face(face), mirrored=True)
    assert scanned_cube(session) == {face: cube.face(face) for face in FACE_ORDER}
    assert session.snapshot()["validation"]["ok"]


def test_a_face_held_rotated_is_repaired_and_saved_crops_match_labels(session, cube, tmp_path):
    for face in FACE_ORDER:
        colors = cube.face(face)
        if face == "R":
            colors = reorder(colors, orientation_map(2))  # held upside down
        show(session, colors)
    assert scanned_cube(session) == {face: cube.face(face) for face in FACE_ORDER}
    assert any(event == "scan:repaired" for event, _ in session.events)

    result = session.save_to_dataset("daylight")
    assert result["ok"]
    import json
    folder = tmp_path / "dataset" / "scans" / result["id"]
    for sticker in json.loads((folder / "scan.json").read_text("utf-8"))["stickers"]:
        image = cv2.imread(str(folder / sticker["file"]))
        mean = image.reshape(-1, 3).mean(axis=0)  # each crop shows its own label's colour
        assert np.abs(mean - np.array(COLOR_BGR[sticker["label"]])).max() < 3, sticker["file"]


def test_capture_button_uses_the_guide_when_the_centre_is_not_recognised(session, cube):
    show(session, cube.face("F"))
    assert list(session._scanned) == ["F"]
    colors = cube.face("R")
    colors[4] = "G"  # the centre reads as green, a face that is already scanned
    show(session, colors)
    assert list(session._scanned) == ["F"]  # auto-capture ignored it
    assert session.capture_face()["face"] == "R"  # the guide's next face
    assert session._scanned["R"]["colors"][4] == "R"  # centre set from the face's identity
    assert session._scanned["R"]["stickers"][4]["color"] == "G"  # what the camera saw is kept


def test_scan_state_lists_the_guide(session, cube):
    show(session, cube.face("F"))
    scan = session.snapshot()["scan"]
    assert [step["face"] for step in scan["steps"]] == ["F", "R", "B", "L", "U", "D"]
    assert scan["steps"][0]["done"] and not scan["steps"][1]["done"]
    assert scan["current"] == "R"
    assert scan["hint"] == "Turn the cube a quarter turn so red faces the camera."


def test_rescan_button_scans_that_face_again(session, cube):
    for face in FACE_ORDER:
        show(session, cube.face(face))
    assert session.snapshot()["mode"] == "scanned"
    session.handle_command("scan.face", {"face": "R"})
    scan = session.snapshot()["scan"]
    assert scan["current"] == "R" and session.snapshot()["mode"] == "scan"
    show(session, cube.face("R"))
    assert "R" in session._scanned and session.snapshot()["validation"]["ok"]
