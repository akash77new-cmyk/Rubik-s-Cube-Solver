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
  ai: AIStatus | null;
  repair: RepairInfo | null;
  /** Solve & Learn (Phase 8), or null when not learning */
  learn: LearnState | null;
  timestamp: number;
}

/* ------------------------------------------------------------------ Solve & Learn (Phase 8) */

/** One stage of the beginner method, with how the learner did (backend/services/learn.py). */
export interface LearnStage {
  number: number;
  name: string;
  goal: string;
  learned: string;
  /** The colour on top while doing this stage */
  top: ColorCode;
  /** The lesson section that teaches it */
  lesson: string;
  done: boolean;
  current: boolean;
  hints: number;
  shown: number;
  moves: number;
  /** Done without hints or "Show me" */
  alone: boolean;
}

/** The next step. Algorithm and moves are only sent once a hint reveals them. */
export interface LearnStep {
  stage: number;
  kind: "moves" | "turn_over";
  task: string;
  piece: string | null;
  /** Sticker keys to highlight on the 3D cube, e.g. "U7" */
  focus: string[];
  how?: string;
  algorithm?: string | null;
  algorithmNotation?: string | null;
  moves?: MoveInfo[];
  notation?: string;
}

export interface LearnHint {
  level: number;
  text: string;
  /** "built-in" at first, then "gemini" (or "fallback") when the tutor answers */
  source: string;
  model: string | null;
}

/** The tutor's answer to a "why?" question, or its recap. */
export interface TutorAnswer {
  kind: "question" | "recap";
  question?: string | null;
  message: string;
  citations?: string[];
  sources?: CoachSource[];
  source: string;
  model: string | null;
  reason?: string | null;
}

export interface LearnState {
  id: string;
  /** True once the learner holds the cube as shown */
  ready: boolean;
  /** 1-7, or 8 when solved */
  stage: number;
  solved: boolean;
  top: ColorCode;
  front: ColorCode;
  cube: Facelets;
  /** Grows with every change; the 3D cube animates each move once */
  version: number;
  previous: Facelets | null;
  lastMove: MoveInfo | null;
  lastAction: string | null;
  moveCount: number;
  history: string[];
  stages: LearnStage[];
  step: LearnStep | null;
  hintLevel: number;
  hints: LearnHint[];
  /** Moves still to do from "Show me" */
  guide: MoveInfo[];
  /** All the moves that were shown, and what they do (while guiding) */
  guideAll: MoveInfo[];
  guideTask: string | null;
  note: string | null;
  justDone: { number: number; name: string; learned: string } | null;
  answer: TutorAnswer | null;
  recap: TutorAnswer | null;
  stats: {
    moves: number;
    stagesAlone: string[];
    stagesWithHelp: string[];
    hints: number;
    shown: number;
    seconds: number;
    /** The stage that needed the most help */
    practise: string | null;
  };
  tutorBusy: boolean;
}

/** One sticker change of a repair proposal (computed by code, never by the model). */
export interface RepairChange {
  face: FaceKey;
  index: number;
  from: ColorCode;
  to: ColorCode;
  /** How sure the camera was of the colour it read (1 = no camera data) */
  oldConfidence: number;
  /** How well the new colour fitted that sticker (0 = not among its best 3) */
  newConfidence: number;
}

/** The Smart Repair Agent's card after an unsolvable scan (Phase 5). */
export interface RepairInfo {
  status: "working" | "ready" | "applied";
  /** The cube this repair belongs to (54 colour codes) */
  cube: string;
  action?: "apply_fix" | "rescan_side";
  message?: string;
  changes?: RepairChange[];
  side?: FaceKey | null;
  /** "gemini" (or another provider), or "search" for the built-in search */
  source?: string;
  model?: string | null;
  /** Why the built-in search answered */
  reason?: string | null;
  fixesFound?: number;
}

/** The AI assistant's status (Phase 4). */
export interface AIStatus {
  enabled: boolean;
  provider: string | null;
  model: string | null;
  /** Why AI is off, e.g. "no Gemini API key is set" */
  offReason: string | null;
  busy: boolean;
  budget: { usedLastMinute: number; perMinute: number; usedToday: number; perDay: number };
  lastError: string | null;
  /** The lessons behind the RAG coach (Phase 7) */
  lessons: LessonsStatus | null;
}

export interface LessonsStatus {
  lessons: number;
  sections: number;
  /** Sections with an embedding from the current model */
  embedded: number;
  model: string | null;
  /** How the coach searches right now */
  search: "pgvector" | "vectors in Python" | "keywords";
  error: string | null;
}

/** One lesson (the lessons:list event); each section is one searchable, citable chunk. */
export interface Lesson {
  slug: string;
  title: string;
  summary: string;
  sections: { id: string; title: string; text: string }[];
}

/** A lesson section the coach cited. */
export interface CoachSource {
  id: string;
  lesson: string;
  lessonTitle: string;
  section: string;
}

/** One answer from the coach (the coach:answer event). */
export interface CoachAnswer {
  runId: string;
  question: string;
  answer: string;
  /** False when the lessons don't cover the question */
  covered: boolean;
  citations: string[];
  sources: CoachSource[];
  suggestions: string[];
  search: string;
  /** "gemini", or "fallback" for the built-in answer */
  source: string;
  model: string | null;
  reason: string | null;
  requests: number;
  durationMs: number;
  /** Only when the coach itself failed */
  error?: string;
}

/** One answer from the assistant (the ai:answer event). */
export interface AIAnswer {
  runId: string;
  question: string;
  answer: string;
  suggestions: string[];
  /** "gemini", or "fallback" for the built-in answer */
  source: string;
  model: string | null;
  /** Why the built-in answer was used */
  reason: string | null;
  requests: number;
  toolCalls: number;
  inputTokens: number;
  outputTokens: number;
  durationMs: number;
  /** Only when the assistant itself failed; then the other fields are missing. */
  error?: string;
}

/** The assistant is working: step 0 = thinking, then one event per tool call. */
export interface AIProgress {
  runId: string;
  step: number;
  tool: string | null;
}

export interface AITraceStep {
  position: number;
  kind: "model" | "tool" | "answer" | "error";
  name: string;
  detail: Record<string, unknown>;
  durationMs: number;
}

/** One traced AI run with its steps (the ai:traces event). */
export interface AITrace {
  id: string;
  feature: string;
  question: string;
  source: string;
  reason: string | null;
  model: string | null;
  answer: { answer: string; suggestions?: string[] } | null;
  requestCount: number;
  inputTokens: number;
  outputTokens: number;
  startedAt: number;
  durationMs: number;
  steps: AITraceStep[];
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
