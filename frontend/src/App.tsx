import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
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

export default function App() {
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
