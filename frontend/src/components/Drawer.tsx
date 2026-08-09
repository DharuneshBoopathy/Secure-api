import { X } from "lucide-react";
import { ReactNode, useEffect, useRef } from "react";

type Props = {
  open: boolean;
  title: string;
  subtitle?: string;
  onClose: () => void;
  children: ReactNode;
};

/** A generic slide-in detail panel — unlike ConfirmDialog (which mandates a
 * reason textarea, purpose-built for destructive actions), this has no
 * required input; it's for *viewing* detail (a raw event, an alert's
 * explanation) with optional actions passed in as children. */
export function Drawer({ open, title, subtitle, onClose, children }: Props) {
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    closeButtonRef.current?.focus();
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-ink-950/40 backdrop-blur-sm" onClick={onClose} aria-hidden />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="glass-strong relative flex h-full w-full max-w-md flex-col overflow-y-auto rounded-l-3xl border-y-0 border-r-0"
      >
        <div className="hairline flex items-start justify-between border-b p-5">
          <div>
            <h2 className="font-display text-lg text-ink-900 dark:text-ink-50">{title}</h2>
            {subtitle ? <p className="mt-0.5 text-xs text-ink-500 dark:text-ink-400">{subtitle}</p> : null}
          </div>
          <button
            ref={closeButtonRef}
            type="button"
            onClick={onClose}
            aria-label="Close panel"
            className="rounded-full p-1.5 text-ink-500 transition hover:bg-ink-900/[0.06] hover:text-ink-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-500/50 dark:hover:bg-white/[0.08] dark:hover:text-ink-100 dark:text-ink-400"
          >
            <X className="h-4 w-4" aria-hidden />
          </button>
        </div>
        <div className="flex-1 p-5">{children}</div>
      </div>
    </div>
  );
}
