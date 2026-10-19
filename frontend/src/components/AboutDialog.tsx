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
      "Persisted solve history with move counts, solve times, move distribution and running detection accuracy.",
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
              Python · OpenCV · NumPy · React · TypeScript · Socket programming
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
            Keyboard: <b>1-9</b> pages · <b>Space</b> play/pause · <b>←/→</b> step
          </span>
        </footer>
      </div>
    </div>
  );
}
