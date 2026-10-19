import { Button, Card, EmptyState, KeyValue, ProgressBar, StatTile, Tag } from "@/components/ui";
import { BarChart, DataTable, LineChart, ProportionBar } from "@/components/charts";
import { PageHead, type PageId } from "@/components/layout";
import {
  IconAnalytics,
  IconCheck,
  IconChip,
  IconRoute,
  IconTarget,
  IconTrash,
} from "@/components/Icons";
import { useApp } from "@/state/AppStore";
import { formatDuration, formatMs, formatRelative } from "@/lib/format";
import { FACE_ORDER } from "@/lib/types";

export default function AnalyticsPage({ navigate }: { navigate: (page: PageId) => void }) {
  const { snapshot, send } = useApp();
  const analytics = snapshot?.analytics;
  const solution = snapshot?.solution;
  const playback = snapshot?.playback;
  const solver = snapshot?.solver;

  const timeline = analytics?.timeline ?? [];
  const hasData = (analytics?.totalSolves ?? 0) > 0;

  return (
    <>
      <PageHead
        title="Analytics"
        description="Move history, solution time, move count and solving progress — recorded for every completed run."
        actions={
          <Button
            variant="danger"
            icon={<IconTrash size={16} />}
            onClick={() => send("analytics.clear")}
            disabled={!hasData}
          >
            Clear history
          </Button>
        }
      />

      {/* Headline tiles ------------------------------------------------ */}
      <div className="grid grid-4 stagger">
        <StatTile
          label="Solution time"
          value={solution?.elapsedMs ?? analytics?.averageSolveMs ?? 0}
          unit="ms"
          digits={solution ? 1 : 0}
          icon={<IconChip size={13} />}
          hint={solution ? "current solution" : "session average"}
          tint="rgba(34,211,238,0.2)"
        />
        <StatTile
          label="Move count"
          value={solution?.moveCount ?? analytics?.averageMoveCount ?? 0}
          digits={solution ? 0 : 1}
          icon={<IconRoute size={13} />}
          hint={solution ? `${solution.quarterTurnCount} quarter turns` : "session average"}
        />
        <StatTile
          label="Avg solve time"
          value={analytics?.averageSolveMs ?? 0}
          unit="ms"
          icon={<IconAnalytics size={13} />}
          hint={`across ${analytics?.totalSolves ?? 0} solves`}
        />
        <StatTile
          label="Cubes solved"
          value={analytics?.totalSolves ?? 0}
          icon={<IconCheck size={13} />}
          hint={`${analytics?.sessionSolves ?? 0} this session`}
          tint="rgba(12,163,12,0.2)"
        />
      </div>

      <div className="grid grid-4 stagger">
        <StatTile
          label="Current solver"
          value={solver?.backend ?? "—"}
          animate={false}
          icon={<IconChip size={13} />}
          hint={solver?.ready ? "ready" : solver?.state ?? "initialising"}
        />
        <StatTile
          label="Detection accuracy"
          value={(analytics?.detectionAccuracy ?? 0) * 100}
          unit="%"
          digits={1}
          icon={<IconTarget size={13} />}
          hint="running mean sticker confidence"
          tint="rgba(245,158,11,0.2)"
        />
        <StatTile
          label="Best solve"
          value={analytics?.bestMoveCount ?? 0}
          unit=" moves"
          icon={<IconRoute size={13} />}
          hint="fewest moves recorded"
        />
        <StatTile
          label="Session length"
          value={formatDuration(analytics?.sessionSeconds ?? 0)}
          icon={<IconAnalytics size={13} />}
          hint={`${analytics?.totalMoves ?? 0} moves total`}
          animate={false}
        />
      </div>

      {/* Progress ------------------------------------------------------ */}
      <Card title="Solving progress" description="Live position within the current solution">
        {solution && playback ? (
          <>
            <ProgressBar
              value={playback.progress}
              striped={playback.playing}
              label={
                <>
                  <span>
                    Move {Math.min(playback.index + 1, playback.total)} of {playback.total}
                    {playback.current ? ` · ${playback.current.notation}` : ""}
                  </span>
                  <b style={{ marginLeft: "auto", color: "var(--ink)" }}>
                    {Math.round(playback.progress * 100)}%
                  </b>
                </>
              }
            />
            <div className="btn-row" style={{ marginTop: 6 }}>
              <Tag tone={playback.completed ? "good" : "brand"}>
                {playback.completed ? "completed" : playback.playing ? "auto playing" : "paused"}
              </Tag>
              <Tag>{playback.history.length} executed</Tag>
              <Tag>{playback.total - playback.index} remaining</Tag>
              <Button size="sm" variant="ghost" onClick={() => navigate("solution")}>
                Open player →
              </Button>
            </div>
          </>
        ) : (
          <p style={{ fontSize: 12.5, color: "var(--ink-3)" }}>
            No active solution. Solve a cube to track progress here.
          </p>
        )}
      </Card>

      {/* Charts -------------------------------------------------------- */}
      <div className="split">
        <Card
          title="Move count per solve"
          description="Kociemba's two-phase search keeps solutions at or below 20 moves"
        >
          {timeline.length > 1 ? (
            <LineChart
              points={timeline.map((item) => ({
                x: item.index,
                y: item.moveCount,
                caption: `solve #${item.index} · ${formatMs(item.solveMs)}`,
              }))}
              unit=" moves"
              label="Hover a point for the search time of that solve."
            />
          ) : (
            <EmptyState
              icon={<IconAnalytics size={26} />}
              title="Not enough data"
              message="Complete at least two solves to see the trend."
            />
          )}
        </Card>

        <Card title="Move distribution" description="Total turns per face across all solves">
          <BarChart
            data={FACE_ORDER.map((face) => ({
              label: face,
              value: analytics?.faceDistribution[face] ?? 0,
            }))}
          />
        </Card>
      </div>

      <div className="split">
        <Card title="Turn types" description="How the solver balances quarter and half turns">
          <ProportionBar
            segments={[
              { label: "Clockwise", value: analytics?.turnDistribution.cw ?? 0 },
              { label: "Counter-clockwise", value: analytics?.turnDistribution.ccw ?? 0 },
              { label: "Half turn (180°)", value: analytics?.turnDistribution.double ?? 0 },
            ]}
          />
          <div style={{ marginTop: 12 }}>
            <KeyValue label="Total moves recorded">{analytics?.totalMoves ?? 0}</KeyValue>
            <KeyValue label="Average execution time">
              {formatDuration(analytics?.averageExecutionSeconds ?? 0)}
            </KeyValue>
          </div>
        </Card>

        <Card title="Solver backends" description="Which implementation is available on this machine">
          {solver?.available.map((backend) => (
            <div key={backend.key} className="backend-row">
              <span className="system-dot" data-ok={backend.installed} />
              <div style={{ minWidth: 0 }}>
                <b style={{ fontSize: 13 }}>{backend.name}</b>
                <p style={{ fontSize: 11.5, color: "var(--ink-3)" }}>{backend.description}</p>
              </div>
              <Tag tone={solver.backendKey === backend.key ? "good" : backend.installed ? "brand" : "default"}>
                {solver.backendKey === backend.key
                  ? "active"
                  : backend.installed
                    ? "available"
                    : "not installed"}
              </Tag>
            </div>
          ))}
          <p style={{ fontSize: 11.5, color: "var(--ink-3)" }}>{solver?.message}</p>
        </Card>
      </div>

      {/* Timeline table ------------------------------------------------ */}
      <Card title="Solve history" description="Every completed run, newest first">
        {hasData ? (
          <DataTable
            columns={["When", "Source", "Moves", "Quarter turns", "Search", "Execution", "Backend"]}
            rows={(analytics?.recent ?? []).map((record) => [
              formatRelative(record.finished_at),
              record.source,
              record.move_count,
              record.quarter_turns,
              formatMs(record.solve_ms),
              formatDuration(record.execution_seconds),
              record.backend,
            ])}
          />
        ) : (
          <EmptyState
            icon={<IconCheck size={26} />}
            title="No solves recorded"
            message="Finish a solution playback to add the first record."
            action={
              <Button size="sm" onClick={() => navigate("dashboard")}>
                Back to dashboard
              </Button>
            }
          />
        )}
      </Card>
    </>
  );
}
