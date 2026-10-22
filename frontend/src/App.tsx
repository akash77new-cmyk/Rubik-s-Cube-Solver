import { useCallback, useEffect, useState, type ReactElement } from "react";
import { BrandCell, Header, Sidebar, type PageId } from "@/components/layout";
import { useApp } from "@/state/AppStore";
import { AboutDialog } from "@/components/AboutDialog";
import { Toasts } from "@/components/Toasts";
import DashboardPage from "@/pages/DashboardPage";
import CameraPage from "@/pages/CameraPage";
import ScannerPage from "@/pages/ScannerPage";
import CubeViewerPage from "@/pages/CubeViewerPage";
import SolutionPage from "@/pages/SolutionPage";
import AnalyticsPage from "@/pages/AnalyticsPage";
import CalibrationPage from "@/pages/CalibrationPage";
import LogsPage from "@/pages/LogsPage";
import SettingsPage from "@/pages/SettingsPage";
import AssistantPage from "@/pages/AssistantPage";
import LessonsPage from "@/pages/LessonsPage";

const PAGES: Record<PageId, (props: { navigate: (page: PageId) => void }) => ReactElement> = {
  dashboard: DashboardPage,
  camera: CameraPage,
  scanner: ScannerPage,
  viewer: CubeViewerPage,
  solution: SolutionPage,
  analytics: AnalyticsPage,
  calibration: CalibrationPage,
  logs: LogsPage,
  settings: SettingsPage,
  assistant: AssistantPage,
  lessons: LessonsPage,
};

const VALID_PAGES = new Set(Object.keys(PAGES) as PageId[]);

function pageFromHash(): PageId {
  const hash = window.location.hash.replace(/^#\/?/, "") as PageId;
  return VALID_PAGES.has(hash) ? hash : "dashboard";
}

export default function App() {
  const [page, setPage] = useState<PageId>(pageFromHash);
  const [collapsed, setCollapsed] = useState(false);
  const [aboutOpen, setAboutOpen] = useState(false);
  const { snapshot, send } = useApp();

  /* Hash routing keeps deep links working without pulling in a router. */
  useEffect(() => {
    const onHashChange = () => setPage(pageFromHash());
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  const navigate = useCallback((next: PageId) => {
    window.location.hash = `/${next}`;
    setPage(next);
  }, []);

  /* Leaving the calibration page stops the mask preview so the normal HUD
     comes back on the camera feed. */
  useEffect(() => {
    if (page !== "calibration" && snapshot?.calibration.active) {
      send("calibration.stop");
    }
  }, [page, snapshot?.calibration.active, send]);

  /* Keyboard shortcuts - the kind of thing that makes a demo feel fast. */
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && /^(INPUT|SELECT|TEXTAREA)$/.test(target.tagName)) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;

      const digit = Number.parseInt(event.key, 10);
      const order: PageId[] = [
        "dashboard", "camera", "scanner", "viewer", "solution",
        "analytics", "calibration", "logs", "settings",
      ];
      if (digit >= 1 && digit <= 9) {
        navigate(order[digit - 1]);
        return;
      }
      if (digit === 0) {
        navigate("assistant");
        return;
      }
      if (event.key === " " && snapshot?.solution) {
        event.preventDefault();
        send(snapshot.playback.playing ? "playback.pause" : "playback.play");
      }
      if (event.key === "ArrowRight" && snapshot?.solution) send("playback.next");
      if (event.key === "ArrowLeft" && snapshot?.solution) send("playback.prev");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [navigate, send, snapshot?.solution, snapshot?.playback.playing]);

  const Page = PAGES[page];

  return (
    <div className="app" data-collapsed={collapsed}>
      <div className="ambient" aria-hidden="true" />
      <BrandCell onToggleSidebar={() => setCollapsed((value) => !value)} />
      <Header page={page} onAbout={() => setAboutOpen(true)} onSettings={() => navigate("settings")} />
      <Sidebar page={page} onNavigate={navigate} />
      <main className="main">
        <div key={page} className="page fade-in">
          <Page navigate={navigate} />
        </div>
      </main>
      <Toasts />
      {aboutOpen && <AboutDialog onClose={() => setAboutOpen(false)} />}
    </div>
  );
}