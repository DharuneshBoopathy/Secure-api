import { Shield } from "lucide-react";
import { FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { LoginResponse, apiFetch } from "@/api/client";
import { Button } from "@/components/Button";
import { useAppStore } from "@/store/appStore";

export function Login() {
  const navigate = useNavigate();
  const setTokens = useAppStore((s) => s.setTokens);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setErr(null);
    setLoading(true);
    try {
      const res = await apiFetch<LoginResponse>("/auth/login", {
        method: "POST",
        auth: false,
        body: JSON.stringify({ username, password }),
      });
      setTokens(res.access_token, res.refresh_token, res.user);
      void navigate("/", { replace: true });
    } catch (error) {
      setErr(error instanceof Error ? error.message : "Login failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    // Login renders outside <Layout>, so it carries its own ambient ground —
    // without it the frosted card has nothing to refract and reads as a plain
    // white box.
    <div className="bg-ambient flex min-h-screen items-center justify-center px-4">
      <div className="glass-card w-full max-w-md p-8 animate-fade-rise">
        <div className="sheen mb-5 flex h-11 w-11 items-center justify-center rounded-2xl bg-accent-500 text-white shadow-glow">
          <Shield className="h-5 w-5" aria-hidden strokeWidth={1.75} />
        </div>
        <h1 className="font-display text-3xl tracking-[-0.02em] text-ink-900 dark:text-ink-50">Sign in</h1>
        <p className="mt-1.5 text-sm text-ink-600 dark:text-ink-400">Use your monitor account credentials.</p>
        <form onSubmit={(e) => void submit(e)} className="mt-6 space-y-4">
        <input
          className="w-full field dark:text-ink-100"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          placeholder="Username"
        />
        <input
          type="password"
          className="w-full field dark:text-ink-100"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Password"
        />
        {err ? <p className="text-sm text-negative-600">{err}</p> : null}
        <Button type="submit" className="w-full" disabled={loading}>
          {loading ? "Signing in..." : "Sign in"}
        </Button>
      </form>
        <p className="mt-6 text-center text-sm text-ink-600 dark:text-ink-400">
          Don't have an account?{" "}
          <Link to="/register" className="font-medium text-accent-600 hover:text-accent-700 dark:text-accent-300">
            Create one
          </Link>
        </p>
      </div>
    </div>
  );
}
