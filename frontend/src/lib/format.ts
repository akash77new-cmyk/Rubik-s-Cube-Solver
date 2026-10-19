/** Small formatting helpers shared across pages. */

export const clamp = (value: number, min: number, max: number): number =>
  Math.min(max, Math.max(min, value));

export function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return "0s";
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)}s`;
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds % 60);
  if (minutes < 60) return `${minutes}m ${rest}s`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

export function formatMs(ms: number): string {
  if (!Number.isFinite(ms) || ms <= 0) return "0 ms";
  if (ms < 1000) return `${ms.toFixed(ms < 10 ? 2 : 0)} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}

export function formatClock(timestamp: number): string {
  const date = new Date(timestamp * 1000);
  return date.toLocaleTimeString(undefined, {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function formatRelative(timestamp: number): string {
  const delta = Date.now() / 1000 - timestamp;
  if (delta < 60) return "just now";
  if (delta < 3600) return `${Math.floor(delta / 60)}m ago`;
  if (delta < 86400) return `${Math.floor(delta / 3600)}h ago`;
  return `${Math.floor(delta / 86400)}d ago`;
}

export const percent = (value: number, digits = 0): string =>
  `${(clamp(value, 0, 1) * 100).toFixed(digits)}%`;

/** Confidence -> status token, used for colour and label together. */
export function confidenceTone(value: number): "good" | "warning" | "critical" {
  if (value >= 0.6) return "good";
  if (value >= 0.35) return "warning";
  return "critical";
}

export function confidenceLabel(value: number): string {
  const tone = confidenceTone(value);
  return tone === "good" ? "Strong" : tone === "warning" ? "Fair" : "Weak";
}
