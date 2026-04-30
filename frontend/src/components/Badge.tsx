type Props = { children: React.ReactNode; variant?: "neutral" | "ok" | "warn" | "bad" | "info" };

const styles: Record<NonNullable<Props["variant"]>, string> = {
  neutral: "bg-slate-100 text-slate-700 ring-slate-200/80",
  ok: "bg-emerald-50 text-emerald-800 ring-emerald-200/80",
  warn: "bg-amber-50 text-amber-900 ring-amber-200/80",
  bad: "bg-rose-50 text-rose-800 ring-rose-200/80",
  info: "bg-brand-50 text-brand-800 ring-brand-200/80",
};

export function Badge({ children, variant = "neutral" }: Props) {
  return (
    <span
      className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-semibold uppercase tracking-wide ring-1 ${styles[variant]}`}
    >
      {children}
    </span>
  );
}
