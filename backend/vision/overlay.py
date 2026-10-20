"""Frame overlays: the heads-up display drawn on top of the camera feed.

Everything here is drawn procedurally with anti-aliased OpenCV primitives rather
than blitted from bitmaps, so the HUD stays crisp at any capture resolution -
the original implementation pasted fixed-size PNGs which blurred badly and broke
whenever the frame size changed.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from backend.core.moves import FACE_NAMES, Move
from backend.vision.detector import DetectionResult

BGR = Tuple[int, int, int]

#: Sticker colours in BGR - kept in sync with the frontend palette.
COLOR_BGR: Dict[str, BGR] = {
    "W": (250, 250, 248),
    "Y": (21, 204, 250),
    "R": (68, 68, 239),
    "O": (22, 115, 249),
    "G": (94, 197, 34),
    "B": (246, 130, 59),
}

ACCENT: BGR = (245, 158, 66)      # violet-blue accent
GOOD: BGR = (105, 220, 120)
WARN: BGR = (60, 190, 250)
BAD: BGR = (90, 90, 245)
INK: BGR = (245, 245, 245)
PANEL: BGR = (26, 20, 16)

FONT = cv2.FONT_HERSHEY_SIMPLEX


def _rounded_rect_pts(
    x: int, y: int, w: int, h: int, radius: int
) -> np.ndarray:
    """Polygon approximation of a rounded rectangle (for filled glass panels)."""
    radius = max(0, min(radius, w // 2, h // 2))
    if radius == 0:
        return np.array(
            [[x, y], [x + w, y], [x + w, y + h], [x, y + h]], dtype=np.int32
        )
    points: List[Tuple[int, int]] = []
    corners = (
        (x + w - radius, y + radius, -90, 0),
        (x + w - radius, y + h - radius, 0, 90),
        (x + radius, y + h - radius, 90, 180),
        (x + radius, y + radius, 180, 270),
    )
    for cx, cy, start, end in corners:
        for angle in range(start, end + 1, 6):
            rad = math.radians(angle)
            points.append((int(cx + radius * math.cos(rad)), int(cy + radius * math.sin(rad))))
    return np.array(points, dtype=np.int32)


def draw_glass_panel(
    frame: np.ndarray,
    rect: Tuple[int, int, int, int],
    alpha: float = 0.55,
    radius: int = 14,
    color: BGR = PANEL,
    border: Optional[BGR] = None,
) -> None:
    """Translucent rounded panel - the glassmorphism effect, in OpenCV."""
    x, y, w, h = rect
    if w <= 0 or h <= 0:
        return
    pts = _rounded_rect_pts(x, y, w, h, radius)
    layer = frame.copy()
    cv2.fillPoly(layer, [pts], color, lineType=cv2.LINE_AA)
    cv2.addWeighted(layer, alpha, frame, 1 - alpha, 0, dst=frame)
    if border:
        cv2.polylines(frame, [pts], True, border, 1, lineType=cv2.LINE_AA)


def draw_text(
    frame: np.ndarray,
    text: str,
    org: Tuple[int, int],
    scale: float = 0.6,
    color: BGR = INK,
    thickness: int = 1,
    shadow: bool = True,
) -> None:
    if shadow:
        cv2.putText(
            frame, text, (org[0] + 1, org[1] + 1), FONT, scale, (0, 0, 0), thickness + 1, cv2.LINE_AA
        )
    cv2.putText(frame, text, org, FONT, scale, color, thickness, cv2.LINE_AA)


def text_size(text: str, scale: float = 0.6, thickness: int = 1) -> Tuple[int, int]:
    (w, h), _ = cv2.getTextSize(text, FONT, scale, thickness)
    return w, h


def wrap_text(text: str, max_width: int, scale: float, thickness: int) -> List[str]:
    """Split ``text`` into lines that fit in ``max_width`` pixels (OpenCV can't wrap)."""
    lines: List[str] = []
    for word in text.split():
        candidate = f"{lines[-1]} {word}" if lines else word
        if lines and text_size(candidate, scale, thickness)[0] <= max_width:
            lines[-1] = candidate
        else:
            lines.append(word)
    return lines


class OverlayRenderer:
    """Draws detection results, instructions and move arrows onto frames."""

    def __init__(self, style: str = "neon") -> None:
        self.style = style

    # ------------------------------------------------------------------
    # Detection HUD
    # ------------------------------------------------------------------
    def draw_detection(
        self,
        frame: np.ndarray,
        result: DetectionResult,
        *,
        show_grid: bool = True,
        show_labels: bool = True,
        show_bounding_box: bool = True,
        show_confidence: bool = True,
        min_confidence: float = 0.35,
    ) -> np.ndarray:
        if show_bounding_box and result.quad:
            cv2.polylines(
                frame,
                [np.array(result.quad, dtype=np.int32)],
                True,
                ACCENT,
                2,
                lineType=cv2.LINE_AA,
            )

        if show_bounding_box and result.bbox:
            self._draw_reticle(frame, result.bbox, result.stable)

        if not show_grid:
            return frame

        for reading in result.readings:
            color = COLOR_BGR.get(reading.color, (200, 200, 200))
            weak = reading.confidence < min_confidence
            half = 26
            x, y = reading.x, reading.y

            pts = _rounded_rect_pts(x - half, y - half, half * 2, half * 2, 10)
            # Filled colour chip at low opacity, solid outline in the sticker colour.
            layer = frame.copy()
            cv2.fillPoly(layer, [pts], color, lineType=cv2.LINE_AA)
            cv2.addWeighted(layer, 0.30, frame, 0.70, 0, dst=frame)
            cv2.polylines(
                frame,
                [pts],
                True,
                BAD if weak else color,
                2 if not weak else 1,
                lineType=cv2.LINE_AA,
            )

            if show_labels:
                label = reading.color
                tw, th = text_size(label, 0.62, 2)
                draw_text(
                    frame,
                    label,
                    (x - tw // 2, y + th // 2),
                    0.62,
                    (20, 20, 20) if reading.color in ("W", "Y") else INK,
                    2,
                )

            if show_confidence:
                self._draw_confidence_bar(frame, x - half, y + half + 5, half * 2, reading.confidence)

        return frame

    def _draw_confidence_bar(
        self, frame: np.ndarray, x: int, y: int, width: int, confidence: float
    ) -> None:
        height = 4
        cv2.rectangle(frame, (x, y), (x + width, y + height), (45, 45, 45), -1)
        filled = int(width * max(0.0, min(1.0, confidence)))
        tone = GOOD if confidence >= 0.6 else (WARN if confidence >= 0.35 else BAD)
        if filled:
            cv2.rectangle(frame, (x, y), (x + filled, y + height), tone, -1)

    def _draw_reticle(
        self, frame: np.ndarray, bbox: Tuple[int, int, int, int], stable: bool
    ) -> None:
        """Corner brackets around the sampling area, green once the read is stable."""
        x, y, w, h = bbox
        color = GOOD if stable else ACCENT
        arm = max(20, w // 6)
        thickness = 3
        corners = (
            ((x, y), (1, 1)),
            ((x + w, y), (-1, 1)),
            ((x, y + h), (1, -1)),
            ((x + w, y + h), (-1, -1)),
        )
        for (px, py), (sx, sy) in corners:
            cv2.line(frame, (px, py), (px + sx * arm, py), color, thickness, cv2.LINE_AA)
            cv2.line(frame, (px, py), (px, py + sy * arm), color, thickness, cv2.LINE_AA)

    # ------------------------------------------------------------------
    # Status banners
    # ------------------------------------------------------------------
    def draw_scan_banner(
        self,
        frame: np.ndarray,
        face: Optional[str],
        scanned: Sequence[str],
        result: Optional[DetectionResult] = None,
        title: Optional[str] = None,
    ) -> np.ndarray:
        height, width = frame.shape[:2]
        draw_glass_panel(frame, (16, 14, width - 32, 62), alpha=0.6, radius=16, border=(70, 60, 55))

        if title is None:
            if face:
                title = f"Show the {FACE_NAMES.get(face, face)} face  ({face})"
            else:
                title = "All faces captured"
        draw_text(frame, title, (32, 44), 0.72, INK, 2)

        progress = f"{len(scanned)}/6 faces"
        tw, _ = text_size(progress, 0.6, 2)
        draw_text(frame, progress, (width - 32 - tw, 44), 0.6, ACCENT, 2)

        # Slim progress bar under the banner text.
        bar_x, bar_y, bar_w = 32, 58, width - 64
        cv2.rectangle(frame, (bar_x, bar_y), (bar_x + bar_w, bar_y + 4), (55, 48, 45), -1)
        filled = int(bar_w * (len(scanned) / 6.0))
        if filled:
            cv2.rectangle(frame, (bar_x, bar_y), (bar_x + filled, bar_y + 4), ACCENT, -1)

        if result is not None:
            self._draw_stats_strip(frame, result)
        return frame

    def _draw_stats_strip(self, frame: np.ndarray, result: DetectionResult) -> None:
        height, width = frame.shape[:2]
        draw_glass_panel(frame, (16, height - 62, 300, 46), alpha=0.6, radius=14, border=(70, 60, 55))
        confidence = result.mean_confidence
        tone = GOOD if confidence >= 0.6 else (WARN if confidence >= 0.35 else BAD)
        draw_text(frame, f"confidence {confidence:.2f}", (30, height - 34), 0.55, tone, 1)
        state = "LOCKED" if result.stable else "reading..."
        draw_text(frame, state, (30, height - 16), 0.5, GOOD if result.stable else INK, 1)

    def draw_hud(
        self, frame: np.ndarray, fps: float, status: str, extra: Optional[str] = None
    ) -> np.ndarray:
        height, width = frame.shape[:2]
        label = f"{fps:.0f} FPS"
        tw, _ = text_size(label, 0.55, 2)
        draw_glass_panel(frame, (width - tw - 46, height - 62, tw + 30, 46), alpha=0.6, radius=14)
        draw_text(frame, label, (width - tw - 32, height - 32), 0.55, ACCENT, 2)
        if extra:
            draw_text(frame, extra, (width - tw - 32, height - 16), 0.42, INK, 1)
        return frame

    # ------------------------------------------------------------------
    # Move arrows
    # ------------------------------------------------------------------
    def draw_move(
        self,
        frame: np.ndarray,
        move: Optional[Move],
        *,
        index: int = 0,
        total: int = 0,
        turn_back: bool = False,
    ) -> np.ndarray:
        """Draw the move the user should perform now: its notation and name, the
        plain-English instruction, and an arrow showing which way to turn.

        ``turn_back`` marks a B move: the instruction says to turn the whole cube
        around first, and the arrow shows the turn as seen after doing that.
        """
        height, width = frame.shape[:2]
        if move is None:
            return frame

        counter = f"{index + 1} / {total}" if total else ""
        counter_width = text_size(counter, 0.7, 2)[0] + 24 if counter else 0
        text_x = 124  # right of the big notation
        scale = 0.6 if width >= 900 else 0.5
        lines = wrap_text(move.instruction, width - 32 - text_x - counter_width, scale, 2)
        panel_height = 54 + 26 * len(lines)

        draw_glass_panel(frame, (16, 14, width - 32, panel_height), alpha=0.7, radius=16, border=(70, 60, 55))
        draw_text(frame, move.notation, (32, 66), 1.25, ACCENT, 3)
        draw_text(frame, move.label, (text_x, 40), 0.5, ACCENT, 1)
        for number, line in enumerate(lines):
            draw_text(frame, line, (text_x, 66 + 26 * number), scale, INK, 2)
        if counter:
            draw_text(frame, counter, (width - 32 - counter_width + 24, 52), 0.7, INK, 2)
            bar_x, bar_y, bar_w = 32, 14 + panel_height - 10, width - 64
            cv2.rectangle(frame, (bar_x, bar_y), (bar_x + bar_w, bar_y + 4), (55, 48, 45), -1)
            filled = int(bar_w * ((index + 1) / max(total, 1)))
            if filled:
                cv2.rectangle(frame, (bar_x, bar_y), (bar_x + filled, bar_y + 4), ACCENT, -1)

        self._draw_rotation_arrow(frame, move)
        if turn_back:
            # The arrow is the back face's turn; this label says which face it is.
            ax, ay, _ = self._face_anchor(move, width, height)
            tw, th = text_size("BACK", 0.9, 2)
            draw_text(frame, "BACK", (ax - tw // 2, ay + th // 2), 0.9, WARN, 2)
        return frame

    def _face_anchor(self, move: Move, width: int, height: int) -> Tuple[int, int, int]:
        """Where the arrow sits, and how big, for each face."""
        cx, cy = width // 2, height // 2 + 20
        span = int(min(width, height) * 0.20)
        offset = int(span * 1.9)
        anchors = {
            "U": (cx, cy - offset),
            "D": (cx, cy + offset),
            "L": (cx - offset, cy),
            "R": (cx + offset, cy),
            "F": (cx, cy),
            "B": (cx, cy),
        }
        ax, ay = anchors[move.face]
        return ax, ay, span

    def _draw_rotation_arrow(self, frame: np.ndarray, move: Move) -> None:
        height, width = frame.shape[:2]
        ax, ay, span = self._face_anchor(move, width, height)

        if move.face in ("F", "B"):
            self._draw_circular_arrow(frame, (ax, ay), span, move.direction)
        else:
            start, end = self.linear_arrow_ends(move, (ax, ay), span)
            self._glow_line(frame, start, end, ACCENT)
            self._draw_arrow_head(frame, start, end, ACCENT, span)

        if move.modifier == "2":
            badge = "x2"
            tw, th = text_size(badge, 0.8, 2)
            draw_glass_panel(frame, (ax - tw // 2 - 10, ay + span + 6, tw + 20, th + 16), alpha=0.7, radius=10)
            draw_text(frame, badge, (ax - tw // 2, ay + span + th + 14), 0.8, WARN, 2)

    def _glow_line(
        self, frame: np.ndarray, p1: Tuple[int, int], p2: Tuple[int, int], color: BGR
    ) -> None:
        """Neon look: a soft wide stroke under a bright thin stroke."""
        if self.style == "neon":
            glow = frame.copy()
            cv2.line(glow, p1, p2, color, 14, cv2.LINE_AA)
            cv2.addWeighted(glow, 0.30, frame, 0.70, 0, dst=frame)
        cv2.line(frame, p1, p2, color, 5, cv2.LINE_AA)
        if self.style != "outline":
            cv2.line(frame, p1, p2, (255, 255, 255), 1, cv2.LINE_AA)

    @staticmethod
    def linear_arrow_ends(
        move: Move, center: Tuple[int, int], span: int
    ) -> Tuple[Tuple[int, int], Tuple[int, int]]:
        """Start and end of the straight arrow for a U, D, L or R turn. It points the
        way the layer moves for the person holding the cube (``Move.arrow``)."""
        cx, cy = center
        dx, dy = {"left": (-1, 0), "right": (1, 0), "up": (0, -1), "down": (0, 1)}[move.arrow]
        return (cx - dx * span, cy - dy * span), (cx + dx * span, cy + dy * span)

    def _draw_arrow_head(
        self,
        frame: np.ndarray,
        start: Tuple[int, int],
        end: Tuple[int, int],
        color: BGR,
        span: int,
    ) -> None:
        angle = math.atan2(end[1] - start[1], end[0] - start[0])
        size = max(14, span // 3)
        spread = math.radians(28)
        p1 = (
            int(end[0] - size * math.cos(angle - spread)),
            int(end[1] - size * math.sin(angle - spread)),
        )
        p2 = (
            int(end[0] - size * math.cos(angle + spread)),
            int(end[1] - size * math.sin(angle + spread)),
        )
        cv2.fillPoly(frame, [np.array([end, p1, p2], dtype=np.int32)], color, cv2.LINE_AA)

    def _draw_circular_arrow(
        self, frame: np.ndarray, center: Tuple[int, int], radius: int, direction: str
    ) -> None:
        cx, cy = center
        clockwise = direction != "ccw"
        start_angle, end_angle = (-40, 250) if clockwise else (220, -70)

        points: List[Tuple[int, int]] = []
        step = 4 if clockwise else -4
        for angle in range(start_angle, end_angle, step):
            rad = math.radians(angle)
            points.append((int(cx + radius * math.cos(rad)), int(cy + radius * math.sin(rad))))

        if len(points) < 2:
            return
        if self.style == "neon":
            glow = frame.copy()
            cv2.polylines(glow, [np.array(points, dtype=np.int32)], False, ACCENT, 16, cv2.LINE_AA)
            cv2.addWeighted(glow, 0.28, frame, 0.72, 0, dst=frame)
        cv2.polylines(frame, [np.array(points, dtype=np.int32)], False, ACCENT, 6, cv2.LINE_AA)
        if self.style != "outline":
            cv2.polylines(frame, [np.array(points, dtype=np.int32)], False, (255, 255, 255), 1, cv2.LINE_AA)

        self._draw_arrow_head(frame, points[-2], points[-1], ACCENT, radius)


def encode_jpeg(frame: np.ndarray, quality: int = 80) -> Optional[bytes]:
    """JPEG-encode a frame for the MJPEG stream / socket transport."""
    ok, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    return buffer.tobytes() if ok else None
