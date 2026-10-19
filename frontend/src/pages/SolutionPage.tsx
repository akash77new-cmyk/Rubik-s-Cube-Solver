import { useMemo } from "react";
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
  IconShuffle,
} from "@/components/Icons";
import { useApp } from "@/state/AppStore";
import { formatMs } from "@/lib/format";
import { FACE_ORDER, type Facelets } from "@/lib/types";

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
        <Card className="player-card">
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
                {playback?.current ? (
                  <>
                    <MoveGlyph move={playback.current} size={148} key={`${playback.current.notation}-${index}`} />
                    <div className="move-hero-notation">{playback.current.notation}</div>
                    <p style={{ fontSize: 12.5, color: "var(--ink-2)" }}>{playback.current.label}</p>
                  </>
                ) : (
                  <>
                    <IconCheck size={44} />
                    <div className="move-hero-notation">Done</div>
                    <p style={{ fontSize: 12.5, color: "var(--ink-2)" }}>Cube solved</p>
                  </>
                )}
              </div>

              <div className="neighbour-row">
                <div className="neighbour" data-role="prev">
                  <small>Previous</small>
                  <b>{playback?.previous?.notation ?? "—"}</b>
                </div>
                <div className="neighbour" data-role="next">
                  <small>Next</small>
                  <b>{playback?.next?.notation ?? "—"}</b>
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
              disabled={index === 0}
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
                    <span>Move {Math.min(index + 1, total)} of {total}</span>
                    <b style={{ marginLeft: "auto", color: "var(--ink)" }}>
                      {Math.round((playback?.progress ?? 0) * 100)}%
                    </b>
                  </>
                }
              />
            </div>
          </div>

          <SliderRow
            label="Playback speed"
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
        description="A person cannot turn the hidden back face directly, so B moves become a whole-cube rotation plus a front turn."
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
