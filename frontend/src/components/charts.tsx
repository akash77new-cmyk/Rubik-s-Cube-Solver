/**
 * Hand-built SVG charts.
 *
 * Colour follows the job, not decoration:
 *  - magnitude (move counts, solve times) -> ONE sequential hue,
 *  - identity (turn types) -> the three validated categorical slots, always with
 *    a legend *and* direct labels so identity is never colour-alone,
 *  - the cube-colour and hue-histogram charts are the one legitimate exception:
 *    there the colour *is* the measured value.
 *
 * Every series also carries a text label or a table fallback, and each chart
 * scrolls inside its own container rather than widening the page.
 */

import { useState, type ReactNode } from "react";
import { CUBE_COLORS, COLOR_NAMES } from "@/lib/colors";
import type { ColorCode } from "@/lib/types";

const SERIES = ["var(--series-1)", "var(--series-2)", "var(--series-3)"];

interface Datum {
  label: string;
  value: number;
  /** Only set when the colour IS the data (cube colours, hue bins). */
  color?: string;
  hint?: string;
}

/* ==================================================================== */
/* Horizontal bar - magnitude                                           */
/* ==================================================================== */

export function BarChart({
  data,
  unit = "",
  height = 22,
  gap = 10,
  showTrack = true,
}: {
  data: Datum[];
  unit?: string;
  height?: number;
  gap?: number;
  showTrack?: boolean;
}) {
  const max = Math.max(1, ...data.map((d) => d.value));
  const labelWidth = 34;
  const valueWidth = 46;
  const total = data.length * (height + gap) - gap;

  return (
    <div className="chart">
      <svg viewBox={`0 0 320 ${Math.max(total, 1)}`} height={Math.max(total, 1)} width="100%"
           preserveAspectRatio="none" style={{ minWidth: 260 }}>
        {data.map((datum, index) => {
          const y = index * (height + gap);
          const trackWidth = 320 - labelWidth - valueWidth;
          const width = Math.max(0, (datum.value / max) * trackWidth);
          return (
            <g key={datum.label}>
              <text x="0" y={y + height * 0.72} className="axis-label">
                {datum.label}
              </text>
              {showTrack && (
                <rect
                  x={labelWidth}
                  y={y}
                  width={trackWidth}
                  height={height}
                  rx="4"
                  className="bar-track"
                />
              )}
              <rect
                x={labelWidth}
                y={y}
                width={width}
                height={height}
                rx="4"
                fill={datum.color ?? "var(--seq-500)"}
                stroke="var(--surface)"
                strokeWidth="2"
              >
                <title>{`${datum.label}: ${datum.value}${unit}`}</title>
              </rect>
              <text x={320 - valueWidth + 8} y={y + height * 0.72} className="axis-value">
                {datum.value}
                {unit}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

/* ==================================================================== */
/* Line chart - change over time, single series + hover crosshair       */
/* ==================================================================== */

export function LineChart({
  points,
  unit = "",
  height = 168,
  label,
}: {
  points: { x: number; y: number; caption?: string }[];
  unit?: string;
  height?: number;
  label?: string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  if (points.length === 0) return null;

  const width = 520;
  const pad = { top: 14, right: 14, bottom: 24, left: 36 };
  const innerW = width - pad.left - pad.right;
  const innerH = height - pad.top - pad.bottom;

  const maxY = Math.max(1, ...points.map((p) => p.y));
  const minY = 0;
  const sx = (index: number) =>
    pad.left + (points.length === 1 ? innerW / 2 : (index / (points.length - 1)) * innerW);
  const sy = (value: number) =>
    pad.top + innerH - ((value - minY) / (maxY - minY || 1)) * innerH;

  const path = points.map((p, i) => `${i === 0 ? "M" : "L"}${sx(i)} ${sy(p.y)}`).join(" ");
  const area = `${path} L${sx(points.length - 1)} ${pad.top + innerH} L${sx(0)} ${
    pad.top + innerH
  } Z`;
  const ticks = [0, 0.5, 1].map((t) => Math.round(minY + t * (maxY - minY)));

  return (
    <div className="chart chart-wrap">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width="100%"
        height={height}
        style={{ minWidth: 320 }}
        onMouseLeave={() => setHover(null)}
      >
        <defs>
          <linearGradient id="area-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--seq-500)" stopOpacity="0.28" />
            <stop offset="100%" stopColor="var(--seq-500)" stopOpacity="0" />
          </linearGradient>
        </defs>

        {ticks.map((tick) => (
          <g key={tick}>
            <line
              x1={pad.left}
              x2={width - pad.right}
              y1={sy(tick)}
              y2={sy(tick)}
              stroke="var(--grid)"
              strokeWidth="1"
            />
            <text x="4" y={sy(tick) + 4} className="axis-value">
              {tick}
            </text>
          </g>
        ))}

        <path d={area} fill="url(#area-fill)" />
        <path d={path} fill="none" stroke="var(--seq-500)" strokeWidth="2" strokeLinejoin="round" />

        {points.map((point, index) => (
          <circle
            key={index}
            cx={sx(index)}
            cy={sy(point.y)}
            r={hover === index ? 5.5 : 3.5}
            fill="var(--seq-500)"
            stroke="var(--surface)"
            strokeWidth="2"
          />
        ))}

        {/* Wide invisible hit targets so hovering is forgiving. */}
        {points.map((_, index) => (
          <rect
            key={`hit-${index}`}
            x={sx(index) - innerW / (points.length * 2 || 1) - 6}
            y={pad.top}
            width={innerW / (points.length || 1) + 12}
            height={innerH}
            fill="transparent"
            onMouseEnter={() => setHover(index)}
          />
        ))}

        {hover !== null && (
          <line
            x1={sx(hover)}
            x2={sx(hover)}
            y1={pad.top}
            y2={pad.top + innerH}
            stroke="var(--axis)"
            strokeWidth="1"
            strokeDasharray="3 3"
          />
        )}
      </svg>

      {hover !== null && (
        <div
          className="chart-tip"
          style={{
            left: `${(sx(hover) / width) * 100}%`,
            top: `${(sy(points[hover].y) / height) * 100}%`,
          }}
        >
          <b>
            {points[hover].y}
            {unit}
          </b>
          {points[hover].caption && (
            <span style={{ color: "var(--ink-3)" }}> · {points[hover].caption}</span>
          )}
        </div>
      )}
      {label && (
        <p style={{ fontSize: 11.5, color: "var(--ink-3)", marginTop: 4 }}>{label}</p>
      )}
    </div>
  );
}

/* ==================================================================== */
/* Stacked proportion bar - identity across 2-3 categories              */
/* ==================================================================== */

export function ProportionBar({
  segments,
  height = 26,
}: {
  segments: { label: string; value: number }[];
  height?: number;
}) {
  const total = segments.reduce((sum, item) => sum + item.value, 0);
  if (total === 0) {
    return <p style={{ fontSize: 12, color: "var(--ink-3)" }}>No moves recorded yet.</p>;
  }

  let offset = 0;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div className="chart">
        <svg viewBox={`0 0 320 ${height}`} width="100%" height={height} preserveAspectRatio="none">
          {segments.map((segment, index) => {
            const width = (segment.value / total) * 320;
            const x = offset;
            offset += width;
            return (
              <rect
                key={segment.label}
                x={x}
                y="0"
                width={Math.max(0, width - 2)}
                height={height}
                rx="4"
                fill={SERIES[index % SERIES.length]}
              >
                <title>{`${segment.label}: ${segment.value}`}</title>
              </rect>
            );
          })}
        </svg>
      </div>
      <div className="chart-legend">
        {segments.map((segment, index) => (
          <span key={segment.label}>
            <i style={{ background: SERIES[index % SERIES.length] }} />
            {segment.label}
            <b style={{ color: "var(--ink)", fontVariantNumeric: "tabular-nums" }}>
              {segment.value}
            </b>
            <span style={{ color: "var(--ink-3)" }}>
              ({Math.round((segment.value / total) * 100)}%)
            </span>
          </span>
        ))}
      </div>
    </div>
  );
}

/* ==================================================================== */
/* Cube colour summary - colour IS the data                             */
/* ==================================================================== */

export function ColorSummary({
  counts,
  expected = 9,
}: {
  counts: Record<ColorCode, number>;
  expected?: number;
}) {
  const codes = Object.keys(counts) as ColorCode[];
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {codes.map((code) => {
        const value = counts[code] ?? 0;
        const ok = value === expected;
        return (
          <div key={code} style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span
              style={{
                width: 14,
                height: 14,
                borderRadius: 4,
                background: CUBE_COLORS[code],
                boxShadow: "inset 0 -3px 5px rgba(0,0,0,.25)",
                flex: "none",
              }}
            />
            <span style={{ fontSize: 12.5, width: 62 }}>{COLOR_NAMES[code]}</span>
            <div className="progress" style={{ flex: 1, height: 6 }}>
              <div
                className="progress-fill"
                style={{
                  width: `${Math.min(100, (value / expected) * 100)}%`,
                  background: CUBE_COLORS[code],
                }}
              />
            </div>
            <b
              style={{
                fontSize: 12,
                fontVariantNumeric: "tabular-nums",
                width: 44,
                textAlign: "right",
                color: ok ? "var(--status-good)" : "var(--status-warning)",
              }}
            >
              {value}/{expected}
            </b>
          </div>
        );
      })}
    </div>
  );
}

/* ==================================================================== */
/* Hue histogram - hue IS the data                                      */
/* ==================================================================== */

export function HueHistogram({
  bins,
  height = 104,
}: {
  bins: number[];
  height?: number;
}) {
  if (!bins.length) {
    return (
      <p style={{ fontSize: 12, color: "var(--ink-3)" }}>
        Start the camera to see the live hue distribution.
      </p>
    );
  }
  const width = 320;
  const barWidth = width / bins.length;
  return (
    <div className="chart">
      <svg viewBox={`0 0 ${width} ${height}`} width="100%" height={height} preserveAspectRatio="none">
        {bins.map((value, index) => {
          const h = Math.max(1, (value / 100) * (height - 6));
          // Bin index maps straight back to an OpenCV hue (0-179).
          const hue = (index / bins.length) * 360;
          return (
            <rect
              key={index}
              x={index * barWidth}
              y={height - h}
              width={Math.max(1, barWidth - 1)}
              height={h}
              rx="1.5"
              fill={`hsl(${hue} 78% 58%)`}
            >
              <title>{`hue ${Math.round((index / bins.length) * 180)}: ${value}%`}</title>
            </rect>
          );
        })}
      </svg>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          fontSize: 10.5,
          color: "var(--ink-3)",
          marginTop: 2,
        }}
      >
        <span>H 0</span>
        <span>60</span>
        <span>120</span>
        <span>179</span>
      </div>
    </div>
  );
}

/* ==================================================================== */
/* Sparkline - compact trend inside a stat tile                         */
/* ==================================================================== */

export function Sparkline({ values, width = 96, height = 26 }: { values: number[]; width?: number; height?: number }) {
  if (values.length < 2) return null;
  const max = Math.max(...values);
  const min = Math.min(...values);
  const span = max - min || 1;
  const path = values
    .map((value, index) => {
      const x = (index / (values.length - 1)) * width;
      const y = height - ((value - min) / span) * (height - 4) - 2;
      return `${index === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg width={width} height={height} aria-hidden="true">
      <path d={path} fill="none" stroke="var(--seq-400)" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

/* ==================================================================== */
/* Table fallback - the accessibility escape hatch for any chart         */
/* ==================================================================== */

export function DataTable({
  columns,
  rows,
}: {
  columns: string[];
  rows: ReactNode[][];
}) {
  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
        <thead>
          <tr>
            {columns.map((column) => (
              <th
                key={column}
                style={{
                  textAlign: "left",
                  padding: "6px 10px",
                  color: "var(--ink-3)",
                  fontWeight: 650,
                  borderBottom: "1px solid var(--hairline)",
                  whiteSpace: "nowrap",
                }}
              >
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index}>
              {row.map((cell, cellIndex) => (
                <td
                  key={cellIndex}
                  style={{
                    padding: "6px 10px",
                    borderBottom: "1px solid var(--hairline)",
                    fontVariantNumeric: "tabular-nums",
                    whiteSpace: "nowrap",
                  }}
                >
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
