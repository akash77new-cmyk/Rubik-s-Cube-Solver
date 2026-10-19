import type { ColorCode, FaceKey } from "./types";

/** Sticker colours. Kept in sync with tokens.css and backend/vision/overlay.py. */
export const CUBE_COLORS: Record<ColorCode, string> = {
  W: "#F8FAFC",
  Y: "#FACC15",
  R: "#EF4444",
  O: "#F97316",
  G: "#22C55E",
  B: "#3B82F6",
};

export const COLOR_NAMES: Record<ColorCode, string> = {
  W: "White",
  Y: "Yellow",
  R: "Red",
  O: "Orange",
  G: "Green",
  B: "Blue",
};

export const FACE_NAMES: Record<FaceKey, string> = {
  U: "Up",
  R: "Right",
  F: "Front",
  D: "Down",
  L: "Left",
  B: "Back",
};

/** Position of each face in the unfolded-net layout (4 columns x 3 rows). */
export const NET_POSITION: Record<FaceKey, { col: number; row: number }> = {
  U: { col: 2, row: 1 },
  L: { col: 1, row: 2 },
  F: { col: 2, row: 2 },
  R: { col: 3, row: 2 },
  B: { col: 4, row: 2 },
  D: { col: 2, row: 3 },
};

export const stickerColor = (
  code: ColorCode | undefined,
  palette?: Partial<Record<ColorCode, string>>,
): string => (code ? palette?.[code] ?? CUBE_COLORS[code] ?? "#333" : "#333");

/** Readable ink for text drawn on top of a sticker. */
export const stickerInk = (code: ColorCode | undefined): string =>
  code === "W" || code === "Y" ? "#0B0B12" : "#FFFFFF";
