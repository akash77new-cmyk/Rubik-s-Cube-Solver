"""Dataset collection: a confirmed scan becomes 54 labelled sticker crops on disk.

These tests drive the real SolveSession with synthetic camera frames:
_process_frame() runs the real detector, capture_face() captures the current face.
No camera, server or solver search is involved.
"""

import json

import cv2
import pytest

from backend.core.cube import FACE_ORDER, CubeState, random_scramble
from backend.core.solver import SolverEngine
from backend.services.dataset import LIGHTING_OPTIONS, DatasetStore, build_scan_record
from backend.services.logbus import LogBus
from backend.services.session import SolveSession
from tests.storage import memory_stores
from tests.synthetic import synthetic_face


def make_session(tmp_path, with_dataset=True):
    events = []
    session = SolveSession(
        **memory_stores(),
        solver=SolverEngine(),
        logs=LogBus(),
        publish_event=lambda event, data: events.append((event, data)),
        publish_frame=lambda jpeg: None,
        dataset=DatasetStore(tmp_path / "dataset") if with_dataset else None,
    )
    return session, events


def scan(session, cube, paint=None):
    """Show each face of ``cube`` to the session. ``paint`` overrides stickers: {(face, i): code}."""
    for face in FACE_ORDER:
        colors = cube.face(face)
        for (painted_face, index), code in (paint or {}).items():
            if painted_face == face:
                colors[index] = code
        session._process_frame(synthetic_face(colors))
        assert session.capture_face(face)["ok"]


@pytest.fixture
def cube():
    return CubeState.solved().apply_sequence(random_scramble(20, seed=11))


def test_capture_keeps_per_sticker_data(tmp_path, cube):
    session, _ = make_session(tmp_path)
    scan(session, cube)
    snapshot = session.snapshot()
    json.dumps(snapshot)  # everything broadcast must be JSON (crops are not in it)
    stickers = snapshot["scan"]["faces"]["U"]["stickers"]
    assert len(stickers) == 9
    assert [s["color"] for s in stickers] == cube.face("U")
    assert all(len(s["alternatives"]) == 3 and "uncertain" in s for s in stickers)


def test_confirmed_scan_is_saved_as_54_labelled_crops(tmp_path, cube):
    session, events = make_session(tmp_path)
    scan(session, cube)
    state = session.dataset_state()
    assert state["enabled"] and state["canSave"] and state["reason"] is None

    result = session.save_to_dataset("daylight")
    assert result["ok"] and result["corrected"] == 0

    folder = tmp_path / "dataset" / "scans" / result["id"]
    record = json.loads((folder / "scan.json").read_text("utf-8"))
    assert record["lighting"] == "daylight" and record["counts"]["stickers"] == 54
    assert len(list(folder.glob("*.png"))) == 54
    for sticker in record["stickers"]:
        assert sticker["label"] == cube.face(sticker["face"])[sticker["index"]]
        assert sticker["predicted"] == sticker["label"] and not sticker["corrected"]
        image = cv2.imread(str(folder / sticker["file"]))
        assert image is not None and image.shape == (32, 32, 3)

    stats = session.dataset_state()["stats"]
    assert stats["scans"] == 1 and stats["stickers"] == 54
    assert set(stats["byColor"].values()) == {9}  # every scan is balanced
    assert stats["byLighting"]["daylight"] == 1
    assert any(event == "dataset:saved" for event, _ in events)


def test_a_corrected_sticker_is_labelled_with_the_fix(tmp_path, cube):
    session, _ = make_session(tmp_path)
    true_color = cube.face("F")[0]
    wrong_color = next(c for c in "WYROGB" if c != true_color)
    scan(session, cube, paint={("F", 0): wrong_color})
    assert not session.dataset_state()["canSave"]  # the cube is invalid until fixed

    session.set_sticker("F", 0, true_color)
    result = session.save_to_dataset("dim")
    assert result["ok"] and result["corrected"] == 1
    record = json.loads(
        (tmp_path / "dataset" / "scans" / result["id"] / "scan.json").read_text("utf-8")
    )
    fixed = next(s for s in record["stickers"] if s["file"] == "F0.png")
    assert fixed == {**fixed, "label": true_color, "predicted": wrong_color, "corrected": True}


def test_saving_is_blocked_when_it_would_store_wrong_or_duplicate_data(tmp_path, cube):
    session, _ = make_session(tmp_path)
    assert "Scan all six faces" in session.dataset_state()["reason"]
    assert not session.save_to_dataset("daylight")["ok"]

    scan(session, cube)
    assert not session.save_to_dataset("sunset")["ok"]  # unknown lighting tag
    assert session.save_to_dataset("glare")["ok"]
    assert "already saved" in session.save_to_dataset("glare")["error"]

    session.reset_scan()
    scan(session, cube)
    session.apply_moves("R")  # the cube no longer matches the camera images
    assert "Scan all six faces" in session.dataset_state()["reason"]

    session.reset_scan()
    scan(session, cube)
    session.scramble()
    assert not session.dataset_state()["canSave"]


def test_disabled_dataset_never_saves(tmp_path, cube):
    session, _ = make_session(tmp_path, with_dataset=False)
    scan(session, cube)
    state = session.dataset_state()
    assert not state["enabled"] and state["stats"] is None
    assert not session.save_to_dataset("daylight")["ok"]


def test_store_reloads_its_statistics_and_ignores_unfinished_scans(tmp_path, cube):
    session, _ = make_session(tmp_path)
    scan(session, cube)
    session.save_to_dataset("warm")
    (tmp_path / "dataset" / "scans" / ".tmp-crashed").mkdir()
    (tmp_path / "dataset" / "scans" / ".tmp-crashed" / "scan.json").write_text("{}")
    assert DatasetStore(tmp_path / "dataset").stats() == session.dataset_state()["stats"]


def test_build_scan_record_rejects_bad_input():
    labels = {face: ["W"] * 9 for face in FACE_ORDER}
    readings = {face: [{"color": "W", "confidence": 0.9}] * 9 for face in FACE_ORDER}
    common = dict(profile="default", camera={}, detector={})
    with pytest.raises(ValueError):
        build_scan_record("sunset", labels, readings, **common)
    with pytest.raises(ValueError):
        build_scan_record("daylight", {**labels, "U": ["W"] * 8}, readings, **common)
    with pytest.raises(ValueError):
        build_scan_record("daylight", {**labels, "U": ["X"] * 9}, readings, **common)
    record = build_scan_record("daylight", labels, readings, **common)
    assert set(LIGHTING_OPTIONS) >= {record["lighting"]} and len(record["stickers"]) == 54
