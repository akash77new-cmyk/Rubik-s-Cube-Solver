"""Kociemba two-phase solving, behind a pluggable backend interface.

Two interchangeable implementations of the **same algorithm** are supported:

``kociemba``       Herbert Kociemba's C implementation via the ``kociemba`` PyPI
                   package. Fastest, but it is a C extension and needs a
                   compiler toolchain on platforms without a prebuilt wheel.

``RubikTwoPhase``  Kociemba's own pure-Python implementation (``twophase``).
                   Installs anywhere with no compiler. It builds ~150 MB of
                   pruning tables on first use, so the engine warms it up in a
                   background thread and reports progress to the UI.

The engine picks the fastest available backend at runtime and exposes which one
is active - that is what the "Current Solver" card on the analytics page shows.
"""

from __future__ import annotations

import importlib
import importlib.util
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from backend.config import SOLVER_TABLE_DIR
from backend.core.cube import CubeState
from backend.core.moves import (
    Move,
    move_distribution,
    parse_sequence,
    sequence_to_string,
    turn_type_distribution,
)

# --------------------------------------------------------------------------------------
# Result type
# --------------------------------------------------------------------------------------


@dataclass
class Solution:
    """A solved manoeuvre plus everything the analytics dashboard needs."""

    moves: List[Move]
    backend: str
    elapsed_ms: float
    facelet_string: str
    scramble_state: Optional[CubeState] = None
    states: List[CubeState] = field(default_factory=list)

    @property
    def notation(self) -> str:
        return sequence_to_string(self.moves)

    @property
    def move_count(self) -> int:
        return len(self.moves)

    @property
    def quarter_turn_count(self) -> int:
        return sum(2 if m.modifier == "2" else 1 for m in self.moves)

    def to_dict(self) -> Dict[str, object]:
        return {
            "moves": [move.to_dict() for move in self.moves],
            "notation": self.notation,
            "moveCount": self.move_count,
            "quarterTurnCount": self.quarter_turn_count,
            "backend": self.backend,
            "elapsedMs": round(self.elapsed_ms, 2),
            "faceletString": self.facelet_string,
            "faceDistribution": move_distribution(self.moves),
            "turnDistribution": turn_type_distribution(self.moves),
            "states": [state.facelets for state in self.states],
        }


class SolverUnavailableError(RuntimeError):
    """No solving backend could be loaded."""


class SolveFailedError(RuntimeError):
    """The backend rejected the cube (usually an unsolvable scan)."""


# --------------------------------------------------------------------------------------
# Backends
# --------------------------------------------------------------------------------------


class SolverBackendBase:
    key = "base"
    name = "Base"
    description = ""
    #: Lower is preferred.
    priority = 100
    #: True when the backend needs a slow one-time preparation step.
    needs_warmup = False

    def is_installed(self) -> bool:  # pragma: no cover - overridden
        raise NotImplementedError

    def prepare(self, progress: Optional[Callable[[str], None]] = None) -> None:
        """Load whatever the backend needs. May block for a long time."""

    def solve(self, facelets: str, max_length: int, timeout: float) -> str:
        # pragma: no cover - overridden
        raise NotImplementedError


class KociembaCBackend(SolverBackendBase):
    """``kociemba`` PyPI package - C extension, sub-millisecond solves."""

    key = "kociemba-c"
    name = "Kociemba Two-Phase (C)"
    description = "Native C implementation of the two-phase algorithm"
    priority = 0

    def is_installed(self) -> bool:
        return importlib.util.find_spec("kociemba") is not None

    def prepare(self, progress: Optional[Callable[[str], None]] = None) -> None:
        importlib.import_module("kociemba")

    def solve(self, facelets: str, max_length: int, timeout: float) -> str:
        kociemba = importlib.import_module("kociemba")
        return kociemba.solve(facelets)


class TwoPhasePythonBackend(SolverBackendBase):
    """``RubikTwoPhase`` - Kociemba's pure-Python two-phase implementation."""

    key = "twophase-py"
    name = "Kociemba Two-Phase (Python)"
    description = "Pure-Python two-phase search with symmetry-reduced pruning tables"
    priority = 1
    needs_warmup = True

    #: ``U1 R2 F3`` -> ``U R2 F'``
    _SUFFIX = {"1": "", "2": "2", "3": "'"}

    def is_installed(self) -> bool:
        return importlib.util.find_spec("twophase") is not None

    def prepare(self, progress: Optional[Callable[[str], None]] = None) -> None:
        # Point the library's table cache at our own directory *before* importing
        # the modules that build them, otherwise they land in the cwd.
        defs = importlib.import_module("twophase.defs")
        defs.FOLDER = str(SOLVER_TABLE_DIR)
        if progress:
            progress("Loading two-phase pruning tables (one-time table build on first run)")
        importlib.import_module("twophase.solver")

    def solve(self, facelets: str, max_length: int, timeout: float) -> str:
        solver = importlib.import_module("twophase.solver")
        raw = solver.solve(facelets, max_length, timeout)
        return self._normalise(raw)

    @classmethod
    def _normalise(cls, raw: str) -> str:
        """Convert ``"U1 R2 F3 (3f)"`` into standard ``"U R2 F'"`` notation."""
        raw = (raw or "").strip()
        if not raw:
            raise SolveFailedError("Solver returned an empty solution")
        if raw.lower().startswith("error"):
            raise SolveFailedError(raw)
        tokens = [t for t in raw.split() if not t.endswith("f)")]
        moves: List[str] = []
        for token in tokens:
            if len(token) != 2 or token[1] not in cls._SUFFIX:
                raise SolveFailedError(f"Unexpected token from solver: {token!r}")
            moves.append(token[0] + cls._SUFFIX[token[1]])
        return " ".join(moves)


