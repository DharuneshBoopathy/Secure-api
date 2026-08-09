import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, ShieldOff, UserCog } from "lucide-react";
import { FormEvent, useState } from "react";
import { createUser, deactivateUser, isAuthenticated, listUsers, updateUser, type UserRow } from "@/api/client";
import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { useAppStore } from "@/store/appStore";

const roleVariant: Record<UserRow["role"], "neutral" | "ok" | "warn" | "bad" | "info"> = {
  admin: "info",
  editor: "ok",
  viewer: "neutral",
};

export function Users() {
  const currentUser = useAppStore((s) => s.user);
  const queryClient = useQueryClient();

  const [err, setErr] = useState<string | null>(null);
  const [confirmingId, setConfirmingId] = useState<number | null>(null);

  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<UserRow["role"]>("viewer");

  const { data: users, isLoading } = useQuery({
    queryKey: ["users"],
    queryFn: listUsers,
    enabled: isAuthenticated() && currentUser?.role === "admin",
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
    mutationFn: (vars: { id: number; role?: UserRow["role"] }) => updateUser(vars.id, { role: vars.role }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["users"] }),
    onError: (e) => setErr(e instanceof Error ? e.message : "Failed to update role"),
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

  if (currentUser?.role !== "admin") {
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
        subtitle="Create accounts and manage roles and active status. Global platform roles — distinct from per-organization roles on the Members page."
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
            onChange={(e) => setRole(e.target.value as UserRow["role"])}
            aria-label="Role"
            className="field"
          >
            <option value="viewer">viewer</option>
            <option value="editor">editor</option>
            <option value="admin">admin</option>
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
                        <select
                          value={u.role}
                          disabled={updateMutation.isPending}
                          onChange={(e) => updateMutation.mutate({ id: u.id, role: e.target.value as UserRow["role"] })}
                          aria-label={`Role for ${u.username}`}
                          className="field !w-auto !py-1.5"
                        >
                          <option value="viewer">viewer</option>
                          <option value="editor">editor</option>
                          <option value="admin">admin</option>
                        </select>
                        <Badge variant={roleVariant[u.role]}>{u.role}</Badge>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <Badge variant={u.is_active ? "ok" : "bad"}>{u.is_active ? "active" : "deactivated"}</Badge>
                    </td>
                    <td className="px-4 py-3 text-ink-500 dark:text-ink-400">{u.mfa_enabled ? "on" : "—"}</td>
                    <td className="px-4 py-3 text-ink-500 dark:text-ink-400">{new Date(u.created_at).toLocaleDateString()}</td>
                    <td className="px-4 py-3 text-right">
                      {!u.is_active ? null : isSelf ? (
                        <span className="text-xs text-ink-400" title="You cannot deactivate your own account">
                          —
                        </span>
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
