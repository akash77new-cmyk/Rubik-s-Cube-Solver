"""Vision engine process entry point.

Run standalone::

    python -m backend.engine

This process owns the camera, the OpenCV pipeline and the Kociemba solver, and
publishes everything over the TCP engine socket. The web server is just a
subscriber, so the blocking capture loop can never stall HTTP requests - and the
same engine could equally well feed a native client or a second machine.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
from typing import Any, Dict

from backend.config import ENGINE_HOST, ENGINE_PORT, settings_store
from backend.core.color import profile_store
from backend.core.solver import solver_engine
from backend.ipc.server import ClientConnection, EngineServer
from backend.services.analytics import AnalyticsStore
from backend.services.logbus import log_bus
from backend.services.session import SolveSession

log = logging.getLogger("engine")


class VisionEngine:
    """Wires the session to the socket server."""

    def __init__(self, host: str = ENGINE_HOST, port: int = ENGINE_PORT) -> None:
        self.analytics = AnalyticsStore()
        self.server = EngineServer(
            host=host,
            port=port,
            on_command=self._on_command,
            on_connect=self._on_connect,
        )
        self.session = SolveSession(
            settings=settings_store,
            profiles=profile_store,
            solver=solver_engine,
            logs=log_bus,
            analytics=self.analytics,
            publish_event=self.server.broadcast,
            publish_frame=self.server.broadcast_frame,
        )
        # Stream every log entry to subscribers as it happens.
        log_bus.add_listener(lambda entry: self.server.broadcast("log", entry.to_dict()))
        self._stop = threading.Event()

    # ------------------------------------------------------------------
    def _on_connect(self, client: ClientConnection) -> None:
        """Send a full snapshot so a late subscriber is immediately in sync."""
        client.send_json({"event": "state", "data": self.session.snapshot()})
        client.send_json({"event": "logs", "data": log_bus.history()})
        client.send_json({"event": "analytics", "data": self.analytics.summary()})
        client.send_json({"event": "solver", "data": solver_engine.status()})

    def _on_command(self, message: Dict[str, Any], client: ClientConnection) -> None:
        command = str(message.get("command", ""))
        payload = message.get("payload") or {}

        if command == "subscribe":
            client.wants_frames = bool(payload.get("frames", True))
            client.send_json({"event": "subscribed", "data": {"frames": client.wants_frames}})
            return

        result = self.session.handle_command(command, payload)
        request_id = message.get("requestId")
        if request_id is not None:
            client.send_json(
                {"event": "ack", "data": {"requestId": request_id, "result": result}}
            )

    # ------------------------------------------------------------------
    def run(self) -> None:
        self.server.start()
        self.session.start()
        log_bus.success(
            f"Vision engine online at {self.server.host}:{self.server.port}",
            source="engine",
        )
        # Building the two-phase pruning tables can take a while on first run;
        # do it off the command path so the UI stays responsive meanwhile.
        solver_engine.warm_up_async()

        try:
            while not self._stop.wait(0.5):
                pass
        except KeyboardInterrupt:  # pragma: no cover
            pass
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        self._stop.set()
        self.session.shutdown()
        self.server.stop()
        log.info("Vision engine stopped")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rubik's Cube vision engine")
    parser.add_argument("--host", default=ENGINE_HOST)
    parser.add_argument("--port", type=int, default=ENGINE_PORT)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    engine = VisionEngine(args.host, args.port)

    def _handle_signal(signum, _frame):  # pragma: no cover - signal path
        engine.shutdown()
        sys.exit(0)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _handle_signal)
        except (ValueError, OSError):
            pass  # not available on every platform/thread

    engine.run()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
