import { useEffect, useState } from "react";
import { Button, Card, KeyValue, SliderRow, Tag, ToggleRow } from "@/components/ui";
import { CameraView } from "@/components/CameraView";
import { HueHistogram } from "@/components/charts";
import { PageHead } from "@/components/layout";
import {
  IconCheck,
  IconDroplet,
  IconPower,
  IconRestart,
  IconSave,
  IconTarget,
  IconTrash,
} from "@/components/Icons";
import { useApp } from "@/state/AppStore";
import { CUBE_COLORS, COLOR_NAMES } from "@/lib/colors";
import { COLOR_CODES, type HsvRange } from "@/lib/types";

const CHANNELS: { key: keyof HsvRange; label: string; max: number }[] = [
  { key: "h_min", label: "Hue min", max: 179 },
  { key: "h_max", label: "Hue max", max: 179 },
  { key: "s_min", label: "Saturation min", max: 255 },
  { key: "s_max", label: "Saturation max", max: 255 },
  { key: "v_min", label: "Value min", max: 255 },
  { key: "v_max", label: "Value max", max: 255 },
];

export default function CalibrationPage() {
  const { snapshot, send } = useApp();
  const calibration = snapshot?.calibration;
  const camera = snapshot?.camera;
  const [profileName, setProfileName] = useState("");

  const target = calibration?.target ?? "R";
  const range = calibration?.ranges?.[target];

  /* Entering the page turns on the mask preview; App.tsx turns it off on exit. */
  useEffect(() => {
    if (calibration && !calibration.active) send("calibration.start");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [Boolean(calibration)]);

  return (
    <>
      <PageHead
        title="HSV Calibration"
        description="Tune the six colour boxes so detection survives your camera, your cube and your lighting. The preview shows exactly which pixels the current box accepts."
        actions={
          <>
            <Button
              variant={camera?.running ? "danger" : "primary"}
              icon={<IconPower size={16} />}
              onClick={() => send(camera?.running ? "camera.stop" : "camera.start")}
            >
              {camera?.running ? "Stop camera" : "Start camera"}
            </Button>
            <Button icon={<IconRestart size={16} />} onClick={() => send("calibration.reset")}>
              Reset defaults
            </Button>
          </>
        }
      />

      <div className="split">
        <Card
          className="card-pad-0"
          title={undefined}
        >
          <CameraView
            aspect="4 / 3"
            overlay={
              <>
                <div className="viewport-badges">
                  <Tag tone="brand">
                    <IconDroplet size={12} /> mask preview · {COLOR_NAMES[target]}
                  </Tag>
                  {calibration?.coverage !== undefined && (
                    <Tag>{(calibration.coverage * 100).toFixed(1)}% of frame matched</Tag>
                  )}
                </div>
                <div className="viewport-badges" style={{ alignSelf: "flex-start" }}>
                  <Tag tone="good">
                    <IconTarget size={12} /> hold a sticker in the centre box
                  </Tag>
                </div>
              </>
            }
          />
        </Card>

        <div style={{ display: "flex", flexDirection: "column", gap: "var(--sp-4)" }}>
          <Card title="Target colour" description="Which of the six sticker colours you are tuning">
            <div className="swatch-row" style={{ marginBottom: 24 }}>
              {COLOR_CODES.map((code) => (
                <button
                  key={code}
                  type="button"
                  className="swatch"
                  aria-pressed={target === code}
                  aria-label={COLOR_NAMES[code]}
                  title={COLOR_NAMES[code]}
                  style={{ "--c": CUBE_COLORS[code] } as never}
                  onClick={() => send("calibration.target", { color: code })}
                >
                  <small>{code}</small>
                </button>
              ))}
            </div>

            <KeyValue label="Live sample (H,S,V)">
              {calibration?.sample
                ? `${calibration.sample.h}, ${calibration.sample.s}, ${calibration.sample.v}`
                : "—"}
            </KeyValue>
            <KeyValue label="Samples collected">{calibration?.sampleCount ?? 0}</KeyValue>
            <KeyValue label="Frame coverage">
              {calibration?.coverage !== undefined ? `${(calibration.coverage * 100).toFixed(2)}%` : "—"}
            </KeyValue>

            <div className="btn-row" style={{ marginTop: 8 }}>
              <Button
                size="sm"
                variant="primary"
                icon={<IconTarget size={14} />}
                disabled={!camera?.running}
                onClick={() => send("calibration.sample")}
              >
                Take sample
              </Button>
              <Button
                size="sm"
                icon={<IconCheck size={14} />}
                disabled={!calibration?.sampleCount}
                onClick={() => send("calibration.auto")}
                title="Fit an HSV box around the collected samples"
              >
                Auto-fit box
              </Button>
            </div>
            <p style={{ fontSize: 11.5, color: "var(--ink-3)" }}>
              Point the centre box at a {COLOR_NAMES[target].toLowerCase()} sticker, take a few samples
              from different angles, then auto-fit. Repeat for each colour.
            </p>
          </Card>

          <Card title="Hue histogram" description="Live hue distribution of saturated pixels">
            <HueHistogram bins={calibration?.histogram ?? []} />
          </Card>
        </div>
      </div>

      {/* Sliders ------------------------------------------------------- */}
      <Card
        title={`HSV box · ${COLOR_NAMES[target]}`}
        description="OpenCV ranges: hue 0-179, saturation and value 0-255"
        actions={
          <Tag tone={calibration?.builtin ? "default" : "brand"}>
            {calibration?.profileName ?? "default"} {calibration?.builtin ? "(built-in)" : "(edited)"}
          </Tag>
        }
      >
        <div className="hsv-grid">
          {CHANNELS.map((channel) => (
            <SliderRow
              key={channel.key}
              label={channel.label}
              value={Number(range?.[channel.key] ?? 0)}
              min={0}
              max={channel.max}
              onChange={(value) =>
                send("calibration.range", { color: target, [channel.key]: value })
              }
            />
          ))}
        </div>

        <ToggleRow
          label="Hue wraps around 0"
          hint="Required for red, which straddles hue 179 → 0"
          checked={Boolean(range?.wrap_hue)}
          onChange={(value) => send("calibration.range", { color: target, wrap_hue: value })}
        />

        <div className="btn-row" style={{ marginTop: 6 }}>
          <Button size="sm" variant="primary" onClick={() => send("calibration.apply")}>
            Apply to live detector
          </Button>
        </div>
      </Card>

      {/* Detected colours + presets ------------------------------------ */}
      <div className="split">
        <Card title="All colour boxes" description="Every threshold in the active profile">
          <div className="hsv-table">
            {COLOR_CODES.map((code) => {
              const item = calibration?.ranges?.[code];
              return (
                <button
                  key={code}
                  type="button"
                  className="hsv-row"
                  data-active={target === code}
                  onClick={() => send("calibration.target", { color: code })}
                >
                  <span
                    className="detect-swatch"
                    style={{ background: CUBE_COLORS[code] }}
                    aria-hidden="true"
                  />
                  <b>{COLOR_NAMES[code]}</b>
                  <code>
                    H {item?.h_min ?? 0}–{item?.h_max ?? 0}
                    {item?.wrap_hue ? " (wrap)" : ""} · S {item?.s_min ?? 0}–{item?.s_max ?? 0} · V{" "}
                    {item?.v_min ?? 0}–{item?.v_max ?? 0}
                  </code>
                </button>
              );
            })}
          </div>
        </Card>

        <Card title="Presets" description="Save a profile per lighting setup and switch instantly">
          <div className="btn-row">
            {(calibration?.availableProfiles ?? []).map((name) => (
              <Button
                key={name}
                size="sm"
                variant={calibration?.activeProfile === name ? "primary" : "default"}
                onClick={() => send("calibration.preset", { name })}
              >
                {name}
              </Button>
            ))}
          </div>

          <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
            <input
              type="text"
              placeholder="my-desk-lamp"
              value={profileName}
              onChange={(event) => setProfileName(event.target.value)}
              style={{ flex: 1, minWidth: 160 }}
              aria-label="New profile name"
            />
            <Button
              icon={<IconSave size={15} />}
              disabled={!profileName.trim()}
              onClick={() => {
                send("calibration.save", { name: profileName.trim() });
                setProfileName("");
              }}
            >
              Save profile
            </Button>
          </div>

          <p style={{ fontSize: 11.5, color: "var(--ink-3)", marginTop: 6 }}>
            Saving also makes the profile active for detection. Built-in presets (default, low-light,
            legacy) cannot be overwritten.
          </p>

          {(calibration?.availableProfiles ?? [])
            .filter((name) => !["default", "low-light", "legacy"].includes(name))
            .map((name) => (
              <div key={name} className="kv">
                <span>{name}</span>
                <Button
                  size="sm"
                  variant="danger"
                  iconOnly
                  icon={<IconTrash size={14} />}
                  aria-label={`Delete ${name}`}
                  onClick={() => send("calibration.delete", { name })}
                />
              </div>
            ))}
        </Card>
      </div>
    </>
  );
}
