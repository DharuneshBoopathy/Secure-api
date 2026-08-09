import { AlertTriangle, Info, X } from "lucide-react";
import { Link } from "react-router-dom";
import { useAppStore } from "@/store/appStore";

const AUTO_DISMISS_MS = 8000;

// Severity now rides on a single left accent bar rather than the whole
// border, so a stack of toasts over the frosted UI stays quiet until you
// look at it.
const styles: Record<"info" | "warn" | "bad", string> = {
  info: "before:bg-accent-500",
  warn: "before:bg-warning-500",
  bad: "before:bg-negative-500",
};

const iconColor: Record<"info" | "warn" | "bad", string> = {
  info: "text-accent-500 dark:text-accent-300",
  warn: "text-warning-500 dark:text-warning-100",
  bad: "text-negative-500 dark:text-negative-100",
};

/** Renders the toast stack (see useAlertToasts for what feeds it). Mounted
 * once in Layout.tsx so toasts survive page navigation instead of being
 * torn down with whichever page pushed them. */
export function ToastHost() {
  const toasts = useAppStore((s) => s.toasts);
  const dismissToast = useAppStore((s) => s.dismissToast);

  if (toasts.length === 0) return null;

  return (
    <div
      role="region"
      aria-label="Notifications"
      className="fixed bottom-4 right-4 z-40 flex w-full max-w-sm flex-col gap-2 sm:bottom-6 sm:right-6"
    >
      {toasts.map((toast) => {
        const Icon = toast.variant === "info" ? Info : AlertTriangle;
        const body = (
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold text-ink-900 dark:text-ink-50">{toast.title}</p>
            {toast.description ? (
              <p className="mt-0.5 truncate text-xs text-ink-600 dark:text-ink-400">{toast.description}</p>
            ) : null}
          </div>
        );
        return (
          <div
            key={toast.id}
            role="status"
            className={`glass-strong relative flex animate-fade-rise items-start gap-3 overflow-hidden rounded-2xl p-3.5 before:absolute before:inset-y-0 before:left-0 before:w-1 before:content-[''] ${styles[toast.variant]}`}
          >
            <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${iconColor[toast.variant]}`} aria-hidden />
            {toast.href ? (
              <Link to={toast.href} className="flex-1 min-w-0" onClick={() => dismissToast(toast.id)}>
                {body}
              </Link>
            ) : (
              body
            )}
            <button
              type="button"
              onClick={() => dismissToast(toast.id)}
              aria-label="Dismiss notification"
              className="shrink-0 rounded-full p-1 text-ink-500 transition hover:bg-ink-900/[0.06] hover:text-ink-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-500/50 dark:hover:bg-white/[0.08] dark:hover:text-ink-100 dark:text-ink-400"
            >
              <X className="h-3.5 w-3.5" aria-hidden />
            </button>
          </div>
        );
      })}
    </div>
  );
}

export { AUTO_DISMISS_MS };
