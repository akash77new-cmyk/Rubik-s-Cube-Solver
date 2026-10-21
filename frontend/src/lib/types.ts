/**
 * Wire types. These mirror the dicts produced by the Python backend
 * (`SolveSession.snapshot()` and friends) - keep the two in sync.
 */

export type FaceKey = "U" | "R" | "F" | "D" | "L" | "B";
export type ColorCode = "W" | "Y" | "R" | "O" | "G" | "B";
export type LogLevel = "debug" | "info" | "success" | "warn" | "error";
export type Direction = "cw" | "ccw" | "double";
/** Which way a turn moves for the person holding the cube (backend/core/moves.py). */
export type TurnArrow = "left" | "right" | "up" | "down" | "clockwise" | "counter-clockwise";

export const FACE_ORDER: FaceKey[] = ["U", "R", "F", "D", "L", "B"];
export const COLOR_CODES: ColorCode[] = ["W", "Y", "R", "O", "G", "B"];

export interface MoveInfo {
  notation: string;
  face: FaceKey;
  faceName: string;
  modifier: "" | "'" | "2";
  direction: Direction;
  axis: "x" | "y" | "z";
  quarterTurns: number;
  label: string;
  arrow: TurnArrow;
  /** The turn in plain English, e.g. "Turn the right side up, away from you.". */
  instruction: string;
}

export type Facelets = Record<FaceKey, ColorCode[]>;

export interface CubeInfo {
  facelets: Facelets;
  centers: Record<FaceKey, ColorCode>;
  colorString: string;
  isSolved: boolean;
  solvedStickers: number;
}

/** One reason why a cube is impossible (see backend/core/validation.py). */
export interface ValidationIssue {
  code: string;
  message: string;
  /** Stickers involved: face + 0-based index in reading order. */
  stickers: { face: FaceKey; index: number }[];
  pieces: string[];
  details: Record<string, unknown>;
}

export interface ValidationInfo {
  ok: boolean;
  errors: string[];
  warnings: string[];
  issues: ValidationIssue[];
}

/** One colour's fit for a sticker (see ColorProfile.rank in backend/core/color.py). */
export interface ColorScoreInfo {
  color: ColorCode;
  confidence: number;
  inRange: boolean;
}

/** Why a reading is doubtful: outside every colour range, or inside two. */
export type UncertainReason = "no_range" | "two_ranges";

export interface StickerReading {
  index: number;
  row: number;
  col: number;
  x: number;
  y: number;
  hsv: [number, number, number];
  color: ColorCode;
  colorName: string;
  confidence: number;
  /** Best three colours, best first. */
  alternatives: ColorScoreInfo[];
  uncertain: UncertainReason | null;
}

export interface DetectionInfo {
  readings: StickerReading[];
  colors: ColorCode[];
  meanConfidence: number;
  minConfidence: number;
  bbox: [number, number, number, number] | null;
  quad: [number, number][] | null;
  stable: boolean;
  stability: number;
  timestamp: number;
  fps?: number;
  face?: FaceKey | null;
  /** Auto-capture hold timer: the face being held still, and how far (0 to 1). */
  holdFace?: FaceKey | null;
  hold?: number;
}

export interface CameraInfo {
  running: boolean;
  index: number;
  requestedResolution: [number, number];
  resolution: [number, number] | null;
  fps: number;
  targetFps: number;
  mirror: boolean;
  framesCaptured: number;
  uptimeSeconds: number;
  error: string | null;
}

export interface SolverBackendInfo {
  key: string;
  name: string;
  description: string;
  installed: boolean;
  needsWarmup: boolean;
}

export interface SolverInfo {
  state: "uninitialised" | "warming" | "ready" | "error";
  message: string;
  ready: boolean;
  backend: string | null;
  backendKey: string | null;
  description: string;
  available: SolverBackendInfo[];
}

export interface SolutionInfo {
  moves: MoveInfo[];
  notation: string;
  moveCount: number;
  quarterTurnCount: number;
  backend: string;
  elapsedMs: number;
  faceletString: string;
  faceDistribution: Record<FaceKey, number>;
  turnDistribution: Record<Direction, number>;
  states: Facelets[];
}

export interface PlaybackInfo {
  index: number;
  total: number;
  playing: boolean;
  completed: boolean;
  /** False until the user confirms they hold the cube the right way (before move 1). */
  ready: boolean;
  progress: number;
  current: MoveInfo | null;
  previous: MoveInfo | null;
  next: MoveInfo | null;
  history: MoveInfo[];
  cube: Facelets | null;
}

export interface ScanFaceInfo {
  name: string;
  captured: boolean;
  colors?: ColorCode[];
  confidence?: number;
  minConfidence?: number;
  timestamp?: number;
  auto?: boolean;
  /** What the camera saw for each sticker (camera scans only; absent for scrambles). */
  stickers?: StickerReading[];
}

/** One step of the scan guide (backend/core/scanning.py). */
export interface ScanStepInfo {
  face: FaceKey;
  /** Centre colour that must face the camera. */
  center: ColorCode;
  /** Colour that must be on top. */
  top: ColorCode;
  text: string;
  how: string;
  done: boolean;
}

