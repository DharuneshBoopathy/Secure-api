import {
  Activity,
  AlertTriangle,
  Bell,
  BookOpen,
  CloudOff,
  DatabaseZap,
  LayoutDashboard,
  ListTree,
  Menu,
  Moon,
  Plug,
  Settings,
  Shield,
  Sun,
  Users as UsersIcon,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { OrgSwitcher } from "@/components/OrgSwitcher";
import { ToastHost } from "@/components/ToastHost";
import { useAlertToasts } from "@/hooks/useAlertToasts";
import { useAppStore } from "@/store/appStore";

const nav = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/alerts", label: "Alerts", icon: AlertTriangle },
  { to: "/shadow", label: "Shadow APIs", icon: CloudOff },
  { to: "/discovered", label: "All discovered", icon: ListTree },
  { to: "/idle", label: "Idle routes", icon: Activity },
  { to: "/connections", label: "Connected APIs", icon: Plug },
  { to: "/registry", label: "OpenAPI registry", icon: BookOpen },
  { to: "/traffic", label: "Live traffic", icon: Bell },
  { to: "/zombie", label: "Zombie APIs", icon: Activity },
  { to: "/anomalies", label: "Anomalies", icon: DatabaseZap },
  { to: "/audit", label: "Audit log", icon: ListTree },
  { to: "/members", label: "Members", icon: UsersIcon },
  { to: "/users", label: "Users", icon: UsersIcon },
  { to: "/settings", label: "Settings", icon: Settings },
];

export function Layout() {
  const theme = useAppStore((s) => s.theme);
  const setTheme = useAppStore((s) => s.setTheme);
  const clearTokens = useAppStore((s) => s.clearTokens);
  const user = useAppStore((s) => s.user);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const location = useLocation();

  // Push a toast for every alert while the app is mounted, regardless of
  // which page is active — this is the one place in the tree guaranteed to
  // be alive the whole session, so it's where the SSE subscription lives.
  useAlertToasts();

  // A route change is the clearest signal the user picked something from
  // the nav — close the mobile drawer so it doesn't cover the new page.
  useEffect(() => {
    setMobileNavOpen(false);
  }, [location.pathname]);

  return (
    // The ambient wash lives on the outermost element so every frosted panel
    // in the tree has colour variation to refract — backdrop-blur over a flat
    // fill is indistinguishable from plain opacity.
    <div className="bg-ambient flex min-h-screen">
      <ToastHost />

      {/* Mobile top bar: only the sidebar is hidden below md, not this —
          without it there would be no way to open the nav on a phone. */}
      <div className="glass-strong fixed inset-x-0 top-0 z-20 flex h-14 items-center gap-3 rounded-none border-x-0 border-t-0 px-4 md:hidden">
        <button
          type="button"
          onClick={() => setMobileNavOpen((v) => !v)}
          aria-label={mobileNavOpen ? "Close navigation menu" : "Open navigation menu"}
          aria-expanded={mobileNavOpen}
          className="rounded-full p-2 text-ink-700 transition hover:bg-ink-900/[0.06] focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-500/50 dark:text-ink-300 dark:hover:bg-white/[0.08]"
        >
          {mobileNavOpen ? <X className="h-5 w-5" aria-hidden /> : <Menu className="h-5 w-5" aria-hidden />}
        </button>
        <div className="sheen flex h-8 w-8 items-center justify-center rounded-xl bg-accent-500 text-white">
          <Shield className="h-4 w-4" aria-hidden />
        </div>
        <p className="text-sm font-semibold text-ink-900 dark:text-ink-50">API Security Monitor</p>
      </div>

      {/* Backdrop, mobile only, closes the drawer on outside-tap. */}
      {mobileNavOpen ? (
        <div
          className="fixed inset-0 z-20 bg-ink-950/40 backdrop-blur-sm md:hidden"
          onClick={() => setMobileNavOpen(false)}
          aria-hidden
        />
      ) : null}

      <aside
        className={[
          "glass fixed inset-y-0 left-0 z-30 flex w-64 flex-col rounded-none border-y-0 border-l-0 transition-transform duration-300 ease-out",
          mobileNavOpen ? "translate-x-0" : "-translate-x-full",
          "md:translate-x-0",
        ].join(" ")}
      >
        <div className="hairline flex h-16 items-center gap-2.5 border-b px-5">
          <div className="sheen flex h-9 w-9 items-center justify-center rounded-xl bg-accent-500 text-white shadow-glow">
            <Shield className="h-5 w-5" aria-hidden strokeWidth={1.75} />
          </div>
          <div>
            <p className="font-display text-base leading-tight text-ink-900 dark:text-ink-50">API Security</p>
            <p className="text-[11px] uppercase tracking-widest text-ink-500 dark:text-ink-400">Monitor</p>
          </div>
        </div>
        <OrgSwitcher />
        <nav className="flex-1 space-y-0.5 overflow-y-auto p-3">
          {nav.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                [
                  "flex items-center gap-3 rounded-full px-3.5 py-2.5 text-sm font-medium transition-all duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent-500/50",
                  isActive
                    ? "bg-accent-500/12 text-accent-600 ring-1 ring-inset ring-accent-500/20 dark:text-accent-200"
                    : "text-ink-600 hover:bg-ink-900/[0.05] hover:text-ink-900 dark:text-ink-400 dark:hover:bg-white/[0.07] dark:hover:text-ink-50",
                ].join(" ")
              }
            >
              <Icon className="h-[18px] w-[18px] shrink-0" strokeWidth={1.75} aria-hidden />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="hairline border-t p-4 text-xs text-ink-500 dark:text-ink-400">
          {user ? (
            <div className="mb-3 flex items-center gap-2">
              <span className="truncate font-medium text-ink-700 dark:text-ink-300">{user.username}</span>
              <span className="rounded-full bg-accent-500/12 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-accent-600 ring-1 ring-inset ring-accent-500/20 dark:text-accent-200">
                {user.role}
              </span>
            </div>
          ) : null}
          <div className="mb-3 flex gap-2">
            <button
              type="button"
              onClick={() => setTheme(theme === "light" ? "dark" : "light")}
              aria-label={theme === "light" ? "Switch to dark theme" : "Switch to light theme"}
              className="rounded-full border p-2 transition hover:bg-ink-900/[0.06] focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-500/50 dark:hover:bg-white/[0.08] hairline"
            >
              {theme === "light" ? <Moon className="h-3.5 w-3.5" aria-hidden /> : <Sun className="h-3.5 w-3.5" aria-hidden />}
            </button>
            <button
              type="button"
              onClick={clearTokens}
              className="hairline rounded-full border px-3 py-1 transition hover:bg-ink-900/[0.06] focus:outline-none focus-visible:ring-2 focus-visible:ring-accent-500/50 dark:hover:bg-white/[0.08]"
            >
              Logout
            </button>
          </div>
          Gateway inventory · anomaly scoring · drift alerts
        </div>
      </aside>
      {/* min-w-0: a flex child defaults to min-width:auto, so a wide table
          stretches this column instead of scrolling inside its own
          overflow-x-auto wrapper — which pushed the whole page sideways on
          every table view (Users, Anomalies, Audit, Connected APIs). */}
      <div className="flex min-w-0 flex-1 flex-col pt-14 md:pl-64 md:pt-0">
        <main className="relative flex-1 bg-grid">
          <div className="relative mx-auto max-w-6xl px-4 py-6 sm:px-6 sm:py-8 lg:px-10">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}
