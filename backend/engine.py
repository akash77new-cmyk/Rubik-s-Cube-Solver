"""Vision engine process entry point.

Run standalone::

    python -m backend.engine

This process owns the camera, the OpenCV pipeline, the Kociemba solver and the
database connection, and publishes everything over the TCP engine socket. The web
server is just a subscriber, so the blocking capture loop can never stall HTTP
requests - and the same engine could equally well feed a native client or a second
machine.

Phase 9: one SolveSession per visitor (``backend/services/sessions.py``). The web server
says who sent each command; the engine runs it in that visitor's session, and the
session's events go back addressed to that visitor only. Accounts (``auth.*`` commands,
sent only by the web server's sign-up and login endpoints) are checked here, next to
the database.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
from typing import Any, Dict

from backend.ai.service import AIConfig, AIService
from backend.ai.tracing import TraceStore
from backend.config import DATA_DIR, DATASET_DIR, ENGINE_HOST, ENGINE_PORT, MODEL_DIR, RUNTIME
from backend.core.solver import solver_engine
from backend.db import Database, StorageError, connect
from backend.ipc.server import ClientConnection, EngineServer
from backend.services.accounts import AccountError, AccountStore
from backend.services.analytics import AnalyticsStore
from backend.services.dataset import DatasetStore
from backend.services.legacy_import import import_legacy_json
from backend.services.logbus import log_bus
from backend.services.profiles import ProfileStore
from backend.services.sessions import SessionManager, SharedServices, build_session, visitor_from
from backend.services.settings import SettingsStore
from backend.vision.classifier import load_color_model

log = logging.getLogger("engine")


#: How often idle sessions are looked for and closed.
PRUNE_EVERY_SECONDS = 60.0


class VisionEngine:
    """Wires the visitors' sessions to the socket server."""

    def __init__(
        self, database: Database, host: str = ENGINE_HOST, port: int = ENGINE_PORT
    ) -> None:
        self.database = database
        self.settings = SettingsStore(database)
        self.profiles = ProfileStore(database)
        #: Solves made without an account (locally: the laptop owner's history).
        self.analytics = AnalyticsStore(database)
        self.accounts = AccountStore(database)
        # Training-data collection (Phase 2): off in production, see config.py.
        self.dataset = DatasetStore(DATASET_DIR) if RUNTIME.dataset_enabled else None
        self.server = EngineServer(
            host=host,
            port=port,
            on_command=self._on_command,
            on_connect=self._on_connect,
        )
        # AI (Phase 4): Gemini when GEMINI_API_KEY is set, else built-in answers only.
        self.ai = AIService.create(
            AIConfig(
                api_key=RUNTIME.gemini_api_key,
                model=RUNTIME.gemini_model,
                base_url=RUNTIME.gemini_base_url,
                thinking_level=RUNTIME.gemini_thinking_level,
                requests_per_minute=RUNTIME.ai_requests_per_minute,
                requests_per_day=RUNTIME.ai_requests_per_day,
                embed_model=RUNTIME.gemini_embed_model,
            ),
            TraceStore(database),
            publish=self.server.broadcast,
            logs=log_bus,
            database=database,  # the lessons' embeddings live there (Phase 7)
        )
        # The scanner's colour model (Phase 11): the trained CNN, or the HSV detector.
        classifier, self.color_model = load_color_model(RUNTIME.color_model, MODEL_DIR)
        shared = SharedServices(
            settings=self.settings,
            profiles=self.profiles,
            solver=solver_engine,
            logs=log_bus,
            accounts=self.accounts,
            database=database,
            local_analytics=self.analytics,
            publish=self.server.broadcast,
            publish_frame=self.server.broadcast_frame,
            dataset=self.dataset,
            ai=self.ai,
            classifier=classifier,
            color_model=self.color_model,
            production=RUNTIME.is_production,
        )
        # One session per visitor (Phase 9). The web server is told who uses the camera,
        # so it streams the camera only to that visitor.
        self.sessions = SessionManager(
            lambda visitor, guard: build_session(visitor, guard, shared),
            on_camera_change=lambda owner: self.server.broadcast("camera:owner", {"session": owner}),
        )
        # Stream every log entry to subscribers as it happens.
        log_bus.add_listener(lambda entry: self.server.broadcast("log", entry.to_dict()))
        # The solver's status is the same for everyone: sent once, to every visitor.
        solver_engine.add_listener(lambda status: self.server.broadcast("solver", status))
        self._stop = threading.Event()

    # ------------------------------------------------------------------
    def _on_connect(self, client: ClientConnection) -> None:
        """A web server connected: send what every visitor shares. Each visitor's own
        state follows when their browser connects (the web server sends ``sync``)."""
        client.send_json({"event": "logs", "data": log_bus.history()})
        client.send_json({"event": "solver", "data": solver_engine.status()})
        client.send_json({"event": "camera:owner", "data": {"session": self.sessions.camera.owner}})

    def _on_command(self, message: Dict[str, Any], client: ClientConnection) -> None:
        command = str(message.get("command", ""))
        payload = message.get("payload") or {}

        if command == "subscribe":
            client.wants_frames = bool(payload.get("frames", True))
            client.send_json({"event": "subscribed", "data": {"frames": client.wants_frames}})
            return

        request_id = message.get("requestId")
        if command.startswith("auth."):
            # Password hashing is slow on purpose (~1 s on Render's small CPU), so it runs in
            # its own thread: other visitors' commands are not held up meanwhile.
            threading.Thread(
                target=self._auth, args=(command, payload, request_id, client), name="auth", daemon=True
            ).start()
            return

        visitor = visitor_from(message)
        if command == "touch":  # the web server: this visitor still has a tab open
            self.sessions.touch(visitor.key)
            return
        session = self.sessions.get(visitor)
        result = session.handle_command(command, payload)
        if request_id is not None:
            client.send_json(
                {"event": "ack", "data": {"requestId": request_id, "result": result}}
            )

    def _auth(self, command: str, payload: Dict[str, Any], request_id: Any, client: ClientConnection) -> None:
        """Sign-up, login and account deletion, for the web server's /api/auth endpoints."""
        try:
            result = self._auth_result(command, payload)
        except AccountError as exc:
            result = {"ok": False, "error": str(exc)}
        except StorageError as exc:
            log_bus.error(f"Accounts: {exc}", source="database")
            result = {"ok": False, "error": "The account service is not available right now. Try again soon."}
        except Exception as exc:  # a bug must not leave the web server waiting for an answer
            log.exception("Account command %s failed", command)
            result = {"ok": False, "error": f"Something went wrong: {exc}"}
        if request_id is not None:
            client.send_json({"event": "ack", "data": {"requestId": request_id, "result": result}})

    def _auth_result(self, command: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if command == "auth.signup":
            account = self.accounts.create(str(payload.get("email", "")), payload.get("password", ""))
            log_bus.success(f"A new account was created (#{account.id})", source="accounts")  # never the email
            return {"ok": True, "user": account.to_dict()}
        if command == "auth.login":
            account = self.accounts.authenticate(str(payload.get("email", "")), payload.get("password", ""))
            if account is None:
                return {"ok": False, "error": "Wrong email or password."}
            log_bus.info(f"Account #{account.id} logged in", source="accounts")
            return {"ok": True, "user": account.to_dict()}
        if command == "auth.delete":
            user_id = int(payload.get("user_id", 0))
            if not self.accounts.delete(user_id, payload.get("password", "")):
                return {"ok": False, "error": "Wrong password."}
            self.sessions.close(f"u:{user_id}")
            log_bus.info(f"Account #{user_id} was deleted, with its history", source="accounts")
            return {"ok": True}
        return {"ok": False, "error": f"Unknown command: {command}"}

    # ------------------------------------------------------------------
    def run(self) -> None:
        self.server.start()
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
        ai = self.ai.status()
        if ai["enabled"]:
            budget = ai["budget"]
            ai_summary = (
                f"AI: {ai['provider']} {ai['model']} "
                f"(limits: {budget['perMinute']}/min, {budget['perDay']}/day)"
            )
        else:
            ai_summary = f"AI: off ({ai['offReason']}), so the assistant gives built-in answers"
        log.info(ai_summary)
        log_bus.info(ai_summary, source="ai")
        self.ai.start_lessons()  # embeds new or changed lessons in the background
        if self.dataset is not None:
            log_bus.info(f"Dataset collection is on: {DATASET_DIR}", source="dataset")
        model = self.color_model
        if model["active"] == "cnn":
            accuracy = model["model"]["cnnAccuracy"]
            tested = f"{accuracy:.1%} on held-out scans" if accuracy is not None else "untested"
            colour_summary = f"Colour model: the trained CNN ({tested})"
        else:
            colour_summary = f"Colour model: HSV ({model['reason']})"
        log.info(colour_summary)
        log_bus.info(colour_summary, source="scan")
        # Building the two-phase pruning tables can take a while on first run;
        # do it off the command path so the UI stays responsive meanwhile.
        solver_engine.warm_up_async()

        try:
            while not self._stop.wait(PRUNE_EVERY_SECONDS):
                closed = self.sessions.prune()
                if closed:
                    log.info("Closed %d idle session(s); %d open", len(closed), len(self.sessions))
        except KeyboardInterrupt:  # pragma: no cover
            pass
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        self._stop.set()
        self.sessions.shutdown()
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
