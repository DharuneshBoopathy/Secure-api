import { Check, Crown, Plus, UserPlus, X } from "lucide-react";
import { FormEvent, useCallback, useEffect, useState } from "react";
import type { OrgMembershipRow, OrgRow } from "@/api/client";
import {
  approveOrgMember,
  createOrg,
  isAuthenticated,
  isSuperAdmin,
  listAllOrgs,
  listMyOrgs,
  listOrgMembers,
  rejectOrgMember,
  removeOrgMember,
  requestToJoinOrg,
  transferOrgOwnership,
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
  const currentUser = useAppStore((s) => s.user);

  const [orgs, setOrgs] = useState<OrgRow[]>([]);
  const [allOrgs, setAllOrgs] = useState<OrgRow[]>([]);
  const [members, setMembers] = useState<OrgMembershipRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<number | null>(null);

  const [newOrgName, setNewOrgName] = useState("");
  const [joinOrgId, setJoinOrgId] = useState("");

  const superAdmin = isSuperAdmin(currentUser?.role);
  // A super admin can act on any org (app/routers/orgs.py::_require_owner
  // treats platform admins as owners), including ones they aren't in — so
  // resolve the selected org against the full list, not just memberships.
  const currentOrg =
    orgs.find((o) => o.id === currentOrgId) ?? allOrgs.find((o) => o.id === currentOrgId) ?? null;
  const canManage = currentOrg?.my_role === "owner" || superAdmin;

  const load = useCallback(async () => {
    if (!isAuthenticated()) {
      setLoading(false);
      return;
    }
    setErr(null);
    setLoading(true);
    try {
      const [myOrgs, everyOrg] = await Promise.all([
        listMyOrgs(),
        superAdmin ? listAllOrgs() : Promise.resolve<OrgRow[]>([]),
      ]);
      setOrgs(myOrgs);
      setAllOrgs(everyOrg);
      // Auto-select when nothing is chosen yet (mirrors OrgSwitcher) so
      // `currentOrg`/`canManage` below — and the switcher in the sidebar —
      // agree on which org is active instead of silently disagreeing.
      const selectable = myOrgs.length > 0 ? myOrgs : everyOrg;
      let activeOrgId = currentOrgId;
      if (
        (activeOrgId === null || !selectable.some((o) => o.id === activeOrgId)) &&
        selectable.length > 0 &&
        !everyOrg.some((o) => o.id === activeOrgId)
      ) {
        activeOrgId = selectable[0].id;
        setCurrentOrgId(activeOrgId);
      }
      // Ask for the roster whenever an org is selected and let the server
      // decide: it now admits any active member, not just owners, so gating
      // this on my_role === "owner" hid an org's roster from its own people.
      setMembers(activeOrgId ? await listOrgMembers(activeOrgId) : []);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentOrgId, superAdmin]);

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

  // The only way to change who owns an org: the backend refuses to remove the
  // owner outright (orgs.py::remove_member) and demotes the prior owner to
  // editor as part of the transfer. Without this the owner row had no controls
  // at all, so an ownership mistake was unfixable from the UI.
  async function transferTo(userId: number) {
    if (!currentOrgId) return;
    setBusy(userId);
    try {
      await transferOrgOwnership(currentOrgId, userId);
      await load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Ownership transfer failed");
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
  // Ownership can only move to another *active* member — the backend 404s
  // otherwise (orgs.py::transfer_ownership).
  const ownerCandidates = active.filter((m) => m.role !== "owner");

  return (
    <div>
      <PageHeader
        title="Members"
        subtitle={
          superAdmin
            ? "Every organization on the platform, with its join requests and members."
            : "Organizations you belong to, and — for orgs you own — pending requests and member roles."
        }
      />

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

      {orgs.length === 0 && allOrgs.length === 0 && !loading ? (
        <EmptyState title="No organizations yet" description="Create one above, or request to join an existing one." />
      ) : null}

      {superAdmin && allOrgs.length > 0 ? (
        <div className="mb-6 glass-card p-4">
          <h3 className="text-sm font-semibold text-ink-900 dark:text-ink-50">
            All organizations ({allOrgs.length})
          </h3>
          <p className="mt-1 text-xs text-ink-500 dark:text-ink-400">
            Every organization on the platform. Select one to review its join requests and members.
          </p>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-ink-100 text-xs uppercase tracking-wide text-ink-500 dark:border-ink-800 dark:text-ink-400">
                <tr>
                  <th className="px-2 py-2">Organization</th>
                  <th className="px-2 py-2">Owner</th>
                  <th className="px-2 py-2">Members</th>
                  <th className="px-2 py-2">Pending</th>
                  <th className="px-2 py-2" />
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-100 dark:divide-ink-800">
                {allOrgs.map((o) => (
                  <tr key={o.id}>
                    <td className="px-2 py-2 font-medium text-ink-800 dark:text-ink-100">
                      {o.name}
                      <span className="ml-2 text-xs text-ink-400">#{o.id}</span>
                    </td>
                    <td className="px-2 py-2 text-ink-600 dark:text-ink-300">{o.owner_username ?? "—"}</td>
                    <td className="px-2 py-2 text-ink-600 dark:text-ink-300">{o.member_count ?? 0}</td>
                    <td className="px-2 py-2">
                      {o.pending_count ? (
                        <Badge variant="warn">{o.pending_count}</Badge>
                      ) : (
                        <span className="text-ink-400">—</span>
                      )}
                    </td>
                    <td className="px-2 py-2 text-right">
                      {o.id === currentOrgId ? (
                        <Badge variant="ok">selected</Badge>
                      ) : (
                        <button
                          type="button"
                          onClick={() => setCurrentOrgId(o.id)}
                          className="text-xs font-medium text-accent-600 hover:text-accent-700 dark:text-accent-300"
                        >
                          Select
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
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

      {currentOrg ? (
        <>
          {/* Only a super admin can be looking at an org they don't belong
              to, so only they need telling which one is selected — everyone
              else already sees the "current" badge in their own org list. */}
          {superAdmin ? (
            <div className="mb-3 flex items-center gap-2 text-sm text-ink-600 dark:text-ink-300">
              <span>
                Viewing <span className="font-semibold text-ink-900 dark:text-ink-50">{currentOrg.name}</span>
              </span>
              {currentOrg.my_role ? (
                <Badge variant="neutral">{currentOrg.my_role}</Badge>
              ) : (
                <Badge variant="warn">super admin</Badge>
              )}
            </div>
          ) : null}

          {/* Approving and rejecting stay owner-only server-side, so a plain
              member has nothing to do here — the roster below is the part
              they can now see. */}
          {canManage ? (
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
          ) : null}

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
                      {!canManage ? (
                        <Badge variant={m.role === "owner" ? "info" : "neutral"}>{m.role}</Badge>
                      ) : m.role === "owner" ? (
                        // The owner can't be removed or re-roled directly
                        // (orgs.py::remove_member refuses); handing ownership
                        // to someone else is the supported way out, and it
                        // demotes this account to editor.
                        <>
                          <Badge variant="info">owner</Badge>
                          {ownerCandidates.length > 0 ? (
                            <select
                              value=""
                              disabled={busy === m.user_id}
                              onChange={(e) => {
                                const next = Number(e.target.value);
                                if (next) void transferTo(next);
                              }}
                              aria-label="Transfer ownership to"
                              className="rounded-lg border border-ink-200 px-2 py-1 text-sm"
                            >
                              <option value="">Transfer ownership to…</option>
                              {ownerCandidates.map((c) => (
                                <option key={c.user_id} value={c.user_id}>
                                  {c.username}
                                </option>
                              ))}
                            </select>
                          ) : (
                            <span className="text-xs text-ink-400" title="Add another active member first">
                              <Crown className="h-4 w-4" aria-label="Sole member — nobody to transfer ownership to" />
                            </span>
                          )}
                        </>
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
