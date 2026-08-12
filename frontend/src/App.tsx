import { useEffect } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { getMe, isAuthenticated } from "@/api/client";
import { Layout } from "@/components/Layout";
import { Alerts } from "@/pages/Alerts";
import { Anomalies } from "@/pages/Anomalies";
import { Audit } from "@/pages/Audit";
import { Connections } from "@/pages/Connections";
import { Dashboard } from "@/pages/Dashboard";
import { Discovered } from "@/pages/Discovered";
import { Idle } from "@/pages/Idle";
import { Login } from "@/pages/Login";
import { Members } from "@/pages/Members";
import { Register } from "@/pages/Register";
import { Registry } from "@/pages/Registry";
import { Settings } from "@/pages/Settings";
import { Shadow } from "@/pages/Shadow";
import { Traffic } from "@/pages/Traffic";
import { Users } from "@/pages/Users";
import { Zombie } from "@/pages/Zombie";
import { useAppStore } from "@/store/appStore";

function RequireAuth({ children }: { children: React.ReactNode }) {
  const token = useAppStore((s) => s.accessToken);
  const fallbackApiKey = localStorage.getItem("apimonitor_api_key") ?? "";
  if (!token && !fallbackApiKey) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

/** Re-read the caller's own profile once per app load.
 *
 * The store caches `user` from the login response and never updates it, so a
 * role change or a deactivation was invisible to an open tab until the user
 * happened to log out and back in — which is exactly when it matters most.
 * Failures are ignored on purpose: apiFetch already redirects on a dead
 * session, and a transient error here must not blank out a working session. */
function useSyncCurrentUser() {
  const setUser = useAppStore((s) => s.setUser);
  useEffect(() => {
    if (!isAuthenticated()) return;
    getMe()
      .then(setUser)
      .catch(() => undefined);
  }, [setUser]);
}

export default function App() {
  useSyncCurrentUser();
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route
          element={
            <RequireAuth>
              <Layout />
            </RequireAuth>
          }
        >
          <Route path="/" element={<Dashboard />} />
          <Route path="/alerts" element={<Alerts />} />
          <Route path="/shadow" element={<Shadow />} />
          <Route path="/discovered" element={<Discovered />} />
          <Route path="/idle" element={<Idle />} />
          <Route path="/members" element={<Members />} />
          <Route path="/registry" element={<Registry />} />
          <Route path="/connections" element={<Connections />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/traffic" element={<Traffic />} />
          <Route path="/zombie" element={<Zombie />} />
          <Route path="/anomalies" element={<Anomalies />} />
          <Route path="/audit" element={<Audit />} />
          <Route path="/users" element={<Users />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
