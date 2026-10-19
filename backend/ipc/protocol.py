"""Length-prefixed message framing for the engine socket.

TCP is a byte stream with no message boundaries, so every message is framed::

    +--------+------------------+-----------------------+
    | kind   | payload length   | payload               |
    | 1 byte | 4 bytes, big-end | `length` bytes        |
    +--------+------------------+-----------------------+

Two kinds are used:

``J`` UTF-8 JSON - state updates, commands, telemetry.
``F`` raw JPEG   - camera frames, sent as bytes rather than base64 so the video
                   path costs no extra 33% bandwidth or encode/decode work.

The original prototype called ``sock.send(pickle.dumps(...))`` and read with a
fixed 4096-byte ``recv``, which silently truncated or merged messages and would
execute arbitrary code from the wire. This framing is both correct and safe.
"""

from __future__ import annotations

import json
import struct
from typing import Any, Iterator, Optional, Tuple

KIND_JSON = b"J"
KIND_FRAME = b"F"

_HEADER = struct.Struct("!cI")
HEADER_SIZE = _HEADER.size

#: Refuse absurd frames rather than allocating unbounded memory.
MAX_PAYLOAD = 16 * 1024 * 1024


def encode(kind: bytes, payload: bytes) -> bytes:
    if len(payload) > MAX_PAYLOAD:
        raise ValueError(f"Payload too large: {len(payload)} bytes")
    return _HEADER.pack(kind, len(payload)) + payload


def encode_json(payload: Any) -> bytes:
    return encode(KIND_JSON, json.dumps(payload, separators=(",", ":")).encode("utf-8"))


def encode_frame(jpeg_bytes: bytes) -> bytes:
    return encode(KIND_FRAME, jpeg_bytes)


class ProtocolError(Exception):
    """Malformed data on the wire."""


class MessageReader:
    """Incremental parser - feed it socket chunks, get whole messages out."""

    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, chunk: bytes) -> Iterator[Tuple[bytes, bytes]]:
        """Append ``chunk`` and yield every complete ``(kind, payload)``."""
        self._buffer.extend(chunk)
        while True:
            message = self._take()
            if message is None:
                return
            yield message

    def _take(self) -> Optional[Tuple[bytes, bytes]]:
        if len(self._buffer) < HEADER_SIZE:
            return None
        kind, length = _HEADER.unpack_from(self._buffer, 0)
        if length > MAX_PAYLOAD:
            raise ProtocolError(f"Declared payload of {length} bytes exceeds limit")
        end = HEADER_SIZE + length
        if len(self._buffer) < end:
            return None
        payload = bytes(self._buffer[HEADER_SIZE:end])
        del self._buffer[:end]
        return kind, payload

    def reset(self) -> None:
        self._buffer.clear()


def decode_json(payload: bytes) -> Any:
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError(f"Invalid JSON message: {exc}") from exc
