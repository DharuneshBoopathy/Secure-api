import { useAppStore, type UserInfo } from "@/store/appStore";

const KEY_STORAGE = "apimonitor_api_key";

/** Backend REST routes live under /api (same origin when UI is served from FastAPI). */
const API_PREFIX = "/api";

export function getApiKey(): string {
  return localStorage.getItem(KEY_STORAGE) ?? "";
}

export function setApiKey(key: string): void {
  localStorage.setItem(KEY_STORAGE, key.trim());
}

export function getAccessToken(): string {
  return localStorage.getItem("apimonitor_access_token") ?? "";
}

/** Returns true when the user has either a JWT access token or a legacy API key. */
export function isAuthenticated(): boolean {
  return !!(getAccessToken() || getApiKey());
}

function getRefreshToken(): string {
  return localStorage.getItem("apimonitor_refresh_token") ?? "";
}

export class ApiError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

async function parseError(res: Response): Promise<string> {
  try {
    const j = await res.json();
    if (typeof j?.detail === "string") return j.detail;
    if (Array.isArray(j?.detail)) return j.detail.map((x: { msg?: string }) => x.msg).join("; ");
    return res.statusText;
  } catch {
    return res.statusText;
  }
}

/* —— Automatic token refresh —— */

let refreshPromise: Promise<boolean> | null = null;

async function tryRefreshToken(): Promise<boolean> {
  const refreshToken = getRefreshToken();
  if (!refreshToken) return false;

  // Dedupe: if a refresh is already in flight, wait for it
  if (refreshPromise) return refreshPromise;

  refreshPromise = (async () => {
    try {
      const res = await fetch(`${API_PREFIX}/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
      if (!res.ok) {
        // Refresh failed — clear tokens and redirect to login
        useAppStore.getState().clearTokens();
        return false;
      }
      const data = (await res.json()) as LoginResponse;
      const user: UserInfo | null = data.user ?? null;
      useAppStore.getState().setTokens(data.access_token, data.refresh_token, user);
      return true;
    } catch {
      return false;
    } finally {
      refreshPromise = null;
    }
  })();

  return refreshPromise;
}


export async function apiFetch<T>(
  path: string,
  init: RequestInit & { auth?: boolean; public?: boolean; _retried?: boolean } = {},
): Promise<T> {
  const { auth = true, public: isPublic = false, _retried = false, headers: h, ...rest } = init;
  const headers = new Headers(h);
  if (auth) {
    const accessToken = getAccessToken();
    if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
    const key = getApiKey();
    if (!accessToken && key) headers.set("X-Monitor-Key", key);
  }
  if (!headers.has("Content-Type") && rest.body && typeof rest.body === "string") {
    headers.set("Content-Type", "application/json");
  }
  const url = isPublic ? path : `${API_PREFIX}${path.startsWith("/") ? path : `/${path}`}`;
  const res = await fetch(url, { ...rest, headers });

  // Auto-refresh on 401 (only once per request)
  if (res.status === 401 && auth && !_retried) {
    const refreshed = await tryRefreshToken();
    if (refreshed) {
      return apiFetch<T>(path, { ...init, _retried: true });
    }
    // Refresh failed — redirect to login
    window.location.href = "/login";
    throw new ApiError(401, "Session expired");
  }

  if (!res.ok) {
    throw new ApiError(res.status, await parseError(res));
  }
  if (res.status === 204) return undefined as T;
  const ct = res.headers.get("content-type");
  if (ct?.includes("application/json")) return (await res.json()) as T;
  return (await res.text()) as T;
}

/* —— Types aligned with FastAPI —— */

export type Stats = {
  events_last_hour: number;
  discovered_undocumented: number;
  open_alerts: number;
  known_endpoints: number;
};

export type AlertRow = {
  id: number;
  created_at: string;
  alert_type: string;
  severity: string;
  title: string;
  detail: string;
  method: string | null;
  path: string | null;
  acknowledged: boolean;
};

export type DiscoveredRow = {
  method: string;
  path_normalized: string;
  first_seen: string;
  last_seen: string;
  hit_count: number;
  documented: boolean;
};

export type IdleRow = {
  method: string;
  path_template: string;
  last_traffic: string | null;
  hours_since_traffic: number | null;
};

/** Backend returns `{ snapshot: null }` or a flat object when a snapshot exists. */
export type LatestOpenApiResponse =
  | { snapshot: null }
  | { id: number; created_at: string; title: string; version: string | null };

export type LoginResponse = {
  access_token: string;
  refresh_token: string;
  expires_in: number;
  user: UserInfo;
};

export type ShadowRow = {
  id: number;
  method: string;
  path_normalized: string;
  first_seen: string;
  last_seen: string;
  hit_count: number;
  risk_score: number;
  risk_level: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  sample_ips: string[];
  acknowledged: boolean;
};

export type ZombieRow = {
  id: number;
  method: string;
  path_template: string;
  last_request_at: string | null;
  requests_7d: number;
  requests_14d: number;
  requests_30d: number;
  avg_daily_requests_30d: number;
  status: "ACTIVE" | "DECLINING" | "IDLE" | "ZOMBIE" | "DEAD" | "RETIRED";
  risk_level: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  retired: boolean;
};

export type Paginated<T> = {
  items: T[];
  total: number;
  page: number;
  page_size: number;
};

export type TrafficEventOut = {
  id: number;
  ts: string;
  method: string;
  path: string;
  status_code: number;
  source_ip: string | null;
  response_time_ms: number;
  request_size_bytes: number;
  response_size_bytes: number;
  user_agent: string | null;
  content_type: string | null;
  x_forwarded_for: string | null;
  referer: string | null;
  monitor_key: string | null;
  session_id: string | null;
  anomaly_score: number | null;
  is_anomaly: boolean;
  anomaly_features: Record<string, unknown>;
};
