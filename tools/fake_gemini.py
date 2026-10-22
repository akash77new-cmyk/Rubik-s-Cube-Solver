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
find_fixes, then picks the first fix, or asks for a rescan if there is none.
tests/test_ai_end_to_end.py uses it too.
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, Tuple

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
    tools = {d["name"] for tool in body.get("tools", []) for d in tool.get("functionDeclarations", [])}
    if "find_fixes" in tools:  # the Smart Repair Agent
        if not results:
            return 200, _call("find_fixes", {})
        fixes = results[0].get("response", {}).get("fixes", [])
        if fixes:
            message = f"Fix {fixes[0]['id']} is the most likely: the camera doubted those stickers."
            return 200, _call("final_answer", {"action": "apply_fix", "fix_id": fixes[0]["id"], "message": message})
        return 200, _call("final_answer", {"action": "rescan_side", "side": "U", "message": "Rescan the top side."})
    if not results:
        return 200, _call("get_solution", {})
    data = results[0].get("response", {})
    if data.get("has_solution"):
        text = f"Your solution has {data['move_count']} moves: {data['moves']}."
    else:
        text = "There is no solution yet. Press Solve first."
    return 200, _call("final_answer", {"answer": text, "suggestions": ["How do I do step 1?"]})


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - the http.server API
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
        if self.headers.get("x-goog-api-key") != KEY:
            status, payload = _error(403, f"API key not valid (the fake Gemini expects {KEY!r})")
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
