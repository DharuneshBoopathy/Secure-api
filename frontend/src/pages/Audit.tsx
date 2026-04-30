import { useQuery } from "@tanstack/react-query";
import { Paginated, apiFetch } from "@/api/client";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";

type AuditRow = {
  id: number;
  event_type: string;
  actor: string;
  target: string | null;
  ip: string | null;
  user_agent: string | null;
  timestamp: string;
  success: boolean;
};

export function Audit() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["audit", 1],
    queryFn: () => apiFetch<Paginated<AuditRow>>("/audit?page=1&page_size=100"),
  });
  return (
    <div>
      <PageHeader title="Audit Log" subtitle="Security and operational events." />
      {error ? <p className="text-sm text-rose-600">{(error as Error).message}</p> : null}
      {isLoading ? (
        <p className="text-sm text-slate-500">Loading...</p>
      ) : !data || data.items.length === 0 ? (
        <EmptyState title="No audit entries" description="Events will appear as actions occur." />
      ) : (
        <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50 dark:bg-slate-800">
              <tr>
                <th className="px-3 py-2 text-left">Timestamp</th>
                <th className="px-3 py-2 text-left">Event</th>
                <th className="px-3 py-2 text-left">Actor</th>
                <th className="px-3 py-2 text-left">Target</th>
                <th className="px-3 py-2 text-left">Success</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((row) => (
                <tr key={row.id} className="border-t border-slate-100 dark:border-slate-800">
                  <td className="px-3 py-2">{new Date(row.timestamp).toLocaleString()}</td>
                  <td className="px-3 py-2">{row.event_type}</td>
                  <td className="px-3 py-2">{row.actor}</td>
                  <td className="px-3 py-2">{row.target ?? "-"}</td>
                  <td className="px-3 py-2">{row.success ? "Yes" : "No"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
