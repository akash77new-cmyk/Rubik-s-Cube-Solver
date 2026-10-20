"""Structured validation results.

A scanned cube can be impossible in many ways. Instead of a list of strings,
validation returns *issues*: each one has a stable ``code`` (for programs, such
as the Phase 5 repair agent), a plain-English ``message`` (for people), and the
exact stickers and pieces involved (for highlighting in the UI).

This module has no dependencies on the rest of the backend, so both
``cube.py`` and ``cubie.py`` can import it without circular imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

#: (face, index) - face in "URFDLB", index 0..8 in reading order (4 = centre).
StickerRef = Tuple[str, int]


class IssueCode:
    """Every kind of problem validation can report, in the order it checks them."""

    INVALID_COLOR = "invalid_color"          # a sticker has an unknown colour code
    DUPLICATE_CENTERS = "duplicate_centers"  # two faces have the same centre colour
    COLOR_COUNT = "color_count"              # a colour does not appear exactly 9 times
    IMPOSSIBLE_CORNER = "impossible_corner"  # 3 corner stickers no real corner has
    IMPOSSIBLE_EDGE = "impossible_edge"      # 2 edge stickers no real edge has
    DUPLICATE_CORNER = "duplicate_corner"    # the same corner appears more than once
    MISSING_CORNER = "missing_corner"        # a corner does not appear at all
    DUPLICATE_EDGE = "duplicate_edge"
    MISSING_EDGE = "missing_edge"
    CORNER_TWIST = "corner_twist"            # total corner twist is not 0 (mod 3)
    EDGE_FLIP = "edge_flip"                  # total edge flip is not 0 (mod 2)
    PARITY = "parity"                        # corner and edge permutation parity differ


@dataclass(frozen=True)
class ValidationIssue:
    """One reason why a cube is not a real, solvable cube."""

    code: str
    message: str
    stickers: Tuple[StickerRef, ...] = ()
    pieces: Tuple[str, ...] = ()
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "stickers": [{"face": face, "index": index} for face, index in self.stickers],
            "pieces": list(self.pieces),
            "details": dict(self.details),
        }


@dataclass
class ValidationResult:
    """All issues found in a cube. ``ok`` is True only when there are none."""

    issues: List[ValidationIssue] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues

    @property
    def errors(self) -> List[str]:
        """Plain messages, kept for existing callers (logs, solver, CLI tools)."""
        return [issue.message for issue in self.issues]

    def codes(self) -> List[str]:
        return [issue.code for issue in self.issues]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "errors": self.errors,
            "warnings": list(self.warnings),
            "issues": [issue.to_dict() for issue in self.issues],
        }
