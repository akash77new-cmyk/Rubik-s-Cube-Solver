import { useState } from "react";
import { Button, Card, KeyValue, Segmented, Tag, EmptyState } from "@/components/ui";
import { Cube3D, CubeNet, SOLVED_FACELETS } from "@/components/cube";
import { PageHead, type PageId } from "@/components/layout";
import { ColorSummary } from "@/components/charts";
import { ValidationIssueList, flaggedStickers } from "@/components/validation";
import {
  IconCheck,
  IconCube,
  IconRestart,
  IconRoute,
  IconShuffle,
} from "@/components/Icons";
import { useApp } from "@/state/AppStore";
import { CUBE_COLORS, COLOR_NAMES, FACE_NAMES } from "@/lib/colors";
import { COLOR_CODES, FACE_ORDER, type ColorCode, type FaceKey } from "@/lib/types";

const MANUAL_MOVES = ["U", "U'", "R", "R'", "F", "F'", "D", "D'", "L", "L'", "B", "B'"];

export default function CubeViewerPage({ navigate }: { navigate: (page: PageId) => void }) {
  const { snapshot, send } = useApp();
  const [view, setView] = useState<"3d" | "net" | "both">("both");
  const [paint, setPaint] = useState<ColorCode>("W");
  const [editing, setEditing] = useState(false);
  const [highlight, setHighlight] = useState<FaceKey | null>(null);
  const [resetKey, setResetKey] = useState(0);
  const [selectedIssue, setSelectedIssue] = useState<number | null>(null);

  const cube = snapshot?.cube;
  const settings = snapshot?.settings;
  const validation = snapshot?.validation;
  const facelets = snapshot?.playback.cube ?? cube?.facelets ?? SOLVED_FACELETS;

  const counts = COLOR_CODES.reduce(
    (accumulator, code) => {
      accumulator[code] = 0;
      return accumulator;
    },
    {} as Record<ColorCode, number>,
  );
  for (const face of FACE_ORDER) {
    for (const code of facelets[face] ?? []) if (code in counts) counts[code] += 1;
  }

  const onSticker = (face: FaceKey, index: number) => {
    if (!editing) return;
    send("cube.sticker", { face, index, color: paint });
  };

  return (
    <>
      <PageHead
        title="Cube State Visualizer"
        description="The live 54-facelet model. Drag to orbit, use the zoom buttons (or Ctrl + scroll), or switch to the unfolded net to correct a mis-detected sticker."
        actions={
          <>
            <Segmented
              value={view}
              options={[
                { value: "3d", label: "3D" },
                { value: "net", label: "Net" },
                { value: "both", label: "Both" },
              ]}
              onChange={setView}
            />
            <Button icon={<IconShuffle size={16} />} onClick={() => send("cube.scramble", { length: 22 })}>
              Scramble
            </Button>
            <Button icon={<IconRestart size={16} />} onClick={() => send("cube.reset")}>
              Solved state
            </Button>
          </>
        }
      />

      <div className="split">
        <Card className="viewer-card">
          <div className="viewer-stage">
            {(view === "3d" || view === "both") && (
              <div style={{ flex: 1, minWidth: 300 }}>
                <Cube3D
                  key={resetKey}
                  facelets={facelets}
                  size={view === "both" ? 190 : 250}
                  showLabels
                  highlightFace={highlight}
                  palette={settings?.cube_palette}
                  onStickerClick={editing ? onSticker : undefined}
                />
                <div className="btn-row" style={{ justifyContent: "center" }}>
                  <Button size="sm" variant="ghost" onClick={() => setResetKey((key) => key + 1)}>
                    Reset orientation
                  </Button>
                </div>
              </div>
            )}

            {(view === "net" || view === "both") && (
              <div style={{ flex: 1, minWidth: 300, display: "grid", placeItems: "center" }}>
                <CubeNet
                  facelets={facelets}
                  activeFace={highlight}
                  editable={editing}
                  paintColor={paint}
                  onStickerClick={onSticker}
                  palette={settings?.cube_palette}
                  faceSize={view === "both" ? 82 : 104}
                  flagged={validation && !validation.ok ? flaggedStickers(validation.issues, selectedIssue) : undefined}
                />
              </div>
            )}
          </div>

          <div className="btn-row" style={{ justifyContent: "center", marginTop: 4 }}>
            {FACE_ORDER.map((face) => (
              <Button
                key={face}
                size="sm"
                variant={highlight === face ? "primary" : "ghost"}
                onMouseEnter={() => setHighlight(face)}
                onMouseLeave={() => setHighlight(null)}
                onClick={() => setHighlight(highlight === face ? null : face)}
                title={`Highlight the ${FACE_NAMES[face]} face`}
              >
                {face}
              </Button>
            ))}
          </div>
        </Card>

        <div style={{ display: "flex", flexDirection: "column", gap: "var(--sp-4)" }}>
          <Card
            title="State"
            description="Derived directly from the engine snapshot"
            actions={
              cube?.isSolved ? (
                <Tag tone="good">
                  <IconCheck size={11} /> solved
                </Tag>
              ) : (
                <Tag tone="brand">scrambled</Tag>
              )
            }
          >
            <KeyValue label="Source">{snapshot?.cubeSource ?? "none"}</KeyValue>
            <KeyValue label="Stickers matching centre">
              {cube?.solvedStickers ?? 0} / 54
            </KeyValue>
            <KeyValue label="Centres">
              {cube ? FACE_ORDER.map((face) => cube.centers[face]).join(" ") : "—"}
            </KeyValue>
            <KeyValue label="Validation">
              {validation ? (validation.ok ? "valid" : `${validation.errors.length} error(s)`) : "—"}
            </KeyValue>
            {validation && !validation.ok && (
              <div style={{ marginTop: 6 }}><ValidationIssueList issues={validation.issues} selected={selectedIssue} onSelect={setSelectedIssue} /></div>
            )}
            <div className="btn-row" style={{ marginTop: 8 }}>
              <Button
                variant="primary"
                size="sm"
                icon={<IconRoute size={14} />}
                disabled={!cube || !validation?.ok || snapshot?.solving}
                loading={snapshot?.solving}
                onClick={() => {
                  send("solve.run");
                  navigate("solution");
                }}
              >
                Solve
              </Button>
            </div>
          </Card>

          <Card
            title="Sticker editor"
            description="Fix a mis-detected colour without re-scanning"
            actions={
              <Segmented
                value={editing ? "on" : "off"}
                options={[
                  { value: "off", label: "View" },
                  { value: "on", label: "Edit" },
                ]}
                onChange={(value) => setEditing(value === "on")}
              />
            }
          >
            {editing ? (
              <>
                <p style={{ fontSize: 12, color: "var(--ink-3)" }}>
                  Pick a colour, then click any sticker in the net or on the 3D cube.
                </p>
                <div className="swatch-row" style={{ marginBottom: 22 }}>
                  {COLOR_CODES.map((code) => (
                    <button
                      key={code}
                      type="button"
                      className="swatch"
                      aria-pressed={paint === code}
                      aria-label={COLOR_NAMES[code]}
                      title={COLOR_NAMES[code]}
                      style={{ "--c": CUBE_COLORS[code] } as never}
                      onClick={() => setPaint(code)}
                    >
                      <small>{code}</small>
                    </button>
                  ))}
                </div>
              </>
            ) : (
              <EmptyState
                icon={<IconCube size={24} />}
                title="Read-only"
                message="Switch to Edit to repaint individual stickers. Handy when one sticker was read under a glare."
              />
            )}
          </Card>

          <Card title="Move simulation" description="Apply turns to the working cube">
            <div className="btn-row">
              {MANUAL_MOVES.map((move) => (
                <Button
                  key={move}
                  size="sm"
                  onClick={() => send("cube.apply", { moves: move })}
                  title={`Apply ${move}`}
                >
                  {move}
                </Button>
              ))}
            </div>
            <p style={{ fontSize: 11.5, color: "var(--ink-3)" }}>
              Each turn runs through the same face-cycle tables the solver validates against.
            </p>
          </Card>

          <Card title="Colour census" description="Nine of every colour is required">
            <ColorSummary counts={counts} />
          </Card>
        </div>
      </div>
    </>
  );
}
