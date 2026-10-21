/** Phase 2B: the step-by-step scan guide. Colours only - no "left" or "right". */
import type { ReactNode } from "react";
import { COLOR_NAMES, CUBE_COLORS } from "@/lib/colors";
import type { ColorCode, ScanInfo } from "@/lib/types";

export function ScanGuide({
  scan,
  palette,
  action,
}: {
  scan: ScanInfo | undefined;
  palette?: Partial<Record<ColorCode, string>>;
  /** What to do now (start / capture / hold bar), shown right under the current step. */
  action?: ReactNode;
}) {
  const steps = scan?.steps ?? [];
  if (steps.length === 0) return null;
  const color = (code: ColorCode) => palette?.[code] ?? CUBE_COLORS[code];
  const next = steps.find((step) => step.face === scan?.current) ?? null;
  const number = next ? steps.indexOf(next) + 1 : steps.length;

  return (
    <div className="scan-guide">
      {next ? (
        <div className="scan-guide-now">
          {/* What the camera should see: the centre colour, with the top colour above it. */}
          <div className="scan-guide-face" aria-hidden="true">
            <span className="scan-guide-top" style={{ background: color(next.top) }}>
              {COLOR_NAMES[next.top]} on top
            </span>
            <div className="scan-guide-grid">
              {Array.from({ length: 9 }, (_, index) => (
                <span
                  key={index}
                  style={index === 4 ? { background: color(next.center) } : undefined}
                />
              ))}
            </div>
          </div>
          <div>
            <p className="scan-guide-step">
              Step {number} of {steps.length}
            </p>
            <h3 className="scan-guide-title">{next.text}</h3>
            <p className="scan-guide-how">{next.how}</p>
          </div>
        </div>
      ) : (
        <h3 className="scan-guide-title">All six sides captured.</h3>
      )}

      {action && <div className="scan-guide-action">{action}</div>}

      <ol className="scan-guide-steps">
        {steps.map((step) => (
          <li key={step.face} data-done={step.done} data-next={step.face === scan?.current}>
            <span className="scan-guide-dot" style={{ background: color(step.center) }}>
              {step.done ? "✓" : ""}
            </span>
            {COLOR_NAMES[step.center]}
          </li>
        ))}
      </ol>

      <p className="scan-guide-note">
        The camera reads the side facing it, so you see the opposite side.{" "}
        {scan?.autoCapture
          ? "Hold each side still for a moment: it is captured automatically, and only once."
          : "Hold each side still, then press Capture. Each side is stored only once."}{" "}
        Any order works.
      </p>
    </div>
  );
}