export interface ScanInfo {
  order: FaceKey[];
  faces: Record<FaceKey, ScanFaceInfo>;
  current: FaceKey | null;
  hint: string;
  count: number;
  autoCapture: boolean;
  /** The guide, in its suggested order. */
  steps: ScanStepInfo[];
}

export interface HsvRange {
  h_min: number;
  h_max: number;
  s_min: number;
  s_max: number;
  v_min: number;
  v_max: number;
  wrap_hue: boolean;
}

export interface CalibrationInfo {
  active: boolean;
  target: ColorCode;
  sampleCount: number;
  profileName: string;
  builtin: boolean;
  ranges: Record<ColorCode, HsvRange>;
  colors: { code: ColorCode; name: string }[];
  availableProfiles: string[];
  activeProfile: string;
  sample?: { h: number; s: number; v: number };
  coverage?: number;
  histogram?: number[];
}

/** `midnight` is a true-black variant of dark, for OLED panels and dim rooms. */
export type ThemeName = "dark" | "midnight" | "light";

export const THEMES: readonly { value: ThemeName; label: string; hint: string }[] = [
  { value: "dark", label: "Dark", hint: "Deep navy, the default" },
  { value: "midnight", label: "Midnight", hint: "True black with extra glow" },
  { value: "light", label: "Light", hint: "Bright, for well-lit rooms" },
] as const;

export interface SettingsInfo {
  camera_index: number;
  frame_width: number;
  frame_height: number;
  target_fps: number;
  mirror_camera: boolean;
  sample_radius: number;
  grid_spacing: number;
  grid_offset_y: number;
  min_confidence: number;
  active_profile: string;
  auto_capture_hold_ms: number;
  show_grid: boolean;
  show_labels: boolean;
  show_bounding_box: boolean;
  show_confidence: boolean;
  arrow_style: "neon" | "solid" | "outline";
  animation_speed: number;
  autoplay_interval_ms: number;
  theme: ThemeName;
  accent: string;
  cube_palette: Record<ColorCode, string>;
}

export interface SolveRecord {
  id: string;
  started_at: number;
  finished_at: number;
  move_count: number;
  quarter_turns: number;
  solve_ms: number;
  scan_seconds: number;
  execution_seconds: number;
  backend: string;
  notation: string;
  face_distribution: Record<FaceKey, number>;
  turn_distribution: Record<Direction, number>;
  detection_confidence: number;
  source: string;
}

export interface AnalyticsInfo {
  totalSolves: number;
  sessionSolves: number;
  sessionSeconds: number;
  averageMoveCount: number;
  averageSolveMs: number;
  averageExecutionSeconds: number;
  bestMoveCount: number;
  totalMoves: number;
  averageConfidence: number;
  faceDistribution: Record<FaceKey, number>;
  turnDistribution: Record<Direction, number>;
  recent: SolveRecord[];
  timeline: {
    index: number;
    moveCount: number;
    solveMs: number;
    executionSeconds: number;
    finishedAt: number;
  }[];
}

export interface LogEntry {
  id: number;
  timestamp: number;
  level: LogLevel;
  source: string;
  message: string;
  detail: Record<string, unknown> | null;
}

export type SessionMode =
  | "idle"
  | "scan"
  | "scanned"
  | "solving"
  | "solution"
  | "execute"
  | "complete";

export interface Snapshot {
  mode: SessionMode;
  camera: CameraInfo;
  solver: SolverInfo;
  solving: boolean;
  solveError: string | null;
  scan: ScanInfo;
  cube: CubeInfo | null;
  cubeSource: string;
  validation: ValidationInfo | null;
  solution: SolutionInfo | null;
  playback: PlaybackInfo;
  analytics: AnalyticsInfo;
  settings: SettingsInfo;
  calibration: CalibrationInfo;
  detection: DetectionInfo | null;
  physicalSteps: string[];
  dataset: DatasetInfo;
  database: DatabaseInfo | null;
  timestamp: number;
}

/** Where settings, HSV profiles and solve history are stored (Phase 3). */
export interface DatabaseInfo {
  backend: "PostgreSQL" | "SQLite";
  provider: string | null;
  location: string;
  /** null until the first check */
  connected: boolean | null;
  error: string | null;
  serverVersion: string | null;
  schemaRevision: string | null;
  /** pgvector version the server offers (used from Phase 7), or null */
  pgvector: string | null;
  checkedAt: number | null;
}

export interface DatasetStats {
  scans: number;
  stickers: number;
  corrected: number;
  uncertain: number;
  byLighting: Record<string, number>;
  byColor: Record<ColorCode, number>;
  lastScanId: string | null;
}

/** Training-data collection for the Phase 11 classifier (backend/services/dataset.py). */
export interface DatasetInfo {
  enabled: boolean;
  canSave: boolean;
  reason: string | null;
  saved: boolean;
  lightingOptions: { value: string; label: string }[];
  stats: DatasetStats | null;
}
