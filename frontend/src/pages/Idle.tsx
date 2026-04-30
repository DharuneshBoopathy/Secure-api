import { RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import type { IdleRow } from "@/api/client";
import { apiFetch, isAuthenticated } from "@/api/client";
import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";

export function Idle() {
  const [rows, setRows] = useState<IdleRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!isAuthenticated()) {
      setRows([]);
      setLoading(false);
      return;
    }
    setErr(null);
    setLoading(true);
    try {
      setRows(await apiFetch<IdleRow[]>("/inventory/idle"));
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed");
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (!isAuthenticated()) {
    return (
      <div>
        <PageHeader title="Idle routes" subtitle="Registered OpenAPI paths with no recent traffic." />
        <EmptyState title="API key required" description="Add your monitor key under Settings." />
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title="Idle routes"
        subtitle="Useful for spotting retired APIs, misconfigured gateways, or stale documentation."
        actions={
          <Button variant="secondary" onClick={() => void load()} disabled={loading}>
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        }
      />
      {err ? (
        <div className="mb-4 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-900">
          {err}
        </div>
      ) : null}
      {loading ? (
        <p className="text-sm text-slate-500">Loading…</p>
      ) : rows.length === 0 ? (
        <EmptyState
          title="No idle registered routes"
          description="All known paths have seen traffic inside the idle window, or nothing is registered yet."
        />
      ) : (
        <div className="overflow-hidden rounded-2xl border border-slate-200/80 bg-white shadow-card">
          <table className="min-w-full divide-y divide-slate-100 text-sm">
            <thead className="bg-slate-50/80 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">
              <tr>
                <th className="px-4 py-3">Method</th>
                <th className="px-4 py-3">Path template</th>
                <th className="px-4 py-3">Last traffic</th>
                <th className="px-4 py-3">Hours idle</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rows.map((r) => (
                <tr key={`${r.method}-${r.path_template}`} className="hover:bg-slate-50/60">
                  <td className="px-4 py-3">
                    <Badge variant="neutral">{r.method}</Badge>
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-slate-800">{r.path_template}</td>
                  <td className="px-4 py-3 text-slate-600">
                    {r.last_traffic ? new Date(r.last_traffic).toLocaleString() : (
                      <span className="text-amber-700">Never</span>
                    )}
                  </td>
                  <td className="px-4 py-3 tabular-nums text-slate-600">
                    {r.hours_since_traffic != null ? r.hours_since_traffic.toFixed(1) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
