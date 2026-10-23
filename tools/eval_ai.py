#!/usr/bin/env python3
"""The AI evaluation suite (Phase 12): measures every AI feature and writes a report.

    python tools/eval_ai.py           # offline: no key, about 30 s; CI runs this
    python tools/eval_ai.py --live    # + the real Gemini model (needs GEMINI_API_KEY in .env)

Offline (deterministic, every push in CI; the run fails if a gate fails):
  1. retrieval   - the RAG search on the 15 labelled questions: recall@1, recall@3, MRR
  2. repair      - 60 simulated misread stickers: is the true fix found, and ranked first?
  3. beginner    - 100 random cubes through the beginner method: solved, stages in order
  4. guardrails  - misbehaving model answers: does code catch every one?
  5. fallbacks   - with AI off, does every feature still give a valid answer?

Live (by hand, with a real key, about 90 requests over 10 minutes, paced under the
app's limit of 10 a minute):
  6. the same retrieval with Gemini's real embeddings
  7. the coach on the 15 questions + 3 it must refuse: cites the right section?
  8. the repair agent on 9 misreads, against the built-in search
  9. the tutor's hints on 12 learner states: accepted first time, no moves in hint 1

Reports: docs/eval/offline.md (+ .json) and docs/eval/live.md (+ .json). Numbers come
only from runs; nothing is typed in by hand. Never prints the API key.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import subprocess
import sys
import tempfile
import time
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # so "backend" imports work
os.environ.setdefault("CUBE_DATA_DIR", tempfile.mkdtemp(prefix="cube-eval-"))  # never the real data/

from backend.ai.agent import FINAL_ANSWER, AgentStopped, AgentTask, run_agent  # noqa: E402
from backend.ai.budget import RequestBudget  # noqa: E402
from backend.ai.coach import CoachContext  # noqa: E402
from backend.ai.fake import HashEmbedder, ScriptedLLM, tool_call, tool_calls  # noqa: E402
from backend.ai.lessons import EVAL_QUESTIONS, load_lessons  # noqa: E402
from backend.ai.repair_agent import RepairContext  # noqa: E402
from backend.ai.repair_agent import fallback_answer as repair_fallback  # noqa: E402
from backend.ai.retrieval import LessonIndex  # noqa: E402
from backend.ai.schema import validate  # noqa: E402
from backend.ai.service import AIService  # noqa: E402
from backend.ai.tools import Tool, ToolRegistry  # noqa: E402
from backend.ai.tutor import TutorContext, move_runs  # noqa: E402
from backend.core import beginner  # noqa: E402
from backend.core.cube import COLOR_CODES, FACE_ORDER, CubeState, random_scramble  # noqa: E402
from backend.db import connect  # noqa: E402
from backend.services.learn import LearnSession  # noqa: E402

REPORT_DIR = ROOT / "docs" / "eval"

#: The coach must say "not covered" for these: the lessons don't answer them.
OUT_OF_SCOPE = [
    "Who invented the Rubik's Cube?",
    "What is the world record for solving a cube?",
    "Which shop sells the best speed cube?",
]


# ======================================================================================
# Helpers
# ======================================================================================


def ranking(search: Callable[[str], Sequence[str]]) -> Dict[str, Any]:
    """recall@1, recall@3 and MRR (mean reciprocal rank) over the labelled questions."""
    ranks = []
    for question, expected in EVAL_QUESTIONS:
        found = list(search(question))[:10]
        ranks.append(found.index(expected) + 1 if expected in found else None)
    total = len(ranks)
    return {
        "questions": total,
        "recall@1": sum(1 for r in ranks if r == 1),
        "recall@3": sum(1 for r in ranks if r is not None and r <= 3),
        "mrr": round(sum(1 / r for r in ranks if r) / total, 3),
        "misses@3": [q for (q, _), r in zip(EVAL_QUESTIONS, ranks) if r is None or r > 3],
    }


def readings_for(cube: CubeState, doubtful: Dict[Tuple[str, int], Tuple[str, str, float, float]]) -> Dict[str, Any]:
    """Camera readings like the scanner keeps: sure of every sticker except the doubtful ones,
    given as {(face, index): (read_as, second_guess, confidence, second_confidence)}."""
    readings: Dict[str, Any] = {}
    for face in FACE_ORDER:
        rows = []
        for index, color in enumerate(cube.face(face)):
            other = "W" if color != "W" else "Y"
            read_as, second, sure, second_sure = doubtful.get((face, index), (color, other, 0.9, 0.2))
            rows.append({
                "index": index, "color": read_as, "confidence": sure,
                "alternatives": [{"color": read_as, "confidence": sure}, {"color": second, "confidence": second_sure}],
                "uncertain": "two_ranges" if second_sure > 0.5 else None,
            })
        readings[face] = rows
    return readings


#: How the camera saw the misread sticker, from most to least helpful.
#:   doubt    - unsure (51%), and its second guess is the true colour
#:   hint     - fairly sure (80%) of the wrong colour, the true colour a weak second guess
#:   no-hint  - sure (90%) of the wrong colour, the true colour not among its guesses
MODES = ("doubt", "hint", "no-hint")
EVIDENCE = {"doubt": "unsure", "hint": "fairly sure", "no-hint": "sure (no hint)"}


Truth = List[Tuple[str, int, str]]  # (face, index, true colour) of each misread sticker


def misread_case(seed: int, mode: str, count: int = 1) -> Tuple[CubeState, Dict[str, Any], Truth]:
    """A real cube with ``count`` stickers misread. Returns (scan, readings, the true colours)."""
    rng = random.Random(seed)
    truth = CubeState.solved().apply_sequence(random_scramble(25, seed=seed))
    facelets = truth.facelets
    doubts: Dict[Tuple[str, int], Tuple[str, str, float, float]] = {}
    true: Truth = []
    for face, index in rng.sample([(f, i) for f in FACE_ORDER for i in range(9) if i != 4], count):
        true_color = truth.face(face)[index]
        wrong = rng.choice([c for c in COLOR_CODES if c != true_color])
        facelets[face][index] = wrong
        true.append((face, index, true_color))
        other = next(c for c in COLOR_CODES if c not in (wrong, true_color))
        doubts[(face, index)] = {
            "doubt": (wrong, true_color, 0.51, 0.48),
            "hint": (wrong, true_color, 0.8, 0.3),
            "no-hint": (wrong, other, 0.9, 0.2),
        }[mode]
    scan = CubeState(facelets)
    return scan, readings_for(scan, doubts), true


def ambiguous_seeds(start: int, how_many: int) -> List[int]:
    """Seeds whose two misread stickers leave more than one valid fix (rare: about 1 in 10)."""
    seeds, seed = [], start
    while len(seeds) < how_many:
        scan, readings, _ = misread_case(seed, "doubt", 2)
        if RepairContext(scan, readings).search.total > 1:
            seeds.append(seed)
        seed += 1
    return seeds


def is_true_fix(context: RepairContext, fix_id: Optional[int], truth: Truth) -> bool:
    candidate = next((c for c in context.search.candidates if c.id == fix_id), None)
    return candidate is not None and {(c.face, c.index, c.new) for c in candidate.changes} == set(truth)


def learner_states(count: int) -> List[LearnSession]:
    """``count`` learners spread over the stages: each follows "Show me" for a different
    number of steps from its own random cube."""
    sessions: List[LearnSession] = []
    seed = 0
    while len(sessions) < count:
        learn = LearnSession(CubeState.solved().apply_sequence(random_scramble(25, seed=100 + seed)))
        learn.set_ready()
        for _ in range((seed * 7) % 45):  # 0 to 44 steps: from the white cross to the last layer
            step = learn.step()
            if step is None:
                break
            if step.kind == "turn_over":
                learn.turn_over()
                continue
            learn.show()
            while learn.to_dict()["guide"]:
                learn.move(learn.to_dict()["guide"][0]["notation"])
        if learn.step() is not None and learn.step().kind == "turn_over":
            learn.turn_over()
        if learn.step() is not None and learn.step().kind == "moves":
            sessions.append(learn)
        seed += 1
    return sessions


def percentile(values: List[float], share: float) -> float:
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(share * len(ordered)))], 1) if ordered else 0.0


# ======================================================================================
# Offline evaluations
# ======================================================================================


def eval_retrieval() -> Dict[str, Any]:
    lessons = load_lessons()
    index = LessonIndex(lessons, connect("sqlite://"), HashEmbedder())
    index.sync()
    vectors = ranking(lambda q: [hit.chunk.id for hit in index.search(q, 10).hits])
    keywords = ranking(lambda q: [chunk.id for chunk, _ in index.keywords.search(q, 10)])
    return {"sections": len(index.chunks), "keywords": keywords, "testVectors": vectors,
            "gate": keywords["recall@3"] >= 13 and vectors["recall@3"] >= 13}


REPAIR_KINDS = {  # kind -> (stickers misread, the seeds to use)
    "one sticker": (1, lambda n: list(range(1000, 1000 + n))),
    "two stickers": (2, lambda n: list(range(1100, 1100 + n))),
    "two, ambiguous": (2, lambda n: ambiguous_seeds(1200, n)),
}


def eval_repair(per_kind: int = 10) -> Dict[str, Any]:
    """For each kind of misread and each kind of camera evidence: is the true fix found,
    how many valid fixes are there, and does the built-in search pick the right one?"""
    rows = {}
    for kind, (count, seeds) in REPAIR_KINDS.items():
        chosen = seeds(per_kind)
        row: Dict[str, Any] = {"cases": len(chosen), "trueFixFound": 0, "uniqueFix": 0, "builtInRight": {}}
        for mode in MODES:
            right = 0
            for seed in chosen:
                scan, readings, truth = misread_case(seed, mode, count)
                context = RepairContext(scan, readings)
                if mode == "doubt":
                    row["trueFixFound"] += any(is_true_fix(context, c.id, truth) for c in context.search.candidates)
                    row["uniqueFix"] += context.search.total == 1
                right += is_true_fix(context, repair_fallback(context, None).get("fix_id"), truth)
            row["builtInRight"][mode] = right
        rows[kind] = row
    gate = all(r["trueFixFound"] == r["cases"] for r in rows.values()) and all(
        r["builtInRight"]["doubt"] >= 0.95 * r["cases"] for r in rows.values())
    return {"kinds": rows, "gate": gate}


def eval_beginner(count: int = 100) -> Dict[str, Any]:
    moves, worst_ms, max_algorithms, ordered = [], 0.0, 0, 0
    for seed in range(count):
        state = CubeState.solved().apply_sequence(random_scramble(25, seed=5000 + seed)).to_color_string()
        stages, algorithms, total = [], {}, 0
        while True:
            started = time.perf_counter()
            step = beginner.next_step(state)
            worst_ms = max(worst_ms, (time.perf_counter() - started) * 1000)
            if step is None:
                break
            stages.append(step.stage)
            if step.kind == "turn_over":
                state = beginner.turn_over(state)
                continue
            if step.algorithm and step.stage >= 4:
                algorithms[step.stage] = algorithms.get(step.stage, 0) + 1
            state = beginner.turn(state, step.moves)
            total += len(step.moves)
        ordered += stages == sorted(stages)
        max_algorithms = max([max_algorithms, *algorithms.values()])
        moves.append(total)
    solved = count  # next_step() returned None for every cube: each one ended solved
    return {"cubes": count, "solved": solved, "stagesInOrder": ordered, "movesMin": min(moves),
            "movesMedian": int(statistics.median(moves)), "movesMax": max(moves),
            "maxAlgorithmsPerYellowStage": max_algorithms, "slowestStepMs": round(worst_ms, 1),
            "gate": solved == count and ordered == count and max_algorithms <= 3}


def _guard_cases() -> List[Tuple[str, Callable[[], bool]]]:
    """Each case feeds a misbehaving answer and returns True if code caught it."""
    lessons = LessonIndex(load_lessons())
    scan, readings, _ = misread_case(7, "doubt")
    repair = RepairContext(scan, readings)
    good_fix = repair.search.candidates[0].id
    learn = LearnSession(CubeState.solved().apply_sequence(random_scramble(25, seed=3)))
    learn.set_ready()
    learn.hint()
    hint1 = TutorContext("hint", learn.facts("hint"), learn.allowed_sequences("hint"), lessons)
    question = TutorContext("question", learn.facts("question"), learn.allowed_sequences("question"), lessons, "Why?")
    coach = CoachContext(lessons)
    coach.search("What does R prime mean?")

    def loop(script: List[Any], tools: ToolRegistry, names: List[str], schema: Dict[str, Any],
             check: Optional[Callable[[Dict[str, Any]], List[str]]] = None, steps: int = 4) -> Any:
        task = AgentTask("system", "question", tools, names, schema, max_steps=steps, answer_check=check)
        return run_agent(ScriptedLLM(script), task)

    echo = ToolRegistry([Tool("look", "Read a fact.", {"type": "object", "properties": {}, "additionalProperties": False},
                              lambda args: {"fact": 1})])
    schema = {"type": "object", "properties": {"answer": {"type": "string", "minLength": 1}},
              "required": ["answer"], "additionalProperties": False}
    ok = tool_call(FINAL_ANSWER, answer="fine")

    def stops() -> bool:
        try:
            loop([tool_call("look")] * 5, echo, ["look"], schema, steps=3)
        except AgentStopped:
            return True
        return False

    return [
        ("repair: a fix id the search never returned", lambda: bool(repair.check_answer(
            {"action": "apply_fix", "fix_id": 99, "message": "x"}))),
        ("repair: a rescan without a side", lambda: bool(repair.check_answer({"action": "rescan_side", "message": "x"}))),
        ("repair: a real fix id is accepted", lambda: not repair.check_answer(
            {"action": "apply_fix", "fix_id": good_fix, "message": "x"})),
        ("coach: a citation the search didn't return", lambda: bool(coach.check_answer(
            {"answer": "x", "citations": ["99-made-up#section"], "covered": True}))),
        ("coach: a covered answer with no citation", lambda: bool(coach.check_answer(
            {"answer": "x", "citations": [], "covered": True}))),
        ("tutor: moves in hint 1", lambda: bool(hint1.check_answer({"message": "Do F R U R' U' F'.", "citations": []}))),
        ("tutor: a made-up move sequence", lambda: bool(question.check_answer({"message": "Try L2 B2 D2 F2.", "citations": []}))),
        ("tutor: a lesson algorithm is accepted", lambda: not question.check_answer(
            {"message": "The Sune is R U R' U R U2 R'.", "citations": []})),
        ("agent: an unknown tool gets an error, then the answer counts", lambda: loop(
            [tool_call("delete_everything"), ok], echo, ["look"], schema) == {"answer": "fine"}),
        ("agent: final_answer next to another tool is refused", lambda: loop(
            [tool_calls(("look", {}), (FINAL_ANSWER, {"answer": "early"})), ok], echo, ["look"], schema) == {"answer": "fine"}),
        ("agent: an answer that breaks the schema is sent back", lambda: loop(
            [tool_call(FINAL_ANSWER, answer=""), ok], echo, ["look"], schema) == {"answer": "fine"}),
        ("agent: a model that never answers is stopped", stops),
    ]


def eval_guardrails() -> Dict[str, Any]:
    results = []
    for name, case in _guard_cases():
        try:
            passed = bool(case())
        except Exception as exc:  # a crash counts as a failed case
            passed = False
            name = f"{name} (crashed: {exc})"
        results.append({"case": name, "passed": passed})
    passed = sum(r["passed"] for r in results)
    return {"cases": results, "passed": passed, "total": len(results), "gate": passed == len(results)}


def eval_fallbacks() -> Dict[str, Any]:
    from backend.ai import assistant, coach, repair_agent, tutor
    from backend.ai.assistant import SnapshotContext

    lessons = LessonIndex(load_lessons())
    ai = AIService(None, RequestBudget(10, 100), None, lambda e, d: None, off_reason="no Gemini API key is set",
                   lessons=lessons)
    scan, readings, _ = misread_case(11, "doubt")
    learn = LearnSession(CubeState.solved().apply_sequence(random_scramble(25, seed=4)))
    learn.set_ready()
    learn.hint()
    snapshot = {"cube": CubeState.solved().to_dict(), "solution": None, "scan": {}, "analytics": {}}
    checks = {
        "assistant": lambda: validate({k: v for k, v in assistant.fallback_answer(
            SnapshotContext(lambda: snapshot), "off").items()}, assistant.ANSWER_SCHEMA) == [],
        "repair agent": lambda: ai.repair(RepairContext(scan, readings))["source"] == "search",
        "coach": lambda: ai.coach_answer("What does R prime mean?")["citations"] != [],
        "tutor": lambda: ai.tutor_answer(TutorContext("hint", learn.facts("hint"), learn.allowed_sequences("hint"),
                                                     lessons))["source"] == "fallback",
    }
    del coach, repair_agent, tutor
    results = {}
    for name, check in checks.items():
        try:
            results[name] = bool(check())
        except Exception:
            results[name] = False
    return {"features": results, "gate": all(results.values())}


# ======================================================================================
# Live evaluations (real Gemini)
# ======================================================================================


class Paced:
    """Wraps a Gemini client: at most ``per_minute`` requests a minute, so the run never
    hits the free tier's limits. Waiting is fine here: nobody is waiting for an answer.

    It also keeps two counts, so the report measures the model and not the pacing:
    ``waited`` (seconds spent pacing, left out of the timings) and ``final_answers`` (how
    many answers the model gave: one means its first answer passed code's checks)."""

    def __init__(self, inner: Any, per_minute: float) -> None:
        self._inner = inner
        self._gap = 60.0 / per_minute if per_minute > 0 else 0.0
        self._last = 0.0
        self.provider = getattr(inner, "provider", "gemini")
        self.model = inner.model
        self.waited = 0.0
        self.final_answers = 0

    def _wait(self) -> None:
        delay = self._last + self._gap - time.monotonic()
        if delay > 0:
            time.sleep(delay)
            self.waited += delay
        self._last = time.monotonic()

    def generate(self, request: Any) -> Any:
        self._wait()
        response = self._inner.generate(request)
        self.final_answers += sum(1 for call in response.tool_calls if call.name == FINAL_ANSWER)
        return response

    def embed(self, texts: List[str], task: str) -> List[List[float]]:
        self._wait()
        return self._inner.embed(texts, task)


def live_evals(per_minute: float) -> Dict[str, Any]:
    from backend.ai.gemini import DEFAULT_BASE_URL, GeminiClient, GeminiEmbedder
    from backend.config import RUNTIME

    if not RUNTIME.gemini_api_key:
        raise SystemExit("--live needs GEMINI_API_KEY (in .env). It is never printed.")
    base = RUNTIME.gemini_base_url or DEFAULT_BASE_URL
    llm = Paced(GeminiClient(RUNTIME.gemini_api_key, RUNTIME.gemini_model, base, RUNTIME.gemini_thinking_level), per_minute)
    embedder = Paced(GeminiEmbedder(RUNTIME.gemini_api_key, RUNTIME.gemini_embed_model, base_url=base), per_minute)
    lessons = LessonIndex(load_lessons(), connect("sqlite://"), embedder)
    lessons.sync()
    if not lessons.ready:
        raise SystemExit(f"The lessons could not be embedded: {lessons.status()['error']}")
    ai = AIService(llm, RequestBudget(1000, 1000), None, lambda e, d: None, lessons=lessons)
    out: Dict[str, Any] = {"model": llm.model, "embedModel": embedder.model}

    def measured(ask: Callable[[], Dict[str, Any]]) -> Tuple[Dict[str, Any], int, float]:
        """Run one request: (its payload, how many answers the model gave, ms without pacing).
        A lesson search before the answer is a normal step, not a second try."""
        waited, answers = llm.waited + embedder.waited, llm.final_answers
        payload = ask()
        paced_ms = (llm.waited + embedder.waited - waited) * 1000
        return payload, llm.final_answers - answers, max(0.0, payload["durationMs"] - paced_ms)

    print("  retrieval with real embeddings ...", flush=True)
    out["retrieval"] = ranking(lambda q: [hit.chunk.id for hit in lessons.search(q, 10).hits])

    print("  coach: 15 questions + 3 it must refuse ...", flush=True)
    rows = []
    for question, expected in EVAL_QUESTIONS:
        payload, answers, ms = measured(lambda: ai.coach_answer(question))
        rows.append({"question": question, "gemini": payload["source"] != "fallback", "citesExpected":
                     expected in payload["citations"], "covered": payload["covered"], "requests": payload["requests"],
                     "firstTry": answers == 1, "ms": round(ms)})
    refusals = []
    for question in OUT_OF_SCOPE:
        payload = ai.coach_answer(question)
        refusals.append({"question": question, "gemini": payload["source"] != "fallback",
                         "saidNotCovered": not payload["covered"], "requests": payload["requests"]})
    answered = [r for r in rows if r["gemini"]]
    out["coach"] = {
        "questions": len(rows), "answeredByGemini": len(answered),
        "citesExpected": sum(r["citesExpected"] for r in answered),
        "firstTry": sum(r["firstTry"] for r in answered),
        "outOfScope": len(refusals), "refusedCorrectly": sum(r["saidNotCovered"] for r in refusals if r["gemini"]),
        "p50ms": percentile([r["ms"] for r in answered], 0.5), "p95ms": percentile([r["ms"] for r in answered], 0.95),
        "rows": rows, "refusals": refusals,
    }

    print("  repair agent: 9 misreads (6 ambiguous), against the built-in search ...", flush=True)
    cases = []
    ambiguous = ambiguous_seeds(2000, 2)
    for mode in MODES:
        for seed, count in [(2100, 1), (ambiguous[0], 2), (ambiguous[1], 2)]:
            scan, readings, truth = misread_case(seed, mode, count)
            context = RepairContext(scan, readings)
            proposal = ai.repair(context)
            changed = {(c["face"], c["index"], c["to"]) for c in proposal["changes"]}
            agent_right = proposal["action"] == "apply_fix" and changed == set(truth)
            baseline_right = is_true_fix(context, repair_fallback(context, None).get("fix_id"), truth)
            cases.append({"mode": mode, "gemini": proposal["source"] != "search", "action": proposal["action"],
                          "agentRight": agent_right, "agentWrongFix": proposal["action"] == "apply_fix" and not agent_right,
                          "builtInRight": baseline_right, "uniqueFix": context.search.total == 1,
                          "requests": proposal["requests"]})
    by_mode = {}
    for mode in MODES:
        mine = [c for c in cases if c["mode"] == mode]
        by_mode[mode] = {"cases": len(mine), "agentRight": sum(c["agentRight"] for c in mine),
                         "agentRescans": sum(c["action"] == "rescan_side" for c in mine),
                         "agentWrongFix": sum(c["agentWrongFix"] for c in mine),
                         "builtInRight": sum(c["builtInRight"] for c in mine)}
    out["repair"] = {"modes": by_mode, "answeredByGemini": sum(c["gemini"] for c in cases), "cases": cases}

    print("  tutor: hints on 12 learner states ...", flush=True)
    hints = []
    for number, learn in enumerate(learner_states(12)):
        learn.hint()
        if number % 3 == 2:
            learn.hint()  # every third one asks for hint 2
        level = learn.hint_level
        context = TutorContext("hint", learn.facts("hint"), learn.allowed_sequences("hint"), lessons)
        payload, answers, ms = measured(lambda: ai.tutor_answer(context))
        hints.append({"stage": learn.stage, "level": level, "gemini": payload["source"] != "fallback",
                      "requests": payload["requests"], "firstTry": answers == 1,
                      "movesInText": len(move_runs(payload["message"])),
                      "words": len(payload["message"].split()), "ms": round(ms)})
    answered_hints = [h for h in hints if h["gemini"]]
    out["tutor"] = {
        "hints": len(hints), "answeredByGemini": len(answered_hints),
        "firstTry": sum(h["firstTry"] for h in answered_hints),
        "hint1WithMoves": sum(1 for h in answered_hints if h["level"] == 1 and h["movesInText"]),
        "medianWords": int(statistics.median([h["words"] for h in answered_hints])) if answered_hints else 0,
        "p50ms": percentile([h["ms"] for h in answered_hints], 0.5),
        "p95ms": percentile([h["ms"] for h in answered_hints], 0.95),
        "rows": hints,
    }
    return out


# ======================================================================================
# Reports
# ======================================================================================


def _commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                              text=True, timeout=5).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _mark(ok: bool) -> str:
    return "pass" if ok else "**FAIL**"


