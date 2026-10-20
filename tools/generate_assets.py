#!/usr/bin/env python
"""Generate the project's vector art.

Everything under ``assets/`` is produced from this one script, so the arrow set
stays visually consistent and a colour tweak is a one-line change rather than
eighteen hand-edited files.

    python tools/generate_assets.py            # write SVGs
    python tools/generate_assets.py --png      # also rasterise crisp PNGs

PNG rasterisation shells out to ``node tools/rasterize.mjs`` (sharp). It is
optional: the app itself only ever uses the SVGs.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from typing import Dict, List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ASSETS = PROJECT_ROOT / "assets"

# --------------------------------------------------------------------------------------
# Design tokens - mirrored in frontend/src/styles/tokens.css
# --------------------------------------------------------------------------------------

STICKER_COLORS: Dict[str, Tuple[str, str, str]] = {
    # code: (base, highlight, shadow)
    "white": ("#F8FAFC", "#FFFFFF", "#CBD5E1"),
    "yellow": ("#FACC15", "#FDE68A", "#CA8A04"),
    "red": ("#EF4444", "#FCA5A5", "#B91C1C"),
    "orange": ("#F97316", "#FDBA74", "#C2410C"),
    "green": ("#22C55E", "#86EFAC", "#15803D"),
    "blue": ("#3B82F6", "#93C5FD", "#1D4ED8"),
}

ACCENT = "#8B5CF6"
ACCENT_2 = "#22D3EE"
INK = "#0B0B12"
GRID_IDLE = "#2A2A3A"
GRID_EDGE = "#3F3F55"

FACES = ("U", "R", "F", "D", "L", "B")
MODIFIERS = ("", "'", "2")

#: Filename-safe token for a move (``R'`` -> ``Rp``, ``R2`` -> ``R2``).
def slug(move: str) -> str:
    return move.replace("'", "p")


# --------------------------------------------------------------------------------------
# Shared SVG fragments
# --------------------------------------------------------------------------------------

def _defs(uid: str) -> str:
    """Gradients, glow filter and arrowhead marker shared by every arrow."""
    return f"""  <defs>
    <!-- userSpaceOnUse is required: a straight horizontal/vertical arrow has a
         zero-area bounding box, and an objectBoundingBox gradient on a
         degenerate bbox makes the element disappear entirely. -->
    <linearGradient id="grad{uid}" gradientUnits="userSpaceOnUse"
                    x1="0" y1="0" x2="256" y2="256">
      <stop offset="0%" stop-color="{ACCENT_2}"/>
      <stop offset="100%" stop-color="{ACCENT}"/>
    </linearGradient>
    <linearGradient id="head-grad{uid}" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="{ACCENT_2}"/>
      <stop offset="100%" stop-color="{ACCENT}"/>
    </linearGradient>
    <linearGradient id="face{uid}" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#1B1B29"/>
      <stop offset="100%" stop-color="#12121C"/>
    </linearGradient>
    <!-- userSpaceOnUse for the same reason as the gradient: the default
         objectBoundingBox filter region collapses to nothing on a straight line. -->
    <filter id="glow{uid}" filterUnits="userSpaceOnUse"
            x="-40" y="-40" width="336" height="336">
      <feGaussianBlur stdDeviation="7" result="blur"/>
      <feMerge>
        <feMergeNode in="blur"/>
        <feMergeNode in="SourceGraphic"/>
      </feMerge>
    </filter>
    <!-- userSpaceOnUse: the default markerUnits scales the head by stroke-width,
         which would blow it up to ~65 units and clip it outside the viewBox. -->
    <marker id="head{uid}" viewBox="0 0 12 12" refX="8.5" refY="6"
            markerWidth="28" markerHeight="28" markerUnits="userSpaceOnUse"
            orient="auto-start-reverse">
      <path d="M1.5 1 L11 6 L1.5 11 Z" fill="url(#head-grad{uid})"/>
    </marker>
  </defs>
