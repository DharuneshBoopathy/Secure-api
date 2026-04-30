import { RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import type { Paginated, ShadowRow } from "@/api/client";
import { apiFetch, isAuthenticated } from "@/api/client";
import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";

export function Shadow() {
  const [rows, setRows] = useState<ShadowRow[]>([]);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [total, setTotal] = useState(0);
  const [riskLevel, setRiskLevel] = useState<string>("");
  const [ackId, setAckId] = useState<number | null>(null);
  const [ackReason, setAckReason] = useState("Reviewed by security team");
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
      const query = new URLSearchParams({
        page: String(page),
        page_size: String(pageSize),
      });
      if (riskLevel) query.set("risk_level", riskLevel);
      const data = await apiFetch<Paginated<ShadowRow>>(`/shadow?${query.toString()}`);
      setRows(data.items);
      setTotal(data.total);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed");
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, riskLevel]);

  useEffect(() => {
    void load();
  }, [load]);

  async function acknowledge(id: number) {
    setAckId(id);
  }

  async function confirmAcknowledge() {
    if (ackId == null) return;
    await apiFetch(`/shadow/${ackId}/acknowledge`, {
      method: "POST",
      body: JSON.stringify({ reason: ackReason }),
    });
    setAckId(null);
    await load();
  }

  async function promote(id: number) {
    await apiFetch(`/shadow/${id}/add-to-registry`, { method: "POST" });
    await load();
  }

  if (!isAuthenticated()) {
    return (
      <div>
        <PageHeader title="Shadow APIs" subtitle="Traffic to paths not present in your registered OpenAPI." />
        <EmptyState title="API key required" description="Add your monitor key under Settings." />
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title="Shadow APIs"
        subtitle="Undocumented surface area — candidates for deprecation, auth hardening, or spec updates."
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={riskLevel}
              onChange={(e) => {
                setPage(1);
                setRiskLevel(e.target.value);
              }}
              className="rounded-lg border border-slate-200 px-2 py-1 text-sm"
            >
              <option value="">All risks</option>
              <option value="CRITICAL">Critical</option>
              <option value="HIGH">High</option>
              <option value="MEDIUM">Medium</option>
              <option value="LOW">Low</option>
            </select>
            <select
              value={pageSize}
              onChange={(e) => {
                setPage(1);
                setPageSize(Number(e.target.value));
              }}
              className="rounded-lg border border-slate-200 px-2 py-1 text-sm"
            >
              <option value={25}>25</option>
              <option value={50}>50</option>
              <option value={100}>100</option>
            </select>
            <Button variant="secondary" onClick={() => void load()} disabled={loading}>
              <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
              Refresh
            </Button>
          </div>
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
          title="No shadow endpoints detected"
          description="Either traffic is fully documented, or you haven't ingested events yet."
        />
      ) : (
        <div className="overflow-hidden rounded-2xl border border-slate-200/80 bg-white shadow-card">
          <table className="min-w-full divide-y divide-slate-100 text-sm">
            <thead className="bg-slate-50/80 text-left text-xs font-semibold uppercase tracking-wider text-slate-500">
              <tr>
                <th className="px-4 py-3">Method</th>
                <th className="px-4 py-3">Path (normalized)</th>
                <th className="px-4 py-3">Hits</th>
                <th className="px-4 py-3">Risk</th>
                <th className="px-4 py-3">Last seen</th>
                <th className="px-4 py-3">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rows.map((r) => (
                <tr key={r.id} className="hover:bg-slate-50/60">
                  <td className="px-4 py-3">
                    <Badge variant="info">{r.method}</Badge>
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-slate-800">{r.path_normalized}</td>
                  <td className="px-4 py-3 tabular-nums text-slate-700">{r.hit_count}</td>
                  <td className="px-4 py-3">
                    <Badge variant={r.risk_level === "CRITICAL" || r.risk_level === "HIGH" ? "bad" : r.risk_level === "MEDIUM" ? "warn" : "neutral"}>
                      {r.risk_level} ({r.risk_score})
                    </Badge>
                  </td>
                  <td className="px-4 py-3 text-slate-500">{new Date(r.last_seen).toLocaleString()}</td>
                  <td className="px-4 py-3">
                    <div className="flex gap-2">
                      <Button variant="secondary" className="px-2 py-1 text-xs" onClick={() => void acknowledge(r.id)}>
                        Ack
                      </Button>
                      <Button variant="ghost" className="px-2 py-1 text-xs" onClick={() => void promote(r.id)}>
                        Promote
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="mt-3 flex items-center justify-between text-sm text-slate-600">
        <span>Total: {total}</span>
        <div className="flex items-center gap-2">
          <Button variant="secondary" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
            Prev
          </Button>
          <span>Page {page}</span>
          <Button variant="secondary" disabled={page * pageSize >= total} onClick={() => setPage((p) => p + 1)}>
            Next
          </Button>
        </div>
      </div>
      <ConfirmDialog
        open={ackId != null}
        title="Acknowledge shadow API"
        description="Provide a reason for reviewing this endpoint."
        reason={ackReason}
        setReason={setAckReason}
        onCancel={() => setAckId(null)}
        onConfirm={() => void confirmAcknowledge()}
        confirmLabel="Acknowledge"
      />
    </div>
  );
}
