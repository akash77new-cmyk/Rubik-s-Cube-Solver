"""The AI service: runs AI features in the background, with a budget, tracing and a fallback.

The engine creates one ``AIService`` and hands it to the session. Two features use it:

- **The Cube Assistant.** When the user asks a question, the session calls ``ask()``,
  which returns at once. The answer is worked out in a background thread - never on
  the camera thread (AI rule 9), and the engine keeps handling other commands
  meanwhile - then published as an ``ai:answer`` event.
- **The Smart Repair Agent** (Phase 5). After an unsolvable scan, the session calls
  ``repair_async()``; the proposal comes back through a callback.

Every run is traced and saved, whether the answer came from the model or from the
built-in fallback. Both features share one request budget.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from backend.ai import repair_agent
from backend.ai.agent import AgentStopped, AgentTask, run_agent
from backend.ai.assistant import ANSWER_SCHEMA, SYSTEM_PROMPT, TOOL_NAMES, SnapshotContext, build_tools, fallback_answer
from backend.ai.budget import DAY, BudgetedLLM, RequestBudget
from backend.ai.gemini import DEFAULT_BASE_URL, GeminiClient
from backend.ai.llm import LLMBudgetExceeded, LLMClient, LLMError
from backend.ai.repair_agent import RepairContext
from backend.ai.tracing import Trace, TraceStore
from backend.db.database import StorageError

log = logging.getLogger(__name__)

#: Why the fallback was used, in plain English, by error reason code.
REASON_TEXT = {
    "rate_limited": "Gemini's free limit is used up for now",
    "auth": "Gemini rejected the API key",
    "bad_request": "Gemini refused the request",
    "unavailable": "Gemini can't be reached right now",
    "bad_response": "Gemini sent an unusable answer",
    "step_limit": "the AI didn't reach an answer in time",
    "time_limit": "the AI didn't reach an answer in time",
}

Publish = Callable[[str, Any], None]

#: The Smart Repair Agent's time limit. A repair needs two Gemini requests, and on
#: Render one request can take up to ~30 s (a 25 s timeout, then the retry), so a
#: 30 s limit sometimes stopped the agent before its answer (seen at the Phase 5 go-live).
REPAIR_DEADLINE_SECONDS = 60.0


@dataclass(frozen=True)
class AIConfig:
    """AI settings. The engine fills them from environment variables (backend/config.py)."""

    api_key: str = field(default="", repr=False)  # "" = AI off
    model: str = ""
    base_url: str = ""  # "" = Google's
    thinking_level: str = ""  # "" = the model's default
    requests_per_minute: int = 10
    requests_per_day: int = 200


class AIService:
    """Runs AI features for the session. One question at a time."""

    MAX_QUESTION_LENGTH = 300

    def __init__(
        self,
        llm: Optional[LLMClient],
        budget: RequestBudget,
        store: Optional[TraceStore],
        publish: Publish,
        logs: Any = None,
        off_reason: str = "",
    ) -> None:
        self._llm = llm  # None = AI is off: every answer is the built-in one
        self._budget = budget
        self._store = store
        self._publish = publish
        self._logs = logs  # the Logs page (LogBus); optional
        self._off_reason = off_reason
        self._lock = threading.Lock()
        self._busy = False
        self._last_error: Optional[str] = None

    @classmethod
    def create(cls, config: AIConfig, store: Optional[TraceStore], publish: Publish, logs: Any = None) -> "AIService":
        """Build the service the engine uses: Gemini if there is a key, else AI off."""
        budget = RequestBudget(config.requests_per_minute, config.requests_per_day)
        if store is not None:
            try:  # requests made before a restart still count towards today's limit
                budget.seed(store.request_times(time.time() - DAY))
            except StorageError as exc:
                log.warning("Could not read earlier AI requests: %s", exc)
        llm: Optional[LLMClient] = None
        off_reason = ""
        if config.api_key:
            llm = GeminiClient(
                config.api_key, config.model, config.base_url or DEFAULT_BASE_URL, config.thinking_level
            )
        else:
            off_reason = "no Gemini API key is set"
        return cls(llm, budget, store, publish, logs, off_reason)

    # ------------------------------------------------------------------
    def status(self) -> Dict[str, Any]:
        """For the AI page and every state snapshot (no I/O)."""
        with self._lock:
            busy, last_error = self._busy, self._last_error
        return {
            "enabled": self._llm is not None,
            "provider": self._llm.provider if self._llm else None,
            "model": self._llm.model if self._llm else None,
            "offReason": self._off_reason or None,
            "busy": busy,
            "budget": self._budget.status(),
            "lastError": last_error,
        }

    def ask(self, question: str, context: SnapshotContext) -> Dict[str, Any]:
        """Start answering in the background. Returns at once with a run id, or an error."""
        question = " ".join(str(question or "").split())
        if not question:
            return {"ok": False, "error": "Type a question first."}
        if len(question) > self.MAX_QUESTION_LENGTH:
            return {"ok": False, "error": f"Keep questions under {self.MAX_QUESTION_LENGTH} characters."}
        with self._lock:
            if self._busy:
                return {"ok": False, "error": "The assistant is still answering the last question."}
            self._busy = True
        run_id = uuid.uuid4().hex[:12]
        self._publish("ai:status", self.status())
        threading.Thread(
            target=self._worker, args=(run_id, question, context), name="ai-assistant", daemon=True
        ).start()
        return {"ok": True, "runId": run_id}

    def _worker(self, run_id: str, question: str, context: SnapshotContext) -> None:
        try:
            self.answer(question, context, run_id)
        except Exception as exc:  # a bug must not leave the UI waiting forever
            log.exception("The assistant failed")
            self._publish("ai:answer", {"runId": run_id, "question": question, "error": str(exc)})
        finally:
            with self._lock:
                self._busy = False
            self._publish("ai:status", self.status())

    def answer(self, question: str, context: SnapshotContext, run_id: Optional[str] = None) -> Dict[str, Any]:
        """Answer one question now (the background thread calls this; so do tests)."""
        run_id = run_id or uuid.uuid4().hex[:12]
        trace = Trace(run_id, "assistant", question)
        self._publish("ai:progress", {"runId": run_id, "step": 0, "tool": None})
        source, model, reason = "fallback", None, None
        try:
            if self._llm is None:
                reason = self._off_reason
                trace.error_step("ai_off", reason)
                answer = fallback_answer(context, reason)
            else:
                task = AgentTask(SYSTEM_PROMPT, question, build_tools(context), TOOL_NAMES, ANSWER_SCHEMA)
                answer = run_agent(
                    BudgetedLLM(self._llm, self._budget),
                    task,
                    trace,
                    on_progress=lambda step, tool: self._publish(
                        "ai:progress", {"runId": run_id, "step": step, "tool": tool}
                    ),
                )
                source, model = self._llm.provider, self._llm.model
                with self._lock:
                    self._last_error = None
        except (LLMError, AgentStopped) as exc:
            reason = self._reason_text(exc)
            trace.error_step(getattr(exc, "reason", "error"), str(exc))
            with self._lock:
                self._last_error = str(exc)
            answer = fallback_answer(context, reason)

        trace.finish(source, answer, model, reason)
        if self._store is not None:
            try:
                self._store.save(trace)
            except StorageError as exc:  # the answer still reaches the user
                log.warning("AI trace not saved: %s", exc)

        payload = {
            "runId": run_id,
            "question": question,
            "answer": answer["answer"],
            "suggestions": answer.get("suggestions", []),
            "source": source,
            "model": model,
            "reason": reason,
            **trace.summary(),
        }
        self._publish("ai:answer", payload)
        self._log(payload)
        return payload

    # ------------------------------------------------------------------
    # The Smart Repair Agent (Phase 5)
    # ------------------------------------------------------------------
    def repair(self, context: RepairContext, run_id: Optional[str] = None) -> Dict[str, Any]:
        """Find a fix for an unsolvable cube now (repair_async's thread calls this; so do tests)."""
        run_id = run_id or uuid.uuid4().hex[:12]
        trace = Trace(run_id, "repair", context.question()[:300])
        source, model, reason = "search", None, None
        try:
            if self._llm is None:
                reason = self._off_reason
                trace.error_step("ai_off", reason)
                answer = repair_agent.fallback_answer(context, reason)
            else:
                task = AgentTask(
                    repair_agent.SYSTEM_PROMPT,
                    context.question(),
                    repair_agent.build_tools(context),
                    repair_agent.TOOL_NAMES,
                    repair_agent.ANSWER_SCHEMA,
                    max_steps=4,
                    deadline_seconds=REPAIR_DEADLINE_SECONDS,
                    answer_check=context.check_answer,
                )
                answer = run_agent(BudgetedLLM(self._llm, self._budget), task, trace)
                source, model = self._llm.provider, self._llm.model
        except (LLMError, AgentStopped) as exc:
            reason = self._reason_text(exc)
            trace.error_step(getattr(exc, "reason", "error"), str(exc))
            with self._lock:
                self._last_error = str(exc)
            answer = repair_agent.fallback_answer(context, reason)

        trace.finish(source, answer, model, reason)
        if self._store is not None:
            try:
                self._store.save(trace)
            except StorageError as exc:
                log.warning("AI trace not saved: %s", exc)
        proposal = {"runId": run_id, **context.proposal(answer, source, model, reason), **trace.summary()}
        if self._logs is not None:
            how = f"{model}" if source != "search" else "the built-in search"
            self._logs.info(f"Repair proposal from {how}: {answer['message']}", source="ai")
        return proposal

    def repair_async(self, context: RepairContext, done: Callable[[Dict[str, Any]], None]) -> None:
        """Run repair() in a background thread and hand the proposal to ``done``."""

        def worker() -> None:
            try:
                proposal = self.repair(context)
            except Exception:  # a bug must not leave the repair card spinning forever
                log.exception("The repair agent failed")
                answer = repair_agent.fallback_answer(context, "something went wrong")
                proposal = context.proposal(answer, "search", None, "something went wrong")
            done(proposal)

        threading.Thread(target=worker, name="ai-repair", daemon=True).start()

    def recent_traces(self, limit: int = 20) -> List[Dict[str, Any]]:
        """The newest traces with their steps (reads the database)."""
        if self._store is None:
            return []
        return self._store.recent(max(1, min(int(limit), 50)))

    # ------------------------------------------------------------------
    @staticmethod
    def _reason_text(exc: Exception) -> str:
        if isinstance(exc, LLMBudgetExceeded):
            return str(exc)  # already plain English
        return REASON_TEXT.get(getattr(exc, "reason", ""), "something went wrong")

    def _log(self, payload: Dict[str, Any]) -> None:
        if self._logs is None:
            return
        seconds = payload["durationMs"] / 1000
        if payload["source"] == "fallback":
            self._logs.warn(f"Assistant gave the built-in answer: {payload['reason']}", source="ai")
        else:
            self._logs.success(
                f"Assistant answered with {payload['model']} in {seconds:.1f} s "
                f"({payload['toolCalls']} tool calls, {payload['requests']} requests)",
                source="ai",
            )
