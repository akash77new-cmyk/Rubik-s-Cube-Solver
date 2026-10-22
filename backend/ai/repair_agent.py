"""The Smart Repair Agent (Phase 5): after an unsolvable scan, find the misread sticker(s).

How the work is split (AI rules 1, 2 and 7):

- **Code proves.** ``backend/core/repair.py`` finds every 1- or 2-sticker change
  that makes the cube valid; the validator decides, not the model.
- **The agent decides and explains.** It reads the problems, the stickers the camera
  doubted and the valid fixes, then either picks one fix *by its id* or asks the user
  to rescan one side. It never writes colours or a cube state itself.
- **The user confirms.** The proposal is only applied when the user presses Apply.

Without AI (no key, quota used up, an error), ``fallback_answer`` proposes the
search's best fix, or a rescan of the side the camera was least sure about.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from backend.ai.tools import NO_ARGS, Tool, ToolRegistry
from backend.core.cube import COLOR_NAMES, FACE_ORDER, CubeState
from backend.core.repair import RepairSearch, Readings, find_repairs

SYSTEM_PROMPT = """You are the repair assistant inside a Rubik's Cube scanner app. The user \
has scanned all six sides with a camera, but the cube is not solvable, so the camera misread \
one or more stickers.

How to work:
1. Call get_problems, get_suspect_stickers and find_fixes.
2. find_fixes lists the only changes proven to make the cube valid. If one fix is clearly \
the most likely (the camera doubted the colours it changes), choose it with action \
"apply_fix" and its fix_id.
3. If there is no fix, or several fixes are equally likely, choose action "rescan_side" \
and the side to rescan (the side whose stickers the camera doubted most).

Rules:
- Never invent colours, stickers or fixes. Only use fix ids from find_fixes.
- The message is for the user: simple English, at most 3 short sentences. Name sides by \
their centre colour and stickers by position (for example "the top-left sticker of the \
White side"), and say why (for example "the camera was only 51% sure it was orange").
- When you are done, call final_answer on its own."""

ANSWER_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["apply_fix", "rescan_side"],
            "description": "apply_fix: propose one fix from find_fixes. rescan_side: ask the user to rescan a side.",
        },
        "fix_id": {"type": "integer", "minimum": 1, "maximum": 5, "description": "For apply_fix: the fix's id."},
        "side": {"type": "string", "enum": list(FACE_ORDER), "description": "For rescan_side: the side's letter."},
        "message": {"type": "string", "minLength": 1, "maxLength": 400, "description": "What to tell the user."},
    },
    "required": ["action", "message"],
    "additionalProperties": False,
}

TOOL_NAMES = ["get_problems", "get_suspect_stickers", "find_fixes"]

POSITIONS = (
    "top-left", "top", "top-right", "left", "centre", "right", "bottom-left", "bottom", "bottom-right",
)


class RepairContext:
    """One unsolvable cube, with the camera's readings, and its search result (computed once)."""

    def __init__(self, cube: CubeState, readings: Optional[Readings] = None) -> None:
        self.cube = cube
        self.readings = readings
        self.validation = cube.validate()
        self._search: Optional[RepairSearch] = None

    @property
    def search(self) -> RepairSearch:
        if self._search is None:
            self._search = find_repairs(self.cube, self.readings)
        return self._search

    def side(self, face: str) -> str:
        return f"{COLOR_NAMES[self.cube.centers[face]]} side ({face})"

    def where(self, face: str, index: int) -> str:
        return f"{POSITIONS[index]} sticker of the {self.side(face)}"

    def question(self) -> str:
        return "The scanned cube is not solvable: " + " ".join(self.validation.errors[:4])

    # --- the tools ---------------------------------------------------------------
    def problems(self) -> Dict[str, Any]:
        return {
            "valid": self.validation.ok,
            "problems": [
                {
                    "code": issue.code,
                    "message": issue.message,
                    "stickers": [self.where(face, index) for face, index in issue.stickers[:6]],
                }
                for issue in self.validation.issues[:6]
            ],
        }

    def suspects(self) -> Dict[str, Any]:
        if not self.readings:
            return {"stickers": [], "note": "No camera readings: this cube was typed in or edited by hand."}
        rows = []
        for face in FACE_ORDER:
            for index, reading in enumerate(self.readings.get(face, [])):
                if index == 4:
                    continue  # centres are fixed: a side is identified by its centre
                alternatives = reading.get("alternatives") or []
                second = alternatives[1] if len(alternatives) > 1 else None
                rows.append({
                    "sticker": self.where(face, index),
                    "read_as": COLOR_NAMES.get(reading.get("color", ""), "?"),
                    "confidence": reading.get("confidence", 1.0),
                    "second_guess": COLOR_NAMES.get(second["color"], "?") if second else None,
                    "second_guess_confidence": second["confidence"] if second else None,
                    "unsure": reading.get("uncertain"),
                })
        rows.sort(key=lambda row: row["confidence"])
        return {"stickers": rows[:10], "note": "Least confident first. Confidence is 0 to 1."}

    def fixes(self) -> Dict[str, Any]:
        search = self.search
        fixes = [
            {
                "id": candidate.id,
                "changes": [
                    {
                        "sticker": self.where(change.face, change.index),
                        "from": COLOR_NAMES[change.old],
                        "to": COLOR_NAMES[change.new],
                        "camera_confidence_in_old_colour": change.old_confidence,
                        "camera_score_for_new_colour": change.new_confidence,
                    }
                    for change in candidate.changes
                ],
                "score": candidate.cost,
            }
            for candidate in search.candidates
        ]
        note = (
            f"{search.total} fix(es) make the cube valid; the best {len(fixes)} are listed. "
            "A lower score means the camera doubted these stickers more."
            if fixes
            else "No change of 1 or 2 stickers makes the cube valid. Ask the user to rescan a side."
        )
        return {"fixes": fixes, "note": note}

    # --- checking and turning answers into proposals ---------------------------------
    def check_answer(self, answer: Dict[str, Any]) -> List[str]:
        """The agent's extra answer rules (see AgentTask.answer_check)."""
        ids = [candidate.id for candidate in self.search.candidates]
        if answer["action"] == "apply_fix" and answer.get("fix_id") not in ids:
            return [f"fix_id must be one of {ids} (from find_fixes)" if ids else "There are no fixes: use rescan_side"]
        if answer["action"] == "rescan_side" and "side" not in answer:
            return ["rescan_side needs a side"]
        return []

    def weakest_side(self) -> str:
        """The side to rescan when nothing else helps: the least confident reading, or a flagged side."""
        if self.readings:
            def worst(face: str) -> float:
                return min((r.get("confidence", 1.0) for i, r in enumerate(self.readings.get(face, [])) if i != 4), default=1.0)
            return min(FACE_ORDER, key=worst)
        flagged = [face for issue in self.validation.issues for face, _ in issue.stickers]
        return max(FACE_ORDER, key=flagged.count) if flagged else FACE_ORDER[0]

    def proposal(self, answer: Dict[str, Any], source: str, model: Optional[str], reason: Optional[str]) -> Dict[str, Any]:
        """What the UI shows. The changes always come from the code's candidate, never the model."""
        changes: List[Dict[str, Any]] = []
        side = answer.get("side")
        if answer["action"] == "apply_fix":
            candidate = next(c for c in self.search.candidates if c.id == answer["fix_id"])
            changes = [change.to_dict() for change in candidate.changes]
            side = None
        return {
            "action": answer["action"],
            "message": answer["message"],
            "changes": changes,
            "side": side,
            "source": source,
            "model": model,
            "reason": reason,
            "fixesFound": self.search.total,
            "cube": self.cube.to_color_string(),  # the cube this proposal was made for
        }


