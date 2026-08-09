import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, KeyRound, Link2, Plug, RefreshCw, Trash2 } from "lucide-react";
import { FormEvent, useMemo, useState } from "react";
import {
  createConnection,
  deleteConnection,
  isAuthenticated,
  listConnections,
  listProviders,
  verifyConnection,
  type ConnectionRow,
  type ConnectionStatus,
} from "@/api/client";
import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";

const statusVariant: Record<ConnectionStatus, "neutral" | "ok" | "warn" | "bad" | "info"> = {
  active: "ok",
  invalid: "bad",
  error: "warn",
  unverified: "neutral",
};

const CUSTOM = "custom";

export function Connections() {
  const queryClient = useQueryClient();
  const authed = isAuthenticated();

  const [provider, setProvider] = useState("anthropic");
  const [name, setName] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [verifyPath, setVerifyPath] = useState("");
  const [endpoints, setEndpoints] = useState("");
  const [verify, setVerify] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [confirmingId, setConfirmingId] = useState<number | null>(null);

  const { data: providers } = useQuery({
    queryKey: ["connection-providers"],
    queryFn: listProviders,
    enabled: authed,
    staleTime: Infinity, // A hard-coded server-side catalog; it never changes mid-session.
  });
  const { data: connections, isLoading } = useQuery({
    queryKey: ["connections"],
    queryFn: listConnections,
    enabled: authed,
  });

  const selected = useMemo(() => providers?.find((p) => p.id === provider), [providers, provider]);
  const isCustom = provider === CUSTOM;

  function resetForm() {
    setName("");
    setApiKey("");
    setBaseUrl("");
    setVerifyPath("");
    setEndpoints("");
  }

  const createMutation = useMutation({
    mutationFn: () =>
      createConnection({
        provider,
        name: name.trim(),
        api_key: apiKey.trim(),
        base_url: isCustom ? baseUrl.trim() : null,
        verify_path: isCustom && verifyPath.trim() ? verifyPath.trim() : null,
        endpoints: isCustom ? endpoints : null,
        verify,
      }),
    onSuccess: (row) => {
      setErr(null);
      setMsg(
        `Added ${row.name} — now monitoring ${row.endpoints_registered} endpoint${row.endpoints_registered === 1 ? "" : "s"}.`,
      );
      resetForm();
      void queryClient.invalidateQueries({ queryKey: ["connections"] });
    },
    onError: (e) => {
      setMsg(null);
      setErr(e instanceof Error ? e.message : "Could not add this API");
    },
  });

  const verifyMutation = useMutation({
    mutationFn: (id: number) => verifyConnection(id),
    onSuccess: () => {
      setErr(null);
      void queryClient.invalidateQueries({ queryKey: ["connections"] });
    },
    onError: (e) => setErr(e instanceof Error ? e.message : "Verification failed"),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => deleteConnection(id),
    onSuccess: (res) => {
      setConfirmingId(null);
      setErr(null);
      setMsg(`Removed the connection and ${res.endpoints_removed} of its endpoints.`);
      void queryClient.invalidateQueries({ queryKey: ["connections"] });
    },
    onError: (e) => {
      setConfirmingId(null);
      setErr(e instanceof Error ? e.message : "Could not remove this connection");
    },
  });

  const canSubmit =
    !createMutation.isPending &&
    name.trim().length > 0 &&
    apiKey.trim().length >= 8 &&
    (!isCustom || (baseUrl.trim().length > 0 && endpoints.trim().length > 0));

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    createMutation.mutate();
  }

  if (!authed) {
    return (
      <div>
        <PageHeader title="Connected APIs" subtitle="Add an API to monitoring with its access key." />
        <EmptyState title="Sign in required" description="Log in to connect an API." />
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title="Connected APIs"
        subtitle="Paste a provider key instead of uploading a spec. The endpoints for that provider are added to your monitored inventory straight away."
      />

      {err ? (
        <div className="mb-4 rounded-xl border border-negative-200 bg-negative-50 px-4 py-3 text-sm text-negative-900 dark:border-negative-900 dark:bg-negative-950 dark:text-negative-200">
          {err}
        </div>
      ) : null}
      {msg ? (
        <div className="mb-4 rounded-xl border border-positive-200 bg-positive-50 px-4 py-3 text-sm text-positive-900 dark:border-positive-900 dark:bg-positive-950 dark:text-positive-200">
          {msg}
        </div>
      ) : null}

      <form
        onSubmit={handleSubmit}
        className="mb-6 glass-card p-6"
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label
              htmlFor="conn-provider"
              className="block text-xs font-semibold uppercase tracking-wide text-ink-500 dark:text-ink-400"
            >
              Provider
            </label>
            <select
              id="conn-provider"
              value={provider}
              onChange={(e) => setProvider(e.target.value)}
              className="field mt-1"
            >
              {(providers ?? [{ id: "anthropic", label: "Anthropic (Claude)" }]).map((p) => (
                <option key={p.id} value={p.id}>
                  {p.label}
                </option>
              ))}
            </select>
            {selected && !isCustom ? (
              <p className="mt-1 text-xs text-ink-500 dark:text-ink-400">
                {selected.base_url} · {selected.endpoint_count} endpoints
                {selected.docs_url ? (
                  <>
                    {" · "}
                    <a
                      href={selected.docs_url}
                      target="_blank"
                      rel="noreferrer noopener"
                      className="text-accent-600 underline hover:text-accent-700 dark:text-accent-400"
                    >
                      get a key
                    </a>
                  </>
                ) : null}
              </p>
            ) : null}
          </div>

          <div>
            <label
              htmlFor="conn-name"
              className="block text-xs font-semibold uppercase tracking-wide text-ink-500 dark:text-ink-400"
            >
              Name
            </label>
            <input
              id="conn-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Claude production"
              className="field mt-1"
            />
          </div>
        </div>

        <div className="mt-4">
          <label
            htmlFor="conn-key"
            className="block text-xs font-semibold uppercase tracking-wide text-ink-500 dark:text-ink-400"
          >
            API key
          </label>
          <input
            id="conn-key"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            type="password"
            autoComplete="off"
            spellCheck={false}
            placeholder={selected?.key_hint ?? "Paste the key"}
            className="field mt-1 font-mono"
          />
          <p className="mt-1 text-xs text-ink-500 dark:text-ink-400">
            Encrypted before it is stored. Only the first 8 and last 4 characters are ever shown again.
          </p>
        </div>

        {isCustom ? (
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <div>
              <label
                htmlFor="conn-base-url"
                className="block text-xs font-semibold uppercase tracking-wide text-ink-500 dark:text-ink-400"
              >
                Base URL
              </label>
              <input
                id="conn-base-url"
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
                placeholder="https://api.example.com"
                spellCheck={false}
                className="field mt-1"
              />
            </div>
            <div>
              <label
                htmlFor="conn-verify-path"
                className="block text-xs font-semibold uppercase tracking-wide text-ink-500 dark:text-ink-400"
              >
                Health path (optional)
              </label>
              <input
                id="conn-verify-path"
                value={verifyPath}
                onChange={(e) => setVerifyPath(e.target.value)}
                placeholder="/v1/health"
                spellCheck={false}
                className="field mt-1"
              />
            </div>
            <div className="sm:col-span-2">
              <label
                htmlFor="conn-endpoints"
                className="block text-xs font-semibold uppercase tracking-wide text-ink-500 dark:text-ink-400"
              >
                Endpoints to monitor
              </label>
              <textarea
                id="conn-endpoints"
                value={endpoints}
                onChange={(e) => setEndpoints(e.target.value)}
                placeholder={"GET /v1/health\nPOST /v1/charges\nGET /v1/charges/{id}"}
                spellCheck={false}
                className="field mt-1 h-32 font-mono text-xs leading-relaxed"
              />
              <p className="mt-1 text-xs text-ink-500 dark:text-ink-400">
                One <code>METHOD /path</code> per line. Use <code>{"{id}"}</code> for a variable segment.
              </p>
            </div>
          </div>
        ) : null}

        <label className="mt-4 flex items-center gap-2 text-sm text-ink-600 dark:text-ink-300">
          <input type="checkbox" checked={verify} onChange={(e) => setVerify(e.target.checked)} />
          Check the key against the provider now
        </label>

        <div className="mt-6">
          <Button type="submit" disabled={!canSubmit}>
            <Plug className="h-4 w-4" aria-hidden />
            {createMutation.isPending ? "Connecting…" : "Connect API"}
          </Button>
        </div>
      </form>

      {isLoading ? (
        <p className="text-sm text-ink-500 dark:text-ink-400">Loading...</p>
      ) : !connections || connections.length === 0 ? (
        <EmptyState
          icon={<KeyRound className="h-6 w-6" aria-hidden />}
          title="No connected APIs"
          description="Paste a Claude, Gemini or OpenAI key above to start monitoring one without a spec."
        />
      ) : (
        <div className="overflow-x-auto glass-card">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-ink-100 text-xs uppercase tracking-wide text-ink-500 dark:border-ink-800 dark:text-ink-400">
              <tr>
                <th className="px-4 py-3">Name</th>
                <th className="px-4 py-3">Provider</th>
                <th className="px-4 py-3">Key</th>
                <th className="px-4 py-3">Endpoints</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Last checked</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-100 dark:divide-ink-800">
              {connections.map((c: ConnectionRow) => (
                <tr key={c.id}>
                  <td className="px-4 py-3 font-medium text-ink-900 dark:text-ink-100">
                    {c.name}
                    <span
                      title={c.base_url}
                      className="block max-w-[13rem] truncate text-xs font-normal text-ink-500 dark:text-ink-400"
                    >
                      {c.base_url}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-ink-600 dark:text-ink-300">{c.provider_label}</td>
                  <td className="whitespace-nowrap px-4 py-3 font-mono text-xs text-ink-500 dark:text-ink-400">
                    {c.key_masked}
                  </td>
                  <td className="px-4 py-3 text-ink-600 dark:text-ink-300">{c.endpoints_registered}</td>
                  <td className="px-4 py-3">
                    <Badge variant={statusVariant[c.status]}>{c.status}</Badge>
                    {/* Truncated to one line with the full text on hover — a
                        provider's rejection message is long enough to triple
                        the row height otherwise. */}
                    {c.last_check_detail ? (
                      <span
                        title={c.last_check_detail}
                        className="mt-1 block max-w-[11rem] truncate text-xs text-ink-500 dark:text-ink-400"
                      >
                        {c.last_check_detail}
                      </span>
                    ) : null}
                  </td>
                  <td className="px-4 py-3 text-ink-500 dark:text-ink-400">
                    {c.last_checked_at ? (
                      // Date only, full timestamp on hover — the column has to
                      // stay narrow enough that the row actions still fit.
                      <span title={new Date(c.last_checked_at).toLocaleString()}>
                        {new Date(c.last_checked_at).toLocaleDateString()}
                      </span>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3">
                    <div className="flex justify-end gap-2">
                      <Button
                        variant="secondary"
                        className="px-2 py-1 text-xs"
                        disabled={verifyMutation.isPending}
                        onClick={() => verifyMutation.mutate(c.id)}
                      >
                        {c.status === "active" ? (
                          <CheckCircle2 className="h-3.5 w-3.5" aria-hidden />
                        ) : (
                          <RefreshCw className="h-3.5 w-3.5" aria-hidden />
                        )}
                        Check
                      </Button>
                      {confirmingId === c.id ? (
                        <>
                          <Button
                            variant="danger"
                            className="px-2 py-1 text-xs"
                            disabled={deleteMutation.isPending}
                            onClick={() => deleteMutation.mutate(c.id)}
                          >
                            Confirm?
                          </Button>
                          <Button variant="ghost" className="px-2 py-1 text-xs" onClick={() => setConfirmingId(null)}>
                            Cancel
                          </Button>
                        </>
                      ) : (
                        <Button
                          variant="secondary"
                          className="px-2 py-1 text-xs"
                          onClick={() => setConfirmingId(c.id)}
                          aria-label={`Remove ${c.name}`}
                        >
                          <Trash2 className="h-3.5 w-3.5" aria-hidden />
                          Remove
                        </Button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="mt-4 flex items-center gap-2 text-xs text-ink-500 dark:text-ink-400">
        <Link2 className="h-3.5 w-3.5" aria-hidden />
        Removing a connection also removes the endpoints it added, so idle and zombie scans stop reporting on them.
      </p>
    </div>
  );
}
