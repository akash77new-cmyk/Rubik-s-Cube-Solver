/** The Smart Repair Agent's card, shown on the Scanner page after an unsolvable scan (Phase 5). */

import { Button, Tag } from "@/components/ui";
import { IconCheck, IconRestart, IconSparkle } from "@/components/Icons";
import { useApp } from "@/state/AppStore";
import { COLOR_NAMES, stickerColor } from "@/lib/colors";
import type { ColorCode, FaceKey, RepairChange, RepairInfo } from "@/lib/types";

const POSITIONS = [
  "top-left", "top", "top-right", "left", "centre", "right", "bottom-left", "bottom", "bottom-right",
];

/** Stickers a ready fix would change ("U1", ...), for outlining on the net. */
export function repairStickers(repair: RepairInfo | null | undefined): Set<string> | undefined {
  if (!repair || repair.status !== "ready" || repair.action !== "apply_fix") return undefined;
  return new Set((repair.changes ?? []).map((change) => `${change.face}${change.index}`));
}

function Chip({ code, palette }: { code: ColorCode; palette?: Partial<Record<ColorCode, string>> }) {
  return <span className="repair-chip" style={{ background: stickerColor(code, palette) }} title={COLOR_NAMES[code]} />;
}

export function RepairPanel() {
  const { snapshot, send } = useApp();
  const repair = snapshot?.repair ?? null;
  const centers = snapshot?.cube?.centers;
  const palette = snapshot?.settings.cube_palette;
  const sideName = (face: FaceKey) => (centers ? `${COLOR_NAMES[centers[face]]} side` : `${face} side`);

  const rescan = (face: FaceKey) => {
    send("scan.face", { face });
    if (!snapshot?.camera.running) send("camera.start"); // the camera turns off after a valid scan
  };

  if (!repair) {
    // Dismissed, or the cube was edited by hand: the agent can be asked again.
    return (
      <div className="repair" data-state="idle">
        <Button size="sm" icon={<IconSparkle size={14} />} onClick={() => send("repair.start")}>
          Find the misread sticker
        </Button>
      </div>
    );
  }

  if (repair.status === "working") {
    return (
      <div className="repair" data-state="working">
        <span className="spinner" />
        <span>
          <b>Repair agent</b> · checking which stickers the camera may have misread…
        </span>
      </div>
    );
  }

  const fromAI = repair.source !== "search";
  const tag = fromAI ? (
    <Tag tone="brand">
      <IconSparkle size={11} /> {repair.model}
    </Tag>
  ) : (
    <Tag tone="warning">Built-in search</Tag>
  );

  if (repair.status === "applied") {
    return (
      <div className="repair" data-state="applied">
        <div className="repair-head">
          <b>
            <IconCheck size={14} /> Fix applied
          </b>
          {tag}
        </div>
        <ChangeList changes={repair.changes ?? []} sideName={sideName} palette={palette} />
      </div>
    );
  }

  return (
    <div className="repair" data-state="ready">
      <div className="repair-head">
        <b>
          <IconSparkle size={14} /> Repair agent
        </b>
        {tag}
      </div>
      <p className="repair-message">{repair.message}</p>
      {repair.action === "apply_fix" && (
        <ChangeList changes={repair.changes ?? []} sideName={sideName} palette={palette} />
      )}
      <div className="btn-row">
        {repair.action === "apply_fix" && (
          <Button variant="primary" size="sm" icon={<IconCheck size={14} />} onClick={() => send("repair.apply")}>
            Apply fix
          </Button>
        )}
        {repair.action === "rescan_side" && repair.side && (
          <Button variant="primary" size="sm" icon={<IconRestart size={14} />} onClick={() => rescan(repair.side!)}>
            Rescan the {sideName(repair.side)}
          </Button>
        )}
        {repair.action === "apply_fix" && repair.changes?.[0] && (
          <Button size="sm" variant="ghost" onClick={() => rescan(repair.changes![0].face)}>
            Rescan the {sideName(repair.changes[0].face)} instead
          </Button>
        )}
        <Button size="sm" variant="ghost" onClick={() => send("repair.dismiss")}>
          Dismiss
        </Button>
      </div>
      <p className="repair-note">
        {repair.fixesFound ? `${repair.fixesFound} change(s) were proven to make the cube valid. ` : ""}
        Nothing changes until you press Apply. Check the outlined stickers against your cube.
      </p>
    </div>
  );
}

function ChangeList({
  changes,
  sideName,
  palette,
}: {
  changes: RepairChange[];
  sideName: (face: FaceKey) => string;
  palette?: Partial<Record<ColorCode, string>>;
}) {
  return (
    <ul className="repair-changes">
      {changes.map((change) => (
        <li key={`${change.face}${change.index}`}>
          <span className="repair-swap">
            <Chip code={change.from} palette={palette} />
            <span className="repair-arrow">→</span>
            <Chip code={change.to} palette={palette} />
          </span>
          <span>
            <b>{sideName(change.face)}</b>, {POSITIONS[change.index]} sticker: {COLOR_NAMES[change.from]} →{" "}
            {COLOR_NAMES[change.to]}
          </span>
          {change.oldConfidence < 1 && (
            <span className="repair-sure">camera {Math.round(change.oldConfidence * 100)}% sure</span>
          )}
        </li>
      ))}
    </ul>
  );
}
