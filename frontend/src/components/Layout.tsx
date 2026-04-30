import {
  Activity,
  AlertTriangle,
  Bell,
  BookOpen,
  CloudOff,
  DatabaseZap,
  LayoutDashboard,
  ListTree,
  Moon,
  Settings,
  Shield,
  Sun,
} from "lucide-react";
import { NavLink, Outlet } from "react-router-dom";
import { useAppStore } from "@/store/appStore";

const nav = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/alerts", label: "Alerts", icon: AlertTriangle },
  { to: "/shadow", label: "Shadow APIs", icon: CloudOff },
  { to: "/discovered", label: "All discovered", icon: ListTree },
  { to: "/idle", label: "Idle routes", icon: Activity },
  { to: "/registry", label: "OpenAPI registry", icon: BookOpen },
  { to: "/traffic", label: "Live traffic", icon: Bell },
  { to: "/zombie", label: "Zombie APIs", icon: Activity },
  { to: "/anomalies", label: "Anomalies", icon: DatabaseZap },
  { to: "/audit", label: "Audit log", icon: ListTree },
  { to: "/settings", label: "Settings", icon: Settings },
];

export function Layout() {
  const theme = useAppStore((s) => s.theme);
  const setTheme = useAppStore((s) => s.setTheme);
  const clearTokens = useAppStore((s) => s.clearTokens);
  return (
    <div className="flex min-h-screen dark:bg-slate-950">
      <aside className="fixed inset-y-0 left-0 z-30 flex w-64 flex-col border-r border-slate-200/80 bg-white shadow-card dark:border-slate-800 dark:bg-slate-900">
        <div className="flex h-16 items-center gap-2 border-b border-slate-100 px-5">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-600 text-white shadow-sm">
            <Shield className="h-5 w-5" aria-hidden />
          </div>
          <div>
            <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">API Security</p>
            <p className="text-xs text-slate-500 dark:text-slate-400">Monitor</p>
          </div>
        </div>
        <nav className="flex-1 space-y-0.5 p-3">
          {nav.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                [
                  "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors",
                  isActive
                    ? "bg-brand-50 text-brand-800 ring-1 ring-brand-200/60 dark:bg-brand-950 dark:text-brand-200 dark:ring-brand-900"
                    : "text-slate-600 hover:bg-slate-50 hover:text-slate-900 dark:text-slate-300 dark:hover:bg-slate-800 dark:hover:text-slate-100",
                ].join(" ")
              }
            >
              <Icon className="h-5 w-5 shrink-0 opacity-80" strokeWidth={2} />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-slate-100 p-4 text-xs text-slate-400 dark:border-slate-800 dark:text-slate-500">
          {(() => {
            const user = useAppStore((s) => s.user);
            return user ? (
              <div className="mb-2 flex items-center gap-2">
                <span className="truncate font-medium text-slate-600 dark:text-slate-300">{user.username}</span>
                <span className="rounded-full bg-brand-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-brand-700 dark:bg-brand-900 dark:text-brand-300">{user.role}</span>
              </div>
            ) : null;
          })()}
          <div className="mb-2 flex gap-2">
            <button
              type="button"
              onClick={() => setTheme(theme === "light" ? "dark" : "light")}
              className="rounded-md border border-slate-200 px-2 py-1 dark:border-slate-700"
            >
              {theme === "light" ? <Moon className="h-3.5 w-3.5" /> : <Sun className="h-3.5 w-3.5" />}
            </button>
            <button
              type="button"
              onClick={clearTokens}
              className="rounded-md border border-slate-200 px-2 py-1 dark:border-slate-700"
            >
              Logout
            </button>
          </div>
          Gateway inventory · anomaly scoring · drift alerts
        </div>
      </aside>
      <div className="flex flex-1 flex-col pl-64">
        <main className="relative flex-1 bg-grid">
          <div className="pointer-events-none absolute inset-0 bg-gradient-to-b from-white/80 via-transparent to-slate-50/90" />
          <div className="relative mx-auto max-w-6xl px-6 py-8 lg:px-10">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
