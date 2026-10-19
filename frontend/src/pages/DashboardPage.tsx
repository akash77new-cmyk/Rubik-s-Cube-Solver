import { Card, StatTile, Button, ProgressBar, Tag, KeyValue, EmptyState } from "@/components/ui";
import { HeroCube, SOLVED_FACELETS } from "@/components/cube";
import { PageHead, type PageId } from "@/components/layout";
import { Sparkline } from "@/components/charts";
import {
  IconCamera,
  IconCheck,
  IconChip,
  IconCube,
  IconDroplet,
  IconPower,
  IconRoute,
  IconScan,
  IconShuffle,
  IconSparkle,
  IconTarget,
} from "@/components/Icons";
import { useApp } from "@/state/AppStore";
import { formatDuration, formatMs, percent } from "@/lib/format";
import { THEMES } from "@/lib/types";

export default function DashboardPage({ navigate }: { navigate: (page: PageId) => void }) {
  const { snapshot, send } = useApp();
  const theme = snapshot?.settings.theme ?? "dark";
  const camera = snapshot?.camera;
  const solver = snapshot?.solver;
  const analytics = snapshot?.analytics;
  const scan = snapshot?.scan;
  const solution = snapshot?.solution;

  const facelets = snapshot?.playback.cube ?? snapshot?.cube?.facelets ?? SOLVED_FACELETS;
  const timeline = analytics?.timeline ?? [];

  const systems = [
    {
      label: "Web server",
      ok: true,
      detail: "Flask + Socket.IO relay",
    },
    {
      label: "Vision engine",
      ok: Boolean(snapshot),
      detail: snapshot ? "connected over TCP socket" : "waiting for engine process",
    },
    {
      label: "Camera",
      ok: Boolean(camera?.running),
      detail: camera?.running
        ? `device #${camera.index} · ${camera.resolution?.join("x") ?? "—"} · ${camera.fps.toFixed(0)} fps`
        : camera?.error ?? "not started",
    },
    {
      label: "Solver",
      ok: Boolean(solver?.ready),
      detail: solver?.message ?? "initialising",
    },
  ];

  return (
    <>
      <PageHead
        title="Real-Time Cube Solver"
        description="End-to-end computer-vision pipeline: scan a physical cube, solve it with the Kociemba two-phase algorithm, and follow the moves."
        actions={
          <>
            <Button
              variant="primary"
              icon={<IconSparkle size={16} />}
              onClick={() => navigate("scanner")}
            >
              Start scanning
            </Button>
            <Button icon={<IconShuffle size={16} />} onClick={() => send("cube.scramble", { length: 22 })}>
              Demo scramble
            </Button>
          </>
        }
      />

      {/* Hero ---------------------------------------------------------- */}
      <div className="split split-stretch">
        <Card accent className="hero-card">
          <div className="hero-layout">
            <div>
              <Tag tone="brand">
                <IconChip size={12} /> {solver?.backend ?? "solver warming up"}
              </Tag>
              <h2 style={{ fontSize: 26, letterSpacing: "-0.03em", margin: "12px 0 8px" }}>
                {solution
                  ? `Solution ready · ${solution.moveCount} moves`
                  : snapshot?.cube
                    ? "Cube captured · ready to solve"
                    : "Scan a cube to begin"}
              </h2>
              <p style={{ color: "var(--ink-2)", fontSize: 13.5, maxWidth: 460 }}>
                {solution
                  ? `Found in ${formatMs(solution.elapsedMs)} using ${solution.backend}. Open the solution player to follow the moves one at a time.`
                  : snapshot?.cube
                    ? "The cube state is valid. Run the two-phase search to generate an optimal-length solution."
                    : "Point your webcam at each face of the cube. The HSV segmentation pipeline reads the stickers and builds the cube state automatically."}
              </p>

              <div style={{ marginTop: 18, maxWidth: 420 }}>
                <ProgressBar
                  value={(scan?.count ?? 0) / 6}
                  striped={snapshot?.mode === "scan"}
                  label={
                    <>
                      <span>Scan progress</span>
                      <b style={{ marginLeft: "auto", color: "var(--ink)" }}>{scan?.count ?? 0}/6 faces</b>
                    </>
                  }
                />
              </div>

              <div className="btn-row" style={{ marginTop: 18 }}>
                <Button
                  variant="primary"
                  icon={<IconRoute size={16} />}
                  disabled={!snapshot?.cube || snapshot?.solving}
                  loading={snapshot?.solving}
                  onClick={() => {
                    send("solve.run");
                    navigate("solution");
                  }}
                >
                  {snapshot?.solving ? "Solving" : "Solve cube"}
                </Button>
                <Button icon={<IconCube size={16} />} onClick={() => navigate("viewer")}>
                  Inspect state
                </Button>
              </div>
            </div>

            <HeroCube facelets={facelets} />
          </div>
        </Card>

        <Card title="System status" description="Live health of every stage">
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {systems.map((system) => (
              <div key={system.label} className="system-row">
                <span className="system-dot" data-ok={system.ok} />
                <div style={{ minWidth: 0 }}>
                  <b style={{ fontSize: 13 }}>{system.label}</b>
                  <p style={{ fontSize: 11.5, color: "var(--ink-3)" }}>{system.detail}</p>
                </div>
                <Tag tone={system.ok ? "good" : "warning"}>{system.ok ? "OK" : "idle"}</Tag>
              </div>
            ))}
          </div>

          <div className="btn-row" style={{ marginTop: 6 }}>
            <Button
              size="sm"
              icon={<IconPower size={14} />}
              variant={camera?.running ? "danger" : "default"}
              onClick={() => send(camera?.running ? "camera.stop" : "camera.start")}
            >
              {camera?.running ? "Stop camera" : "Start camera"}
            </Button>
          </div>

          <div className="theme-picker">
            <div className="theme-picker-head">
              <b>Appearance</b>
              <span>{THEMES.find((t) => t.value === theme)?.hint}</span>
            </div>
            <div className="theme-swatches">
              {THEMES.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  className="theme-swatch"
                  data-variant={option.value}
                  data-active={theme === option.value}
                  onClick={() => send("settings.update", { theme: option.value })}
                  title={option.hint}
                  aria-pressed={theme === option.value}
                >
                  <span className="theme-swatch-preview" aria-hidden="true">
                    <i />
                    <i />
                    <i />
                  </span>
                  {option.label}
                </button>
              ))}
            </div>
          </div>
        </Card>
      </div>

      {/* Stats --------------------------------------------------------- */}
      <div className="grid grid-4 stagger">
        <StatTile
          label="Cubes solved"
          value={analytics?.totalSolves ?? 0}
          icon={<IconCheck size={13} />}
          hint={`${analytics?.sessionSolves ?? 0} this session`}
          tint="rgba(12,163,12,0.2)"
        />
        <StatTile
          label="Avg move count"
          value={analytics?.averageMoveCount ?? 0}
          digits={1}
          icon={<IconRoute size={13} />}
          hint={
            timeline.length > 1 ? (
              <Sparkline values={timeline.map((t) => t.moveCount)} />
            ) : (
              "Kociemba stays under 21"
            )
          }
        />
        <StatTile
          label="Avg solve time"
          value={analytics?.averageSolveMs ?? 0}
          unit="ms"
          digits={0}
          icon={<IconChip size={13} />}
          hint="Two-phase search only"
          tint="rgba(34,211,238,0.18)"
        />
        <StatTile
          label="Detection accuracy"
          value={(analytics?.detectionAccuracy ?? 0) * 100}
          unit="%"
          digits={1}
          icon={<IconTarget size={13} />}
          hint="Mean sticker confidence"
          tint="rgba(245,158,11,0.18)"
        />
      </div>

      {/* Quick actions + recent ---------------------------------------- */}
      <div className="split">
        <Card title="Quick actions" description="Everything you need for a full run">
          <div className="quick-grid">
            <QuickAction
              icon={<IconCamera />}
              title={camera?.running ? "Camera running" : "Start camera"}
              detail={camera?.running ? `${camera.fps.toFixed(0)} fps live` : "Open the capture device"}
              onClick={() => {
                if (!camera?.running) send("camera.start");
                navigate("camera");
              }}
            />
            <QuickAction
              icon={<IconScan />}
              title="Scan cube"
              detail={`${scan?.count ?? 0} of 6 faces captured`}
              onClick={() => {
                send("scan.start");
                navigate("scanner");
              }}
            />
            <QuickAction
              icon={<IconRoute />}
              title="Solve cube"
              detail={solution ? `${solution.moveCount} moves ready` : "Run the two-phase search"}
              disabled={!snapshot?.cube}
              onClick={() => {
                send("solve.run");
                navigate("solution");
              }}
            />
            <QuickAction
              icon={<IconDroplet />}
              title="HSV calibration"
              detail={`Profile: ${snapshot?.settings.active_profile ?? "default"}`}
              onClick={() => navigate("calibration")}
            />
          </div>
        </Card>

        <Card title="Recent solves" description="Last few completed runs">
          {analytics && analytics.recent.length > 0 ? (
            <div style={{ display: "flex", flexDirection: "column" }}>
              {analytics.recent.slice(0, 5).map((record) => (
                <KeyValue key={record.id} label={`${record.move_count} moves · ${record.source}`}>
                  {formatDuration(record.execution_seconds)} · {formatMs(record.solve_ms)}
                </KeyValue>
              ))}
              <div style={{ marginTop: 12 }}>
                <Button size="sm" variant="ghost" onClick={() => navigate("analytics")}>
                  View full analytics →
                </Button>
              </div>
            </div>
          ) : (
            <EmptyState
              icon={<IconSparkle size={26} />}
              title="No solves yet"
              message="Scan a cube or generate a demo scramble, then run the solver to populate your analytics."
              action={
                <Button size="sm" onClick={() => send("cube.scramble", { length: 22 })}>
                  Generate scramble
                </Button>
              }
            />
          )}
        </Card>
      </div>

      {/* Pipeline explainer -------------------------------------------- */}
      <Card title="Pipeline" description="What happens between the camera and the solution">
        <div className="pipeline">
          {[
            { step: "01", name: "Capture", detail: "Threaded OpenCV grab, mirrored, paced to target FPS" },
            { step: "02", name: "Segment", detail: "Bilateral denoise → HSV → 3×3 patch median" },
            { step: "03", name: "Classify", detail: "Six HSV boxes → colour + confidence" },
            { step: "04", name: "Model", detail: "54 facelets → validated cube state" },
            { step: "05", name: "Solve", detail: "Kociemba two-phase search ≤ 20 moves" },
            { step: "06", name: "Guide", detail: "Animated 3D playback + arrow overlays" },
          ].map((stage) => (
            <div key={stage.step} className="pipeline-step">
              <span className="pipeline-num">{stage.step}</span>
              <b>{stage.name}</b>
              <p>{stage.detail}</p>
            </div>
          ))}
        </div>
        <p style={{ fontSize: 11.5, color: "var(--ink-3)" }}>
          Detection accuracy is the running mean sticker confidence over{" "}
          {percent(analytics?.detectionAccuracy ?? 0, 1)} of sampled frames this session.
        </p>
      </Card>
    </>
  );
}

function QuickAction({
  icon,
  title,
  detail,
  onClick,
  disabled = false,
}: {
  icon: React.ReactNode;
  title: string;
  detail: string;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button type="button" className="quick-action" onClick={onClick} disabled={disabled}>
      <span className="quick-icon">{icon}</span>
      <b>{title}</b>
      <small>{detail}</small>
    </button>
  );
}
