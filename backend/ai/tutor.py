"""The AI Tutor (Phase 8): explains the beginner method on the learner's own cube.

The learner solves their real cube on the Learn page. Code knows the cube: the stage,
the next step, the piece, the algorithm and the exact moves (``backend/core/beginner.py``,
``backend/services/learn.py``). The tutor turns those facts into words:

- **hints**, in levels: 1 = what to look at, 2 = which algorithm and when;
  (level 3, the exact moves, comes straight from code: no model needed);
- **answers** to "why?" questions, from the lessons, with citations (Phase 7's search);
- a short **recap** when the cube is solved.

Checked in code, so the tutor can't mislead (AI rules 1 and 3):

- citations must be lesson sections that ``search_lessons`` returned in this run;
- every move sequence it writes (two or more moves in a row) must be one the code
  allowed for this request (the step's algorithm, a lesson's sequence ...). Hint 1 may
  write none: it must make the learner look, not tell them what to do.

Without AI, every request has a built-in answer from the same facts.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Sequence, Set

from backend.ai.coach import CoachContext
from backend.ai.coach import fallback_answer as coach_fallback
from backend.ai.retrieval import LessonIndex
from backend.ai.tools import Tool, ToolRegistry

SYSTEM_PROMPT = """You are a friendly Rubik's Cube tutor inside a learning app. The learner is \
solving their own real cube with the beginner method, stage by stage. They tap every move into \
the app, so the app knows their cube exactly.

The app's code knows the cube; you explain it. The facts you are given (stage, piece, where it \
is, algorithm, moves) come from the app's solver and are always right. Never invent moves, piece \
positions or cube states.

