/** Reusable presentational primitives. No business logic lives here. */

import {
  useEffect,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type ReactNode,
} from "react";
import { clamp } from "@/lib/format";

/* ------------------------------------------------------------------ Card */

export function Card({
  title,
  description,
  actions,
  icon,
  children,
  accent = false,
  interactive = false,
  className = "",
  onClick,
}: {
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  icon?: ReactNode;
  children?: ReactNode;
  accent?: boolean;
  interactive?: boolean;
  className?: string;
  onClick?: () => void;
}) {
  return (
    <section
      className={`card ${className}`}
      data-accent={accent}
      data-interactive={interactive}
      onClick={onClick}
    >
      {(title || actions) && (
        <header className="card-head">
          {icon}
          <div>
            {title && <div className="card-title">{title}</div>}
            {description && <div className="card-desc">{description}</div>}
          </div>
          {actions && <div className="card-actions">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

/* ---------------------------------------------------------------- Button */

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "default" | "primary" | "ghost" | "danger";
  size?: "sm" | "md" | "lg";
  icon?: ReactNode;
  iconOnly?: boolean;
  loading?: boolean;
};

export function Button({
  variant = "default",
  size = "md",
  icon,
  iconOnly = false,
  loading = false,
  children,
  disabled,
  ...rest
}: ButtonProps) {
  return (
    <button
      className="btn"
      data-variant={variant}
      data-size={size}
      data-icon={iconOnly}
      disabled={disabled || loading}
      {...rest}
    >
      {loading ? <span className="spinner" /> : icon}
      {!iconOnly && children}
    </button>
  );
}

/* ------------------------------------------------------------- Segmented */

export function Segmented<T extends string | number>({
  value,
  options,
  onChange,
}: {
  value: T;
  options: { value: T; label: ReactNode; title?: string }[];
  onChange: (value: T) => void;
}) {
  return (
    <div className="segmented" role="group">
      {options.map((option) => (
        <button
          key={String(option.value)}
          type="button"
          title={option.title}
          aria-pressed={option.value === value}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

/* ---------------------------------------------------------------- Toggle */

export function ToggleRow({
  label,
  hint,
  checked,
  onChange,
}: {
  label: string;
  hint?: string;
  checked: boolean;
  onChange: (next: boolean) => void;
}) {
  return (
    <div className="toggle-row">
      <div className="label">
        <b>{label}</b>
        {hint && <span>{hint}</span>}
      </div>
      <button
        type="button"
        className="toggle"
        role="switch"
        aria-checked={checked}
        aria-pressed={checked}
        aria-label={label}
        onClick={() => onChange(!checked)}
      />
    </div>
  );
}

/* ---------------------------------------------------------------- Slider */

export function SliderRow({
  label,
  hint,
  value,
  min,
  max,
  step = 1,
  suffix = "",
  onChange,
}: {
  label: string;
  hint?: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  suffix?: string;
  onChange: (value: number) => void;
}) {
  return (
    <label className="slider-row">
      <span className="slider-head">
        <b>{label}</b>
        {hint && <span style={{ color: "var(--ink-3)" }}>{hint}</span>}
        <span className="value">
          {value}
          {suffix}
        </span>
      </span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
      />
    </label>
  );
}

/* ------------------------------------------------------------------- Tag */

export function Tag({
  tone = "default",
  children,
}: {
  tone?: "default" | "good" | "warning" | "serious" | "critical" | "brand";
  children: ReactNode;
}) {
  return (
    <span className="tag" data-tone={tone === "default" ? undefined : tone}>
      {children}
    </span>
  );
}

/* ------------------------------------------------------------ StatusChip */

export function StatusChip({
  label,
  value,
  tone = "default",
  optional = false,
  title,
}: {
  label: string;
  value?: ReactNode;
  tone?: "default" | "good" | "warning" | "critical" | "brand";
  optional?: boolean;
  title?: string;
}) {
  return (
    <span
      className="chip"
      data-tone={tone === "default" ? undefined : tone}
      data-optional={optional}
      title={title}
    >
      <i className="chip-dot" />
      {label}
      {value !== undefined && <strong>{value}</strong>}
    </span>
  );
}

/* -------------------------------------------------------------- Progress */

export function ProgressBar({
  value,
  striped = false,
  label,
}: {
  value: number;
  striped?: boolean;
  label?: ReactNode;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {label && (
        <div style={{ display: "flex", fontSize: 12, color: "var(--ink-3)" }}>{label}</div>
      )}
      <div
        className="progress"
        data-striped={striped}
        role="progressbar"
        aria-valuenow={Math.round(clamp(value, 0, 1) * 100)}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div className="progress-fill" style={{ width: `${clamp(value, 0, 1) * 100}%` }} />
      </div>
    </div>
  );
}

/* -------------------------------------------------------- AnimatedNumber */

/** Counts from the previous value to the next one with an ease-out curve. */
export function AnimatedNumber({
  value,
  digits = 0,
  duration = 620,
}: {
  value: number;
  digits?: number;
  duration?: number;
}) {
  const [display, setDisplay] = useState(value);
  const fromRef = useRef(value);
  const frameRef = useRef(0);

  useEffect(() => {
    const from = fromRef.current;
    const to = Number.isFinite(value) ? value : 0;
    if (from === to) return;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced) {
      fromRef.current = to;
      setDisplay(to);
      return;
    }
    const start = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      setDisplay(from + (to - from) * eased);
      if (t < 1) frameRef.current = requestAnimationFrame(tick);
      else fromRef.current = to;
    };
    frameRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frameRef.current);
  }, [value, duration]);

  return <>{display.toFixed(digits)}</>;
}

/* ------------------------------------------------------------- StatTile */

export function StatTile({
  label,
  value,
  unit,
  hint,
  icon,
  tint,
  digits = 0,
  animate = true,
}: {
  label: string;
  value: number | string;
  unit?: string;
  hint?: ReactNode;
  icon?: ReactNode;
  tint?: string;
  digits?: number;
  animate?: boolean;
}) {
  return (
    <article className="stat" style={tint ? ({ "--tile-tint": tint } as never) : undefined}>
      <div className="stat-label">
        {icon}
        {label}
      </div>
      <div className="stat-value">
        {typeof value === "number" && animate ? (
          <AnimatedNumber value={value} digits={digits} />
        ) : (
          value
        )}
        {unit && <small>{unit}</small>}
      </div>
      {hint && <div className="stat-hint">{hint}</div>}
    </article>
  );
}

/* ----------------------------------------------------------- EmptyState */

export function EmptyState({
  icon,
  title,
  message,
  action,
}: {
  icon?: ReactNode;
  title: string;
  message?: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty">
      {icon}
      <h3>{title}</h3>
      {message && <p>{message}</p>}
      {action}
    </div>
  );
}

/* ------------------------------------------------------------------ KV */

export function KeyValue({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="kv">
      <span>{label}</span>
      <b>{children}</b>
    </div>
  );
}
