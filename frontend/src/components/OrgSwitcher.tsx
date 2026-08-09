import { ChevronsUpDown } from "lucide-react";
import { useEffect, useState } from "react";
import type { OrgRow } from "@/api/client";
import { isAuthenticated, listMyOrgs } from "@/api/client";
import { useAppStore } from "@/store/appStore";

/** Sidebar org picker. Falls back to the caller's sole membership
 * server-side when no org is selected — see app/deps.py::get_org_context —
 * so this only needs to render something when the user belongs to 2+ orgs
 * or hasn't picked one yet. */
export function OrgSwitcher() {
  const [orgs, setOrgs] = useState<OrgRow[]>([]);
  const [loading, setLoading] = useState(true);
  const currentOrgId = useAppStore((s) => s.currentOrgId);
  const setCurrentOrgId = useAppStore((s) => s.setCurrentOrgId);

  useEffect(() => {
    if (!isAuthenticated()) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    void listMyOrgs()
      .then((data) => {
        if (cancelled) return;
        setOrgs(data);
        if (data.length > 0 && !data.some((o) => o.id === currentOrgId)) {
          setCurrentOrgId(data[0].id);
        }
      })
      .catch(() => {
        if (!cancelled) setOrgs([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (loading || orgs.length === 0) return null;

  return (
    <div className="relative px-3 pb-2">
      <label className="sr-only" htmlFor="org-switcher">
        Organization
      </label>
      <div className="relative">
        <select
          id="org-switcher"
          value={currentOrgId ?? ""}
          onChange={(e) => setCurrentOrgId(Number(e.target.value))}
          className="w-full appearance-none rounded-lg border border-ink-200 bg-white py-2 pl-3 pr-8 text-sm font-medium text-ink-800 dark:border-ink-700 dark:bg-ink-950 dark:text-ink-100"
        >
          {orgs.map((o) => (
            <option key={o.id} value={o.id}>
              {o.name}
            </option>
          ))}
        </select>
        <ChevronsUpDown className="pointer-events-none absolute right-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-400" />
      </div>
    </div>
  );
}
