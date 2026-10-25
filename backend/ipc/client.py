"""TCP client side of the engine socket, with automatic reconnection.

The web server holds one of these for the lifetime of the process. It keeps the
most recent camera frame in memory so the MJPEG endpoint can serve any number of
browser tabs from a single engine subscription.

Phase 9 adds two things:

- every command can say **who** sent it (``session`` and ``user``), and events can say
  whom they are **for** (``to``): ``add_routed_handler`` receives that;
- ``request()``: send a command and wait for its answer (the engine's ``ack`` with the
  same ``requestId``). Sign-up and login use it: the web server needs the result.
"""

from __future__ import annotations

import logging
import socket
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from backend.ipc.protocol import (
    KIND_FRAME,
    KIND_JSON,
    MessageReader,
    ProtocolError,
    decode_json,
    encode_json,
)

log = logging.getLogger(__name__)

EventHandler = Callable[[str, Any], None]
#: (event, data, to): ``to`` is the session key the event is for, or None for everyone.
RoutedHandler = Callable[[str, Any, Optional[str]], None]


class EngineClient:
    """Connects to :class:`~backend.ipc.server.EngineServer` and stays connected."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 9999,
        want_frames: bool = True,
        reconnect_delay: float = 1.0,
    ) -> None:
        self.host = host
        self.port = port
        self.want_frames = want_frames
        self.reconnect_delay = reconnect_delay

        self._socket: Optional[socket.socket] = None
        self._socket_lock = threading.RLock()
        self._running = threading.Event()
        self._connected = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self._handlers: List[EventHandler] = []
        self._routed_handlers: List[RoutedHandler] = []
        #: request() calls waiting for their answer: request id -> {"done": Event, "result": ...}
        self._pending: Dict[str, Dict[str, Any]] = {}
        self._pending_lock = threading.Lock()
        self._latest_frame: Optional[bytes] = None
        self._frame_id = 0
        self._frame_cond = threading.Condition()
        self._last_error: Optional[str] = None

    # ------------------------------------------------------------------
    @property
    def is_connected(self) -> bool:
        return self._connected.is_set()

    def add_handler(self, handler: EventHandler) -> None:
        self._handlers.append(handler)

    def add_routed_handler(self, handler: RoutedHandler) -> None:
        """Like add_handler, but the handler also gets whom the event is for (Phase 9)."""
        self._routed_handlers.append(handler)

    def status(self) -> Dict[str, Any]:
        return {
            "connected": self.is_connected,
            "host": self.host,
            "port": self.port,
            "error": self._last_error,
            "framesReceived": self._frame_id,
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self) -> None:
        if self._running.is_set():
            return
        self._running.set()
        self._thread = threading.Thread(
            target=self._run, name="engine-client", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._running.clear()
        self._close_socket()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def _close_socket(self) -> None:
        with self._socket_lock:
            self._connected.clear()
            if self._socket is not None:
                try:
                    self._socket.close()
                except OSError:
                    pass
                self._socket = None

    # ------------------------------------------------------------------
    def _run(self) -> None:
        while self._running.is_set():
            if not self._connect():
                time.sleep(self.reconnect_delay)
                continue
            self._read_loop()
            self._close_socket()
            self._emit("engine:disconnected", {"reason": self._last_error})
            if self._running.is_set():
                time.sleep(self.reconnect_delay)

    def _connect(self) -> bool:
        try:
            sock = socket.create_connection((self.host, self.port), timeout=2.0)
        except OSError as exc:
            self._last_error = str(exc)
            return False

        sock.settimeout(1.0)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        with self._socket_lock:
            self._socket = sock
            self._connected.set()
        self._last_error = None
        log.info("Connected to engine at %s:%s", self.host, self.port)

        self.send("subscribe", {"frames": self.want_frames})
        self.send("sync", {})
        self._emit("engine:connected", self.status())
        return True

    def _read_loop(self) -> None:
        reader = MessageReader()
        while self._running.is_set():
            with self._socket_lock:
                sock = self._socket
            if sock is None:
                return
            try:
                chunk = sock.recv(262144)
            except socket.timeout:
                continue
            except OSError as exc:
                self._last_error = str(exc)
                return
            if not chunk:
                self._last_error = "Engine closed the connection"
                return

            try:
                for kind, payload in reader.feed(chunk):
                    if kind == KIND_FRAME:
                        self._store_frame(payload)
                    elif kind == KIND_JSON:
                        message = decode_json(payload)
                        if not isinstance(message, dict):
                            continue
                        event = str(message.get("event", ""))
                        if event == "ack":  # the answer to a request(): never shown to browsers
                            self._resolve(message.get("data") or {})
                            continue
                        to = message.get("to")
                        self._emit(event, message.get("data"), str(to) if to else None)
            except ProtocolError as exc:
                self._last_error = f"Protocol error: {exc}"
                return

    # ------------------------------------------------------------------
    # Outbound
    # ------------------------------------------------------------------
    def send(
        self,
        command: str,
        payload: Optional[Dict[str, Any]] = None,
        session: Optional[str] = None,
        user: Optional[Dict[str, Any]] = None,
        request_id: Optional[str] = None,
    ) -> bool:
        """Send a command to the engine. Returns False when disconnected.

        ``session`` and ``user`` say which visitor sent it (set by the web server from
        the visitor's token, never from what the browser claims)."""
        message: Dict[str, Any] = {"command": command, "payload": payload or {}}
        if session is not None:
            message["session"] = session
        if user is not None:
            message["user"] = user
        if request_id is not None:
            message["requestId"] = request_id
        with self._socket_lock:
            sock = self._socket
            if sock is None:
                return False
            try:
                sock.sendall(encode_json(message))
                return True
            except OSError as exc:
                self._last_error = str(exc)
                self._connected.clear()
                return False

    def request(
        self, command: str, payload: Optional[Dict[str, Any]] = None, timeout: float = 15.0
    ) -> Optional[Dict[str, Any]]:
        """Send a command and wait for the engine's answer. None = no answer in time."""
        request_id = uuid.uuid4().hex
        waiter: Dict[str, Any] = {"done": threading.Event(), "result": None}
        with self._pending_lock:
            self._pending[request_id] = waiter
        try:
            if not self.send(command, payload, request_id=request_id):
                return None
            if not waiter["done"].wait(timeout):
                return None
            result = waiter["result"]
            return result if isinstance(result, dict) else None
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)

    def _resolve(self, ack: Dict[str, Any]) -> None:
        with self._pending_lock:
            waiter = self._pending.get(str(ack.get("requestId")))
        if waiter is not None:
            waiter["result"] = ack.get("result")
            waiter["done"].set()

    # ------------------------------------------------------------------
    # Frames
    # ------------------------------------------------------------------
    def _store_frame(self, jpeg_bytes: bytes) -> None:
        with self._frame_cond:
            self._latest_frame = jpeg_bytes
            self._frame_id += 1
            self._frame_cond.notify_all()

    def latest_frame(self) -> Optional[bytes]:
        with self._frame_cond:
            return self._latest_frame

    def wait_for_frame(
        self, last_id: int = -1, timeout: float = 2.0
    ) -> tuple[Optional[bytes], int]:
        """Block until a frame newer than ``last_id`` arrives (MJPEG generator)."""
        with self._frame_cond:
            if self._frame_id <= last_id:
                self._frame_cond.wait(timeout)
            return self._latest_frame, self._frame_id

    # ------------------------------------------------------------------
    def _emit(self, event: str, data: Any, to: Optional[str] = None) -> None:
        for handler in list(self._handlers):
            try:
                handler(event, data)
            except Exception:  # pragma: no cover - a bad handler must not kill IPC
                log.exception("Engine event handler failed for %r", event)
        for routed in list(self._routed_handlers):
            try:
                routed(event, data, to)
            except Exception:  # pragma: no cover
                log.exception("Engine event handler failed for %r", event)
