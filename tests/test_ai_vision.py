"""The vision check (Phase 11): the request, its guardrails, and the repair agent's look tool."""

import base64
import json
import threading
from http.server import HTTPServer

import cv2
import numpy as np
import pytest

from backend.ai.budget import RequestBudget
from backend.ai.fake import ScriptedLLM, tool_call
from backend.ai.gemini import GeminiClient
from backend.ai.llm import LLMBadResponse, LLMRateLimited, LLMRequest, Message
from backend.ai.repair_agent import LOOK_TOOL, RepairContext
from backend.ai.service import AIConfig, AIService
from backend.ai.schema import to_gemini_schema
from backend.ai.vision import StickerVision, report_schema
from backend.core.cube import COLOR_CODES, COLOR_NAMES, FACE_ORDER, CubeState
from backend.vision.overlay import COLOR_BGR
from tools import eval_ai
from tools.fake_gemini import KEY, Handler
from tools.fake_gemini import answer as fake_answer


def crop(code):
    return np.full((32, 32, 3), COLOR_BGR[code], np.uint8)


def crops_of(cube):
    """What the camera saw: the true colours."""
    return {face: [crop(code) for code in cube.face(face)] for face in FACE_ORDER}


def ambiguous_case():
    """A scan with two misread stickers, where more than one fix makes the cube valid."""
    seed = eval_ai.ambiguous_seeds(0, 1)[0]
    scan, readings, truth = eval_ai.misread_case(seed, "doubt", 2)
    real = scan.facelets
    for face, index, color in truth:
        real[face][index] = color
    return scan, readings, truth, CubeState(real)


def report(**colours):
    """A report_colours turn: report(S1=("Red", True), ...)."""
    rows = [{"id": key, "color": value[0], "sure": value[1]} for key, value in colours.items()]
    return tool_call("report_colours", stickers=rows)


def test_the_request_holds_the_centres_and_the_stickers_and_the_answer_is_read():
    llm = ScriptedLLM([report(S1=("Orange", True), S2=("White", False))])
    centres = {code: crop(code) for code in COLOR_CODES}
    seen = StickerVision(llm).look(centres, [("S1", crop("O")), ("S2", crop("W"))])
    assert seen == {"S1": {"color": "O", "sure": True}, "S2": {"color": "W", "sure": False}}
    request = llm.requests[0]
    assert request.require_tool_call and [t.name for t in request.tools] == ["report_colours"]
    images = request.messages[0].images
    assert len(images) == 8 and all(image[:4] == b"\x89PNG" for image in images)
    first = cv2.imdecode(np.frombuffer(images[0], np.uint8), cv2.IMREAD_COLOR)
    assert tuple(int(v) for v in first[0, 0]) == COLOR_BGR["W"]  # the centres come first, White first


@pytest.mark.parametrize(
    "turn",
    [
        report(S1=("Orange", True)),  # S2 is missing
        report(S1=("Purple", True), S2=("White", True)),  # not a cube colour
        report(S1=("Red", True), S3=("White", True)),  # a sticker it wasn't asked about
        tool_call("final_answer", answer="Red"),  # the wrong tool
    ],
)
def test_a_broken_answer_is_refused(turn):
    centres = {code: crop(code) for code in COLOR_CODES}
    with pytest.raises(LLMBadResponse):
        StickerVision(ScriptedLLM([turn])).look(centres, [("S1", crop("O")), ("S2", crop("W"))])


def test_gemini_gets_the_images_as_inline_png_parts():
    client = GeminiClient("test-key", "gemini-test")
    body = client.build_body(LLMRequest(system="", messages=[Message.user("Look", [b"\x89PNG-1", b"\x89PNG-2"])]))
    parts = body["contents"][0]["parts"]
    assert parts[0] == {"text": "Look"}
    assert parts[1] == {"inlineData": {"mimeType": "image/png", "data": base64.b64encode(b"\x89PNG-1").decode()}}
    assert len(parts) == 3


def test_the_look_tool_is_only_offered_with_camera_images_and_ai():
    scan, readings, _, real = ambiguous_case()
    assert LOOK_TOOL not in RepairContext(scan, readings).tool_names()
    context = RepairContext(scan, readings, crops_of(real))
    assert LOOK_TOOL not in context.tool_names()  # no vision model yet
    context.vision = lambda centres, stickers: {}
    assert LOOK_TOOL in context.tool_names()
    half = crops_of(real)
    del half["B"]
    partial = RepairContext(scan, readings, half)
    partial.vision = context.vision
    assert LOOK_TOOL not in partial.tool_names()  # every face needs its images