"""


def _cube_face(highlight: List[int], dashed: bool = False, full_face: bool = False) -> str:
    """A 3x3 face; cells listed in ``highlight`` glow with the accent gradient.

    ``full_face`` (F/B turns) lights all nine cells, so their opacity is held
    back to keep the arrow drawn on top of them legible.
    """
    cells: List[str] = []
    size, gap, origin = 52, 10, 46
    for row in range(3):
        for col in range(3):
            index = row * 3 + col
            x = origin + col * (size + gap)
            y = origin + row * (size + gap)
            active = index in highlight
            fill = "url(#gradA)" if active else GRID_IDLE
            opacity = ("0.40" if full_face else "0.92") if active else "0.55"
            stroke = ACCENT if active else GRID_EDGE
            cells.append(
                f'    <rect x="{x}" y="{y}" width="{size}" height="{size}" rx="12" '
                f'fill="{fill}" fill-opacity="{opacity}" stroke="{stroke}" '
                f'stroke-width="2"/>'
            )
    dash = ' stroke-dasharray="10 8"' if dashed else ""
    frame = (
        f'    <rect x="34" y="34" width="188" height="188" rx="26" fill="url(#faceA)" '
        f'stroke="{GRID_EDGE}" stroke-width="3"{dash}/>'
    )
    return frame + "\n" + "\n".join(cells)


def _straight_arrow(
    x1: float, y1: float, x2: float, y2: float, double: bool
) -> str:
    """Neon straight arrow, optionally double-headed (for 180° turns)."""
    start_marker = ' marker-start="url(#headA)"' if double else ""
    return (
        f'    <path d="M{x1} {y1} L{x2} {y2}" fill="none" stroke="url(#gradA)" '
        f'stroke-width="12" stroke-linecap="round" filter="url(#glowA)" '
        f'marker-end="url(#headA)"{start_marker}/>'
    )


def _curved_arrow(clockwise: bool, double: bool) -> str:
    """Circular arrow used for F/B (the face pointing at the viewer)."""
    if clockwise:
        path = "M 76 128 A 52 52 0 1 1 128 180"
    else:
        path = "M 180 128 A 52 52 0 1 0 128 180"
    start_marker = ' marker-start="url(#headA)"' if double else ""
    return (
        f'    <path d="{path}" fill="none" stroke="url(#gradA)" stroke-width="15" '
        f'stroke-linecap="round" filter="url(#glowA)" marker-end="url(#headA)"'
        f"{start_marker}/>"
    )


def _badge(text: str, face: str) -> str:
    """'180' pill, placed in whichever corner the arrow does not occupy."""
    x, y = (16, 8) if face == "D" else (16, 208)
    return (
        f'    <g transform="translate({x} {y})">\n'
        f'      <rect x="0" y="0" width="62" height="34" rx="12" fill="{ACCENT}" '
        f'fill-opacity="0.28" stroke="{ACCENT}" stroke-width="2"/>\n'
        f'      <text x="31" y="24" text-anchor="middle" font-family="Inter,'
        f'Segoe UI,sans-serif" font-size="18" font-weight="700" fill="#E9E7FF">'
        f"{text}</text>\n"
        f"    </g>"
    )


# --------------------------------------------------------------------------------------
# Arrow generation
# --------------------------------------------------------------------------------------

#: Which cells of the 3x3 face each turn moves.
LAYER_CELLS: Dict[str, List[int]] = {
    "U": [0, 1, 2],
    "D": [6, 7, 8],
    "L": [0, 3, 6],
    "R": [2, 5, 8],
    "F": list(range(9)),
    "B": list(range(9)),
}


def build_arrow_svg(face: str, modifier: str) -> str:
    move = f"{face}{modifier}"
    double = modifier == "2"
    clockwise = modifier != "'"
    highlight = LAYER_CELLS[face]

    body: List[str] = [
        _cube_face(highlight, dashed=face == "B", full_face=face in ("F", "B"))
    ]

    if face in ("F", "B"):
        body.append(_curved_arrow(clockwise, double))
    elif face in ("U", "D"):
        y = 20 if face == "U" else 236
        # The arrow shows the way the layer's front stickers move, seen from the front:
        # U turns them to the left and D to the right (backend.core.moves.TURN_ARROWS).
        rightwards = clockwise if face == "D" else not clockwise
        x1, x2 = (56, 196) if rightwards else (196, 56)
        body.append(_straight_arrow(x1, y, x2, y, double))
    else:  # L / R
        x = 20 if face == "L" else 236
        upwards = clockwise if face == "R" else not clockwise
        y1, y2 = (196, 56) if upwards else (56, 196)
        body.append(_straight_arrow(x, y1, x, y2, double))

    if double:
        body.append(_badge("180°", face))

    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" '
        f'width="256" height="256" role="img" aria-label="{move} turn">\n'
        + _defs("A")
        + "\n".join(body)
        + "\n</svg>\n"
    )


def build_turn_back_svg() -> str:
    """'Rotate the whole cube' hint used when the solver asks for a B move."""
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" '
        'width="256" height="256" role="img" aria-label="Rotate cube 180 degrees">\n'
        + _defs("A")
        + _cube_face([], dashed=True)
        + "\n"
        + '    <path d="M 60 118 A 68 68 0 0 1 196 118" fill="none" '
        'stroke="url(#gradA)" stroke-width="15" stroke-linecap="round" '
        'filter="url(#glowA)" marker-end="url(#headA)"/>\n'
        + '    <text x="128" y="152" text-anchor="middle" font-family="Inter,'
        'Segoe UI,sans-serif" font-size="34" font-weight="800" fill="#E9E7FF">180'
        "</text>\n"
        '    <text x="128" y="184" text-anchor="middle" font-family="Inter,'
        'Segoe UI,sans-serif" font-size="17" font-weight="600" fill="#A5A3C4">'
        "TURN CUBE</text>\n"
        "</svg>\n"
    )


def build_sticker_svg(name: str) -> str:
    base, highlight, shadow = STICKER_COLORS[name]
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128" width="128" height="128" role="img" aria-label="{name} sticker">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="0.6" y2="1">
      <stop offset="0%" stop-color="{highlight}"/>
      <stop offset="55%" stop-color="{base}"/>
      <stop offset="100%" stop-color="{shadow}"/>
    </linearGradient>
    <filter id="s" x="-30%" y="-30%" width="160%" height="160%">
      <feDropShadow dx="0" dy="3" stdDeviation="4" flood-color="#000" flood-opacity="0.35"/>
    </filter>
  </defs>
  <rect x="8" y="8" width="112" height="112" rx="24" fill="{shadow}" opacity="0.5"/>
  <rect x="10" y="8" width="108" height="108" rx="22" fill="url(#g)" filter="url(#s)"/>
  <path d="M22 30 Q34 16 60 16 L96 16 Q78 26 62 40 Q40 44 22 52 Z" fill="#fff" opacity="0.20"/>
</svg>
"""


