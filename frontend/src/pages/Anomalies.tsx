import { useQuery } from "@tanstack/react-query";
import { Paginated, TrafficEventOut, apiFetch } from "@/api/client";
import { Button } from "@/components/Button";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { useState } from "react";

export function Anomalies() {
  const [page, setPage] = useState(1);
  const [onlyAnomalies, setOnlyAnomalies] = useState(true);
  const { data, isLoading, error } = useQuery({
    queryKey: ["anomalies", page, onlyAnomalies],
    queryFn: () =>
      apiFetch<Paginated<TrafficEventOut>>(
        `/anomalies?only_anomalies=${onlyAnomalies ? "true" : "false"}&page=${page}&page_size=25`,
      ),
  });
  return (
    <div>
      <PageHeader
        title="Anomalies"
        subtitle="Requests flagged by ensemble anomaly scoring."
        actions={
          <label className="flex items-center gap-2 text-sm text-slate-600">
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
      {error ? <p className="text-sm text-rose-600">{(error as Error).message}</p> : null}
      {isLoading ? (
        <p className="text-sm text-slate-500">Loading...</p>
      ) : !data || data.items.length === 0 ? (
        <EmptyState title="No anomalies detected" description="Model has not flagged suspicious traffic yet." />
      ) : (
        <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50 dark:bg-slate-800">
              <tr>
                <th className="px-3 py-2 text-left">Timestamp</th>
                <th className="px-3 py-2 text-left">Path</th>
                <th className="px-3 py-2 text-left">IP</th>
                <th className="px-3 py-2 text-left">Score</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((row) => (
                <tr key={row.id} className="border-t border-slate-100 dark:border-slate-800">
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
      <div className="mt-3 flex items-center justify-between text-sm text-slate-600">
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
    </div>
  );
}
