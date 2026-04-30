import { create } from "zustand";

const ACCESS_TOKEN_KEY = "apimonitor_access_token";
const REFRESH_TOKEN_KEY = "apimonitor_refresh_token";
const USER_KEY = "apimonitor_user";
const THEME_KEY = "apimonitor_theme";

type Theme = "light" | "dark";

export type UserInfo = {
  id: number;
  username: string;
  email: string | null;
  role: string;
  is_active: boolean;
};

type AppState = {
  accessToken: string;
  refreshToken: string;
  user: UserInfo | null;
  theme: Theme;
  setTokens: (accessToken: string, refreshToken: string, user?: UserInfo | null) => void;
  setUser: (user: UserInfo | null) => void;
  clearTokens: () => void;
  setTheme: (theme: Theme) => void;
  hydrate: () => void;
};

export const useAppStore = create<AppState>((set) => ({
  accessToken: "",
  refreshToken: "",
  user: null,
  theme: "light",
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
  hydrate: () => {
    const accessToken = localStorage.getItem(ACCESS_TOKEN_KEY) ?? "";
    const refreshToken = localStorage.getItem(REFRESH_TOKEN_KEY) ?? "";
    const theme = (localStorage.getItem(THEME_KEY) as Theme | null) ?? "light";
    let user: UserInfo | null = null;
    try {
      const raw = localStorage.getItem(USER_KEY);
      if (raw) user = JSON.parse(raw);
    } catch {
      /* ignore */
    }
    if (theme === "dark") document.documentElement.classList.add("dark");
    else document.documentElement.classList.remove("dark");
    set({ accessToken, refreshToken, theme, user });
  },
}));
