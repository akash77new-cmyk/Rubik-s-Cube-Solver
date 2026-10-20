"""HSV colour segmentation model for cube stickers.

Each cube colour is described by an inclusive HSV box (OpenCV ranges: H 0-179,
S/V 0-255). Classification is a two-stage process:

1. **Range membership** - the classic HSV threshold test. Every colour whose box
   contains the sample is a candidate, scored by how *centred* the sample sits
   inside the box. A sample dead in the middle of a box scores 1.0.
2. **Nearest-box fallback** - if nothing matches (bad lighting, an unusual
   camera), the sample is assigned to the closest box in normalised HSV space
   with a deliberately low confidence so the UI can flag it.

Returning a confidence rather than a bare label is what lets the scanner refuse
low-quality reads instead of silently producing an unsolvable cube.

:meth:`ColorProfile.rank` scores *every* colour, best first. The detector keeps the
top three, so later code (the Phase 5 repair agent) knows the runner-up colours of
a doubtful sticker - e.g. "red 0.62, orange 0.58" - not just the winner.
"""

from __future__ import annotations

import json
import math
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from backend.config import PROFILES_FILE
from backend.core.cube import COLOR_CODES, COLOR_NAMES

HUE_MAX = 179
SAT_MAX = 255
VAL_MAX = 255

#: Why a sticker reading is uncertain (``None`` means it is not).
UNCERTAIN_NO_RANGE = "no_range"      # inside no colour's box: the colour is only the nearest guess
UNCERTAIN_TWO_RANGES = "two_ranges"  # inside two colours' boxes: both colours fit


@dataclass(frozen=True)
class ColorScore:
    """How well one HSV sample fits one colour.

    ``confidence`` uses the same scale as :meth:`ColorProfile.classify`:
    0.55-1.0 when the sample is inside the colour's box, 0.05-0.5 when outside.
    """

    code: str
    confidence: float
    in_range: bool

    def to_dict(self) -> Dict[str, object]:
        return {"color": self.code, "confidence": self.confidence, "inRange": self.in_range}


def uncertainty(ranking: Sequence[ColorScore]) -> Optional[str]:
    """``UNCERTAIN_NO_RANGE``, ``UNCERTAIN_TWO_RANGES`` or ``None`` for a ranked reading."""
    if not ranking or not ranking[0].in_range:
        return UNCERTAIN_NO_RANGE
    if len(ranking) > 1 and ranking[1].in_range:
        return UNCERTAIN_TWO_RANGES
    return None


@dataclass
class ColorRange:
    """Inclusive HSV box for one sticker colour."""

    h_min: int
    h_max: int
    s_min: int
    s_max: int
    v_min: int
    v_max: int
    #: Red straddles hue 0, so its box is the *union* of ``[h_min, 179]`` and
    #: ``[0, h_max]`` when this flag is set.
    wrap_hue: bool = False

    # ------------------------------------------------------------------
    def hue_contains(self, h: float) -> bool:
        if self.wrap_hue:
            return h >= self.h_min or h <= self.h_max
        return self.h_min <= h <= self.h_max

    def contains(self, h: float, s: float, v: float) -> bool:
        return (
            self.hue_contains(h)
            and self.s_min <= s <= self.s_max
            and self.v_min <= v <= self.v_max
        )

    @property
    def hue_center(self) -> float:
        if self.wrap_hue:
            span = (HUE_MAX - self.h_min) + self.h_max + 1
            return ((self.h_min + span / 2.0) % (HUE_MAX + 1))
        return (self.h_min + self.h_max) / 2.0

    @property
    def hue_span(self) -> float:
        if self.wrap_hue:
            return (HUE_MAX - self.h_min) + self.h_max + 1
        return self.h_max - self.h_min

    # ------------------------------------------------------------------
    def _hue_margin(self, h: float) -> float:
        span = max(self.hue_span, 1.0)
        distance = _hue_distance(h, self.hue_center)
        return max(0.0, 1.0 - (distance / (span / 2.0)))

    @staticmethod
    def _linear_margin(x: float, lo: float, hi: float) -> float:
        half = max((hi - lo) / 2.0, 1.0)
        center = (lo + hi) / 2.0
        return max(0.0, 1.0 - abs(x - center) / half)

    def score(self, h: float, s: float, v: float) -> float:
        """0..1 - how comfortably the sample sits inside this box."""
        margins = (
            self._hue_margin(h),
            self._linear_margin(s, self.s_min, self.s_max),
            self._linear_margin(v, self.v_min, self.v_max),
        )
        return sum(margins) / len(margins)

    def distance(self, h: float, s: float, v: float) -> float:
        """Normalised distance from the box centre (used by the fallback)."""
        dh = _hue_distance(h, self.hue_center) / (HUE_MAX / 2.0)
        ds = abs(s - (self.s_min + self.s_max) / 2.0) / SAT_MAX
        dv = abs(v - (self.v_min + self.v_max) / 2.0) / VAL_MAX
        # Hue is the strongest signal for saturated colours; de-weight it when
        # the sample is nearly grey (white stickers).
        hue_weight = min(1.0, s / 90.0)
        return math.sqrt((hue_weight * dh) ** 2 + ds**2 + dv**2)

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Dict[str, object]) -> "ColorRange":
        return cls(
            h_min=int(payload.get("h_min", 0)),
            h_max=int(payload.get("h_max", HUE_MAX)),
            s_min=int(payload.get("s_min", 0)),
            s_max=int(payload.get("s_max", SAT_MAX)),
            v_min=int(payload.get("v_min", 0)),
            v_max=int(payload.get("v_max", VAL_MAX)),
            wrap_hue=bool(payload.get("wrap_hue", False)),
        )


