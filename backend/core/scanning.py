"""Guided scanning: which side to show next, and repairing orientation mistakes.

Three ideas make scanning fast and hard to get wrong:

1. **Colour-only instructions.** The user holds the cube from behind - the camera
   sees the side the user can't see - so "turn left" is confusing. Every step names
   just two colours: the centre that faces the camera, and the colour on top.
2. **Faces are recognised by their centre.** Centres never move, so the centre
   colour says which face is in front of the camera. A face is never captured
   twice, and the faces can be shown in any order.
3. **Orientation mistakes are repaired.** If a face was held rotated (or the camera
   mirrors its image), the stickers land in the wrong positions and the cube is
   invalid. :func:`repair_orientation` finds the smallest set of rotations that
   makes the cube valid again - only when that answer is unique.

Assumes the standard colour scheme (``DEFAULT_SCHEME``): white opposite yellow,
green opposite blue, red opposite orange, and red on the right when white is on top
and green faces you. Pure module: no I/O, no OpenCV.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Sequence, Tuple, TypeVar

from backend.core.cube import COLOR_NAMES, DEFAULT_SCHEME, FACE_ORDER, CubeState
from backend.core.cubie import CORNER_FACELETS, CORNER_NAMES, EDGE_FACELETS, EDGE_NAMES
from backend.core.validation import IssueCode

T = TypeVar("T")

# --------------------------------------------------------------------------------------
# The guide
# --------------------------------------------------------------------------------------

#: The colour that must be on top while each face points at the camera. These are the
#: reading conventions of the cube model (and of Kociemba's solver): the four side
#: faces are read with U on top, U with B on top, and D with F on top.
TOP_NEIGHBOUR: Dict[str, str] = {"F": "U", "R": "U", "B": "U", "L": "U", "U": "B", "D": "F"}


@dataclass(frozen=True)
class ScanStep:
    face: str
    how: str  # how to get here from the previous step

    @property
    def center(self) -> str:
        return DEFAULT_SCHEME[self.face]

    @property
    def top(self) -> str:
        return DEFAULT_SCHEME[TOP_NEIGHBOUR[self.face]]

    @property
    def text(self) -> str:
        """e.g. "Green facing the camera, white on top"."""
        return f"{COLOR_NAMES[self.center]} facing the camera, {COLOR_NAMES[self.top].lower()} on top"


#: The suggested order. Four quarter turns, then one tilt and one flip: the
#: quickest way through all six sides. Any other order works too.
SCAN_STEPS: Tuple[ScanStep, ...] = (
    ScanStep("F", "Start here."),
    ScanStep("R", "Turn the cube a quarter turn so red faces the camera."),
    ScanStep("B", "Keep turning the same way."),
    ScanStep("L", "Keep turning the same way."),
    ScanStep("U", "Turn back to green, then tilt the top towards the camera."),
    ScanStep("D", "Flip the cube over: tilt it the same way twice more."),
)
SCAN_ORDER: Tuple[str, ...] = tuple(step.face for step in SCAN_STEPS)
STEP_BY_FACE: Dict[str, ScanStep] = {step.face: step for step in SCAN_STEPS}

_FACE_BY_CENTER: Dict[str, str] = {color: face for face, color in DEFAULT_SCHEME.items()}


def face_for_center(color: str) -> Optional[str]:
    """Which face has this centre colour (``"G"`` -> ``"F"``), or None."""
    return _FACE_BY_CENTER.get(color)


def banner_title(face: Optional[str]) -> str:
    """Short ASCII instruction for the camera overlay (OpenCV can only draw ASCII)."""
    if face is None:
        return "All six sides captured"
    step = STEP_BY_FACE[face]
    return f"Show {COLOR_NAMES[step.center].upper()}, {COLOR_NAMES[step.top].upper()} on top"


# --------------------------------------------------------------------------------------
# Re-ordering a face's nine stickers
# --------------------------------------------------------------------------------------

#: Index maps over a face's 9 stickers in reading order: ``new[i] = old[MAP[i]]``.
IDENTITY_MAP: Tuple[int, ...] = (0, 1, 2, 3, 4, 5, 6, 7, 8)
#: Undo a left-right flip (a mirrored camera image swaps the left and right columns).
MIRROR_MAP: Tuple[int, ...] = (2, 1, 0, 5, 4, 3, 8, 7, 6)
#: Rotate a face's reading a quarter turn clockwise.
QUARTER_TURN_MAP: Tuple[int, ...] = (6, 3, 0, 7, 4, 1, 8, 5, 2)


def reorder(values: Sequence[T], index_map: Sequence[int]) -> List[T]:
    return [values[i] for i in index_map]


def orientation_map(quarter_turns: int = 0, mirrored: bool = False) -> Tuple[int, ...]:
    """Index map that first undoes a mirror (if any), then turns ``quarter_turns`` clockwise."""
    index_map = list(MIRROR_MAP if mirrored else IDENTITY_MAP)
    for _ in range(quarter_turns % 4):
        index_map = reorder(index_map, QUARTER_TURN_MAP)
    return tuple(index_map)


# --------------------------------------------------------------------------------------
# Orientation repair
# --------------------------------------------------------------------------------------

#: How many faces the repair may re-orient. Guided scans rarely get more than one
#: wrong; three keeps the search small (at most ~1,400 validity checks).
MAX_ROTATED_FACES = 3

_TURN_WORDS = {1: "a quarter turn off", 2: "upside down", 3: "a quarter turn off"}
_COLOUR_PROBLEMS = {IssueCode.INVALID_COLOR, IssueCode.DUPLICATE_CENTERS, IssueCode.COLOR_COUNT}


@dataclass(frozen=True)
class OrientationFix:
    """Quarter turns per face, plus whether every face's reading was mirrored."""

    rotations: Dict[str, int] = field(default_factory=dict)
    mirrored: bool = False

    def index_map(self, face: str) -> Tuple[int, ...]:
        return orientation_map(self.rotations.get(face, 0), self.mirrored)

    def describe(self) -> str:
        parts = ["the camera image was mirrored"] if self.mirrored else []
        for face in FACE_ORDER:
            if face in self.rotations:
                colour = COLOR_NAMES[DEFAULT_SCHEME[face]].lower()
                parts.append(f"the {colour} side was held {_TURN_WORDS[self.rotations[face]]}")
        return "Fixed automatically: " + "; ".join(parts) + "."


