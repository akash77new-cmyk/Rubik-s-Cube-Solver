"""The Smart Repair Agent: its tools, its answer rules, the fallback, and the Scanner flow."""

import threading

from backend.ai.agent import FINAL_ANSWER
from backend.ai.budget import RequestBudget
from backend.ai.fake import ScriptedLLM, tool_call, tool_calls
from backend.ai.llm import LLMRateLimited
from backend.ai.repair_agent import TOOL_NAMES, RepairContext, build_tools, fallback_answer
from backend.ai.service import AIService
from backend.ai.tracing import TraceStore
from backend.core.cube import CubeState
from backend.db import connect
from tests.sessions import misread, readings_for, real_cube, scanned_session

#: The camera read U2 (the top sticker of the White side) as orange, 51% sure; it is red.
DOUBT = {("U", 1): ("O", "R", 0.51, 0.48)}
LOOK = tool_calls(("get_problems", {}), ("get_suspect_stickers", {}), ("find_fixes", {}))


def context():
    scan = misread(real_cube(), {("U", 1): "O"})
    return RepairContext(scan, readings_for(scan, DOUBT))


def service(script=None):
    store = TraceStore(connect("sqlite://"))
    llm = ScriptedLLM(script) if script is not None else None
    return AIService(llm, RequestBudget(10, 100), store, lambda e, d: None, off_reason="no Gemini API key is set"), store


def test_the_tools_describe_problems_doubts_and_proven_fixes():
    tools = build_tools(context())
    problems = tools.call("get_problems", {}, TOOL_NAMES)
    assert problems["valid"] is False and {p["code"] for p in problems["problems"]} >= {"color_count"}
    suspects = tools.call("get_suspect_stickers", {}, TOOL_NAMES)["stickers"]
    assert suspects[0]["sticker"] == "top sticker of the White side (U)"
    assert (suspects[0]["read_as"], suspects[0]["confidence"], suspects[0]["second_guess"]) == ("Orange", 0.51, "Red")
    (fix,) = tools.call("find_fixes", {}, TOOL_NAMES)["fixes"]
    assert fix["id"] == 1 and fix["changes"][0]["to"] == "Red"


def test_answers_must_use_a_real_fix_id():
    ctx = context()
    assert ctx.check_answer({"action": "apply_fix", "fix_id": 1, "message": "x"}) == []
    assert ctx.check_answer({"action": "apply_fix", "fix_id": 4, "message": "x"}) == ["fix_id must be one of [1] (from find_fixes)"]
    assert ctx.check_answer({"action": "rescan_side", "message": "x"}) == ["rescan_side needs a side"]


def test_the_built_in_answer():
    answer = fallback_answer(context(), "no Gemini API key is set")
    assert answer["action"] == "apply_fix" and answer["fix_id"] == 1
    assert "Most likely the top sticker of the White side (U) is red, not orange (the camera was 51% sure)." in answer["message"]

    f = real_cube().facelets  # a twisted corner: no 1- or 2-sticker fix exists
    f["U"][8], f["R"][0], f["F"][2] = f["R"][0], f["F"][2], f["U"][8]
    rescan = fallback_answer(RepairContext(CubeState(f)), None)
    assert rescan["action"] == "rescan_side" and "Rescan the" in rescan["message"]


def test_the_agent_picks_a_proven_fix_and_the_changes_come_from_code():
    ai, store = service([LOOK, tool_call(FINAL_ANSWER, action="apply_fix", fix_id=1, message="The top sticker is red.")])
    proposal = ai.repair(context())
    assert (proposal["source"], proposal["action"], proposal["message"]) == ("scripted", "apply_fix", "The top sticker is red.")
    assert proposal["changes"] == [
        {"face": "U", "index": 1, "from": "O", "to": "R", "oldConfidence": 0.51, "newConfidence": 0.48}
    ]
    assert proposal["toolCalls"] == 3 and proposal["requests"] == 2
    (run,) = store.recent()
    assert run["feature"] == "repair"


def test_a_made_up_fix_id_is_sent_back_and_corrected():
    ai, _ = service([
        LOOK,
        tool_call(FINAL_ANSWER, action="apply_fix", fix_id=3, message="Fix 3."),
        tool_call(FINAL_ANSWER, action="apply_fix", fix_id=1, message="Fix 1."),
    ])
    proposal = ai.repair(context())
    assert proposal["message"] == "Fix 1." and proposal["requests"] == 3


def test_without_ai_or_on_errors_the_search_answers():
    off, _ = service(None)
    proposal = off.repair(context())
    assert proposal["source"] == "search" and proposal["reason"] == "no Gemini API key is set"
    assert proposal["message"].startswith("AI help is off right now (no Gemini API key is set)")
    failing, _ = service([LLMRateLimited("429")])
    assert failing.repair(context())["reason"] == "Gemini's free limit is used up for now"


def test_an_unsolvable_scan_gets_a_proposal_and_apply_fixes_it():
    session = scanned_session(misread(real_cube(), {("U", 1): "O"}), DOUBT)
    repair = session.snapshot()["repair"]
    assert (repair["status"], repair["action"], repair["source"]) == ("ready", "apply_fix", "search")
    stopped = []
    session.camera.stop = lambda: stopped.append(True)
    session.camera._running.set()  # pretend the camera is on, as it is during a scan
    assert session.handle_command("repair.apply", {}) == {"ok": True, "valid": True}
    snapshot = session.snapshot()
    assert snapshot["validation"]["ok"] is True and snapshot["repair"]["status"] == "applied"
    assert snapshot["scan"]["faces"]["U"]["colors"][1] == "R"  # the scan record is corrected too
    assert stopped == [True]  # a valid cube turns the camera off
    assert session.handle_command("repair.apply", {})["ok"] is False  # nothing left to apply


def test_a_valid_scan_turns_the_camera_off_and_needs_no_repair():
    session = scanned_session(real_cube())
    assert session.snapshot()["repair"] is None and session.snapshot()["validation"]["ok"] is True
    assert session.handle_command("repair.start", {})["ok"] is False


def test_a_proposal_for_an_older_cube_is_ignored():
    session = scanned_session(misread(real_cube(), {("U", 1): "O"}), DOUBT)
    old = dict(session.snapshot()["repair"])
    session.handle_command("cube.sticker", {"face": "U", "index": 1, "color": "R"})  # the user fixed it by hand
    assert session.snapshot()["repair"] is None
    session._on_repair(old)
    assert session.snapshot()["repair"] is None


def test_with_the_ai_service_the_agent_answers_in_the_background():
    done = threading.Event()
    events = []

    def publish(event, data):
        events.append(event)
        if event == "repair:proposed":
            done.set()

    ai, _ = service([LOOK, tool_call(FINAL_ANSWER, action="apply_fix", fix_id=1, message="Red, not orange.")])
    session = scanned_session(misread(real_cube(), {("U", 1): "O"}), DOUBT, ai=ai, publish_event=publish)
    assert done.wait(5)
    repair = session.snapshot()["repair"]
    assert (repair["status"], repair["source"], repair["message"]) == ("ready", "scripted", "Red, not orange.")
    assert session.handle_command("repair.dismiss", {})["ok"] and session.snapshot()["repair"] is None
