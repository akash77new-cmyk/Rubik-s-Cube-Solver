/** Phase 2: uncertain-sticker hints for the net, and the training-data card. */
import { useState } from "react";
import { Button, Card, Segmented, Tag } from "@/components/ui";
import { COLOR_NAMES } from "@/lib/colors";
import { FACE_ORDER, type ScanInfo, type UncertainReason } from "@/lib/types";
import { useApp } from "@/state/AppStore";

const REASON_TEXT: Record<UncertainReason, string> = {
  no_range: "outside every colour range",
  two_ranges: "inside two colour ranges",
};

const percent = (value: number) => `${Math.round(value * 100)}%`;
const plural = (count: number, word: string) => `${count} ${word}${count === 1 ? "" : "s"}`;

/**
 * Hints from what the camera saw, keyed like "U8":
 * - `uncertain`: stickers the camera was unsure about that nobody has corrected yet;
 * - `notes`: a tooltip for every scanned sticker ("camera: Red 62% · next: Orange 41%").
 */
export function scanHints(scan: ScanInfo | undefined) {
  const uncertain = new Set<string>();
  const notes: Record<string, string> = {};
  for (const face of FACE_ORDER) {
    const info = scan?.faces[face];
    info?.stickers?.forEach((reading, index) => {
      const key = `${face}${index}`;
      const next = reading.alternatives[1];
      notes[key] =
        `camera: ${COLOR_NAMES[reading.color]} ${percent(reading.confidence)}` +
        (next ? ` · next: ${COLOR_NAMES[next.color]} ${percent(next.confidence)}` : "") +
        (reading.uncertain ? ` · unsure (${REASON_TEXT[reading.uncertain]})` : "");
      if (reading.uncertain && info.colors?.[index] === reading.color) uncertain.add(key);
    });
  }
  return { uncertain, notes };
}

/** Save confirmed scans as training data. Hidden when collection is off (production). */
export function DatasetCard() {
  const { snapshot, send } = useApp();
  const [lighting, setLighting] = useState("");
  const dataset = snapshot?.dataset;
  if (!dataset?.enabled) return null;

  const stats = dataset.stats;
  const blocker = dataset.reason ?? (lighting ? null : "Pick the lighting for this scan.");

  return (
    <Card
      title="Training data"
      description="Save confirmed scans to build the dataset for the colour classifier (Phase 11)."
    >
      <div className="dataset-stats">
        <Tag tone="brand">{plural(stats?.scans ?? 0, "scan")}</Tag>
        <Tag>{stats?.stickers ?? 0} stickers</Tag>
        <Tag>{stats?.corrected ?? 0} corrected</Tag>
        {dataset.lightingOptions.map((option) => (
          <Tag key={option.value}>
            {option.label} · {stats?.byLighting[option.value] ?? 0}
          </Tag>
        ))}
      </div>
      <p style={{ fontSize: 12, color: "var(--ink-3)", marginTop: 10 }}>Lighting for this scan</p>
      <Segmented value={lighting} options={dataset.lightingOptions} onChange={setLighting} />
      <div className="btn-row" style={{ marginTop: 10 }}>
        <Button
          variant="primary"
          size="sm"
          disabled={blocker !== null}
          onClick={() => send("dataset.save", { lighting })}
        >
          {dataset.saved ? "Saved" : "Save scan to dataset"}
        </Button>
      </div>
      <p style={{ fontSize: 11.5, color: "var(--ink-3)", marginTop: 6 }}>
        {blocker ?? "Ready to save."} Only save when the net matches your real cube exactly: these
        colours become the training labels.
      </p>
    </Card>
  );
}
