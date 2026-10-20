"""Colour ranking: rank() scores every colour; classify() must not change."""

import math
import random

import pytest

from backend.core.color import (
    BUILTIN_PRESETS,
    UNCERTAIN_NO_RANGE,
    UNCERTAIN_TWO_RANGES,
    ColorProfile,
    uncertainty,
)
from backend.core.cube import COLOR_CODES


def classify_before_phase_2(profile: ColorProfile, h: float, s: float, v: float):
    """The classify() algorithm exactly as it was before Phase 2 (the reference)."""
    best_code, best_score = None, -1.0
    for code, rng in profile.ranges.items():
        if rng.contains(h, s, v):
            score = rng.score(h, s, v)
            if score > best_score:
                best_score, best_code = score, code
    if best_code is not None:
        return best_code, round(0.55 + 0.45 * best_score, 3)
    nearest = min(profile.ranges, key=lambda code: profile.ranges[code].distance(h, s, v))
    distance = profile.ranges[nearest].distance(h, s, v)
    return nearest, round(max(0.05, min(0.5, 0.5 * math.exp(-1.8 * distance))), 3)


@pytest.mark.parametrize("preset", list(BUILTIN_PRESETS))
def test_classify_is_unchanged(preset):
    """20,000 random HSV samples per preset: same colour and confidence as before."""
    profile = ColorProfile.preset(preset)
    rng = random.Random(42)
    for _ in range(20_000):
        h, s, v = rng.uniform(0, 179), rng.uniform(0, 255), rng.uniform(0, 255)
        assert profile.classify(h, s, v) == classify_before_phase_2(profile, h, s, v)


def test_rank_lists_every_colour_once_best_first():
    profile = ColorProfile.preset("default")
    ranking = profile.rank(110, 200, 180)  # a clear blue
    assert sorted(score.code for score in ranking) == sorted(COLOR_CODES)
    assert ranking[0].code == "B" and ranking[0].in_range
    assert (ranking[0].code, ranking[0].confidence) == profile.classify(110, 200, 180)
    # In-range colours come before out-of-range ones.
    flags = [score.in_range for score in ranking]
    assert flags == sorted(flags, reverse=True)


def test_uncertainty_reasons():
    profile = ColorProfile.preset("default")
    assert uncertainty(profile.rank(110, 200, 180)) is None            # inside blue only
    assert uncertainty(profile.rank(110, 200, 20)) == UNCERTAIN_NO_RANGE  # too dark for any box
    # Hue 4 is the shared edge of the default red (170-4) and orange (4-19) boxes.
    ranking = profile.rank(4, 200, 200)
    assert {ranking[0].code, ranking[1].code} == {"R", "O"}
    assert uncertainty(ranking) == UNCERTAIN_TWO_RANGES


def test_color_score_to_dict():
    score = ColorProfile.preset("default").rank(110, 200, 180)[0]
    assert score.to_dict() == {"color": "B", "confidence": score.confidence, "inRange": True}
