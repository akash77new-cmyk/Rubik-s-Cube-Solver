"""Command-line cube solver (the original OpenCV-window workflow).

This is the terminal-only entry point that predates the web UI. It now delegates
to :mod:`backend.core` and :mod:`backend.vision` instead of carrying its own copy
of the classifier, the move tables and the solver, so both front ends always
agree about how a cube is read and solved.

    python "python code files/cube_solver.py"

Keys
----
``u r f d l b``  capture that face
``space``        advance one move while executing the solution
``r``            reset the scan
``esc``          quit
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import cv2

from backend.config import settings_store
from backend.core.color import profile_store
from backend.core.cube import FACE_ORDER, CubeState, InvalidCubeError
from backend.core.moves import FACE_NAMES, expand_for_physical_turns
from backend.core.solver import SolveFailedError, solver_engine
from backend.ipc.client import EngineClient
from backend.vision.camera import CameraStream
from backend.vision.detector import FaceDetector
from backend.vision.overlay import OverlayRenderer

WINDOW = "Cube Solver"


def _print_face(face: str, colors: list[str]) -> None:
    print(f"[ok] scanned {face} ({FACE_NAMES[face]}):")
    for row in range(3):
        print("      " + " ".join(colors[row * 3 : row * 3 + 3]))


def main() -> int:
    settings = settings_store.current
    camera = CameraStream(
        index=settings.camera_index,
        width=settings.frame_width,
        height=settings.frame_height,
        target_fps=settings.target_fps,
        mirror=settings.mirror_camera,
    )
    if not camera.start():
        print(f"[error] could not open camera {settings.camera_index}")
        return 1

    detector = FaceDetector(
        profile=profile_store.get(settings.active_profile),
        spacing=settings.grid_spacing,
        sample_radius=settings.sample_radius,
        offset_y=settings.grid_offset_y,
    )
    overlay = OverlayRenderer(style=settings.arrow_style)

    # Optional: mirror state to a running viewer/engine over the socket bridge.
    bridge = EngineClient(want_frames=False)
    bridge.start()

    print("Press u r f d l b to capture a face, r to reset, ESC to quit.")
    scanned: dict[str, list[str]] = {}
    last_id = -1

    try:
        while len(scanned) < 6:
            frame, last_id = camera.wait_for_frame(last_id, timeout=1.0)
            if frame is None:
                continue
            result = detector.detect(frame)
            pending = [f for f in FACE_ORDER if f not in scanned]
            overlay.draw_detection(frame, result, min_confidence=settings.min_confidence)
            overlay.draw_scan_banner(frame, pending[0] if pending else None, list(scanned), result)
            overlay.draw_hud(frame, camera.fps, "scan")
            cv2.imshow(WINDOW, frame)

            key = cv2.waitKey(1) & 0xFF
            if key == 27:
                return 0
            if key == ord("r"):
                scanned.clear()
                print("[info] scan reset")
                continue
            char = chr(key).upper() if 32 <= key < 127 else ""
            if char in FACE_ORDER:
                scanned[char] = result.colors
                _print_face(char, result.colors)
                detector.reset_stability()

        # ------------------------------------------------------------------
        try:
            cube = CubeState({face: scanned[face] for face in FACE_ORDER})
        except InvalidCubeError as exc:
            print(f"[error] {exc}")
            return 1

        validation = cube.validate()
        if not validation.ok:
            print("[error] scanned cube is not valid:")
            for problem in validation.errors:
                print(f"        - {problem}")
            return 1

        print(f"[info] facelet string: {cube.to_facelet_string()}")
        print("[info] running Kociemba two-phase search (first run builds tables)...")
        try:
            solution = solver_engine.solve(cube, wait_for_warmup=None)
        except SolveFailedError as exc:
            print(f"[error] solve failed: {exc}")
            return 1

        print(f"[ok] {solution.move_count} moves in {solution.elapsed_ms:.1f} ms "
              f"via {solution.backend}")
        print(f"     {solution.notation}")
        print(f"     physical steps: {' '.join(expand_for_physical_turns(solution.moves))}")

        # ------------------------------------------------------------------
        index = 0
        state = cube
        bridge.send("sync", {})
        while index < len(solution.moves):
            frame, last_id = camera.wait_for_frame(last_id, timeout=1.0)
            if frame is None:
                continue
            move = solution.moves[index]
            overlay.draw_move(
                frame, move, index=index, total=len(solution.moves), turn_back=move.face == "B"
            )
            overlay.draw_hud(frame, camera.fps, "execute")
            cv2.imshow(WINDOW, frame)

            key = cv2.waitKey(1) & 0xFF
            if key == 27:
                return 0
            if key == ord(" "):
                state = state.apply(move)
                print(f"[ok] {index + 1}/{len(solution.moves)}  {move.notation}  ({move.label})")
                index += 1

        print("[done] cube solved.")
        while True:
            frame, last_id = camera.wait_for_frame(last_id, timeout=1.0)
            if frame is None:
                break
            overlay.draw_scan_banner(frame, None, list(FACE_ORDER))
            cv2.imshow(WINDOW, frame)
            if (cv2.waitKey(1) & 0xFF) == 27:
                break
        return 0
    finally:
        bridge.stop()
        camera.stop()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    raise SystemExit(main())
