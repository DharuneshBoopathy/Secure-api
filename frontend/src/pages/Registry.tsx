import { Upload } from "lucide-react";
import type { FormEvent } from "react";
import { useCallback, useEffect, useState } from "react";
import type { LatestOpenApiResponse } from "@/api/client";
import { apiFetch, isAuthenticated } from "@/api/client";
import { Button } from "@/components/Button";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";

export function Registry() {
  const [title, setTitle] = useState("Production API");
  const [version, setVersion] = useState("");
  const [yaml, setYaml] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [latest, setLatest] = useState<LatestOpenApiResponse | null>(null);

  const loadLatest = useCallback(async () => {
    if (!isAuthenticated()) {
      setLatest(null);
      return;
    }
    try {
      setLatest(await apiFetch<LatestOpenApiResponse>("/registry/openapi/latest"));
    } catch {
      setLatest(null);
    }
  }, []);

  useEffect(() => {
    void loadLatest();
  }, [loadLatest]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setErr(null);
    setMsg(null);
    if (!yaml.trim()) {
      setErr("Paste an OpenAPI YAML spec.");
      return;
    }
    setSubmitting(true);
    try {
      const res = await apiFetch<{ snapshot_id: number; paths_registered: number; paths_in_spec: number }>(
        "/registry/openapi",
        {
          method: "POST",
          body: JSON.stringify({
            title: title.trim() || "Registered API",
            version: version.trim() || null,
            spec_yaml: yaml,
          }),
        },
      );
      setMsg(`Saved snapshot #${res.snapshot_id}. New paths registered: ${res.paths_registered} of ${res.paths_in_spec}.`);
      await loadLatest();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setSubmitting(false);
    }
  }

  if (!isAuthenticated()) {
    return (
      <div>
        <PageHeader title="OpenAPI registry" subtitle="Define your authorized API surface for drift detection." />
        <EmptyState title="API key required" description="Add your monitor key under Settings." />
      </div>
    );
  }

  const latestLine =
    latest && "snapshot" in latest && latest.snapshot === null
      ? "No snapshot uploaded yet."
      : latest && "title" in latest
        ? `${latest.title}${latest.version ? ` v${latest.version}` : ""} · ${new Date(latest.created_at).toLocaleString()}`
        : null;

  return (
    <div>
      <PageHeader
        title="OpenAPI registry"
        subtitle="Upload YAML (OpenAPI 3). New path templates are merged into the known-endpoint inventory."
      />

      {latestLine ? (
        <div className="mb-6 rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-700 shadow-sm">
          <span className="font-semibold text-slate-900">Latest: </span>
          {latestLine}
        </div>
      ) : null}

      <form
        onSubmit={(e) => void submit(e)}
        className="rounded-2xl border border-slate-200/80 bg-white p-6 shadow-card"
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wide text-slate-500">
              Title
            </label>
            <input
              className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm shadow-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. Payments API"
            />
          </div>
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wide text-slate-500">
              Version (optional)
            </label>
            <input
              className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm shadow-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20"
              value={version}
              onChange={(e) => setVersion(e.target.value)}
              placeholder="1.0.0"
            />
          </div>
        </div>
        <div className="mt-4">
          <label className="block text-xs font-semibold uppercase tracking-wide text-slate-500">
            OpenAPI YAML
          </label>
          <textarea
            className="mt-1 h-72 w-full rounded-lg border border-slate-200 px-3 py-2 font-mono text-xs leading-relaxed shadow-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20"
            value={yaml}
            onChange={(e) => setYaml(e.target.value)}
            placeholder={
              "openapi: 3.0.3\ninfo:\n  title: My API\n  version: 1.0.0\npaths:\n  /health:\n    get:\n      responses:\n        '200':\n          description: OK"
            }
            spellCheck={false}
          />
        </div>
        {err ? <p className="mt-3 text-sm text-rose-600">{err}</p> : null}
        {msg ? <p className="mt-3 text-sm text-emerald-700">{msg}</p> : null}
        <div className="mt-6">
          <Button type="submit" disabled={submitting}>
            <Upload className="h-4 w-4" />
            {submitting ? "Uploading…" : "Register specification"}
          </Button>
        </div>
      </form>
    </div>
  );
}
