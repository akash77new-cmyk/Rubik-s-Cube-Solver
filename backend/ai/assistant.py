"""The Cube Assistant: answers questions about the user's own cube, solution and solves.

It is a tool-calling agent with five read-only tools. Every fact in an answer comes
from a tool, computed by the app; the model only chooses which tools to call and
writes the explanation (AI rules 1 and 2). When the model can't be used - no API
key, the request budget is used up, an error - the same tools produce a built-in
answer instead (AI rule 4).

The tools read the session's state snapshot (the same data the UI shows) through a
function passed in, so this module needs no global state (AI rule 5).
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List

from backend.ai.tools import NO_ARGS, Tool, ToolRegistry
from backend.core.cube import COLOR_NAMES

SYSTEM_PROMPT = """You are the assistant inside a Rubik's Cube solver web app. The user scans a \
real cube with a camera (or makes a demo scramble), the app checks and solves it, and then \
shows the solution move by move.

Rules:
- Get facts by calling tools. Every number, colour, face and move in your answer must come \
from a tool result. Never guess.
- Never invent cube moves or cube states. Moves come only from get_solution and explain_move.
- If a tool says there is no cube or no solution yet, tell the user what to do in the app.
- Only answer questions about this app and the user's cube, solution and solves. For anything \
else, say in one sentence that you can only help with the cube app.
- Use simple English and at most 4 short sentences.
- When you are done, call final_answer on its own."""

ANSWER_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "answer": {
            "type": "string",
            "minLength": 1,
            "maxLength": 800,
            "description": "The answer for the user: simple English, at most 4 short sentences.",
        },
        "suggestions": {
            "type": "array",
            "maxItems": 3,
            "items": {"type": "string", "minLength": 1, "maxLength": 80},
            "description": "Up to 3 short follow-up questions the user could ask next.",
        },
    },
    "required": ["answer"],
    "additionalProperties": False,
}

STEP_ARGS: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "step": {"type": "integer", "minimum": 1, "maximum": 200, "description": "Move number, starting at 1."}
    },
    "required": ["step"],
    "additionalProperties": False,
}

TOOL_NAMES = ["get_cube_state", "get_scan_progress", "get_solution", "explain_move", "get_solve_stats"]


class SnapshotContext:
    """The facts the assistant may see, read from the session's state snapshot."""

    def __init__(self, get_snapshot: Callable[[], Dict[str, Any]]) -> None:
        self._get_snapshot = get_snapshot

    def cube_state(self) -> Dict[str, Any]:
        snapshot = self._get_snapshot()
        cube = snapshot.get("cube")
        if not cube:
            return {
                "has_cube": False,
                "hint": "There is no cube yet. Scan it on the Scanner page, or press Demo scramble on the Dashboard.",
            }
        validation = snapshot.get("validation") or {}
        return {
            "has_cube": True,
            "source": snapshot.get("cubeSource"),  # "scan", "scramble" or "manual"
            "valid": bool(validation.get("ok")),
            "problems": [
                {"code": issue["code"], "message": issue["message"]} for issue in validation.get("issues", [])[:6]
            ],
            "is_solved": bool(cube.get("isSolved")),
            "stickers_in_solved_position": cube.get("solvedStickers"),
        }

    def scan_progress(self) -> Dict[str, Any]:
        scan = self._get_snapshot().get("scan") or {}
        steps = scan.get("steps", [])
        waiting = [step for step in steps if not step.get("done")]
        return {
            "sides_captured": scan.get("count", 0),
            "sides_total": 6,
            "sides": [
                {"centre_colour": COLOR_NAMES.get(step["center"], step["center"]), "captured": bool(step.get("done"))}
                for step in steps
            ],
            "next_instruction": waiting[0]["text"] if waiting else None,
            "auto_capture": bool(scan.get("autoCapture")),
        }

    def solution(self) -> Dict[str, Any]:
        snapshot = self._get_snapshot()
        solution = snapshot.get("solution")
        if not solution:
            return {
                "has_solution": False,
                "hint": "There is no solution yet. With a valid cube, press Solve on the Cube Viewer or Solution page.",
            }
        playback = snapshot.get("playback") or {}
        return {
            "has_solution": True,
            "move_count": solution["moveCount"],
            "moves": solution["notation"],
            "solver": solution["backend"],
            "search_milliseconds": solution["elapsedMs"],
            "turns_per_face": solution.get("faceDistribution", {}),
            "current_step": playback.get("index", 0),  # moves already done in the player
            "finished": bool(playback.get("completed")),
        }

    def move(self, step: int) -> Dict[str, Any]:
        solution = self._get_snapshot().get("solution")
        if not solution:
            return {"error": "There is no solution yet."}
        moves = solution["moves"]
        if not 1 <= step <= len(moves):
            return {"error": f"There is no step {step}: the solution has {len(moves)} moves."}
        move = moves[step - 1]
        return {
            "step": step,
            "of": len(moves),
            "notation": move["notation"],
            "face": move["faceName"],
            "turn": move["label"],
            "instruction": move["instruction"],
        }

    def solve_stats(self) -> Dict[str, Any]:
        analytics = self._get_snapshot().get("analytics") or {}
        return {
            "total_solves": analytics.get("totalSolves", 0),
            "solves_this_session": analytics.get("sessionSolves", 0),
            "average_moves": analytics.get("averageMoveCount", 0),
            "best_moves": analytics.get("bestMoveCount", 0),
            "average_search_milliseconds": analytics.get("averageSolveMs", 0),
            "average_hands_on_seconds": analytics.get("averageExecutionSeconds", 0),
            "latest": [
                {"moves": r["move_count"], "hands_on_seconds": r["execution_seconds"], "source": r["source"]}
                for r in analytics.get("recent", [])[:5]
            ],
        }


