"""HTTP + WebSocket server.

Responsibilities:

* serve the built React frontend (and fall back to a helpful page if it has not
  been built yet),
* relay browser Socket.IO commands down the engine TCP socket and engine events
  back up to the browsers they are for,
* expose the camera as an MJPEG stream that any number of tabs can share,
* offer a small REST surface for one-shot reads (health, state, assets),
* accounts (Phase 9): sign-up, login and logout under ``/api/auth/``, and a signed token
  (JWT, in an HttpOnly cookie) on every request, so it knows **who** each visitor is.

The server holds **no** cube state of its own - it is a pure relay, so the
engine remains the single source of truth. It does decide identity: each command it
relays carries the visitor's session key, taken from their verified token, never from
anything the browser claims.
"""

from __future__ import annotations

import logging
import mimetypes
import os
import threading
import time
from typing import Any, Dict, Iterator, Optional

from flask import Flask, Response, jsonify, request, send_from_directory
from flask_socketio import SocketIO, join_room

from backend.config import (
    ASSETS_DIR,
    ENGINE_HOST,
    ENGINE_PORT,
    FRONTEND_DIST,
    RUNTIME,
    WEB_HOST,
    WEB_PORT,
)
from backend.ipc.client import EngineClient
from backend.server.auth import (
    COOKIE,
    GUEST_TOKEN_SECONDS,
    USER_TOKEN_SECONDS,
    Identity,
    LoginLimiter,
    issue_token,
    new_guest,
    public_view,
    read_token,
    session_key,
    user_identity,
)

log = logging.getLogger("server")

# Windows registries sometimes map .js to a bogus type, which breaks ES modules.
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("image/svg+xml", ".svg")

#: Boundary used by the MJPEG multipart response.
_BOUNDARY = "cubeframe"

#: The deployed commit: Render sets RENDER_GIT_COMMIT. After a deploy, /api/health shows
#: which version is live ("local" when running on a laptop).
VERSION = (os.environ.get("RENDER_GIT_COMMIT") or "local")[:7]

#: Security headers on every response (Phase 12): no MIME sniffing, no framing of the
#: app inside another site (clickjacking), and no full URLs leaked to other sites.
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}

