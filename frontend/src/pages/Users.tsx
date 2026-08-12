import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Lock, Plus, ShieldOff, UserCog } from "lucide-react";
import { FormEvent, useState } from "react";
import {
  createUser,
  deactivateUser,
  isAuthenticated,
  isPlatformAdmin,
  isSuperAdmin,
  listUsers,
  updateUser,
  type AssignableRole,
  type UserRow,
} from "@/api/client";
import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { useAppStore } from "@/store/appStore";

const roleVariant: Record<UserRow["role"], "neutral" | "ok" | "warn" | "bad" | "info"> = {
  super_admin: "warn",
  admin: "info",
  editor: "ok",
  viewer: "neutral",
};

export function Users() {
  const currentUser = useAppStore((s) => s.user);
  const queryClient = useQueryClient();

  const canAdminister = isPlatformAdmin(currentUser?.role);
  // Only the super admin may touch another administrator or hand out the
  // admin role. The server enforces this (app/routers/auth.py
  // ::_require_can_administer); mirroring it here means the UI shows a
  // disabled control with a reason instead of a 403 after the click.
  const canAdministerAdmins = isSuperAdmin(currentUser?.role);
  const assignableRoles: AssignableRole[] = canAdministerAdmins
    ? ["viewer", "editor", "admin"]
    : ["viewer", "editor"];

  const [err, setErr] = useState<string | null>(null);
  const [confirmingId, setConfirmingId] = useState<number | null>(null);

  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<AssignableRole>("viewer");

  const { data: users, isLoading } = useQuery({
    queryKey: ["users"],
    queryFn: listUsers,
    enabled: isAuthenticated() && canAdminister,
  });

  const createMutation = useMutation({
    mutationFn: () => createUser({ username, password, email, role, is_active: true }),
    onSuccess: () => {
      setUsername("");
      setEmail("");
      setPassword("");
      setRole("viewer");
      setErr(null);
      void queryClient.invalidateQueries({ queryKey: ["users"] });
    },
    onError: (e) => setErr(e instanceof Error ? e.message : "Failed to create user"),
  });

  const updateMutation = useMutation({
    mutationFn: (vars: { id: number; role?: AssignableRole; is_active?: boolean }) =>
      updateUser(vars.id, { role: vars.role, is_active: vars.is_active }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["users"] }),
    onError: (e) => setErr(e instanceof Error ? e.message : "Failed to update user"),
  });

  const deactivateMutation = useMutation({
    mutationFn: (id: number) => deactivateUser(id),
    onSuccess: () => {
      setConfirmingId(null);
      void queryClient.invalidateQueries({ queryKey: ["users"] });
    },
    onError: (e) => {
      setConfirmingId(null);
      setErr(e instanceof Error ? e.message : "Failed to deactivate user");
    },
  });

  function handleCreate(e: FormEvent) {
    e.preventDefault();
    if (username.trim().length < 3 || password.length < 12 || !email.trim()) return;
    createMutation.mutate();
  }

  if (!isAuthenticated()) {
    return (
      <div>
        <PageHeader title="Users" subtitle="Platform user administration." />
        <EmptyState title="Sign in required" description="Log in to view and manage platform users." />
      </div>
    );
  }

  if (!canAdminister) {
    return (
      <div>
        <PageHeader title="Users" subtitle="Platform user administration." />
        <EmptyState
          icon={<ShieldOff className="h-6 w-6" aria-hidden />}
          title="Admin access required"
          description="Only platform admins can view and manage user accounts."
        />
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title="Users"
        subtitle={
          canAdministerAdmins
            ? "Create accounts and manage roles and active status. Global platform roles — distinct from per-organization roles on the Members page."
            : "Create accounts and manage roles and active status. Administrator accounts can only be changed by the super admin."
        }
      />

      {err ? (
        <div className="mb-4 rounded-xl border border-negative-200 bg-negative-50 px-4 py-3 text-sm text-negative-900 dark:border-negative-900 dark:bg-negative-950 dark:text-negative-200">
          {err}
        </div>
      ) : null}

      <form
        onSubmit={handleCreate}
        className="mb-6 glass-card p-4"
      >
        <h3 className="text-sm font-semibold text-ink-900 dark:text-ink-100">Create a user</h3>
        <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="Username"
            aria-label="Username"
            className="field"
          />
          <input
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            type="email"
            placeholder="Email"
            aria-label="Email"
            className="field"
          />
          <input
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            type="password"
            placeholder="Password (min 12 chars)"
            aria-label="Password"
            className="field"
          />
          <select
            value={role}
            onChange={(e) => setRole(e.target.value as AssignableRole)}
            aria-label="Role"
            className="field"
          >
            {assignableRoles.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
          <Button
            type="submit"
            disabled={createMutation.isPending || username.trim().length < 3 || password.length < 12 || !email.trim()}
          >
            <Plus className="h-4 w-4" aria-hidden />
            Create
          </Button>
        </div>
      </form>

      {isLoading ? (
        <p className="text-sm text-ink-500 dark:text-ink-400">Loading...</p>
      ) : !users || users.length === 0 ? (
        <EmptyState icon={<UserCog className="h-6 w-6" aria-hidden />} title="No users" description="Create the first account above." />
      ) : (
        <div className="overflow-x-auto glass-card">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-ink-100 text-xs uppercase tracking-wide text-ink-500 dark:border-ink-800 dark:text-ink-400">
              <tr>
                <th className="px-4 py-3">Username</th>
                <th className="px-4 py-3">Email</th>
                <th className="px-4 py-3">Role</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">MFA</th>
                <th className="px-4 py-3">Created</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-100 dark:divide-ink-800">
              {users.map((u) => {
                const isSelf = u.id === currentUser?.id;
                // The super admin is immutable for everyone, themselves
                // included — there is no account above it to undo a mistake.
                const isProtected = isSuperAdmin(u.role);
                // A plain admin may manage viewers and editors, but not peers.
                const isLockedPeer = isPlatformAdmin(u.role) && !isSelf && !canAdministerAdmins;
                // The server would accept an admin stepping themselves down;
                // the UI doesn't offer it, because the role dropdown has no
                // admin option for a non-super-admin, so the click would be
                // one-way — they could not put themselves back.
                const isOwnAdminRow = isSelf && isPlatformAdmin(u.role) && !canAdministerAdmins;
                const roleLocked = isProtected || isLockedPeer || isOwnAdminRow;
                const lockReason = isProtected
                  ? "The super admin account cannot be modified"
                  : isOwnAdminRow
                    ? "You cannot change your own admin role — ask the super admin"
                    : "Only the super admin can modify another administrator";
                return (
                  <tr key={u.id}>
                    <td className="px-4 py-3 font-medium text-ink-900 dark:text-ink-100">{u.username}</td>
                    <td className="px-4 py-3 text-ink-600 dark:text-ink-300">{u.email ?? "—"}</td>
                    <td className="px-4 py-3">
                      {/* .field is width-full by design (it's mostly used in
                          stacked forms); inline in a table the select has to
                          size to its content or it pushes the badge onto a
                          second line. */}
                      <div className="flex items-center gap-2">
                        {roleLocked ? (
                          <span className="text-ink-400 dark:text-ink-500" title={lockReason}>
                            <Lock className="h-4 w-4" aria-label={lockReason} />
                          </span>
                        ) : (
                          <select
                            value={u.role}
                            disabled={updateMutation.isPending}
                            onChange={(e) =>
                              updateMutation.mutate({ id: u.id, role: e.target.value as AssignableRole })
                            }
                            aria-label={`Role for ${u.username}`}
                            className="field !w-auto !py-1.5"
                          >
                            {assignableRoles.map((r) => (
                              <option key={r} value={r}>
                                {r}
                              </option>
                            ))}
                          </select>
                        )}
                        <Badge variant={roleVariant[u.role]}>{u.role}</Badge>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <Badge variant={u.is_active ? "ok" : "bad"}>{u.is_active ? "active" : "deactivated"}</Badge>
                    </td>
                    <td className="px-4 py-3 text-ink-500 dark:text-ink-400">{u.mfa_enabled ? "on" : "—"}</td>
                    <td className="px-4 py-3 text-ink-500 dark:text-ink-400">{new Date(u.created_at).toLocaleDateString()}</td>
                    <td className="px-4 py-3 text-right">
                      {/* isSelf first: "you cannot deactivate your own
                          account" is the accurate reason for this column,
                          and a signed-in user is never inactive. */}
                      {isSelf ? (
                        <span className="text-xs text-ink-400" title="You cannot deactivate your own account">
                          —
                        </span>
                      ) : roleLocked ? (
                        <span className="text-xs text-ink-400" title={lockReason}>
                          —
                        </span>
                      ) : !u.is_active ? (
                        // Without this a deactivated row's action cell was
                        // empty forever — deactivating was a one-way door.
                        <Button
                          variant="secondary"
                          className="px-2 py-1 text-xs"
                          disabled={updateMutation.isPending}
                          onClick={() => updateMutation.mutate({ id: u.id, is_active: true })}
                        >
                          Reactivate
                        </Button>
                      ) : confirmingId === u.id ? (
                        <div className="flex justify-end gap-2">
                          <Button
                            variant="danger"
                            className="px-2 py-1 text-xs"
                            disabled={deactivateMutation.isPending}
                            onClick={() => deactivateMutation.mutate(u.id)}
                          >
                            Confirm?
                          </Button>
                          <Button variant="ghost" className="px-2 py-1 text-xs" onClick={() => setConfirmingId(null)}>
                            Cancel
                          </Button>
                        </div>
                      ) : (
                        <Button variant="secondary" className="px-2 py-1 text-xs" onClick={() => setConfirmingId(u.id)}>
                          Deactivate
                        </Button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
