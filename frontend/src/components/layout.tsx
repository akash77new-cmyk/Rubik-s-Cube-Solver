/** Application chrome: brand cell, header status rail, sidebar navigation. */

import type { ReactNode } from "react";
import type { ThemeName } from "@/lib/types";
import { useApp } from "@/state/AppStore";
import { Button, StatusChip } from "@/components/ui";
import {
  IconAnalytics,
  IconBook,
  IconCamera,
  IconCube,
  IconDashboard,
  IconDroplet,
  IconGraduation,
  IconInfo,
  IconMenu,
  IconMoon,
  IconRoute,
  IconScan,
  IconSettings,
  IconSparkle,
  IconSun,
  IconTerminal,
  IconUser,
} from "@/components/Icons";

export type PageId =
  | "dashboard"
  | "camera"
  | "scanner"
  | "viewer"
  | "solution"
  | "analytics"
  | "calibration"
  | "logs"
  | "settings"
  | "assistant"
  | "lessons"
  | "learn";

export const NAV: {
  group: string;
  items: { id: PageId; label: string; icon: ReactNode; hint: string }[];
}[] = [
  {
    group: "Overview",
    items: [
      { id: "dashboard", label: "Dashboard", icon: <IconDashboard />, hint: "Status & quick actions" },
      { id: "analytics", label: "Analytics", icon: <IconAnalytics />, hint: "Solve performance" },
    ],
  },
  {
    group: "Vision pipeline",
    items: [
      { id: "camera", label: "Live Camera", icon: <IconCamera />, hint: "Detection feed" },
      { id: "scanner", label: "Scanner", icon: <IconScan />, hint: "Capture six faces" },
      { id: "calibration", label: "HSV Calibration", icon: <IconDroplet />, hint: "Colour thresholds" },
    ],
  },
  {
    group: "Solve",
    items: [
      { id: "viewer", label: "Cube Viewer", icon: <IconCube />, hint: "Live cube state" },
      { id: "solution", label: "Solution", icon: <IconRoute />, hint: "Move-by-move player" },
      { id: "learn", label: "Solve & Learn", icon: <IconGraduation />, hint: "Beginner method, with a tutor" },
    ],
  },
  {
    group: "AI",
    items: [
      { id: "assistant", label: "AI Assistant", icon: <IconSparkle />, hint: "Ask about your cube" },
      { id: "lessons", label: "Lessons & Coach", icon: <IconBook />, hint: "Learn, with cited answers" },
    ],
  },
  {
    group: "System",
    items: [
      { id: "logs", label: "Logs", icon: <IconTerminal />, hint: "Pipeline events" },
      { id: "settings", label: "Settings", icon: <IconSettings />, hint: "Camera & appearance" },
    ],
  },
];

export const PAGE_META: Record<PageId, { title: string; subtitle: string }> = {
  dashboard: { title: "Dashboard", subtitle: "Pipeline status and quick actions" },
  camera: { title: "Live Camera", subtitle: "HSV segmentation running on the live feed" },
  scanner: { title: "Scanning Pipeline", subtitle: "Capture all six faces of the cube" },
  viewer: { title: "Cube State Visualizer", subtitle: "Interactive 3D and unfolded net views" },
  solution: { title: "Solution Visualizer", subtitle: "Kociemba two-phase solution, move by move" },
  analytics: { title: "Analytics", subtitle: "Solve times, move counts and detection quality" },
  calibration: { title: "HSV Calibration", subtitle: "Tune colour detection for your camera and lighting" },
  logs: { title: "Logs", subtitle: "Live event stream from the vision engine" },
  settings: { title: "Settings", subtitle: "Camera, overlays, playback and appearance" },
  assistant: { title: "AI Assistant", subtitle: "Ask about your cube, your solution and your solves" },
  lessons: { title: "Lessons & Coach", subtitle: "Short lessons, and a coach that answers from them" },
  learn: { title: "Solve & Learn", subtitle: "Solve your own cube with the beginner method and an AI tutor" },
};

/* ------------------------------------------------------------------ */

export function BrandCell({ onToggleSidebar }: { onToggleSidebar: () => void }) {
  return (
    <div className="brand-cell">
      <img className="brand-logo" src="/assets-lib/brand/logo.svg" alt="" width={34} height={34} />
      <div className="brand-text">
        <div className="brand-name">CubeSolver</div>
        <div className="brand-sub">vision · kociemba</div>
      </div>
      <Button
        variant="ghost"
        size="sm"
        iconOnly
        icon={<IconMenu size={16} />}
        onClick={onToggleSidebar}
        aria-label="Toggle navigation"
        style={{ marginLeft: "auto" }}
      />
    </div>
  );
}

