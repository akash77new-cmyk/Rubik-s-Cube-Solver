"""Singmaster move notation: parsing, metadata and physical-turn expansion.

A :class:`Move` carries everything the UI needs to render a move graphically -
which face, how many quarter turns, the rotation direction and the axis - so the
frontend never has to re-parse notation strings. It also says which way the turn
moves and gives it in plain English, for a cube held with the front facing you.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Tuple

FACES: tuple[str, ...] = ("U", "R", "F", "D", "L", "B")

#: Human readable face names, used for on-screen instructions.
FACE_NAMES: Dict[str, str] = {
    "U": "Up",
    "R": "Right",
    "F": "Front",
    "D": "Down",
    "L": "Left",
    "B": "Back",
}

#: Rotation axis per face - drives the 3D animation in the frontend.
FACE_AXIS: Dict[str, str] = {
    "U": "y",
    "D": "y",
    "R": "x",
    "L": "x",
    "F": "z",
    "B": "z",
}

#: Which way each turn moves, for a person holding the cube with the front (F) facing
#: them and the top (U) on top - the orientation the solver's moves assume. Everything
#: is seen from where that person is, and the cube is never turned around. For the four
#: side layers it is the way the layer's front stickers travel; for F and B it is the
#: way the layer spins as seen from the front. B "clockwise" is named as seen from
#: behind, so from the front it spins counter-clockwise. Half turns use the clockwise
#: entry. tests/test_moves.py checks every entry against the cube model.
TURN_ARROWS: Dict[str, Tuple[str, str]] = {
    # face: (clockwise, counter-clockwise)
    "U": ("left", "right"),
    "D": ("right", "left"),
    "R": ("up", "down"),
    "L": ("down", "up"),
    "F": ("clockwise", "counter-clockwise"),
    "B": ("counter-clockwise", "clockwise"),
}

#: The same turns in plain English. "Clockwise" alone is hard to follow for a side you
#: are not looking at, so each instruction says which way the layer moves.
_BACK = "Turn the back layer, the side facing away from you"
INSTRUCTIONS: Dict[str, str] = {
    "U": "Turn the top layer to the left.",
    "U'": "Turn the top layer to the right.",
    "U2": "Turn the top layer twice (a half turn, either way).",
    "D": "Turn the bottom layer to the right.",
    "D'": "Turn the bottom layer to the left.",
    "D2": "Turn the bottom layer twice (a half turn, either way).",
    "R": "Turn the right side up, away from you.",
    "R'": "Turn the right side down, towards you.",
    "R2": "Turn the right side twice (a half turn, either way).",
    "L": "Turn the left side down, towards you.",
    "L'": "Turn the left side up, away from you.",
    "L2": "Turn the left side twice (a half turn, either way).",
    "F": "Turn the front face clockwise: its top moves to the right.",
    "F'": "Turn the front face counter-clockwise: its top moves to the left.",
    "F2": "Turn the front face twice (a half turn, either way).",
    "B": _BACK + ": its top moves to the left.",
    "B'": _BACK + ": its top moves to the right.",
    "B2": _BACK + ", twice (a half turn, either way).",
}

_MOVE_RE = re.compile(r"^([URFDLB])(['2]?)$")


@dataclass(frozen=True)
class Move:
    """A single face turn."""

    face: str
    modifier: str = ""  # '' | "'" | '2'

    # ------------------------------------------------------------------
    @property
    def notation(self) -> str:
        return f"{self.face}{self.modifier}"

    @property
    def quarter_turns(self) -> int:
        """Number of clockwise quarter turns (1, 2 or 3)."""
        return {"": 1, "'": 3, "2": 2}[self.modifier]

    @property
    def direction(self) -> str:
        if self.modifier == "'":
            return "ccw"
        if self.modifier == "2":
            return "double"
        return "cw"

    @property
    def axis(self) -> str:
        return FACE_AXIS[self.face]

    @property
    def face_name(self) -> str:
        return FACE_NAMES[self.face]

    @property
    def label(self) -> str:
        suffix = {"": "clockwise", "'": "counter-clockwise", "2": "180°"}[
            self.modifier
        ]
        if self.face == "B" and self.modifier != "2":
            suffix += " (seen from behind)"  # from the front it spins the other way
        return f"{self.face_name} {suffix}"

    @property
    def arrow(self) -> str:
        """Which way the turn moves, as the person holding the cube sees it."""
        clockwise, counter = TURN_ARROWS[self.face]
        return counter if self.modifier == "'" else clockwise

    @property
    def instruction(self) -> str:
        """The turn in plain English, e.g. "Turn the right side up, away from you."."""
        return INSTRUCTIONS[self.notation]

    def inverse(self) -> "Move":
        if self.modifier == "2":
            return self
        return Move(self.face, "'" if self.modifier == "" else "")

    def to_dict(self) -> Dict[str, object]:
        return {
            "notation": self.notation,
            "face": self.face,
            "faceName": self.face_name,
            "modifier": self.modifier,
            "direction": self.direction,
            "axis": self.axis,
            "quarterTurns": self.quarter_turns,
            "label": self.label,
            "arrow": self.arrow,
            "instruction": self.instruction,
        }

    # ------------------------------------------------------------------
    @classmethod
    def parse(cls, token: str) -> "Move":
        match = _MOVE_RE.match(token.strip())
        if not match:
            raise ValueError(f"Invalid move notation: {token!r}")
        return cls(match.group(1), match.group(2))

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.notation


def parse_sequence(sequence: str | Iterable[str]) -> List[Move]:
    """Parse ``"R U R' U'"`` (or an iterable of tokens) into :class:`Move` objects."""
    tokens = sequence.split() if isinstance(sequence, str) else list(sequence)
    return [Move.parse(token) for token in tokens if token]


def sequence_to_string(moves: Iterable[Move]) -> str:
    return " ".join(move.notation for move in moves)


def invert_sequence(moves: Iterable[Move]) -> List[Move]:
    """Return the sequence that undoes ``moves``."""
    return [move.inverse() for move in reversed(list(moves))]


# --------------------------------------------------------------------------------------
# Physical turn expansion
# --------------------------------------------------------------------------------------

#: Marker emitted when the solver asks for a B turn - a human holding the cube
#: cannot see the back face, so we ask them to rotate the whole cube instead.
TURN_BACK = "TURN_BACK"


def expand_for_physical_turns(moves: Iterable[Move]) -> List[str]:
    """Expand a solution into the individual actions a person performs by hand.

    ``B`` is not directly reachable while holding the cube, so it becomes
    ``TURN_BACK, F, TURN_BACK``. Half turns become two quarter turns because the
    on-screen arrow shows one quarter turn at a time.

    This mirrors the behaviour of the original ``expand_moves`` helper so the
    physical guidance flow is unchanged.
    """
    expanded: List[str] = []
    for move in moves:
        if move.face == "B":
            expanded.append(TURN_BACK)
            inner = "F" if move.modifier != "'" else "F'"
            expanded.extend([inner] * (2 if move.modifier == "2" else 1))
            expanded.append(TURN_BACK)
        elif move.modifier == "2":
            expanded.extend([move.face, move.face])
        else:
            expanded.append(move.notation)
    return expanded


def required_presses(move: Move) -> int:
    """How many physical actions a single solver move costs the user."""
    if move.face == "B":
        return 4 if move.modifier == "2" else 3
    return 2 if move.modifier == "2" else 1


def move_distribution(moves: Iterable[Move]) -> Dict[str, int]:
    """Count moves per face - feeds the analytics 'move distribution' chart."""
    counts = {face: 0 for face in FACES}
    for move in moves:
        counts[move.face] += 1
    return counts


def turn_type_distribution(moves: Iterable[Move]) -> Dict[str, int]:
    counts = {"cw": 0, "ccw": 0, "double": 0}
    for move in moves:
        counts[move.direction] += 1
    return counts
