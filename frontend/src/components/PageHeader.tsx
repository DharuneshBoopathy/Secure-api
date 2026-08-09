import type { ReactNode } from "react";

type Props = {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
};

export function PageHeader({ title, subtitle, actions }: Props) {
  return (
    <header className="mb-8 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div>
        {/* Serif display face and negative tracking, mirroring the reference
            design's editorial headline treatment. */}
        <h1 className="font-display text-3xl font-normal tracking-[-0.02em] text-ink-900 dark:text-ink-50 sm:text-[2.5rem] sm:leading-[1.1]">
          {title}
        </h1>
        {subtitle ? (
          <p className="mt-2 max-w-2xl text-sm leading-relaxed text-ink-600 dark:text-ink-400">{subtitle}</p>
        ) : null}
      </div>
      {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  );
}