Rules:
- Simple, warm English, at most 3 short sentences. Talk to the learner ("you").
- Keep move notation exactly as given (R, U', F2).
- Hint level 1: help them see what to look at. Never write moves.
- Hint level 2: name the algorithm, say when to use it, and write it as given.
- Questions: call search_lessons, answer only from the passages and the facts, and cite the ids \
you used. If neither covers it, say so in one sentence.
- Recap: congratulate them, name one thing they did well and one thing to practise next.
- When you are done, call final_answer on its own."""

ANSWER_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "message": {"type": "string", "minLength": 1, "maxLength": 600, "description": "What the learner reads."},
        "citations": {
            "type": "array",
            "maxItems": 3,
            "items": {"type": "string", "minLength": 1, "maxLength": 120},
            "description": "Ids of the lesson passages you used (from search_lessons); [] if none.",
        },
    },
    "required": ["message", "citations"],
    "additionalProperties": False,
}

SEARCH_ARGS: Dict[str, Any] = {
    "type": "object",
    "properties": {"query": {"type": "string", "minLength": 2, "maxLength": 200, "description": "What to look for."}},
    "required": ["query"],
    "additionalProperties": False,
}

TOOL_NAMES = ["search_lessons"]

#: One move written in the text: a face letter, then ', ’ or 2, standing alone.
_MOVE = re.compile(r"(?<![\w'’])([URFDLB])(2|'|’)?(?![\w'’])")


def move_runs(text: str) -> List[List[str]]:
    """Sequences of two or more moves written one after the other, e.g. "do R U R' U'"."""
    runs: List[List[str]] = []
    current: List[str] = []
    end = None
    for match in _MOVE.finditer(text):
        move = match.group(1) + ("'" if match.group(2) in ("'", "’") else match.group(2) or "")
        if current and end is not None and text[end:match.start()].strip(" ,") == "":
            current.append(move)
        else:
            if len(current) >= 2:
                runs.append(current)
            current = [move]
        end = match.end()
    if len(current) >= 2:
        runs.append(current)
    return runs


def _inside(run: Sequence[str], sequence: Sequence[str]) -> bool:
    """True if ``run`` appears in ``sequence`` as consecutive moves."""
    n = len(run)
    return any(list(sequence[i:i + n]) == list(run) for i in range(len(sequence) - n + 1))


class TutorContext:
    """One tutor request: its facts, the move sequences it may write, and the lesson search."""

    def __init__(self, kind: str, facts: Dict[str, Any], allowed: List[List[str]],
                 lessons: Optional[LessonIndex], question: str = "") -> None:
        self.kind = kind  # "hint", "question" or "recap"
        self.facts = facts
        self.allowed = allowed
        self.question = question
        self.coach = CoachContext(lessons) if lessons is not None else None
        self.passage_runs: List[List[str]] = []  # move sequences in the passages it was shown
        step = facts.get("step") or {}
        for key in ("how", "moves"):  # sequences in the facts it was given come from code too
            self.allowed = self.allowed + move_runs(step.get(key, ""))

    @property
    def seen(self) -> Set[str]:
        return self.coach.seen if self.coach is not None else set()

    def prompt(self) -> str:
        """The request the model gets: what to do, then the facts as JSON."""
        if self.kind == "hint":
            ask = f"Give hint level {self.facts['hintLevel']} for the learner's next step."
        elif self.kind == "question":
            ask = f"The learner asks: {self.question}"
        else:
            ask = "The learner just solved the cube. Write a short recap."
        return f"{ask}\n\nFacts from the app (always right):\n{json.dumps(self.facts, indent=1)}"

    def search(self, query: str) -> Dict[str, Any]:
        if self.coach is None:
            return {"error": "The lessons are not loaded."}
        result = self.coach.search(query)
        for passage in result["passages"]:
            self.passage_runs += move_runs(passage["text"])
        return result

    def check_answer(self, answer: Dict[str, Any]) -> List[str]:
        """The tutor's rules, checked in code (see AgentTask.answer_check)."""
        problems = []
        unknown = [cid for cid in answer["citations"] if cid not in self.seen]
        if unknown:
            problems.append(f"citations {unknown} were not returned by search_lessons; cite only passage ids you were given")
        allowed = self.allowed + self.passage_runs
        for run in move_runs(answer["message"]):
            if not any(_inside(run, sequence) for sequence in allowed):
                if not allowed:
                    problems.append("this hint must not contain moves: help the learner look, don't tell them what to turn")
                else:
                    options = "; ".join(" ".join(seq) for seq in allowed[:6])
                    problems.append(f"the moves '{' '.join(run)}' don't come from the app; you may only write these: {options}")
                break
        return problems

    def sources(self, citations: List[str]) -> List[Dict[str, Any]]:
        return self.coach.sources(citations) if self.coach is not None else []

    # ------------------------------------------------------------------
    def fallback(self, reason: Optional[str]) -> Dict[str, Any]:
        """The built-in answer, from the same facts (no model)."""
        step = self.facts.get("step") or {}
        if self.kind == "hint":
            text = step.get("look") if self.facts["hintLevel"] <= 1 else step.get("how")
            return {"message": text or "Follow the moves shown.", "citations": []}
        if self.kind == "recap":
            return {"message": recap_text(self.facts.get("stats", {})), "citations": []}
        if self.coach is None:
            return {"message": "The lessons are not loaded, so I can't answer that right now.", "citations": []}
        answer = coach_fallback(self.coach, self.question, reason)
        return {"message": answer["answer"][:600], "citations": answer["citations"]}


def build_tools(context: TutorContext) -> ToolRegistry:
    return ToolRegistry(
        [
            Tool(
                "search_lessons",
                "Search the app's cube lessons. Returns up to 4 passages, each with an id to cite.",
                SEARCH_ARGS,
                lambda args: context.search(str(args["query"])),
            )
        ]
    )


def recap_text(stats: Dict[str, Any]) -> str:
    """The built-in recap: what the learner did, and what to practise."""
    alone = stats.get("stagesAlone", [])
    helped = stats.get("stagesWithHelp", [])
    minutes = max(1, round(stats.get("seconds", 0) / 60))
    text = f"You solved your cube in {stats.get('moves', 0)} moves and about {minutes} min. "
    if alone:
        text += f"You did {len(alone)} of 7 stages without help. "
    if helped:
        practise = stats.get("practise") or helped[0]
        text += f"Practise the {practise.lower()} stage next, until you can do it without hints."
    else:
        text += "Next, try a whole solve without the app, then learn finger tricks (lesson 8)."
    return text