def _hue_distance(a: float, b: float) -> float:
    """Circular distance on the OpenCV hue wheel."""
    diff = abs(float(a) - float(b)) % (HUE_MAX + 1)
    return min(diff, (HUE_MAX + 1) - diff)


# --------------------------------------------------------------------------------------
# Built-in presets
# --------------------------------------------------------------------------------------

#: Tuned for a typical indoor-lit webcam and a standard-colour cube.
DEFAULT_RANGES: Dict[str, ColorRange] = {
    "W": ColorRange(0, HUE_MAX, 0, 65, 125, 255),
    "Y": ColorRange(20, 38, 95, 255, 120, 255),
    "O": ColorRange(4, 19, 130, 255, 110, 255),
    "R": ColorRange(170, 4, 120, 255, 70, 255, wrap_hue=True),
    "G": ColorRange(40, 88, 75, 255, 55, 255),
    "B": ColorRange(90, 132, 90, 255, 55, 255),
}

#: The thresholds from the original ``classify_hue`` implementation, preserved so
#: the previous behaviour stays reproducible from the Calibration page.
LEGACY_RANGES: Dict[str, ColorRange] = {
    "W": ColorRange(5, 36, 9, 60, 45, 179),
    "R": ColorRange(0, 25, 156, 232, 82, 143),
    "Y": ColorRange(28, 39, 146, 255, 132, 194),
    "G": ColorRange(42, 160, 133, 255, 97, 190),
    "B": ColorRange(55, 121, 129, 255, 26, 84),
    "O": ColorRange(1, 85, 211, 248, 75, 148),
}

#: Wider boxes for dim rooms / warm bulbs.
LOW_LIGHT_RANGES: Dict[str, ColorRange] = {
    "W": ColorRange(0, HUE_MAX, 0, 80, 90, 255),
    "Y": ColorRange(18, 40, 70, 255, 90, 255),
    "O": ColorRange(3, 20, 105, 255, 80, 255),
    "R": ColorRange(166, 5, 95, 255, 45, 255, wrap_hue=True),
    "G": ColorRange(38, 92, 55, 255, 35, 255),
    "B": ColorRange(86, 138, 65, 255, 35, 255),
}

BUILTIN_PRESETS: Dict[str, Dict[str, ColorRange]] = {
    "default": DEFAULT_RANGES,
    "low-light": LOW_LIGHT_RANGES,
    "legacy": LEGACY_RANGES,
}


# --------------------------------------------------------------------------------------
# Profile
# --------------------------------------------------------------------------------------


