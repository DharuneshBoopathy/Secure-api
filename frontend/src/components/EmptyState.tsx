import type { ReactNode } from "react";

type Props = {
  title: string;
  description: string;
  icon?: ReactNode;
};

export function EmptyState({ title, description, icon }: Props) {
  return (
    <div className="glass-card border-dashed px-8 py-16 text-center">
      {icon ? (
        <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-accent-500/10 text-accent-500 dark:text-accent-300">
          {icon}
        </div>
      ) : null}
      <p className="font-display text-lg text-ink-900 dark:text-ink-50">{title}</p>
      <p className="mx-auto mt-1.5 max-w-md text-sm text-ink-600 dark:text-ink-400">{description}</p>
    </div>
  );
}
