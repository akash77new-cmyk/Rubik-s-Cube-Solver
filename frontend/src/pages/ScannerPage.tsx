import { useEffect, useRef, useState } from "react";
import { Button, Card, ProgressBar, Segmented, Tag, EmptyState } from "@/components/ui";
import { CameraView, DetectionSummary } from "@/components/CameraView";
import { CubeNet, FaceGrid } from "@/components/cube";
import { DatasetCard, scanHints } from "@/components/dataset";
import { ScanGuide } from "@/components/scanGuide";
import { ValidationIssueList, flaggedStickers } from "@/components/validation";
import { RepairPanel, repairStickers } from "@/components/repair";
import { PageHead, type PageId } from "@/components/layout";
import { ColorSummary } from "@/components/charts";
import {
  IconAlert,
  IconCheck,
  IconGraduation,
  IconRestart,
  IconRoute,
  IconScan,
  IconSparkle,
  IconTarget,
} from "@/components/Icons";
import { useApp } from "@/state/AppStore";
import { COLOR_NAMES, FACE_NAMES } from "@/lib/colors";
import { COLOR_CODES, FACE_ORDER, type ColorCode } from "@/lib/types";

export default function ScannerPage({ navigate }: { navigate: (page: PageId) => void }) {
  const { snapshot, detection, send } = useApp();
  const [selectedIssue, setSelectedIssue] = useState<number | null>(null);
  const scan = snapshot?.scan;
  const settings = snapshot?.settings;
  const validation = snapshot?.validation;
  const scanned = scan?.count ?? 0;
  const complete = scanned === 6;
  const hints = scanHints(scan);
  const steps = scan?.steps ?? [];
  const nextStep = steps.find((step) => step.face === scan?.current) ?? null;
  // Auto-capture hold timer: a side is captured once it has been held still this long.
  const holding = snapshot?.mode === "scan" && Boolean(scan?.autoCapture && snapshot?.camera.running);
  const hold = holding ? detection?.hold ?? 0 : 0;
  const holdStep = steps.find((step) => step.face === detection?.holdFace) ?? null;
  const holdSeconds = ((settings?.auto_capture_hold_ms ?? 1000) / 1000).toFixed(1);

  // Manual capture (the default): the button names the side it will store, and only
  // turns on for a steady, confident read of a side that still needs scanning.
  const seenStep = steps.find((step) => step.center === detection?.colors?.[4]) ?? null;
  const outerConfident = (detection?.readings ?? [])
    .filter((reading) => reading.index !== 4) // the centre often carries a logo
    .every((reading) => reading.confidence >= (settings?.min_confidence ?? 0.35));
  function manualCapture(): { ok: boolean; label: string } {
    if (!snapshot?.camera.running) return { ok: false, label: "Starting the camera…" };
    if (!detection?.stable || !outerConfident) {
      return { ok: false, label: "Hold the side still in the frame…" };
    }
    if (seenStep?.done) {
      return { ok: false, label: `${COLOR_NAMES[seenStep.center]} is already captured: show the next side` };
    }
    const side = seenStep ?? nextStep;
    return { ok: true, label: side ? `Capture the ${COLOR_NAMES[side.center]} side` : "Capture this side" };
  }
  const capture = manualCapture();

  // When scanning starts, scroll so the camera and the guide fill the screen together.
  const scanArea = useRef<HTMLDivElement>(null);
  const previousMode = useRef(snapshot?.mode);
  useEffect(() => {
    if (snapshot?.mode === "scan" && previousMode.current !== "scan") {
      scanArea.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
    previousMode.current = snapshot?.mode;
  }, [snapshot?.mode]);

  // The one thing to do now, shown right under the guide's current step.
  let guideAction = (
    <Button variant="primary" icon={<IconScan size={16} />} onClick={() => send("scan.start")}>
      Start scanning
    </Button>
  );
  if (snapshot?.mode === "scan" && scan?.autoCapture) {
    guideAction = (
      <ProgressBar
        value={hold}
        label={
          <>
            <span>
              {holdStep && hold > 0
                ? `Hold still: capturing ${COLOR_NAMES[holdStep.center]}`
                : `Hold a side still for ${holdSeconds} s to capture it`}
            </span>
            <b style={{ marginLeft: "auto", color: "var(--ink)" }}>{Math.round(hold * 100)}%</b>
          </>
        }
      />
    );
  } else if (snapshot?.mode === "scan") {
    guideAction = (
      <Button
        variant="primary"
        icon={<IconTarget size={16} />}
        disabled={!capture.ok}
        onClick={() => send("scan.capture")}
      >
        {capture.label}
      </Button>
    );
  }

  const counts = COLOR_CODES.reduce(
    (accumulator, code) => {
      accumulator[code] = 0;
      return accumulator;
    },
    {} as Record<ColorCode, number>,
  );
  for (const face of FACE_ORDER) {
    for (const code of scan?.faces[face]?.colors ?? []) {
      if (code in counts) counts[code] += 1;
    }
  }

  return (
    <>
      <PageHead
        title="Scanning Pipeline"
        description="Six sides, each recognised by its centre colour, so any order works. Press Capture for each side, or switch to Auto to capture a side once it's held still."
        actions={
          <>
            <Segmented
              value={scan?.autoCapture ? "auto" : "manual"}
              options={[
                { value: "auto", label: "Auto" },
                { value: "manual", label: "Manual" },
              ]}
              onChange={(value) => send("scan.auto", { enabled: value === "auto" })}
            />
            <Button icon={<IconRestart size={16} />} onClick={() => send("scan.reset")}>
              Reset
            </Button>
            <Button variant="primary" icon={<IconScan size={16} />} onClick={() => send("scan.start")}>
              Start scanning
            </Button>
          </>
        }
      />

      {/* Progress ------------------------------------------------------ */}
      <Card accent>
        <div style={{ display: "flex", alignItems: "center", gap: "var(--sp-4)", flexWrap: "wrap" }}>
          <div className="scan-counter">
            <b>{scanned}</b>
            <span>/6</span>
          </div>
          <div style={{ flex: 1, minWidth: 220 }}>
            <ProgressBar value={scanned / 6} striped={snapshot?.mode === "scan"} />
            <p style={{ fontSize: 12.5, color: "var(--ink-2)", marginTop: 8 }}>
              {complete
                ? validation?.ok
                  ? "All six faces captured and the cube state is valid."
                  : "All faces captured, but the cube is not solvable: the repair agent looks for misread stickers."
                : snapshot?.mode !== "scan"
                  ? "Press Start scanning, then follow the guide beside the camera."
                  : scan?.autoCapture
                    ? "Follow the guide: each side is captured once it's held still."
                    : "Follow the guide and press Capture for each side."}
            </p>
          </div>
          {complete && (
            <div className="btn-row">
              <Button
                variant="primary"
                icon={<IconRoute size={16} />}
                disabled={!validation?.ok || snapshot?.solving}
                loading={snapshot?.solving}
                onClick={() => {
                  send("solve.run");
                  navigate("solution");
                }}
              >
                Solve this cube
              </Button>
              <Button
                icon={<IconGraduation size={16} />}
                disabled={!validation?.ok}
                title="Solve it yourself, stage by stage, with the AI tutor"
                onClick={() => {
                  send("learn.start");
                  navigate("learn");
                }}
              >
                Solve & Learn
              </Button>
            </div>
          )}
        </div>
      </Card>

      {/* Live camera + guide, side by side so both stay in view ------- */}
      <div className="split scan-split" ref={scanArea}>
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
                  {scan?.autoCapture
                    ? hold > 0 && <Tag tone="good">Hold still · {Math.round(hold * 100)}%</Tag>
                    : snapshot?.mode === "scan" && capture.ok && <Tag tone="good">ready to capture</Tag>}
                </div>
              </>
            }
          />
        </Card>

        <div className="scan-side">
          {!complete && (
            <Card title="Scan guide" description="Show each side to the camera, as pictured">
              <ScanGuide scan={scan} palette={settings?.cube_palette} action={guideAction} />
            </Card>
          )}

          {complete && (validation?.ok === false || snapshot?.repair) && (
            <Card
              title="Smart repair"
              description="An unsolvable scan means the camera misread something: this finds what"
              icon={<IconSparkle size={16} />}
            >
              <RepairPanel />
            </Card>
          )}

          <Card
            title="Live read"
            description="What the camera sees right now"
            actions={
              <Button
                size="sm"
                disabled={!snapshot?.camera.running || complete}
                onClick={() => send("scan.capture")}
                title="Capture even if the read is not steady yet (e.g. a logo hides the centre)"
              >
                Capture anyway
              </Button>
            }
          >
            <div style={{ display: "flex", gap: "var(--sp-4)", alignItems: "center" }}>
              <FaceGrid colors={detection?.colors ?? null} size={98} palette={settings?.cube_palette} />
              <div style={{ fontSize: 12.5, color: "var(--ink-2)" }}>
                <p>
                  <b style={{ color: "var(--ink)" }}>Live read</b>
                </p>
                <p style={{ color: "var(--ink-3)" }}>
                  {detection
                    ? `${detection.colors.join(" ")} · weakest ${(detection.minConfidence * 100).toFixed(0)}%`
                    : "No frame analysed yet"}
                </p>
              </div>
            </div>

            <h4 style={{ fontSize: 12, marginTop: 8, color: "var(--ink-3)" }}>Colour census</h4>
            <ColorSummary counts={counts} />
          </Card>
        </div>
      </div>

      {/* Face tiles ---------------------------------------------------- */}
      <Card title="Faces" description="Each tile fills in as its face is captured">
        <div className="scan-grid">
          {(steps.length ? steps.map((step) => step.face) : FACE_ORDER).map((face) => {
            const info = scan?.faces[face];
            const center = steps.find((step) => step.face === face)?.center;
            const state = info?.captured ? "done" : scan?.current === face ? "active" : "idle";
            return (
              <div key={face} className="scan-tile" data-state={state}>
                <div className="scan-tile-head">
                  <b>{center ? COLOR_NAMES[center] : FACE_NAMES[face]}</b>
                  <span style={{ color: "var(--ink-3)", fontSize: 12 }}>
                    {FACE_NAMES[face]} · {face}
                  </span>
                  {info?.captured ? (
                    <Tag tone="good">
                      <IconCheck size={11} /> {((info.confidence ?? 0) * 100).toFixed(0)}%
                    </Tag>
                  ) : state === "active" ? (
                    <Tag tone="brand">scanning</Tag>
                  ) : (
                    <Tag>waiting</Tag>
                  )}
                </div>
                <FaceGrid colors={info?.colors ?? null} size={88} palette={settings?.cube_palette} />
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    send("scan.face", { face });
                    if (!snapshot?.camera.running) send("camera.start"); // it turns off after a valid scan
                  }}
                  title={`Re-scan the ${FACE_NAMES[face]} face`}
                >
                  {info?.captured ? "Re-scan" : "Scan this"}
                </Button>
              </div>
            );
          })}
        </div>
      </Card>

      {/* Net + validation ---------------------------------------------- */}
      <div className="split">
        <Card title="Assembled net" description="Live unfolded view of everything captured so far">
          <CubeNet
            facelets={
              scan
                ? (Object.fromEntries(
                    FACE_ORDER.map((face) => [face, scan.faces[face]?.colors ?? undefined]),
                  ) as never)
                : null
            }
            capturedFaces={Object.fromEntries(
              FACE_ORDER.map((face) => [face, Boolean(scan?.faces[face]?.captured)]),
            )}
            activeFace={scan?.current ?? null}
            palette={settings?.cube_palette}
            flagged={
              complete && validation && !validation.ok
                ? repairStickers(snapshot?.repair) ?? flaggedStickers(validation.issues, selectedIssue)
                : undefined
            }
            uncertain={hints.uncertain}
            notes={hints.notes}
          />
          {Object.keys(hints.notes).length > 0 && (
            <p style={{ fontSize: 11.5, color: "var(--ink-3)", marginTop: 8 }}>
              {hints.uncertain.size > 0 &&
                "Dashed amber outline: the camera was unsure about this sticker (outside every colour range, or inside two). Check it against your cube. "}
              Hover a sticker to see what the camera saw.
            </p>
          )}
        </Card>

        <Card title="Validation" description="Checks run before the solver is allowed to start">
          {!complete ? (
            <EmptyState
              icon={<IconScan size={26} />}
              title={`${6 - scanned} face${6 - scanned === 1 ? "" : "s"} to go`}
              message="Validation runs automatically once all six faces are captured."
            />
          ) : validation?.ok ? (
            <EmptyState
              icon={<IconCheck size={26} />}
              title="Cube state is valid"
              message="Every piece is real, and twist, flip and parity all check out."
              action={
                <div className="btn-row" style={{ justifyContent: "center" }}>
                  <Button variant="primary" onClick={() => { send("solve.run"); navigate("solution"); }}>
                    Solve now
                  </Button>
                  <Button icon={<IconGraduation size={16} />} onClick={() => { send("learn.start"); navigate("learn"); }}>
                    Solve & Learn
                  </Button>
                </div>
              }
            />
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <Tag tone="critical">
                <IconAlert size={12} /> {validation?.errors.length ?? 0} problem(s)
              </Tag>
              <ValidationIssueList issues={validation?.issues ?? []} selected={selectedIssue} onSelect={setSelectedIssue} />
              <p style={{ fontSize: 11.5, color: "var(--ink-3)" }}>
                Click a problem to outline its stickers on the net. Fix them on the Cube Viewer page, or
                re-scan the affected face.
              </p>
              <p style={{ fontSize: 11.5, color: "var(--ink-3)" }}>
                Why a cube can be impossible: only 1 in 12 ways of putting the pieces together can be
                solved. Face turns never twist one corner, flip one edge, or swap just two pieces.
              </p>
              <Button size="sm" onClick={() => navigate("viewer")}>
                Open cube editor
              </Button>
            </div>
          )}
        </Card>
      </div>

      <DatasetCard />
    </>
  );
}
