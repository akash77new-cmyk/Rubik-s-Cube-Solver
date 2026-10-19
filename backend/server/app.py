"""HTTP + WebSocket server.

Responsibilities:

* serve the built React frontend (and fall back to a helpful page if it has not
  been built yet),
* relay browser Socket.IO commands down the engine TCP socket and engine events
  back up to every connected browser,
* expose the camera as an MJPEG stream that any number of tabs can share,
* offer a small REST surface for one-shot reads (health, state, assets).

The server holds **no** cube state of its own - it is a pure relay, so the
engine remains the single source of truth.
"""

from __future__ import annotations

import logging
import mimetypes
from typing import Any, Dict, Iterator

from flask import Flask, Response, jsonify, request, send_from_directory
from flask_socketio import SocketIO

from backend.config import (
    ASSETS_DIR,
    ENGINE_HOST,
    ENGINE_PORT,
    FRONTEND_DIST,
    WEB_HOST,
    WEB_PORT,
)
from backend.ipc.client import EngineClient

log = logging.getLogger("server")

# Windows registries sometimes map .js to a bogus type, which breaks ES modules.
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("image/svg+xml", ".svg")

#: Boundary used by the MJPEG multipart response.
_BOUNDARY = "cubeframe"

_PLACEHOLDER_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Rubik's Cube Solver</title>
<style>
 body{margin:0;height:100vh;display:grid;place-items:center;background:#0b0b12;
      color:#e8e8f0;font:16px/1.6 ui-sans-serif,system-ui,sans-serif}
 .card{max-width:520px;padding:40px;border-radius:20px;text-align:center;
       background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08)}
 code{background:rgba(255,255,255,.08);padding:3px 8px;border-radius:6px}
 h1{margin:0 0 12px;font-size:22px}
</style></head>
<body><div class="card">
 <h1>Frontend not built yet</h1>
 <p>The backend is running. Build the UI once with:</p>
 <p><code>cd frontend &amp;&amp; npm install &amp;&amp; npm run build</code></p>
 <p>Or run <code>python run.py --dev</code> to use the Vite dev server.</p>
</div></body></html>
"""


def create_app(
    engine_host: str = ENGINE_HOST, engine_port: int = ENGINE_PORT
) -> tuple[Flask, SocketIO, EngineClient]:
    """Build the Flask app, Socket.IO server and engine client."""
    app = Flask(__name__, static_folder=None)
    app.config["SECRET_KEY"] = "rubiks-cube-solver"
    socketio = SocketIO(
        app,
        cors_allowed_origins="*",
        async_mode="threading",
        logger=False,
        engineio_logger=False,
    )
    engine = EngineClient(host=engine_host, port=engine_port, want_frames=True)

    # ------------------------------------------------------------------
    # Engine -> browser relay
    # ------------------------------------------------------------------
    def _relay(event: str, data: Any) -> None:
        if not event:
            return
        socketio.emit(event, data)

    engine.add_handler(_relay)

    # ------------------------------------------------------------------
    # Browser -> engine relay
    # ------------------------------------------------------------------
    @socketio.on("connect")
    def _on_connect() -> None:
        socketio.emit("engine:status", engine.status())
        engine.send("sync", {})

    @socketio.on("command")
    def _on_command(message: Dict[str, Any]) -> Dict[str, Any]:
        """Browser command -> engine socket. Returns a Socket.IO ack."""
        if not isinstance(message, dict):
            return {"ok": False, "error": "Malformed command"}
        name = str(message.get("command", ""))
        payload = message.get("payload") or {}
        if not name:
            return {"ok": False, "error": "Missing command name"}
        delivered = engine.send(name, payload)
        if not delivered:
            return {
                "ok": False,
                "error": "Vision engine is not connected. Start it with "
                "`python -m backend.engine`.",
            }
        return {"ok": True, "queued": name}

    # ------------------------------------------------------------------
    # REST
    # ------------------------------------------------------------------
    @app.get("/api/health")
    def health() -> Response:
        return jsonify(
            {
                "status": "ok",
                "engine": engine.status(),
                "frontendBuilt": (FRONTEND_DIST / "index.html").exists(),
            }
        )

    @app.get("/api/engine")
    def engine_status() -> Response:
        return jsonify(engine.status())

    @app.post("/api/command")
    def rest_command() -> Response:
        """REST equivalent of the Socket.IO ``command`` event (handy for curl)."""
        body = request.get_json(silent=True) or {}
        name = str(body.get("command", ""))
        if not name:
            return jsonify({"ok": False, "error": "Missing command"}), 400
        ok = engine.send(name, body.get("payload") or {})
        return jsonify({"ok": ok})

    # ------------------------------------------------------------------
    # MJPEG stream
    # ------------------------------------------------------------------
    def _mjpeg() -> Iterator[bytes]:
        last_id = -1
        while True:
            frame, last_id = engine.wait_for_frame(last_id, timeout=2.0)
            if frame is None:
                # Keep the connection alive while the camera is off.
                yield b""
                continue
            yield (
                b"--" + _BOUNDARY.encode() + b"\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(frame)).encode() + b"\r\n\r\n"
                + frame + b"\r\n"
            )

    @app.get("/api/stream.mjpg")
    def stream() -> Response:
        response = Response(
            _mjpeg(),
            mimetype=f"multipart/x-mixed-replace; boundary={_BOUNDARY}",
        )
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        return response

    @app.get("/api/snapshot.jpg")
    def snapshot() -> Response:
        frame = engine.latest_frame()
        if frame is None:
            return Response(status=503)
        return Response(frame, mimetype="image/jpeg")

    # ------------------------------------------------------------------
    # Assets + SPA
    # ------------------------------------------------------------------
    @app.get("/assets-lib/<path:filename>")
    def project_assets(filename: str) -> Response:
        return send_from_directory(ASSETS_DIR, filename)

    @app.get("/", defaults={"path": ""})
    @app.get("/<path:path>")
    def spa(path: str) -> Response:
        index = FRONTEND_DIST / "index.html"
        if not index.exists():
            return Response(_PLACEHOLDER_PAGE, mimetype="text/html")
        candidate = (FRONTEND_DIST / path).resolve() if path else None
        if (
            candidate
            and candidate.is_file()
            and str(candidate).startswith(str(FRONTEND_DIST.resolve()))
        ):
            return send_from_directory(FRONTEND_DIST, path)
        return send_from_directory(FRONTEND_DIST, "index.html")

    return app, socketio, engine


def run(
    host: str = WEB_HOST,
    port: int = WEB_PORT,
    engine_host: str = ENGINE_HOST,
    engine_port: int = ENGINE_PORT,
    debug: bool = False,
) -> None:
    app, socketio, engine = create_app(engine_host, engine_port)
    engine.start()
    log.info("Web UI on http://%s:%s", host, port)
    socketio.run(
        app,
        host=host,
        port=port,
        debug=debug,
        use_reloader=False,
        allow_unsafe_werkzeug=True,
    )


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    run()
