type Props = { children: React.ReactNode; variant?: "neutral" | "ok" | "warn" | "bad" | "info" };

// Tinted fill + same-hue ring, rather than the previous saturated blocks —
// against a warm cream ground a heavy chip reads as an error even when it's
// only a status.
const styles: Record<NonNullable<Props["variant"]>, string> = {
  neutral: "bg-ink-900/[0.05] text-ink-700 ring-ink-900/10 dark:bg-white/[0.08] dark:text-ink-300 dark:ring-white/10",
  ok: "bg-positive-100 text-positive-600 ring-positive-500/20 dark:bg-positive-500/15 dark:text-positive-100 dark:ring-positive-500/25",
  warn: "bg-warning-100 text-warning-600 ring-warning-500/20 dark:bg-warning-500/15 dark:text-warning-100 dark:ring-warning-500/25",
  bad: "bg-negative-100 text-negative-600 ring-negative-500/20 dark:bg-negative-500/15 dark:text-negative-100 dark:ring-negative-500/25",
  info: "bg-accent-100 text-accent-600 ring-accent-500/20 dark:bg-accent-500/15 dark:text-accent-200 dark:ring-accent-500/25",
};

export function Badge({ children, variant = "neutral" }: Props) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide ring-1 ring-inset ${styles[variant]}`}
    >
      {children}
    </span>
  );
}
