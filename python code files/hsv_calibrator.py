"""Trackbar HSV calibration utility (the original standalone tool).

Same idea as before - six sliders over a live mask preview - but it now edits a
real :class:`~backend.core.color.ColorProfile` and can save it, so a calibration
done here is immediately used by the scanner and by the web UI.

    python "python code files/hsv_calibrator.py"          # tune 'default'
    python "python code files/hsv_calibrator.py" --color G --profile desk-lamp

Keys
----
``n``    cycle to the next colour
``s``    save the profile under ``--profile`` and make it active
``r``    reset the current colour to the built-in default
``esc``  quit
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import cv2
import numpy as np

from backend.config import settings_store
from backend.core.color import DEFAULT_RANGES, ColorProfile, profile_store
from backend.core.cube import COLOR_CODES, COLOR_NAMES
from backend.vision.overlay import COLOR_BGR, draw_glass_panel, draw_text

TRACKBARS = "HSV Controls"
PREVIEW = "Mask Preview"
CHANNELS = (
    ("H min", "h_min", 179),
    ("H max", "h_max", 179),
    ("S min", "s_min", 255),
    ("S max", "s_max", 255),
    ("V min", "v_min", 255),
    ("V max", "v_max", 255),
)


def _load_trackbars(profile: ColorProfile, code: str) -> None:
    rng = profile.ranges[code]
    for label, attribute, _ in CHANNELS:
        cv2.setTrackbarPos(label, TRACKBARS, int(getattr(rng, attribute)))
    cv2.setTrackbarPos("wrap hue", TRACKBARS, 1 if rng.wrap_hue else 0)


def _read_trackbars(profile: ColorProfile, code: str) -> None:
    rng = profile.ranges[code]
    for label, attribute, _ in CHANNELS:
        setattr(rng, attribute, cv2.getTrackbarPos(label, TRACKBARS))
    rng.wrap_hue = bool(cv2.getTrackbarPos("wrap hue", TRACKBARS))


def _mask_for(hsv: np.ndarray, profile: ColorProfile, code: str) -> np.ndarray:
    rng = profile.ranges[code]
    if rng.wrap_hue:
        lower = cv2.inRange(hsv, np.array([rng.h_min, rng.s_min, rng.v_min]),
                            np.array([179, rng.s_max, rng.v_max]))
        upper = cv2.inRange(hsv, np.array([0, rng.s_min, rng.v_min]),
                            np.array([rng.h_max, rng.s_max, rng.v_max]))
        return cv2.bitwise_or(lower, upper)
    return cv2.inRange(hsv, np.array([rng.h_min, rng.s_min, rng.v_min]),
                       np.array([rng.h_max, rng.s_max, rng.v_max]))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="HSV calibration utility")
    parser.add_argument("--color", default="R", choices=list(COLOR_CODES))
    parser.add_argument("--profile", default="custom", help="name to save under")
    parser.add_argument("--base", default=None, help="profile to start from")
    parser.add_argument("--camera", type=int, default=None)
    args = parser.parse_args(argv)

    settings = settings_store.current
    base = args.base or settings.active_profile
    profile = ColorProfile.from_dict(profile_store.get(base).to_dict())
    profile.name = args.profile
    profile.builtin = False
    code = args.color

    index = cv2.VideoCapture(args.camera if args.camera is not None else settings.camera_index)
    if not index.isOpened():
        print("[error] could not open the camera")
        return 1

    cv2.namedWindow(TRACKBARS, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(TRACKBARS, 460, 300)
    for label, _, maximum in CHANNELS:
        cv2.createTrackbar(label, TRACKBARS, 0, maximum, lambda _value: None)
    cv2.createTrackbar("wrap hue", TRACKBARS, 0, 1, lambda _value: None)
    _load_trackbars(profile, code)

    print("Keys:  n = next colour   s = save profile   r = reset colour   esc = quit")

    try:
        while True:
            ok, frame = index.read()
            if not ok:
                break
            frame = cv2.flip(frame, 1)
            hsv = cv2.cvtColor(cv2.bilateralFilter(frame, 7, 60, 60), cv2.COLOR_BGR2HSV)

            _read_trackbars(profile, code)
            mask = _mask_for(hsv, profile, code)

            preview = cv2.add((frame * 0.25).astype(np.uint8),
                              cv2.bitwise_and(frame, frame, mask=mask))
            preview[cv2.Canny(mask, 50, 150) > 0] = (255, 255, 255)

            height, width = preview.shape[:2]
            size = max(30, min(width, height) // 8)
            x, y = (width - size) // 2, (height - size) // 2
            cv2.rectangle(preview, (x, y), (x + size, y + size), (245, 158, 66), 2)

            roi = hsv[y : y + size, x : x + size].reshape(-1, 3)
            median = np.median(roi, axis=0).astype(int) if roi.size else np.zeros(3, int)
            coverage = float(np.count_nonzero(mask)) / mask.size * 100

            draw_glass_panel(preview, (12, 10, width - 24, 58), alpha=0.6, radius=14)
            draw_text(preview, f"{COLOR_NAMES[code]} ({code})   profile: {profile.name}",
                      (26, 34), 0.6, COLOR_BGR[code], 2)
            draw_text(preview,
                      f"sample HSV {tuple(median)}   mask {coverage:5.1f}%   "
                      f"[n] next  [s] save  [r] reset",
                      (26, 56), 0.45, (225, 225, 235), 1)

            cv2.imshow(PREVIEW, preview)
            key = cv2.waitKey(1) & 0xFF

            if key == 27:
                break
            if key == ord("n"):
                code = COLOR_CODES[(COLOR_CODES.index(code) + 1) % len(COLOR_CODES)]
                _load_trackbars(profile, code)
                print(f"[info] editing {COLOR_NAMES[code]}")
            elif key == ord("r"):
                profile.ranges[code] = ColorProfile.preset("default").ranges[code]
                _load_trackbars(profile, code)
                print(f"[info] {COLOR_NAMES[code]} reset to default "
                      f"{DEFAULT_RANGES[code].to_dict()}")
            elif key == ord("s"):
                try:
                    profile_store.save(profile)
                except ValueError as exc:
                    print(f"[error] {exc}")
                else:
                    settings_store.update({"active_profile": profile.name})
                    print(f"[ok] saved profile '{profile.name}' and made it active")
    finally:
        index.release()
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
