/**
 * Real-time application state.
 *
 * One Socket.IO connection mirrors the engine's session snapshot into React.
 * Every page reads from this store and every user action goes out as a single
 * `command` event, so the engine stays the single source of truth and the UI
 * never holds a divergent copy of the cube.
 *
 * Phase 9: before connecting, the store asks the server who this browser is (a guest
 * or an account). The socket's handshake then carries the login cookie, so the server
 * puts this browser in its own session: other visitors never see this cube.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { io, type Socket } from "socket.io-client";
import { fetchAccount, type Account } from "@/lib/account";
import type {
  AIAnswer,
  AIProgress,
  AIStatus,
  AITrace,
  AnalyticsInfo,
  CoachAnswer,
  Lesson,
  CalibrationInfo,
  CameraInfo,
  DatabaseInfo,
  DetectionInfo,
  LogEntry,
  SettingsInfo,
  Snapshot,
  SolutionInfo,
  SolverInfo,
} from "@/lib/types";

const MAX_LOGS = 400;

declare global {
  interface Window {
    /** Debug/automation handle for the live Socket.IO connection. */
    __cubeSocket?: Socket;
  }
}

export type ConnectionState = "connecting" | "online" | "offline";

export interface Toast {
  id: number;
  tone: "good" | "warning" | "critical" | "brand";
  title: string;
  message?: string;
}

interface AppStoreValue {
  connection: ConnectionState;
  snapshot: Snapshot | null;
  detection: DetectionInfo | null;
  logs: LogEntry[];
  toasts: Toast[];
  /** Frames rendered per second by the MJPEG viewport (client-side measure). */
  send: (command: string, payload?: Record<string, unknown>) => void;
  dismissToast: (id: number) => void;
  pushToast: (toast: Omit<Toast, "id">) => void;
  clearLogs: () => void;
  /** The AI assistant's latest answer, live progress and recent traces (Phase 4). */
  ai: { answer: AIAnswer | null; progress: AIProgress | null; traces: AITrace[] };
  /** The lessons and the coach's latest answer (Phase 7). */
  learn: { lessons: Lesson[]; answer: CoachAnswer | null };
  /** Who this browser is (Phase 9): null until the server has answered. */
  account: Account | null;
}

const AppStoreContext = createContext<AppStoreValue | null>(null);