# --------------------------------------------------------------------------------------
# Engine
# --------------------------------------------------------------------------------------

_STATE_UNINITIALISED = "uninitialised"
_STATE_WARMING = "warming"
_STATE_READY = "ready"
_STATE_ERROR = "error"


class SolverEngine:
    """Chooses a backend, warms it up off the request thread and solves cubes."""

    def __init__(self, backends: Optional[List[SolverBackendBase]] = None) -> None:
        self._backends = sorted(
            backends or [KociembaCBackend(), TwoPhasePythonBackend()],
            key=lambda b: b.priority,
        )
        self._backend: Optional[SolverBackendBase] = None
        self._state = _STATE_UNINITIALISED
        self._message = "Solver not initialised"
        self._lock = threading.RLock()
        self._ready = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._listeners: List[Callable[[Dict[str, object]], None]] = []

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------
    def add_listener(self, callback: Callable[[Dict[str, object]], None]) -> None:
        """Register a callback fired whenever solver status changes."""
        self._listeners.append(callback)

    def _emit(self) -> None:
        status = self.status()
        for listener in list(self._listeners):
            try:
                listener(status)
            except Exception:  # pragma: no cover - listener must never break the engine
                pass

    def _set_state(self, state: str, message: str) -> None:
        with self._lock:
            self._state = state
            self._message = message
        self._emit()

    def status(self) -> Dict[str, object]:
        with self._lock:
            backend = self._backend
            return {
                "state": self._state,
                "message": self._message,
                "ready": self._state == _STATE_READY,
                "backend": backend.name if backend else None,
                "backendKey": backend.key if backend else None,
                "description": backend.description if backend else "",
                "available": [
                    {
                        "key": b.key,
                        "name": b.name,
                        "description": b.description,
                        "installed": b.is_installed(),
                        "needsWarmup": b.needs_warmup,
                    }
                    for b in self._backends
                ],
            }

    @property
    def is_ready(self) -> bool:
        return self._ready.is_set()

    # ------------------------------------------------------------------
    # Warm-up
    # ------------------------------------------------------------------
    def warm_up_async(self) -> None:
        """Start backend preparation in the background (idempotent)."""
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            if self._state == _STATE_READY:
                return
            self._thread = threading.Thread(
                target=self._warm_up, name="solver-warmup", daemon=True
            )
            self._thread.start()

    def warm_up(self, timeout: Optional[float] = None) -> bool:
        """Block until a backend is ready (or ``timeout`` elapses)."""
        self.warm_up_async()
        return self._ready.wait(timeout)

    def _warm_up(self) -> None:
        installed = [b for b in self._backends if b.is_installed()]
        if not installed:
            self._set_state(
                _STATE_ERROR,
                "No solver backend installed. Run: pip install RubikTwoPhase",
            )
            return

        for backend in installed:
            self._set_state(_STATE_WARMING, f"Preparing {backend.name}...")
            try:
                started = time.perf_counter()
                backend.prepare(progress=lambda msg: self._set_state(_STATE_WARMING, msg))
                elapsed = time.perf_counter() - started
            except Exception as exc:
                self._set_state(
                    _STATE_WARMING, f"{backend.name} unavailable ({exc}); trying next"
                )
                continue

            with self._lock:
                self._backend = backend
            self._ready.set()
            self._set_state(
                _STATE_READY, f"{backend.name} ready in {elapsed:.2f}s"
            )
            return

        self._set_state(_STATE_ERROR, "Every solver backend failed to initialise")

    # ------------------------------------------------------------------
    # Solving
    # ------------------------------------------------------------------
    def solve(
        self,
        cube: CubeState,
        max_length: int = 20,
        timeout: float = 5.0,
        wait_for_warmup: Optional[float] = None,
    ) -> Solution:
        """Solve ``cube`` and return a :class:`Solution` with per-move states."""
        validation = cube.validate()
        if not validation.ok:
            raise SolveFailedError("; ".join(validation.errors))

        if not self._ready.is_set():
            self.warm_up_async()
            if not self._ready.wait(wait_for_warmup):
                raise SolverUnavailableError(self._message)

        backend = self._backend
        if backend is None:  # pragma: no cover - guarded by the event above
            raise SolverUnavailableError(self._message)

        facelets = cube.to_facelet_string()
        started = time.perf_counter()
        try:
            raw = backend.solve(facelets, max_length, timeout)
        except SolveFailedError:
            raise
        except Exception as exc:
            raise SolveFailedError(str(exc)) from exc
        elapsed_ms = (time.perf_counter() - started) * 1000.0

        raw = (raw or "").strip()
        if raw.lower().startswith("error"):
            raise SolveFailedError(raw)

        moves = parse_sequence(raw) if raw else []
        return Solution(
            moves=moves,
            backend=backend.name,
            elapsed_ms=elapsed_ms,
            facelet_string=facelets,
            scramble_state=cube,
            states=cube.trace(moves),
        )


#: Process-wide engine. The vision engine process owns it; the web server talks
#: to that process over the socket bus rather than importing it a second time.
solver_engine = SolverEngine()