def build_logo_svg() -> str:
    """Isometric cube mark used in the header and as the favicon."""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128" width="128" height="128" role="img" aria-label="Cube Solver logo">
  <defs>
    <linearGradient id="lt" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#F8FAFC"/><stop offset="100%" stop-color="#CBD5E1"/>
    </linearGradient>
    <linearGradient id="ll" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#F97316"/><stop offset="100%" stop-color="#C2410C"/>
    </linearGradient>
    <linearGradient id="lr" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#22C55E"/><stop offset="100%" stop-color="#15803D"/>
    </linearGradient>
    <linearGradient id="lg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="{ACCENT_2}"/><stop offset="100%" stop-color="{ACCENT}"/>
    </linearGradient>
    <filter id="lglow" x="-40%" y="-40%" width="180%" height="180%">
      <feGaussianBlur stdDeviation="4" result="b"/>
      <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
  </defs>
  <rect x="2" y="2" width="124" height="124" rx="30" fill="{INK}"/>
  <rect x="2" y="2" width="124" height="124" rx="30" fill="url(#lg)" opacity="0.16"/>
  <g filter="url(#lglow)">
    <path d="M64 20 L108 42 L64 64 L20 42 Z" fill="url(#lt)"/>
    <path d="M20 42 L64 64 L64 110 L20 88 Z" fill="url(#ll)"/>
    <path d="M108 42 L108 88 L64 110 L64 64 Z" fill="url(#lr)"/>
  </g>
  <g stroke="{INK}" stroke-opacity="0.45" stroke-width="2.5" fill="none">
    <path d="M49 27 L93 49 M79 27 L35 49"/>
    <path d="M20 57 L64 79 M20 73 L64 95"/>
    <path d="M108 57 L64 79 M108 73 L64 95"/>
    <path d="M35 51 L35 96 M49 58 L49 103"/>
    <path d="M93 51 L93 96 M79 58 L79 103"/>
  </g>
</svg>
"""


# --------------------------------------------------------------------------------------
# Writer
# --------------------------------------------------------------------------------------

def write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def generate() -> List[Path]:
    written: List[Path] = []

    arrows = ASSETS / "arrows"
    for face in FACES:
        for modifier in MODIFIERS:
            move = f"{face}{modifier}"
            written.append(write(arrows / f"{slug(move)}.svg", build_arrow_svg(face, modifier)))
    written.append(write(arrows / "TURN_BACK.svg", build_turn_back_svg()))

    stickers = ASSETS / "stickers"
    for name in STICKER_COLORS:
        written.append(write(stickers / f"{name}.svg", build_sticker_svg(name)))

    written.append(write(ASSETS / "brand" / "logo.svg", build_logo_svg()))
    return written


def rasterize(size: int = 512) -> bool:
    """Optional: render every SVG to PNG with sharp (needs Node + npm i sharp)."""
    script = PROJECT_ROOT / "tools" / "rasterize.mjs"
    if not script.exists():
        print("rasterize.mjs missing - skipping PNG generation")
        return False
    try:
        subprocess.run(
            ["node", str(script), str(ASSETS), str(size)],
            cwd=str(PROJECT_ROOT),
            check=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"PNG rasterisation skipped: {exc}")
        return False


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate project vector assets")
    parser.add_argument("--png", action="store_true", help="also rasterise PNGs")
    parser.add_argument("--size", type=int, default=512)
    args = parser.parse_args(argv)

    written = generate()
    print(f"Wrote {len(written)} SVG assets to {ASSETS}")
    if args.png:
        rasterize(args.size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
