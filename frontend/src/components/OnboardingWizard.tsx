import { Check } from "lucide-react";
import { ReactNode, useState } from "react";
import { Link } from "react-router-dom";
import { apiFetch, type Stats } from "@/api/client";
import { Button } from "@/components/Button";

type Props = {
  stats: Stats;
  onDismiss: () => void;
  onDataChanged: () => void;
};

/** Shown on Dashboard in place of a blank first-run screen — see the
 * trigger condition in Dashboard.tsx (no registered endpoints, no shadow
 * endpoints, no traffic yet). Each step's "done" state is derived directly
 * from the same Stats the dashboard already fetches, so it advances on the
 * next Dashboard refresh with no separate polling of its own. */
export function OnboardingWizard({ stats, onDismiss, onDataChanged }: Props) {
  const [sending, setSending] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const hasRegisteredSpec = stats.known_endpoints > 0;
  const hasTraffic = stats.events_last_hour > 0;
  const hasShadow = stats.discovered_undocumented > 0;

  async function sendDemoTraffic() {
    setSending(true);
    setErr(null);
    try {
      await apiFetch("/ingest/batch", {
        method: "POST",
        body: JSON.stringify({
          events: [
            { method: "GET", path: "/health", status_code: 200, latency_ms: 8 },
            // Deliberately not in any registered spec, so step 3 (shadow
            // detection) has something to find immediately.
            { method: "GET", path: "/api/reports/export", status_code: 200, latency_ms: 42 },
          ],
        }),
      });
      onDataChanged();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to send demo traffic");
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="mb-6 rounded-2xl border border-accent-200 bg-accent-50/60 p-6 dark:border-accent-900 dark:bg-accent-950/30">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-base font-semibold text-ink-900 dark:text-ink-100">Get started</h2>
          <p className="mt-1 text-sm text-ink-600 dark:text-ink-300">
            Three steps to see the platform detect a shadow API end to end.
          </p>
        </div>
        <button
          type="button"
          onClick={onDismiss}
          className="shrink-0 rounded-md px-2 py-1 text-xs text-ink-500 hover:bg-white/60 hover:text-ink-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-500 dark:text-ink-400 dark:hover:bg-ink-800"
        >
          Skip for now
        </button>
      </div>

      <ol className="mt-5 space-y-4">
        <Step n={1} done={hasRegisteredSpec} title="Register your API">
          <p>
            Upload an OpenAPI spec, or import a Postman collection or curl commands, from the{" "}
            <Link to="/registry" className="font-medium text-accent-700 hover:underline dark:text-accent-400">
              Registry
            </Link>{" "}
            page.
          </p>
        </Step>
        <Step n={2} done={hasTraffic} title="See traffic flow in">
          <p>Point real traffic at your ingest endpoint, or try it now with two synthetic requests:</p>
          <div className="mt-2 flex items-center gap-3">
            <Button variant="secondary" className="text-xs" disabled={sending} onClick={() => void sendDemoTraffic()}>
              {sending ? "Sending…" : "Send demo traffic"}
            </Button>
            {err ? <span className="text-xs text-negative-600 dark:text-negative-400">{err}</span> : null}
          </div>
        </Step>
        <Step n={3} done={hasShadow} title="Spot your first shadow endpoint">
          <p>
            Undocumented paths (like the demo request above) show up automatically on the{" "}
            <Link to="/shadow" className="font-medium text-accent-700 hover:underline dark:text-accent-400">
              Shadow APIs
            </Link>{" "}
            page.
          </p>
        </Step>
      </ol>
    </div>
  );
}

function Step({ n, done, title, children }: { n: number; done: boolean; title: string; children: ReactNode }) {
  return (
    <li className="flex gap-3">
      <span
        className={[
          "mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold",
          done
            ? "bg-positive-500 text-white"
            : "bg-white text-ink-500 ring-1 ring-ink-200 dark:bg-ink-900 dark:text-ink-400 dark:ring-ink-700",
        ].join(" ")}
      >
        {done ? <Check className="h-3.5 w-3.5" aria-hidden /> : n}
      </span>
      <div className="min-w-0 flex-1">
        <p className={`text-sm font-semibold ${done ? "text-ink-500 line-through dark:text-ink-500" : "text-ink-900 dark:text-ink-100"}`}>
          {title}
        </p>
        <div className="mt-1 text-sm text-ink-600 dark:text-ink-300">{children}</div>
      </div>
    </li>
  );
}