def repair_orientation(
    faces: Mapping[str, Sequence[str]], max_rotated_faces: int = MAX_ROTATED_FACES
) -> Optional[OrientationFix]:
    """The smallest orientation change that turns an invalid scan into a valid cube.

    Tries 0, 1, 2 ... ``max_rotated_faces`` re-oriented faces, each with and without
    undoing a mirror on every face, and stops at the first size that works.
    Returns None when:

    * the scan is already valid (nothing to repair);
    * the colours themselves are wrong - a misread sticker changes the colour
      counts, and no rotation can fix that (the Phase 5 repair agent handles it);
    * nothing small enough works;
    * two different fixes are equally small - guessing could store a wrong cube,
      so it is better to ask for a re-scan.
    """
    issues = CubeState({face: list(faces[face]) for face in FACE_ORDER}).validate().issues
    if not issues or any(issue.code in _COLOUR_PROBLEMS for issue in issues):
        return None

    # Quick filter: a valid cube shows a real piece at every corner and edge. Checking
    # just the colour sets rejects almost every candidate in microseconds; only the
    # few that pass get the full validation.
    center = {face: faces[face][4] for face in FACE_ORDER}
    corner_sets = {frozenset(center[f] for f in name) for name in CORNER_NAMES}
    edge_sets = {frozenset(center[f] for f in name) for name in EDGE_NAMES}

    def plausible(candidate: Mapping[str, Sequence[str]]) -> bool:
        stickers = [color for face in FACE_ORDER for color in candidate[face]]
        return all(
            frozenset(stickers[i] for i in slots) in corner_sets for slots in CORNER_FACELETS
        ) and all(frozenset(stickers[i] for i in slots) in edge_sets for slots in EDGE_FACELETS)

    for size in range(max_rotated_faces + 1):
        found: Dict[Tuple[Tuple[str, ...], ...], OrientationFix] = {}
        for mirrored in (False, True):
            if size == 0 and not mirrored:
                continue  # that is the scan as it is: already known to be invalid
            for chosen in itertools.combinations(FACE_ORDER, size):
                for turns in itertools.product((1, 2, 3), repeat=size):
                    fix = OrientationFix(dict(zip(chosen, turns)), mirrored)
                    candidate = {face: reorder(faces[face], fix.index_map(face)) for face in FACE_ORDER}
                    if plausible(candidate) and CubeState(candidate).validate().ok:
                        key = tuple(tuple(candidate[face]) for face in FACE_ORDER)
                        found.setdefault(key, fix)
        if len(found) == 1:
            return next(iter(found.values()))
        if len(found) > 1:
            return None
    return None
