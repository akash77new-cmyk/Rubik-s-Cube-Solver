/** About panel - the one-screen explanation of what this project demonstrates. */

import { useEffect } from "react";
import { Button } from "@/components/ui";
import { useApp } from "@/state/AppStore";

const CAPABILITIES: { title: string; detail: string }[] = [
  {
    title: "Computer-vision pipeline",
    detail:
      "Threaded OpenCV capture, bilateral denoise, HSV conversion, 3x3 patch sampling with a circular-median hue and per-sticker confidence.",
  },
  {
    title: "HSV colour segmentation",
    detail:
      "Six tunable HSV boxes with hue wrap-around for red, scored by how centred a sample sits inside its box.",
  },
  {
    title: "Cube state & move simulation",
    detail:
      "Immutable 54-facelet model with verified face-cycle tables; every move returns a new state so playback can scrub in both directions.",
  },
  {
    title: "Kociemba two-phase solver",
    detail:
      "Pluggable backend - the native C extension when available, otherwise Kociemba's own pure-Python implementation with cached pruning tables.",
  },
  {
    title: "Socket-based IPC",
    detail:
      "The vision engine runs as a separate OS process and publishes state and JPEG frames over a length-prefixed TCP protocol; the web server relays them to the browser over Socket.IO.",
  },
  {
    title: "Analytics",
    detail:
      "Persisted solve history with move counts, solve times, move distribution and running average sticker confidence.",
  },
  {
    title: "Database",
    detail:
      "PostgreSQL (Neon) in production and SQLite locally, through SQLAlchemy. Alembic migrations run at start-up; reads come from memory, so the camera never waits for the network.",
  },
  {
    title: "AI assistant",
    detail:
      "A Gemini tool-calling agent: it reads facts through read-only tools, answers through a schema-checked final_answer, and every step is traced. Without an API key it gives a built-in answer.",
  },
  {
    title: "Smart repair",
    detail:
      "An unsolvable scan gets the 1- or 2-sticker fixes the validator accepts; an agent picks one by id (or asks for a rescan) and explains it, and the user confirms before anything changes.",
  },
  {
    title: "RAG coach",
    detail:
      "Lessons embedded with Gemini and stored in PostgreSQL with pgvector; the coach answers only from the sections it retrieved, and every citation is checked.",
  },
  {
    title: "Accounts & sessions",
    detail:
      "Every visitor gets their own session through per-visitor Socket.IO rooms. Accounts use scrypt-hashed passwords and a signed JWT in an HttpOnly cookie, and keep their settings and solve history.",
  },
  {
    title: "Solve & Learn",
    detail:
      "The beginner method on your own cube, in seven stages: code finds every step and its moves, an AI tutor gives hints and answers why, and any moves it writes must come from the app.",
  },
];

export function AboutDialog({ onClose }: { onClose: () => void }) {
  const { snapshot } = useApp();

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="modal-backdrop" onClick={onClose} role="presentation">
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label="About this project"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="modal-head">
          <img src="/assets-lib/brand/logo.svg" alt="" width={40} height={40} />
          <div>
            <h2 style={{ fontSize: 17 }}>Real-Time Rubik's Cube Solver</h2>
            <p style={{ fontSize: 12.5, color: "var(--ink-3)" }}>
              Python · OpenCV · NumPy · React · TypeScript · Socket programming · PostgreSQL · Gemini API
            </p>
          </div>
          <Button variant="ghost" size="sm" onClick={onClose} style={{ marginLeft: "auto" }}>
            Close
          </Button>
        </header>

        <div className="modal-body">
          {CAPABILITIES.map((item) => (
            <div key={item.title} className="about-item">
              <b>{item.title}</b>
              <p>{item.detail}</p>
            </div>
          ))}
        </div>

        <footer className="modal-foot">
          <span>
            Solver backend: <b>{snapshot?.solver.backend ?? "initialising"}</b>
          </span>
          <span>
            Keyboard: <b>1-9</b> pages · <b>0</b> AI Assistant · <b>Space</b> play/pause · <b>←/→</b> step
          </span>
        </footer>
      </div>
    </div>
  );
}
