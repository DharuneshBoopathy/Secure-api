import { useInfiniteQuery } from "@tanstack/react-query";
import { listAudit } from "@/api/client";
import { Button } from "@/components/Button";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";

export function Audit() {
  // The endpoint is keyset-paginated (items + next_cursor_id, no total). This
  // page previously sent ?page=1&page_size=100 — parameters the route does not
  // declare, so FastAPI dropped both and served the default first 25 rows with
  // no way to reach anything older. Everything before those 25 looked erased.
  const { data, isLoading, error, fetchNextPage, hasNextPage, isFetchingNextPage } =
    useInfiniteQuery({
      queryKey: ["audit"],
      queryFn: ({ pageParam }) => listAudit(pageParam),
      initialPageParam: null as number | null,
      getNextPageParam: (last) => last.next_cursor_id,
    });

  const rows = data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <div>
      <PageHeader title="Audit Log" subtitle="Security and operational events." />
      {error ? <p className="text-sm text-negative-600">{error.message}</p> : null}
      {isLoading ? (
        <p className="text-sm text-ink-500 dark:text-ink-400">Loading...</p>
      ) : rows.length === 0 ? (
        <EmptyState title="No audit entries" description="Events will appear as actions occur." />
      ) : (
        <>
          <div className="overflow-hidden rounded-2xl border border-ink-200 bg-white dark:border-ink-800 dark:bg-ink-900">
            <table className="min-w-full text-sm">
              <thead className="bg-ink-50 dark:bg-ink-800">
                <tr>
                  <th className="px-3 py-2 text-left">Timestamp</th>
                  <th className="px-3 py-2 text-left">Event</th>
                  <th className="px-3 py-2 text-left">Actor</th>
                  <th className="px-3 py-2 text-left">Target</th>
                  <th className="px-3 py-2 text-left">Success</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id} className="border-t border-ink-100 dark:border-ink-800">
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
          <div className="mt-4 flex items-center gap-3">
            {hasNextPage ? (
              <Button
                variant="secondary"
                onClick={() => void fetchNextPage()}
                disabled={isFetchingNextPage}
              >
                {isFetchingNextPage ? "Loading..." : "Load older events"}
              </Button>
            ) : null}
            <p className="text-sm text-ink-500 dark:text-ink-400">
              {rows.length} event{rows.length === 1 ? "" : "s"}
              {hasNextPage ? " so far" : " — start of the log"}
            </p>
          </div>
        </>
      )}
    </div>
  );
}
