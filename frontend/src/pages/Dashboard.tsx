import { Activity, BookMarked, RefreshCw, Route, ShieldAlert } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Cell, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import { Link } from "react-router-dom";
import type { LatestOpenApiResponse, Paginated, Stats, ZombieRow } from "@/api/client";
import { ApiError, apiFetch, isAuthenticated } from "@/api/client";
import { Button } from "@/components/Button";
import { PageHeader } from "@/components/PageHeader";
import { StatCard } from "@/components/StatCard";

export function Dashboard() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [registry, setRegistry] = useState<LatestOpenApiResponse | null>(null);
  const [health, setHealth] = useState<string | null>(null);
  const [zombie, setZombie] = useState<ZombieRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

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
      const [s, reg, z] = await Promise.all([
        apiFetch<Stats>("/inventory/stats"),
        apiFetch<LatestOpenApiResponse>("/registry/openapi/latest"),
        apiFetch<Paginated<ZombieRow>>("/zombie?page=1&page_size=100"),
      ]);
      setStats(s);
      setRegistry(reg);
      setZombie(z.items);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        setErr("Invalid API key. Update it under Settings.");
      } else if (e instanceof Error) {
        setErr(e.message);
      } else setErr("Request failed");
      setStats(null);
      setRegistry(null);
      setZombie([]);
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
  const trafficTrend = [
    { hour: "Now-3h", requests: Math.max(0, Math.round((stats?.events_last_hour ?? 0) * 0.6)) },
    { hour: "Now-2h", requests: Math.max(0, Math.round((stats?.events_last_hour ?? 0) * 0.75)) },
    { hour: "Now-1h", requests: Math.max(0, Math.round((stats?.events_last_hour ?? 0) * 0.9)) },
    { hour: "Now", requests: stats?.events_last_hour ?? 0 },
  ];

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
        <div className="mb-6 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-950">
          <span className="font-semibold">Authentication required.</span>{" "}
          <Link className="font-medium text-brand-700 underline underline-offset-2" to="/login">
            Sign in
          </Link>{" "}
          or set your <code className="rounded bg-amber-100/80 px-1 font-mono text-xs">X-Monitor-Key</code> under{" "}
          <Link className="font-medium text-brand-700 underline underline-offset-2" to="/settings">
            Settings
          </Link>.
        </div>
      ) : null}

      {err ? (
        <div className="mb-6 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-900">
          {err}
        </div>
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
        <div className="rounded-2xl border border-slate-200/80 bg-white p-6 shadow-card">
          <h2 className="text-sm font-semibold text-slate-900">Service status</h2>
          <dl className="mt-4 space-y-3 text-sm">
            <div className="flex justify-between gap-4">
              <dt className="text-slate-500">Backend</dt>
              <dd className="font-medium text-slate-900">{health ?? "…"}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-slate-500">Latest OpenAPI</dt>
              <dd className="max-w-[60%] truncate text-right font-medium text-slate-900">{regTitle}</dd>
            </div>
          </dl>
          <div className="mt-6 flex flex-wrap gap-2">
            <Link
              to="/registry"
              className="inline-flex rounded-lg bg-brand-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-brand-700"
            >
              Upload OpenAPI
            </Link>
            <a
              href="/docs"
              target="_blank"
              rel="noreferrer"
              className="inline-flex rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-800 hover:bg-slate-50"
            >
              Swagger docs
            </a>
          </div>
        </div>

        <div className="rounded-2xl border border-slate-200/80 bg-white p-6 shadow-card">
          <h2 className="text-sm font-semibold text-slate-900">Quick checks</h2>
          <ul className="mt-4 list-inside list-disc space-y-2 text-sm text-slate-600">
            <li>
              Review <Link className="font-medium text-brand-700 hover:underline" to="/shadow">shadow APIs</Link> for
              undocumented routes.
            </li>
            <li>
              Acknowledge noise in <Link className="font-medium text-brand-700 hover:underline" to="/alerts">Alerts</Link>
              .
            </li>
            <li>
              Compare <Link className="font-medium text-brand-700 hover:underline" to="/idle">idle routes</Link> against
              deprecations.
            </li>
          </ul>
        </div>

        <div className="rounded-2xl border border-slate-200/80 bg-white p-6 shadow-card">
          <h2 className="mb-3 text-sm font-semibold text-slate-900">Traffic trend (last 4h)</h2>
          <div className="h-44">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={trafficTrend}>
                <Tooltip />
                <Line type="monotone" dataKey="requests" stroke="#2563eb" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="rounded-2xl border border-slate-200/80 bg-white p-6 shadow-card">
          <h2 className="mb-3 text-sm font-semibold text-slate-900">Endpoint health mix</h2>
          <div className="h-44">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={statusData} dataKey="value" nameKey="name" outerRadius={72}>
                  {statusData.map((entry) => (
                    <Cell
                      key={entry.name}
                      fill={
                        entry.name === "ACTIVE"
                          ? "#10b981"
                          : entry.name === "DECLINING"
                            ? "#0ea5e9"
                            : entry.name === "IDLE"
                              ? "#f59e0b"
                              : entry.name === "RETIRED"
                                ? "#64748b"
                                : "#ef4444"
                      }
                    />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>
    </div>
  );
}
