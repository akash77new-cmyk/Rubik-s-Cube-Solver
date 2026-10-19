import { useEffect, useMemo, useRef, useState } from "react";
import { Button, Card, EmptyState, Segmented, Tag, ToggleRow } from "@/components/ui";
import { PageHead } from "@/components/layout";
import { IconTerminal, IconTrash } from "@/components/Icons";
import { useApp } from "@/state/AppStore";
import { formatClock } from "@/lib/format";
import type { LogLevel } from "@/lib/types";

const LEVELS: (LogLevel | "all")[] = ["all", "info", "success", "warn", "error"];

export default function LogsPage() {
  const { logs, clearLogs } = useApp();
  const [level, setLevel] = useState<LogLevel | "all">("all");
  const [source, setSource] = useState("all");
  const [follow, setFollow] = useState(true);
  const listRef = useRef<HTMLDivElement>(null);

  const sources = useMemo(
    () => ["all", ...Array.from(new Set(logs.map((entry) => entry.source))).sort()],
    [logs],
  );

  const visible = useMemo(
    () =>
      logs.filter(
        (entry) =>
          (level === "all" || entry.level === level) &&
          (source === "all" || entry.source === source),
      ),
    [logs, level, source],
  );

  useEffect(() => {
    if (!follow || !listRef.current) return;
    listRef.current.scrollTop = listRef.current.scrollHeight;
  }, [visible.length, follow]);

  const counts = useMemo(() => {
    const tally: Record<string, number> = {};
    for (const entry of logs) tally[entry.level] = (tally[entry.level] ?? 0) + 1;
    return tally;
  }, [logs]);

  return (
    <>
      <PageHead
        title="Logs"
        description="Structured events streamed live from the vision engine over the socket bridge."
        actions={
          <Button variant="danger" icon={<IconTrash size={16} />} onClick={clearLogs}>
            Clear
          </Button>
        }
      />

      <Card
        title={`${visible.length} entries`}
        description="Newest at the bottom"
        actions={
          <>
            <Tag tone="good">{counts.success ?? 0} success</Tag>
            <Tag tone="warning">{counts.warn ?? 0} warn</Tag>
            <Tag tone="critical">{counts.error ?? 0} error</Tag>
          </>
        }
      >
        <div style={{ display: "flex", gap: "var(--sp-3)", flexWrap: "wrap", alignItems: "center" }}>
          <Segmented
            value={level}
            options={LEVELS.map((item) => ({ value: item, label: item }))}
            onChange={setLevel}
          />
          <select value={source} onChange={(event) => setSource(event.target.value)} aria-label="Filter by source">
            {sources.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
          <div style={{ marginLeft: "auto", minWidth: 180 }}>
            <ToggleRow label="Follow tail" checked={follow} onChange={setFollow} />
          </div>
        </div>
      </Card>

      <Card className="card-pad-0">
        {visible.length === 0 ? (
          <EmptyState
            icon={<IconTerminal size={28} />}
            title="No log entries"
            message="Start the camera or run a solve — every pipeline stage reports here."
          />
        ) : (
          <div className="log-list" ref={listRef}>
            {visible.map((entry) => (
              <div key={entry.id} className="log-row" data-level={entry.level}>
                <span className="log-time">{formatClock(entry.timestamp)}</span>
                <span className="log-level">{entry.level.toUpperCase()}</span>
                <span className="log-source">{entry.source}</span>
                <span className="log-message">{entry.message}</span>
              </div>
            ))}
          </div>
        )}
      </Card>
    </>
  );
}
