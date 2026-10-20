"""Cubie-level cube model: 8 corners + 12 edges instead of 54 stickers.

Why: a sticker map can look fine (nine of each colour) and still describe a cube
that no amount of turning can solve. Physically, a cube is 8 corner pieces and
12 edge pieces. Turning the faces can never:

* twist a single corner in place      -> total corner twist must be 0 (mod 3)
* flip a single edge in place         -> total edge flip must be 0 (mod 2)
* swap just two pieces                -> corner and edge permutation parity must match

So only 1 in 12 ways of putting the pieces together is solvable. This module
turns a 54-facelet string into pieces, reports any sticker group that is not a
real piece, and checks the three invariants.

Conventions are Herbert Kociemba's (the same as the solver), so a facelet string
here is exactly the string the solver receives:

* facelet index = face * 9 + position, faces in order U R F D L B,
  e.g. U1..U9 = 0..8, R1..R9 = 9..17, ..., B1..B9 = 45..53;
* corner orientation = which of the corner's three stickers carries the U or D
  colour (0, 1 or 2, counted clockwise from the U/D-facing sticker position);
* edge orientation = 0 if the edge's first sticker (the U/D sticker, or the F/B
  sticker for the four middle-layer edges) is in the first slot, else 1.

This module is pure: no I/O, no OpenCV, no colour codes - only face letters.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from backend.core.validation import IssueCode, StickerRef, ValidationIssue

FACES = "URFDLB"

#: Pairs of faces that are opposite each other - never on the same piece.
OPPOSITE: Dict[str, str] = {"U": "D", "D": "U", "R": "L", "L": "R", "F": "B", "B": "F"}

CORNER_NAMES: Tuple[str, ...] = ("URF", "UFL", "ULB", "UBR", "DFR", "DLF", "DBL", "DRB")
EDGE_NAMES: Tuple[str, ...] = (
    "UR", "UF", "UL", "UB", "DR", "DF", "DL", "DB", "FR", "FL", "BL", "BR",
)

#: Facelet indices of each corner position, U/D sticker first, then clockwise.
#: (URF = U9, R1, F3 -> 8, 9, 20; and so on, as in Kociemba's cornerFacelet.)
CORNER_FACELETS: Tuple[Tuple[int, int, int], ...] = (
    (8, 9, 20), (6, 18, 38), (0, 36, 47), (2, 45, 11),
    (29, 26, 15), (27, 44, 24), (33, 53, 42), (35, 17, 51),
)

#: Facelet indices of each edge position (Kociemba's edgeFacelet).
EDGE_FACELETS: Tuple[Tuple[int, int], ...] = (
    (5, 10), (7, 19), (3, 37), (1, 46), (32, 16), (28, 25),
    (30, 43), (34, 52), (23, 12), (21, 41), (50, 39), (48, 14),
)

#: The colours (face letters) of each piece, in the same order as its facelets.
CORNER_COLORS: Tuple[str, ...] = CORNER_NAMES
EDGE_COLORS: Tuple[str, ...] = EDGE_NAMES

CENTER_FACELETS: Tuple[int, ...] = (4, 13, 22, 31, 40, 49)
MIDDLE_LAYER_EDGES = frozenset({8, 9, 10, 11})  # FR, FL, BL, BR: the E-slice

#: G1 moves: Kociemba phase 2 uses only these. A cube in G1 never needs others.
G1_MOVES = frozenset({"U", "U'", "U2", "D", "D'", "D2", "R2", "L2", "F2", "B2"})


def sticker_ref(facelet: int) -> StickerRef:
    """Facelet index 0..53 -> (face, index 0..8)."""
    return FACES[facelet // 9], facelet % 9


def sticker_label(facelet: int) -> str:
    """Facelet index -> Kociemba's 1-based label, e.g. 8 -> 'U9'."""
    face, index = sticker_ref(facelet)
    return f"{face}{index + 1}"


