"""The RAG coach (Phase 7): answers cube questions from the app's own lessons, with citations.

RAG = retrieval-augmented generation: first *retrieve* the lesson sections that match
the question, then let the model *generate* an answer from them. The coach is a
small agent with one tool, ``search_lessons``, so it can search again with other words
when the first results don't fit.

Low hallucination by design:
- the prompt says: answer only from the passages, and say so when they don't cover it;
- every answer lists its ``citations`` (section ids) and the code checks them: each one
  must be a section that ``search_lessons`` returned in this run (``answer_check``);
- an answer marked ``covered`` must cite at least one section;
- the UI shows the cited sections next to the answer, so the user can check them.

Without AI, the built-in answer quotes the best keyword match, with its citation.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from backend.ai.retrieval import LessonIndex
from backend.ai.tools import Tool, ToolRegistry

SYSTEM_PROMPT = """You are the coach inside a Rubik's Cube app. You answer questions about \
solving and scanning a cube, using only the app's lessons.

How to work:
1. Call search_lessons with the question (or with better search words).
2. Answer only from the passages it returns. If they don't answer the question, you may \
search once more with other words.
3. If the lessons still don't cover it, set covered to false and say so in one sentence; \
do not answer from your own knowledge.

Rules:
- Cite the id of every passage you used in citations.
- Simple English, at most 5 short sentences. Keep move notation exactly as written (R, U', F2).
- When you are done, call final_answer on its own."""

ANSWER_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "answer": {"type": "string", "minLength": 1, "maxLength": 900, "description": "The answer for the user."},
        "citations": {
            "type": "array",
            "maxItems": 4,
            "items": {"type": "string", "minLength": 1, "maxLength": 120},
            "description": "Ids of the passages the answer uses (from search_lessons).",
        },
        "covered": {"type": "boolean", "description": "False if the lessons don't answer the question."},
        "suggestions": {
            "type": "array",
            "maxItems": 3,
            "items": {"type": "string", "minLength": 1, "maxLength": 80},
            "description": "Up to 3 short follow-up questions.",
        },
    },
    "required": ["answer", "citations", "covered"],
    "additionalProperties": False,
}

SEARCH_ARGS: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "minLength": 2, "maxLength": 200, "description": "What to look for."},
    },
    "required": ["query"],
    "additionalProperties": False,
}

TOOL_NAMES = ["search_lessons"]


class CoachContext:
    """One question's retrieval: remembers every section it has shown the model."""

    def __init__(self, index: LessonIndex) -> None:
        self.index = index
        self.seen: Set[str] = set()  # section ids returned by search_lessons in this run
        self.methods: List[str] = []  # "pgvector", "vectors in Python" or "keywords", per search

    def search(self, query: str) -> Dict[str, Any]:
        result = self.index.search(query, k=4)
        self.methods.append(result.method)
        self.seen.update(hit.chunk.id for hit in result.hits)
        payload: Dict[str, Any] = {
            "passages": [
                {"id": hit.chunk.id, "lesson": hit.chunk.lesson_title, "section": hit.chunk.section, "text": hit.chunk.text}
                for hit in result.hits
            ],
        }
        if not result.hits:
            payload["note"] = "Nothing matched. Try other words, or say the lessons don't cover it."
        return payload

    def check_answer(self, answer: Dict[str, Any]) -> List[str]:
        """The coach's grounding rules (see AgentTask.answer_check)."""
        unknown = [cid for cid in answer["citations"] if cid not in self.seen]
        if unknown:
            return [f"citations {unknown} were not returned by search_lessons; cite only passage ids you were given"]
        if answer["covered"] and not answer["citations"]:
            return ["a covered answer must cite at least one passage"]
        return []

    def sources(self, citations: List[str]) -> List[Dict[str, Any]]:
        """The cited sections, for the UI (section text comes from the lessons, not the model)."""
        found = [self.index.get(cid) for cid in citations]
        return [
            {"id": chunk.id, "lesson": chunk.lesson, "lessonTitle": chunk.lesson_title, "section": chunk.section}
            for chunk in found
            if chunk is not None
        ]


def build_tools(context: CoachContext) -> ToolRegistry:
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


def fallback_answer(context: CoachContext, question: str, reason: Optional[str]) -> Dict[str, Any]:
    """The built-in answer: the best keyword match, quoted, with its citation. No model involved."""
    prefix = f"AI answers are off right now ({reason}), so here is the closest lesson. " if reason else ""
    hits = context.index.keywords.search(question, k=2)
    if not hits:
        return {"answer": prefix + "The lessons don't cover that question.", "citations": [], "covered": False}
    chunk = hits[0][0]
    excerpt = chunk.text if len(chunk.text) <= 420 else chunk.text[:420].rsplit(" ", 1)[0] + " ..."
    answer = f'{prefix}From "{chunk.lesson_title}", {chunk.section}: {" ".join(excerpt.split())}'
    return {"answer": answer[:900], "citations": [chunk.id], "covered": True}