def test_the_agent_looks_and_picks_the_fix_the_images_support():
    scan, readings, truth, real = ambiguous_case()
    context = RepairContext(scan, readings, crops_of(real))
    true_fix = next(c.id for c in context.search.candidates if eval_ai.is_true_fix(context, c.id, truth))

    # Script: find_fixes, look (the agent), then the vision request, then the final answer.
    stickers = []
    for candidate in context.search.candidates:
        for change in candidate.changes:
            if (change.face, change.index) not in stickers:
                stickers.append((change.face, change.index))
    vision_turn = report(**{f"S{n + 1}": (COLOR_NAMES[real.face(f)[i]], True) for n, (f, i) in enumerate(stickers[:6])})
    llm = ScriptedLLM([
        tool_call("find_fixes"),
        tool_call(LOOK_TOOL),
        vision_turn,
        tool_call("final_answer", action="apply_fix", fix_id=true_fix, message="The images show it."),
    ])
    proposal = AIService(llm, RequestBudget(10, 100), None, lambda e, d: None).repair(context)
    assert proposal["action"] == "apply_fix" and proposal["source"] == "scripted"
    assert {(c["face"], c["index"], c["to"]) for c in proposal["changes"]} == set(truth)
    assert proposal["requests"] == 4  # 3 agent turns + the vision request, in one trace
    looked = context.look()
    assert all(row["vision_sees"] == COLOR_NAMES[real.face(f)[i]] for row, (f, i) in zip(looked["stickers"], stickers))
    assert LOOK_TOOL in [tool.name for tool in llm.requests[0].tools]


def test_a_failed_look_does_not_stop_the_repair():
    scan, readings, _, real = ambiguous_case()
    context = RepairContext(scan, readings, crops_of(real))
    llm = ScriptedLLM([
        tool_call(LOOK_TOOL),
        LLMRateLimited("quota"),  # the vision request fails
        tool_call("final_answer", action="rescan_side", side="U", message="Please rescan the top."),
    ])
    proposal = AIService(llm, RequestBudget(10, 100), None, lambda e, d: None).repair(context)
    assert proposal["action"] == "rescan_side"
    assert "vision check failed" in context.look()["error"]  # remembered: never asked twice


def test_the_fake_gemini_sees_the_true_colours():
    centres = [crop(code) for code in COLOR_CODES]
    stickers = [crop("O"), crop("B")]

    def part(image):
        return {"inlineData": {"mimeType": "image/png", "data": base64.b64encode(cv2.imencode(".png", image)[1].tobytes()).decode()}}

    body = {
        "contents": [{"role": "user", "parts": [{"text": "Which?"}] + [part(i) for i in centres + stickers]}],
        "tools": [{"functionDeclarations": [{"name": "report_colours", "description": "",
                                             "parameters": to_gemini_schema(report_schema(["S1", "S2"]))}]}],
        "toolConfig": {"functionCallingConfig": {"mode": "ANY"}},
    }
    status, payload = fake_answer(json.loads(json.dumps(body)))
    rows = payload["candidates"][0]["content"]["parts"][0]["functionCall"]["args"]["stickers"]
    assert status == 200 and [(r["id"], r["color"], r["sure"]) for r in rows] == [("S1", "Orange", True), ("S2", "Blue", True)]


def test_the_vision_check_end_to_end_finds_the_fix_the_numbers_miss():
    """Real HTTP to tools/fake_gemini.py: a case where the built-in search picks a wrong fix."""
    for seed in eval_ai.ambiguous_seeds(0, 10):
        scan, readings, truth = eval_ai.misread_case(seed, "no-hint", 2)
        context = RepairContext(scan, readings)
        if context.search.total > 1 and not eval_ai.is_true_fix(context, context.search.candidates[0].id, truth):
            break
    else:
        pytest.fail("no ambiguous case where the built-in pick is wrong")
    real = scan.facelets
    for face, index, color in truth:
        real[face][index] = color

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/v1beta"
        ai = AIService.create(AIConfig(api_key=KEY, model="gemini-test", base_url=url), None, lambda e, d: None)
        context = RepairContext(scan, readings, crops_of(CubeState(real)))
        proposal = ai.repair(context)
    finally:
        server.shutdown()
        server.server_close()
    assert (proposal["source"], proposal["action"]) == ("gemini", "apply_fix")
    assert {(c["face"], c["index"], c["to"]) for c in proposal["changes"]} == set(truth)
    assert "vision check agrees" in proposal["message"]
    assert proposal["requests"] == 4  # find_fixes, look, the vision request, final_answer
