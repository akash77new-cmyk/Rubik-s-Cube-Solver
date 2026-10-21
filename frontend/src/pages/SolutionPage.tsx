import { useEffect, useMemo, useState, type CSSProperties } from "react";
import { Button, Card, EmptyState, KeyValue, ProgressBar, SliderRow, Tag } from "@/components/ui";
import { Cube3D, SOLVED_FACELETS } from "@/components/cube";
import { CameraView } from "@/components/CameraView";
import { MoveGlyph, MoveStrip } from "@/components/move";
import { PageHead, type PageId } from "@/components/layout";
import { BarChart, ProportionBar } from "@/components/charts";
import {
  IconCamera,
  IconCheck,
  IconNext,
  IconPause,
  IconPlay,
  IconPrev,
  IconRestart,
  IconRoute,
  IconScan,
  IconShuffle,
} from "@/components/Icons";
import { useApp } from "@/state/AppStore";
import { formatMs } from "@/lib/format";
import { COLOR_NAMES, CUBE_COLORS } from "@/lib/colors";
import { FACE_ORDER, type ColorCode, type FaceKey, type Facelets } from "@/lib/types";

/** How to hold the cube for every instruction: the front colour facing you (the
 *  middle sticker) and the top colour on top. Same picture style as the scan guide. */
function HoldFigure({
  front,
  top,
  paint,
}: {
  front: ColorCode;
  top: ColorCode;
  paint: (code: ColorCode) => string;
}) {
  return (
    <div className="scan-guide-face hold-figure" aria-hidden="true">
      <span className="scan-guide-top" style={{ background: paint(top) }}>
        {COLOR_NAMES[top]} on top
      </span>
      <div className="scan-guide-grid">
        {Array.from({ length: 9 }, (_, index) => (
          <span key={index} style={index === 4 ? { background: paint(front) } : undefined} />
        ))}
      </div>
      <span className="hold-figure-caption">{COLOR_NAMES[front]} facing you</span>
    </div>
  );
}

/**
 * Auto play's time bar for the current move: it fills from 0 to `seconds` while a timer
 * counts up, and starts again from 0 for every move (`stepKey` changes) and whenever auto
 * play starts. The backend waits exactly `seconds` per move, so both stay in step. The
 * component keeps its own state, so only this bar re-renders on every animation frame.
 */
function StepTimer({ running, stepKey, seconds }: { running: boolean; stepKey: number; seconds: number }) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    setElapsed(0);
    if (!running) return undefined;
    const start = performance.now();
    let frame = 0;
    const tick = () => {
      setElapsed(Math.min((performance.now() - start) / 1000, seconds));
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [running, stepKey, seconds]);

  return (
    <div className="step-timer" data-running={running}>
      <div className="step-timer-head">
        <span>{running ? "Time for this move" : "Auto play is off"}</span>
        <b>{running ? `${elapsed.toFixed(1)} s / ${seconds} s` : `${seconds} s per move`}</b>
      </div>
      <div className="step-timer-track">
        <div className="step-timer-fill" style={{ width: `${(elapsed / seconds) * 100}%` }} />
      </div>
    </div>
  );
}

/** A one-off burst of cube-coloured confetti when the cube is solved (plain CSS: each
 *  piece gets its own position, colour, delay, speed, drift and spin). */
function Confetti({ paint }: { paint: (code: ColorCode) => string }) {
  const colours: ColorCode[] = ["W", "Y", "R", "O", "G", "B"];
  return (
    <div className="confetti" aria-hidden="true">
      {Array.from({ length: 36 }, (_, i) => (
        <span
          key={i}
          style={
            {
              left: `${(i * 37) % 100}%`,
              background: paint(colours[i % 6]),
              "--delay": `${(i % 9) * 0.09}s`,
              "--dur": `${2.2 + (i % 5) * 0.3}s`,
              "--drift": `${((i % 7) - 3) * 18}px`,
              "--spin": `${(i * 47) % 360}deg`,
            } as CSSProperties
          }
        />
      ))}
    </div>
  );
}