#: Commands only the server itself may send to the engine, never a browser.
INTERNAL_COMMANDS = ("auth.", "subscribe", "touch")
#: How often the engine hears that a connected visitor is still there (it closes idle sessions).
KEEP_ALIVE_SECONDS = 300.0
#: How long sign-up and login wait for the engine (password hashing takes ~1 s on Render).
AUTH_TIMEOUT_SECONDS = 15.0

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
    app.config["SECRET_KEY"] = RUNTIME.secret_key
    socketio = SocketIO(
        app,
        cors_allowed_origins=RUNTIME.allowed_origins,
        async_mode="threading",
        logger=False,
        engineio_logger=False,
    )
    engine = EngineClient(host=engine_host, port=engine_port, want_frames=True)
    limiter = LoginLimiter()
    #: Socket.IO connection id -> (session key, user) of the visitor on it.
    connections: Dict[str, Any] = {}
    #: Whose session is using the camera now (the engine says): only they get its frames.
    camera = {"owner": None}
    keep_alive_started = threading.Event()

    def keep_alive() -> None:
        """Every few minutes, tell the engine which visitors still have a tab open."""
        while True:
            time.sleep(KEEP_ALIVE_SECONDS)
            for key in {key for key, _ in list(connections.values())}:
                engine.send("touch", {}, session=key)

    def identity() -> Optional[Identity]:
        """The visitor of the current request, from their token cookie (None = no valid token)."""
        return read_token(RUNTIME.secret_key, request.cookies.get(COOKIE))

    def with_token(response: Response, who: Identity) -> Response:
        """Attach a fresh token for ``who`` as an HttpOnly cookie."""
        lifetime = USER_TOKEN_SECONDS if who["kind"] == "user" else GUEST_TOKEN_SECONDS
        response.set_cookie(
            COOKIE, issue_token(RUNTIME.secret_key, who), max_age=lifetime, httponly=True,
            samesite="Lax", secure=RUNTIME.is_production, path="/",
        )
        return response

    def engine_user(who: Optional[Identity]) -> Optional[Dict[str, Any]]:
        return {"id": who["id"], "email": who["email"]} if who and who["kind"] == "user" else None

    @app.after_request
    def _security_headers(response: Response) -> Response:
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response

    # ------------------------------------------------------------------
    # Engine -> browser relay
    # ------------------------------------------------------------------
    def _relay(event: str, data: Any, to: Optional[str]) -> None:
        if not event:
            return
        if event == "camera:owner":  # for the server itself, never shown to browsers
            camera["owner"] = (data or {}).get("session")
            return
        if to is None:
            socketio.emit(event, data)  # for every visitor (logs, the solver's status)
        else:
            socketio.emit(event, data, to=to)  # only that visitor's tabs (their room)

    engine.add_routed_handler(_relay)

    # ------------------------------------------------------------------
    # Browser -> engine relay
    # ------------------------------------------------------------------
    @socketio.on("connect")
    def _on_connect() -> None:
        # Each visitor joins a "room" named after their session key, so the engine's
        # events for that session reach all of their tabs and nobody else's.
        who = identity()
        key = session_key(who) if who else f"s:{request.sid}"  # no token (tools): its own session
        connections[request.sid] = (key, engine_user(who))
        join_room(key)
        if not keep_alive_started.is_set():
            keep_alive_started.set()
            threading.Thread(target=keep_alive, name="keep-alive", daemon=True).start()
        socketio.emit("engine:status", engine.status(), to=request.sid)
        engine.send("sync", {}, session=key, user=engine_user(who))

    @socketio.on("disconnect")
    def _on_disconnect(*_args: Any) -> None:
        connections.pop(request.sid, None)

    @socketio.on("command")
    def _on_command(message: Dict[str, Any]) -> Dict[str, Any]:
        """Browser command -> engine socket, tagged with who sent it. Returns a Socket.IO ack."""
        if not isinstance(message, dict):
            return {"ok": False, "error": "Malformed command"}
        name = str(message.get("command", ""))
        payload = message.get("payload") or {}
        if not name:
            return {"ok": False, "error": "Missing command name"}
        if name.startswith(INTERNAL_COMMANDS):
            return {"ok": False, "error": f"Unknown command: {name}"}
        key, user = connections.get(request.sid, (f"s:{request.sid}", None))
        delivered = engine.send(name, payload, session=key, user=user)
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
                "version": VERSION,
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
        if name.startswith(INTERNAL_COMMANDS):
            return jsonify({"ok": False, "error": f"Unknown command: {name}"}), 400
        who = identity()
        key = session_key(who) if who else "local"
        ok = engine.send(name, body.get("payload") or {}, session=key, user=engine_user(who))
        return jsonify({"ok": ok})

    # ------------------------------------------------------------------
    # Accounts (Phase 9)
    # ------------------------------------------------------------------
    def credentials() -> Optional[Dict[str, Any]]:
        """The JSON body, or None. Only JSON is accepted: a form on another site can't send it."""
        if not request.is_json:
            return None
        body = request.get_json(silent=True)
        return body if isinstance(body, dict) else None

    def ask_engine(command: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        return engine.request(command, payload, timeout=AUTH_TIMEOUT_SECONDS)

    def unavailable() -> Response:
        response = jsonify({"error": "The server is starting or busy. Try again in a moment."})
        response.status_code = 503
        return response

    @app.get("/api/auth/me")
    def auth_me() -> Response:
        """Who this browser is. A browser without a valid token becomes a new guest."""
        who = identity()
        if who is not None:
            return jsonify(public_view(who))
        guest = new_guest()
        return with_token(jsonify(public_view(guest)), guest)

    @app.post("/api/auth/signup")
    def auth_signup() -> Response:
        body = credentials()
        if body is None:
            return jsonify({"error": "Send JSON: {\"email\": ..., \"password\": ...}"}), 415
        result = ask_engine("auth.signup", {"email": body.get("email", ""), "password": body.get("password", "")})
        if result is None:
            return unavailable()
        if not result.get("ok"):
            return jsonify({"error": result.get("error", "Could not create the account.")}), 400
        who = user_identity(result["user"])
        response = with_token(jsonify(public_view(who)), who)
        response.status_code = 201
        return response

    @app.post("/api/auth/login")
    def auth_login() -> Response:
        body = credentials()
        if body is None:
            return jsonify({"error": "Send JSON: {\"email\": ..., \"password\": ...}"}), 415
        email = str(body.get("email", "")).strip().lower()
        wait = limiter.wait_seconds(email)
        if wait:
            minutes = (wait + 59) // 60
            response = jsonify({"error": f"Too many wrong passwords. Try again in {minutes} minute(s)."})
            response.status_code = 429
            response.headers["Retry-After"] = str(wait)
            return response
        result = ask_engine("auth.login", {"email": email, "password": body.get("password", "")})
        if result is None:
            return unavailable()
        if not result.get("ok"):
            limiter.failed(email)
            return jsonify({"error": result.get("error", "Wrong email or password.")}), 401
        limiter.succeeded(email)
        who = user_identity(result["user"])
        return with_token(jsonify(public_view(who)), who)

    @app.post("/api/auth/logout")
    def auth_logout() -> Response:
        """Back to being a guest (a new one: the account's session isn't left reachable)."""
        guest = new_guest()
        return with_token(jsonify(public_view(guest)), guest)

    @app.post("/api/auth/delete")
    def auth_delete() -> Response:
        """Delete the logged-in account and its history (the password is asked again)."""
        who = identity()
        if who is None or who["kind"] != "user":
            return jsonify({"error": "Log in first."}), 401
        body = credentials()
        if body is None:
            return jsonify({"error": "Send JSON: {\"password\": ...}"}), 415
        result = ask_engine("auth.delete", {"user_id": who["id"], "password": body.get("password", "")})
        if result is None:
            return unavailable()
        if not result.get("ok"):
            return jsonify({"error": result.get("error", "Wrong password.")}), 403
        guest = new_guest()
        return with_token(jsonify(public_view(guest)), guest)

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

    def may_watch_camera() -> bool:
        """Only the visitor whose session uses the camera may see it (Phase 9)."""
        owner = camera["owner"]
        if owner is None:
            return True  # camera off: the stream only sends keep-alives
        who = identity()
        return who is not None and session_key(who) == owner

    @app.get("/api/stream.mjpg")
    def stream() -> Response:
        if not may_watch_camera():
            return Response("The camera belongs to another session.", status=403)
        response = Response(
            _mjpeg(),
            mimetype=f"multipart/x-mixed-replace; boundary={_BOUNDARY}",
        )
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        return response

    @app.get("/api/snapshot.jpg")
    def snapshot() -> Response:
        if not may_watch_camera():
            return Response(status=403)
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
