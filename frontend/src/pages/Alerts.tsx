import { CheckCircle2, RefreshCw, ThumbsDown, ThumbsUp } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { ackAlert, isAuthenticated, listAlerts, submitAlertFeedback, type AlertRow } from "@/api/client";
import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { Drawer } from "@/components/Drawer";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";

function severityVariant(s: string): "neutral" | "ok" | "warn" | "bad" | "info" {
  const x = s.toLowerCase();
  if (x === "high" || x === "critical") return "bad";
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
  const [detailId, setDetailId] = useState<number | null>(null);

  const load = useCallback(async () => {
    if (!isAuthenticated()) {
      setRows([]);
      setLoading(false);
      return;
    }
    setErr(null);
    setLoading(true);
    try {
      setRows(await listAlerts(openOnly));
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
      await ackAlert(id);
      await load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Ack failed");
    } finally {
      setBusy(null);
    }
  }

  async function feedback(id: number, label: "true_positive" | "false_positive") {
    setBusy(id);
    try {
      await submitAlertFeedback(id, label);
      await load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Feedback failed");
    } finally {
      setBusy(null);
    }
  }

  const detailAlert = rows.find((r) => r.id === detailId) ?? null;

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
            <label className="flex cursor-pointer items-center gap-2 text-sm text-ink-600 dark:text-ink-300">
              <input
                type="checkbox"
                className="h-4 w-4 rounded border-ink-300 text-accent-600 focus:ring-accent-500"
                checked={openOnly}
                onChange={(e) => setOpenOnly(e.target.checked)}
              />
              Open only
            </label>
            <Button variant="secondary" onClick={() => void load()} disabled={loading}>
              <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} aria-hidden />
              Refresh
            </Button>
          </>
        }
      />

      {err ? (
        <div className="mb-4 rounded-xl border border-negative-200 bg-negative-50 px-4 py-3 text-sm text-negative-900 dark:border-negative-900 dark:bg-negative-950 dark:text-negative-200">
          {err}
        </div>
      ) : null}

      {loading ? (
        <p className="text-sm text-ink-500 dark:text-ink-400">Loading…</p>
      ) : rows.length === 0 ? (
        <EmptyState title="No alerts" description="You're clear — or try turning off “Open only”." />
      ) : (
        <div className="space-y-3">
          {rows.map((a) => (
            <article
              key={a.id}
              className="glass-card p-5 dark:border-ink-800 dark:bg-ink-900"
            >
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <button
                  type="button"
                  onClick={() => setDetailId(a.id)}
                  className="min-w-0 flex-1 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-500 focus-visible:ring-offset-2 rounded-lg"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant={severityVariant(a.severity)}>{a.severity}</Badge>
                    <Badge variant="neutral">{a.alert_type.replace(/_/g, " ")}</Badge>
                    {!a.acknowledged ? (
                      <span className="text-xs font-medium text-negative-600 dark:text-negative-400">Open</span>
                    ) : (
                      <span className="text-xs font-medium text-positive-600 dark:text-positive-400">Acknowledged</span>
                    )}
                    {a.feedback ? (
                      <Badge variant={a.feedback === "true_positive" ? "bad" : "neutral"}>
                        {a.feedback.replace("_", " ")}
                      </Badge>
                    ) : null}
                  </div>
                  <h3 className="mt-2 font-semibold text-ink-900 dark:text-ink-100">{a.title}</h3>
                  <p className="mt-1 text-sm text-ink-600 dark:text-ink-300">{a.detail}</p>
                  <div className="mt-3 flex flex-wrap gap-2 font-mono text-xs text-ink-500 dark:text-ink-400">
                    {a.method ? (
                      <span className="rounded-md bg-ink-100 px-2 py-0.5 dark:bg-ink-800">{a.method}</span>
                    ) : null}
                    {a.path ? (
                      <span className="max-w-full truncate rounded-md bg-ink-100 px-2 py-0.5 dark:bg-ink-800">{a.path}</span>
                    ) : null}
                    <span className="text-ink-400 dark:text-ink-500">
                      {new Date(a.created_at).toLocaleString()}
                    </span>
                  </div>
                </button>
                {a.acknowledged ? null : (
                  <Button
                    variant="secondary"
                    className="shrink-0"
                    disabled={busy === a.id}
                    onClick={() => void ack(a.id)}
                  >
                    <CheckCircle2 className="h-4 w-4" aria-hidden />
                    Acknowledge
                  </Button>
                )}
              </div>
            </article>
          ))}
        </div>
      )}

      <Drawer
        open={detailAlert != null}
        title={detailAlert?.title ?? ""}
        subtitle={detailAlert ? `${detailAlert.alert_type.replace(/_/g, " ")} · ${detailAlert.severity}` : undefined}
        onClose={() => setDetailId(null)}
      >
        {detailAlert ? (
          <div className="space-y-4 text-sm">
            <p className="text-ink-700 dark:text-ink-300">{detailAlert.detail}</p>
            <dl className="space-y-1 text-xs">
              {detailAlert.method ? (
                <div className="flex gap-2">
                  <dt className="font-medium text-ink-500 dark:text-ink-400">Method</dt>
                  <dd className="font-mono text-ink-700 dark:text-ink-300">{detailAlert.method}</dd>
                </div>
              ) : null}
              {detailAlert.path ? (
                <div className="flex gap-2">
                  <dt className="font-medium text-ink-500 dark:text-ink-400">Path</dt>
                  <dd className="break-all font-mono text-ink-700 dark:text-ink-300">{detailAlert.path}</dd>
                </div>
              ) : null}
              <div className="flex gap-2">
                <dt className="font-medium text-ink-500 dark:text-ink-400">Created</dt>
                <dd className="text-ink-700 dark:text-ink-300">{new Date(detailAlert.created_at).toLocaleString()}</dd>
              </div>
              {detailAlert.event_id ? (
                <div className="flex gap-2">
                  <dt className="font-medium text-ink-500 dark:text-ink-400">Event ID</dt>
                  <dd className="font-mono text-ink-700 dark:text-ink-300">#{detailAlert.event_id}</dd>
                </div>
              ) : null}
            </dl>

            {detailAlert.explanation && detailAlert.explanation.length > 0 ? (
              <div>
                <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-500 dark:text-ink-400">
                  Why this was flagged
                </h4>
                <div className="space-y-2">
                  {detailAlert.explanation.map((f) => (
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
            ) : null}

            {detailAlert.event_id ? (
              <div>
                <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-500 dark:text-ink-400">
                  Was this a real finding?
                </h4>
                <p className="mb-2 text-xs text-ink-500 dark:text-ink-400">
                  {detailAlert.feedback
                    ? `Already labeled ${detailAlert.feedback.replace("_", " ")}.`
                    : "Feeds the next ML retrain — see the README's Anomalies section."}
                </p>
                <div className="flex gap-2">
                  <Button
                    variant="secondary"
                    className="text-xs"
                    disabled={busy === detailAlert.id}
                    onClick={() => void feedback(detailAlert.id, "true_positive")}
                  >
                    <ThumbsUp className="h-3.5 w-3.5" aria-hidden />
                    Real finding
                  </Button>
                  <Button
                    variant="secondary"
                    className="text-xs"
                    disabled={busy === detailAlert.id}
                    onClick={() => void feedback(detailAlert.id, "false_positive")}
                  >
                    <ThumbsDown className="h-3.5 w-3.5" aria-hidden />
                    False positive
                  </Button>
                </div>
              </div>
            ) : null}

            {!detailAlert.acknowledged ? (
              <Button disabled={busy === detailAlert.id} onClick={() => void ack(detailAlert.id)}>
                <CheckCircle2 className="h-4 w-4" aria-hidden />
                Acknowledge
              </Button>
            ) : null}
          </div>
        ) : null}
      </Drawer>
    </div>
  );
}
