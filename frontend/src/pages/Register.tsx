import { FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { LoginResponse, apiFetch } from "@/api/client";
import { Button } from "@/components/Button";
import { useAppStore } from "@/store/appStore";

const PASSWORD_RULES = [
  { label: "At least 8 characters", test: (p: string) => p.length >= 8 },
  { label: "One uppercase letter", test: (p: string) => /[A-Z]/.test(p) },
  { label: "One lowercase letter", test: (p: string) => /[a-z]/.test(p) },
  { label: "One digit", test: (p: string) => /\d/.test(p) },
  { label: "One special character", test: (p: string) => /[!@#$%^&*()_+\-=\[\]{};':"\\|,.<>\/?`~]/.test(p) },
];

export function Register() {
  const navigate = useNavigate();
  const setTokens = useAppStore((s) => s.setTokens);
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const allPasswordRulesPass = PASSWORD_RULES.every((r) => r.test(password));
  const passwordsMatch = password === confirmPassword && confirmPassword.length > 0;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setErr(null);

    if (!allPasswordRulesPass) {
      setErr("Password does not meet all requirements");
      return;
    }
    if (!passwordsMatch) {
      setErr("Passwords do not match");
      return;
    }

    setLoading(true);
    try {
      const res = await apiFetch<LoginResponse>("/auth/register", {
        method: "POST",
        auth: false,
        body: JSON.stringify({ username, email, password }),
      });
      setTokens(res.access_token, res.refresh_token, res.user);
      navigate("/", { replace: true });
    } catch (error) {
      setErr(error instanceof Error ? error.message : "Registration failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="mx-auto mt-12 max-w-md rounded-2xl border border-slate-200 bg-white p-6 shadow-card dark:border-slate-700 dark:bg-slate-900">
      <h1 className="text-xl font-semibold text-slate-900 dark:text-slate-100">Create account</h1>
      <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">Register for an API Security Monitor account.</p>
      <form onSubmit={submit} className="mt-4 space-y-4">
        <div>
          <label className="mb-1 block text-xs font-medium text-slate-700 dark:text-slate-300">Username</label>
          <input
            className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="johndoe"
            minLength={3}
            maxLength={128}
            pattern="^[a-zA-Z0-9_\-\.]+$"
            required
          />
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-slate-700 dark:text-slate-300">Email</label>
          <input
            type="email"
            className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
            required
          />
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-slate-700 dark:text-slate-300">Password</label>
          <input
            type="password"
            className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Strong password"
            required
          />
          {password.length > 0 && (
            <ul className="mt-2 space-y-1">
              {PASSWORD_RULES.map((rule) => (
                <li
                  key={rule.label}
                  className={`text-xs flex items-center gap-1.5 ${rule.test(password) ? "text-emerald-600" : "text-slate-400"}`}
                >
                  <span>{rule.test(password) ? "\u2713" : "\u2022"}</span>
                  {rule.label}
                </li>
              ))}
            </ul>
          )}
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-slate-700 dark:text-slate-300">Confirm password</label>
          <input
            type="password"
            className="w-full rounded-lg border border-slate-200 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            placeholder="Repeat password"
            required
          />
          {confirmPassword.length > 0 && !passwordsMatch && (
            <p className="mt-1 text-xs text-rose-500">Passwords do not match</p>
          )}
        </div>
        {err ? <p className="text-sm text-rose-600">{err}</p> : null}
        <Button
          type="submit"
          className="w-full"
          disabled={loading || !allPasswordRulesPass || !passwordsMatch}
        >
          {loading ? "Creating account..." : "Create account"}
        </Button>
      </form>
      <p className="mt-4 text-center text-sm text-slate-500 dark:text-slate-400">
        Already have an account?{" "}
        <Link to="/login" className="font-medium text-brand-600 hover:text-brand-700 dark:text-brand-400">
          Sign in
        </Link>
      </p>
    </div>
  );
}
