"""Cube state representation and move simulation.

The cube is stored the same way the scanner produces it: a mapping of face key
(``U R F D L B``) to a list of nine **colour codes** in reading order::

    0 1 2
    3 4 5
    6 7 8

Colour codes are ``W Y R O G B``. Index 4 of every face is its centre, which is
what defines the colour scheme of the physical cube being scanned.

The face-cycle tables in :func:`CubeState.apply` are the ones from the original
solver script - they are known-correct and deliberately left untouched; only the
surrounding structure changed.
"""

from __future__ import annotations

import copy
import random
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from backend.core.moves import Move, parse_sequence

FACE_ORDER: Tuple[str, ...] = ("U", "R", "F", "D", "L", "B")
COLOR_CODES: Tuple[str, ...] = ("W", "Y", "R", "O", "G", "B")

COLOR_NAMES: Dict[str, str] = {
    "W": "White",
    "Y": "Yellow",
    "R": "Red",
    "O": "Orange",
    "G": "Green",
    "B": "Blue",
}

#: Colour scheme of a standard Western-scheme cube, used for the "solved" state
#: and for the animated hero cube on the dashboard.
DEFAULT_SCHEME: Dict[str, str] = {
    "U": "W",
    "R": "R",
    "F": "G",
    "D": "Y",
    "L": "O",
    "B": "B",
}

# Which faces/indices cycle for each face turn. ``cycle`` lists the faces in the
# order content flows (faces[i] receives from faces[i-1]).
_EDGE_CYCLES: Dict[str, Tuple[Sequence[str], Sequence[Sequence[int]]]] = {
    "U": (("B", "R", "F", "L"), ([0, 1, 2], [0, 1, 2], [0, 1, 2], [0, 1, 2])),
    "D": (("F", "R", "B", "L"), ([6, 7, 8], [6, 7, 8], [6, 7, 8], [6, 7, 8])),
    "F": (("U", "R", "D", "L"), ([6, 7, 8], [0, 3, 6], [2, 1, 0], [8, 5, 2])),
    "B": (("U", "L", "D", "R"), ([2, 1, 0], [0, 3, 6], [6, 7, 8], [8, 5, 2])),
    "L": (("U", "F", "D", "B"), ([0, 3, 6], [0, 3, 6], [0, 3, 6], [8, 5, 2])),
    "R": (("U", "B", "D", "F"), ([8, 5, 2], [0, 3, 6], [8, 5, 2], [8, 5, 2])),
}


class InvalidCubeError(ValueError):
    """Raised when a scanned cube cannot describe a real, solvable cube."""


@dataclass
class ValidationResult:
    ok: bool
    errors: List[str]
    warnings: List[str]

    def to_dict(self) -> Dict[str, object]:
        return {"ok": self.ok, "errors": self.errors, "warnings": self.warnings}


def _rotate_face(stickers: List[str], turns: int) -> None:
    """Rotate one face's nine stickers clockwise, in place."""
    for _ in range(turns % 4):
        stickers[:] = [
            stickers[6], stickers[3], stickers[0],
            stickers[7], stickers[4], stickers[1],
            stickers[8], stickers[5], stickers[2],
        ]


def _cycle_edges(
    facelets: Dict[str, List[str]],
    faces: Sequence[str],
    indices: Sequence[Sequence[int]],
    turns: int,
) -> None:
    """Cycle the four adjacent strips that a face turn drags along."""
    for _ in range(turns % 4):
        carry = [facelets[faces[-1]][i] for i in indices[-1]]
        for i in reversed(range(1, 4)):
            for j in range(3):
                facelets[faces[i]][indices[i][j]] = facelets[faces[i - 1]][
                    indices[i - 1][j]
                ]
        for j in range(3):
            facelets[faces[0]][indices[0][j]] = carry[j]


