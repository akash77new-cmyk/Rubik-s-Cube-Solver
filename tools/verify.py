#!/usr/bin/env python
"""End-to-end verification of the whole pipeline.

    python tools/verify.py            # offline checks only
    python tools/verify.py --live     # also drive a running app over Socket.IO
    python tools/verify.py --live --expect-db postgresql   # ... and require Postgres
    python tools/verify.py --live --expect-ai gemini       # ... and require a real AI answer

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

    @check("AI · tool-calling agent: answer checked, run traced, built-in answer without a key")
    def _() -> str:
        from backend.ai.agent import FINAL_ANSWER
        from backend.ai.assistant import SnapshotContext
        from backend.ai.budget import RequestBudget
        from backend.ai.fake import ScriptedLLM, tool_call
        from backend.ai.service import AIService
        from backend.ai.tracing import TraceStore
        from backend.core.solver import SolverEngine
        from backend.services.logbus import LogBus
        from backend.services.session import SolveSession

        stores = memory_stores()
        session = SolveSession(
            **stores, solver=SolverEngine(), logs=LogBus(),
            publish_event=lambda event, data: None, publish_frame=lambda jpeg: None,
        )
        session.handle_command("cube.reset", {})  # a solved cube
        context = SnapshotContext(session.snapshot)
        store = TraceStore(stores["database"])

        # A scripted model (tests never call real APIs): one tool call, then the answer.
        llm = ScriptedLLM([tool_call("get_cube_state"), tool_call(FINAL_ANSWER, answer="Your cube is solved.")])
        ai = AIService(llm, RequestBudget(10, 100), store, publish=lambda event, data: None)
        payload = ai.answer("Is my cube solved?", context)
        assert payload["source"] == "scripted", f"answer came from {payload['source']}: {payload['reason']}"
        tool_result = llm.requests[1].messages[-1].tool_results[0].response
        assert tool_result["is_solved"] is True, f"the tool did not read the session: {tool_result}"
        steps = [step["kind"] for step in store.recent(1)[0]["steps"]]
        assert steps == ["model", "tool", "model", "answer"], f"trace steps: {steps}"

        off = AIService(None, RequestBudget(10, 100), store, lambda e, d: None, off_reason="no Gemini API key is set")
        fallback = off.answer("Is my cube solved?", context)
        assert fallback["source"] == "fallback" and "Your cube is solved." in fallback["answer"], fallback
        return "scripted model -> get_cube_state -> schema-checked answer, 4 steps traced; no key -> built-in answer"

    @check("repair · a misread sticker: a proven fix, chosen by the agent, applied -> valid")
    def _() -> str:
        from backend.ai.agent import FINAL_ANSWER
        from backend.ai.budget import RequestBudget
        from backend.ai.fake import ScriptedLLM, tool_call, tool_calls
        from backend.ai.repair_agent import RepairContext
        from backend.ai.service import AIService
        from backend.core.repair import find_repairs
        from backend.core.solver import SolverEngine
        from backend.services.logbus import LogBus
        from backend.services.session import SolveSession

        moves = random_scramble(20, seed=9)
        truth = CubeState.solved().apply_sequence(moves)
        facelets = truth.facelets
        true_color = facelets["U"][1]
        wrong = next(code for code in "WYROGB" if code != true_color)
        facelets["U"][1] = wrong  # what a camera that misread one sticker reports
        scan = CubeState(facelets)
        assert not scan.validate().ok, "the misread cube should be invalid"

        # 1. Code proves: exactly one 1-sticker change makes it valid, and it is the right one.
        search = find_repairs(scan)
        assert search.total == 1 and search.candidates[0].apply(scan) == truth, f"search found {search.total} fixes"

        # 2. The agent (a scripted model: tests never call real APIs) picks that fix by its id.
        llm = ScriptedLLM([
            tool_calls(("get_problems", {}), ("get_suspect_stickers", {}), ("find_fixes", {})),
            tool_call(FINAL_ANSWER, action="apply_fix", fix_id=1, message="Fix 1."),
        ])
        proposal = AIService(llm, RequestBudget(10, 100), None, lambda e, d: None).repair(RepairContext(scan))
        assert proposal["source"] == "scripted" and proposal["changes"][0]["to"] == true_color, proposal

        # 3. The session: repair.start -> a proposal -> repair.apply -> a valid cube.
        session = SolveSession(
            **memory_stores(), solver=SolverEngine(), logs=LogBus(),
            publish_event=lambda event, data: None, publish_frame=lambda jpeg: None,
        )
        session.handle_command("cube.reset", {})
        session.handle_command("cube.apply", {"moves": " ".join(move.notation for move in moves)})
        session.handle_command("cube.sticker", {"face": "U", "index": 1, "color": wrong})
        session.handle_command("repair.start", {})
        assert session.snapshot()["repair"]["status"] == "ready", session.snapshot()["repair"]
        assert session.handle_command("repair.apply", {}) == {"ok": True, "valid": True}
        assert session.snapshot()["validation"]["ok"], "still invalid after Apply"
        return f"1 misread sticker -> {search.total} proven fix -> scripted agent chose it -> Apply -> valid cube"

    @check("RAG · lessons embedded and searched; the coach cites only what it found")
    def _() -> str:
        from backend.ai.agent import FINAL_ANSWER
        from backend.ai.budget import RequestBudget
        from backend.ai.fake import HashEmbedder, ScriptedLLM, tool_call
        from backend.ai.lessons import evaluate, load_lessons
        from backend.ai.retrieval import LessonIndex
        from backend.ai.service import AIService
        from backend.db import connect

        # Test embeddings (tests never call real APIs) in a throwaway SQLite database.
        index = LessonIndex(load_lessons(), connect("sqlite://"), HashEmbedder())
        index.sync()
        assert index.status()["embedded"] == len(index.chunks), index.status()
        vectors = evaluate(lambda q: [hit.chunk.id for hit in index.search(q, 3).hits])
        keywords = evaluate(lambda q: [chunk.id for chunk, _ in index.keywords.search(q, 3)])
        assert vectors["hits"] >= 13 and keywords["hits"] >= 13, (vectors, keywords)

        notation = "02-notation#clockwise-primes-and-doubles"
        llm = ScriptedLLM([
            tool_call("search_lessons", query="What does R prime mean?"),
            tool_call(FINAL_ANSWER, answer="Anticlockwise.", citations=[notation], covered=True),
        ])
        payload = AIService(llm, RequestBudget(10, 100), None, lambda e, d: None, lessons=index).coach_answer(
            "What does R prime mean?"
        )
        assert payload["citations"] == [notation] and payload["sources"][0]["id"] == notation, payload
        return (
            f"{len(index.chunks)} sections; recall@3 {vectors['hits']}/{vectors['total']} with test embeddings, "
            f"{keywords['hits']}/{keywords['total']} with keywords; the coach cited {notation}"
        )

    @check("learn · the beginner method solves random cubes; the tutor's moves are checked")
    def _() -> str:
        from backend.ai.tutor import TutorContext
        from backend.core.beginner import current_stage, solve_all
        from backend.core.solver import SolverEngine
        from backend.services.logbus import LogBus
        from backend.services.session import SolveSession

        counts = []
        for seed in range(20):  # 20 random cubes, solved stage by stage, the stages in order
            start = CubeState.solved().apply_sequence(random_scramble(25, seed=seed)).to_color_string()
            actions, stages = solve_all(start)
            assert stages == sorted(stages), f"cube {seed}: stages out of order"
            counts.append(sum(1 for action in actions if action != "turn_over"))

        # The session: start, hold, a hint (the built-in one: no AI here), then "Show me" to the end.
        session = SolveSession(
            **memory_stores(), solver=SolverEngine(), logs=LogBus(),
            publish_event=lambda event, data: None, publish_frame=lambda jpeg: None,
        )
        session.handle_command("cube.scramble", {"length": 25})
        assert session.handle_command("learn.start", {})["ok"]
        session.handle_command("learn.ready", {})
        session.handle_command("learn.hint", {})
        assert session.snapshot()["learn"]["hints"][0]["text"], "no hint"
        for _ in range(100):
            learn = session.snapshot()["learn"]
            if learn["solved"]:
                break
            if learn["step"]["kind"] == "turn_over":
                session.handle_command("learn.turnover", {})
                continue
            session.handle_command("learn.show", {})
            for move in session.snapshot()["learn"]["step"]["notation"].split():
                session.handle_command("learn.move", {"move": move})
        learn = session.snapshot()["learn"]
        assert learn["solved"] and current_stage("".join("".join(learn["cube"][f]) for f in "URFDLB")) == 8
        assert learn["recap"], "no recap"

        # Hint 1 may not tell the learner which moves to make: code rejects it.
        context = TutorContext("hint", {"hintLevel": 1, "step": {"look": "Look at the white sticker."}}, [], None)
        assert context.check_answer({"message": "Do F R U.", "citations": []}), "moves in hint 1 were accepted"
        return (f"20 random cubes solved in 7 stages ({min(counts)}-{max(counts)} moves); a session solved one "
                f"with Show me in {learn['moveCount']} moves; moves in hint 1 rejected")

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

    @check("accounts · hashed passwords, signed tokens, and one session per visitor")
    def _() -> str:
        from backend.core.solver import SolverEngine
        from backend.server.auth import issue_token, read_token
        from backend.services.accounts import AccountStore
        from backend.services.logbus import LogBus
        from backend.services.sessions import SessionManager, SharedServices, Visitor, build_session

        stores = memory_stores()
        database = stores["database"]
        accounts = AccountStore(database)
        account = accounts.create("verify@example.com", "a-long-password")
        assert accounts.authenticate("VERIFY@example.com", "a-long-password") == account, "login failed"
        assert accounts.authenticate("verify@example.com", "a-wrong-password") is None, "a wrong password passed"
        token = issue_token("secret", {"kind": "user", "id": account.id, "email": account.email})
        assert read_token("secret", token)["id"] == account.id, "the token did not round-trip"
        assert read_token("other-secret", token) is None, "a token signed with another key was accepted"

        shared = SharedServices(
            settings=stores["settings"], profiles=stores["profiles"], solver=SolverEngine(), logs=LogBus(),
            accounts=accounts, database=database, local_analytics=stores["analytics"],
            publish=lambda event, data, to=None: None, publish_frame=lambda jpeg: None, production=True,
        )
        sessions = SessionManager(lambda visitor, guard: build_session(visitor, guard, shared))
        mine = sessions.get(Visitor(f"u:{account.id}", account.email))
        guest = sessions.get(Visitor("g:0123456789abcdef"))
        mine.handle_command("cube.scramble", {"length": 15})
        assert guest.snapshot()["cube"] is None, "a guest saw another visitor's cube"
        guest.handle_command("settings.update", {"theme": "light"})
        assert shared.settings.current.theme == "dark", "a live-site guest changed the shared settings"
        sessions.shutdown()
        return "scrypt hash + login; JWT signed and checked; 2 visitors, 2 cubes; a guest changes nothing shared"

    @check("colour model · the trained CNN or HSV; the vision check picks the fix the images show")
    def _() -> str:
        import json

        from backend.ai.budget import RequestBudget
        from backend.ai.gemini import GeminiClient
        from backend.ai.repair_agent import RepairContext
        from backend.ai.service import AIService
        from backend.config import MODEL_DIR
        from backend.core.cube import FACE_ORDER
        from backend.vision.classifier import load_color_model
        from tools import eval_ai, fake_gemini

        # 1. Which colour model the scanner would use (a trained CNN only if it beat HSV).
        _, status = load_color_model("auto", MODEL_DIR)
        model = status["model"]
        found = (f"CNN {model['cnnAccuracy']:.1%} vs HSV {model['hsvAccuracy']:.1%} on "
                 f"{model['testScans']} test scans" if model else "no trained model yet")
        # 2. An ambiguous misread where the built-in search picks the wrong fix...
        for seed in eval_ai.ambiguous_seeds(0, 10):
            scan, readings, truth = eval_ai.misread_case(seed, "no-hint", 2)
            context = RepairContext(scan, readings)
            if not eval_ai.is_true_fix(context, context.search.candidates[0].id, truth):
                break
        else:
            raise AssertionError("no ambiguous case where the built-in pick is wrong")
        real = scan.facelets
        for face, index, color in truth:
            real[face][index] = color
        crops = {f: [np.full((32, 32, 3), COLOR_BGR[c], np.uint8) for c in real[f]] for f in FACE_ORDER}

        # 3. ...the agent looks at the sticker images (fake Gemini over the real request format).
        def transport(url, headers, body, timeout):
            status_code, payload = fake_gemini.answer(json.loads(body))
            return status_code, json.dumps(payload).encode("utf-8")

        llm = GeminiClient(fake_gemini.KEY, "gemini-fake", base_url="http://fake/v1beta", transport=transport)
        proposal = AIService(llm, RequestBudget(10, 100), None, lambda e, d: None).repair(
            RepairContext(scan, readings, crops))
        chosen = {(c["face"], c["index"], c["to"]) for c in proposal["changes"]}
        assert chosen == set(truth), f"the agent chose {chosen}, the truth is {set(truth)}"
        return (f"colour model: {status['active']} ({found}); ambiguous misread: built-in pick wrong, "
                f"vision check -> the true fix ({proposal['requests']} requests)")

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

def run_live(url: str, expect_db: str | None = None, expect_ai: str | None = None) -> None:
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

    @check("live · AI assistant answers (Gemini, or the built-in answer)")
    def _() -> str:
        answers: list = []
        client.on("ai:answer", lambda data: answers.append(data))
        command("ai.ask", {"question": "How many moves is my solution?"}, settle=0.2)
        assert wait_for(lambda: bool(answers), timeout=90), "no ai:answer event within 90 s"
        answer = answers[-1]
        assert answer.get("answer"), f"no answer: {answer}"
        if expect_ai:
            assert answer["source"] == expect_ai, f"expected {expect_ai}, got {answer['source']}: {answer['reason']}"
        how = answer["model"] if answer["source"] != "fallback" else f"built-in answer ({answer['reason']})"
        return f"{how}, {answer['durationMs']} ms, {answer['requests']} request(s): {answer['answer'][:70]}"

    @check("live · repair agent fixes a broken cube (Gemini, or the built-in search)")
    def _() -> str:
        command("cube.scramble", settle=0.3)
        old = state["cube"]["facelets"]["U"][1]
        wrong = next(code for code in "WYROGB" if code != old)
        command("cube.sticker", {"face": "U", "index": 1, "color": wrong}, settle=0.3)
        assert wait_for(lambda: state["validation"] and not state["validation"]["ok"]), "the broken cube is valid"
        command("repair.start", settle=0.2)

        def ready() -> bool:
            return (state.get("repair") or {}).get("status") == "ready"

        assert wait_for(ready, timeout=90), "no repair proposal within 90 s"
        repair = state["repair"]
        if expect_ai:
            assert repair["source"] == expect_ai, f"expected {expect_ai}, got {repair['source']}: {repair['reason']}"
        if repair["action"] == "apply_fix":
            command("repair.apply", settle=0.2)
            assert wait_for(lambda: state["validation"]["ok"]), "the cube is still invalid after Apply"
        how = repair["model"] if repair["source"] != "search" else f"built-in search ({repair['reason'] or 'no AI'})"
        return f"{how}: {repair['action']}, {repair['fixesFound']} proven fix(es); {repair['message'][:60]}"

    @check("live · RAG coach answers from the lessons, with citations")
    def _() -> str:
        answers: list = []
        client.on("coach:answer", lambda data: answers.append(data))
        command("coach.ask", {"question": "What does R prime mean?"}, settle=0.2)
        assert wait_for(lambda: bool(answers), timeout=90), "no coach:answer event within 90 s"
        answer = answers[-1]
        assert answer.get("answer") and answer.get("citations"), f"no cited answer: {answer}"
        if expect_ai:
            assert answer["source"] == expect_ai, f"expected {expect_ai}, got {answer['source']}: {answer['reason']}"
        how = answer["model"] if answer["source"] != "fallback" else f"built-in answer ({answer['reason']})"
        return f"{how}; search: {answer['search']}; cites {', '.join(answer['citations'])}"

    @check("live · Solve & Learn: a stage step and a tutor hint (Gemini, or the built-in hint)")
    def _() -> str:
        command("cube.scramble", settle=0.3)
        command("learn.start", settle=0.3)
        command("learn.ready", settle=0.3)
        assert wait_for(lambda: (state.get("learn") or {}).get("ready")), "Solve & Learn did not start"

        # A hint takes up to 3 AI requests (the lesson search's embedding and two model
        # turns), and the AI checks above have just used the same per-minute budget. Wait
        # until it has room, or the app rightly gives its built-in hint and the tutor's
        # Gemini path goes untested. The budget numbers come from the app's own snapshot.
        def budget_has_room() -> bool:
            command("sync", settle=2.0)  # a fresh snapshot: the count covers the last 60 s
            budget = (state.get("ai") or {}).get("budget") or {}
            return budget.get("usedLastMinute", 0) + 3 <= budget.get("perMinute", 3)

        started = time.time()
        assert wait_for(budget_has_room, timeout=70), "the AI budget had no room for a hint within 70 s"
        waited = round(time.time() - started)
        command("learn.hint", settle=0.2)

        def hint_ready() -> bool:
            hints = (state.get("learn") or {}).get("hints") or []
            return bool(hints) and hints[0]["source"] != "built-in"

        assert wait_for(hint_ready, timeout=90), "no tutor hint within 90 s"
        hint = state["learn"]["hints"][0]
        if expect_ai:
            assert hint["source"] == expect_ai, f"expected {expect_ai}, got {hint['source']}"
        command("learn.show", settle=0.3)
        moves = state["learn"]["step"]["notation"].split()
        for move in moves:
            command("learn.move", {"move": move}, settle=0.15)
        assert wait_for(lambda: state["learn"]["moveCount"] == len(moves)), "the moves did not arrive"
        stage = state["learn"]["stage"]
        command("learn.exit", settle=0.3)  # the live site has one shared session: leave it clean
        how = hint["model"] if hint["source"] != "fallback" else "built-in hint"
        pause = f" (waited {waited} s for the AI budget)" if waited > 2 else ""
        return (f"{how}{pause}: \"{hint['text'][:50]}...\"; followed {len(moves)} shown move(s), "
                f"now at stage {stage}")

    @check("live · accounts: sign up, a session of its own, log out, delete")
    def _() -> str:
        import json
        import secrets
        import urllib.error
        import urllib.request

        # The login cookie, kept by hand: a browser sends a "Secure" cookie only over HTTPS,
        # but this check must also work against a local production-mode run (plain HTTP).
        token = {"cookie": ""}

        def remember(headers) -> None:
            for header in headers.get_all("Set-Cookie") or []:
                if header.startswith("cube_token="):
                    token["cookie"] = header.split(";", 1)[0]

        def call(path: str, body: dict | None = None) -> tuple:
            data = json.dumps(body).encode() if body is not None else None
            headers = {"Content-Type": "application/json"}
            if token["cookie"]:
                headers["Cookie"] = token["cookie"]
            request = urllib.request.Request(url.rstrip("/") + path, data=data, headers=headers,
                                             method="POST" if body is not None else "GET")
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    remember(response.headers)
                    return response.status, json.loads(response.read())
            except urllib.error.HTTPError as exc:
                remember(exc.headers)
                return exc.code, json.loads(exc.read() or b"{}")

        email, password = f"verify-{secrets.token_hex(4)}@example.com", secrets.token_urlsafe(12)
        status, me = call("/api/auth/signup", {"email": email, "password": password})
        assert status == 201 and me["email"] == email, f"sign-up failed: {status} {me}"
        try:
            assert call("/api/auth/me")[1].get("email") == email, "the cookie did not log the browser in"
            mine: dict = {}
            account = socketio.Client()
            account.on("state", lambda data: mine.update(data))
            account.connect(url, headers={"Cookie": token["cookie"]}, wait_timeout=15)
            assert wait_for(lambda: bool(mine), timeout=10), "the account's socket got no state"
            before = (state.get("cube") or {}).get("facelets")
            account.emit("command", {"command": "cube.scramble", "payload": {"length": 15}})
            assert wait_for(lambda: mine.get("cubeSource") == "scramble"), "the account's scramble did not arrive"
            time.sleep(0.5)
            assert (state.get("cube") or {}).get("facelets") == before, "another visitor's cube changed"
            account.disconnect()
            assert call("/api/auth/logout", {})[1] == {"kind": "guest"}, "log-out failed"
            assert call("/api/auth/login", {"email": email, "password": password})[0] == 200, "log-in failed"
        finally:  # never leave test accounts behind on the live site
            status, _ = call("/api/auth/delete", {"password": password})
        assert status == 200, f"could not delete the test account ({status})"
        return "signed up, own cube (this session's unchanged), logged out and in, account deleted"

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
    parser.add_argument(
        "--expect-ai", choices=["gemini"],
        help="with --live: fail unless the assistant's answer comes from this AI provider",
    )
    args = parser.parse_args(argv)

    print("Rubik's Cube Solver - verification\n" + "=" * 72)
    run_offline()
    if args.live:
        run_live(args.url, args.expect_db, args.expect_ai)

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
