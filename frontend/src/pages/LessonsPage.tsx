import { useEffect, useState, type FormEvent } from "react";
import { Button, Card, KeyValue, Tag } from "@/components/ui";
import { PageHead } from "@/components/layout";
import { IconBook, IconSparkle } from "@/components/Icons";
import { useApp } from "@/state/AppStore";
import type { CoachAnswer, CoachSource } from "@/lib/types";

const EXAMPLES = [
  "What does R prime mean?",
  "Which way do I turn B?",
  "How do I make the yellow cross?",
  "Why can a scan be unsolvable?",
];

/** A section's text as paragraphs (blank lines separate them). */
function Paragraphs({ text }: { text: string }) {
  return (
    <>
      {text.split(/\n\s*\n/).map((paragraph, index) => (
        <p key={index}>{paragraph.split("\n").join(" ")}</p>
      ))}
    </>
  );
}

export default function LessonsPage() {
  const { snapshot, send, learn, connection } = useApp();
  const status = snapshot?.ai?.lessons ?? null;
  const busy = snapshot?.ai?.busy ?? false;
  const [slug, setSlug] = useState<string | null>(null);
  const [focus, setFocus] = useState<string | null>(null);
  const [question, setQuestion] = useState("");

  /* Ask once the socket is online: on a reload or a direct link the page opens before
     it connects, and a request sent then would be dropped. Also reloads after a reconnect. */
  useEffect(() => {
    if (connection === "online") send("lessons.list");
  }, [send, connection]);

  const lesson = learn.lessons.find((item) => item.slug === slug) ?? learn.lessons[0] ?? null;

  /* Open a cited section: show its lesson, then scroll to it and highlight it. */
  const openSource = (source: CoachSource) => {
    setSlug(source.lesson);
    setFocus(source.id);
  };
  useEffect(() => {
    if (focus) document.getElementById(`section-${focus}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [focus, lesson?.slug]);

  const ask = (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || busy) return;
    setQuestion(trimmed);
    send("coach.ask", { question: trimmed });
  };
  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    ask(question);
  };

  return (
    <>
      <PageHead
        title="Lessons & Coach"
        description="Eight short lessons, written for this app. The coach answers from them and shows which sections it used."
      />

      <div className="lessons-layout">
        <Card title="Lessons" icon={<IconBook size={16} />} className="lessons-list-card">
          <ol className="lessons-list">
            {learn.lessons.map((item) => (
              <li key={item.slug}>
                <button
                  className="lessons-item"
                  data-active={item.slug === lesson?.slug}
                  onClick={() => {
                    setSlug(item.slug);
                    setFocus(null);
                  }}
                >
                  <b>{item.title}</b>
                  <span>{item.summary}</span>
                </button>
              </li>
            ))}
          </ol>
        </Card>

        <Card title={lesson?.title ?? "Lesson"} description={lesson?.summary} className="lesson-reader">
          {lesson?.sections.map((section) => (
            <section
              key={section.id}
              id={`section-${section.id}`}
              className="lesson-section"
              data-focus={section.id === focus}
            >
              <h3>{section.title}</h3>
              <Paragraphs text={section.text} />
            </section>
          ))}
        </Card>

        <div className="lessons-side">
          <Card
            title="Ask the coach"
            description="Answers come only from the lessons, with their sources. Questions are sent to Google Gemini."
            icon={<IconSparkle size={16} />}
          >
            <form className="ai-ask" onSubmit={onSubmit}>
              <input
                type="text"
                value={question}
                maxLength={300}
                placeholder="e.g. Which way do I turn B?"
                aria-label="Your question for the coach"
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
            {busy && <p className="ai-progress">Searching the lessons…</p>}
            {learn.answer && <CoachAnswerView answer={learn.answer} busy={busy} onAsk={ask} onOpen={openSource} />}
          </Card>

          <Card title="Search index" description="How the coach finds the right sections">
            {status ? (
              <>
                <KeyValue label="Lessons">
                  {status.lessons} lessons · {status.sections} sections
                </KeyValue>
                <KeyValue label="Embedded">
                  {status.embedded} / {status.sections}
                </KeyValue>
                <KeyValue label="Search">
                  <Tag tone={status.search === "keywords" ? "warning" : "good"}>{status.search}</Tag>
                </KeyValue>
                <KeyValue label="Embedding model">{status.model ?? "—"}</KeyValue>
                {status.error && <p className="ai-note">Last error: {status.error}</p>}
              </>
            ) : (
              <KeyValue label="Index">Not connected to the engine</KeyValue>
            )}
            <p className="ai-note">
              Without embeddings (no key, or Gemini unreachable), the coach still finds sections by keywords.
            </p>
          </Card>
        </div>
      </div>
    </>
  );
}

function CoachAnswerView({
  answer,
  busy,
  onAsk,
  onOpen,
}: {
  answer: CoachAnswer;
  busy: boolean;
  onAsk: (text: string) => void;
  onOpen: (source: CoachSource) => void;
}) {
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
      {answer.sources.length > 0 && (
        <div className="coach-sources">
          <span className="ai-note">Sources:</span>
          {answer.sources.map((source) => (
            <button key={source.id} className="coach-source" onClick={() => onOpen(source)}>
              {source.lessonTitle} › {source.section}
            </button>
          ))}
        </div>
      )}
      {!answer.covered && <p className="ai-note">The lessons don't cover this question.</p>}
      <p className="ai-note">
        Searched with {answer.search} · {(answer.durationMs / 1000).toFixed(1)} s · {answer.requests} model request(s)
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
