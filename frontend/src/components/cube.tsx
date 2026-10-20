/**
 * Cube renderers.
 *
 * `Cube3D` builds a real 3x3x3 stack of 26 cubies with CSS 3D transforms, so a
 * face turn can be animated by rotating the nine cubies of that layer around
 * the correct axis - not by cross-fading a picture of a cube.
 *
 * `CubeNet` is the flat unfolded view: better for reading the whole state at a
 * glance and for correcting a mis-detected sticker by clicking it.
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { CUBE_COLORS, FACE_NAMES, NET_POSITION, stickerColor } from "@/lib/colors";
import { clamp } from "@/lib/format";
import { FACE_ORDER, type ColorCode, type FaceKey, type Facelets, type MoveInfo } from "@/lib/types";

/* ==================================================================== */
/* Facelet <-> cubie mapping                                            */
/* ==================================================================== */

type Vec = { x: -1 | 0 | 1; y: -1 | 0 | 1; z: -1 | 0 | 1 };

/**
 * Index of the sticker a cubie shows on `face`, derived from its grid position.
 * Screen axes: +x right, +y down, +z towards the viewer.
 */
function faceletIndex(face: FaceKey, { x, y, z }: Vec): number {
  switch (face) {
    case "F": return (y + 1) * 3 + (x + 1);       // seen from +z
    case "B": return (y + 1) * 3 + (1 - x);       // seen from -z
    case "R": return (y + 1) * 3 + (1 - z);       // left column touches F
    case "L": return (y + 1) * 3 + (z + 1);       // left column touches B
    case "U": return (z + 1) * 3 + (x + 1);       // top row touches B
    case "D": return (1 - z) * 3 + (x + 1);       // top row touches F
  }
}

/** Which coordinate a face turn holds fixed, and at what value. */
const LAYER_TEST: Record<FaceKey, (c: Vec) => boolean> = {
  U: (c) => c.y === -1,
  D: (c) => c.y === 1,
  R: (c) => c.x === 1,
  L: (c) => c.x === -1,
  F: (c) => c.z === 1,
  B: (c) => c.z === -1,
};

/** Rotation axis and sign that makes a *clockwise* turn look clockwise. */
const TURN_AXIS: Record<FaceKey, { axis: "X" | "Y" | "Z"; sign: 1 | -1 }> = {
  U: { axis: "Y", sign: -1 },
  D: { axis: "Y", sign: 1 },
  R: { axis: "X", sign: 1 },
  L: { axis: "X", sign: -1 },
  F: { axis: "Z", sign: 1 },
  B: { axis: "Z", sign: -1 },
};

function turnTransform(move: MoveInfo, progress: number): string {
  const { axis, sign } = TURN_AXIS[move.face];
  const magnitude = move.modifier === "2" ? 180 : 90;
  const direction = move.modifier === "'" ? -1 : 1;
  const angle = sign * direction * magnitude * progress;
  return `rotate${axis}(${angle}deg)`;
}

const CUBIES: Vec[] = (() => {
  const list: Vec[] = [];
  for (let x = -1; x <= 1; x += 1)
    for (let y = -1; y <= 1; y += 1)
      for (let z = -1; z <= 1; z += 1)
        if (x || y || z) list.push({ x, y, z } as Vec);
  return list;
})();

/** Faces of the whole cube a given cubie is on the outside of. */
function visibleFaces({ x, y, z }: Vec): FaceKey[] {
  const faces: FaceKey[] = [];
  if (z === 1) faces.push("F");
  if (z === -1) faces.push("B");
  if (x === 1) faces.push("R");
  if (x === -1) faces.push("L");
  if (y === -1) faces.push("U");
  if (y === 1) faces.push("D");
  return faces;
}

/** Transform that lays a cubie's face onto the correct side of the cubie. */
const FACE_TRANSFORM: Record<FaceKey, (half: number) => string> = {
  F: (h) => `translateZ(${h}px)`,
  B: (h) => `rotateY(180deg) translateZ(${h}px)`,
  R: (h) => `rotateY(90deg) translateZ(${h}px)`,
  L: (h) => `rotateY(-90deg) translateZ(${h}px)`,
  U: (h) => `rotateX(90deg) translateZ(${h}px)`,
  D: (h) => `rotateX(-90deg) translateZ(${h}px)`,
};

/* ==================================================================== */
/* Cube3D                                                               */
/* ==================================================================== */

