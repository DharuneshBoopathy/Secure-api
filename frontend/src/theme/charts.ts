/** Chart colours and surfaces.
 *
 * Recharts takes literal colour strings, not Tailwind classes, so these can't
 * come from the config the rest of the UI uses. Keeping them in one module —
 * mirroring the ramps in tailwind.config.js — is what stops the charts
 * drifting back to a different palette than everything around them.
 */

export const chart = {
  accent: "#20808D",
  accentSoft: "#43A9B7",
  positive: "#2E7D5B",
  warning: "#C2691E",
  negative: "#BE3B32",
  neutral: "#6B6B60",
} as const;

/** Endpoint lifecycle states, ordered healthy -> dead. */
export const statusColor: Record<string, string> = {
  ACTIVE: chart.positive,
  DECLINING: chart.accentSoft,
  IDLE: chart.warning,
  RETIRED: chart.neutral,
  ZOMBIE: chart.negative,
  DEAD: chart.negative,
};

export function colorForStatus(name: string): string {
  return statusColor[name] ?? chart.negative;
}

/** Tooltip chrome. The `var()` references resolve against the live theme, so
 * one object covers both light and dark without a theme subscription. */
export const tooltipStyle = {
  background: "rgb(var(--surface-raised))",
  border: "1px solid var(--hairline)",
  borderRadius: "0.875rem",
  color: "rgb(var(--fg-primary))",
  boxShadow: "0 8px 32px -8px rgb(26 25 24 / 0.18)",
  fontSize: "12px",
} as const;

export const axisTick = { fontSize: 10, fill: "rgb(var(--fg-tertiary))" } as const;
