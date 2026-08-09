import type { LucideIcon } from "lucide-react";

type Props = {
  title: string;
  value: string | number;
  hint?: string;
  icon: LucideIcon;
  tone?: "default" | "amber" | "rose" | "emerald";
};

const tones = {
  default: "bg-accent-500/12 text-accent-600 ring-accent-500/20 dark:text-accent-300",
  amber: "bg-warning-500/12 text-warning-600 ring-warning-500/20 dark:text-warning-100",
  rose: "bg-negative-500/12 text-negative-600 ring-negative-500/20 dark:text-negative-100",
  emerald: "bg-positive-500/12 text-positive-600 ring-positive-500/20 dark:text-positive-100",
};

export function StatCard({ title, value, hint, icon: Icon, tone = "default" }: Props) {
  return (
    <div className="glass-card p-5 transition-shadow duration-300 hover:shadow-card-hover">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-medium text-ink-600 dark:text-ink-400">{title}</p>
          {/* Serif numerals: the figure is the point of the tile, and the
              display face gives it weight without shouting in bold. */}
          <p className="mt-2 font-display text-4xl tracking-[-0.02em] text-ink-900 tabular-nums dark:text-ink-50">
            {value}
          </p>
          {hint ? <p className="mt-1.5 text-xs text-ink-500 dark:text-ink-400">{hint}</p> : null}
        </div>
        <div className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl ring-1 ring-inset ${tones[tone]}`}>
          <Icon className="h-5 w-5" strokeWidth={1.75} />
        </div>
      </div>
    </div>
  );
}
