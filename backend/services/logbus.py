"""Structured, in-memory log bus that feeds the Logs page.

Entries are kept in a bounded ring buffer so a long session cannot grow without
limit, and pushed to listeners as they happen so the UI streams rather than
polls. Every entry carries a source ("camera", "solver", "scan", ...) and a
level, which is what the UI colour-codes on.
"""

from __future__ import annotations

import itertools
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Deque, Dict, List, Optional

LEVELS = ("debug", "info", "success", "warn", "error")


@dataclass(frozen=True)
class LogEntry:
    id: int
    timestamp: float
    level: str
    source: str
    message: str
    detail: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "level": self.level,
            "source": self.source,
            "message": self.message,
            "detail": self.detail,
        }


class LogBus:
    """Bounded ring buffer plus fan-out to live listeners."""

    def __init__(self, capacity: int = 500) -> None:
        self._entries: Deque[LogEntry] = deque(maxlen=capacity)
        self._lock = threading.RLock()
        self._counter = itertools.count(1)
        self._listeners: List[Callable[[LogEntry], None]] = []

    # ------------------------------------------------------------------
    def add_listener(self, listener: Callable[[LogEntry], None]) -> None:
        self._listeners.append(listener)

    def emit(
        self,
        message: str,
        level: str = "info",
        source: str = "app",
        detail: Optional[Dict[str, Any]] = None,
    ) -> LogEntry:
        entry = LogEntry(
            id=next(self._counter),
            timestamp=time.time(),
            level=level if level in LEVELS else "info",
            source=source,
            message=message,
            detail=detail,
        )
        with self._lock:
            self._entries.append(entry)
        for listener in list(self._listeners):
            try:
                listener(entry)
            except Exception:  # pragma: no cover - never let the UI break logging
                pass
        return entry

    # Convenience level helpers ----------------------------------------
    def debug(self, message: str, source: str = "app", **detail: Any) -> LogEntry:
        return self.emit(message, "debug", source, detail or None)

    def info(self, message: str, source: str = "app", **detail: Any) -> LogEntry:
        return self.emit(message, "info", source, detail or None)

    def success(self, message: str, source: str = "app", **detail: Any) -> LogEntry:
        return self.emit(message, "success", source, detail or None)

    def warn(self, message: str, source: str = "app", **detail: Any) -> LogEntry:
        return self.emit(message, "warn", source, detail or None)

    def error(self, message: str, source: str = "app", **detail: Any) -> LogEntry:
        return self.emit(message, "error", source, detail or None)

    # ------------------------------------------------------------------
    def history(self, limit: int = 200) -> List[Dict[str, Any]]:
        with self._lock:
            entries = list(self._entries)[-limit:]
        return [entry.to_dict() for entry in entries]

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


log_bus = LogBus()
