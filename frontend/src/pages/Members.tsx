import { Check, Plus, UserPlus, X } from "lucide-react";
import { FormEvent, useCallback, useEffect, useState } from "react";
import type { OrgMembershipRow, OrgRow } from "@/api/client";
import {
  approveOrgMember,
  createOrg,
  isAuthenticated,
  listMyOrgs,
  listOrgMembers,
  rejectOrgMember,
  removeOrgMember,
  requestToJoinOrg,
  updateOrgMemberRole,
} from "@/api/client";
import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { useAppStore } from "@/store/appStore";

export function Members() {
  const currentOrgId = useAppStore((s) => s.currentOrgId);
  const setCurrentOrgId = useAppStore((s) => s.setCurrentOrgId);

  const [orgs, setOrgs] = useState<OrgRow[]>([]);
  const [members, setMembers] = useState<OrgMembershipRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<number | null>(null);

  const [newOrgName, setNewOrgName] = useState("");
  const [joinOrgId, setJoinOrgId] = useState("");

  const currentOrg = orgs.find((o) => o.id === currentOrgId) ?? null;
  const isOwner = currentOrg?.my_role === "owner";

  const load = useCallback(async () => {
    if (!isAuthenticated()) {
      setLoading(false);
      return;
    }
    setErr(null);
    setLoading(true);
    try {
      const myOrgs = await listMyOrgs();
      setOrgs(myOrgs);
      // Auto-select when nothing is chosen yet (mirrors OrgSwitcher) so
      // `currentOrg`/`isOwner` below — and the switcher in the sidebar —
      // agree on which org is active instead of silently disagreeing.
      let activeOrgId = currentOrgId;
      if ((activeOrgId === null || !myOrgs.some((o) => o.id === activeOrgId)) && myOrgs.length > 0) {
        activeOrgId = myOrgs[0].id;
        setCurrentOrgId(activeOrgId);
      }
      if (activeOrgId && myOrgs.some((o) => o.id === activeOrgId && o.my_role === "owner")) {
        setMembers(await listOrgMembers(activeOrgId));
      } else {
        setMembers([]);
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentOrgId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleCreateOrg(e: FormEvent) {
    e.preventDefault();
    if (newOrgName.trim().length < 2) return;
    try {
      const org = await createOrg(newOrgName.trim());
      setNewOrgName("");
      setCurrentOrgId(org.id);
      await load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to create organization");
    }
  }

  async function handleJoinRequest(e: FormEvent) {
    e.preventDefault();
    const id = Number(joinOrgId);
    if (!Number.isFinite(id) || id <= 0) return;
    try {
      await requestToJoinOrg(id);
      setJoinOrgId("");
      await load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Join request failed");
    }
  }

  async function approve(userId: number) {
    if (!currentOrgId) return;
    setBusy(userId);
    try {
      await approveOrgMember(currentOrgId, userId);
      await load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Approve failed");
    } finally {
      setBusy(null);
    }
  }

  async function reject(userId: number) {
    if (!currentOrgId) return;
    setBusy(userId);
    try {
      await rejectOrgMember(currentOrgId, userId);
      await load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Reject failed");
    } finally {
      setBusy(null);
    }
  }

  async function changeRole(userId: number, role: string) {
    if (!currentOrgId) return;
    setBusy(userId);
    try {
      await updateOrgMemberRole(currentOrgId, userId, role);
      await load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Role change failed");
    } finally {
      setBusy(null);
    }
  }

  async function remove(userId: number) {
    if (!currentOrgId) return;
    setBusy(userId);
    try {
      await removeOrgMember(currentOrgId, userId);
      await load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Remove failed");
    } finally {
      setBusy(null);
    }
  }

  if (!isAuthenticated()) {
    return (
      <div>
        <PageHeader title="Members" subtitle="Manage your organizations and their members." />
        <EmptyState title="Sign in required" description="Log in to view and manage organization membership." />
      </div>
    );
  }

  const pending = members.filter((m) => m.status === "pending");
  const active = members.filter((m) => m.status === "active");

  return (
    <div>
      <PageHeader title="Members" subtitle="Organizations you belong to, and — for orgs you own — pending requests and member roles." />

      {err ? (
        <div className="mb-4 rounded-xl border border-negative-200 bg-negative-50 px-4 py-3 text-sm text-negative-900">{err}</div>
      ) : null}

      <div className="mb-6 grid gap-4 sm:grid-cols-2">
        <form onSubmit={(e) => void handleCreateOrg(e)} className="glass-card p-4">
          <h3 className="text-sm font-semibold text-ink-900 dark:text-ink-50">Create an organization</h3>
          <p className="mt-1 text-xs text-ink-500 dark:text-ink-400">You become its owner.</p>
          <div className="mt-3 flex gap-2">
            <input
              value={newOrgName}
              onChange={(e) => setNewOrgName(e.target.value)}
              placeholder="Organization name"
              className="flex-1 field"
            />
            <Button type="submit" disabled={newOrgName.trim().length < 2}>
              <Plus className="h-4 w-4" />
              Create
            </Button>
          </div>
        </form>

        <form onSubmit={(e) => void handleJoinRequest(e)} className="glass-card p-4">
          <h3 className="text-sm font-semibold text-ink-900 dark:text-ink-50">Request to join an organization</h3>
          <p className="mt-1 text-xs text-ink-500 dark:text-ink-400">Ask the org owner for its ID. Grants no access until approved.</p>
          <div className="mt-3 flex gap-2">
            <input
              value={joinOrgId}
              onChange={(e) => setJoinOrgId(e.target.value)}
              placeholder="Organization ID"
              inputMode="numeric"
              className="flex-1 field"
            />
            <Button type="submit" variant="secondary" disabled={!joinOrgId.trim()}>
              <UserPlus className="h-4 w-4" />
              Request
            </Button>
          </div>
        </form>
      </div>

      {orgs.length === 0 && !loading ? (
        <EmptyState title="No organizations yet" description="Create one above, or request to join an existing one." />
      ) : null}

      {orgs.length > 0 ? (
        <div className="mb-6 glass-card p-4">
          <h3 className="text-sm font-semibold text-ink-900 dark:text-ink-50">Your organizations</h3>
          <ul className="mt-3 space-y-2">
            {orgs.map((o) => (
              <li key={o.id} className="flex items-center justify-between rounded-lg border border-ink-100 px-3 py-2 text-sm">
                <span className="font-medium text-ink-800 dark:text-ink-100">{o.name}</span>
                <div className="flex items-center gap-2">
                  <Badge variant="neutral">{o.my_role}</Badge>
                  {o.id === currentOrgId ? (
                    <Badge variant="ok">current</Badge>
                  ) : (
                    <button
                      type="button"
                      onClick={() => setCurrentOrgId(o.id)}
                      className="text-xs font-medium text-accent-600 hover:text-accent-700 dark:text-accent-300"
                    >
                      Switch
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {currentOrgId && !isOwner ? (
        <EmptyState
          title="Owner access required"
          description="Only the owner of the selected organization can view and manage its members."
        />
      ) : null}

      {isOwner ? (
        <>
          <section className="mb-6">
            <h2 className="mb-3 text-sm font-semibold text-ink-900 dark:text-ink-50">
              Pending requests {pending.length > 0 ? `(${pending.length})` : ""}
            </h2>
            {pending.length === 0 ? (
              <p className="text-sm text-ink-500 dark:text-ink-400">No pending join requests.</p>
            ) : (
              <div className="space-y-2">
                {pending.map((m) => (
                  <div
                    key={m.id}
                    className="glass-card flex items-center justify-between p-4"
                  >
                    <div>
                      <p className="font-medium text-ink-900 dark:text-ink-50">{m.username}</p>
                      <p className="text-xs text-ink-500 dark:text-ink-400">Requested {new Date(m.created_at).toLocaleString()}</p>
                    </div>
                    <div className="flex gap-2">
                      <Button variant="secondary" disabled={busy === m.user_id} onClick={() => void approve(m.user_id)}>
                        <Check className="h-4 w-4" />
                        Approve
                      </Button>
                      <Button variant="danger" disabled={busy === m.user_id} onClick={() => void reject(m.user_id)}>
                        <X className="h-4 w-4" />
                        Reject
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section>
            <h2 className="mb-3 text-sm font-semibold text-ink-900 dark:text-ink-50">Active members ({active.length})</h2>
            {active.length === 0 ? (
              <p className="text-sm text-ink-500 dark:text-ink-400">No active members yet.</p>
            ) : (
              <div className="space-y-2">
                {active.map((m) => (
                  <div
                    key={m.id}
                    className="glass-card flex items-center justify-between p-4"
                  >
                    <p className="font-medium text-ink-900 dark:text-ink-50">{m.username}</p>
                    <div className="flex items-center gap-2">
                      {m.role === "owner" ? (
                        <Badge variant="info">owner</Badge>
                      ) : (
                        <>
                          <select
                            value={m.role}
                            disabled={busy === m.user_id}
                            onChange={(e) => void changeRole(m.user_id, e.target.value)}
                            className="rounded-lg border border-ink-200 px-2 py-1 text-sm"
                          >
                            <option value="viewer">viewer</option>
                            <option value="editor">editor</option>
                          </select>
                          <Button variant="danger" disabled={busy === m.user_id} onClick={() => void remove(m.user_id)}>
                            Remove
                          </Button>
                        </>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>
        </>
      ) : null}
    </div>
  );
}
