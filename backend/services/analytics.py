"""Solve history and aggregate statistics for the analytics dashboard.

History is stored in the database (table ``solves``). Like settings, it is read
from memory and written to the database first: ``summary()`` runs for every state
snapshot, so it must never wait for the network.
"""

from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from typing import Any, Dict, List

from sqlalchemy import delete, select

from backend.core.moves import FACES
from backend.db.database import Database
from backend.db.models import SolveRow


@dataclass
class SolveRecord:
    """One completed solve (one row of the ``solves`` table)."""

    id: str
    started_at: float
    finished_at: float
    move_count: int
    quarter_turns: int
    solve_ms: float
    scan_seconds: float
    execution_seconds: float
    backend: str
    notation: str
    face_distribution: Dict[str, int] = field(default_factory=dict)
    turn_distribution: Dict[str, int] = field(default_factory=dict)
    detection_confidence: float = 0.0
    source: str = "scan"  # scan | scramble | manual

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


#: SolveRecord keeps times as Unix seconds (what the UI uses); the table stores
#: real timestamps, so the history is readable in any SQL tool.
_TIME_FIELDS = ("started_at", "finished_at")


def row_from_record(record: SolveRecord) -> SolveRow:
    values = asdict(record)
    for name in _TIME_FIELDS:
        values[name] = datetime.fromtimestamp(values[name], tz=timezone.utc)
    return SolveRow(**values)


def record_from_row(row: SolveRow) -> SolveRecord:
    values = {f.name: getattr(row, f.name) for f in fields(SolveRecord)}
    for name in _TIME_FIELDS:
        values[name] = values[name].timestamp()
    return SolveRecord(**values)


class AnalyticsStore:
    """Solve history (memory + database) with derived session/lifetime statistics."""

    def __init__(self, database: Database) -> None:
        self._db = database
        self._lock = threading.RLock()       # guards the memory copy
        self._write_lock = threading.Lock()  # one database write at a time
        self._records: List[SolveRecord] = self._load()
        self._session_started = time.time()
        self._session_ids: set[str] = set()
        self._detection_samples: List[float] = []

    # ------------------------------------------------------------------
    def _load(self) -> List[SolveRecord]:
        with self._db.transaction("load solve history") as session:
            rows = session.scalars(select(SolveRow).order_by(SolveRow.finished_at, SolveRow.id))
            return [record_from_row(row) for row in rows]

    # ------------------------------------------------------------------
    def record(self, record: SolveRecord) -> SolveRecord:
        """Save one solve. Raises StorageError if the database refuses it."""
        with self._write_lock:
            with self._db.transaction("save the solve to history") as session:
                session.add(row_from_record(record))
            with self._lock:
                self._records.append(record)
                self._session_ids.add(record.id)
        return record

    def note_detection_confidence(self, confidence: float) -> None:
        """Feed the running average-confidence metric."""
        with self._lock:
            self._detection_samples.append(confidence)
            if len(self._detection_samples) > 2000:
                del self._detection_samples[:1000]

    def reset_detection_samples(self) -> None:
        with self._lock:
            self._detection_samples.clear()

    # ------------------------------------------------------------------
    @property
    def average_confidence(self) -> float:
        with self._lock:
            if not self._detection_samples:
                return 0.0
            return round(
                sum(self._detection_samples) / len(self._detection_samples), 3
            )

    def summary(self) -> Dict[str, Any]:
        with self._lock:
            records = list(self._records)
            session = [r for r in records if r.id in self._session_ids]

        def _avg(values: List[float]) -> float:
            return round(sum(values) / len(values), 2) if values else 0.0

        move_counts = [r.move_count for r in records]
        solve_times = [r.solve_ms for r in records]
        exec_times = [r.execution_seconds for r in records]

        face_totals = {face: 0 for face in FACES}
        turn_totals = {"cw": 0, "ccw": 0, "double": 0}
        for record in records:
            for face, count in (record.face_distribution or {}).items():
                if face in face_totals:
                    face_totals[face] += count
            for key, count in (record.turn_distribution or {}).items():
                if key in turn_totals:
                    turn_totals[key] += count

        best = min(records, key=lambda r: r.move_count, default=None)

        return {
            "totalSolves": len(records),
            "sessionSolves": len(session),
            "sessionSeconds": round(time.time() - self._session_started, 1),
            "averageMoveCount": _avg([float(m) for m in move_counts]),
            "averageSolveMs": _avg(solve_times),
            "averageExecutionSeconds": _avg(exec_times),
            "bestMoveCount": best.move_count if best else 0,
            "totalMoves": sum(move_counts),
            "averageConfidence": self.average_confidence,
            "faceDistribution": face_totals,
            "turnDistribution": turn_totals,
            "recent": [r.to_dict() for r in records[-12:]][::-1],
            "timeline": [
                {
                    "index": index + 1,
                    "moveCount": record.move_count,
                    "solveMs": round(record.solve_ms, 2),
                    "executionSeconds": round(record.execution_seconds, 1),
                    "finishedAt": record.finished_at,
                }
                for index, record in enumerate(records[-30:])
            ],
        }

    def clear(self) -> None:
        """Wipe history and start a fresh session.

        The session clock is reset too - leaving it running after "Clear
        history" would report a session length with no solves behind it.
        """
        with self._write_lock:
            with self._db.transaction("clear solve history") as session:
                session.execute(delete(SolveRow))
            with self._lock:
                self._records.clear()
                self._session_ids.clear()
                self._detection_samples.clear()
                self._session_started = time.time()
