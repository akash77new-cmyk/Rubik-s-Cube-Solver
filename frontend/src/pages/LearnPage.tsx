import { useEffect, useMemo, useState, type CSSProperties, type FormEvent } from "react";
import { Button, Card, Tag } from "@/components/ui";
import { Cube3D } from "@/components/cube";
import { MoveGlyph } from "@/components/move";
import { PageHead, type PageId } from "@/components/layout";
import {
  IconCheck,
  IconFlip,
  IconGraduation,
  IconRestart,
  IconScan,
  IconShuffle,
  IconSparkle,
  IconUndo,
} from "@/components/Icons";
import { useApp } from "@/state/AppStore";
import { COLOR_NAMES, CUBE_COLORS } from "@/lib/colors";
import type { ColorCode, LearnHint, LearnStage, LearnState, TutorAnswer } from "@/lib/types";

const FACES = ["U", "R", "F", "D", "L", "B"] as const;
const PAD_ROWS = [FACES.map((f) => f), FACES.map((f) => `${f}'`), FACES.map((f) => `${f}2`)];
const STAGE_NAMES = ["White cross", "White corners", "Middle layer", "Yellow cross", "Yellow face", "Yellow corners", "Yellow edges"];
const HINT_TITLES = ["", "What to look at", "The algorithm", "The moves"];
const EXAMPLES = ["Why does the corner trick work?", "What is an algorithm?", "Why turn the cube over?"];

type Paint = (code: ColorCode) => string;

/**
 * Solve & Learn (Phase 8): the learner solves their own cube with the beginner method.
 * The backend knows the cube (every move is tapped in); the tutor explains and hints.
 */
