"""The trained colour classifier's runtime (Phase 11): loading, ranking, modes, the detector.

These tests need no PyTorch. They build a tiny ONNX model with the ``onnx`` package: the
average colour of the crop, then the nearest of six reference colours (a linear layer), the
colours tests/synthetic.py paints.
OpenCV runs it exactly as it runs the real CNN.
"""

import json

import numpy as np
import pytest

onnx = pytest.importorskip("onnx")
from onnx import TensorProto, helper, numpy_helper  # noqa: E402

from backend.config import ConfigError, read_runtime_config  # noqa: E402
from backend.core.cube import COLOR_CODES  # noqa: E402
from backend.services.dataset import build_scan_record  # noqa: E402
from backend.vision.classifier import (  # noqa: E402
    META_FILE,
    MODEL_FILE,
    UNCERTAIN_LOW_CONFIDENCE,
    StickerClassifier,
    load_color_model,
)
from backend.vision.detector import FaceDetector  # noqa: E402
from backend.vision.overlay import COLOR_BGR  # noqa: E402
from tests.synthetic import synthetic_face  # noqa: E402

MEAN, STD = 0.5, 0.25


def write_model(folder, beats_hsv=True, sharpness=8.0, schema=1):
    """A nearest-reference-colour model in ONNX, plus its metadata, in ``folder``."""
    folder.mkdir(parents=True, exist_ok=True)
    centres = np.array([(np.array(COLOR_BGR[c]) / 255.0 - MEAN) / STD for c in COLOR_CODES], np.float32)
    # -|x - c|^2 = 2 c.x - |c|^2 - |x|^2, and |x|^2 is the same for every colour: a linear layer.
    weights = (2 * sharpness * centres).astype(np.float32)  # (6, 3)
    bias = (-sharpness * (centres**2).sum(axis=1)).astype(np.float32)
    graph = helper.make_graph(
        [
            helper.make_node("GlobalAveragePool", ["crops"], ["pooled"]),
            helper.make_node("Flatten", ["pooled"], ["flat"]),
            helper.make_node("Gemm", ["flat", "W", "b"], ["logits"], transB=1),
        ],
        "nearest-colour",
        [helper.make_tensor_value_info("crops", TensorProto.FLOAT, ["n", 3, 32, 32])],
        [helper.make_tensor_value_info("logits", TensorProto.FLOAT, ["n", 6])],
        [numpy_helper.from_array(weights, "W"), numpy_helper.from_array(bias, "b")],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    model.ir_version = 7
    (folder / MODEL_FILE).write_bytes(model.SerializeToString())
    meta = {
        "schema": schema,
        "classes": list(COLOR_CODES),
        "input": {"size": 32, "order": "BGR", "mean": MEAN, "std": STD},
        "trainedAt": "2026-10-24 00:00 UTC",
        "test": {"scans": 2, "cnnAccuracy": 0.99, "hsvAccuracy": 0.95, "beatsHsv": beats_hsv},
    }
    (folder / META_FILE).write_text(json.dumps(meta), encoding="utf-8")
    return folder


def test_the_classifier_ranks_crops_with_probabilities(tmp_path):
    classifier = StickerClassifier.load(write_model(tmp_path / "model"))
    rng = np.random.default_rng(3)
    crops = [
        np.clip(np.full((32, 32, 3), COLOR_BGR[code], np.float32) + rng.normal(0, 8, (32, 32, 3)), 0, 255).astype(np.uint8)
        for code in COLOR_CODES
    ]
    probabilities = classifier.probabilities(crops)
    assert probabilities.shape == (6, 6)
    assert np.allclose(probabilities.sum(axis=1), 1.0, atol=1e-5)
    rankings = classifier.rank(crops)
    assert [ranking[0].code for ranking in rankings] == list(COLOR_CODES)
    for ranking in rankings:
        assert len(ranking) == 6 and ranking[0].confidence >= ranking[1].confidence
    assert classifier.probabilities([]).shape == (0, 6)


def test_the_colour_model_modes(tmp_path):
    good = write_model(tmp_path / "good")
    classifier, status = load_color_model("auto", good)
    assert classifier is not None and status["active"] == "cnn" and status["model"]["beatsHsv"]

    classifier, status = load_color_model("hsv", good)
    assert classifier is None and status["active"] == "hsv"

    weak = write_model(tmp_path / "weak", beats_hsv=False)
    classifier, status = load_color_model("auto", weak)
    assert classifier is None and "less accurate than HSV" in status["reason"]
    classifier, status = load_color_model("cnn", weak)  # forced, for experiments
    assert classifier is not None and status["active"] == "cnn"

    classifier, status = load_color_model("auto", tmp_path / "missing")
    assert classifier is None and status["reason"].startswith("no usable trained model")

    old = write_model(tmp_path / "old", schema=0)
    classifier, status = load_color_model("cnn", old)
    assert classifier is None and "schema" in status["reason"]


def test_the_detector_reads_colours_with_the_cnn(tmp_path):
    codes = ["W", "Y", "R", "O", "G", "B", "W", "Y", "R"]
    face = synthetic_face(codes)
    detector = FaceDetector(classifier=StickerClassifier.load(write_model(tmp_path / "model")))
    result = detector.detect(face)
    assert result.colors == codes
    reading = result.readings[0].to_dict()
    assert reading["hsvColor"] == "W"  # the HSV baseline is still recorded
    assert len(reading["alternatives"]) == 3
    assert all(r.uncertain is None for r in result.readings)

    # A blurry model (every colour almost equally likely) marks its readings as uncertain.
    blurry = FaceDetector(classifier=StickerClassifier.load(write_model(tmp_path / "blurry", sharpness=0.01)))
    assert all(r.uncertain == UNCERTAIN_LOW_CONFIDENCE for r in blurry.detect(face).readings)


def test_without_a_classifier_the_detector_is_unchanged():
    codes = ["W", "Y", "R", "O", "G", "B", "W", "Y", "R"]
    reading = FaceDetector().detect(synthetic_face(codes)).readings[2].to_dict()
    assert reading["color"] == reading["hsvColor"] == "R"


def test_the_dataset_keeps_the_hsv_baseline_and_the_model_name():
    readings, labels = {}, {}
    for face in "URFDLB":
        labels[face] = ["W"] * 9
        readings[face] = [{"color": "Y", "hsvColor": "W", "confidence": 0.9, "alternatives": []}] * 9
    record = build_scan_record("daylight", labels, readings, "default", {}, {}, color_model="cnn")
    assert record["colorModel"] == "cnn"
    sticker = record["stickers"][0]
    assert sticker["predicted"] == "Y" and sticker["hsvPredicted"] == "W" and sticker["corrected"]


def test_the_colour_model_setting():
    assert read_runtime_config({}).color_model == "auto"
    assert read_runtime_config({"CUBE_COLOR_MODEL": "HSV"}).color_model == "hsv"
    with pytest.raises(ConfigError):
        read_runtime_config({"CUBE_COLOR_MODEL": "best"})
