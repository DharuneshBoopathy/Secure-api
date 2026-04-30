import type { ReactNode } from "react";

type Props = {
  title: string;
  description: string;
  icon?: ReactNode;
};

export function EmptyState({ title, description, icon }: Props) {
  return (
    <div className="rounded-2xl border border-dashed border-slate-200 bg-white/60 px-8 py-14 text-center">
      {icon ? <div className="mx-auto mb-4 flex justify-center text-slate-300">{icon}</div> : null}
      <p className="text-sm font-semibold text-slate-800">{title}</p>
      <p className="mx-auto mt-1 max-w-md text-sm text-slate-500">{description}</p>
    </div>
  );
}
