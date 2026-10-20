import { Button, Card, KeyValue, ProgressBar, Segmented, Tag, ToggleRow } from "@/components/ui";
import { CameraView, DetectionGrid, DetectionSummary } from "@/components/CameraView";
import { FaceGrid } from "@/components/cube";
import { PageHead, type PageId } from "@/components/layout";
import { IconPower, IconScan, IconTarget } from "@/components/Icons";
import { useApp } from "@/state/AppStore";
import { COLOR_NAMES, FACE_NAMES } from "@/lib/colors";
import { confidenceLabel, confidenceTone } from "@/lib/format";
import { FACE_ORDER } from "@/lib/types";

export default function CameraPage({ navigate }: { navigate: (page: PageId) => void }) {
  const { snapshot, detection, send } = useApp();
  const camera = snapshot?.camera;
  const scan = snapshot?.scan;
  const settings = snapshot?.settings;
  const running = Boolean(camera?.running);

  const currentFace = scan?.current ?? null;
  const steps = scan?.steps ?? [];
  const nextStep = steps.find((step) => step.face === currentFace) ?? null;
  const confidence = detection?.meanConfidence ?? 0;

  return (
    <>
      <PageHead
        title="Live Camera"
        description="Bilateral denoise → HSV conversion → 3×3 patch sampling → colour classification, drawn straight onto the frame."
        actions={
          <>
            <Button
              variant={running ? "danger" : "primary"}
              icon={<IconPower size={16} />}
              onClick={() => send(running ? "camera.stop" : "camera.start")}
            >
              {running ? "Stop camera" : "Start camera"}
            </Button>
            <Button
              icon={<IconScan size={16} />}
              onClick={() => {
                send("scan.start");
                navigate("scanner");
              }}
            >
              Go to scanner
            </Button>
          </>
        }
      />

      <div className="split">
        <Card className="card-pad-0">
          <CameraView
            showScanline={snapshot?.mode === "scan"}
            overlay={
              <>
                <DetectionSummary />
                <div className="viewport-badges" style={{ alignSelf: "flex-start" }}>
                  {nextStep && (
                    <Tag tone="brand">
                      <IconTarget size={12} /> Show {COLOR_NAMES[nextStep.center]} ·{" "}
                      {COLOR_NAMES[nextStep.top].toLowerCase()} on top
                    </Tag>
                  )}
                </div>
              </>
            }
          />
        </Card>

        <div style={{ display: "flex", flexDirection: "column", gap: "var(--sp-4)" }}>
          <Card title="Detection confidence" description="Per-sticker HSV classification quality">
            <ProgressBar
              value={confidence}
              label={
                <>
                  <span>Mean confidence</span>
                  <b style={{ marginLeft: "auto", color: "var(--ink)" }}>
                    {(confidence * 100).toFixed(0)}% · {confidenceLabel(confidence)}
                  </b>
                </>
              }
            />
            <div style={{ display: "flex", gap: 8, marginTop: 4, flexWrap: "wrap" }}>
              <Tag tone={confidenceTone(confidence)}>{confidenceLabel(confidence)} read</Tag>
              <Tag tone={detection?.stable ? "good" : "default"}>
                {detection?.stable ? "Stable across frames" : "Hold the cube steady"}
              </Tag>
              <Tag>min accepted {(settings?.min_confidence ?? 0.35).toFixed(2)}</Tag>
            </div>
            <DetectionGrid />
          </Card>

          <Card
            title="Current read"
            description="What the classifier would store if you captured now"
            actions={
              <Button
                size="sm"
                variant="primary"
                disabled={!running || !currentFace}
                onClick={() => send("scan.capture")}
              >
                Capture {currentFace ?? ""}
              </Button>
            }
          >
            <div style={{ display: "flex", gap: "var(--sp-4)", alignItems: "center" }}>
              <FaceGrid colors={detection?.colors ?? null} size={92} palette={settings?.cube_palette} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <KeyValue label="Target face">
                  {currentFace ? `${FACE_NAMES[currentFace]} (${currentFace})` : "all captured"}
                </KeyValue>
                <KeyValue label="Colours">
                  {detection?.colors.join(" ") ?? "—"}
                </KeyValue>
                <KeyValue label="Weakest sticker">
                  {detection ? `${(detection.minConfidence * 100).toFixed(0)}%` : "—"}
                </KeyValue>
              </div>
            </div>
            {nextStep && (
              <p style={{ fontSize: 12, color: "var(--ink-2)" }}>{nextStep.text}</p>
            )}
            {scan?.hint && (
              <p style={{ fontSize: 12, color: "var(--ink-3)" }}>{scan.hint}</p>
            )}
          </Card>
        </div>
      </div>

      <div className="grid grid-3">
        <Card title="Camera" description="Device telemetry">
          <KeyValue label="Status">{running ? "streaming" : "stopped"}</KeyValue>
          <KeyValue label="Device index">#{camera?.index ?? 0}</KeyValue>
          <KeyValue label="Resolution">{camera?.resolution?.join(" × ") ?? "—"}</KeyValue>
          <KeyValue label="Measured FPS">{(camera?.fps ?? 0).toFixed(1)}</KeyValue>
          <KeyValue label="Target FPS">{camera?.targetFps ?? 0}</KeyValue>
          <KeyValue label="Frames captured">{camera?.framesCaptured ?? 0}</KeyValue>
          <KeyValue label="Uptime">{camera?.uptimeSeconds ?? 0}s</KeyValue>
          {camera?.error && (
            <p style={{ fontSize: 12, color: "var(--status-critical)" }}>{camera.error}</p>
          )}
        </Card>

        <Card title="Overlay" description="What is drawn onto the frame">
          <ToggleRow
            label="Sampling grid"
            hint="Rounded chips at each sample point"
            checked={Boolean(settings?.show_grid)}
            onChange={(value) => send("settings.update", { show_grid: value })}
          />
          <ToggleRow
            label="Colour labels"
            checked={Boolean(settings?.show_labels)}
            onChange={(value) => send("settings.update", { show_labels: value })}
          />
          <ToggleRow
            label="Contour & reticle"
            checked={Boolean(settings?.show_bounding_box)}
            onChange={(value) => send("settings.update", { show_bounding_box: value })}
          />
          <ToggleRow
            label="Confidence bars"
            checked={Boolean(settings?.show_confidence)}
            onChange={(value) => send("settings.update", { show_confidence: value })}
          />
        </Card>

        <Card title="Face order" description="Suggested order. Any order works: each side is recognised by its centre colour.">
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {(steps.length ? steps.map((step) => step.face) : FACE_ORDER).map((face) => {
              const info = scan?.faces[face];
              const center = steps.find((step) => step.face === face)?.center;
              return (
                <button
                  key={face}
                  type="button"
                  className="face-row"
                  data-active={currentFace === face}
                  onClick={() => send("scan.face", { face })}
                  title={`Re-scan the ${FACE_NAMES[face]} face`}
                >
                  <b>{face}</b>
                  <span>{center ? `${COLOR_NAMES[center]} · ${FACE_NAMES[face]}` : FACE_NAMES[face]}</span>
                  {info?.captured ? (
                    <Tag tone="good">{((info.confidence ?? 0) * 100).toFixed(0)}%</Tag>
                  ) : (
                    <Tag>pending</Tag>
                  )}
                </button>
              );
            })}
          </div>
          <Segmented
            value={scan?.autoCapture ? "auto" : "manual"}
            options={[
              { value: "auto", label: "Auto capture" },
              { value: "manual", label: "Manual" },
            ]}
            onChange={(value) => send("scan.auto", { enabled: value === "auto" })}
          />
        </Card>
      </div>
    </>
  );
}