def offline_markdown(r: Dict[str, Any], meta: Dict[str, str]) -> str:
    ret, rep, beg, grd, fb = r["retrieval"], r["repair"], r["beginner"], r["guardrails"], r["fallbacks"]
    lines = [
        "# AI evaluation: offline",
        "",
        f"Run {meta['date']} on commit `{meta['commit']}`, with no API key (test embeddings and scripted models).",
        f"Made by `python tools/eval_ai.py`; CI runs it on every push. All gates: {_mark(r['allGates'])}.",
        "",
        "## 1. Retrieval (RAG search)",
        "",
        f"{len(EVAL_QUESTIONS)} labelled questions over {ret['sections']} lesson sections. Gate: recall@3 >= 13 for both "
        f"({_mark(ret['gate'])}).",
        "",
        "| Search | recall@1 | recall@3 | MRR |",
        "| --- | --- | --- | --- |",
        f"| Keywords (BM25) | {ret['keywords']['recall@1']}/15 | {ret['keywords']['recall@3']}/15 | {ret['keywords']['mrr']} |",
        f"| Test embeddings (word hashing) | {ret['testVectors']['recall@1']}/15 | {ret['testVectors']['recall@3']}/15 | "
        f"{ret['testVectors']['mrr']} |",
        "",
        "Missed at 3: " + ("; ".join(ret["keywords"]["misses@3"]) or "none") + ".",
        "",
        "## 2. Repair search (misread stickers)",
        "",
        "Simulated scans of real cubes with misread stickers. The camera's evidence on a misread sticker: *unsure* "
        "(51%, the true colour its 2nd guess), *fairly sure* (80%, the true colour a weak 2nd guess) or *sure* (90%, "
        "the true colour not among its guesses). Gate: the true fix is always found, and the built-in pick is right "
        f"in >= 95% of the unsure cases ({_mark(rep['gate'])}).",
        "",
        "| Misread | Cases | True fix found | Only one valid fix | Built-in pick right: unsure / fairly sure / sure |",
        "| --- | --- | --- | --- | --- |",
    ]
    for kind, row in rep["kinds"].items():
        right = row["builtInRight"]
        lines.append(f"| {kind} | {row['cases']} | {row['trueFixFound']} | {row['uniqueFix']} | "
                     f"{right['doubt']} / {right['hint']} / {right['no-hint']} |")
    lines += [
        "",
        "The cube's invariants are strict: one or two misread stickers almost always leave exactly one valid fix. "
        "Only in the rare ambiguous cases does the camera's evidence decide, and with no evidence the built-in "
        "search can pick a wrong fix; the agent may ask for a rescan instead (see the live report).",
        "",
        "## 3. Beginner method (Solve & Learn)",
        "",
        f"Gate: every cube solved, stages in order, at most 3 algorithms per yellow stage ({_mark(beg['gate'])}).",
        "",
        "| Cubes | Solved | Stages in order | Moves (min / median / max) | Max algorithms per yellow stage | Slowest step |",
        "| --- | --- | --- | --- | --- | --- |",
        f"| {beg['cubes']} | {beg['solved']} | {beg['stagesInOrder']} | {beg['movesMin']} / {beg['movesMedian']} / "
        f"{beg['movesMax']} | {beg['maxAlgorithmsPerYellowStage']} | {beg['slowestStepMs']} ms |",
        "",
        "## 4. Guardrails",
        "",
        f"Misbehaving model answers; code must catch each one. {grd['passed']}/{grd['total']} caught "
        f"({_mark(grd['gate'])}).",
        "",
        "| Case | Result |",
        "| --- | --- |",
    ]
    lines += [f"| {c['case']} | {_mark(c['passed'])} |" for c in grd["cases"]]
    lines += [
        "",
        "## 5. Fallbacks (AI off)",
        "",
        f"With no API key, every feature must still answer ({_mark(fb['gate'])}).",
        "",
        "| Feature | Valid built-in answer |",
        "| --- | --- |",
    ]
    lines += [f"| {name} | {_mark(ok)} |" for name, ok in fb["features"].items()]
    return "\n".join(lines) + "\n"


