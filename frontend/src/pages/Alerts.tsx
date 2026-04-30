import { CheckCircle2, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import type { AlertRow } from "@/api/client";
import { ApiError, apiFetch, isAuthenticated } from "@/api/client";
import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";

function severityVariant(s: string): "neutral" | "ok" | "warn" | "bad" | "info" {
  const x = s.toLowerCase();
  if (x === "high") return "bad";
  if (x === "medium") return "warn";
  if (x === "low") return "info";
  return "neutral";
}

export function Alerts() {
  const [rows, setRows] = useState<AlertRow[]>([]);
  const [openOnly, setOpenOnly] = useState(true);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<number | null>(null);

  const load = useCallback(async () => {
    if (!isAuthenticated()) {
      setRows([]);
      setLoading(false);
      return;
    }
    setErr(null);
    setLoading(true);
    try {
      const q = openOnly ? "?open_only=true" : "?open_only=false";
      const data = await apiFetch<AlertRow[]>(`/alerts${q}`);
      setRows(data);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to load");
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, [openOnly]);

  useEffect(() => {
    void load();
  }, [load]);

  async function ack(id: number) {
    setBusy(id);
    try {
      await apiFetch(`/alerts/${id}/ack`, { method: "POST" });
      await load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Ack failed");
    } finally {
      setBusy(null);
    }
  }

  if (!isAuthenticated()) {
    return (
      <div>
        <PageHeader title="Alerts" subtitle="Triage undocumented traffic, anomalies, and idle routes." />
        <EmptyState
          title="Configure your API key"
          description="Go to Settings and save your X-Monitor-Key to load alerts."
        />
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title="Alerts"
        subtitle="High-signal items from discovery, ML scoring, and policy checks."
        actions={
          <>
            <label className="flex cursor-pointer items-center gap-2 text-sm text-slate-600">
              <input
                type="checkbox"
                className="h-4 w-4 rounded border-slate-300 text-brand-600 focus:ring-brand-500"
                checked={openOnly}
                onChange={(e) => setOpenOnly(e.target.checked)}
              />
              Open only
            </label>
            <Button variant="secondary" onClick={() => void load()} disabled={loading}>
              <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
              Refresh
            </Button>
          </>
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
        <EmptyState title="No alerts" description="You're clear — or try turning off “Open only”." />
      ) : (
        <div className="space-y-3">
          {rows.map((a) => (
            <article
              key={a.id}
              className="rounded-2xl border border-slate-200/80 bg-white p-5 shadow-card"
            >
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant={severityVariant(a.severity)}>{a.severity}</Badge>
                    <Badge variant="neutral">{a.alert_type.replace(/_/g, " ")}</Badge>
                    {!a.acknowledged ? (
                      <span className="text-xs font-medium text-rose-600">Open</span>
                    ) : (
                      <span className="text-xs font-medium text-emerald-600">Acknowledged</span>
                    )}
                  </div>
                  <h3 className="mt-2 font-semibold text-slate-900">{a.title}</h3>
                  <p className="mt-1 text-sm text-slate-600">{a.detail}</p>
                  <div className="mt-3 flex flex-wrap gap-2 font-mono text-xs text-slate-500">
                    {a.method ? (
                      <span className="rounded-md bg-slate-100 px-2 py-0.5">{a.method}</span>
                    ) : null}
                    {a.path ? (
                      <span className="max-w-full truncate rounded-md bg-slate-100 px-2 py-0.5">{a.path}</span>
                    ) : null}
                    <span className="text-slate-400">
                      {new Date(a.created_at).toLocaleString()}
                    </span>
                  </div>
                </div>
                {a.acknowledged ? null : (
                  <Button
                    variant="secondary"
                    className="shrink-0"
                    disabled={busy === a.id}
                    onClick={() => void ack(a.id)}
                  >
                    <CheckCircle2 className="h-4 w-4" />
                    Acknowledge
                  </Button>
                )}
              </div>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
