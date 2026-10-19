"""Threaded webcam capture.

Grabbing frames on a dedicated thread keeps the socket/HTTP layers responsive:
consumers always read the most recent frame instead of draining a backlog, which
is what makes the live view feel real-time rather than laggy.
"""

from __future__ import annotations

import platform
import threading
import time
from collections import deque
from typing import Deque, Dict, List, Optional, Tuple

import cv2
import numpy as np

#: DirectShow avoids the multi-second MSMF startup penalty on Windows.
_PREFERRED_BACKEND = cv2.CAP_DSHOW if platform.system() == "Windows" else cv2.CAP_ANY


def list_cameras(max_index: int = 5) -> List[Dict[str, object]]:
    """Probe camera indices and report which ones can deliver a frame."""
    found: List[Dict[str, object]] = []
    for index in range(max_index):
        capture = cv2.VideoCapture(index, _PREFERRED_BACKEND)
        try:
            if not capture.isOpened():
                continue
            ok, frame = capture.read()
            if not ok or frame is None:
                continue
            height, width = frame.shape[:2]
            found.append(
                {
                    "index": index,
                    "label": f"Camera {index}",
                    "width": int(width),
                    "height": int(height),
                }
            )
        finally:
            capture.release()
    return found


class CameraStream:
    """Owns a ``cv2.VideoCapture`` and publishes the latest frame."""

    def __init__(
        self,
        index: int = 0,
        width: int = 960,
        height: int = 720,
        target_fps: int = 30,
        mirror: bool = True,
    ) -> None:
        self.index = index
        self.width = width
        self.height = height
        self.target_fps = target_fps
        self.mirror = mirror

        self._capture: Optional[cv2.VideoCapture] = None
        self._thread: Optional[threading.Thread] = None
        self._running = threading.Event()
        self._frame: Optional[np.ndarray] = None
        self._frame_lock = threading.RLock()
        self._frame_available = threading.Condition(self._frame_lock)
        self._frame_id = 0
        self._timestamps: Deque[float] = deque(maxlen=60)
        self._error: Optional[str] = None
        self._started_at: Optional[float] = None
        self._frames_captured = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    @property
    def is_running(self) -> bool:
        return self._running.is_set()

    def start(self) -> bool:
        """Open the device and begin capturing. Returns success."""
        if self.is_running:
            return True

        capture = cv2.VideoCapture(self.index, _PREFERRED_BACKEND)
        if not capture.isOpened():
            capture.release()
            self._error = (
                f"Could not open camera {self.index}. "
                "Check the device index on the Settings page."
            )
            return False

        capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        capture.set(cv2.CAP_PROP_FPS, self.target_fps)
        # A 1-frame buffer keeps latency down on most drivers.
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        self._capture = capture
        self._error = None
        self._started_at = time.time()
        self._frames_captured = 0
        self._running.set()
        self._thread = threading.Thread(
            target=self._loop, name=f"camera-{self.index}", daemon=True
        )
        self._thread.start()
        return True

    def stop(self) -> None:
        self._running.clear()
        thread, self._thread = self._thread, None
        if thread and thread.is_alive():
            thread.join(timeout=2.0)
        if self._capture is not None:
            self._capture.release()
            self._capture = None
        with self._frame_lock:
            self._frame = None
            self._frame_available.notify_all()
        self._timestamps.clear()

    def restart(self, **overrides: object) -> bool:
        """Apply new device settings and reopen."""
        self.stop()
        for key, value in overrides.items():
            if hasattr(self, key) and value is not None:
                setattr(self, key, value)
        return self.start()

    # ------------------------------------------------------------------
    # Capture loop
    # ------------------------------------------------------------------
    def _loop(self) -> None:
        min_interval = 1.0 / max(self.target_fps, 1)
        while self._running.is_set() and self._capture is not None:
            loop_start = time.perf_counter()
            ok, frame = self._capture.read()
            if not ok or frame is None:
                self._error = "Camera returned no frame"
                time.sleep(0.05)
                continue

            if self.mirror:
                frame = cv2.flip(frame, 1)

            with self._frame_lock:
                self._frame = frame
                self._frame_id += 1
                self._frames_captured += 1
                self._timestamps.append(time.perf_counter())
                self._frame_available.notify_all()

            # Pace the loop so we do not spin faster than the requested FPS.
            elapsed = time.perf_counter() - loop_start
            if elapsed < min_interval:
                time.sleep(min_interval - elapsed)

    # ------------------------------------------------------------------
    # Consumers
    # ------------------------------------------------------------------
    def read(self) -> Tuple[Optional[np.ndarray], int]:
        """Latest frame (a copy) and its monotonically increasing id."""
        with self._frame_lock:
            if self._frame is None:
                return None, self._frame_id
            return self._frame.copy(), self._frame_id

    def wait_for_frame(
        self, last_id: int = -1, timeout: float = 1.0
    ) -> Tuple[Optional[np.ndarray], int]:
        """Block until a frame newer than ``last_id`` arrives."""
        with self._frame_available:
            if self._frame_id <= last_id:
                self._frame_available.wait(timeout)
            if self._frame is None:
                return None, self._frame_id
            return self._frame.copy(), self._frame_id

    # ------------------------------------------------------------------
    # Telemetry
    # ------------------------------------------------------------------
    @property
    def fps(self) -> float:
        with self._frame_lock:
            stamps = list(self._timestamps)
        if len(stamps) < 2:
            return 0.0
        span = stamps[-1] - stamps[0]
        return round((len(stamps) - 1) / span, 1) if span > 0 else 0.0

    def status(self) -> Dict[str, object]:
        with self._frame_lock:
            frame = self._frame
            resolution = (
                [int(frame.shape[1]), int(frame.shape[0])] if frame is not None else None
            )
        return {
            "running": self.is_running,
            "index": self.index,
            "requestedResolution": [self.width, self.height],
            "resolution": resolution,
            "fps": self.fps,
            "targetFps": self.target_fps,
            "mirror": self.mirror,
            "framesCaptured": self._frames_captured,
            "uptimeSeconds": (
                round(time.time() - self._started_at, 1) if self._started_at and self.is_running else 0
            ),
            "error": self._error,
        }
