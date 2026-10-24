"""ml/train.py on a small synthetic dataset (Phase 11). Skipped where PyTorch isn't installed
(CI and the app don't need it; install it with requirements-ml.txt)."""

import json

import pytest

pytest.importorskip("torch")
pytest.importorskip("onnx")

from backend.vision.classifier import META_FILE, MODEL_FILE, load_color_model  # noqa: E402
from ml import train  # noqa: E402
from tests.stickers import write_dataset  # noqa: E402


def test_split_keeps_whole_scans_apart(tmp_path):
    scans = train.load_scans(write_dataset(tmp_path, count=5))
    assert len(scans) == 5 and scans[0].images.shape == (54, 32, 32, 3)
    training, test = train.split_scans(scans, 1, seed=0)
    assert len(training) == 4 and len(test) == 1
    assert not {s.id for s in training} & {s.id for s in test}
    assert train.split_scans(scans, 1, seed=0)[1][0].id == test[0].id  # the same split every run


def test_training_exports_a_model_the_app_can_load(tmp_path):
    data = write_dataset(tmp_path / "data", count=4)
    out, report = tmp_path / "models", tmp_path / "classifier.md"
    code = train.main(["--data", str(data), "--out", str(out), "--report", str(report),
                       "--epochs", "3", "--test-scans", "1"])
    assert code == 0
    assert (out / MODEL_FILE).stat().st_size > 1000
    meta = json.loads((out / META_FILE).read_text("utf-8"))
    assert meta["classes"] == list(train.CLASSES)
    assert meta["test"]["stickers"] == 54 and meta["train"]["scans"] == 3
    assert meta["onnxMaxDifference"] < 1e-3  # OpenCV and PyTorch agree
    classifier, status = load_color_model("cnn", out)
    assert classifier is not None and status["active"] == "cnn"
    assert "| CNN |" in report.read_text("utf-8")


def test_too_few_scans_is_a_clear_error(tmp_path, capsys):
    data = write_dataset(tmp_path, count=2)
    assert train.main(["--data", str(data), "--out", str(tmp_path / "m"), "--report", str(tmp_path / "r.md")]) == 1
    assert "at least 3" in capsys.readouterr().out
