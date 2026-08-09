import { create } from "zustand";

const ACCESS_TOKEN_KEY = "apimonitor_access_token";
const REFRESH_TOKEN_KEY = "apimonitor_refresh_token";
const USER_KEY = "apimonitor_user";
const THEME_KEY = "apimonitor_theme";
const ORG_ID_KEY = "apimonitor_org_id";

type Theme = "light" | "dark";

export type UserInfo = {
  id: number;
  username: string;
  email: string | null;
  role: string;
  is_active: boolean;
};

export type ToastItem = {
  id: number;
  title: string;
  description?: string;
  variant: "info" | "warn" | "bad";
  href?: string;
};

let nextToastId = 1;

type AppState = {
  accessToken: string;
  refreshToken: string;
  user: UserInfo | null;
  theme: Theme;
  currentOrgId: number | null;
  toasts: ToastItem[];
  setTokens: (accessToken: string, refreshToken: string, user?: UserInfo | null) => void;
  setUser: (user: UserInfo | null) => void;
  clearTokens: () => void;
  setTheme: (theme: Theme) => void;
  setCurrentOrgId: (orgId: number | null) => void;
  pushToast: (toast: Omit<ToastItem, "id">) => number;
  dismissToast: (id: number) => void;
  hydrate: () => void;
};

export const useAppStore = create<AppState>((set) => ({
  accessToken: "",
  refreshToken: "",
  user: null,
  theme: "light",
  currentOrgId: null,
  toasts: [],
  setTokens: (accessToken, refreshToken, user) => {
    localStorage.setItem(ACCESS_TOKEN_KEY, accessToken);
    localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
    if (user) {
      localStorage.setItem(USER_KEY, JSON.stringify(user));
    }
    set({ accessToken, refreshToken, ...(user !== undefined ? { user } : {}) });
  },
  setUser: (user) => {
    if (user) {
      localStorage.setItem(USER_KEY, JSON.stringify(user));
    } else {
      localStorage.removeItem(USER_KEY);
    }
    set({ user });
  },
  clearTokens: () => {
    localStorage.removeItem(ACCESS_TOKEN_KEY);
    localStorage.removeItem(REFRESH_TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    set({ accessToken: "", refreshToken: "", user: null });
  },
  setTheme: (theme) => {
    localStorage.setItem(THEME_KEY, theme);
    set({ theme });
    if (theme === "dark") document.documentElement.classList.add("dark");
    else document.documentElement.classList.remove("dark");
  },
  setCurrentOrgId: (orgId) => {
    if (orgId === null) localStorage.removeItem(ORG_ID_KEY);
    else localStorage.setItem(ORG_ID_KEY, String(orgId));
    set({ currentOrgId: orgId });
  },
  pushToast: (toast) => {
    const id = nextToastId++;
    set((state) => ({ toasts: [...state.toasts, { ...toast, id }] }));
    return id;
  },
  dismissToast: (id) => {
    set((state) => ({ toasts: state.toasts.filter((t) => t.id !== id) }));
  },
  hydrate: () => {
    const accessToken = localStorage.getItem(ACCESS_TOKEN_KEY) ?? "";
    const refreshToken = localStorage.getItem(REFRESH_TOKEN_KEY) ?? "";
    const theme = (localStorage.getItem(THEME_KEY) as Theme | null) ?? "light";
    const rawOrgId = localStorage.getItem(ORG_ID_KEY);
    const currentOrgId = rawOrgId && Number.isFinite(Number(rawOrgId)) ? Number(rawOrgId) : null;
    let user: UserInfo | null = null;
    try {
      const raw = localStorage.getItem(USER_KEY);
      if (raw) user = JSON.parse(raw);
    } catch {
      /* ignore */
    }
    if (theme === "dark") document.documentElement.classList.add("dark");
    else document.documentElement.classList.remove("dark");
    set({ accessToken, refreshToken, theme, user, currentOrgId });
  },
}));
