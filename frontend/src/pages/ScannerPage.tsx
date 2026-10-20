import { useState } from "react";
import { Button, Card, ProgressBar, Segmented, Tag, EmptyState } from "@/components/ui";
import { CameraView, DetectionSummary } from "@/components/CameraView";
import { CubeNet, FaceGrid } from "@/components/cube";
import { DatasetCard, scanHints } from "@/components/dataset";
import { ValidationIssueList, flaggedStickers } from "@/components/validation";
import { PageHead, type PageId } from "@/components/layout";
import { ColorSummary } from "@/components/charts";
import {
  IconAlert,
  IconCheck,
  IconRestart,
  IconRoute,
  IconScan,
  IconTarget,
} from "@/components/Icons";
import { useApp } from "@/state/AppStore";
import { FACE_NAMES } from "@/lib/colors";
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
        description="Six faces, captured in U → R → F → D → L → B order. Auto-capture fires once a read is stable across consecutive frames."
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
                  : "All faces captured, but the state is not solvable — fix the highlighted colours."
                : scan?.current
                  ? `Show the ${FACE_NAMES[scan.current]} face to the camera.`
                  : "Press Start scanning to begin."}
            </p>
            {scan?.hint && !complete && (
              <p style={{ fontSize: 11.5, color: "var(--ink-3)" }}>{scan.hint}</p>
            )}
          </div>
          {complete && (
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
          )}
        </div>
      </Card>

      {/* Live + tiles -------------------------------------------------- */}
      <div className="split">
        <Card className="card-pad-0">
          <CameraView
            showScanline={snapshot?.mode === "scan"}
            overlay={
              <>
                <DetectionSummary />
                <div className="viewport-badges" style={{ alignSelf: "flex-start" }}>
                  {scan?.current && (
                    <Tag tone="brand">
                      <IconTarget size={12} /> {FACE_NAMES[scan.current]} face · {scan.current}
                    </Tag>
                  )}
                  {detection?.stable && <Tag tone="good">ready to capture</Tag>}
                </div>
              </>
            }
          />
        </Card>

        <Card
          title="Capture"
          description="Manual override when auto-capture is off"
          actions={
            <Button
              size="sm"
              variant="primary"
              disabled={!snapshot?.camera.running || complete}
              onClick={() => send("scan.capture")}
            >
              Capture face
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

      {/* Face tiles ---------------------------------------------------- */}
      <Card title="Faces" description="Each tile fills in as its face is captured">
        <div className="scan-grid">
          {FACE_ORDER.map((face) => {
            const info = scan?.faces[face];
            const state = info?.captured ? "done" : scan?.current === face ? "active" : "idle";
            return (
              <div key={face} className="scan-tile" data-state={state}>
                <div className="scan-tile-head">
                  <b>{FACE_NAMES[face]}</b>
                  <span style={{ color: "var(--ink-3)", fontSize: 12 }}>{face}</span>
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
                  onClick={() => send("scan.face", { face })}
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
            flagged={complete && validation && !validation.ok ? flaggedStickers(validation.issues, selectedIssue) : undefined}
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
                <Button variant="primary" onClick={() => { send("solve.run"); navigate("solution"); }}>
                  Solve now
                </Button>
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