@dataclass
class ColorProfile:
    """A named set of HSV boxes - one per sticker colour."""

    name: str = "default"
    ranges: Dict[str, ColorRange] = field(
        default_factory=lambda: {k: ColorRange(**asdict(v)) for k, v in DEFAULT_RANGES.items()}
    )
    builtin: bool = False

    # ------------------------------------------------------------------
    @classmethod
    def preset(cls, key: str = "default") -> "ColorProfile":
        source = BUILTIN_PRESETS.get(key, DEFAULT_RANGES)
        return cls(
            name=key,
            ranges={code: ColorRange(**asdict(rng)) for code, rng in source.items()},
            builtin=True,
        )

    def to_dict(self) -> Dict[str, object]:
        return {
            "name": self.name,
            "builtin": self.builtin,
            "ranges": {code: rng.to_dict() for code, rng in self.ranges.items()},
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, object]) -> "ColorProfile":
        raw = payload.get("ranges") or {}
        ranges = {
            code: ColorRange.from_dict(raw[code])  # type: ignore[index]
            for code in COLOR_CODES
            if code in raw
        }
        for code, fallback in DEFAULT_RANGES.items():
            ranges.setdefault(code, ColorRange(**asdict(fallback)))
        return cls(
            name=str(payload.get("name", "custom")),
            ranges=ranges,
            builtin=bool(payload.get("builtin", False)),
        )

    # ------------------------------------------------------------------
    def rank(self, h: float, s: float, v: float) -> List[ColorScore]:
        """Every colour for one HSV sample, best match first.

        Colours whose box contains the sample come first, most centred first.
        The rest follow, nearest box first. ``sorted`` is stable, so on a tie the
        colour listed first in the profile wins - exactly like the original
        first-match loop. :meth:`classify` is simply ``rank(...)[0]``.
        """
        inside: List[Tuple[float, ColorScore]] = []
        outside: List[Tuple[float, ColorScore]] = []
        for code, rng in self.ranges.items():
            if rng.contains(h, s, v):
                score = rng.score(h, s, v)
                # Map an in-box score onto a confident 0.55-1.0 band.
                inside.append((score, ColorScore(code, round(0.55 + 0.45 * score, 3), True)))
            else:
                distance = rng.distance(h, s, v)
                # Outside the box: a deliberately low 0.05-0.5 band, so the UI can flag it.
                confidence = max(0.05, min(0.5, 0.5 * math.exp(-1.8 * distance)))
                outside.append((distance, ColorScore(code, round(confidence, 3), False)))
        inside.sort(key=lambda item: -item[0])
        outside.sort(key=lambda item: item[0])
        return [score for _, score in inside] + [score for _, score in outside]

    def classify(self, h: float, s: float, v: float) -> Tuple[str, float]:
        """Return ``(colour_code, confidence)`` for one HSV sample."""
        best = self.rank(h, s, v)[0]
        return best.code, best.confidence

    def calibrate_from_samples(
        self, code: str, samples: Sequence[Tuple[float, float, float]], padding: int = 12
    ) -> ColorRange:
        """Derive a box for ``code`` from sampled pixels (auto-calibration)."""
        if not samples:
            raise ValueError("No samples supplied")
        hues = [float(s[0]) for s in samples]
        sats = [float(s[1]) for s in samples]
        vals = [float(s[2]) for s in samples]

        # Average hue on the circle so red samples near 0/179 do not average to 90.
        mean_x = sum(math.cos(2 * math.pi * h / (HUE_MAX + 1)) for h in hues) / len(hues)
        mean_y = sum(math.sin(2 * math.pi * h / (HUE_MAX + 1)) for h in hues) / len(hues)
        mean_hue = (math.degrees(math.atan2(mean_y, mean_x)) / 360.0) * (HUE_MAX + 1)
        mean_hue %= HUE_MAX + 1
        spread = max(_hue_distance(h, mean_hue) for h in hues) + padding

        h_min = int(round(mean_hue - spread)) % (HUE_MAX + 1)
        h_max = int(round(mean_hue + spread)) % (HUE_MAX + 1)
        wrap = h_min > h_max

        rng = ColorRange(
            h_min=h_min,
            h_max=h_max,
            s_min=max(0, int(min(sats)) - padding * 4),
            s_max=min(SAT_MAX, int(max(sats)) + padding * 4),
            v_min=max(0, int(min(vals)) - padding * 4),
            v_max=min(VAL_MAX, int(max(vals)) + padding * 4),
            wrap_hue=wrap,
        )
        self.ranges[code] = rng
        self.builtin = False
        return rng


# --------------------------------------------------------------------------------------
# Persistence
# --------------------------------------------------------------------------------------


class ProfileStore:
    """JSON-backed store of user-saved HSV profiles."""

    def __init__(self, path: Path = PROFILES_FILE) -> None:
        self._path = path
        self._lock = threading.RLock()
        self._profiles: Dict[str, ColorProfile] = {}
        self._load()

    def _load(self) -> None:
        for key in BUILTIN_PRESETS:
            self._profiles[key] = ColorProfile.preset(key)
        if self._path.exists():
            try:
                payload = json.loads(self._path.read_text("utf-8"))
                for item in payload.get("profiles", []):
                    profile = ColorProfile.from_dict(item)
                    if not profile.builtin:
                        self._profiles[profile.name] = profile
            except (json.JSONDecodeError, OSError, TypeError, KeyError):
                pass

    def _save(self) -> None:
        custom = [p.to_dict() for p in self._profiles.values() if not p.builtin]
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps({"profiles": custom}, indent=2), encoding="utf-8"
        )

    # ------------------------------------------------------------------
    def names(self) -> List[str]:
        with self._lock:
            return list(self._profiles)

    def get(self, name: str) -> ColorProfile:
        with self._lock:
            return self._profiles.get(name) or ColorProfile.preset("default")

    def save(self, profile: ColorProfile) -> ColorProfile:
        with self._lock:
            profile.builtin = profile.name in BUILTIN_PRESETS
            if profile.builtin:
                raise ValueError(
                    f"'{profile.name}' is a built-in preset - save under a new name"
                )
            self._profiles[profile.name] = profile
            self._save()
            return profile

    def delete(self, name: str) -> None:
        with self._lock:
            if name in BUILTIN_PRESETS:
                raise ValueError("Built-in presets cannot be deleted")
            self._profiles.pop(name, None)
            self._save()

    def to_dict(self) -> Dict[str, object]:
        with self._lock:
            return {
                "profiles": [p.to_dict() for p in self._profiles.values()],
                "builtins": list(BUILTIN_PRESETS),
                "colors": [
                    {"code": code, "name": COLOR_NAMES[code]} for code in COLOR_CODES
                ],
            }


#: Convenience wrapper matching the original module-level ``classify_hue`` helper.
def classify_hsv(
    h: float, s: float, v: float, profile: Optional[ColorProfile] = None
) -> Tuple[str, float]:
    return (profile or ColorProfile.preset("default")).classify(h, s, v)


profile_store = ProfileStore()
