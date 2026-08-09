import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Paginated, TrafficEventOut, apiFetch } from "@/api/client";
import { Button } from "@/components/Button";
import { Drawer } from "@/components/Drawer";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";

type ExplanationFeature = { feature: string; value: number; baseline_mean: number; z_score: number };

function asExplanation(features: Record<string, unknown>): ExplanationFeature[] {
  const raw = features["explanation"];
  return Array.isArray(raw) ? (raw as ExplanationFeature[]) : [];
}

export function Anomalies() {
  const [page, setPage] = useState(1);
  const [onlyAnomalies, setOnlyAnomalies] = useState(true);
  const [detailId, setDetailId] = useState<number | null>(null);
  const { data, isLoading, error } = useQuery({
    queryKey: ["anomalies", page, onlyAnomalies],
    queryFn: () =>
      apiFetch<Paginated<TrafficEventOut>>(
        `/anomalies?only_anomalies=${onlyAnomalies ? "true" : "false"}&page=${page}&page_size=25`,
      ),
  });

  const detailEvent = data?.items.find((r) => r.id === detailId) ?? null;
  const explanation = detailEvent ? asExplanation(detailEvent.anomaly_features) : [];

  return (
    <div>
      <PageHeader
        title="Anomalies"
        subtitle="Requests flagged by ensemble anomaly scoring."
        actions={
          <label className="flex items-center gap-2 text-sm text-ink-600 dark:text-ink-300">
            <input
              type="checkbox"
              checked={onlyAnomalies}
              onChange={(e) => {
                setPage(1);
                setOnlyAnomalies(e.target.checked);
              }}
            />
            Only anomalies
          </label>
        }
      />
      {error ? <p className="text-sm text-negative-600 dark:text-negative-400">{(error).message}</p> : null}
      {isLoading ? (
        <p className="text-sm text-ink-500 dark:text-ink-400">Loading...</p>
      ) : !data || data.items.length === 0 ? (
        <EmptyState title="No anomalies detected" description="Model has not flagged suspicious traffic yet." />
      ) : (
        <div className="overflow-x-auto overflow-hidden rounded-2xl border border-ink-200 bg-white dark:border-ink-800 dark:bg-ink-900">
          <table className="min-w-full text-sm">
            <thead className="bg-ink-50 dark:bg-ink-800">
              <tr>
                <th className="px-3 py-2 text-left">Timestamp</th>
                <th className="px-3 py-2 text-left">Path</th>
                <th className="px-3 py-2 text-left">IP</th>
                <th className="px-3 py-2 text-left">Score</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((row) => (
                <tr
                  key={row.id}
                  tabIndex={0}
                  role="button"
                  onClick={() => setDetailId(row.id)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") setDetailId(row.id);
                  }}
                  className="cursor-pointer border-t border-ink-100 hover:bg-ink-50 focus:outline-none focus-visible:bg-accent-50 dark:border-ink-800 dark:hover:bg-ink-800 dark:focus-visible:bg-ink-800"
                >
                  <td className="px-3 py-2">{new Date(row.ts).toLocaleString()}</td>
                  <td className="px-3 py-2 font-mono text-xs">{row.path}</td>
                  <td className="px-3 py-2">{row.source_ip ?? "-"}</td>
                  <td className="px-3 py-2">{row.anomaly_score?.toFixed(3) ?? "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="mt-3 flex items-center justify-between text-sm text-ink-600 dark:text-ink-300">
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

      <Drawer
        open={detailEvent != null}
        title={detailEvent ? `${detailEvent.method} ${detailEvent.path}` : ""}
        subtitle={detailEvent ? new Date(detailEvent.ts).toLocaleString() : undefined}
        onClose={() => setDetailId(null)}
      >
        {detailEvent ? (
          <div className="space-y-4 text-sm">
            <dl className="space-y-1 text-xs">
              <Row label="Status">{detailEvent.status_code}</Row>
              <Row label="Response time">{detailEvent.response_time_ms.toFixed(1)} ms</Row>
              <Row label="Source IP">{detailEvent.source_ip ?? "—"}</Row>
              <Row label="Anomaly score">{detailEvent.anomaly_score?.toFixed(4) ?? "—"}</Row>
              <Row label="Request size">{detailEvent.request_size_bytes} bytes</Row>
              <Row label="Response size">{detailEvent.response_size_bytes} bytes</Row>
              <Row label="User agent">{detailEvent.user_agent ?? "—"}</Row>
              <Row label="Content type">{detailEvent.content_type ?? "—"}</Row>
              <Row label="Session ID">{detailEvent.session_id ?? "—"}</Row>
            </dl>

            {explanation.length > 0 ? (
              <div>
                <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-500 dark:text-ink-400">
                  Why this was flagged
                </h4>
                <div className="space-y-2">
                  {explanation.map((f) => (
                    <div
                      key={f.feature}
                      className="rounded-lg border border-ink-100 bg-ink-50 p-2 text-xs dark:border-ink-800 dark:bg-ink-950"
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-mono font-semibold text-ink-800 dark:text-ink-200">{f.feature}</span>
                        <span className={f.z_score >= 0 ? "text-negative-600 dark:text-negative-400" : "text-accent-600 dark:text-accent-400"}>
                          z = {f.z_score.toFixed(2)}
                        </span>
                      </div>
                      <p className="mt-1 text-ink-500 dark:text-ink-400">
                        value {f.value.toFixed(2)} vs. baseline mean {f.baseline_mean.toFixed(2)}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <p className="text-xs text-ink-400 dark:text-ink-500">
                No per-feature explanation stored for this event (only populated for events scored anomalous — see app/services/ml_anomaly.py).
              </p>
            )}
          </div>
        ) : null}
      </Drawer>
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-2">
      <dt className="w-28 shrink-0 font-medium text-ink-500 dark:text-ink-400">{label}</dt>
      <dd className="break-all text-ink-700 dark:text-ink-300">{children}</dd>
    </div>
  );
}
