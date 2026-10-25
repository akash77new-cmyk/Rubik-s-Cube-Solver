"""Tracing: a record of everything one AI run did, saved in the database.

AI rule 6: every step is traced. A trace answers "why did the assistant say that?":
which tools the model asked for, with which arguments, what each tool returned,
how long each step took and how many tokens it used, and whether the answer came
from the model or from the built-in fallback.

``Trace`` collects the steps of one run in memory. ``TraceStore`` saves finished
traces (tables ``ai_runs`` and ``ai_steps``), keeps only the newest 200 runs, and
reads them back for the AI page. Each run records its ``owner`` (Phase 9), and the AI
page of one visitor lists only that visitor's runs: questions are private.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import delete, select

from backend.ai.llm import LLMResponse, ToolCall
from backend.db.database import Database
from backend.db.models import AIRunRow, AIStepRow


class Trace:
    """The steps of one AI run, in order."""

    def __init__(
        self, run_id: str, feature: str, question: str, clock: Callable[[], float] = time.time,
        owner: Optional[str] = None,
    ) -> None:
        self.run_id = run_id
        self.feature = feature
        self.question = question
        self.owner = owner  # "u:<id>", "g:<id>" or "local" (Phase 9)
        self._clock = clock
        self.started_at = clock()
        self.steps: List[Dict[str, Any]] = []
        self.request_count = 0
        self.input_tokens = 0
        self.output_tokens = 0
        # Filled by finish():
        self.source = ""
        self.reason: Optional[str] = None
        self.model: Optional[str] = None
        self.answer: Optional[Dict[str, Any]] = None
        self.duration_ms = 0

    def _add(self, kind: str, name: str, detail: Dict[str, Any], duration_ms: float) -> None:
        self.steps.append(
            {
                "position": len(self.steps) + 1,
                "kind": kind,
                "name": name,
                "detail": detail,
                "durationMs": int(round(duration_ms)),
                "at": self._clock(),
            }
        )

    def model_step(self, response: LLMResponse, duration_ms: float) -> None:
        """One request to the model, and what it asked for."""
        self.request_count += 1
        self.input_tokens += response.usage.input_tokens
        self.output_tokens += response.usage.output_tokens + response.usage.thinking_tokens
        self._add(
            "model",
            response.model or "model",
            {
                "toolCalls": [{"name": c.name, "args": c.args} for c in response.tool_calls],
                "text": response.text[:500],
                "finishReason": response.finish_reason,
                "inputTokens": response.usage.input_tokens,
                "outputTokens": response.usage.output_tokens,
                "thinkingTokens": response.usage.thinking_tokens,
            },
            duration_ms,
        )

    def tool_step(self, call: ToolCall, result: Dict[str, Any], duration_ms: float) -> None:
        """One tool the app ran for the model, with its arguments and result."""
        self._add("tool", call.name, {"args": call.args, "result": result}, duration_ms)

    def answer_step(self, answer: Dict[str, Any]) -> None:
        self._add("answer", "final_answer", {"answer": answer}, 0)

    def error_step(self, name: str, message: str) -> None:
        self._add("error", name, {"message": message}, 0)

    def finish(self, source: str, answer: Dict[str, Any], model: Optional[str], reason: Optional[str]) -> None:
        self.source = source  # "gemini" (or another provider) or "fallback"
        self.answer = answer
        self.model = model
        self.reason = reason
        self.duration_ms = int(round((self._clock() - self.started_at) * 1000))

    def summary(self) -> Dict[str, Any]:
        """Counts for the UI and the Logs page."""
        return {
            "requests": self.request_count,
            "inputTokens": self.input_tokens,
            "outputTokens": self.output_tokens,
            "toolCalls": sum(1 for step in self.steps if step["kind"] == "tool"),
            "durationMs": self.duration_ms,
        }


def _utc(seconds: float) -> datetime:
    return datetime.fromtimestamp(seconds, tz=timezone.utc)


class TraceStore:
    """Finished traces in the database."""

    def __init__(self, database: Database, max_runs: int = 200) -> None:
        self._db = database
        self.max_runs = max_runs

    def save(self, trace: Trace) -> None:
        """Save one run and its steps, then delete the oldest runs beyond ``max_runs``."""
        with self._db.transaction("save the AI trace") as session:
            session.add(
                AIRunRow(
                    id=trace.run_id,
                    feature=trace.feature,
                    question=trace.question,
                    source=trace.source,
                    reason=trace.reason,
                    model=trace.model,
                    answer=trace.answer,
                    request_count=trace.request_count,
                    input_tokens=trace.input_tokens,
                    output_tokens=trace.output_tokens,
                    started_at=_utc(trace.started_at),
                    duration_ms=trace.duration_ms,
                    owner=trace.owner,
                )
            )
            for step in trace.steps:
                session.add(
                    AIStepRow(
                        run_id=trace.run_id,
                        position=step["position"],
                        kind=step["kind"],
                        name=step["name"][:64],
                        detail=step["detail"],
                        duration_ms=step["durationMs"],
                        created_at=_utc(step["at"]),
                    )
                )
            session.flush()
            old = session.scalars(
                select(AIRunRow.id)
                .order_by(AIRunRow.started_at.desc(), AIRunRow.id.desc())
                .offset(self.max_runs)
            ).all()
            if old:
                session.execute(delete(AIStepRow).where(AIStepRow.run_id.in_(old)))
                session.execute(delete(AIRunRow).where(AIRunRow.id.in_(old)))

    def recent(self, limit: int = 20, owner: Optional[str] = None) -> List[Dict[str, Any]]:
        """The newest runs with their steps, newest first, ready for the UI.

        With ``owner``, only that visitor's runs (the AI page); without, everyone's (tools)."""
        query = select(AIRunRow)
        if owner is not None:
            query = query.where(AIRunRow.owner == owner)
        with self._db.transaction("load AI traces") as session:
            runs = session.scalars(
                query.order_by(AIRunRow.started_at.desc(), AIRunRow.id.desc()).limit(limit)
            ).all()
            ids = [run.id for run in runs]
            steps = session.scalars(
                select(AIStepRow).where(AIStepRow.run_id.in_(ids)).order_by(AIStepRow.position)
            ).all() if ids else []
            by_run: Dict[str, List[Dict[str, Any]]] = {run_id: [] for run_id in ids}
            for step in steps:
                by_run[step.run_id].append(
                    {
                        "position": step.position,
                        "kind": step.kind,
                        "name": step.name,
                        "detail": step.detail,
                        "durationMs": step.duration_ms,
                    }
                )
            return [
                {
                    "id": run.id,
                    "feature": run.feature,
                    "question": run.question,
                    "source": run.source,
                    "reason": run.reason,
                    "model": run.model,
                    "answer": run.answer,
                    "requestCount": run.request_count,
                    "inputTokens": run.input_tokens,
                    "outputTokens": run.output_tokens,
                    "startedAt": run.started_at.timestamp(),
                    "durationMs": run.duration_ms,
                    "steps": by_run[run.id],
                }
                for run in runs
            ]

    def request_times(self, since: float) -> List[float]:
        """When model requests were made since ``since`` (Unix time), to refill the budget."""
        with self._db.transaction("load AI request times") as session:
            rows = session.scalars(
                select(AIStepRow.created_at).where(AIStepRow.kind == "model", AIStepRow.created_at >= _utc(since))
            ).all()
            return [row.timestamp() for row in rows]
