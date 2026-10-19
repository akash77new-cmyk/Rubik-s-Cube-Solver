"""Standalone cube-state viewer (the original second OpenCV window).

Subscribes to the vision engine over the socket bridge and draws the unfolded
net of whatever cube state the engine currently holds - the terminal-only
equivalent of the web UI's Cube Viewer page.

    python -m backend.engine                    # terminal 1
    python "python code files/cube_viewer.py"   # terminal 2

The original version listened on port 9999 and unpickled whatever arrived.
It now *connects* to the engine and speaks the length-prefixed JSON protocol in
:mod:`backend.ipc.protocol`, so there is no arbitrary-code-execution risk and no
truncated-message corruption.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Any, Dict, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import cv2
import numpy as np

from backend.ipc.client import EngineClient
from backend.vision.overlay import COLOR_BGR, draw_glass_panel, draw_text

WINDOW = "Rubik's Cube State Viewer"
CELL = 46
GAP = 4
FACE = CELL * 3 + GAP * 2

#: Column/row of each face in the unfolded net.
NET = {"U": (1, 0), "L": (0, 1), "F": (1, 1), "R": (2, 1), "B": (3, 1), "D": (1, 2)}

MARGIN = 30
WIDTH = MARGIN * 2 + FACE * 4 + 24 * 3
HEIGHT = MARGIN * 2 + FACE * 3 + 24 * 2 + 60


def render(facelets: Optional[Dict[str, list]], status: str) -> np.ndarray:
    canvas = np.full((HEIGHT, WIDTH, 3), 14, np.uint8)

    for face, (col, row) in NET.items():
        ox = MARGIN + col * (FACE + 24)
        oy = MARGIN + 46 + row * (FACE + 24)
        cv2.rectangle(canvas, (ox - 5, oy - 5), (ox + FACE + 5, oy + FACE + 5), (48, 42, 38), 1)
        draw_text(canvas, face, (ox, oy - 10), 0.5, (150, 150, 165), 1, shadow=False)

        stickers = (facelets or {}).get(face)
        for index in range(9):
            r, c = divmod(index, 3)
            x = ox + c * (CELL + GAP)
            y = oy + r * (CELL + GAP)
            code = stickers[index] if stickers and index < len(stickers) else None
            color = COLOR_BGR.get(code, (42, 42, 52))
            cv2.rectangle(canvas, (x, y), (x + CELL, y + CELL), color, -1, cv2.LINE_AA)
            cv2.rectangle(canvas, (x, y), (x + CELL, y + CELL), (18, 18, 22), 1, cv2.LINE_AA)

    draw_glass_panel(canvas, (MARGIN - 6, 12, WIDTH - (MARGIN - 6) * 2, 34), alpha=0.5, radius=12)
    draw_text(canvas, status, (MARGIN + 6, 35), 0.55, (235, 235, 245), 1)
    draw_text(canvas, "ESC to quit", (WIDTH - 130, HEIGHT - 18), 0.45, (120, 120, 140), 1)
    return canvas


def main() -> int:
    state: Dict[str, Any] = {"facelets": None, "status": "connecting to engine..."}
    lock = threading.Lock()

    def on_event(event: str, data: Any) -> None:
        with lock:
            if event == "state" and isinstance(data, dict):
                cube = data.get("cube")
                playback = data.get("playback") or {}
                state["facelets"] = (playback.get("cube") or (cube or {}).get("facelets"))
                mode = data.get("mode", "idle")
                scanned = (data.get("scan") or {}).get("count", 0)
                state["status"] = f"mode: {mode}   faces: {scanned}/6"
            elif event == "engine:connected":
                state["status"] = "connected to vision engine"
            elif event == "engine:disconnected":
                state["status"] = "engine disconnected - retrying..."
                state["facelets"] = None

    client = EngineClient(want_frames=False)
    client.add_handler(on_event)
    client.start()

    try:
        while True:
            with lock:
                frame = render(state["facelets"], state["status"])
            cv2.imshow(WINDOW, frame)
            if (cv2.waitKey(30) & 0xFF) == 27:
                break
            if cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                break
    finally:
        client.stop()
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
