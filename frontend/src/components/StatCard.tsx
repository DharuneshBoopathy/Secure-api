import type { LucideIcon } from "lucide-react";

type Props = {
  title: string;
  value: string | number;
  hint?: string;
  icon: LucideIcon;
  tone?: "default" | "amber" | "rose" | "emerald";
};

const tones = {
  default: "bg-white text-brand-600 ring-slate-200/80",
  amber: "bg-amber-50 text-amber-700 ring-amber-200/80",
  rose: "bg-rose-50 text-rose-700 ring-rose-200/80",
  emerald: "bg-emerald-50 text-emerald-700 ring-emerald-200/80",
};

export function StatCard({ title, value, hint, icon: Icon, tone = "default" }: Props) {
  return (
    <div className="rounded-2xl border border-slate-200/80 bg-white p-5 shadow-card transition-shadow hover:shadow-card-hover">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-medium text-slate-500">{title}</p>
          <p className="mt-2 text-3xl font-semibold tracking-tight text-slate-900 tabular-nums">
            {value}
          </p>
          {hint ? <p className="mt-1 text-xs text-slate-400">{hint}</p> : null}
        </div>
        <div
          className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl ring-1 ${tones[tone]}`}
        >
          <Icon className="h-5 w-5" strokeWidth={2} />
        </div>
      </div>
    </div>
  );
}