# --------------------------------------------------------------------------------------
# Cubie cube
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class CubieCube:
    """Which piece sits in each position, and how it is oriented.

    ``cp[i] = j`` means corner ``CORNER_NAMES[j]`` sits in corner position i,
    ``co[i]`` is its twist (0..2). ``ep``/``eo`` are the same for edges (flip 0..1).
    """

    cp: Tuple[int, ...]
    co: Tuple[int, ...]
    ep: Tuple[int, ...]
    eo: Tuple[int, ...]

    @classmethod
    def solved(cls) -> "CubieCube":
        return cls(tuple(range(8)), (0,) * 8, tuple(range(12)), (0,) * 12)

    @property
    def corner_twist(self) -> int:
        """Total corner twist mod 3. A solvable cube has 0."""
        return sum(self.co) % 3

    @property
    def edge_flip(self) -> int:
        """Total edge flip mod 2. A solvable cube has 0."""
        return sum(self.eo) % 2

    @property
    def corner_parity(self) -> int:
        return permutation_parity(self.cp)

    @property
    def edge_parity(self) -> int:
        return permutation_parity(self.ep)

    def to_facelet_string(self) -> str:
        """Back to a 54-char URFDLB string (centres included)."""
        facelets = ["?"] * 54
        for index, face in zip(CENTER_FACELETS, FACES):
            facelets[index] = face
        for position, (piece, twist) in enumerate(zip(self.cp, self.co)):
            for k in range(3):
                facelets[CORNER_FACELETS[position][(k + twist) % 3]] = CORNER_COLORS[piece][k]
        for position, (piece, flip) in enumerate(zip(self.ep, self.eo)):
            for k in range(2):
                facelets[EDGE_FACELETS[position][(k + flip) % 2]] = EDGE_COLORS[piece][k]
        return "".join(facelets)


def permutation_parity(permutation: Sequence[int]) -> int:
    """0 if the permutation is even, 1 if odd (counts inversions)."""
    inversions = 0
    for i in range(len(permutation)):
        for j in range(i + 1, len(permutation)):
            if permutation[i] > permutation[j]:
                inversions += 1
    return inversions % 2


def in_g1(cube: CubieCube) -> bool:
    """True if the cube is in Kociemba's subgroup G1 = <U, D, R2, L2, F2, B2>.

    That means: no corner is twisted, no edge is flipped, and the four
    middle-layer edges (FR, FL, BL, BR) are somewhere in the middle layer.
    Phase 1 of Kociemba's algorithm ends exactly when the cube reaches G1.
    """
    return (
        all(t == 0 for t in cube.co)
        and all(f == 0 for f in cube.eo)
        and all(cube.ep[position] in MIDDLE_LAYER_EDGES for position in MIDDLE_LAYER_EDGES)
    )


# --------------------------------------------------------------------------------------
# Facelets -> cubies, with a precise reason for every failure
# --------------------------------------------------------------------------------------


@dataclass
class PieceAnalysis:
    """Result of :func:`analyse_facelets`. ``cubie`` is None if any issue was found."""

    cubie: Optional[CubieCube]
    issues: List[ValidationIssue]


def _match_corner(colors: Tuple[str, str, str]) -> Optional[Tuple[int, int]]:
    """(piece, twist) of the real corner these stickers show, or None."""
    for piece, piece_colors in enumerate(CORNER_COLORS):
        for twist in range(3):
            if all(colors[(k + twist) % 3] == piece_colors[k] for k in range(3)):
                return piece, twist
    return None


def _match_edge(colors: Tuple[str, str]) -> Optional[Tuple[int, int]]:
    """(piece, flip) of the real edge these stickers show, or None."""
    for piece, piece_colors in enumerate(EDGE_COLORS):
        if colors == (piece_colors[0], piece_colors[1]):
            return piece, 0
        if colors == (piece_colors[1], piece_colors[0]):
            return piece, 1
    return None


def _why_not_a_piece(colors: Sequence[str]) -> str:
    """'repeated', 'opposite' or 'mirrored' - why these stickers are no real piece."""
    if len(set(colors)) < len(colors):
        return "repeated"
    if any(OPPOSITE[a] == b for a in colors for b in colors):
        return "opposite"
    return "mirrored"  # right colours, mirror-image order (only possible for corners)


def _names(faces: Sequence[str], color_names: Mapping[str, str]) -> str:
    words = [color_names.get(face, face) for face in faces]
    return ", ".join(words[:-1]) + " and " + words[-1] if len(words) > 1 else words[0]


