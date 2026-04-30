import { useEffect, useMemo, useState } from "react";
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { apiFetch, Paginated, TrafficEventOut } from "@/api/client";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { useAppStore } from "@/store/appStore";

export function Traffic() {
  const token = useAppStore((s) => s.accessToken);
  const [rows, setRows] = useState<TrafficEventOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void apiFetch<Paginated<TrafficEventOut>>("/anomalies?only_anomalies=false&page=1&page_size=100")
      .then((res) => {
        if (!active) return;
        setRows(res.items);
      })
      .catch((e) => {
        if (!active) return;
        setErr(e instanceof Error ? e.message : "Failed to load");
      })
      .finally(() => {
        if (!active) return;
        setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    const apiKey = localStorage.getItem("apimonitor_api_key") ?? "";
    const authHeader = token ? `Bearer ${token}` : apiKey;
    if (!authHeader) return;
    const src = new EventSource(`/api/traffic/stream?auth=${encodeURIComponent(authHeader)}`);
    src.onmessage = (ev) => {
      try {
        const d = JSON.parse(ev.data) as {
          id: number;
          ts: string;
          method: string;
          path: string;
          status_code: number;
          response_time_ms: number;
          source_ip: string | null;
          is_anomaly: boolean;
          anomaly_score: number | null;
        };
        setRows((prev) => {
          const next: TrafficEventOut = {
            id: d.id,
            ts: d.ts,
            method: d.method,
            path: d.path,
            status_code: d.status_code,
            source_ip: d.source_ip,
            response_time_ms: d.response_time_ms,
            request_size_bytes: 0,
            response_size_bytes: 0,
            user_agent: null,
            content_type: null,
            x_forwarded_for: null,
            referer: null,
            monitor_key: null,
            session_id: null,
            anomaly_score: d.anomaly_score,
            is_anomaly: d.is_anomaly,
            anomaly_features: {},
          };
          return [next, ...prev].slice(0, 500);
        });
      } catch {
        // ignore malformed event payload
      }
    };
    src.onerror = () => src.close();
    return () => src.close();
  }, [token]);

  const rpm = useMemo(() => {
    const map = new Map<string, number>();
    for (const row of rows) {
      const bucket = new Date(row.ts);
      bucket.setSeconds(0, 0);
      const key = bucket.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
      map.set(key, (map.get(key) ?? 0) + 1);
    }
    return Array.from(map.entries())
      .map(([minute, count]) => ({ minute, count }))
      .slice(-60);
  }, [rows]);

  return (
    <div>
      <PageHeader title="Live Traffic" subtitle="Most recent requests with anomaly labels." />
      {err ? <p className="text-sm text-rose-600">{err}</p> : null}
      <div className="mb-4 h-48 rounded-2xl border border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={rpm}>
            <XAxis dataKey="minute" hide />
            <YAxis allowDecimals={false} />
            <Tooltip />
            <Bar dataKey="count" fill="#2563eb" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      {loading ? (
        <p className="text-sm text-slate-500">Loading...</p>
      ) : rows.length === 0 ? (
        <EmptyState title="No traffic yet" description="Start ingesting events to populate the stream." />
      ) : (
        <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50 dark:bg-slate-800">
              <tr>
                <th className="px-3 py-2 text-left">Timestamp</th>
                <th className="px-3 py-2 text-left">Method</th>
                <th className="px-3 py-2 text-left">Path</th>
                <th className="px-3 py-2 text-left">Status</th>
                <th className="px-3 py-2 text-left">Response ms</th>
                <th className="px-3 py-2 text-left">IP</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id} className="border-t border-slate-100 dark:border-slate-800">
                  <td className="px-3 py-2">{new Date(row.ts).toLocaleString()}</td>
                  <td className="px-3 py-2">{row.method}</td>
                  <td className="px-3 py-2 font-mono text-xs">{row.path}</td>
                  <td className="px-3 py-2">{row.status_code}</td>
                  <td className="px-3 py-2">{row.response_time_ms.toFixed(2)}</td>
                  <td className="px-3 py-2">{row.source_ip ?? "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
