"""Socket-based inter-process communication between the vision engine and the web server.

The vision engine runs as its own OS process (it owns the camera and the solver)
and exposes a TCP server. The Flask/Socket.IO web server connects to it as a
client, forwards browser commands down the socket and relays engine events back
up to the browser. That keeps a blocking OpenCV capture loop completely off the
HTTP thread pool.

Wire format is defined in :mod:`backend.ipc.protocol`.
"""

from backend.ipc.client import EngineClient
from backend.ipc.protocol import (
    KIND_FRAME,
    KIND_JSON,
    MessageReader,
    encode_frame,
    encode_json,
)
from backend.ipc.server import EngineServer

__all__ = [
    "EngineClient",
    "EngineServer",
    "MessageReader",
    "encode_frame",
    "encode_json",
    "KIND_FRAME",
    "KIND_JSON",
]
