/** Transient notifications for pipeline events (face captured, solved, errors). */

import { useApp } from "@/state/AppStore";
import { IconAlert, IconCheck, IconInfo, IconSparkle } from "@/components/Icons";

const ICONS = {
  good: <IconCheck size={16} />,
  warning: <IconAlert size={16} />,
  critical: <IconAlert size={16} />,
  brand: <IconSparkle size={16} />,
} as const;

export function Toasts() {
  const { toasts, dismissToast } = useApp();
  if (toasts.length === 0) return null;

  return (
    <div className="toast-stack" role="status" aria-live="polite">
      {toasts.map((toast) => (
        <button
          key={toast.id}
          type="button"
          className="toast"
          data-tone={toast.tone}
          onClick={() => dismissToast(toast.id)}
        >
          <span className="toast-icon">{ICONS[toast.tone] ?? <IconInfo size={16} />}</span>
          <span>
            <b>{toast.title}</b>
            {toast.message && <small>{toast.message}</small>}
          </span>
        </button>
      ))}
    </div>
  );
}