def analyse_facelets(
    facelets: str, color_names: Optional[Mapping[str, str]] = None
) -> PieceAnalysis:
    """Identify every corner and edge, and check twist, flip and parity.

    ``facelets`` is a 54-char URFDLB string with each centre equal to its face
    letter (what ``CubeState.to_facelet_string()`` returns). ``color_names``
    maps face letters to words used in messages, e.g. {"U": "white"}.
    """
    if len(facelets) != 54 or any(facelets[i] != FACES[k] for k, i in enumerate(CENTER_FACELETS)):
        raise ValueError("analyse_facelets() needs a 54-char URFDLB string with fixed centres")
    names = dict(color_names or {face: face for face in FACES})
    issues: List[ValidationIssue] = []

    # ---- 1. Every sticker group must be a real piece -------------------------
    cp: List[Optional[int]] = [None] * 8
    co: List[int] = [0] * 8
    for position, slots in enumerate(CORNER_FACELETS):
        colors = tuple(facelets[i] for i in slots)
        match = _match_corner(colors)  # type: ignore[arg-type]
        if match:
            cp[position], co[position] = match
            continue
        reason = _why_not_a_piece(colors)
        what = {
            "repeated": "has the same colour twice",
            "opposite": "has two opposite colours",
            "mirrored": "has its colours in mirror-image order",
        }[reason]
        issues.append(ValidationIssue(
            code=IssueCode.IMPOSSIBLE_CORNER,
            message=(
                f"Corner {CORNER_NAMES[position]} ({_names(colors, names)}) {what}, "
                "so no real corner looks like this."
            ),
            stickers=tuple(sticker_ref(i) for i in slots),
            pieces=(CORNER_NAMES[position],),
            details={"reason": reason, "labels": [sticker_label(i) for i in slots]},
        ))

    ep: List[Optional[int]] = [None] * 12
    eo: List[int] = [0] * 12
    for position, slots in enumerate(EDGE_FACELETS):
        colors = tuple(facelets[i] for i in slots)
        match = _match_edge(colors)  # type: ignore[arg-type]
        if match:
            ep[position], eo[position] = match
            continue
        reason = _why_not_a_piece(colors)
        what = "has the same colour twice" if reason == "repeated" else "has two opposite colours"
        issues.append(ValidationIssue(
            code=IssueCode.IMPOSSIBLE_EDGE,
            message=(
                f"Edge {EDGE_NAMES[position]} ({_names(colors, names)}) {what}, "
                "so no real edge looks like this."
            ),
            stickers=tuple(sticker_ref(i) for i in slots),
            pieces=(EDGE_NAMES[position],),
            details={"reason": reason, "labels": [sticker_label(i) for i in slots]},
        ))

    # ---- 2. Every piece exactly once -------------------------------------------
    issues += _duplicates_and_missing(cp, CORNER_NAMES, CORNER_FACELETS, "corner", names)
    issues += _duplicates_and_missing(ep, EDGE_NAMES, EDGE_FACELETS, "edge", names)
    if issues:
        return PieceAnalysis(cubie=None, issues=issues)

    cube = CubieCube(tuple(cp), tuple(co), tuple(ep), tuple(eo))  # type: ignore[arg-type]

    # ---- 3. The three invariants -----------------------------------------------
    if cube.corner_twist:
        issues.append(ValidationIssue(
            code=IssueCode.CORNER_TWIST,
            message=(
                "One corner is twisted in place. Face turns can never do that, so a "
                "sticker was probably read wrong or a corner was put back twisted."
            ),
            details={"twist": cube.corner_twist},
        ))
    if cube.edge_flip:
        issues.append(ValidationIssue(
            code=IssueCode.EDGE_FLIP,
            message=(
                "One edge is flipped in place. Face turns can never do that, so a "
                "sticker was probably read wrong or an edge was put back flipped."
            ),
            details={"flip": cube.edge_flip},
        ))
    if cube.corner_parity != cube.edge_parity:
        issues.append(ValidationIssue(
            code=IssueCode.PARITY,
            message=(
                "Two pieces are swapped (a parity error). Face turns can never swap "
                "just two pieces, so this cube can't be solved as scanned."
            ),
            details={"cornerParity": cube.corner_parity, "edgeParity": cube.edge_parity},
        ))
    return PieceAnalysis(cubie=None if issues else cube, issues=issues)


def _duplicates_and_missing(
    found: Sequence[Optional[int]],
    piece_names: Sequence[str],
    position_facelets: Sequence[Sequence[int]],
    kind: str,
    names: Mapping[str, str],
) -> List[ValidationIssue]:
    counts = Counter(piece for piece in found if piece is not None)
    duplicate_code = IssueCode.DUPLICATE_CORNER if kind == "corner" else IssueCode.DUPLICATE_EDGE
    missing_code = IssueCode.MISSING_CORNER if kind == "corner" else IssueCode.MISSING_EDGE
    issues: List[ValidationIssue] = []

    for piece, count in sorted(counts.items()):
        if count < 2:
            continue
        positions = [p for p, value in enumerate(found) if value == piece]
        stickers = tuple(sticker_ref(i) for p in positions for i in position_facelets[p])
        issues.append(ValidationIssue(
            code=duplicate_code,
            message=(
                f"The {_names(piece_names[piece], names)} {kind} appears {count} times "
                f"(at {', '.join(piece_names[p] for p in positions)}). A real cube has each piece once."
            ),
            stickers=stickers,
            pieces=tuple(piece_names[p] for p in positions),
            details={"piece": piece_names[piece], "count": count},
        ))

    for piece, name in enumerate(piece_names):
        if counts.get(piece, 0) == 0:
            issues.append(ValidationIssue(
                code=missing_code,
                message=f"The {_names(name, names)} {kind} is missing.",
                details={"piece": name},
            ))
    return issues