export function Header({
  page,
  onAbout,
  onSettings,
  onAccount,
}: {
  page: PageId;
  onAbout: () => void;
  onSettings: () => void;
  onAccount: () => void;
}) {
  /** Header button cycles through the three themes in one control. */
  const nextTheme = (current: ThemeName): ThemeName =>
    current === "dark" ? "midnight" : current === "midnight" ? "light" : "dark";

  const { connection, snapshot, detection, account } = useApp();
  const meta = PAGE_META[page];
  const camera = snapshot?.camera;
  const solver = snapshot?.solver;
  const theme = snapshot?.settings.theme ?? "dark";
  const { send } = useApp();

  const connectionTone =
    connection === "online" ? "good" : connection === "connecting" ? "warning" : "critical";

  const detectionState = (() => {
    if (!camera?.running) return { label: "Detection", value: "idle", tone: "default" as const };
    if (!detection) return { label: "Detection", value: "warming", tone: "warning" as const };
    if (detection.stable) return { label: "Detection", value: "locked", tone: "good" as const };
    return { label: "Detection", value: "reading", tone: "brand" as const };
  })();

  return (
    <header className="header">
      <div>
        <div className="header-title">{meta.title}</div>
        <div className="header-sub">{meta.subtitle}</div>
      </div>
      <div className="header-spacer" />
      <div className="header-chips">
        <StatusChip
          label="Server"
          value={connection}
          tone={connectionTone}
          title="Socket.IO connection to the web server"
        />
        <StatusChip
          label="Camera"
          value={camera?.running ? `#${camera.index}` : "off"}
          tone={camera?.running ? "good" : "default"}
          optional
          title={camera?.error ?? "Camera device state"}
        />
        <StatusChip
          label="FPS"
          value={(camera?.fps ?? 0).toFixed(0)}
          tone={(camera?.fps ?? 0) > 12 ? "good" : camera?.running ? "warning" : "default"}
          optional
        />
        <StatusChip
          label={detectionState.label}
          value={detectionState.value}
          tone={detectionState.tone}
          optional
        />
        <StatusChip
          label="Solver"
          value={solver?.ready ? "ready" : solver?.state ?? "…"}
          tone={solver?.ready ? "good" : solver?.state === "error" ? "critical" : "warning"}
          optional
          title={solver?.message}
        />
        <Button
          variant="ghost"
          size="sm"
          icon={<IconUser size={16} />}
          aria-label="Account"
          title={account?.kind === "user" ? `Logged in as ${account.email}` : "Log in or sign up"}
          onClick={onAccount}
        >
          <span className="account-chip">{account?.kind === "user" ? account.email : "Log in"}</span>
        </Button>
        <Button
          variant="ghost"
          size="sm"
          iconOnly
          icon={theme === "light" ? <IconMoon size={16} /> : <IconSun size={16} />}
          aria-label="Change colour theme"
          title={`Theme: ${theme} — click to cycle (dark → midnight → light)`}
          onClick={() => send("settings.update", { theme: nextTheme(theme) })}
        />
        <Button
          variant="ghost"
          size="sm"
          iconOnly
          icon={<IconSettings size={16} />}
          aria-label="Settings"
          title="Settings"
          onClick={onSettings}
        />
        <Button
          variant="ghost"
          size="sm"
          iconOnly
          icon={<IconInfo size={16} />}
          aria-label="About"
          title="About this project"
          onClick={onAbout}
        />
      </div>
    </header>
  );
}

export function Sidebar({
  page,
  onNavigate,
}: {
  page: PageId;
  onNavigate: (page: PageId) => void;
}) {
  const { snapshot } = useApp();
  const scanned = snapshot?.scan.count ?? 0;
  const moves = snapshot?.solution?.moveCount ?? 0;

  const badgeFor = (id: PageId): string | null => {
    if (id === "scanner" && scanned > 0) return `${scanned}/6`;
    if (id === "solution" && moves > 0) return String(moves);
    return null;
  };

  return (
    <nav className="sidebar" aria-label="Primary">
      {NAV.map((group) => (
        <div key={group.group}>
          <div className="nav-group-label">{group.group}</div>
          {group.items.map((item) => {
            const badge = badgeFor(item.id);
            return (
              <button
                key={item.id}
                type="button"
                className="nav-item"
                aria-current={page === item.id ? "page" : undefined}
                title={item.hint}
                onClick={() => onNavigate(item.id)}
                style={{ width: "100%" }}
              >
                {item.icon}
                <span className="nav-label">{item.label}</span>
                {badge && <span className="nav-badge">{badge}</span>}
              </button>
            );
          })}
        </div>
      ))}
      <div className="sidebar-footer">
        <div className="nav-group-label">v2.0.0</div>
      </div>
    </nav>
  );
}

/* ------------------------------------------------------------------ */

export function PageHead({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="page-head">
      <div>
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {actions && <div className="page-head-actions">{actions}</div>}
    </div>
  );
}
