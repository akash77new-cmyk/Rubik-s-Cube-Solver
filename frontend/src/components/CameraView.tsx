/**
 * MJPEG viewport.
 *
 * The engine already draws the detection HUD into the frame with OpenCV, so the
 * browser only has to display the stream and layer interactive chrome on top.
 * The `<img>` src is remounted with a cache-busting key whenever the camera is
 * restarted, otherwise browsers keep the dead multipart connection open.
 */

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Button, Tag } from "@/components/ui";
import { IconCamera, IconPower } from "@/components/Icons";
import { useApp } from "@/state/AppStore";

export function CameraView({
  overlay,
  showScanline = false,
  aspect = "4 / 3",
}: {
  overlay?: ReactNode;
  showScanline?: boolean;
  aspect?: string;
}) {
  const { snapshot, send } = useApp();
  const running = Boolean(snapshot?.camera.running);
  const [nonce, setNonce] = useState(() => Date.now());
  const wasRunning = useRef(running);

  useEffect(() => {
    if (running && !wasRunning.current) setNonce(Date.now());
    wasRunning.current = running;
  }, [running]);

  const src = useMemo(() => `/api/stream.mjpg?t=${nonce}`, [nonce]);

  return (
    <div className="viewport" style={{ aspectRatio: aspect }}>
      {running ? (
        <img key={src} src={src} alt="Live camera feed with detection overlay" />
      ) : (
        <div className="viewport-idle">
          <IconCamera size={34} />
          <b>Camera is off</b>
          <p>
            {snapshot?.camera.error ??
              "Start the capture device to run the HSV segmentation pipeline."}
          </p>
          <Button variant="primary" icon={<IconPower size={16} />} onClick={() => send("camera.start")}>
            Start camera
          </Button>
        </div>
      )}

      {running && showScanline && <div className="scanline" />}
      {overlay && <div className="viewport-overlay">{overlay}</div>}
    </div>
  );
}

/** Per-sticker confidence readout drawn beside the feed. */
export function DetectionGrid() {
  const { detection, snapshot } = useApp();
  const min = snapshot?.settings.min_confidence ?? 0.35;

  if (!detection || detection.readings.length === 0) {
    return (
      <p style={{ fontSize: 12, color: "var(--ink-3)" }}>
        Waiting for the first analysed frame…
      </p>
    );
  }

  return (
    <div className="detect-grid">
      {detection.readings.map((reading) => {
        const weak = reading.confidence < min;
        return (
          <div key={reading.index} className="detect-cell" data-weak={weak}>
            <span
              className="detect-swatch"
              style={{ background: `var(--cube-${reading.color})` }}
              title={reading.colorName}
            />
            <b>{reading.color}</b>
            <small>{(reading.confidence * 100).toFixed(0)}%</small>
            <code>
              {reading.hsv[0]},{reading.hsv[1]},{reading.hsv[2]}
            </code>
          </div>
        );
      })}
    </div>
  );
}

/** Compact live telemetry line used on several pages. */
export function DetectionSummary() {
  const { detection, snapshot } = useApp();
  const fps = snapshot?.camera.fps ?? 0;
  if (!detection) return null;
  const tone =
    detection.meanConfidence >= 0.6
      ? "good"
      : detection.meanConfidence >= 0.35
        ? "warning"
        : "critical";
  return (
    <div className="viewport-badges">
      <Tag tone="brand">{fps.toFixed(0)} FPS</Tag>
      <Tag tone={tone}>confidence {(detection.meanConfidence * 100).toFixed(0)}%</Tag>
      <Tag tone={detection.stable ? "good" : "default"}>
        {detection.stable ? "locked" : `stability ${(detection.stability * 100).toFixed(0)}%`}
      </Tag>
      {detection.quad && <Tag>contour found</Tag>}
    </div>
  );
}
