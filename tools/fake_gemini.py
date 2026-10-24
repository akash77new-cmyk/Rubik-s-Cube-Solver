"""A fake Gemini server: test the AI path end to end without a key or the internet.

    python tools/fake_gemini.py                       # listens on http://127.0.0.1:8799
    GEMINI_API_KEY=test-key GEMINI_BASE_URL=http://127.0.0.1:8799/v1beta python run.py --headless
    python tools/verify.py --live --expect-ai gemini

It answers ``generateContent`` the way Gemini 3 does, and is strict where Gemini is strict:
- the key must come in the ``x-goog-api-key`` header (HTTP 403 otherwise);
- the request must force a function call (mode ANY);
- each function call it sends has an id and a thought signature, and a later request that
  drops or changes a signature gets HTTP 400, like on the real API.

It is not a model. For the Cube Assistant it calls get_solution, then answers with
final_answer from what the tool returned. For the Smart Repair Agent (Phase 5) it calls
find_fixes; when several fixes fit and it may look (Phase 11), it calls look_at_stickers and
picks the fix the vision check agrees with, else the first fix, or asks for a rescan if
there is none. A vision request (report_colours) is answered by comparing each sticker
image's average colour with the six centre images. For the RAG
coach (Phase 7) it calls search_lessons with the question, then cites the first passage.
For the AI Tutor (Phase 8) it gives the app's own hint text back, searches the lessons for a
question, and writes a recap from the stats it was given.
``batchEmbedContents`` returns word-hash vectors (see backend/ai/fake.py), so lesson
search works end to end. tests/test_ai_end_to_end.py uses it too.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, List, Tuple

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # so "backend" imports work

from backend.ai.fake import hash_vector  # noqa: E402 - needs the path above
from backend.ai.tutor import recap_text  # noqa: E402

KEY = "test-key"


def _call(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """A Gemini 3 answer that calls one function, with an id and a thought signature."""
    return {
        "candidates": [
            {
                "content": {
                    "role": "model",
                    "parts": [
                        {"functionCall": {"id": f"id-{name}", "name": name, "args": args}, "thoughtSignature": f"sig-{name}"}
                    ],
                },
                "finishReason": "STOP",
            }
        ],
        "usageMetadata": {"promptTokenCount": 321, "candidatesTokenCount": 12, "thoughtsTokenCount": 7},
        "modelVersion": "gemini-fake-001",
    }


def _error(status: int, message: str) -> Tuple[int, Dict[str, Any]]:
    return status, {"error": {"code": status, "message": message}}


def answer(body: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    """(HTTP status, JSON answer) for one generateContent request body."""
    if body.get("toolConfig", {}).get("functionCallingConfig", {}).get("mode") != "ANY":
        return _error(400, "The fake Gemini expects function calling mode ANY")
    contents = body.get("contents") or []
    for content in contents:
        if content.get("role") != "model":
            continue
        calls = [part for part in content.get("parts", []) if "functionCall" in part]
        # Like Gemini 3: the first function call of a model turn must keep its signature.
        if calls and calls[0].get("thoughtSignature") != "sig-" + calls[0]["functionCall"]["name"]:
            return _error(400, "Function call is missing a thought_signature")
    if not contents:
        return _error(400, "No contents")
    results = [part["functionResponse"] for part in contents[-1].get("parts", []) if "functionResponse" in part]
    declarations = [d for tool in body.get("tools", []) for d in tool.get("functionDeclarations", [])]
    tools = {d["name"] for d in declarations}
    if "report_colours" in tools:  # the vision check (Phase 11)
        return _vision(contents[0], next(d for d in declarations if d["name"] == "report_colours"))
    final = next((d for d in declarations if d["name"] == "final_answer"), {})
    if "message" in final.get("parameters", {}).get("properties", {}) and "search_lessons" in tools:
        return _tutor(contents, results)
    if "search_lessons" in tools:  # the RAG coach
        if not results:
            question = contents[0]["parts"][0].get("text", "")
            return 200, _call("search_lessons", {"query": question})
        passages = results[0].get("response", {}).get("passages", [])
        if not passages:
            return 200, _call("final_answer", {"answer": "The lessons don't cover that.", "citations": [], "covered": False})
        first = passages[0]
        text = f"The lesson \"{first['section']}\" covers this: {first['text'].split('. ')[0]}."
        return 200, _call("final_answer", {"answer": text[:900], "citations": [first["id"]], "covered": True})
    if "find_fixes" in tools:  # the Smart Repair Agent
        done = {
            part["functionResponse"]["name"]: part["functionResponse"].get("response", {})
            for content in contents for part in content.get("parts", []) if "functionResponse" in part
        }
        if "find_fixes" not in done:
            return 200, _call("find_fixes", {})
        fixes = done["find_fixes"].get("fixes", [])
        if len(fixes) > 1 and "look_at_stickers" in tools and "look_at_stickers" not in done:
            return 200, _call("look_at_stickers", {})
        if fixes:
            seen = {row["sticker"]: row for row in done.get("look_at_stickers", {}).get("stickers", [])}
            agreed = [
                fix for fix in fixes
                if seen and all(seen.get(c["sticker"], {}).get("vision_sees") == c["to"] for c in fix["changes"])
            ]
            fix = (agreed or fixes)[0]
            why = "the vision check agrees" if agreed else "the camera doubted those stickers"
            message = f"Fix {fix['id']} is the most likely: {why}."
            return 200, _call("final_answer", {"action": "apply_fix", "fix_id": fix["id"], "message": message})
        return 200, _call("final_answer", {"action": "rescan_side", "side": "U", "message": "Rescan the top side."})
    if not results:
        return 200, _call("get_solution", {})
    data = results[0].get("response", {})
    if data.get("has_solution"):
        text = f"Your solution has {data['move_count']} moves: {data['moves']}."
    else:
        text = "There is no solution yet. Press Solve first."
    return 200, _call("final_answer", {"answer": text, "suggestions": ["How do I do step 1?"]})


def _vision(content: Dict[str, Any], declaration: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    """The vision check: each sticker gets the colour of the centre image nearest in average colour."""
    images: List[np.ndarray] = []
    for part in content.get("parts", []):
        if "inlineData" in part:
            data = np.frombuffer(base64.b64decode(part["inlineData"]["data"]), np.uint8)
            images.append(cv2.imdecode(data, cv2.IMREAD_COLOR).reshape(-1, 3).mean(axis=0))
    item = declaration["parameters"]["properties"]["stickers"]["items"]["properties"]
    ids, names = item["id"]["enum"], item["color"]["enum"]
    if len(images) != 6 + len(ids):
        return _error(400, f"Expected {6 + len(ids)} images, got {len(images)}")
    centres, rows = images[:6], []
    for sticker_id, image in zip(ids, images[6:]):
        distances = sorted((float(np.linalg.norm(image - centre)), name) for centre, name in zip(centres, names))
        rows.append({"id": sticker_id, "color": distances[0][1], "sure": distances[0][0] < 0.6 * distances[1][0]})
    return 200, _call("report_colours", {"stickers": rows})


def _tutor(contents: Any, results: Any) -> Tuple[int, Dict[str, Any]]:
    """The AI Tutor: hints echo the app's facts, questions search the lessons first."""
    prompt = contents[0]["parts"][0].get("text", "")
    facts = json.loads(prompt.split("Facts from the app (always right):\n", 1)[1])
    if prompt.startswith("The learner asks: "):
        if not results:
            return 200, _call("search_lessons", {"query": prompt.split("\n", 1)[0][len("The learner asks: "):]})
        passages = results[0].get("response", {}).get("passages", [])
        if not passages:
            return 200, _call("final_answer", {"message": "The lessons don't cover that.", "citations": []})
        first = passages[0]
        message = f"The lesson \"{first['section']}\" says: {first['text'].split('. ')[0]}."
        return 200, _call("final_answer", {"message": message[:600], "citations": [first["id"]]})
    if prompt.startswith("Give hint level"):
        step = facts.get("step", {})
        text = step.get("look") if facts["hintLevel"] <= 1 else step.get("how", step.get("look"))
        return 200, _call("final_answer", {"message": f"Tutor hint: {text}"[:600], "citations": []})
    return 200, _call("final_answer", {"message": "Well done! " + recap_text(facts.get("stats", {})), "citations": []})


def embed(body: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    """A batchEmbedContents answer: one vector per request, in order."""
    vectors = []
    for request in body.get("requests") or []:
        text = request["content"]["parts"][0]["text"]
        vectors.append({"values": hash_vector(text, int(request.get("outputDimensionality", 768)))})
    return 200, {"embeddings": vectors}


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - the http.server API
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
        if self.headers.get("x-goog-api-key") != KEY:
            status, payload = _error(403, f"API key not valid (the fake Gemini expects {KEY!r})")
        elif self.path.endswith(":batchEmbedContents"):
            status, payload = embed(body)
        elif not self.path.endswith(":generateContent"):
            status, payload = _error(404, f"Unknown path {self.path}")
        else:
            status, payload = answer(body)
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args: Any) -> None:  # keep the terminal quiet
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description="A fake Gemini server for end-to-end tests.")
    parser.add_argument("--port", type=int, default=8799)
    args = parser.parse_args()
    server = HTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Fake Gemini at http://127.0.0.1:{args.port}/v1beta (key: {KEY}). Ctrl+C stops it.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