export default function SolutionPage({ navigate }: { navigate: (page: PageId) => void }) {
  const { snapshot, send } = useApp();
  const solution = snapshot?.solution;
  const playback = snapshot?.playback;
  const settings = snapshot?.settings;
  const executing = snapshot?.mode === "execute";

  const index = playback?.index ?? 0;
  const total = playback?.total ?? 0;

  const current = playback?.cube ?? solution?.states?.[index] ?? SOLVED_FACELETS;
  const previous: Facelets | null = useMemo(() => {
    if (!solution?.states || index <= 0) return null;
    return (solution.states[index - 1] as Facelets) ?? null;
  }, [solution?.states, index]);

  if (!solution) {
    return (
      <>
        <PageHead
          title="Solution Visualizer"
          description="Kociemba two-phase output, played back move by move with a synchronised 3D cube."
        />
        <Card>
          <EmptyState
            icon={<IconRoute size={30} />}
            title="No solution yet"
            message={
              snapshot?.cube
                ? "A valid cube state is loaded. Run the solver to generate a manoeuvre of at most 20 moves."
                : "Scan a cube or generate a demo scramble first, then run the solver."
            }
            action={
              <div className="btn-row" style={{ justifyContent: "center" }}>
                <Button
                  variant="primary"
                  icon={<IconRoute size={16} />}
                  disabled={!snapshot?.cube || snapshot?.solving}
                  loading={snapshot?.solving}
                  onClick={() => send("solve.run")}
                >
                  {snapshot?.solving ? "Searching…" : "Solve cube"}
                </Button>
                <Button icon={<IconShuffle size={16} />} onClick={() => send("cube.scramble", { length: 22 })}>
                  Demo scramble
                </Button>
                <Button variant="ghost" onClick={() => navigate("scanner")}>
                  Scan a cube
                </Button>
              </div>
            }
          />
          {snapshot?.solveError && (
            <p style={{ fontSize: 12.5, color: "var(--status-critical)", textAlign: "center" }}>
              {snapshot.solveError}
            </p>
          )}
        </Card>
      </>
    );
  }

  const faceData = FACE_ORDER.map((face) => ({
    label: face,
    value: solution.faceDistribution[face] ?? 0,
  }));

  // Every instruction assumes the cube is held with its front centre facing you and
  // its top centre on top. Centres never move, so the colours come from the cube.
  const centers = snapshot?.cube?.centers;
  const paint = (code: ColorCode) => settings?.cube_palette?.[code] ?? CUBE_COLORS[code];
  const centreDot = (face: FaceKey) =>
    centers ? <span className="face-dot" style={{ background: paint(centers[face]) }} /> : null;
  const centreName = (face: FaceKey, fallback: string) =>
    centers ? COLOR_NAMES[centers[face]].toLowerCase() : fallback;
  // Before move 1 the user confirms they hold the cube the right way (see "ready").
  const ready = playback?.ready ?? true;
  const shownNext = ready ? playback?.next : playback?.current;

  return (
    <>
      <PageHead
        title="Solution Visualizer"
        description={`${solution.moveCount} moves · ${solution.quarterTurnCount} quarter turns · found in ${formatMs(solution.elapsedMs)}`}
        actions={
          <>
            <Button
              variant={executing ? "primary" : "default"}
              icon={<IconCamera size={16} />}
              onClick={() => send(executing ? "playback.review" : "playback.execute")}
              title="Overlay the current move onto the live camera feed"
            >
              {executing ? "Exit guidance" : "Camera guidance"}
            </Button>
            <Button icon={<IconRestart size={16} />} onClick={() => send("playback.restart")}>
              Restart
            </Button>
          </>
        }
      />

      {/* Player -------------------------------------------------------- */}
      <div className="split">
        <Card className={playback?.completed ? "player-card is-solved" : "player-card"}>
          {playback?.completed && <Confetti paint={paint} />}
          {ready && (
            <p className="hold-note">
              Hold the cube with {centreDot("F")} <b>{centreName("F", "the front")}</b> facing you and{" "}
              {centreDot("U")} <b>{centreName("U", "the top")}</b> on top. Every step is from your
              point of view.
            </p>
          )}
          <div className="player-stage">
            {executing ? (
              <CameraView aspect="4 / 3" />
            ) : (
              <Cube3D
                facelets={current}
                move={playback?.previous ?? null}
                previousFacelets={previous}
                size={216}
                durationMs={Math.max(140, 420 / Math.max(settings?.animation_speed ?? 1, 0.25))}
                palette={settings?.cube_palette}
              />
            )}

            <div className="player-side">
              <div className="move-hero">
                {playback?.current && !ready ? (
                  <>
                    {centers && <HoldFigure front={centers.F} top={centers.U} paint={paint} />}
                    <p className="move-hero-instruction">
                      Before the first move, hold the cube like the picture:{" "}
                      {centreName("F", "the front")} facing you, {centreName("U", "the top")} on top.
                    </p>
                    <p className="move-hero-label">Keep holding it this way for every move.</p>
                    <Button variant="primary" size="sm" onClick={() => send("playback.next")}>
                      I'm holding it like this · show move 1
                    </Button>
                  </>
                ) : playback?.current ? (
                  <>
                    <MoveGlyph move={playback.current} size={148} key={`${playback.current.notation}-${index}`} />
                    <div className="move-hero-notation">{playback.current.notation}</div>
                    <p className="move-hero-instruction">{playback.current.instruction}</p>
                    <p className="move-hero-label">
                      {centreDot(playback.current.face)} {playback.current.label}
                    </p>
                    <StepTimer
                      running={Boolean(playback.playing)}
                      stepKey={index}
                      seconds={(settings?.autoplay_interval_ms ?? 8000) / 1000}
                    />
                  </>
                ) : (
                  <>
                    <span className="solved-badge">
                      <IconCheck size={38} />
                    </span>
                    <div className="solved-title">Cube solved!</div>
                    <p className="move-hero-label">All {total} moves done. Nice work!</p>
                    <Button
                      variant="primary"
                      size="sm"
                      icon={<IconScan size={14} />}
                      onClick={() => {
                        send("scan.reset");
                        navigate("scanner");
                      }}
                    >
                      Scan another cube
                    </Button>
                  </>
                )}
              </div>

              <div className="neighbour-row">
                <div className="neighbour" data-role="prev" title={playback?.previous?.instruction}>
                  <small>Previous</small>
                  <b>{playback?.previous?.notation ?? "—"}</b>
                </div>
                <div className="neighbour" data-role="next" title={shownNext?.instruction}>
                  <small>Next</small>
                  <b>{shownNext?.notation ?? "—"}</b>
                </div>
              </div>
            </div>
          </div>

          {/* Transport */}
          <div className="transport">
            <Button
              iconOnly
              icon={<IconRestart size={16} />}
              onClick={() => send("playback.restart")}
              aria-label="Restart"
              title="Restart (R)"
            />
            <Button
              iconOnly
              icon={<IconPrev size={16} />}
              onClick={() => send("playback.prev")}
              disabled={index === 0 && !ready}
              aria-label="Previous move"
              title="Previous move (←)"
            />
            <Button
              variant="primary"
              size="lg"
              icon={playback?.playing ? <IconPause size={17} /> : <IconPlay size={17} />}
              onClick={() => send(playback?.playing ? "playback.pause" : "playback.play")}
              disabled={index >= total}
            >
              {playback?.playing ? "Pause" : "Auto play"}
            </Button>
            <Button
              iconOnly
              icon={<IconNext size={16} />}
              onClick={() => send("playback.next")}
              disabled={index >= total}
              aria-label="Next move"
              title="Next move (→)"
            />
            <div className="transport-progress">
              <ProgressBar
                value={total ? index / total : 0}
                striped={playback?.playing}
                label={
                  <>
                    <span>
                      {ready ? `Move ${Math.min(index + 1, total)} of ${total}` : `Get ready · ${total} moves`}
                    </span>
                    <b style={{ marginLeft: "auto", color: "var(--ink)" }}>
                      {Math.round((playback?.progress ?? 0) * 100)}%
                    </b>
                  </>
                }
              />
            </div>
          </div>

          <SliderRow
            label="Auto play: time per move"
            hint="How long each move is shown before the next one"
            value={(settings?.autoplay_interval_ms ?? 8000) / 1000}
            min={1}
            max={20}
            step={0.5}
            suffix=" s"
            onChange={(value) => send("settings.update", { autoplay_interval_ms: Math.round(value * 1000) })}
          />
          <SliderRow
            label="Animation speed"
            hint="How fast the 3D cube turns"
            value={settings?.animation_speed ?? 1}
            min={0.25}
            max={3}
            step={0.25}
            suffix="×"
            onChange={(value) => send("settings.update", { animation_speed: value })}
          />
        </Card>

        <div style={{ display: "flex", flexDirection: "column", gap: "var(--sp-4)" }}>
          <Card title="Solution" description="Click any move to jump straight to it">
            <MoveStrip
              moves={solution.moves}
              index={index}
              onSelect={(position) => send("playback.seek", { index: position })}
            />
            <code className="notation-block">{solution.notation}</code>
          </Card>

          <Card title="Search result" description="Reported by the solver backend">
            <KeyValue label="Backend">{solution.backend}</KeyValue>
            <KeyValue label="Search time">{formatMs(solution.elapsedMs)}</KeyValue>
            <KeyValue label="Move count">{solution.moveCount}</KeyValue>
            <KeyValue label="Quarter turns">{solution.quarterTurnCount}</KeyValue>
            <KeyValue label="Facelet string">
              <span style={{ fontSize: 10 }}>{solution.faceletString.slice(0, 27)}…</span>
            </KeyValue>
          </Card>

          <Card title="Turn types" description="Clockwise, counter-clockwise and half turns">
            <ProportionBar
              segments={[
                { label: "Clockwise", value: solution.turnDistribution.cw ?? 0 },
                { label: "Counter-clockwise", value: solution.turnDistribution.ccw ?? 0 },
                { label: "Half turn (180°)", value: solution.turnDistribution.double ?? 0 },
              ]}
            />
          </Card>

          <Card title="Moves per face" description="How the solution loads each face">
            <BarChart data={faceData} />
          </Card>
        </div>
      </div>

      {/* Physical guidance --------------------------------------------- */}
      <Card
        title="Physical execution steps"
        description="Another way to follow the solution: half turns split into two quarter turns, and each back (B) move done by turning the whole cube around (↻), turning the front, then turning it back."
      >
        <div className="physical-strip">
          {(snapshot?.physicalSteps ?? []).map((step, position) => (
            <span
              key={`${step}-${position}`}
              className="physical-step"
              data-kind={step === "TURN_BACK" ? "rotate" : "turn"}
            >
              {step === "TURN_BACK" ? "↻ rotate cube" : step}
            </span>
          ))}
        </div>
        <p style={{ fontSize: 11.5, color: "var(--ink-3)" }}>
          {snapshot?.physicalSteps.length ?? 0} physical actions for {solution.moveCount} solver moves.
          Turn on <b>Camera guidance</b> to draw each arrow over the live feed.
        </p>
      </Card>

      {/* History ------------------------------------------------------- */}
      <Card title="Move history" description="Executed so far this run">
        {playback && playback.history.length > 0 ? (
          <div className="move-strip">
            {playback.history.map((move, position) => (
              <span key={`${move.notation}-${position}`} className="history-chip">
                <b>{position + 1}</b>
                {move.notation}
              </span>
            ))}
          </div>
        ) : (
          <p style={{ fontSize: 12.5, color: "var(--ink-3)" }}>
            No moves executed yet — press Auto play or step forward.
          </p>
        )}
        {playback?.completed && (
          <Tag tone="good">
            <IconCheck size={12} /> Solved — all {total} moves executed
          </Tag>
        )}
      </Card>
    </>
  );
}