def build_tools(context: SnapshotContext) -> ToolRegistry:
    """The assistant's tools. All read-only."""
    return ToolRegistry(
        [
            Tool(
                "get_cube_state",
                "The user's current cube: where it came from, whether it is valid, its problems, "
                "and whether it is solved.",
                NO_ARGS,
                lambda args: context.cube_state(),
            ),
            Tool(
                "get_scan_progress",
                "Scanning progress: which sides are captured and how to hold the cube for the next one.",
                NO_ARGS,
                lambda args: context.scan_progress(),
            ),
            Tool(
                "get_solution",
                "The current solution: number of moves, all moves in notation, the solver, and the "
                "step the user has reached in the player.",
                NO_ARGS,
                lambda args: context.solution(),
            ),
            Tool(
                "explain_move",
                "One move of the solution, with plain-English instructions for turning the cube by hand.",
                STEP_ARGS,
                lambda args: context.move(int(args["step"])),
            ),
            Tool(
                "get_solve_stats",
                "The user's solve history: number of solves, average and best move counts, and the latest solves.",
                NO_ARGS,
                lambda args: context.solve_stats(),
            ),
        ]
    )


def fallback_answer(context: SnapshotContext, reason: str) -> Dict[str, Any]:
    """The built-in answer: the main facts from the same tools, with no model involved."""
    cube = context.cube_state()
    solution = context.solution()
    stats = context.solve_stats()

    parts: List[str] = [f"AI answers are off right now ({reason}), so here is what the app knows."]
    if not cube["has_cube"]:
        parts.append("There is no cube yet: scan it, or use Demo scramble.")
    elif cube["is_solved"]:
        parts.append("Your cube is solved.")
    elif cube["valid"]:
        parts.append("Your cube is valid and ready to solve.")
    elif cube["problems"]:
        problems = cube["problems"]
        parts.append(f"Your cube has {len(problems)} problem(s). First: {problems[0]['message']}")
    else:
        parts.append("Your cube is not valid yet.")
    if solution["has_solution"]:
        parts.append(f"The solution has {solution['move_count']} moves: {solution['moves']}.")
    if stats["total_solves"]:
        parts.append(
            f"You have {stats['total_solves']} solve(s); best {stats['best_moves']} moves, "
            f"average {stats['average_moves']} moves."
        )
    return {"answer": " ".join(parts)[:800], "suggestions": []}