export default function LearnPage({ navigate }: { navigate: (page: PageId) => void }) {
  const { snapshot, send } = useApp();
  const learn = snapshot?.learn ?? null;
  const paint: Paint = (code) => snapshot?.settings?.cube_palette?.[code] ?? CUBE_COLORS[code];

  /* Keyboard: U R F D L B turn clockwise, with Shift counter-clockwise; Backspace undoes. */
  useEffect(() => {
    if (!learn?.ready || learn.solved) return undefined;
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && /^(INPUT|SELECT|TEXTAREA)$/.test(target.tagName)) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      const face = event.key.toUpperCase();
      if ((FACES as readonly string[]).includes(face) && event.key.length === 1) {
        event.preventDefault();
        send("learn.move", { move: event.shiftKey ? `${face}'` : face });
      } else if (event.key === "Backspace") {
        event.preventDefault();
        send("learn.undo");
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [learn?.ready, learn?.solved, send]);

  if (!learn) return <LearnIntro navigate={navigate} paint={paint} />;

  // The stage being worked on, not the one the stickers show right now: that one drops
  // for a moment in the middle of most algorithms.
  const stage = learn.stages[Math.min(learn.working, 7) - 1];
  return (
    <>
      <PageHead
        title="Solve & Learn"
        description={
          learn.solved
            ? `Solved with the beginner method in ${learn.moveCount} moves`
            : `Beginner method · stage ${stage.number} of 7 · ${learn.moveCount} moves so far`
        }
        actions={
          <>
            <Button icon={<IconRestart size={16} />} onClick={() => send("learn.restart")} title="Start again from the scanned cube">
              Restart
            </Button>
            <Button variant="ghost" onClick={() => send("learn.exit")}>
              Exit
            </Button>
          </>
        }
      />

      <StageTrack learn={learn} />

      <div className="learn-layout">
        <CubeCard learn={learn} paint={paint} />
        <div className="learn-side">
          <Card
            className="learn-tutor"
            accent
            icon={<IconSparkle size={16} />}
            title="Your tutor"
            description={learn.solved ? "All seven stages done" : `Stage ${stage.number}: ${stage.name}`}
          >
            {!learn.ready ? (
              <HoldStep learn={learn} paint={paint} />
            ) : learn.solved ? (
              <Recap learn={learn} navigate={navigate} />
            ) : learn.step?.kind === "turn_over" && learn.guide.length === 0 ? (
              <TurnOver learn={learn} paint={paint} />
            ) : (
              <StepView learn={learn} stage={stage} />
            )}
          </Card>
          <AskCard learn={learn} navigate={navigate} />
        </div>
      </div>
    </>
  );
}

/* ------------------------------------------------------------------ the 7 stages */

function StageTrack({ learn }: { learn: LearnState }) {
  const guiding = learn.guide.length > 0;
  return (
    <Card className="learn-track-card">
      <ol className="learn-track">
        {learn.stages.map((stage) => {
          // A finished stage stays ticked. If the learner's own move has broken it, it turns
          // amber; in the middle of shown moves that's expected, so it stays green.
          const broken = stage.done && stage.number >= learn.stage && !guiding;
          const state = stage.done ? (broken ? "broken" : "done") : stage.current ? "current" : "todo";
          return (
            <li
              key={stage.number}
              className="learn-track-item"
              data-state={state}
              title={broken ? "Finished before, but broken right now: finish your algorithm, or press Undo" : undefined}
            >
              {stage.number === 3 && (
                <span className="learn-track-flip" title="Turn the cube over: yellow on top">
                  <IconFlip size={12} />
                </span>
              )}
              <span className="learn-track-dot">
                {stage.done ? <IconCheck size={15} /> : stage.number}
              </span>
              <span className="learn-track-name">{stage.name}</span>
              <span className="learn-track-meta">
                {broken
                  ? "broken for now"
                  : stage.done
                    ? stage.alone ? "on your own" : `with ${stage.hints + stage.shown} hint(s)`
                    : stage.top === "W" ? "white on top" : "yellow on top"}
              </span>
            </li>
          );
        })}
      </ol>
    </Card>
  );
}

/* ------------------------------------------------------------------ the cube and the move pad */

function CubeCard({ learn, paint }: { learn: LearnState; paint: Paint }) {
  const { snapshot, send } = useApp();
  const settings = snapshot?.settings;
  // A new object arrives with every snapshot: keep the same one until the cube really
  // changes, so the 3D cube animates each move exactly once.
  const move = useMemo(() => learn.lastMove, [learn.id, learn.version]);
  const previous = useMemo(() => learn.previous, [learn.id, learn.version]);
  const focus = useMemo(
    () => (learn.ready && !learn.solved && learn.step?.focus.length ? new Set(learn.step.focus) : null),
    [learn.ready, learn.solved, learn.step?.focus.join(",")],
  );
  const guided = learn.guide[0]?.notation;
  const locked = !learn.ready || learn.solved || learn.step?.kind === "turn_over";

  return (
    <Card className="learn-cube-card">
      <div className="learn-hold">
        <span>
          <i style={{ background: paint(learn.top) }} /> {COLOR_NAMES[learn.top]} on top
        </span>
        <span>
          <i style={{ background: paint(learn.front) }} /> {COLOR_NAMES[learn.front]} facing you
        </span>
        {focus && <span className="learn-hold-focus">bright stickers = this step</span>}
      </div>
      <div className="learn-cube">
        <Cube3D
          facelets={learn.cube}
          move={move}
          previousFacelets={previous}
          size={290}
          durationMs={Math.max(160, 420 / Math.max(settings?.animation_speed ?? 1, 0.25))}
          palette={settings?.cube_palette}
          highlight={focus}
        />
      </div>

      <div className="learn-pad-head">
        <b>Your moves</b>
        <span>Turn your real cube, then tap the same move here. Keys: U R F D L B, Shift for '.</span>
      </div>
      <div className="learn-pad" role="group" aria-label="Move pad">
        {PAD_ROWS.flat().map((notation) => (
          <button
            key={notation}
            type="button"
            className="learn-key"
            data-next={guided === notation}
            disabled={locked}
            onClick={() => send("learn.move", { move: notation })}
          >
            {notation}
          </button>
        ))}
      </div>
      <div className="learn-pad-foot">
        <Button
          size="sm"
          icon={<IconUndo size={14} />}
          disabled={!learn.ready || learn.history.length === 0}
          onClick={() => send("learn.undo")}
        >
          Undo
        </Button>
        <span className="learn-history">
          {learn.history.length === 0
            ? "No moves yet"
            : learn.history.slice(-10).map((action, index) => (
                <code key={`${action}-${index}`}>{action === "turn_over" ? "⟲" : action}</code>
              ))}
        </span>
        <b>{learn.moveCount} moves</b>
      </div>
    </Card>
  );
}

/* ------------------------------------------------------------------ tutor states */

function HoldFigure({ top, front, paint }: { top: ColorCode; front: ColorCode; paint: Paint }) {
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

function HoldStep({ learn, paint }: { learn: LearnState; paint: Paint }) {
  const { send } = useApp();
  return (
    <div className="learn-center">
      <HoldFigure top={learn.top} front={learn.front} paint={paint} />
      <p className="learn-big">
        Hold your cube with <b>{COLOR_NAMES[learn.top].toLowerCase()}</b> on top and{" "}
        <b>{COLOR_NAMES[learn.front].toLowerCase()}</b> facing you.
      </p>
      <p className="ai-note">
        You will solve it in 7 stages. Try each step yourself and tap every move you make. Stuck? Ask for a hint, or
        press Show me.
      </p>
      <Button variant="primary" onClick={() => send("learn.ready")}>
        I'm holding it like this · start stage {learn.stage}
      </Button>
    </div>
  );
}

function TurnOver({ learn, paint }: { learn: LearnState; paint: Paint }) {
  const { send } = useApp();
  const top: ColorCode = learn.top === "W" ? "Y" : "W";
  return (
    <div className="learn-center">
      {learn.justDone && <DoneBanner done={learn.justDone} />}
      <span className="learn-flip">
        <IconFlip size={40} />
      </span>
      <p className="learn-big">{learn.step?.task}</p>
      <p className="learn-text">{learn.step?.how}</p>
      <HoldFigure top={top} front={learn.front} paint={paint} />
      <Button variant="primary" icon={<IconFlip size={16} />} onClick={() => send("learn.turnover")}>
        I turned it over
      </Button>
    </div>
  );
}

function DoneBanner({ done }: { done: NonNullable<LearnState["justDone"]> }) {
  return (
    <div className="learn-banner" data-tone="good">
      <IconCheck size={16} />
      <div>
        <b>Stage {done.number} done: {done.name.toLowerCase()}.</b> {done.learned}
      </div>
    </div>
  );
}

function SourceTag({ source, model }: { source: string; model: string | null }) {
  if (source === "built-in") return <Tag>from the app</Tag>;
  if (source === "fallback") return <Tag tone="warning">built-in</Tag>;
  return <Tag tone="brand">{model ?? source}</Tag>;
}

function StepView({ learn, stage }: { learn: LearnState; stage: LearnStage }) {
  const { send } = useApp();
  // One tap = one move: the button waits for the cube to change before it works again.
  const [sentAt, setSentAt] = useState(-1);
  const step = learn.step;
  if (!step) return null;
  const guide = learn.guide;
  const moves = learn.guideAll;
  const doneCount = moves.length - guide.length;
  const thinking = learn.tutorBusy && learn.hints.some((hint) => hint.source === "built-in");
  const guiding = guide.length > 0;

  // While moves are shown, nothing above the Done button changes, so it stays in one place:
  // old banners are hidden, and the guide comes before the hints (a hint's text can change
  // when the tutor's words arrive).
  return (
    <div className="learn-step">
      {!guiding && learn.justDone && <DoneBanner done={learn.justDone} />}
      {!guiding && learn.note && (
        <div className="learn-banner" data-tone="warning">
          <IconUndo size={16} />
          <div>{learn.note}</div>
        </div>
      )}
      <p className="learn-goal">{stage.goal}</p>
      <p className="learn-big">{guiding && learn.guideTask ? learn.guideTask : step.task}</p>

      {guiding && (
        <div className="learn-guide">
          <div className="learn-guide-move">
            <MoveGlyph move={guide[0]} size={112} key={`${guide[0].notation}-${learn.version}`} />
            <div>
              <div className="move-hero-notation">{guide[0].notation}</div>
              <p className="learn-text">{guide[0].instruction}</p>
            </div>
          </div>
          <div className="learn-guide-strip">
            {moves.map((move, index) => (
              <span key={`${move.notation}-${index}`} data-state={index < doneCount ? "done" : index === doneCount ? "now" : "next"}>
                {move.notation}
              </span>
            ))}
          </div>
          <Button
            variant="primary"
            disabled={sentAt === learn.version}
            onClick={() => {
              setSentAt(learn.version);
              send("learn.move", { move: guide[0].notation });
            }}
          >
            Done · {guide.length > 1 ? `next move (${doneCount + 1} of ${moves.length})` : "last move"}
          </Button>
          <p className="ai-note">Do this move on your cube, then press Done. Any other move stops the guide.</p>
        </div>
      )}

      {learn.hints.map((hint: LearnHint) => (
        <div key={hint.level} className="learn-hint">
          <div className="learn-hint-head">
            <span className="learn-hint-level">{hint.level}</span>
            <b>{HINT_TITLES[hint.level]}</b>
            <SourceTag source={hint.source} model={hint.model} />
          </div>
          <p>{hint.text}</p>
          {hint.level === 2 && step.algorithmNotation && (
            <code className="learn-alg" title={step.algorithm ?? undefined}>
              {step.algorithmNotation}
            </code>
          )}
        </div>
      ))}
      {thinking && <p className="ai-progress">The tutor is writing your hint…</p>}

      {!guiding && (
        <>
          <div className="btn-row learn-actions">
            {learn.hintLevel < 2 && (
              <Button icon={<IconSparkle size={15} />} disabled={learn.tutorBusy} onClick={() => send("learn.hint")}>
                Hint {learn.hintLevel + 1} of 3
              </Button>
            )}
            <Button variant="primary" onClick={() => send("learn.show")}>
              Show me the moves
            </Button>
          </div>
          <p className="ai-note">Try it on your cube first. The app follows every move you tap.</p>
        </>
      )}
    </div>
  );
}

function Recap({ learn, navigate }: { learn: LearnState; navigate: (page: PageId) => void }) {
  const { send } = useApp();
  const recap = learn.recap;
  const minutes = Math.max(1, Math.round(learn.stats.seconds / 60));
  return (
    <div className="learn-center learn-recap">
      <Confetti />
      <span className="solved-badge">
        <IconCheck size={38} />
      </span>
      <div className="solved-title">You solved it!</div>
      <div className="learn-stats">
        <div>
          <b>{learn.stats.moves}</b>
          <span>moves</span>
        </div>
        <div>
          <b>{minutes}</b>
          <span>min</span>
        </div>
        <div>
          <b>{learn.stats.stagesAlone.length}/7</b>
          <span>stages alone</span>
        </div>
        <div>
          <b>{learn.stats.hints + learn.stats.shown}</b>
          <span>hints used</span>
        </div>
      </div>
      {recap && (
        <div className="ai-answer learn-recap-text" data-source={recap.source === "built-in" || recap.source === "fallback" ? "fallback" : "ai"}>
          <div className="ai-answer-head">
            <b>Your recap</b>
            <SourceTag source={recap.source} model={recap.model} />
          </div>
          <p className="ai-answer-text">{recap.message}</p>
        </div>
      )}
      <div className="btn-row" style={{ justifyContent: "center" }}>
        <Button
          variant="primary"
          icon={<IconScan size={15} />}
          onClick={() => {
            send("learn.exit");
            send("scan.reset");
            navigate("scanner");
          }}
        >
          Scan another cube
        </Button>
        <Button icon={<IconRestart size={15} />} onClick={() => send("learn.restart")}>
          Learn it again
        </Button>
      </div>
    </div>
  );
}

function Confetti() {
  const colours = ["--cube-W", "--cube-Y", "--cube-R", "--cube-O", "--cube-G", "--cube-B"];
  return (
    <div className="confetti" aria-hidden="true">
      {Array.from({ length: 30 }, (_, i) => (
        <span
          key={i}
          style={
            {
              left: `${(i * 37) % 100}%`,
              background: `var(${colours[i % 6]})`,
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

/* ------------------------------------------------------------------ "why?" questions */

function AskCard({ learn, navigate }: { learn: LearnState; navigate: (page: PageId) => void }) {
  const { send } = useApp();
  const [question, setQuestion] = useState("");
  const answer: TutorAnswer | null = learn.answer;
  const busy = learn.tutorBusy;
  const ask = (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || busy) return;
    setQuestion(trimmed);
    send("learn.ask", { question: trimmed });
  };
  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    ask(question);
  };
  return (
    <Card title="Ask why" description="Answers come from the lessons, with sources." icon={<IconGraduation size={16} />}>
      <form className="ai-ask" onSubmit={onSubmit}>
        <input
          type="text"
          value={question}
          maxLength={300}
          placeholder="e.g. Why does the corner trick work?"
          aria-label="Your question for the tutor"
          disabled={busy}
          onChange={(event) => setQuestion(event.target.value)}
        />
        <Button variant="primary" type="submit" loading={busy} disabled={!question.trim()}>
          Ask
        </Button>
      </form>
      <div className="btn-row ai-examples">
        {EXAMPLES.map((example) => (
          <Button key={example} size="sm" variant="ghost" disabled={busy} onClick={() => ask(example)}>
            {example}
          </Button>
        ))}
      </div>
      {answer && (
        <div className="ai-answer" data-source={answer.source === "fallback" ? "fallback" : "ai"}>
          <div className="ai-answer-head">
            <span className="ai-question">{answer.question}</span>
            <SourceTag source={answer.source} model={answer.model} />
          </div>
          <p className="ai-answer-text">{answer.message}</p>
          {(answer.sources ?? []).length > 0 && (
            <div className="coach-sources">
              <span className="ai-note">Sources:</span>
              {(answer.sources ?? []).map((source) => (
                <button key={source.id} className="coach-source" onClick={() => navigate("lessons")}>
                  {source.lessonTitle} › {source.section}
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

/* ------------------------------------------------------------------ before starting */

function LearnIntro({ navigate, paint }: { navigate: (page: PageId) => void; paint: Paint }) {
  const { snapshot, send } = useApp();
  const valid = Boolean(snapshot?.cube && snapshot?.validation?.ok);
  return (
    <>
      <PageHead
        title="Solve & Learn"
        description="Solve your own cube with the beginner method, stage by stage, with an AI tutor."
      />
      <Card className="learn-intro" accent>
        <div className="learn-intro-text">
          <span className="learn-flip">
            <IconGraduation size={34} />
          </span>
          <h2>Learn to solve it yourself</h2>
          <p>
            Scan your cube once. Then solve it in seven stages, the way people learn: try each step on your real cube,
            tap the moves you make, and ask for a hint only when you're stuck. The app always knows your cube, so the
            hints are about <b>your</b> pieces.
          </p>
          <div className="btn-row">
            <Button
              variant="primary"
              icon={<IconGraduation size={16} />}
              disabled={!valid}
              onClick={() => send("learn.start")}
              title={valid ? undefined : "Scan a valid cube first"}
            >
              Start with my scanned cube
            </Button>
            <Button icon={<IconScan size={16} />} onClick={() => navigate("scanner")}>
              Scan a cube
            </Button>
            <Button
              variant="ghost"
              icon={<IconShuffle size={16} />}
              onClick={() => {
                send("cube.scramble", { length: 25 });
                send("learn.start");
              }}
            >
              Practise on a demo scramble
            </Button>
          </div>
        </div>
        <ol className="learn-intro-stages">
          {STAGE_NAMES.map((name, index) => (
            <li key={name}>
              <span style={{ background: paint(index < 2 ? "W" : "Y") }}>{index + 1}</span>
              {name}
            </li>
          ))}
        </ol>
      </Card>
    </>
  );
}
