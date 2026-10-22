import { useEffect, useState, type FormEvent } from "react";
import { Button, Card, KeyValue, Tag } from "@/components/ui";
import { PageHead } from "@/components/layout";
import { IconSparkle } from "@/components/Icons";
import { useApp } from "@/state/AppStore";
import { formatClock } from "@/lib/format";
import type { AIAnswer, AIProgress, AITrace, AITraceStep } from "@/lib/types";

const EXAMPLES = [
  "Is my cube valid?",
  "How many moves is my solution?",
  "How do I do step 1?",
  "How are my solves going?",
];

/** What each tool does, in words, for the progress line. */
const TOOL_LABELS: Record<string, string> = {
  get_cube_state: "checked your cube",
  get_scan_progress: "checked the scan",
  get_solution: "read the solution",
  explain_move: "looked up a move",
  get_solve_stats: "read your solve history",
  final_answer: "checked its answer",
};

function progressText(progress: AIProgress | null): string {
  if (!progress || progress.step === 0 || !progress.tool) return "Thinking…";
  return `Step ${progress.step}: ${TOOL_LABELS[progress.tool] ?? progress.tool}…`;
}

function formatArgs(args: unknown): string {
  if (!args || typeof args !== "object") return "";
  return Object.entries(args as Record<string, unknown>)
    .map(([key, value]) => `${key}=${JSON.stringify(value)}`)
    .join(", ");
}

function shorten(text: string, limit = 160): string {
  return text.length > limit ? `${text.slice(0, limit)}…` : text;
}

export default function AssistantPage() {
  const { snapshot, send, ai } = useApp();
  const status = snapshot?.ai ?? null;
  const busy = status?.busy ?? false;
  const [question, setQuestion] = useState("");

  /* Load the recent runs when the page opens, and again after every answer. */
  useEffect(() => {
    send("ai.traces");
  }, [send, ai.answer]);

  const ask = (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || busy) return;
    setQuestion(trimmed);
    send("ai.ask", { question: trimmed });
  };

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    ask(question);
  };

  return (
    <>
      <PageHead
        title="AI Assistant"
        description="Ask about your cube, your solution or your solves. Every fact comes from the app; the AI only explains it."
      />

      <div className="grid grid-2">
        <Card
          title="Ask"
          description="Questions and cube data are sent to Google Gemini. Don't type personal information."
          icon={<IconSparkle size={16} />}
        >
          <form className="ai-ask" onSubmit={onSubmit}>
            <input
              type="text"
              value={question}
              maxLength={300}
              placeholder="e.g. How do I do step 1?"
              aria-label="Your question"
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
          {busy && <p className="ai-progress">{progressText(ai.progress)}</p>}
          {ai.answer && <AnswerView answer={ai.answer} busy={busy} onAsk={ask} />}
        </Card>

        <Card title="Status" description="Which model answers, and how much of the request limit is used">
          {status ? (
            <>
              <KeyValue label="AI">
                {status.enabled ? <Tag tone="good">On</Tag> : <Tag tone="warning">Off</Tag>}
              </KeyValue>
              <KeyValue label="Model">
                {status.enabled ? `${status.provider} · ${status.model}` : "—"}
              </KeyValue>
              <KeyValue label="Requests, last minute">
                {status.budget.usedLastMinute} / {status.budget.perMinute}
              </KeyValue>
              <KeyValue label="Requests, last 24 h">
                {status.budget.usedToday} / {status.budget.perDay}
              </KeyValue>
              {!status.enabled && status.offReason && <p className="ai-note">AI is off: {status.offReason}.</p>}
              {status.lastError && <p className="ai-note">Last error: {status.lastError}</p>}
            </>
          ) : (
            <KeyValue label="AI">Not connected to the engine</KeyValue>
          )}
          <p className="ai-note">
            Without AI, the assistant still answers with the facts the app computed.
          </p>
        </Card>
      </div>

      <Card
        title="Recent runs"
        description="Every model request and tool call, as traced"
        actions={
          <Button size="sm" variant="ghost" onClick={() => send("ai.traces")}>
            Refresh
          </Button>
        }
      >
        {ai.traces.length === 0 ? (
          <p className="ai-note">No runs yet. Ask a question above.</p>
        ) : (
          <div className="ai-runs">
            {ai.traces.map((trace) => (
              <TraceView key={trace.id} trace={trace} />
            ))}
          </div>
        )}
      </Card>
    </>
  );
}

function AnswerView({ answer, busy, onAsk }: { answer: AIAnswer; busy: boolean; onAsk: (text: string) => void }) {
  if (answer.error) {
    return (
      <div className="ai-answer" data-source="fallback">
        <p className="ai-answer-text">Something went wrong: {answer.error}</p>
      </div>
    );
  }
  const fromAI = answer.source !== "fallback";
  return (
    <div className="ai-answer" data-source={fromAI ? "ai" : "fallback"}>
      <div className="ai-answer-head">
        <span className="ai-question">{answer.question}</span>
        {fromAI ? <Tag tone="brand">{answer.model}</Tag> : <Tag tone="warning">Built-in answer</Tag>}
      </div>
      <p className="ai-answer-text">{answer.answer}</p>
      <p className="ai-note">
        {(answer.durationMs / 1000).toFixed(1)} s · {answer.requests} model request(s) ·{" "}
        {answer.toolCalls} tool call(s)
      </p>
      {answer.suggestions.length > 0 && (
        <div className="btn-row ai-examples">
          {answer.suggestions.map((suggestion) => (
            <Button key={suggestion} size="sm" variant="ghost" disabled={busy} onClick={() => onAsk(suggestion)}>
              {suggestion}
            </Button>
          ))}
        </div>
      )}
    </div>
  );
}

function TraceView({ trace }: { trace: AITrace }) {
  const builtIn = trace.source === "fallback";
  return (
    <details className="ai-run">
      <summary>
        <span className="ai-run-time">{formatClock(trace.startedAt)}</span>
        <span className="ai-run-question">{trace.question}</span>
        <Tag tone={builtIn ? "warning" : "brand"}>{builtIn ? "built-in" : trace.model ?? trace.source}</Tag>
        <span className="ai-run-meta">
          {trace.requestCount} req · {trace.durationMs} ms
        </span>
      </summary>
      <ol className="ai-steps">
        {trace.steps.map((step) => (
          <li key={step.position} data-kind={step.kind}>
            <StepView step={step} />
          </li>
        ))}
      </ol>
      {trace.answer && <p className="ai-note">Answer: {trace.answer.answer}</p>}
    </details>
  );
}

function StepView({ step }: { step: AITraceStep }) {
  const detail = step.detail;
  if (step.kind === "model") {
    const calls = (detail.toolCalls as { name: string; args: unknown }[] | undefined) ?? [];
    const asked = calls.map((call) => `${call.name}(${formatArgs(call.args)})`).join(", ");
    return (
      <>
        <b>Model</b> asked for {asked || "nothing"}
        <span className="ai-step-meta">
          {step.durationMs} ms · {String(detail.inputTokens ?? 0)} in / {String(detail.outputTokens ?? 0)} out tokens
        </span>
      </>
    );
  }
  if (step.kind === "tool") {
    return (
      <>
        <b>Tool</b> {step.name}({formatArgs(detail.args)}) → <code>{shorten(JSON.stringify(detail.result))}</code>
      </>
    );
  }
  if (step.kind === "answer") {
    return (
      <>
        <b>Answer</b> passed the schema check
      </>
    );
  }
  return (
    <>
      <b>Fallback</b> {String(detail.message ?? "")}
    </>
  );
}
