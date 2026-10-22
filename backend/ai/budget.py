"""A request budget: how many model requests the app may send per minute and per day.

The live site is public, and Gemini's free tier has per-minute and per-day limits.
The app stops itself well before Google says no, and answers with its built-in
fallback instead. "Per day" is a sliding 24-hour window.

The counts live in memory. After a restart they are refilled from the trace table
(every model request is traced), so a redeploy doesn't reset the daily count.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable, Deque, Dict, Iterable, List, Optional

from backend.ai.llm import Embedder, LLMBudgetExceeded, LLMClient, LLMRequest, LLMResponse

MINUTE = 60.0
DAY = 24 * 60 * 60.0


class RequestBudget:
    """Counts requests in the last minute and the last 24 hours."""

    def __init__(self, per_minute: int, per_day: int, clock: Callable[[], float] = time.time) -> None:
        self.per_minute = per_minute
        self.per_day = per_day
        self._clock = clock
        self._lock = threading.Lock()
        self._times: Deque[float] = deque()  # one timestamp per request, oldest first

    def seed(self, times: Iterable[float]) -> None:
        """Add requests made before a restart (Unix times)."""
        with self._lock:
            self._times.extend(sorted(times))
            self._forget_old(self._clock())

    def try_acquire(self) -> Optional[str]:
        """Count one request now, or say why not (None = allowed)."""
        with self._lock:
            now = self._clock()
            self._forget_old(now)
            if len(self._times) >= self.per_day:
                return f"the app's daily limit of {self.per_day} AI requests is used up"
            if sum(1 for t in self._times if t > now - MINUTE) >= self.per_minute:
                return f"the app's limit of {self.per_minute} AI requests per minute is reached"
            self._times.append(now)
            return None

    def status(self) -> Dict[str, int]:
        with self._lock:
            now = self._clock()
            self._forget_old(now)
            return {
                "usedLastMinute": sum(1 for t in self._times if t > now - MINUTE),
                "perMinute": self.per_minute,
                "usedToday": len(self._times),
                "perDay": self.per_day,
            }

    def _forget_old(self, now: float) -> None:
        while self._times and self._times[0] <= now - DAY:
            self._times.popleft()


class BudgetedLLM:
    """Wraps an ``LLMClient``: every request must fit in the budget first."""

    def __init__(self, llm: LLMClient, budget: RequestBudget) -> None:
        self._llm = llm
        self._budget = budget
        self.provider = llm.provider
        self.model = llm.model

    def generate(self, request: LLMRequest) -> LLMResponse:
        refusal = self._budget.try_acquire()
        if refusal is not None:
            raise LLMBudgetExceeded(refusal)
        return self._llm.generate(request)


class BudgetedEmbedder:
    """Wraps an ``Embedder`` the same way: one embedding request = one request of the budget."""

    def __init__(self, embedder: Embedder, budget: RequestBudget) -> None:
        self._embedder = embedder
        self._budget = budget
        self.model = embedder.model

    def embed(self, texts: List[str], task: str) -> List[List[float]]:
        refusal = self._budget.try_acquire()
        if refusal is not None:
            raise LLMBudgetExceeded(refusal)
        return self._embedder.embed(texts, task)
