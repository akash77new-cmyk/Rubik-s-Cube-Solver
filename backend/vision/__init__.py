"""OpenCV camera capture, HSV sticker detection and frame overlays."""

from backend.vision.camera import CameraStream, list_cameras
from backend.vision.detector import DetectionResult, FaceDetector, StickerReading
from backend.vision.overlay import OverlayRenderer

__all__ = [
    "CameraStream",
    "list_cameras",
    "DetectionResult",
    "FaceDetector",
    "StickerReading",
    "OverlayRenderer",
]
