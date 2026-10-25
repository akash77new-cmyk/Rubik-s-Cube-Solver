"""TCP server side of the engine socket.

Owns the listening socket, tracks connected subscribers and fans messages out to
all of them. Command messages arriving from a client are handed to a callback.

Frames are published on a *drop-if-slow* basis: if a subscriber's send buffer is
full the frame is skipped for that subscriber rather than blocking the capture
loop. Stale video is worse than dropped video.
"""

from __future__ import annotations

import logging
import socket
import threading
from typing import Any, Callable, Dict, List, Optional

from backend.ipc.protocol import (
    KIND_JSON,
    MessageReader,
    ProtocolError,
    decode_json,
    encode_frame,
    encode_json,
)

log = logging.getLogger(__name__)

CommandHandler = Callable[[Dict[str, Any], "ClientConnection"], None]


class ClientConnection:
    """One connected subscriber (normally the web server)."""

    def __init__(self, sock: socket.socket, address: tuple) -> None:
        self.socket = sock
        self.address = address
        self.wants_frames = False
        self._send_lock = threading.Lock()
        self._alive = True

    @property
    def alive(self) -> bool:
        return self._alive

    def send_raw(self, data: bytes) -> bool:
        if not self._alive:
            return False
        with self._send_lock:
            try:
                self.socket.sendall(data)
                return True
            except (OSError, socket.timeout):
                self._alive = False
                return False

    def send_json(self, payload: Dict[str, Any]) -> bool:
        return self.send_raw(encode_json(payload))

    def close(self) -> None:
        self._alive = False
        try:
            self.socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.socket.close()
        except OSError:
            pass


class EngineServer:
    """Accepts subscribers and broadcasts engine events to them."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 9999,
        on_command: Optional[CommandHandler] = None,
        on_connect: Optional[Callable[[ClientConnection], None]] = None,
    ) -> None:
        self.host = host
        self.port = port
        self.on_command = on_command
        self.on_connect = on_connect

        self._server: Optional[socket.socket] = None
        self._clients: List[ClientConnection] = []
        self._clients_lock = threading.RLock()
        self._running = threading.Event()
        self._accept_thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    @property
    def is_running(self) -> bool:
        return self._running.is_set()

    @property
    def client_count(self) -> int:
        with self._clients_lock:
            return len(self._clients)

    def start(self) -> None:
        if self.is_running:
            return
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((self.host, self.port))
        server.listen(8)
        server.settimeout(0.5)
        self._server = server
        self._running.set()
        self._accept_thread = threading.Thread(
            target=self._accept_loop, name="engine-accept", daemon=True
        )
        self._accept_thread.start()
        log.info("Engine socket listening on %s:%s", self.host, self.port)

    def stop(self) -> None:
        self._running.clear()
        if self._accept_thread and self._accept_thread.is_alive():
            self._accept_thread.join(timeout=2.0)
        with self._clients_lock:
            for client in self._clients:
                client.close()
            self._clients.clear()
        if self._server:
            try:
                self._server.close()
            except OSError:
                pass
            self._server = None

    # ------------------------------------------------------------------
    def _accept_loop(self) -> None:
        while self._running.is_set() and self._server is not None:
            try:
                sock, address = self._server.accept()
            except socket.timeout:
                continue
            except OSError:
                break

            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            client = ClientConnection(sock, address)
            with self._clients_lock:
                self._clients.append(client)
            log.info("Engine subscriber connected: %s", address)

            if self.on_connect:
                try:
                    self.on_connect(client)
                except Exception:
                    log.exception("on_connect handler failed")

            threading.Thread(
                target=self._client_loop,
                args=(client,),
                name=f"engine-client-{address[1]}",
                daemon=True,
            ).start()

    def _client_loop(self, client: ClientConnection) -> None:
        reader = MessageReader()
        client.socket.settimeout(1.0)
        try:
            while self._running.is_set() and client.alive:
                try:
                    chunk = client.socket.recv(65536)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if not chunk:
                    break
                try:
                    for kind, payload in reader.feed(chunk):
                        if kind != KIND_JSON:
                            continue
                        message = decode_json(payload)
                        if isinstance(message, dict) and self.on_command:
                            self.on_command(message, client)
                except ProtocolError:
                    log.warning("Dropping subscriber %s: bad framing", client.address)
                    break
                except Exception:
                    log.exception("Command handler failed")
        finally:
            client.close()
            with self._clients_lock:
                if client in self._clients:
                    self._clients.remove(client)
            log.info("Engine subscriber disconnected: %s", client.address)

    # ------------------------------------------------------------------
    # Broadcast
    # ------------------------------------------------------------------
    def broadcast(self, event: str, data: Any = None, to: Optional[str] = None) -> None:
        """Send a JSON event to every subscriber.

        ``to`` (Phase 9) names the visitor's session the event is for; the web server then
        passes it only to that visitor's browser tabs. None = for every visitor."""
        message: Dict[str, Any] = {"event": event, "data": data}
        if to is not None:
            message["to"] = to
        self._fanout(encode_json(message))

    def broadcast_frame(self, jpeg_bytes: bytes) -> None:
        """Send a JPEG frame to subscribers that asked for video."""
        payload = encode_frame(jpeg_bytes)
        with self._clients_lock:
            clients = [c for c in self._clients if c.wants_frames]
        for client in clients:
            client.send_raw(payload)

    def _fanout(self, payload: bytes) -> None:
        with self._clients_lock:
            clients = list(self._clients)
        dead = [client for client in clients if not client.send_raw(payload)]
        if dead:
            with self._clients_lock:
                for client in dead:
                    if client in self._clients:
                        self._clients.remove(client)