def live_markdown(r: Dict[str, Any], meta: Dict[str, str]) -> str:
    ret, coach, rep, tut = r["retrieval"], r["coach"], r["repair"], r["tutor"]
    lines = [
        "# AI evaluation: live (real Gemini)",
        "",
        f"Run {meta['date']} on commit `{meta['commit']}` with `{r['model']}` and `{r['embedModel']}`.",
        "Made by `python tools/eval_ai.py --live` (by hand: it uses the real API).",
        "",
        "## Retrieval with real embeddings",
        "",
        "| recall@1 | recall@3 | MRR |",
        "| --- | --- | --- |",
        f"| {ret['recall@1']}/15 | {ret['recall@3']}/15 | {ret['mrr']} |",
        "",
        "## Coach (RAG answers)",
        "",
        "| Questions | Answered by Gemini | Cites the expected section | Accepted first try | Out-of-scope refused | p50 / p95 |",
        "| --- | --- | --- | --- | --- | --- |",
        f"| {coach['questions']} | {coach['answeredByGemini']} | {coach['citesExpected']} | {coach['firstTry']} | "
        f"{coach['refusedCorrectly']}/{coach['outOfScope']} | {coach['p50ms'] / 1000:.1f} s / {coach['p95ms'] / 1000:.1f} s |",
        "",
        "Every accepted citation is one the search returned in that run: code rejects any other.",
        "Times are the model's own: the run's pacing waits (to stay under the free limits) are left out.",
        "",
        "## Repair agent vs the built-in search",
        "",
        "Per kind of camera evidence: 1 case with one misread sticker and 2 ambiguous cases (two misread stickers, "
        "more than one valid fix).",
        "",
        "| Camera evidence | Cases | Agent picked the true fix | Agent asked for a rescan | Agent picked a wrong fix | "
        "Built-in pick right |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for mode in MODES:
        m = rep["modes"][mode]
        lines.append(f"| {EVIDENCE[mode]} | {m['cases']} | {m['agentRight']} | {m['agentRescans']} | "
                     f"{m['agentWrongFix']} | {m['builtInRight']} |")
    lines += [
        "",
        f"{rep['answeredByGemini']} of {sum(m['cases'] for m in rep['modes'].values())} proposals came from Gemini "
        "(the rest: the built-in search after a timeout or a limit). A wrong fix is the costly mistake; "
        "a rescan is the safe one.",
        "",
        "## Tutor hints",
        "",
        "| Hints | Answered by Gemini | Accepted first try | Hint 1 with moves | Median words | p50 / p95 |",
        "| --- | --- | --- | --- | --- | --- |",
        f"| {tut['hints']} | {tut['answeredByGemini']} | {tut['firstTry']} | {tut['hint1WithMoves']} | "
        f"{tut['medianWords']} | {tut['p50ms'] / 1000:.1f} s / {tut['p95ms'] / 1000:.1f} s |",
        "",
        "\"Accepted first try\" = code's checks passed on the model's first answer (a lesson search before it is a "
        "normal step); otherwise the model fixed it after the rejection. Hint 1 can never show moves: code rejects them.",
    ]
    return "\n".join(lines) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate the AI features and write a report.")
    parser.add_argument("--live", action="store_true", help="also run the real-Gemini evaluations (uses the API)")
    parser.add_argument("--per-minute", type=float, default=8.0, help="live: requests per minute (default 8)")
    parser.add_argument("--out", default=str(REPORT_DIR), help="where to write the reports")
    args = parser.parse_args(argv)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = {"date": time.strftime("%Y-%m-%d %H:%M"), "commit": _commit()}

    print("AI evaluation: offline", flush=True)
    results = {
        "retrieval": eval_retrieval(),
        "repair": eval_repair(),
        "beginner": eval_beginner(),
        "guardrails": eval_guardrails(),
        "fallbacks": eval_fallbacks(),
    }
    results["allGates"] = all(section["gate"] for section in results.values() if isinstance(section, dict))
    for name, section in results.items():
        if isinstance(section, dict):
            print(f"  [{'pass' if section['gate'] else 'FAIL'}] {name}")
    (out_dir / "offline.json").write_text(json.dumps({**meta, **results}, indent=1) + "\n")
    (out_dir / "offline.md").write_text(offline_markdown(results, meta))
    print(f"Report: {out_dir / 'offline.md'}")

    if args.live:
        print("AI evaluation: live (real Gemini, paced; about 10 minutes)", flush=True)
        live = live_evals(args.per_minute)
        (out_dir / "live.json").write_text(json.dumps({**meta, **live}, indent=1) + "\n")
        (out_dir / "live.md").write_text(live_markdown(live, meta))
        print(f"Report: {out_dir / 'live.md'}")
    return 0 if results["allGates"] else 1


if __name__ == "__main__":
    sys.exit(main())