export function AppStoreProvider({ children }: { children: ReactNode }) {
  const [connection, setConnection] = useState<ConnectionState>("connecting");
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [detection, setDetection] = useState<DetectionInfo | null>(null);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [aiAnswer, setAiAnswer] = useState<AIAnswer | null>(null);
  const [aiProgress, setAiProgress] = useState<AIProgress | null>(null);
  const [aiTraces, setAiTraces] = useState<AITrace[]>([]);
  const [lessons, setLessons] = useState<Lesson[]>([]);
  const [coachAnswer, setCoachAnswer] = useState<CoachAnswer | null>(null);
  const [account, setAccount] = useState<Account | null>(null);
  const socketRef = useRef<Socket | null>(null);
  const toastId = useRef(1);

  const pushToast = useCallback((toast: Omit<Toast, "id">) => {
    const id = toastId.current++;
    setToasts((current) => [...current, { ...toast, id }].slice(-4));
    window.setTimeout(() => {
      setToasts((current) => current.filter((item) => item.id !== id));
    }, 4200);
  }, []);

  const dismissToast = useCallback((id: number) => {
    setToasts((current) => current.filter((item) => item.id !== id));
  }, []);

  // ------------------------------------------------------------------
  // Socket wiring
  // ------------------------------------------------------------------
  // First: who is this browser? (A new browser gets a guest token cookie here.)
  useEffect(() => {
    let cancelled = false;
    const load = () =>
      fetchAccount()
        .then((who) => !cancelled && setAccount(who))
        .catch(() => !cancelled && window.setTimeout(load, 1500)); // the server may still be starting
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (account === null) return; // connect only once the token cookie is in place
    const socket = io({ transports: ["websocket", "polling"], reconnectionDelay: 800 });
    socketRef.current = socket;
    // Exposed so tooling (tools/screenshots.mjs) and manual debugging can drive
    // the engine from the browser console without a second connection.
    window.__cubeSocket = socket;

    const patch = (key: keyof Snapshot, value: unknown) =>
      setSnapshot((current) =>
        current ? ({ ...current, [key]: value } as Snapshot) : current,
      );

    socket.on("connect", () => setConnection("online"));
    socket.on("disconnect", () => setConnection("offline"));
    socket.on("connect_error", () => setConnection("offline"));

    socket.on("state", (data: Snapshot) => setSnapshot(data));
    socket.on("detection", (data: DetectionInfo) => setDetection(data));
    // Camera counters tick constantly; they arrive on their own slow channel so
    // a full state broadcast is not needed for every frame.
    socket.on("telemetry", (data: { camera: CameraInfo }) => patch("camera", data.camera));
    socket.on("solver", (data: SolverInfo) => patch("solver", data));
    socket.on("analytics", (data: AnalyticsInfo) => patch("analytics", data));
    socket.on("calibration", (data: CalibrationInfo) => patch("calibration", data));
    socket.on("playback", () => void 0); // full state follows every playback event

    socket.on("logs", (data: LogEntry[]) => setLogs(Array.isArray(data) ? data : []));
    socket.on("log", (entry: LogEntry) =>
      setLogs((current) => [...current, entry].slice(-MAX_LOGS)),
    );

    socket.on("scan:face", (data: { face: string; confidence: number }) =>
      pushToast({
        tone: "good",
        title: `Face ${data.face} captured`,
        message: `confidence ${(data.confidence * 100).toFixed(0)}%`,
      }),
    );
    socket.on("scan:complete", (data: { validation: { ok: boolean; errors: string[] } }) =>
      pushToast(
        data.validation.ok
          ? { tone: "good", title: "All six faces scanned", message: "Cube state is valid" }
          : {
              tone: "critical",
              title: "Scan invalid",
              message: data.validation.errors[0] ?? "Re-scan the cube",
            },
      ),
    );
    socket.on("scan:repaired", (data: { message: string }) =>
      pushToast({ tone: "brand", title: "Scan orientation fixed", message: data.message }),
    );
    socket.on("solve:complete", (data: SolutionInfo) =>
      pushToast({
        tone: "brand",
        title: `Solved in ${data.moveCount} moves`,
        message: `${data.elapsedMs.toFixed(1)} ms · ${data.backend}`,
      }),
    );
    socket.on("solve:error", (data: { error: string }) =>
      pushToast({ tone: "critical", title: "Solve failed", message: data.error }),
    );
    socket.on("solve:finished", () =>
      pushToast({ tone: "good", title: "Cube solved", message: "Nice work" }),
    );
    socket.on("dataset:saved", (data: { id: string; corrected: number }) =>
      pushToast({
        tone: "good",
        title: "Scan saved to the dataset",
        message: `54 stickers · ${data.corrected} corrected`,
      }),
    );
    socket.on("storage:error", (data: { message: string }) =>
      pushToast({ tone: "critical", title: "Not saved", message: data.message }),
    );
    socket.on("database:checked", (data: DatabaseInfo) =>
      pushToast(
        data.connected
          ? {
              tone: "good",
              title: "Connection OK",
              message: `${data.backend} ${data.serverVersion ?? ""}${data.provider ? ` · ${data.provider}` : ""}`,
            }
          : { tone: "critical", title: "Database not reachable", message: data.error ?? "" },
      ),
    );
    socket.on("ai:status", (data: AIStatus) => patch("ai", data));
    socket.on("ai:progress", (data: AIProgress) => setAiProgress(data));
    socket.on("ai:answer", (data: AIAnswer) => {
      setAiProgress(null);
      setAiAnswer(data);
    });
    socket.on("ai:traces", (data: AITrace[]) => setAiTraces(Array.isArray(data) ? data : []));
    socket.on("lessons:list", (data: Lesson[]) => setLessons(Array.isArray(data) ? data : []));
    socket.on("coach:answer", (data: CoachAnswer) => setCoachAnswer(data));
    socket.on("ai:rejected", (data: { message: string }) =>
      pushToast({ tone: "warning", title: "Assistant", message: data.message }),
    );
    socket.on("learn:rejected", (data: { message: string }) =>
      pushToast({ tone: "warning", title: "Solve & Learn", message: data.message }),
    );
    socket.on("engine:disconnected", () =>
      pushToast({ tone: "warning", title: "Vision engine disconnected" }),
    );

    return () => {
      socket.removeAllListeners();
      socket.close();
      socketRef.current = null;
    };
  }, [pushToast, account]);

  // Keep the document theme in sync with the persisted setting.
  useEffect(() => {
    const theme = snapshot?.settings.theme ?? "dark";
    document.documentElement.dataset.theme = theme;
  }, [snapshot?.settings.theme]);

  const send = useCallback(
    (command: string, payload: Record<string, unknown> = {}) => {
      const socket = socketRef.current;
      if (!socket?.connected) {
        pushToast({ tone: "critical", title: "Not connected", message: "Backend is unreachable" });
        return;
      }
      socket.emit(
        "command",
        { command, payload },
        (ack: { ok: boolean; error?: string } | undefined) => {
          if (ack && !ack.ok && ack.error) {
            pushToast({ tone: "critical", title: "Command failed", message: ack.error });
          }
        },
      );
    },
    [pushToast],
  );

  const clearLogs = useCallback(() => {
    setLogs([]);
    send("logs.clear");
  }, [send]);

  const value = useMemo<AppStoreValue>(
    () => ({
      connection,
      snapshot,
      detection,
      logs,
      toasts,
      send,
      pushToast,
      dismissToast,
      clearLogs,
      ai: { answer: aiAnswer, progress: aiProgress, traces: aiTraces },
      learn: { lessons, answer: coachAnswer },
      account,
    }),
    [
      connection, snapshot, detection, logs, toasts, send, pushToast, dismissToast, clearLogs,
      aiAnswer, aiProgress, aiTraces, lessons, coachAnswer, account,
    ],
  );

  return <AppStoreContext.Provider value={value}>{children}</AppStoreContext.Provider>;
}

export function useApp(): AppStoreValue {
  const context = useContext(AppStoreContext);
  if (!context) throw new Error("useApp must be used inside <AppStoreProvider>");
  return context;
}

/** Convenience selectors so pages do not repeat null checks everywhere. */
export function useSnapshot(): Snapshot | null {
  return useApp().snapshot;
}

export function useSettings(): SettingsInfo | null {
  return useApp().snapshot?.settings ?? null;
}
