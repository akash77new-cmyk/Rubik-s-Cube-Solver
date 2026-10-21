"""Vision engine process entry point.

Run standalone::

    python -m backend.engine

This process owns the camera, the OpenCV pipeline, the Kociemba solver and the
database connection, and publishes everything over the TCP engine socket. The web
server is just a subscriber, so the blocking capture loop can never stall HTTP
requests - and the same engine could equally well feed a native client or a second
machine.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
from typing import Any, Dict

from backend.config import DATA_DIR, DATASET_DIR, ENGINE_HOST, ENGINE_PORT, RUNTIME
from backend.core.solver import solver_engine
from backend.db import Database, StorageError, connect
from backend.ipc.server import ClientConnection, EngineServer
from backend.services.analytics import AnalyticsStore
from backend.services.dataset import DatasetStore
from backend.services.legacy_import import import_legacy_json
from backend.services.logbus import log_bus
from backend.services.profiles import ProfileStore
from backend.services.session import SolveSession
from backend.services.settings import SettingsStore

log = logging.getLogger("engine")


class VisionEngine:
    """Wires the session to the socket server."""

    def __init__(
        self, database: Database, host: str = ENGINE_HOST, port: int = ENGINE_PORT
    ) -> None:
        self.database = database
        self.settings = SettingsStore(database)
        self.profiles = ProfileStore(database)
        self.analytics = AnalyticsStore(database)
        # Training-data collection (Phase 2): off in production, see config.py.
        self.dataset = DatasetStore(DATASET_DIR) if RUNTIME.dataset_enabled else None
        self.server = EngineServer(
            host=host,
            port=port,
            on_command=self._on_command,
            on_connect=self._on_connect,
        )
        self.session = SolveSession(
            settings=self.settings,
            profiles=self.profiles,
            solver=solver_engine,
            logs=log_bus,
            analytics=self.analytics,
            publish_event=self.server.broadcast,
            publish_frame=self.server.broadcast_frame,
            dataset=self.dataset,
            database=database,
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
        status = self.database.status()
        summary = (
            f"Database: {status['backend']} {status['serverVersion']} at {status['location']}, "
            f"schema {status['schemaRevision']}"
        )
        log.info(summary)  # the terminal, and Render's log
        log_bus.success(summary, source="database")  # the Logs page
        if self.dataset is not None:
            log_bus.info(f"Dataset collection is on: {DATASET_DIR}", source="dataset")
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
        self.database.dispose()
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

    # The database comes first: without it there is nowhere to keep settings and
    # history, so stop with a clear message instead of running half-broken.
    try:
        database = connect()
    except StorageError as exc:
        log.error("%s", exc)
        log.error("Check DATABASE_URL (see .env.example). The engine cannot start without it.")
        return 1
    for message in import_legacy_json(database, DATA_DIR):
        log.info(message)
        log_bus.info(message, source="database")

    engine = VisionEngine(database, args.host, args.port)

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
