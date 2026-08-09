import type { ButtonHTMLAttributes } from "react";

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
};

export function Button({ variant = "primary", className = "", type = "button", ...props }: Props) {
  // Pill geometry throughout — the reference design uses fully-rounded
  // actions, and it's the single change that most carries its feel over.
  const base =
    "inline-flex items-center justify-center gap-2 rounded-full px-5 py-2.5 text-sm font-medium tracking-[-0.01em] transition-all duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-500/50 focus-visible:ring-offset-2 focus-visible:ring-offset-transparent active:scale-[0.98] disabled:pointer-events-none disabled:opacity-40";
  const variants = {
    // The inner white hairline is what keeps a solid fill from looking flat
    // against the frosted surfaces around it.
    primary:
      "bg-accent-500 text-white shadow-glow ring-1 ring-inset ring-white/20 hover:bg-accent-600",
    secondary:
      "glass text-ink-800 hover:bg-white/80 dark:text-ink-100 dark:hover:bg-white/[0.10]",
    ghost:
      "text-ink-700 hover:bg-ink-900/[0.06] dark:text-ink-300 dark:hover:bg-white/[0.08]",
    danger:
      "bg-negative-500 text-white ring-1 ring-inset ring-white/20 hover:bg-negative-600",
  };
  return <button type={type} className={`${base} ${variants[variant]} ${className}`} {...props} />;
}
