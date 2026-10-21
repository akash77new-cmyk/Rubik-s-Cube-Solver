#!/usr/bin/env python
"""End-to-end verification of the whole pipeline.

    python tools/verify.py            # offline checks only
    python tools/verify.py --live     # also drive a running app over Socket.IO
    python tools/verify.py --live --expect-db postgresql   # ... and require Postgres

Offline checks need nothing running. The ``--live`` pass expects
``python run.py --headless`` in another terminal and exercises the real
browser-facing path: Socket.IO command in, engine event out.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Callable, List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

PASS, FAIL = "PASS", "FAIL"
results: List[Tuple[str, str, str]] = []


def check(name: str) -> Callable:
    """Decorator that runs a check and records PASS/FAIL plus a detail line."""

    def wrapper(function: Callable[[], str]) -> Callable[[], str]:
        try:
            detail = function()
            results.append((PASS, name, detail))
        except AssertionError as exc:
            results.append((FAIL, name, str(exc)))
        except Exception as exc:  # noqa: BLE001 - report, never abort the suite
            results.append((FAIL, name, f"{type(exc).__name__}: {exc}"))
        return function

    return wrapper


# ======================================================================
# Offline checks
# ======================================================================

def run_offline() -> None:
    from backend.core.cube import CubeState, random_scramble
    from backend.core.moves import (
        expand_for_physical_turns,
        invert_sequence,
        parse_sequence,
    )

    @check("cube model · scramble then inverse returns to solved")
    def _() -> str:
        for seed in range(200):
            scramble = random_scramble(25, seed=seed)
            state = CubeState.solved().apply_sequence(scramble)
            assert not state.is_solved, f"seed {seed} produced a solved cube"
            state = state.apply_sequence(invert_sequence(scramble))
            assert state.is_solved, f"seed {seed} did not return to solved"
        return "200 random 25-move scrambles round-tripped"

    @check("cube model · every face turn has order 4")
    def _() -> str:
        for face in "URFDLB":
            state = CubeState.solved()
            for _ in range(4):
                state = state.apply(face)
            assert state.is_solved, f"{face}x4 is not the identity"
        return "U R F D L B all return to solved after four turns"

    @check("cube model · (R U R' U')x6 is the identity")
    def _() -> str:
        state = CubeState.solved().apply_sequence("R U R' U' " * 6)
        assert state.is_solved, "sexy move x6 did not return to solved"
        return "well-known 6-cycle verified"

    @check("cube model · validation rejects an impossible cube")
    def _() -> str:
        facelets = CubeState.solved().facelets
        facelets["U"][0] = "R"  # ten reds, eight whites
        assert not CubeState(facelets).validate().ok, "invalid cube passed validation"
        return "colour-count violation detected"

    @check("cube validation · twist, flip and parity are caught")
    def _() -> str:
        from backend.core.cube import DEFAULT_SCHEME
        from backend.core.cubie import CubieCube

        def cube_from(cubie: CubieCube) -> CubeState:
            letters = cubie.to_facelet_string()
            return CubeState.from_color_string("".join(DEFAULT_SCHEME[f] for f in letters))

        solved = CubieCube.solved()
        cases = {
            "corner_twist": CubieCube(solved.cp, (1,) + (0,) * 7, solved.ep, solved.eo),
            "edge_flip": CubieCube(solved.cp, solved.co, solved.ep, (1,) + (0,) * 11),
            "parity": CubieCube(solved.cp, solved.co, (1, 0) + tuple(range(2, 12)), solved.eo),
        }
        for code, cubie in cases.items():
            codes = cube_from(cubie).validate().codes()
            assert codes == [code], f"{code}: got {codes}"
        return "a twisted corner, a flipped edge and a two-piece swap are each rejected"

    @check("move notation · physical expansion of back-face turns")
    def _() -> str:
        cases = {
            "B": ["TURN_BACK", "F", "TURN_BACK"],
            "B'": ["TURN_BACK", "F'", "TURN_BACK"],
            "B2": ["TURN_BACK", "F", "F", "TURN_BACK"],
            "R2": ["R", "R"],
            "U'": ["U'"],
        }
        for notation, expected in cases.items():
            actual = expand_for_physical_turns(parse_sequence(notation))
            assert actual == expected, f"{notation} -> {actual}, expected {expected}"
        return "B / B' / B2 / R2 / U' expand as the original implementation did"

    # ------------------------------------------------------------------
    from backend.ipc.protocol import MessageReader, encode_frame, encode_json

    @check("socket protocol · framing survives arbitrary chunk splits")
    def _() -> str:
        blob = encode_json({"event": "state"}) + encode_frame(b"\xff\xd8jpeg\xff\xd9") \
            + encode_json({"event": "log", "data": "x" * 500})
        reader = MessageReader()
        messages = []
        for offset in range(0, len(blob), 7):  # deliberately awkward chunk size
            messages.extend(reader.feed(blob[offset : offset + 7]))
        kinds = [kind for kind, _ in messages]
        assert kinds == [b"J", b"F", b"J"], f"got {kinds}"
        return "3 messages reassembled from 7-byte chunks"

    # ------------------------------------------------------------------
    import numpy as np
    import cv2
    from backend.vision.detector import FaceDetector
    from backend.vision.overlay import COLOR_BGR, OverlayRenderer
    from backend.core.moves import Move

    @check("HSV segmentation · classifies a synthetic cube face")
    def _() -> str:
        codes = ["R", "G", "B", "W", "Y", "O", "G", "R", "B"]
        width, height, spacing = 960, 720, 96
        frame = np.full((height, width, 3), 28, np.uint8)
        for index, code in enumerate(codes):
            row, col = divmod(index, 3)
            x = width // 2 + (col - 1) * spacing
            y = height // 2 + (row - 1) * spacing
            cv2.rectangle(frame, (x - 42, y - 42), (x + 42, y + 42), COLOR_BGR[code], -1)

        detector = FaceDetector(spacing=spacing, sample_radius=10)
        for _ in range(6):  # fill the stability window
            result = detector.detect(frame.copy())
        assert result.colors == codes, f"detected {result.colors}, expected {codes}"
        assert result.stable, "read never stabilised"
        return f"9/9 correct, mean confidence {result.mean_confidence:.2f}, stable"

    @check("overlays · HUD and move arrows render without error")
    def _() -> str:
        frame = np.full((720, 960, 3), 28, np.uint8)
        detector = FaceDetector(spacing=96)
        result = detector.detect(frame)
        overlay = OverlayRenderer("neon")
        overlay.draw_detection(frame.copy(), result)
        overlay.draw_scan_banner(frame.copy(), "F", ["U", "R"], result)
        for face in "URFDLB":
            for modifier in ("", "'", "2"):
                overlay.draw_move(frame.copy(), Move(face, modifier), index=0, total=20)
        overlay.draw_move(frame.copy(), Move("B"), turn_back=True)
        return "18 move arrows + scan HUD + turn-back hint drawn"

    def memory_stores() -> dict:
        """Stores on a fresh in-memory database (built by the real migrations)."""
        from backend.db import connect
        from backend.services.analytics import AnalyticsStore
        from backend.services.profiles import ProfileStore
        from backend.services.settings import SettingsStore

        database = connect("sqlite://")
        return {
            "settings": SettingsStore(database),
            "profiles": ProfileStore(database),
            "analytics": AnalyticsStore(database),
            "database": database,
        }

    @check("database · migrations build the schema; data survives a restart")
    def _() -> str:
        import tempfile

        from alembic.autogenerate import compare_metadata
        from alembic.migration import MigrationContext

        from backend.core.color import ColorProfile
        from backend.db import connect, head_revision
        from backend.db.models import Base
        from backend.services.analytics import AnalyticsStore, SolveRecord
        from backend.services.profiles import ProfileStore
        from backend.services.settings import SettingsStore

        # ignore_cleanup_errors: on Windows a failed check could leave the file open.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            url = f"sqlite:///{Path(tmp, 'verify.db').as_posix()}"
            first = connect(url)  # a brand-new database: every migration runs
            status = first.status()
            assert status["schemaRevision"] == head_revision(), f"schema at {status['schemaRevision']}"
            with first.engine.connect() as connection:
                diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
            assert not diff, f"models.py and the migrations disagree: {diff}"

            SettingsStore(first).update({"target_fps": 24})
            ProfileStore(first).save(ColorProfile(name="verify-lamp"))
            now = time.time()
            AnalyticsStore(first).record(SolveRecord(
                id="verify1", started_at=now - 60, finished_at=now, move_count=20,
                quarter_turns=24, solve_ms=3.5, scan_seconds=30.0, execution_seconds=60.0,
                backend="test", notation="R U",
            ))
            first.dispose()

            second = connect(url)  # like restarting the app
            assert SettingsStore(second).current.target_fps == 24, "settings were not kept"
            assert "verify-lamp" in ProfileStore(second).names(), "profile was not kept"
            history = AnalyticsStore(second).summary()
            assert history["totalSolves"] == 1, "solve history was not kept"
            second.dispose()
        return f"schema {head_revision()} matches models.py; settings, a profile and a solve survived a restart"

    @check("dataset · a scanned cube is saved as 54 labelled sticker crops")
    def _() -> str:
        import json
        import tempfile

        from backend.core.cube import FACE_ORDER
        from backend.core.solver import SolverEngine
        from backend.services.dataset import DatasetStore
        from backend.services.logbus import LogBus
        from backend.services.session import SolveSession

        def face_frame(codes: List[str]) -> "np.ndarray":
            frame = np.full((720, 960, 3), 28, np.uint8)
            for index, code in enumerate(codes):
                row, col = divmod(index, 3)
                x, y = 480 + (col - 1) * 96, 360 + (row - 1) * 96
                cv2.rectangle(frame, (x - 42, y - 42), (x + 42, y + 42), COLOR_BGR[code], -1)
            return frame

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session = SolveSession(
                **memory_stores(),
                solver=SolverEngine(),
                logs=LogBus(),
                publish_event=lambda event, data: None,
                publish_frame=lambda jpeg: None,
                dataset=DatasetStore(root / "dataset"),
            )
            cube = CubeState.solved().apply_sequence(random_scramble(20, seed=5))
            for face in FACE_ORDER:
                session._process_frame(face_frame(cube.face(face)))  # real detector
                assert session.capture_face(face)["ok"], f"capture of {face} failed"
            result = session.save_to_dataset("daylight")
            assert result["ok"], result.get("error")
            folder = root / "dataset" / "scans" / result["id"]
            record = json.loads((folder / "scan.json").read_text("utf-8"))
            pngs = len(list(folder.glob("*.png")))
            assert pngs == 54, f"{pngs} crops written"
            wrong = [s["file"] for s in record["stickers"]
                     if s["label"] != cube.face(s["face"])[s["index"]]]
            assert not wrong, f"wrong labels: {wrong}"
        return "6 synthetic faces scanned by the real detector -> 54 PNGs, all labels correct"

    @check("guided scan · any order, mirrored preview, 1 s hold, a rotated face -> the right cube")
    def _() -> str:
        from backend.core.cube import FACE_ORDER
        from backend.core.scanning import orientation_map, reorder
        from backend.core.solver import SolverEngine
        from backend.services.logbus import LogBus
        from backend.services.session import SolveSession

        def face_frame(codes: List[str]) -> "np.ndarray":
            frame = np.full((720, 960, 3), 28, np.uint8)
            for index, code in enumerate(codes):
                row, col = divmod(index, 3)
                x, y = 480 + (col - 1) * 96, 360 + (row - 1) * 96
                cv2.rectangle(frame, (x - 42, y - 42), (x + 42, y + 42), COLOR_BGR[code], -1)
            return cv2.flip(frame, 1)  # a selfie-style (mirrored) camera preview

        events: List[str] = []
        session = SolveSession(
            **memory_stores(),
            solver=SolverEngine(),
            logs=LogBus(),
            publish_event=lambda event, data: events.append(event),
            publish_frame=lambda jpeg: None,
        )
        clock = [0.0]
        session._clock = lambda: clock[0]  # fake clock: 30 frames per second below
        session.handle_command("scan.auto", {"enabled": True})  # manual is the default
        session.start_scan(open_camera=False)
        cube = CubeState.solved().apply_sequence(random_scramble(20, seed=8))
        for face in ["D", "B", "F", "U", "L", "R"]:  # not the guide's order
            colors = cube.face(face)
            if face == "L":
                colors = reorder(colors, orientation_map(1))  # held a quarter turn off
            frame = face_frame(colors)
            for number in range(45):  # 1.5 s held still: captured once, after the hold
                session._process_frame(frame.copy(), mirrored=True)
                clock[0] += 1 / 30
                if number == 26:  # 0.9 s: the read is stable, but the 1 s hold is not over
                    assert face not in session._scanned, f"{face} captured before the hold"
        scanned = {f: session._scanned[f]["colors"] for f in FACE_ORDER}
        assert scanned == {f: cube.face(f) for f in FACE_ORDER}, "scanned cube is wrong"
        assert "scan:repaired" in events, "the rotated face was not repaired"
        return (
            "6 faces in random order through a mirrored preview, each captured after a 1 s "
            "hold, 1 held rotated -> exact cube"
        )

    # ------------------------------------------------------------------
    from backend.core.solver import solver_engine

    @check("solver · solutions are correct when replayed onto the cube")
    def _() -> str:
        assert solver_engine.warm_up(600), f"solver never became ready: {solver_engine.status()['message']}"
        lengths = []
        for length in (6, 12, 18, 25):
            scramble = random_scramble(length, seed=length)
            cube = CubeState.solved().apply_sequence(scramble)
            solution = solver_engine.solve(cube)
            replayed = cube.apply_sequence(solution.moves)
            assert replayed.is_solved, f"solution for a {length}-move scramble does not solve it"
            assert solution.move_count <= 22, f"solution too long: {solution.move_count}"
            assert len(solution.states) == solution.move_count + 1, "state trace length mismatch"
            lengths.append(solution.move_count)
        backend = solver_engine.status()["backend"]
        return f"4 cubes solved and verified via {backend}; move counts {lengths}"


# ======================================================================
# Live checks
# ======================================================================

def run_live(url: str, expect_db: str | None = None) -> None:
    try:
        import socketio  # type: ignore
    except ImportError:
        results.append((FAIL, "live · socket.io client", "pip install 'python-socketio[client]'"))
        return

    state: dict = {}
    logs: list = []
    client = socketio.Client()
    client.on("state", lambda data: state.update(data))
    client.on("log", lambda entry: logs.append(entry))

    def command(name: str, payload: dict | None = None, settle: float = 0.5) -> None:
        client.emit("command", {"command": name, "payload": payload or {}})
        time.sleep(settle)

    def wait_for(condition: Callable[[], bool], timeout: float = 5.0) -> bool:
        """Poll until condition() is true. A save to a remote database (Neon from a
        laptop: ~0.5 s) takes longer than the fixed settle time."""
        deadline = time.time() + timeout
        while not condition():
            if time.time() > deadline:
                return False
            time.sleep(0.05)
        return True

    @check("live · Socket.IO connects and receives a state snapshot")
    def _() -> str:
        client.connect(url, wait_timeout=15)
        time.sleep(1.5)
        assert state, "no state event received"
        return f"mode={state['mode']}, solver={state['solver']['backend']}"

    @check("live · scramble produces a valid cube")
    def _() -> str:
        command("cube.scramble", {"length": 22})
        assert state["validation"]["ok"], state["validation"]["errors"]
        assert state["scan"]["count"] == 6, "scan did not report six faces"
        return f"source={state['cubeSource']}, centres={''.join(state['cube']['centers'].values())}"

    @check("live · solve returns a solution with a per-move state trace")
    def _() -> str:
        command("solve.run")
        for _ in range(300):
            if state.get("solution"):
                break
            time.sleep(0.1)
        solution = state.get("solution")
        assert solution, "no solution arrived"
        assert len(solution["states"]) == solution["moveCount"] + 1, "state trace mismatch"
        return f"{solution['moveCount']} moves in {solution['elapsedMs']:.1f} ms"

    @check("live · stepping through playback solves the cube and records analytics")
    def _() -> str:
        total = state["solution"]["moveCount"]
        command("playback.next", settle=0.3)  # the hold-the-cube step comes before move 1
        assert state["playback"]["ready"] and state["playback"]["index"] == 0, "no hold step"
        for _ in range(total):
            command("playback.next", settle=0.12)
        time.sleep(0.6)
        assert state["playback"]["completed"], "playback did not complete"
        final = CubeStateFromDict(state["playback"]["cube"])
        assert final.is_solved, "cube is not solved at the end of playback"
        assert state["analytics"]["totalSolves"] >= 1, "no analytics record written"
        return (
            f"hold step, then {total} moves executed, cube verified solved, "
            f"{state['analytics']['totalSolves']} solve(s) recorded"
        )

    @check("live · calibration and settings round-trip through the engine")
    def _() -> str:
        command("calibration.start")
        command("calibration.target", {"color": "B"})
        command("calibration.range", {"color": "B", "h_min": 97})
        assert state["calibration"]["ranges"]["B"]["h_min"] == 97, "HSV edit did not stick"
        command("calibration.stop")
        original = state["settings"]["target_fps"]
        command("settings.update", {"target_fps": 24})
        assert wait_for(lambda: state["settings"]["target_fps"] == 24), "settings update did not stick"
        command("settings.update", {"target_fps": original})
        assert wait_for(lambda: state["settings"]["target_fps"] == original), "settings were not restored"
        return "HSV range + settings persisted via the socket bridge"

    @check("live · database connected, schema up to date")
    def _() -> str:
        from backend.db import head_revision

        database = state.get("database")
        assert database, "the engine reported no database"
        assert database["connected"], f"database not reachable: {database['error']}"
        assert database["schemaRevision"] == head_revision(), (
            f"schema {database['schemaRevision']}, code expects {head_revision()}"
        )
        if expect_db:
            assert database["backend"].lower() == expect_db, f"expected {expect_db}, got {database['backend']}"
        extra = f", pgvector {database['pgvector']} available" if database["pgvector"] else ""
        provider = f" ({database['provider']})" if database["provider"] else ""
        return (
            f"{database['backend']} {database['serverVersion']}{provider} at {database['location']}, "
            f"schema {database['schemaRevision']}{extra}"
        )

    @check("live · engine streams structured logs")
    def _() -> str:
        assert logs, "no log entries streamed"
        sources = sorted({entry["source"] for entry in logs})
        return f"{len(logs)} entries from {sources}"

    try:
        client.disconnect()
    except Exception:
        pass


def CubeStateFromDict(facelets):  # noqa: N802 - tiny local helper
    from backend.core.cube import CubeState

    return CubeState(facelets)


# ======================================================================

def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the cube solver pipeline")
    parser.add_argument("--live", action="store_true", help="also test a running app")
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--expect-db", choices=["postgresql", "sqlite"],
        help="with --live: fail unless the app uses this database",
    )
    args = parser.parse_args(argv)

    print("Rubik's Cube Solver - verification\n" + "=" * 72)
    run_offline()
    if args.live:
        run_live(args.url, args.expect_db)

    print()
    for status, name, detail in results:
        mark = "✓" if status == PASS else "✗"
        print(f"  [{mark}] {name}")
        print(f"      {detail}")

    failed = [r for r in results if r[0] == FAIL]
    print("\n" + "=" * 72)
    print(f"{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