/**
 * How much room a cube needs relative to its edge length. A cube rotated to an
 * arbitrary orientation sweeps a circle of diameter `sqrt(3) * edge`; 1.7 is
 * that, less a hair, since the orbit is clamped to +/-88 degrees on X.
 */
const FOOTPRINT = 1.7;

const ZOOM_MIN = 0.55;
const ZOOM_MAX = 1.9;

export interface Cube3DProps {
  facelets: Facelets;
  /** The move that produced `facelets`; supplying it animates the layer turn. */
  move?: MoveInfo | null;
  /** Facelets *before* `move` - required for the turn animation to look right. */
  previousFacelets?: Facelets | null;
  size?: number;
  autoRotate?: boolean;
  interactive?: boolean;
  showLabels?: boolean;
  durationMs?: number;
  palette?: Partial<Record<ColorCode, string>>;
  highlightFace?: FaceKey | null;
  onStickerClick?: (face: FaceKey, index: number) => void;
}

export function Cube3D({
  facelets,
  move = null,
  previousFacelets = null,
  size = 220,
  autoRotate = false,
  interactive = true,
  showLabels = false,
  durationMs = 420,
  palette,
  highlightFace = null,
  onStickerClick,
}: Cube3DProps) {
  const [rotation, setRotation] = useState({ x: -24, y: -32 });
  const [zoom, setZoom] = useState(1);
  const [turning, setTurning] = useState(false);
  const dragRef = useRef<{ x: number; y: number } | null>(null);
  const lastMoveRef = useRef<MoveInfo | null>(null);
  const frozenRef = useRef<Facelets | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const [available, setAvailable] = useState<number | null>(null);

  /* -- Fit to the container ------------------------------------------- */
  // A cube spun to an arbitrary angle sweeps a circle of sqrt(3) x its edge,
  // and CSS transforms do not contribute to layout - so the stage has to
  // reserve that footprint itself or the cube visually spills over whatever
  // sits next to it.
  useEffect(() => {
    const element = wrapRef.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) =>
      setAvailable(entry.contentRect.width),
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const fitted = available ? Math.floor(available / FOOTPRINT) : size;
  const effectiveSize = Math.max(96, Math.min(size, fitted));

  /* -- Layer turn animation ------------------------------------------ */
  useEffect(() => {
    if (!move || move === lastMoveRef.current || !previousFacelets) {
      lastMoveRef.current = move;
      return;
    }
    lastMoveRef.current = move;
    frozenRef.current = previousFacelets;
    setTurning(true);
    const timer = window.setTimeout(() => {
      frozenRef.current = null;
      setTurning(false);
    }, durationMs);
    return () => window.clearTimeout(timer);
  }, [move, previousFacelets, durationMs]);

  const rendered = turning && frozenRef.current ? frozenRef.current : facelets;
  const activeMove = turning ? move : null;

  /* -- Auto rotate ---------------------------------------------------- */
  useEffect(() => {
    if (!autoRotate) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    let frame = 0;
    let previous = performance.now();
    const tick = (now: number) => {
      const delta = now - previous;
      previous = now;
      setRotation((current) => ({ ...current, y: current.y + delta * 0.014 }));
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [autoRotate]);

  /* -- Drag to orbit -------------------------------------------------- */
  const onPointerDown = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      if (!interactive) return;
      dragRef.current = { x: event.clientX, y: event.clientY };
      event.currentTarget.setPointerCapture(event.pointerId);
    },
    [interactive],
  );

  const onPointerMove = useCallback((event: ReactPointerEvent<HTMLDivElement>) => {
    const origin = dragRef.current;
    if (!origin) return;
    const dx = event.clientX - origin.x;
    const dy = event.clientY - origin.y;
    dragRef.current = { x: event.clientX, y: event.clientY };
    setRotation((current) => ({
      x: clamp(current.x - dy * 0.45, -88, 88),
      y: current.y + dx * 0.45,
    }));
  }, []);

  const endDrag = useCallback(() => {
    dragRef.current = null;
  }, []);

  /* -- Zoom ------------------------------------------------------------ */
  // Bound natively with { passive: false } so preventDefault actually works.
  // Plain wheel is left alone: hijacking it made scrolling past the cube
  // silently resize it. Ctrl/Cmd + wheel is the conventional zoom gesture.
  useEffect(() => {
    const element = stageRef.current;
    if (!element || !interactive) return;
    const onWheel = (event: WheelEvent) => {
      if (!event.ctrlKey && !event.metaKey) return;
      event.preventDefault();
      setZoom((z) => clamp(z - event.deltaY * 0.0015, ZOOM_MIN, ZOOM_MAX));
    };
    element.addEventListener("wheel", onWheel, { passive: false });
    return () => element.removeEventListener("wheel", onWheel);
  }, [interactive]);

  const nudgeZoom = useCallback(
    (delta: number) => setZoom((z) => clamp(z + delta, ZOOM_MIN, ZOOM_MAX)),
    [],
  );

  const cubieSize = effectiveSize / 3;
  const half = cubieSize / 2;
  const gap = 1.5;

  const groups = useMemo(() => {
    const inLayer = activeMove ? LAYER_TEST[activeMove.face] : null;
    const still: Vec[] = [];
    const moving: Vec[] = [];
    for (const cubie of CUBIES) (inLayer && inLayer(cubie) ? moving : still).push(cubie);
    return { still, moving };
  }, [activeMove]);

  const renderCubie = (cubie: Vec) => (
    <div
      key={`${cubie.x}${cubie.y}${cubie.z}`}
      className="cubie"
      style={{
        width: cubieSize - gap,
        height: cubieSize - gap,
        transform: `translate3d(${cubie.x * cubieSize - half + gap / 2}px, ${
          cubie.y * cubieSize - half + gap / 2
        }px, ${cubie.z * cubieSize - half + gap / 2}px)`,
      }}
    >
      {visibleFaces(cubie).map((face) => {
        const index = faceletIndex(face, cubie);
        const code = rendered[face]?.[index];
        const dim = highlightFace ? face !== highlightFace : false;
        return (
          <div
            key={face}
            className="cubie-face"
            data-dim={dim}
            data-clickable={Boolean(onStickerClick)}
            style={{
              transform: FACE_TRANSFORM[face](half - gap / 2),
              background: stickerColor(code, palette),
            }}
            title={showLabels ? `${FACE_NAMES[face]} · ${code ?? "?"}` : undefined}
            onClick={onStickerClick ? () => onStickerClick(face, index) : undefined}
          />
        );
      })}
    </div>
  );

  const footprint = Math.round(effectiveSize * FOOTPRINT);

  return (
    <div className="cube3d-wrap" ref={wrapRef}>
      <div
        className="cube3d-stage"
        ref={stageRef}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        style={{ width: footprint, height: footprint }}
      >
        <div
          className="cube3d"
          style={{
            width: effectiveSize,
            height: effectiveSize,
            transform: `scale(${zoom}) rotateX(${rotation.x}deg) rotateY(${rotation.y}deg)`,
            transition: dragRef.current || autoRotate ? "none" : undefined,
          }}
        >
          {groups.still.map(renderCubie)}
          {groups.moving.length > 0 && (
            <div
              className="cube-layer"
              style={{
                transform: activeMove ? turnTransform(activeMove, 1) : undefined,
                transition: `transform ${durationMs}ms cubic-bezier(0.5, 0, 0.2, 1)`,
              }}
            >
              {groups.moving.map(renderCubie)}
            </div>
          )}
        </div>
        <div className="cube3d-shadow" style={{ width: effectiveSize * 0.8 }} />
      </div>

      {interactive && (
        <div className="cube3d-controls">
          <button
            type="button"
            className="zoom-btn"
            onClick={() => nudgeZoom(-0.2)}
            disabled={zoom <= ZOOM_MIN + 0.001}
            aria-label="Zoom out"
          >
            −
          </button>
          <span className="cube3d-hint">
            drag to orbit · {Math.round(zoom * 100)}%
          </span>
          <button
            type="button"
            className="zoom-btn"
            onClick={() => nudgeZoom(0.2)}
            disabled={zoom >= ZOOM_MAX - 0.001}
            aria-label="Zoom in"
          >
            +
          </button>
        </div>
      )}
    </div>
  );
}

/** Reset/orbit controls shared by the viewer pages. */
export function useCubeView(initial = { x: -24, y: -32 }) {
  const [view, setView] = useState(initial);
  return {
    view,
    reset: () => setView(initial),
    setView,
  };
}

/* ==================================================================== */
/* CubeNet                                                              */
/* ==================================================================== */

export function CubeNet({
  facelets,
  capturedFaces,
  activeFace = null,
  editable = false,
  paintColor,
  faceSize,
  onStickerClick,
  palette,
  flagged,
  uncertain,
  notes,
}: {
  facelets: Partial<Facelets> | null;
  capturedFaces?: Partial<Record<FaceKey, boolean>>;
  activeFace?: FaceKey | null;
  editable?: boolean;
  paintColor?: ColorCode;
  faceSize?: number;
  onStickerClick?: (face: FaceKey, index: number) => void;
  palette?: Partial<Record<ColorCode, string>>;
  /** Sticker keys like "U8" (face + 0-based index) to outline as problems. */
  flagged?: ReadonlySet<string>;
  /** Sticker keys like "U8" the camera was unsure about (dashed outline). */
  uncertain?: ReadonlySet<string>;
  /** Extra tooltip text per sticker key, e.g. what the camera saw. */
  notes?: Readonly<Record<string, string>>;
}) {
  const previous = useRef<string>("");
  const signature = JSON.stringify(facelets ?? {});
  const changed = previous.current !== signature;
  useEffect(() => {
    previous.current = signature;
  }, [signature]);

  return (
    <div
      className="net"
      style={faceSize ? ({ "--face-size": `${faceSize}px` } as never) : undefined}
    >
      {FACE_ORDER.map((face) => {
        const position = NET_POSITION[face];
        const stickers = facelets?.[face];
        const captured = capturedFaces ? Boolean(capturedFaces[face]) : Boolean(stickers);
        return (
          <div
            key={face}
            className="net-face"
            data-active={activeFace === face}
            data-captured={captured}
            style={{ gridColumn: position.col, gridRow: position.row }}
          >
            <span className="net-face-label">{face}</span>
            {Array.from({ length: 9 }, (_, index) => {
              const code = stickers?.[index];
              return (
                <div
                  key={index}
                  className="sticker"
                  data-empty={!code}
                  data-editable={editable}
                  data-changed={changed && Boolean(code)}
                  data-flagged={flagged?.has(`${face}${index}`) ?? false}
                  data-uncertain={uncertain?.has(`${face}${index}`) ?? false}
                  style={{ "--c": stickerColor(code, palette) } as never}
                  title={`${FACE_NAMES[face]} ${index + 1}${code ? ` · ${code}` : ""}${
                    notes?.[`${face}${index}`] ? ` · ${notes[`${face}${index}`]}` : ""
                  }`}
                  onClick={
                    editable && onStickerClick
                      ? () => onStickerClick(face, index)
                      : undefined
                  }
                  role={editable ? "button" : undefined}
                  aria-label={
                    editable ? `Set ${FACE_NAMES[face]} sticker ${index + 1} to ${paintColor}` : undefined
                  }
                />
              );
            })}
          </div>
        );
      })}
    </div>
  );
}

/* ==================================================================== */
/* FaceGrid - a single 3x3 face, used by the scanner tiles               */
/* ==================================================================== */

export function FaceGrid({
  colors,
  size = 84,
  palette,
}: {
  colors?: ColorCode[] | null;
  size?: number;
  palette?: Partial<Record<ColorCode, string>>;
}) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(3, 1fr)",
        gap: 3,
        padding: 4,
        width: size,
        height: size,
        borderRadius: 12,
        background: "rgba(0,0,0,0.3)",
        border: "1px solid var(--hairline)",
      }}
    >
      {Array.from({ length: 9 }, (_, index) => (
        <div
          key={index}
          className="sticker"
          data-empty={!colors?.[index]}
          style={{ "--c": stickerColor(colors?.[index], palette) } as never}
        />
      ))}
    </div>
  );
}

/* ==================================================================== */
/* HeroCube - the dashboard's floating showpiece                         */
/* ==================================================================== */

export function HeroCube({ facelets, size = 168 }: { facelets: Facelets; size?: number }) {
  return (
    <div className="hero-cube">
      <Cube3D facelets={facelets} size={size} autoRotate interactive={false} />
    </div>
  );
}

/** A solved cube, for the hero when nothing has been scanned yet. */
export const SOLVED_FACELETS: Facelets = {
  U: Array<ColorCode>(9).fill("W"),
  R: Array<ColorCode>(9).fill("R"),
  F: Array<ColorCode>(9).fill("G"),
  D: Array<ColorCode>(9).fill("Y"),
  L: Array<ColorCode>(9).fill("O"),
  B: Array<ColorCode>(9).fill("B"),
};

export const COLOR_SWATCHES = CUBE_COLORS;