def build_tools(context: RepairContext) -> ToolRegistry:
    """The repair agent's tools. All read-only."""
    return ToolRegistry(
        [
            Tool("get_problems", "Why the cube is not solvable, with the stickers involved.", NO_ARGS,
                 lambda args: context.problems()),
            Tool("get_suspect_stickers",
                 "The stickers the camera was least sure about: what it read, how sure it was, and its second guess.",
                 NO_ARGS, lambda args: context.suspects()),
            Tool("find_fixes",
                 "Fixes of 1 or 2 sticker changes that are proven to make the cube valid, most likely first.",
                 NO_ARGS, lambda args: context.fixes()),
        ]
    )


def fallback_answer(context: RepairContext, reason: Optional[str]) -> Dict[str, Any]:
    """The built-in answer: the search's best fix, or a rescan. No model involved."""
    prefix = f"AI help is off right now ({reason}), so this comes from the built-in search. " if reason else ""
    candidates = context.search.candidates
    if candidates:
        best = candidates[0]
        parts = []
        for change in best.changes:
            sure = f" (the camera was {change.old_confidence:.0%} sure)" if change.old_confidence < 1 else ""
            parts.append(
                f"the {context.where(change.face, change.index)} is "
                f"{COLOR_NAMES[change.new].lower()}, not {COLOR_NAMES[change.old].lower()}{sure}"
            )
        others = context.search.total - 1
        tail = f" {others} other fix(es) would also work, so check it against your cube." if others else ""
        message = prefix + "Most likely " + " and ".join(parts) + "." + tail
        return {"action": "apply_fix", "fix_id": best.id, "message": message[:400]}
    side = context.weakest_side()
    message = (
        prefix + "No change of one or two stickers makes this cube valid. "
        f"Rescan the {context.side(side)}: the camera was least sure about it."
    )
    return {"action": "rescan_side", "side": side, "message": message[:400]}
