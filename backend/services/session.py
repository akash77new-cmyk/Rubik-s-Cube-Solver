"""The solving session - the state machine every UI page mirrors.

Owns the camera loop, the scan progress, the generated solution and its
playback. It is deliberately transport-agnostic: it publishes events through two
callbacks (``publish_event`` / ``publish_frame``) which the engine process wires
to the socket server. That is what keeps the vision pipeline testable without a
browser attached.

Lifecycle::

    idle --(scan.start)--> scanning --(6 faces)--> scanned
         --(solve.run)--> solving --> solution --(playback)--> complete
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Sequence

import cv2
import numpy as np

from backend.config import Settings, SettingsStore
from backend.core.color import ColorProfile, ProfileStore
from backend.core.cube import (
    COLOR_CODES,
    COLOR_NAMES,
    DEFAULT_SCHEME,
    FACE_ORDER,
    CubeState,
    InvalidCubeError,
    random_scramble,
)
from backend.core.moves import FACE_NAMES, Move, expand_for_physical_turns, parse_sequence
from backend.core.scanning import (
    IDENTITY_MAP,
    MIRROR_MAP,
    SCAN_ORDER,
    SCAN_STEPS,
    STEP_BY_FACE,
    banner_title,
    face_for_center,
    reorder,
    repair_orientation,
)
from backend.core.solver import (
    SolveFailedError,
    SolverEngine,
    SolverUnavailableError,
    Solution,
)
from backend.services.analytics import AnalyticsStore, SolveRecord
from backend.services.dataset import LIGHTING_OPTIONS, DatasetStore, build_scan_record
from backend.services.logbus import LogBus
from backend.vision.camera import CameraStream, list_cameras
from backend.vision.detector import CROP_SIZE, DetectionResult, FaceDetector
from backend.vision.overlay import OverlayRenderer, encode_jpeg

PublishEvent = Callable[[str, Any], None]
PublishFrame = Callable[[bytes], None]


class SolveSession:
    """Coordinates camera, detection, solving, playback and analytics."""

    DETECTION_EVENT_HZ = 12.0
    CALIBRATION_EVENT_HZ = 6.0
    #: Camera counters change every frame but nothing structural does, so they
    #: ride a slow telemetry channel instead of a full state broadcast.
    TELEMETRY_HZ = 2.0

    def __init__(
        self,
        settings: SettingsStore,
        profiles: ProfileStore,
        solver: SolverEngine,
        logs: LogBus,
        analytics: AnalyticsStore,
        publish_event: PublishEvent,
        publish_frame: PublishFrame,
        dataset: Optional[DatasetStore] = None,
    ) -> None:
        self._settings = settings
        self._profiles = profiles
        self._solver = solver
        self._logs = logs
        self._analytics = analytics
        self._publish_event = publish_event
        self._publish_frame = publish_frame
        #: None when dataset collection is off (production).
        self._dataset = dataset

        config = settings.current
        self.camera = CameraStream(
            index=config.camera_index,
            width=config.frame_width,
            height=config.frame_height,
            target_fps=config.target_fps,
            mirror=config.mirror_camera,
        )
        self.detector = FaceDetector(
            profile=profiles.get(config.active_profile),
            spacing=config.grid_spacing,
            sample_radius=config.sample_radius,
            offset_y=config.grid_offset_y,
        )
        self.overlay = OverlayRenderer(style=config.arrow_style)

        self._lock = threading.RLock()
        self._mode = "idle"
        self._scanned: Dict[str, Dict[str, Any]] = {}
        #: Sticker crops of the faces captured by the camera (face -> 9 images).
        #: Kept apart from _scanned because images are never broadcast. Cleared
        #: whenever the cube stops matching what the camera saw.
        self._scan_crops: Dict[str, List[np.ndarray]] = {}
        #: True once the current scan has been saved to the dataset.
        self._dataset_saved = False
        self._face_index = 0
        self._auto_capture = True
        self._cube: Optional[CubeState] = None
        self._cube_source = "none"
        self._solution: Optional[Solution] = None
        self._solve_error: Optional[str] = None
        self._solving = False
        self._latest_detection: Optional[DetectionResult] = None
        #: True if the latest frame was mirrored (a selfie-style camera preview).
        self._latest_mirrored = False
        #: Auto-capture hold timer (frame thread only): the face being held still, the
        #: colours it showed, when that started, and how much of the hold time is done.
        #: ``_clock`` is a monotonic clock that tests can replace with a fake one.
        self._clock: Callable[[], float] = time.monotonic
        self._hold_face: Optional[str] = None
        self._hold_colors: Optional[List[str]] = None
        self._hold_since = 0.0
        self._hold_progress = 0.0

        self._playback = {"index": 0, "playing": False, "completed": False}
        self._playback_thread: Optional[threading.Thread] = None
        self._playback_stop = threading.Event()

        self._calibration: Dict[str, Any] = {
            "active": False,
            "target": "R",
            "samples": [],
            "draft": None,
        }

        self._scan_started_at: Optional[float] = None
        self._execution_started_at: Optional[float] = None
        self._solve_id: Optional[str] = None

        self._loop_thread: Optional[threading.Thread] = None
        self._loop_stop = threading.Event()
        self._last_detection_emit = 0.0
        self._last_calibration_emit = 0.0
        self._last_telemetry_emit = 0.0

        solver.add_listener(lambda status: self._publish_event("solver", status))

    # ==================================================================
    # Lifecycle
    # ==================================================================
    def start(self) -> None:
        """Start the frame-processing loop (camera itself starts on demand)."""
        if self._loop_thread and self._loop_thread.is_alive():
            return
        self._loop_stop.clear()
        self._loop_thread = threading.Thread(
            target=self._frame_loop, name="session-loop", daemon=True
        )
        self._loop_thread.start()

    def shutdown(self) -> None:
        self._loop_stop.set()
        self._playback_stop.set()
        if self._loop_thread and self._loop_thread.is_alive():
            self._loop_thread.join(timeout=2.0)
        self.camera.stop()

    # ==================================================================
    # Frame loop
    # ==================================================================
    def _frame_loop(self) -> None:
        last_id = -1
        while not self._loop_stop.is_set():
            if not self.camera.is_running:
                time.sleep(0.1)
                continue

            frame, last_id = self.camera.wait_for_frame(last_id, timeout=0.5)
            if frame is None:
                continue

            try:
                self._process_frame(frame, mirrored=self.camera.mirror)
            except Exception as exc:  # never let one bad frame kill the loop
                self._logs.error(f"Frame processing failed: {exc}", source="camera")
                time.sleep(0.05)

    def _process_frame(self, frame: np.ndarray, mirrored: bool = False) -> None:
        """Detect, auto-capture, draw and publish one frame.

        ``mirrored`` says the frame was flipped left-right for display. Detection runs
        on the frame as shown (so the overlay lines up), and capture_face() undoes the
        flip, so each face is stored the way the camera really sees it.
        """
        settings = self._settings.current
        now = time.time()

        if now - self._last_telemetry_emit >= 1.0 / self.TELEMETRY_HZ:
            self._last_telemetry_emit = now
            self._publish_event(
                "telemetry", {"camera": self.camera.status(), "mode": self._mode}
            )

        if self._calibration["active"]:
            rendered = self._render_calibration(frame, settings, now)
            self._publish_encoded(rendered)
            return

        result = self.detector.detect(frame)
        with self._lock:
            self._latest_detection = result
            self._latest_mirrored = mirrored
        self._analytics.note_detection_confidence(result.mean_confidence)

        self._maybe_auto_capture(result, settings)

        rendered = self._render_scene(frame, result, settings)
        self._publish_encoded(rendered)

        if now - self._last_detection_emit >= 1.0 / self.DETECTION_EVENT_HZ:
            self._last_detection_emit = now
            self._publish_event(
                "detection",
                {
                    **result.to_dict(),
                    "fps": self.camera.fps,
                    "face": self.current_face,
                    # Auto-capture hold timer: which face is being held, and how far.
                    "holdFace": self._hold_face,
                    "hold": round(self._hold_progress, 3),
                },
            )

    def _render_scene(
        self, frame: np.ndarray, result: DetectionResult, settings: Settings
    ) -> np.ndarray:
        """Compose the HUD appropriate to the current mode."""
        move = self.current_move
        if self._mode == "execute" and move is not None:
            self.overlay.draw_move(
                frame,
                move,
                index=self._playback["index"],
                total=len(self._solution.moves) if self._solution else 0,
                turn_back=move.face == "B",
            )
        else:
            self.overlay.draw_detection(
                frame,
                result,
                show_grid=settings.show_grid,
                show_labels=settings.show_labels,
                show_bounding_box=settings.show_bounding_box,
                show_confidence=settings.show_confidence,
                min_confidence=settings.min_confidence,
            )
            if self._mode == "scan":
                self.overlay.draw_scan_banner(
                    frame,
                    self.current_face,
                    list(self._scanned),
                    result,
                    title=banner_title(self.current_face),
                )

        self.overlay.draw_hud(frame, self.camera.fps, self._mode)
        return frame

    def _publish_encoded(self, frame: np.ndarray) -> None:
        jpeg = encode_jpeg(frame, quality=80)
        if jpeg:
            self._publish_frame(jpeg)

    # ------------------------------------------------------------------
    def _render_calibration(
        self, frame: np.ndarray, settings: Settings, now: float
    ) -> np.ndarray:
        """Live mask preview for the HSV calibration page."""
        profile = self._calibration_profile()
        target = self._calibration["target"]
        rng = profile.ranges.get(target)

        hsv = cv2.cvtColor(cv2.bilateralFilter(frame, 7, 60, 60), cv2.COLOR_BGR2HSV)
        if rng is None:
            mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
        elif rng.wrap_hue:
            lower = cv2.inRange(
                hsv,
                np.array([rng.h_min, rng.s_min, rng.v_min]),
                np.array([179, rng.s_max, rng.v_max]),
            )
            upper = cv2.inRange(
                hsv,
                np.array([0, rng.s_min, rng.v_min]),
                np.array([rng.h_max, rng.s_max, rng.v_max]),
            )
            mask = cv2.bitwise_or(lower, upper)
        else:
            mask = cv2.inRange(
                hsv,
                np.array([rng.h_min, rng.s_min, rng.v_min]),
                np.array([rng.h_max, rng.s_max, rng.v_max]),
            )

        # Show the original dimmed, with matching pixels punched through at full
        # brightness and tinted - far more readable than a raw binary mask.
        dimmed = (frame * 0.25).astype(np.uint8)
        highlighted = cv2.bitwise_and(frame, frame, mask=mask)
        rendered = cv2.add(dimmed, highlighted)
        edges = cv2.Canny(mask, 50, 150)
        rendered[edges > 0] = (255, 255, 255)

        roi, roi_rect = self._calibration_roi(hsv)
        cv2.rectangle(
            rendered,
            (roi_rect[0], roi_rect[1]),
            (roi_rect[0] + roi_rect[2], roi_rect[1] + roi_rect[3]),
            (245, 158, 66),
            2,
            cv2.LINE_AA,
        )

        coverage = float(np.count_nonzero(mask)) / float(mask.size or 1)
        if now - self._last_calibration_emit >= 1.0 / self.CALIBRATION_EVENT_HZ:
            self._last_calibration_emit = now
            self._publish_event(
                "calibration",
                {
                    **self.calibration_state(),
                    "sample": self._roi_stats(roi),
                    "coverage": round(coverage, 4),
                    "histogram": self._hue_histogram(hsv),
                },
            )
        return rendered

    def _calibration_roi(self, hsv: np.ndarray):
        height, width = hsv.shape[:2]
        size = max(30, min(width, height) // 8)
        x, y = (width - size) // 2, (height - size) // 2
        return hsv[y : y + size, x : x + size], (x, y, size, size)

    @staticmethod
    def _roi_stats(roi: np.ndarray) -> Dict[str, Any]:
        if roi.size == 0:
            return {"h": 0, "s": 0, "v": 0}
        flat = roi.reshape(-1, 3)
        return {
            "h": int(np.median(flat[:, 0])),
            "s": int(np.median(flat[:, 1])),
            "v": int(np.median(flat[:, 2])),
        }

    @staticmethod
    def _hue_histogram(hsv: np.ndarray, bins: int = 60) -> List[int]:
        # Ignore near-grey pixels so the histogram reflects real sticker hues.
        mask = (hsv[:, :, 1] > 60).astype(np.uint8)
        hist = cv2.calcHist([hsv], [0], mask, [bins], [0, 180]).flatten()
        peak = float(hist.max()) or 1.0
        return [int(round(value / peak * 100)) for value in hist]

    def _calibration_profile(self) -> ColorProfile:
        draft = self._calibration.get("draft")
        if isinstance(draft, ColorProfile):
            return draft
        return self.detector.profile

    # ==================================================================
    # Scanning
    # ==================================================================
    @property
    def current_face(self) -> Optional[str]:
        """The face the guide asks for next: the face picked for a re-scan, if any,
        otherwise the first face in guide order that hasn't been captured."""
        remaining = [face for face in SCAN_ORDER if face not in self._scanned]
        if not remaining:
            return None
        preferred = SCAN_ORDER[self._face_index % len(SCAN_ORDER)]
        return preferred if preferred in remaining else remaining[0]

    def _maybe_auto_capture(self, result: DetectionResult, settings: Settings) -> None:
        face = self._auto_capture_candidate(result, settings)
        if face is None:
            self._hold_face, self._hold_colors, self._hold_progress = None, None, 0.0
            return
        # Wait until the same nine colours have been held still for the hold time, so
        # a side is not grabbed while the cube is still being turned into place. Any
        # change in the read (the cube moved) starts the wait again.
        now = self._clock()
        if face != self._hold_face or result.colors != self._hold_colors:
            self._hold_face, self._hold_colors, self._hold_since = face, list(result.colors), now
        hold_seconds = max(0, settings.auto_capture_hold_ms) / 1000.0
        held = now - self._hold_since
        self._hold_progress = min(1.0, held / hold_seconds) if hold_seconds else 1.0
        if held >= hold_seconds:
            self._hold_face, self._hold_colors, self._hold_progress = None, None, 0.0
            self.capture_face(face, auto=True)

    def _auto_capture_candidate(
        self, result: DetectionResult, settings: Settings
    ) -> Optional[str]:
        """The face auto-capture may take from this frame, or None."""
        if self._mode != "scan" or not self._auto_capture:
            return None
        if not result.stable or len(result.readings) != 9:
            return None
        # The centre is left out of the confidence check: it often carries a logo.
        outer = [reading.confidence for reading in result.readings if reading.index != 4]
        if min(outer) < settings.min_confidence:
            return None
        # Each face is recognised by its centre colour (centres never move). A face
        # still in front of the camera after its capture is simply ignored.
        face = face_for_center(result.readings[4].color)
        if face is None or face in self._scanned:
            return None
        return face

    def _face_to_capture(self, result: Optional[DetectionResult]) -> Optional[str]:
        """The face whose centre is visible, if it still needs scanning, else the
        guide's next face (e.g. when a logo hides the centre colour)."""
        if result is not None and len(result.readings) == 9:
            by_center = face_for_center(result.readings[4].color)
            if by_center is not None and by_center not in self._scanned:
                return by_center
        return self.current_face

    def start_scan(self, open_camera: bool = True) -> Dict[str, Any]:
        """Enter scan mode. ``open_camera=False`` lets tests feed frames themselves."""
        with self._lock:
            self._mode = "scan"
            self._scan_started_at = time.time()
        self.detector.reset_stability()
        if open_camera and not self.camera.is_running:
            self.start_camera()
        self._logs.info("Scanning started", source="scan")
        self._broadcast_state()
        return {"ok": True}

    def capture_face(self, face: Optional[str] = None, auto: bool = False) -> Dict[str, Any]:
        with self._lock:
            result = self._latest_detection
            target = face or self._face_to_capture(result)
            if target is None:
                return {"ok": False, "error": "All six faces are already captured"}
            if result is None or len(result.readings) != 9:
                return {"ok": False, "error": "No detection available yet"}

            # Undo a mirrored preview, so the face is stored as the camera sees it.
            index_map = MIRROR_MAP if self._latest_mirrored else IDENTITY_MAP
            colors = reorder(result.colors, index_map)
            colors[4] = DEFAULT_SCHEME[target]  # a face's centre colour is its identity
            stickers = []
            for position, reading in enumerate(reorder(result.readings, index_map)):
                sticker = reading.to_dict()
                sticker.update(index=position, row=position // 3, col=position % 3)
                stickers.append(sticker)

            self._scanned[target] = {
                # "colors" is the face's current colours: corrections update it.
                "colors": colors,
                "confidence": result.mean_confidence,
                "minConfidence": result.min_confidence,
                "timestamp": time.time(),
                "auto": auto,
                # What the detector saw, per sticker: colour, confidence, the best
                # three colours and whether it was unsure. Never changed afterwards.
                "stickers": stickers,
            }
            self._scan_crops[target] = reorder(result.crops, index_map)
            self._face_index = 0  # back to "first face not yet captured"
            self.detector.reset_stability()

        self._logs.success(
            f"{COLOR_NAMES[DEFAULT_SCHEME[target]]} face ({target}) captured "
            f"({'auto' if auto else 'manual'}) - {''.join(colors)} @ {result.mean_confidence:.2f}",
            source="scan",
        )
        self._publish_event(
            "scan:face",
            {
                "face": target,
                "colors": colors,
                "confidence": result.mean_confidence,
                "scanned": list(self._scanned),
                "auto": auto,
            },
        )

        if len(self._scanned) == 6:
            self._finish_scan()
        self._broadcast_state()
        return {"ok": True, "face": target, "colors": colors}

    def _finish_scan(self) -> None:
        try:
            cube = CubeState({f: self._scanned[f]["colors"] for f in FACE_ORDER})
        except InvalidCubeError as exc:
            self._logs.error(f"Scan produced an invalid cube: {exc}", source="scan")
            return

        validation = cube.validate()
        if not validation.ok:
            fix = repair_orientation({f: self._scanned[f]["colors"] for f in FACE_ORDER})
            if fix is not None:
                with self._lock:
                    for face in FACE_ORDER:
                        index_map = fix.index_map(face)
                        if index_map != IDENTITY_MAP:
                            self._reorient_face(face, index_map)
                    cube = CubeState({f: self._scanned[f]["colors"] for f in FACE_ORDER})
                validation = cube.validate()
                self._logs.success(fix.describe(), source="scan")
                self._publish_event("scan:repaired", {"message": fix.describe()})
        with self._lock:
            self._cube = cube
            self._cube_source = "scan"
            self._mode = "scanned"
        if validation.ok:
            self._logs.success(
                "All six faces captured - cube state is valid", source="scan"
            )
        else:
            self._logs.warn(
                "Scan complete but the cube is invalid: " + "; ".join(validation.errors),
                source="scan",
            )
        self._publish_event(
            "scan:complete",
            {"validation": validation.to_dict(), "cube": cube.to_dict()},
        )

    def _reorient_face(self, face: str, index_map: Sequence[int]) -> None:
        """Re-order one captured face's colours, readings and crops together, so the
        labels and images saved to the dataset stay matched (caller holds the lock)."""
        entry = self._scanned[face]
        entry["colors"] = reorder(entry["colors"], index_map)
        stickers = reorder(entry.get("stickers", []), index_map) if entry.get("stickers") else []
        for position, sticker in enumerate(stickers):
            sticker.update(index=position, row=position // 3, col=position % 3)
        if stickers:
            entry["stickers"] = stickers
        if face in self._scan_crops:
            self._scan_crops[face] = reorder(self._scan_crops[face], index_map)

    def reset_scan(self) -> None:
        with self._lock:
            self._scanned.clear()
            self._scan_crops.clear()
            self._dataset_saved = False
            self._face_index = 0
            self._cube = None
            self._cube_source = "none"
            self._solution = None
            self._solve_error = None
            self._playback = {"index": 0, "playing": False, "completed": False}
            self._mode = "idle"
            self._scan_started_at = None
        self.detector.reset_stability()
        self._logs.info("Scan reset", source="scan")
        self._broadcast_state()

    # ==================================================================
    # Solving
    # ==================================================================
    @property
    def current_move(self) -> Optional[Move]:
        solution = self._solution
        if not solution or not solution.moves:
            return None
        index = self._playback["index"]
        if 0 <= index < len(solution.moves):
            return solution.moves[index]
        return None

    def solve(self) -> Dict[str, Any]:
        with self._lock:
            if self._solving:
                return {"ok": False, "error": "A solve is already running"}
            cube = self._cube
            if cube is None:
                return {"ok": False, "error": "Scan or scramble a cube first"}
            self._solving = True
            self._solve_error = None
            self._mode = "solving"

        self._logs.info("Kociemba two-phase search started...", source="solver")
        self._broadcast_state()
        threading.Thread(
            target=self._solve_worker, args=(cube,), name="solve", daemon=True
        ).start()
        return {"ok": True}

    def _solve_worker(self, cube: CubeState) -> None:
        try:
            solution = self._solver.solve(cube, wait_for_warmup=None)
        except (SolveFailedError, SolverUnavailableError) as exc:
            with self._lock:
                self._solving = False
                self._solve_error = str(exc)
                self._mode = "scanned" if self._cube else "idle"
            self._logs.error(f"Solve failed: {exc}", source="solver")
            self._publish_event("solve:error", {"error": str(exc)})
            self._broadcast_state()
            return

        with self._lock:
            self._solving = False
            self._solution = solution
            self._solve_id = uuid.uuid4().hex[:10]
            self._playback = {"index": 0, "playing": False, "completed": False}
            self._mode = "solution"
            self._execution_started_at = time.time()

        self._logs.success(
            f"Solution found: {solution.move_count} moves in "
            f"{solution.elapsed_ms:.1f} ms via {solution.backend}",
            source="solver",
        )
        self._publish_event("solve:complete", solution.to_dict())
        self._broadcast_state()

    # ==================================================================
    # Playback
    # ==================================================================
    def _set_index(self, index: int) -> None:
        solution = self._solution
        total = len(solution.moves) if solution else 0
        with self._lock:
            self._playback["index"] = max(0, min(index, max(total, 0)))
            self._playback["completed"] = total > 0 and self._playback["index"] >= total
        if self._playback["completed"]:
            self._on_playback_complete()

    def playback_command(self, action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        solution = self._solution
        if solution is None:
            return {"ok": False, "error": "No solution to play"}
        total = len(solution.moves)

        if action == "next":
            index = self._playback["index"]
            if index < total:
                self._log_move(solution.moves[index], index)
            self._set_index(index + 1)
        elif action == "prev":
            self._set_index(self._playback["index"] - 1)
        elif action == "seek":
            self._set_index(int(payload.get("index", 0)))
        elif action == "restart":
            with self._lock:
                self._playback = {"index": 0, "playing": False, "completed": False}
                self._execution_started_at = time.time()
            self._stop_autoplay()
        elif action == "play":
            self._start_autoplay()
        elif action == "pause":
            self._stop_autoplay()
        elif action == "execute":
            # Physical-guidance mode: arrows are drawn over the camera feed.
            with self._lock:
                self._mode = "execute"
        elif action == "review":
            with self._lock:
                self._mode = "solution"
        else:
            return {"ok": False, "error": f"Unknown playback action: {action}"}

        self._publish_event("playback", self.playback_state())
        self._broadcast_state()
        return {"ok": True}

    def _log_move(self, move: Move, index: int) -> None:
        self._logs.info(
            f"Move {index + 1}: {move.notation} ({move.label})", source="playback"
        )

    def _start_autoplay(self) -> None:
        if self._playback_thread and self._playback_thread.is_alive():
            return
        with self._lock:
            self._playback["playing"] = True
        self._playback_stop.clear()
        self._playback_thread = threading.Thread(
            target=self._autoplay_loop, name="autoplay", daemon=True
        )
        self._playback_thread.start()

    def _stop_autoplay(self) -> None:
        self._playback_stop.set()
        with self._lock:
            self._playback["playing"] = False

    def _autoplay_loop(self) -> None:
        while not self._playback_stop.is_set():
            settings = self._settings.current
            interval = settings.autoplay_interval_ms / 1000.0
            interval = max(0.08, interval / max(settings.animation_speed, 0.1))
            if self._playback_stop.wait(interval):
                break

            solution = self._solution
            if solution is None:
                break
            index = self._playback["index"]
            if index >= len(solution.moves):
                break
            self._log_move(solution.moves[index], index)
            self._set_index(index + 1)
            self._publish_event("playback", self.playback_state())
            self._broadcast_state()

        with self._lock:
            self._playback["playing"] = False
        self._publish_event("playback", self.playback_state())

    def _on_playback_complete(self) -> None:
        solution = self._solution
        if solution is None or self._solve_id is None:
            return
        self._stop_autoplay()

        finished = time.time()
        record = SolveRecord(
            id=self._solve_id,
            started_at=self._execution_started_at or finished,
            finished_at=finished,
            move_count=solution.move_count,
            quarter_turns=solution.quarter_turn_count,
            solve_ms=solution.elapsed_ms,
            scan_seconds=round(
                (self._execution_started_at or finished) - (self._scan_started_at or finished),
                1,
            ),
            execution_seconds=round(finished - (self._execution_started_at or finished), 1),
            backend=solution.backend,
            notation=solution.notation,
            face_distribution=solution.to_dict()["faceDistribution"],  # type: ignore[index]
            turn_distribution=solution.to_dict()["turnDistribution"],  # type: ignore[index]
            detection_confidence=self._analytics.average_confidence,
            source=self._cube_source,
        )
        self._solve_id = None
        self._analytics.record(record)
        with self._lock:
            self._mode = "complete"
        self._logs.success(
            f"Cube solved - {record.move_count} moves in {record.execution_seconds:.0f}s",
            source="playback",
        )
        self._publish_event("solve:finished", record.to_dict())
        self._publish_event("analytics", self._analytics.summary())

    # ==================================================================
    # Cube manipulation (works with no camera at all - great for demos)
    # ==================================================================
    def scramble(self, length: int = 22) -> Dict[str, Any]:
        moves = random_scramble(length)
        cube = CubeState.solved().apply_sequence(moves)
        with self._lock:
            self._cube = cube
            self._cube_source = "scramble"
            self._solution = None
            self._solve_error = None
            self._playback = {"index": 0, "playing": False, "completed": False}
            self._mode = "scanned"
            self._scanned = {
                face: {
                    "colors": cube.face(face),
                    "confidence": 1.0,
                    "minConfidence": 1.0,
                    "timestamp": time.time(),
                    "auto": False,
                }
                for face in FACE_ORDER
            }
            self._scan_crops.clear()  # the cube no longer matches the camera images
            self._face_index = len(FACE_ORDER)
            self._scan_started_at = time.time()
        self._logs.info(
            f"Generated a {len(moves)}-move scramble: "
            + " ".join(m.notation for m in moves),
            source="cube",
        )
        self._broadcast_state()
        return {"ok": True, "scramble": " ".join(m.notation for m in moves)}

    def reset_cube(self) -> Dict[str, Any]:
        cube = CubeState.solved()
        with self._lock:
            self._cube = cube
            self._cube_source = "manual"
            self._solution = None
            self._playback = {"index": 0, "playing": False, "completed": False}
            self._mode = "scanned"
            self._scanned = {
                face: {
                    "colors": cube.face(face),
                    "confidence": 1.0,
                    "minConfidence": 1.0,
                    "timestamp": time.time(),
                    "auto": False,
                }
                for face in FACE_ORDER
            }
            self._scan_crops.clear()  # the cube no longer matches the camera images
        self._logs.info("Cube reset to solved", source="cube")
        self._broadcast_state()
        return {"ok": True}

    def apply_moves(self, notation: str) -> Dict[str, Any]:
        """Apply a manual move sequence to the working cube (move simulation)."""
        with self._lock:
            cube = self._cube or CubeState.solved()
        try:
            moves = parse_sequence(notation)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        cube = cube.apply_sequence(moves)
        with self._lock:
            self._cube = cube
            self._cube_source = self._cube_source if self._cube_source != "none" else "manual"
            self._solution = None
            self._scanned = {
                face: {
                    "colors": cube.face(face),
                    "confidence": 1.0,
                    "minConfidence": 1.0,
                    "timestamp": time.time(),
                    "auto": False,
                }
                for face in FACE_ORDER
            }
            self._scan_crops.clear()  # the cube no longer matches the camera images
        self._logs.info(f"Applied moves: {notation}", source="cube")
        self._broadcast_state()
        return {"ok": True, "cube": cube.to_dict()}

    def set_sticker(self, face: str, index: int, color: str) -> Dict[str, Any]:
        """Manual correction from the Cube Viewer page."""
        if face not in FACE_ORDER or not 0 <= index < 9 or color not in COLOR_CODES:
            return {"ok": False, "error": "Invalid sticker reference"}
        with self._lock:
            cube = self._cube or CubeState.solved()
            facelets = cube.facelets
            facelets[face][index] = color
            self._cube = CubeState(facelets)
            self._cube_source = "manual"
            self._solution = None
            entry = self._scanned.setdefault(
                face,
                {"colors": facelets[face], "confidence": 1.0, "minConfidence": 1.0,
                 "timestamp": time.time(), "auto": False},
            )
            entry["colors"] = facelets[face]
        self._broadcast_state()
        return {"ok": True}

    # ==================================================================
    # Dataset (training data for the Phase 11 colour classifier)
    # ==================================================================
    def _dataset_blocker(self) -> Optional[str]:
        """Why the current cube can't be saved to the dataset, or None if it can."""
        if self._dataset is None:
            return "Dataset collection is turned off on this server."
        if self._dataset_saved:
            return "This scan is already saved. Reset and scan the cube again."
        if any(len(self._scan_crops.get(face, [])) != 9 for face in FACE_ORDER):
            return (
                "Scan all six faces with the camera first. Turning, scrambling or "
                "resetting the cube clears the scan."
            )
        if self._cube is None or not self._cube.validate().ok:
            return "Fix the problems first. Only a valid cube can be saved."
        return None

    def dataset_state(self) -> Dict[str, Any]:
        with self._lock:
            blocker = self._dataset_blocker()
            saved = self._dataset_saved
        return {
            "enabled": self._dataset is not None,
            "canSave": blocker is None,
            "reason": blocker,
            "saved": saved,
            "lightingOptions": [
                {"value": key, "label": label} for key, label in LIGHTING_OPTIONS.items()
            ],
            "stats": self._dataset.stats() if self._dataset is not None else None,
        }

    def save_to_dataset(self, lighting: str) -> Dict[str, Any]:
        """Save the confirmed scan: 54 sticker crops labelled with the cube's colours."""
        if lighting not in LIGHTING_OPTIONS:
            return {"ok": False, "error": "Pick the lighting for this scan first."}
        with self._lock:
            blocker = self._dataset_blocker()
            if blocker is not None:
                return {"ok": False, "error": blocker}
            assert self._cube is not None and self._dataset is not None  # checked above
            labels = {face: self._cube.face(face) for face in FACE_ORDER}
            readings = {face: list(self._scanned[face]["stickers"]) for face in FACE_ORDER}
            crops = {face: list(self._scan_crops[face]) for face in FACE_ORDER}
            settings = self._settings.current
            dataset = self._dataset

        record = build_scan_record(
            lighting=lighting,
            labels=labels,
            readings=readings,
            profile=settings.active_profile,
            camera={
                "index": settings.camera_index,
                "resolution": self.camera.status().get("resolution"),
                "mirror": settings.mirror_camera,
            },
            detector={
                "spacing": self.detector.spacing,
                "sampleRadius": self.detector.sample_radius,
                "cropSize": CROP_SIZE,
            },
        )
        try:
            scan_id = dataset.save(record, crops)
        except OSError as exc:
            self._logs.error(f"Could not save the scan to the dataset: {exc}", source="dataset")
            return {"ok": False, "error": f"Could not save: {exc}"}

        with self._lock:
            self._dataset_saved = True
        corrected = record["counts"]["corrected"]
        self._logs.success(
            f"Saved scan {scan_id} to the dataset: 54 stickers, {corrected} corrected",
            source="dataset",
        )
        self._publish_event(
            "dataset:saved", {"id": scan_id, "corrected": corrected, "stats": dataset.stats()}
        )
        self._broadcast_state()
        return {"ok": True, "id": scan_id, "corrected": corrected}

    # ==================================================================
    # Calibration
    # ==================================================================
    def calibration_state(self) -> Dict[str, Any]:
        profile = self._calibration_profile()
        return {
            "active": self._calibration["active"],
            "target": self._calibration["target"],
            "sampleCount": len(self._calibration["samples"]),
            "profileName": profile.name,
            "builtin": profile.builtin,
            "ranges": {code: rng.to_dict() for code, rng in profile.ranges.items()},
            "colors": [{"code": c, "name": COLOR_NAMES[c]} for c in COLOR_CODES],
            "availableProfiles": self._profiles.names(),
            "activeProfile": self._settings.current.active_profile,
        }

    def calibration_command(self, action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if action == "start":
            self._calibration["active"] = True
            self._calibration["draft"] = ColorProfile.from_dict(
                self.detector.profile.to_dict()
            )
            self._calibration["samples"] = []
            self._logs.info("HSV calibration started", source="calibration")
        elif action == "stop":
            self._calibration["active"] = False
            self._calibration["draft"] = None
            self._logs.info("HSV calibration stopped", source="calibration")
        elif action == "target":
            code = str(payload.get("color", "R")).upper()
            if code in COLOR_CODES:
                self._calibration["target"] = code
                self._calibration["samples"] = []
        elif action == "range":
            profile = self._ensure_draft()
            code = str(payload.get("color", self._calibration["target"])).upper()
            rng = profile.ranges.get(code)
            if rng is None:
                return {"ok": False, "error": f"Unknown colour {code}"}
            for key in ("h_min", "h_max", "s_min", "s_max", "v_min", "v_max"):
                if key in payload:
                    setattr(rng, key, int(payload[key]))
            if "wrap_hue" in payload:
                rng.wrap_hue = bool(payload["wrap_hue"])
            profile.builtin = False
        elif action == "sample":
            frame, _ = self.camera.read()
            if frame is None:
                return {"ok": False, "error": "Camera is not running"}
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            roi, _ = self._calibration_roi(hsv)
            stats = self._roi_stats(roi)
            self._calibration["samples"].append((stats["h"], stats["s"], stats["v"]))
            self._logs.info(
                f"Sampled {self._calibration['target']}: "
                f"H{stats['h']} S{stats['s']} V{stats['v']}",
                source="calibration",
            )
        elif action == "auto":
            profile = self._ensure_draft()
            samples = self._calibration["samples"]
            if not samples:
                return {"ok": False, "error": "Take at least one sample first"}
            target = self._calibration["target"]
            profile.calibrate_from_samples(target, samples)
            self._logs.success(
                f"Auto-calibrated {target} from {len(samples)} samples",
                source="calibration",
            )
        elif action == "preset":
            name = str(payload.get("name", "default"))
            self._calibration["draft"] = ColorProfile.from_dict(
                self._profiles.get(name).to_dict()
            )
            self._logs.info(f"Loaded HSV preset '{name}'", source="calibration")
        elif action == "save":
            profile = self._ensure_draft()
            name = str(payload.get("name") or "custom").strip() or "custom"
            profile.name = name
            try:
                self._profiles.save(profile)
            except ValueError as exc:
                return {"ok": False, "error": str(exc)}
            self._settings.update({"active_profile": name})
            self.detector.configure(profile=self._profiles.get(name))
            self._logs.success(f"Saved HSV profile '{name}'", source="calibration")
        elif action == "apply":
            profile = self._ensure_draft()
            self.detector.configure(profile=profile)
            self._logs.info("Applied calibration to the live detector", source="calibration")
        elif action == "delete":
            name = str(payload.get("name", ""))
            try:
                self._profiles.delete(name)
            except ValueError as exc:
                return {"ok": False, "error": str(exc)}
        elif action == "reset":
            self._calibration["draft"] = ColorProfile.preset("default")
            self._calibration["samples"] = []
            self._logs.info("Calibration reset to defaults", source="calibration")
        else:
            return {"ok": False, "error": f"Unknown calibration action: {action}"}

        state = self.calibration_state()
        self._publish_event("calibration", state)
        self._broadcast_state()
        return {"ok": True, "calibration": state}

    def _ensure_draft(self) -> ColorProfile:
        draft = self._calibration.get("draft")
        if not isinstance(draft, ColorProfile):
            draft = ColorProfile.from_dict(self.detector.profile.to_dict())
            self._calibration["draft"] = draft
        return draft

    # ==================================================================
    # Camera / settings
    # ==================================================================
    def start_camera(self) -> Dict[str, Any]:
        config = self._settings.current
        ok = self.camera.restart(
            index=config.camera_index,
            width=config.frame_width,
            height=config.frame_height,
            target_fps=config.target_fps,
            mirror=config.mirror_camera,
        )
        if ok:
            self._logs.success(
                f"Camera {config.camera_index} started at "
                f"{config.frame_width}x{config.frame_height}",
                source="camera",
            )
        else:
            self._logs.error(
                self.camera.status().get("error") or "Camera failed to start",
                source="camera",
            )
        self._broadcast_state()
        return {"ok": ok, "camera": self.camera.status()}

    def stop_camera(self) -> Dict[str, Any]:
        self.camera.stop()
        self._logs.info("Camera stopped", source="camera")
        self._broadcast_state()
        return {"ok": True, "camera": self.camera.status()}

    def update_settings(self, patch: Dict[str, Any]) -> Dict[str, Any]:
        updated = self._settings.update(patch)
        config = self._settings.current

        self.detector.configure(
            profile=self._profiles.get(config.active_profile),
            spacing=config.grid_spacing,
            sample_radius=config.sample_radius,
            offset_y=config.grid_offset_y,
        )
        self.overlay.style = config.arrow_style

        camera_keys = {
            "camera_index", "frame_width", "frame_height", "target_fps", "mirror_camera"
        }
        if camera_keys & set(patch or {}) and self.camera.is_running:
            self.camera.restart(
                index=config.camera_index,
                width=config.frame_width,
                height=config.frame_height,
                target_fps=config.target_fps,
                mirror=config.mirror_camera,
            )
        self._logs.info(f"Settings updated: {', '.join(patch or {})}", source="settings")
        self._broadcast_state()
        return {"ok": True, "settings": updated}

    # ==================================================================
    # State snapshot
    # ==================================================================
    def playback_state(self) -> Dict[str, Any]:
        solution = self._solution
        total = len(solution.moves) if solution else 0
        index = self._playback["index"]
        move = self.current_move
        previous = solution.moves[index - 1] if solution and index > 0 else None
        upcoming = solution.moves[index + 1] if solution and index + 1 < total else None
        return {
            "index": index,
            "total": total,
            "playing": self._playback["playing"],
            "completed": self._playback["completed"],
            "progress": round(index / total, 4) if total else 0.0,
            "current": move.to_dict() if move else None,
            "previous": previous.to_dict() if previous else None,
            "next": upcoming.to_dict() if upcoming else None,
            "history": [m.to_dict() for m in (solution.moves[:index] if solution else [])],
            "cube": (
                solution.states[min(index, len(solution.states) - 1)].facelets
                if solution and solution.states
                else None
            ),
        }

    def scan_state(self) -> Dict[str, Any]:
        return {
            "order": list(FACE_ORDER),
            "faces": {
                face: {
                    "name": FACE_NAMES[face],
                    "captured": face in self._scanned,
                    **self._scanned.get(face, {}),
                }
                for face in FACE_ORDER
            },
            "current": self.current_face,
            "hint": STEP_BY_FACE[self.current_face].how if self.current_face else "",
            "steps": [
                {
                    "face": step.face,
                    "center": step.center,
                    "top": step.top,
                    "text": step.text,
                    "how": step.how,
                    "done": step.face in self._scanned,
                }
                for step in SCAN_STEPS
            ],
            "count": len(self._scanned),
            "autoCapture": self._auto_capture,
        }

    def snapshot(self) -> Dict[str, Any]:
        cube = self._cube
        solution = self._solution
        validation = cube.validate().to_dict() if cube else None
        return {
            "mode": self._mode,
            "camera": self.camera.status(),
            "solver": self._solver.status(),
            "solving": self._solving,
            "solveError": self._solve_error,
            "scan": self.scan_state(),
            "cube": cube.to_dict() if cube else None,
            "cubeSource": self._cube_source,
            "validation": validation,
            "solution": solution.to_dict() if solution else None,
            "playback": self.playback_state(),
            "analytics": self._analytics.summary(),
            "settings": self._settings.get(),
            "calibration": self.calibration_state(),
            "detection": (
                self._latest_detection.to_dict() if self._latest_detection else None
            ),
            "physicalSteps": (
                expand_for_physical_turns(solution.moves) if solution else []
            ),
            "dataset": self.dataset_state(),
            "timestamp": time.time(),
        }

    def _broadcast_state(self) -> None:
        self._publish_event("state", self.snapshot())

    # ==================================================================
    # Command dispatch
    # ==================================================================
    def handle_command(self, command: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Route a UI command. Returns a small ack dict."""
        payload = payload or {}
        try:
            return self._dispatch(command, payload)
        except Exception as exc:
            self._logs.error(f"Command '{command}' failed: {exc}", source="app")
            return {"ok": False, "error": str(exc)}

    def _dispatch(self, command: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if command == "sync":
            self._broadcast_state()
            self._publish_event("analytics", self._analytics.summary())
            return {"ok": True}
        if command == "camera.start":
            return self.start_camera()
        if command == "camera.stop":
            return self.stop_camera()
        if command == "camera.list":
            return {"ok": True, "cameras": list_cameras()}
        if command == "scan.start":
            return self.start_scan()
        if command == "scan.capture":
            return self.capture_face(payload.get("face"))
        if command == "scan.reset":
            self.reset_scan()
            return {"ok": True}
        if command == "scan.auto":
            self._auto_capture = bool(payload.get("enabled", True))
            self._broadcast_state()
            return {"ok": True, "autoCapture": self._auto_capture}
        if command == "scan.face":
            face = str(payload.get("face", "U")).upper()
            if face in FACE_ORDER:
                with self._lock:
                    self._face_index = SCAN_ORDER.index(face)
                    self._scanned.pop(face, None)
                    self._scan_crops.pop(face, None)
                    self._mode = "scan"  # so the re-scanned face is captured automatically
                self.detector.reset_stability()
                self._broadcast_state()
            return {"ok": True}
        if command == "solve.run":
            return self.solve()
        if command == "dataset.save":
            return self.save_to_dataset(str(payload.get("lighting", "")))
        if command == "cube.scramble":
            return self.scramble(int(payload.get("length", 22)))
        if command == "cube.reset":
            return self.reset_cube()
        if command == "cube.apply":
            return self.apply_moves(str(payload.get("moves", "")))
        if command == "cube.sticker":
            return self.set_sticker(
                str(payload.get("face", "")).upper(),
                int(payload.get("index", -1)),
                str(payload.get("color", "")).upper(),
            )
        if command.startswith("playback."):
            return self.playback_command(command.split(".", 1)[1], payload)
        if command.startswith("calibration."):
            return self.calibration_command(command.split(".", 1)[1], payload)
        if command == "settings.update":
            return self.update_settings(payload)
        if command == "settings.reset":
            self._settings.reset()
            return self.update_settings({})
        if command == "logs.clear":
            self._logs.clear()
            return {"ok": True}
        if command == "analytics.clear":
            self._analytics.clear()
            self._publish_event("analytics", self._analytics.summary())
            return {"ok": True}
        if command == "solver.warmup":
            self._solver.warm_up_async()
            return {"ok": True}
        return {"ok": False, "error": f"Unknown command: {command}"}