class CubeState:
    """An immutable-by-convention 3x3 cube state.

    :meth:`apply` returns a **new** ``CubeState`` so that scan history, solution
    playback and undo can all hold on to earlier states safely.
    """

    __slots__ = ("_facelets",)

    def __init__(self, facelets: Dict[str, Iterable[str]]) -> None:
        missing = [face for face in FACE_ORDER if face not in facelets]
        if missing:
            raise InvalidCubeError(f"Missing faces: {', '.join(missing)}")
        self._facelets = {}
        for face in FACE_ORDER:
            stickers = list(facelets[face])
            if len(stickers) != 9:
                raise InvalidCubeError(
                    f"Face {face} has {len(stickers)} stickers, expected 9"
                )
            self._facelets[face] = stickers

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------
    @classmethod
    def solved(cls, scheme: Optional[Dict[str, str]] = None) -> "CubeState":
        scheme = scheme or DEFAULT_SCHEME
        return cls({face: [scheme[face]] * 9 for face in FACE_ORDER})

    @classmethod
    def from_color_string(
        cls, text: str, scheme: Optional[Dict[str, str]] = None
    ) -> "CubeState":
        """Build from 54 colour codes in ``U R F D L B`` order."""
        text = "".join(text.split()).upper()
        if len(text) != 54:
            raise InvalidCubeError(f"Expected 54 colour codes, got {len(text)}")
        return cls(
            {face: list(text[i * 9 : i * 9 + 9]) for i, face in enumerate(FACE_ORDER)}
        )

    def copy(self) -> "CubeState":
        return CubeState(copy.deepcopy(self._facelets))

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------
    @property
    def facelets(self) -> Dict[str, List[str]]:
        """Defensive copy of the raw sticker map."""
        return {face: list(stickers) for face, stickers in self._facelets.items()}

    def face(self, key: str) -> List[str]:
        return list(self._facelets[key])

    @property
    def centers(self) -> Dict[str, str]:
        """Face key -> centre colour code (the cube's colour scheme)."""
        return {face: self._facelets[face][4] for face in FACE_ORDER}

    def color_counts(self) -> Dict[str, int]:
        counts = {code: 0 for code in COLOR_CODES}
        for face in FACE_ORDER:
            for code in self._facelets[face]:
                counts[code] = counts.get(code, 0) + 1
        return counts

    def to_color_string(self) -> str:
        return "".join("".join(self._facelets[face]) for face in FACE_ORDER)

    def to_facelet_string(self) -> str:
        """54-char string in Kociemba's ``URFDLB`` facelet alphabet.

        Each sticker colour is mapped to the face whose centre carries that
        colour, which is exactly how the original script built its cube string.
        """
        color_to_face = {color: face for face, color in self.centers.items()}
        if len(color_to_face) != 6:
            raise InvalidCubeError(
                "Centre colours are not unique - re-scan the cube "
                f"(centres: {self.centers})"
            )
        try:
            return "".join(
                color_to_face[color]
                for face in FACE_ORDER
                for color in self._facelets[face]
            )
        except KeyError as exc:  # unknown colour on a sticker
            raise InvalidCubeError(
                f"Sticker colour {exc.args[0]!r} does not match any centre colour"
            ) from exc

    # ------------------------------------------------------------------
    # Move simulation
    # ------------------------------------------------------------------
    def apply(self, move: Move | str) -> "CubeState":
        """Return a new state with ``move`` applied."""
        if isinstance(move, str):
            move = Move.parse(move)
        facelets = copy.deepcopy(self._facelets)
        _rotate_face(facelets[move.face], move.quarter_turns)
        faces, indices = _EDGE_CYCLES[move.face]
        _cycle_edges(facelets, faces, indices, move.quarter_turns)
        return CubeState(facelets)

    def apply_sequence(self, moves: Iterable[Move] | str) -> "CubeState":
        if isinstance(moves, str):
            moves = parse_sequence(moves)
        state = self
        for move in moves:
            state = state.apply(move)
        return state

    def trace(self, moves: Iterable[Move]) -> List["CubeState"]:
        """States after each move, starting with the current state.

        Length is ``len(moves) + 1`` - the solution player scrubs through this
        list so stepping backwards is instant.
        """
        states = [self]
        state = self
        for move in moves:
            state = state.apply(move)
            states.append(state)
        return states

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    @property
    def is_solved(self) -> bool:
        return all(
            len(set(self._facelets[face])) == 1 for face in FACE_ORDER
        )

    def solved_sticker_count(self) -> int:
        """How many stickers already match their face centre (progress metric)."""
        total = 0
        for face in FACE_ORDER:
            center = self._facelets[face][4]
            total += sum(1 for code in self._facelets[face] if code == center)
        return total

    def validate(self) -> ValidationResult:
        errors: List[str] = []
        warnings: List[str] = []

        centers = self.centers
        if len(set(centers.values())) != 6:
            errors.append(
                "Centre colours must all differ - two faces were scanned with the "
                "same centre colour."
            )

        counts = self.color_counts()
        for code, count in counts.items():
            if count and count != 9:
                errors.append(
                    f"{COLOR_NAMES.get(code, code)} appears {count} times (expected 9)."
                )
        unknown = [c for c in counts if c not in COLOR_CODES]
        if unknown:
            errors.append(f"Unrecognised colour codes: {', '.join(unknown)}")

        if not errors:
            try:
                facelets = self.to_facelet_string()
            except InvalidCubeError as exc:
                errors.append(str(exc))
            else:
                if len(facelets) != 54:
                    errors.append("Facelet string is not 54 characters long.")

        return ValidationResult(ok=not errors, errors=errors, warnings=warnings)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------
    def to_dict(self) -> Dict[str, object]:
        return {
            "facelets": self.facelets,
            "centers": self.centers,
            "colorString": self.to_color_string(),
            "isSolved": self.is_solved,
            "solvedStickers": self.solved_sticker_count(),
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, object]) -> "CubeState":
        facelets = payload.get("facelets") if isinstance(payload, dict) else None
        if not isinstance(facelets, dict):
            raise InvalidCubeError("Payload has no 'facelets' mapping")
        return cls(facelets)  # type: ignore[arg-type]

    def __eq__(self, other: object) -> bool:
        return isinstance(other, CubeState) and self._facelets == other._facelets

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<CubeState {self.to_color_string()}>"


def random_scramble(length: int = 22, seed: Optional[int] = None) -> List[Move]:
    """Generate a random scramble that never turns the same face twice in a row."""
    rng = random.Random(seed)
    faces = list("URFDLB")
    modifiers = ["", "'", "2"]
    moves: List[Move] = []
    previous = ""
    for _ in range(length):
        face = rng.choice([f for f in faces if f != previous])
        previous = face
        moves.append(Move(face, rng.choice(modifiers)))
    return moves
