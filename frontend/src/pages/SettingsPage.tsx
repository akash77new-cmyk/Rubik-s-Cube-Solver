import { useEffect, useState } from "react";
import { Button, Card, KeyValue, Segmented, SliderRow, Tag, ToggleRow } from "@/components/ui";
import { PageHead } from "@/components/layout";
import { IconCamera, IconRestart, IconSave } from "@/components/Icons";
import { useApp } from "@/state/AppStore";
import { CUBE_COLORS, COLOR_NAMES } from "@/lib/colors";
import { COLOR_CODES, THEMES, type ColorCode } from "@/lib/types";

const RESOLUTIONS = [
  { label: "640 × 480", width: 640, height: 480 },
  { label: "960 × 720", width: 960, height: 720 },
  { label: "1280 × 720", width: 1280, height: 720 },
  { label: "1920 × 1080", width: 1920, height: 1080 },
];

interface CameraOption {
  index: number;
  label: string;
  width: number;
  height: number;
}

export default function SettingsPage() {
  const { snapshot, send } = useApp();
  const settings = snapshot?.settings;
  const [cameras, setCameras] = useState<CameraOption[]>([]);
  const [probing, setProbing] = useState(false);

  /* Device probing goes through the REST endpoint because it blocks briefly. */
  const probeCameras = async () => {
    setProbing(true);
    try {
      const response = await fetch("/api/command", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command: "camera.list" }),
      });
      await response.json();
    } finally {
      setProbing(false);
    }
  };

  useEffect(() => {
    // Offer the four indices most webcams live on, plus whatever is in use.
    const base = [0, 1, 2, 3].map((index) => ({
      index,
      label: `Camera ${index}`,
      width: 0,
      height: 0,
    }));
    setCameras(base);
  }, []);

  if (!settings) {
    return (
      <>
        <PageHead title="Settings" description="Waiting for the engine…" />
        <Card>
          <div className="skeleton" style={{ height: 180 }} />
        </Card>
      </>
    );
  }

  const update = (patch: Record<string, unknown>) => send("settings.update", patch);

  return (
    <>
      <PageHead
        title="Settings"
        description="Everything here is persisted to data/settings.json and applied to the running engine immediately."
        actions={
          <Button icon={<IconRestart size={16} />} variant="danger" onClick={() => send("settings.reset")}>
            Reset to defaults
          </Button>
        }
      />

      <div className="grid grid-2">
        {/* Camera ----------------------------------------------------- */}
        <Card title="Camera" description="Capture device and stream format" icon={<IconCamera size={16} />}>
          <div className="setting-field">
            <label htmlFor="camera-index">Device</label>
            <select
              id="camera-index"
              value={settings.camera_index}
              onChange={(event) => update({ camera_index: Number(event.target.value) })}
            >
              {cameras.map((camera) => (
                <option key={camera.index} value={camera.index}>
                  {camera.label}
                </option>
              ))}
            </select>
          </div>

          <div className="setting-field">
            <label htmlFor="resolution">Resolution</label>
            <select
              id="resolution"
              value={`${settings.frame_width}x${settings.frame_height}`}
              onChange={(event) => {
                const [width, height] = event.target.value.split("x").map(Number);
                update({ frame_width: width, frame_height: height });
              }}
            >
              {RESOLUTIONS.map((item) => (
                <option key={item.label} value={`${item.width}x${item.height}`}>
                  {item.label}
                </option>
              ))}
            </select>
          </div>

          <SliderRow
            label="Target FPS"
            value={settings.target_fps}
            min={5}
            max={60}
            onChange={(value) => update({ target_fps: value })}
          />

          <ToggleRow
            label="Mirror the feed"
            hint="Matches how you see yourself in a mirror"
            checked={settings.mirror_camera}
            onChange={(value) => update({ mirror_camera: value })}
          />

          <div className="btn-row">
            <Button size="sm" loading={probing} onClick={probeCameras}>
              Probe devices
            </Button>
            <Button size="sm" variant="ghost" onClick={() => send("camera.start")}>
              Restart camera
            </Button>
          </div>

          <KeyValue label="Reported resolution">
            {snapshot?.camera.resolution?.join(" × ") ?? "—"}
          </KeyValue>
          <KeyValue label="Measured FPS">{(snapshot?.camera.fps ?? 0).toFixed(1)}</KeyValue>
        </Card>

        {/* Detection -------------------------------------------------- */}
        <Card title="Detection" description="Sampling geometry and acceptance threshold">
          <SliderRow
            label="Grid spacing"
            hint="Distance between sample points"
            value={settings.grid_spacing}
            min={40}
            max={200}
            suffix=" px"
            onChange={(value) => update({ grid_spacing: value })}
          />
          <SliderRow
            label="Sample radius"
            hint="Half-width of each sampled patch"
            value={settings.sample_radius}
            min={2}
            max={30}
            suffix=" px"
            onChange={(value) => update({ sample_radius: value })}
          />
          <SliderRow
            label="Vertical offset"
            value={settings.grid_offset_y}
            min={-200}
            max={200}
            suffix=" px"
            onChange={(value) => update({ grid_offset_y: value })}
          />
          <SliderRow
            label="Minimum confidence"
            hint="Auto-capture will not fire below this"
            value={settings.min_confidence}
            min={0}
            max={1}
            step={0.05}
            onChange={(value) => update({ min_confidence: value })}
          />
          <KeyValue label="Active HSV profile">
            <Tag tone="brand">{settings.active_profile}</Tag>
          </KeyValue>
        </Card>

        {/* Overlays --------------------------------------------------- */}
        <Card title="Overlays" description="What the engine draws onto each frame">
          <ToggleRow
            label="Sampling grid"
            checked={settings.show_grid}
            onChange={(value) => update({ show_grid: value })}
          />
          <ToggleRow
            label="Colour labels"
            checked={settings.show_labels}
            onChange={(value) => update({ show_labels: value })}
          />
          <ToggleRow
            label="Contour & reticle"
            checked={settings.show_bounding_box}
            onChange={(value) => update({ show_bounding_box: value })}
          />
          <ToggleRow
            label="Confidence bars"
            checked={settings.show_confidence}
            onChange={(value) => update({ show_confidence: value })}
          />

          <div className="setting-field" style={{ marginTop: 8 }}>
            <label>Arrow style</label>
            <Segmented
              value={settings.arrow_style}
              options={[
                { value: "neon", label: "Neon" },
                { value: "solid", label: "Solid" },
                { value: "outline", label: "Outline" },
              ]}
              onChange={(value) => update({ arrow_style: value })}
            />
          </div>
        </Card>

        {/* Playback + theme ------------------------------------------- */}
        <Card title="Playback & appearance" description="How the solution plays and how the app looks">
          <SliderRow
            label="Animation speed"
            value={settings.animation_speed}
            min={0.25}
            max={3}
            step={0.25}
            suffix="×"
            onChange={(value) => update({ animation_speed: value })}
          />
          <SliderRow
            label="Auto-play interval"
            value={settings.autoplay_interval_ms}
            min={200}
            max={3000}
            step={50}
            suffix=" ms"
            onChange={(value) => update({ autoplay_interval_ms: value })}
          />

          <div className="setting-field" style={{ marginTop: 8 }}>
            <label>Theme</label>
            <Segmented
              value={settings.theme}
              options={THEMES.map(({ value, label }) => ({ value, label }))}
              onChange={(value) => update({ theme: value })}
            />
          </div>
        </Card>
      </div>

      {/* Cube palette --------------------------------------------------- */}
      <Card
        title="Cube colours"
        description="How each sticker code is rendered in the 3D cube and net. Detection is unaffected — tune those on the Calibration page."
        actions={
          <Button
            size="sm"
            icon={<IconSave size={14} />}
            onClick={() => update({ cube_palette: CUBE_COLORS })}
          >
            Restore defaults
          </Button>
        }
      >
        <div className="palette-grid">
          {COLOR_CODES.map((code) => (
            <label key={code} className="palette-item">
              <input
                type="color"
                value={settings.cube_palette?.[code] ?? CUBE_COLORS[code]}
                onChange={(event) =>
                  update({
                    cube_palette: {
                      ...(settings.cube_palette ?? CUBE_COLORS),
                      [code]: event.target.value,
                    } as Record<ColorCode, string>,
                  })
                }
                aria-label={`${COLOR_NAMES[code]} sticker colour`}
              />
              <span>
                <b>{COLOR_NAMES[code]}</b>
                <small>{settings.cube_palette?.[code] ?? CUBE_COLORS[code]}</small>
              </span>
            </label>
          ))}
        </div>
      </Card>

      <Card title="Configuration file" description="Where these values live">
        <KeyValue label="Settings">data/settings.json</KeyValue>
        <KeyValue label="HSV profiles">data/hsv_profiles.json</KeyValue>
        <KeyValue label="Solve history">data/solve_history.json</KeyValue>
        <KeyValue label="Solver tables">.cache/twophase/</KeyValue>
      </Card>
    </>
  );
}
