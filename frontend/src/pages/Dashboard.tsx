import { Activity, BookMarked, RefreshCw, Route, ShieldAlert } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Cell, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Link } from "react-router-dom";
import type { LatestOpenApiResponse, Paginated, Stats, TrafficTrendPoint, ZombieRow } from "@/api/client";
import { ApiError, apiFetch, getTrafficTrend, isAuthenticated } from "@/api/client";
import { Button } from "@/components/Button";
import { OnboardingWizard } from "@/components/OnboardingWizard";
import { PageHeader } from "@/components/PageHeader";
import { StatCard } from "@/components/StatCard";
import { axisTick, chart, colorForStatus, tooltipStyle } from "@/theme/charts";

const ONBOARDING_DISMISSED_KEY = "apimonitor_onboarding_dismissed";

export function Dashboard() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [registry, setRegistry] = useState<LatestOpenApiResponse | null>(null);
  const [health, setHealth] = useState<string | null>(null);
  const [zombie, setZombie] = useState<ZombieRow[]>([]);
  const [trend, setTrend] = useState<TrafficTrendPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [onboardingDismissed, setOnboardingDismissed] = useState(
    () => localStorage.getItem(ONBOARDING_DISMISSED_KEY) === "true",
  );

  const load = useCallback(async () => {
    setErr(null);
    setLoading(true);
    try {
      const h = await apiFetch<{ status: string }>("/health", { auth: false, public: true, method: "GET" });
      setHealth(h.status === "ok" ? "Connected" : "Unknown");
      if (!isAuthenticated()) {
        setStats(null);
        setRegistry(null);
        setLoading(false);
        return;
      }
      const [s, reg, z, t] = await Promise.all([
        apiFetch<Stats>("/inventory/stats"),
        apiFetch<LatestOpenApiResponse>("/registry/openapi/latest"),
        apiFetch<Paginated<ZombieRow>>("/zombie?page=1&page_size=100"),
        getTrafficTrend(30),
      ]);
      setStats(s);
      setRegistry(reg);
      setZombie(z.items);
      setTrend(t);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        setErr("Invalid API key. Update it under Settings.");
      } else if (e instanceof Error) {
        setErr(e.message);
      } else setErr("Request failed");
      setStats(null);
      setRegistry(null);
      setZombie([]);
      setTrend([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const regTitle =
    registry && "snapshot" in registry && registry.snapshot === null
      ? "No spec uploaded yet"
      : registry && "title" in registry
        ? registry.title
        : "—";

  const statusCounts = zombie.reduce<Record<string, number>>((acc, r) => {
    acc[r.status] = (acc[r.status] ?? 0) + 1;
    return acc;
  }, {});
  const statusData = Object.entries(statusCounts).map(([name, value]) => ({ name, value }));
  const trendHasData = trend.some((p) => p.requests > 0);

  return (
    <div>
      <PageHeader
        title="Overview"
        subtitle="Runtime visibility across registered APIs, shadow traffic, and open alerts."
        actions={
          <Button variant="secondary" onClick={() => void load()} disabled={loading}>
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        }
      />

      {!isAuthenticated() ? (
        <div className="mb-6 rounded-xl border border-warning-200 bg-warning-50 px-4 py-3 text-sm text-warning-950">
          <span className="font-semibold">Authentication required.</span>{" "}
          <Link className="font-medium text-accent-700 underline underline-offset-2 dark:text-accent-300" to="/login">
            Sign in
          </Link>{" "}
          or set your <code className="rounded bg-warning-100/80 px-1 font-mono text-xs">X-Monitor-Key</code> under{" "}
          <Link className="font-medium text-accent-700 underline underline-offset-2 dark:text-accent-300" to="/settings">
            Settings
          </Link>.
        </div>
      ) : null}

      {err ? (
        <div className="mb-6 rounded-xl border border-negative-200 bg-negative-50 px-4 py-3 text-sm text-negative-900">
          {err}
        </div>
      ) : null}

      {stats &&
      !onboardingDismissed &&
      stats.known_endpoints === 0 &&
      stats.discovered_undocumented === 0 &&
      stats.events_last_hour === 0 ? (
        <OnboardingWizard
          stats={stats}
          onDataChanged={() => void load()}
          onDismiss={() => {
            localStorage.setItem(ONBOARDING_DISMISSED_KEY, "true");
            setOnboardingDismissed(true);
          }}
        />
      ) : null}

      <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          title="Events (last hour)"
          value={stats?.events_last_hour ?? "—"}
          hint="Ingested traffic volume"
          icon={Activity}
        />
        <StatCard
          title="Shadow endpoints"
          value={stats?.discovered_undocumented ?? "—"}
          hint="Not in OpenAPI registry"
          icon={Route}
          tone="amber"
        />
        <StatCard
          title="Open alerts"
          value={stats?.open_alerts ?? "—"}
          hint="Needs triage"
          icon={ShieldAlert}
          tone={stats != null && stats.open_alerts > 0 ? "rose" : "default"}
        />
        <StatCard
          title="Registered paths"
          value={stats?.known_endpoints ?? "—"}
          hint="From uploaded OpenAPI"
          icon={BookMarked}
          tone="emerald"
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="glass-card p-6">
          <h2 className="text-sm font-semibold text-ink-900 dark:text-ink-50">Service status</h2>
          <dl className="mt-4 space-y-3 text-sm">
            <div className="flex justify-between gap-4">
              <dt className="text-ink-500 dark:text-ink-400">Backend</dt>
              <dd className="font-medium text-ink-900 dark:text-ink-50">{health ?? "…"}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-ink-500 dark:text-ink-400">Latest OpenAPI</dt>
              <dd className="max-w-[60%] truncate text-right font-medium text-ink-900 dark:text-ink-50">{regTitle}</dd>
            </div>
          </dl>
          <div className="mt-6 flex flex-wrap gap-2">
            {/* Anchors rather than <Button>, so they carry the same pill
                geometry by hand. */}
            <Link
              to="/registry"
              className="inline-flex rounded-full bg-accent-500 px-5 py-2.5 text-sm font-medium text-white ring-1 ring-inset ring-white/20 shadow-glow transition hover:bg-accent-600"
            >
              Upload OpenAPI
            </Link>
            <a
              href="/docs"
              target="_blank"
              rel="noreferrer"
              className="glass inline-flex rounded-full px-5 py-2.5 text-sm font-medium text-ink-800 transition hover:bg-white/80 dark:text-ink-100 dark:hover:bg-white/[0.10]"
            >
              Swagger docs
            </a>
          </div>
        </div>

        <div className="glass-card p-6">
          <h2 className="text-sm font-semibold text-ink-900 dark:text-ink-50">Quick checks</h2>
          <ul className="mt-4 list-inside list-disc space-y-2 text-sm text-ink-600 dark:text-ink-400">
            <li>
              Review <Link className="font-medium text-accent-700 hover:underline dark:text-accent-300" to="/shadow">shadow APIs</Link> for
              undocumented routes.
            </li>
            <li>
              Acknowledge noise in <Link className="font-medium text-accent-700 hover:underline dark:text-accent-300" to="/alerts">Alerts</Link>
              .
            </li>
            <li>
              Compare <Link className="font-medium text-accent-700 hover:underline dark:text-accent-300" to="/idle">idle routes</Link> against
              deprecations.
            </li>
          </ul>
        </div>

        <div className="glass-card p-6">
          <h2 className="mb-1 text-sm font-semibold text-ink-900 dark:text-ink-100">Traffic trend (last 30 days)</h2>
          <p className="mb-3 text-xs text-ink-500 dark:text-ink-400">
            Requests and errors per day, from live traffic and daily rollups.
          </p>
          <div className="h-44">
            {trendHasData ? (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={trend}>
                  <XAxis dataKey="day" tick={axisTick} tickFormatter={(d: string) => d.slice(5)} minTickGap={24} />
                  <YAxis tick={axisTick} width={32} allowDecimals={false} />
                  <Tooltip contentStyle={tooltipStyle} />
                  <Line type="monotone" dataKey="requests" name="Requests" stroke={chart.accent} strokeWidth={2} dot={false} />
                  <Line type="monotone" dataKey="errors" name="Errors" stroke={chart.negative} strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <div className="flex h-full items-center justify-center text-xs text-ink-400 dark:text-ink-500">
                No traffic ingested yet.
              </div>
            )}
          </div>
        </div>

        <div className="glass-card p-6">
          <h2 className="mb-3 text-sm font-semibold text-ink-900 dark:text-ink-50">Endpoint health mix</h2>
          <div className="h-44">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={statusData} dataKey="value" nameKey="name" outerRadius={72}>
                  {statusData.map((entry) => (
                    <Cell key={entry.name} fill={colorForStatus(entry.name)} stroke="none" />
                  ))}
                </Pie>
                <Tooltip contentStyle={tooltipStyle} />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>
    </div>
  );
}
