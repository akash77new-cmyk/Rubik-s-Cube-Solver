"""Find the stickers the camera most likely misread (Phase 5). Pure code, no AI.

A scan that fails validation usually has one or two misread stickers: red read as
orange, white read as yellow, and so on. This search tries every way of changing
one sticker, then every way of changing two, and keeps only the changes that make
the cube **valid**. The validator decides; nothing here guesses.

    1. Skip any change that leaves a colour count other than 9 (an instant check).
    2. Run the full validation (pieces, twist, flip, parity) on what is left.
    3. Rank the valid fixes: fewest changes first, then the ones the camera itself
       doubted most (a low confidence for the colour it read, and a good score
       for the new colour among its best three guesses).

Centres are never changed: a side is identified by its centre colour. A scan
that needs three or more changes gets no candidates; then the user rescans.

The Smart Repair Agent (``backend/ai/repair_agent.py``) reads these candidates
through a tool, and the built-in fallback simply proposes the best one.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations, product
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from backend.core.cube import COLOR_CODES, FACE_ORDER, CubeState

#: At most this many stickers are changed in one fix.
MAX_CHANGES = 2

#: Per-sticker readings from the scan: face -> 9 dicts, each with "color",
#: "confidence" and "alternatives" ([{"color", "confidence"}, ...], best first).
Readings = Mapping[str, Sequence[Mapping[str, Any]]]


@dataclass(frozen=True)
class StickerChange:
    face: str
    index: int
    old: str
    new: str
    old_confidence: float  # how sure the camera was of the colour it read (1.0 = no data)
    new_confidence: float  # how well the new colour fitted (0.0 = not among its best 3)

    @property
    def cost(self) -> float:
        """Lower = more likely a misread: the camera doubted the old colour, liked the new one."""
        return round(self.old_confidence - self.new_confidence, 4)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "face": self.face,
            "index": self.index,
            "from": self.old,
            "to": self.new,
            "oldConfidence": self.old_confidence,
            "newConfidence": self.new_confidence,
        }


@dataclass(frozen=True)
class RepairCandidate:
    """One fix that makes the cube valid."""

    id: int
    changes: Tuple[StickerChange, ...]

    @property
    def cost(self) -> float:
        return round(sum(change.cost for change in self.changes), 4)

    def apply(self, cube: CubeState) -> CubeState:
        facelets = cube.facelets
        for change in self.changes:
            facelets[change.face][change.index] = change.new
        return CubeState(facelets)

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "cost": self.cost, "changes": [c.to_dict() for c in self.changes]}


@dataclass(frozen=True)
class RepairSearch:
    candidates: List[RepairCandidate]  # the best few, best first
    total: int  # how many valid fixes were found in all
    checked: int  # how many changes passed the colour count and were validated


def _evidence(readings: Optional[Readings], face: str, index: int, old: str, new: str) -> Tuple[float, float]:
    """(confidence of the colour read, confidence of the new colour) for one sticker."""
    if not readings or face not in readings or index >= len(readings[face]):
        return 1.0, 0.0  # no camera data (a typed or demo cube): every sticker counts the same
    reading = readings[face][index]
    old_confidence = float(reading.get("confidence", 1.0)) if reading.get("color") == old else 1.0
    new_confidence = 0.0
    for alternative in reading.get("alternatives") or []:
        if alternative.get("color") == new:
            new_confidence = float(alternative.get("confidence", 0.0))
            break
    return round(old_confidence, 3), round(new_confidence, 3)


def find_repairs(cube: CubeState, readings: Optional[Readings] = None, limit: int = 5) -> RepairSearch:
    """Every fix of 1 (else 2) sticker changes that makes ``cube`` valid, best first."""
    if cube.validate().ok:
        return RepairSearch([], 0, 0)
    centers = cube.centers
    if len(set(centers.values())) != 6:
        return RepairSearch([], 0, 0)  # a centre problem: changing stickers can't fix it

    facelets = cube.facelets
    counts = cube.color_counts()
    if any(code not in COLOR_CODES for code in counts):
        return RepairSearch([], 0, 0)
    stickers = [(face, index) for face in FACE_ORDER for index in range(9) if index != 4]

    found: List[Tuple[StickerChange, ...]] = []
    checked = 0
    for size in range(1, MAX_CHANGES + 1):
        for chosen in combinations(stickers, size):
            olds = [facelets[face][index] for face, index in chosen]
            options = [[code for code in COLOR_CODES if code != old] for old in olds]
            for news in product(*options):
                if not _counts_fixed(counts, olds, news):
                    continue
                checked += 1
                trial = {face: list(colors) for face, colors in facelets.items()}
                for (face, index), new in zip(chosen, news):
                    trial[face][index] = new
                if CubeState(trial).validate().ok:
                    found.append(tuple(
                        StickerChange(face, index, old, new, *_evidence(readings, face, index, old, new))
                        for (face, index), old, new in zip(chosen, olds, news)
                    ))
        if found:
            break  # fewer changes is always more likely than more changes

    found.sort(key=lambda changes: (sum(change.cost for change in changes), changes[0].face, changes[0].index))
    candidates = [RepairCandidate(number + 1, changes) for number, changes in enumerate(found[:limit])]
    return RepairSearch(candidates, len(found), checked)


def _counts_fixed(counts: Dict[str, int], olds: Sequence[str], news: Sequence[str]) -> bool:
    """Would these changes leave exactly 9 stickers of every colour?"""
    after = dict(counts)
    for old, new in zip(olds, news):
        after[old] -= 1
        after[new] = after.get(new, 0) + 1
    return all(after.get(code, 0) == 9 for code in COLOR_CODES)
