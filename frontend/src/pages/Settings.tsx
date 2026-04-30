import { KeyRound, Save } from "lucide-react";
import type { FormEvent } from "react";
import { useState } from "react";
import { getApiKey, setApiKey } from "@/api/client";
import { Button } from "@/components/Button";
import { PageHeader } from "@/components/PageHeader";

export function Settings() {
  const [key, setKey] = useState(() => getApiKey());
  const [saved, setSaved] = useState(false);

  function save(e: FormEvent) {
    e.preventDefault();
    setApiKey(key);
    setSaved(true);
    window.setTimeout(() => setSaved(false), 2500);
  }

  return (
    <div>
      <PageHeader
        title="Settings"
        subtitle="The monitor API expects the same value as MONITOR_API_KEY on the backend (.env)."
      />
      <form
        onSubmit={save}
        className="max-w-xl rounded-2xl border border-slate-200/80 bg-white p-6 shadow-card"
      >
        <div className="flex items-center gap-2 text-slate-800">
          <KeyRound className="h-5 w-5 text-brand-600" />
          <span className="text-sm font-semibold">X-Monitor-Key</span>
        </div>
        <p className="mt-2 text-sm text-slate-600">
          Stored only in this browser (localStorage). Sent as a header on dashboard and inventory requests.
        </p>
        <input
          type="password"
          autoComplete="off"
          className="mt-4 w-full rounded-lg border border-slate-200 px-3 py-2 font-mono text-sm shadow-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20"
          value={key}
          onChange={(e) => setKey(e.target.value)}
          placeholder="change-me-local-dev-key"
        />
        <div className="mt-6 flex flex-wrap items-center gap-3">
          <Button type="submit" variant="primary">
            <Save className="h-4 w-4" />
            Save key
          </Button>
          {saved ? <span className="text-sm font-medium text-emerald-600">Saved.</span> : null}
        </div>
      </form>
    </div>
  );
}
