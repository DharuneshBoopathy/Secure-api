import { useQuery } from "@tanstack/react-query";
import { Paginated, ZombieRow, apiFetch } from "@/api/client";
import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { useState } from "react";

const statusVariant: Record<ZombieRow["status"], "neutral" | "ok" | "warn" | "bad" | "info"> = {
  ACTIVE: "ok",
  DECLINING: "info",
  IDLE: "warn",
  ZOMBIE: "bad",
  DEAD: "bad",
  RETIRED: "neutral",
};

export function Zombie() {
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState("");
  const [retireId, setRetireId] = useState<number | null>(null);
  const [retireReason, setRetireReason] = useState("Intentionally retired endpoint");
  const { data, isLoading, error } = useQuery({
    queryKey: ["zombie", page, statusFilter],
    queryFn: () =>
      apiFetch<Paginated<ZombieRow>>(
        `/zombie?page=${page}&page_size=25${statusFilter ? `&status=${encodeURIComponent(statusFilter)}` : ""}`,
      ),
  });

  async function retire(id: number) {
    setRetireId(id);
  }

  async function confirmRetire() {
    if (retireId == null) return;
    await apiFetch(`/zombie/${retireId}/retire`, { method: "POST", body: JSON.stringify({ reason: retireReason }) });
    setRetireId(null);
    window.location.reload();
  }

  async function reactivate(id: number) {
    await apiFetch(`/zombie/${id}/reactivate`, { method: "POST" });
    window.location.reload();
  }
  return (
    <div>
      <PageHeader
        title="Zombie / Idle APIs"
        subtitle="Documented APIs with declining or no traffic."
        actions={
          <select
            value={statusFilter}
            onChange={(e) => {
              setPage(1);
              setStatusFilter(e.target.value);
            }}
            aria-label="Filter by status"
            className="rounded-lg border border-ink-200 px-2 py-1 text-sm"
          >
            <option value="">All statuses</option>
            <option value="ACTIVE">ACTIVE</option>
            <option value="DECLINING">DECLINING</option>
            <option value="IDLE">IDLE</option>
            <option value="ZOMBIE">ZOMBIE</option>
            <option value="DEAD">DEAD</option>
            <option value="RETIRED">RETIRED</option>
          </select>
        }
      />
      {error ? <p className="text-sm text-negative-600">{(error).message}</p> : null}
      {isLoading ? (
        <p className="text-sm text-ink-500 dark:text-ink-400">Loading...</p>
      ) : !data || data.items.length === 0 ? (
        <EmptyState title="No zombie findings" description="All registered endpoints are active." />
      ) : (
        <div className="space-y-3">
          {data.items.map((row) => (
            <div key={row.id} className="rounded-xl border border-ink-200 bg-white p-4 dark:border-ink-800 dark:bg-ink-900">
              <div className="flex items-center gap-3">
                <Badge variant={statusVariant[row.status]}>{row.status}</Badge>
                <span className="font-mono text-xs">{row.method} {row.path_template}</span>
              </div>
              <p className="mt-2 text-xs text-ink-600 dark:text-ink-300">
                7d: {row.requests_7d} · 14d: {row.requests_14d} · 30d: {row.requests_30d} · avg/day: {row.avg_daily_requests_30d.toFixed(2)}
              </p>
              <div className="mt-3 flex gap-2">
                {row.retired ? (
                  <Button variant="secondary" className="px-2 py-1 text-xs" onClick={() => void reactivate(row.id)}>
                    Reactivate
                  </Button>
                ) : (
                  <Button variant="secondary" className="px-2 py-1 text-xs" onClick={() => void retire(row.id)}>
                    Retire
                  </Button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
      <div className="mt-3 flex items-center justify-between text-sm text-ink-600 dark:text-ink-400">
        <span>Total: {data?.total ?? 0}</span>
        <div className="flex gap-2">
          <Button variant="secondary" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
            Prev
          </Button>
          <span>Page {page}</span>
          <Button
            variant="secondary"
            disabled={Boolean(data && page * data.page_size >= data.total)}
            onClick={() => setPage((p) => p + 1)}
          >
            Next
          </Button>
        </div>
      </div>
      <ConfirmDialog
        open={retireId != null}
        title="Retire endpoint"
        description="Add a reason for retirement."
        reason={retireReason}
        setReason={setRetireReason}
        onCancel={() => setRetireId(null)}
        onConfirm={() => void confirmRetire()}
        confirmLabel="Retire"
      />
    </div>
  );
}
