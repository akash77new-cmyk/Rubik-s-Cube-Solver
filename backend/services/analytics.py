"""Solve history and aggregate statistics for the analytics dashboard."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List

from backend.config import HISTORY_FILE
from backend.core.moves import FACES


@dataclass
class SolveRecord:
    """One completed solve, persisted to disk."""

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


class AnalyticsStore:
    """Append-only solve log with derived session/lifetime statistics."""

    MAX_RECORDS = 200

    def __init__(self, path: Path = HISTORY_FILE) -> None:
        self._path = path
        self._lock = threading.RLock()
        self._records: List[SolveRecord] = []
        self._session_started = time.time()
        self._session_ids: set[str] = set()
        self._detection_samples: List[float] = []
        self._load()

    # ------------------------------------------------------------------
    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            payload = json.loads(self._path.read_text("utf-8"))
            for item in payload.get("records", []):
                try:
                    self._records.append(SolveRecord(**item))
                except TypeError:
                    continue  # skip records written by an older schema
        except (json.JSONDecodeError, OSError):
            self._records = []

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"records": [r.to_dict() for r in self._records[-self.MAX_RECORDS :]]}
        self._path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # ------------------------------------------------------------------
    def record(self, record: SolveRecord) -> SolveRecord:
        with self._lock:
            self._records.append(record)
            self._session_ids.add(record.id)
            self._save()
            return record

    def note_detection_confidence(self, confidence: float) -> None:
        """Feed the running detection-accuracy metric."""
        with self._lock:
            self._detection_samples.append(confidence)
            if len(self._detection_samples) > 2000:
                del self._detection_samples[:1000]

    def reset_detection_samples(self) -> None:
        with self._lock:
            self._detection_samples.clear()

    # ------------------------------------------------------------------
    @property
    def detection_accuracy(self) -> float:
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
            "detectionAccuracy": self.detection_accuracy,
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
        with self._lock:
            self._records.clear()
            self._session_ids.clear()
            self._detection_samples.clear()
            self._session_started = time.time()
            self._save()
