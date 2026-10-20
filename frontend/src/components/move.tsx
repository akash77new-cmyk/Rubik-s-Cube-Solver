/**
 * Graphical move overlays.
 *
 * `MoveGlyph` draws the turn as vector art rather than printing "R'": a 3x3
 * face with the moving layer lit up and an arrow showing the rotation. The same
 * geometry is generated as standalone SVG files by tools/generate_assets.py.
 */

import type { Direction, FaceKey, MoveInfo } from "@/lib/types";

/** Cells of the 3x3 face that a turn moves. */
const LAYER_CELLS: Record<FaceKey, number[]> = {
  U: [0, 1, 2],
  D: [6, 7, 8],
  L: [0, 3, 6],
  R: [2, 5, 8],
  F: [0, 1, 2, 3, 4, 5, 6, 7, 8],
  B: [0, 1, 2, 3, 4, 5, 6, 7, 8],
};

export function MoveGlyph({
  move,
  size = 132,
  animated = true,
  idSuffix,
}: {
  move: MoveInfo;
  size?: number;
  animated?: boolean;
  idSuffix?: string;
}) {
  const uid = `${move.notation.replace(/'/g, "p")}${idSuffix ?? ""}`;
  const highlight = new Set(LAYER_CELLS[move.face]);
  // F and B spin the way the person holding the cube sees them (move.arrow): B
  // "clockwise" is named as seen from behind, so from the front it spins the other way.
  const clockwise = move.arrow === "clockwise";
  const isDouble = move.modifier === "2";

  return (
    <svg
      className="move-glyph"
      width={size}
      height={size}
      viewBox="0 0 256 256"
      role="img"
      aria-label={`${move.notation}: ${move.label}. ${move.instruction}`}
    >
      <defs>
        {/* userSpaceOnUse is required: a straight horizontal/vertical arrow has
            a zero-area bounding box, and an objectBoundingBox gradient on a
            degenerate bbox makes the element disappear entirely. */}
        <linearGradient
          id={`g-${uid}`}
          gradientUnits="userSpaceOnUse"
          x1="0"
          y1="0"
          x2="256"
          y2="256"
        >
          <stop offset="0%" stopColor="var(--brand-2)" />
          <stop offset="100%" stopColor="var(--brand)" />
        </linearGradient>
        <linearGradient id={`gh-${uid}`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="var(--brand-2)" />
          <stop offset="100%" stopColor="var(--brand)" />
        </linearGradient>
        {/* userSpaceOnUse for the same reason as the gradient: the default
            objectBoundingBox filter region collapses to nothing on a line. */}
        <filter
          id={`glow-${uid}`}
          filterUnits="userSpaceOnUse"
          x="-40"
          y="-40"
          width="336"
          height="336"
        >
          <feGaussianBlur stdDeviation="6" result="b" />
          <feMerge>
            <feMergeNode in="b" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
        {/* userSpaceOnUse keeps the head a fixed 28 units regardless of stroke
            width - the default (strokeWidth) would scale it to ~65 units and
            push it outside the viewBox. */}
        <marker
          id={`head-${uid}`}
          viewBox="0 0 12 12"
          refX="8.5"
          refY="6"
          markerWidth="28"
          markerHeight="28"
          markerUnits="userSpaceOnUse"
          orient="auto-start-reverse"
        >
          <path d="M1.5 1 L11 6 L1.5 11 Z" fill={`url(#gh-${uid})`} />
        </marker>
      </defs>

      {/* Face plate */}
      <rect
        x="34"
        y="34"
        width="188"
        height="188"
        rx="26"
        fill="rgba(0,0,0,0.28)"
        stroke="var(--hairline-strong)"
        strokeWidth="2.5"
        strokeDasharray={move.face === "B" ? "10 8" : undefined}
      />

      {/* Nine cells. F/B light the whole face, so those cells are held back to
          keep the arrow on top of them legible. */}
      {Array.from({ length: 9 }, (_, index) => {
        const row = Math.floor(index / 3);
        const col = index % 3;
        const active = highlight.has(index);
        const activeOpacity = move.face === "F" || move.face === "B" ? 0.4 : 0.92;
        return (
          <rect
            key={index}
            x={46 + col * 62}
            y={46 + row * 62}
            width="52"
            height="52"
            rx="12"
            fill={active ? `url(#g-${uid})` : "var(--hairline)"}
            fillOpacity={active ? activeOpacity : 0.5}
            stroke={active ? "var(--brand)" : "var(--hairline-strong)"}
            strokeWidth="2"
          />
        );
      })}

      <ArrowFor move={move} uid={uid} clockwise={clockwise} animated={animated} />

      {isDouble && (
        /* Placed in whichever corner the arrow does not occupy. */
        <g transform={move.face === "D" ? "translate(16 8)" : "translate(16 208)"}>
          <rect
            x="0"
            y="0"
            width="62"
            height="34"
            rx="12"
            fill="var(--brand)"
            fillOpacity="0.28"
            stroke="var(--brand)"
            strokeWidth="2"
          />
          <text
            x="31"
            y="24"
            textAnchor="middle"
            fontSize="18"
            fontWeight="700"
            fill="var(--ink)"
            fontFamily="var(--font)"
          >
            180°
          </text>
        </g>
      )}
    </svg>
  );
}

function ArrowFor({
  move,
  uid,
  clockwise,
  animated,
}: {
  move: MoveInfo;
  uid: string;
  clockwise: boolean;
  animated: boolean;
}) {
  const stroke = `url(#g-${uid})`;
  const common = {
    fill: "none",
    stroke,
    strokeWidth: 12,
    strokeLinecap: "round" as const,
    filter: `url(#glow-${uid})`,
    markerEnd: `url(#head-${uid})`,
    ...(move.modifier === "2" ? { markerStart: `url(#head-${uid})` } : {}),
  };
  const className = animated ? "arrow-path" : undefined;

  if (move.face === "F" || move.face === "B") {
    const d = clockwise
      ? "M 76 128 A 52 52 0 1 1 128 180"
      : "M 180 128 A 52 52 0 1 0 128 180";
    return <path d={d} className={className} style={{ "--len": 300 } as never} {...common} />;
  }

  // Straight arrows point the way the layer moves for the person holding the cube
  // (move.arrow comes from backend/core/moves.py, where tests check it).
  if (move.face === "U" || move.face === "D") {
    const y = move.face === "U" ? 20 : 236;
    const [x1, x2] = move.arrow === "right" ? [56, 196] : [196, 56];
    return (
      <path
        d={`M${x1} ${y} L${x2} ${y}`}
        className={className}
        style={{ "--len": 150 } as never}
        {...common}
      />
    );
  }

  const x = move.face === "L" ? 20 : 236;
  const [y1, y2] = move.arrow === "up" ? [196, 56] : [56, 196];
  return (
    <path
      d={`M${x} ${y1} L${x} ${y2}`}
      className={className}
      style={{ "--len": 150 } as never}
      {...common}
    />
  );
}

/* ==================================================================== */
/* Badges & strips                                                      */
/* ==================================================================== */

export function MoveBadge({
  move,
  state = "pending",
  onClick,
  title,
}: {
  move: MoveInfo;
  state?: "pending" | "active" | "done";
  onClick?: () => void;
  title?: string;
}) {
  return (
    <button
      type="button"
      className="move-badge"
      data-state={state}
      onClick={onClick}
      title={title ?? move.label}
    >
      {move.notation}
      <DirectionMark direction={move.direction} />
    </button>
  );
}

/** Tiny rotation cue next to the notation so direction is never text-only. */
function DirectionMark({ direction }: { direction: Direction }) {
  if (direction === "double") {
    return (
      <svg width="13" height="13" viewBox="0 0 24 24" aria-hidden="true">
        <path
          d="M6 9a7 7 0 1 1 0 6"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.4"
          strokeLinecap="round"
        />
        <path d="M2.5 6.5 6.5 9 3 12z" fill="currentColor" />
      </svg>
    );
  }
  const flip = direction === "ccw";
  return (
    <svg
      width="13"
      height="13"
      viewBox="0 0 24 24"
      aria-hidden="true"
      style={flip ? { transform: "scaleX(-1)" } : undefined}
    >
      <path
        d="M5 13a7.5 7.5 0 1 1 3 6"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.4"
        strokeLinecap="round"
      />
      <path d="M4.4 8.6 8.8 12l-5 1.6z" fill="currentColor" />
    </svg>
  );
}

export function MoveStrip({
  moves,
  index,
  onSelect,
}: {
  moves: MoveInfo[];
  index: number;
  onSelect?: (index: number) => void;
}) {
  return (
    <div className="move-strip">
      {moves.map((move, position) => (
        <MoveBadge
          key={`${move.notation}-${position}`}
          move={move}
          state={position < index ? "done" : position === index ? "active" : "pending"}
          title={`Move ${position + 1}: ${move.label}. ${move.instruction}`}
          onClick={onSelect ? () => onSelect(position) : undefined}
        />
      ))}
    </div>
  );
}
