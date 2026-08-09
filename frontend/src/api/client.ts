import { useAppStore, type UserInfo } from "@/store/appStore";

const KEY_STORAGE = "apimonitor_api_key";
const ORG_ID_STORAGE = "apimonitor_org_id";

/** Backend REST routes live under /api (same origin when UI is served from FastAPI). */
const API_PREFIX = "/api";

export function getApiKey(): string {
  return localStorage.getItem(KEY_STORAGE) ?? "";
}

export function setApiKey(key: string): void {
  localStorage.setItem(KEY_STORAGE, key.trim());
}

/** Which organization org-scoped requests act on — see the X-Org-Id header
 * in the backend's app/deps.py::get_org_context. Falls back server-side to
 * the caller's sole membership when unset, so this can legitimately be
 * null for a user who hasn't picked an org yet. */
export function getCurrentOrgId(): number | null {
  const raw = localStorage.getItem(ORG_ID_STORAGE);
  if (!raw) return null;
  const n = Number(raw);
  return Number.isFinite(n) ? n : null;
}

export function setCurrentOrgId(orgId: number | null): void {
  if (orgId === null) {
    localStorage.removeItem(ORG_ID_STORAGE);
  } else {
    localStorage.setItem(ORG_ID_STORAGE, String(orgId));
  }
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
    const orgId = getCurrentOrgId();
    if (orgId !== null) headers.set("X-Org-Id", String(orgId));
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

/** One day of the traffic-volume series. Backed by traffic_events for recent
 * days and traffic_daily_summary for days past the raw-retention window —
 * see app/routers/inventory.py::traffic_trend. */
export type TrafficTrendPoint = {
  day: string;
  requests: number;
  errors: number;
};

export function getTrafficTrend(days = 30): Promise<TrafficTrendPoint[]> {
  return apiFetch<TrafficTrendPoint[]>(`/inventory/traffic-trend?days=${days}`);
}

export type AlertExplanationFeature = {
  feature: string;
  value: number;
  baseline_mean: number;
  z_score: number;
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
  event_id: number | null;
  explanation: AlertExplanationFeature[] | null;
  feedback: "true_positive" | "false_positive" | null;
  feedback_at: string | null;
};

export function listAlerts(openOnly: boolean): Promise<AlertRow[]> {
  return apiFetch<AlertRow[]>(`/alerts?open_only=${openOnly}`);
}

export function ackAlert(id: number): Promise<{ id: number; acknowledged: boolean }> {
  return apiFetch(`/alerts/${id}/ack`, { method: "POST" });
}

export function submitAlertFeedback(
  id: number,
  label: "true_positive" | "false_positive",
): Promise<{ id: number; feedback: string }> {
  return apiFetch(`/alerts/${id}/feedback`, { method: "POST", body: JSON.stringify({ label }) });
}

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

/* —— Organizations —— */

export type OrgRow = {
  id: number;
  name: string;
  slug: string;
  owner_user_id: number;
  created_at: string;
  my_role: "owner" | "editor" | "viewer" | null;
};

export type OrgMembershipRow = {
  id: number;
  user_id: number;
  username: string;
  org_id: number;
  role: "owner" | "editor" | "viewer";
  status: "pending" | "active" | "revoked";
  created_at: string;
  decided_at: string | null;
};

export function listMyOrgs(): Promise<OrgRow[]> {
  return apiFetch<OrgRow[]>("/orgs");
}

export function createOrg(name: string): Promise<OrgRow> {
  return apiFetch<OrgRow>("/orgs", { method: "POST", body: JSON.stringify({ name }) });
}

export function requestToJoinOrg(orgId: number): Promise<OrgMembershipRow> {
  return apiFetch<OrgMembershipRow>(`/orgs/${orgId}/join-requests`, { method: "POST" });
}

export function listOrgMembers(orgId: number, status?: string): Promise<OrgMembershipRow[]> {
  const q = status ? `?status=${encodeURIComponent(status)}` : "";
  return apiFetch<OrgMembershipRow[]>(`/orgs/${orgId}/members${q}`);
}

export function approveOrgMember(orgId: number, userId: number): Promise<OrgMembershipRow> {
  return apiFetch<OrgMembershipRow>(`/orgs/${orgId}/members/${userId}/approve`, { method: "POST" });
}

export function rejectOrgMember(orgId: number, userId: number): Promise<{ rejected: boolean }> {
  return apiFetch<{ rejected: boolean }>(`/orgs/${orgId}/members/${userId}/reject`, { method: "POST" });
}

export function updateOrgMemberRole(orgId: number, userId: number, role: string): Promise<OrgMembershipRow> {
  return apiFetch<OrgMembershipRow>(`/orgs/${orgId}/members/${userId}`, {
    method: "PATCH",
    body: JSON.stringify({ role }),
  });
}

export function removeOrgMember(orgId: number, userId: number): Promise<void> {
  return apiFetch<void>(`/orgs/${orgId}/members/${userId}`, { method: "DELETE" });
}

export function renameOrg(orgId: number, name: string): Promise<OrgRow> {
  return apiFetch<OrgRow>(`/orgs/${orgId}`, { method: "PATCH", body: JSON.stringify({ name }) });
}

export function transferOrgOwnership(orgId: number, newOwnerUserId: number): Promise<OrgRow> {
  return apiFetch<OrgRow>(`/orgs/${orgId}/transfer-ownership`, {
    method: "POST",
    body: JSON.stringify({ new_owner_user_id: newOwnerUserId }),
  });
}

/* —— Server-sent events —— */

/** Exchange the header credential this request already carries for a
 * short-lived, stream-only ticket. Only the ticket ever appears in a URL —
 * see app/security.py::create_stream_ticket for why that matters. */
export function getStreamTicket(): Promise<{ ticket: string; expires_in: number }> {
  return apiFetch<{ ticket: string; expires_in: number }>("/auth/stream-ticket", { method: "POST" });
}

/* —— Connected APIs (onboarding by key, /api/connections) —— */

/** One entry of the backend's built-in provider catalog. The key format hint
 * and endpoint count are served rather than duplicated here so the picker
 * can't drift from app/services/provider_catalog.py. */
export type ProviderRow = {
  id: string;
  label: string;
  base_url: string;
  key_hint: string;
  docs_url: string | null;
  endpoint_count: number;
  requires_base_url: boolean;
};

export type ConnectionStatus = "unverified" | "active" | "invalid" | "error";

export type ConnectionRow = {
  id: number;
  name: string;
  provider: string;
  provider_label: string;
  base_url: string;
  /** Prefix + last 4 only — the full key never leaves the server. */
  key_masked: string;
  endpoints_registered: number;
  status: ConnectionStatus;
  last_checked_at: string | null;
  last_check_detail: string | null;
  created_at: string;
};

export type ConnectionCreateIn = {
  provider: string;
  name: string;
  api_key: string;
  base_url?: string | null;
  verify_path?: string | null;
  endpoints?: string | null;
  verify?: boolean;
};

export function listProviders(): Promise<ProviderRow[]> {
  return apiFetch<ProviderRow[]>("/connections/providers");
}

export function listConnections(): Promise<ConnectionRow[]> {
  return apiFetch<ConnectionRow[]>("/connections");
}

export function createConnection(body: ConnectionCreateIn): Promise<ConnectionRow> {
  return apiFetch<ConnectionRow>("/connections", { method: "POST", body: JSON.stringify(body) });
}

export function verifyConnection(id: number): Promise<ConnectionRow> {
  return apiFetch<ConnectionRow>(`/connections/${id}/verify`, { method: "POST" });
}

export function deleteConnection(id: number): Promise<{ deleted: boolean; endpoints_removed: number }> {
  return apiFetch(`/connections/${id}`, { method: "DELETE" });
}

/* —— Platform user administration (admin only, /api/auth/users) —— */

export type UserRow = {
  id: number;
  username: string;
  email: string | null;
  role: "admin" | "editor" | "viewer";
  is_active: boolean;
  created_at: string;
  mfa_enabled: boolean;
};

export type AdminCreateUserIn = {
  username: string;
  password: string;
  email: string;
  role?: "admin" | "editor" | "viewer";
  is_active?: boolean;
};

export type UserUpdateIn = {
  email?: string;
  role?: "admin" | "editor" | "viewer";
  is_active?: boolean;
};

export function listUsers(): Promise<UserRow[]> {
  return apiFetch<UserRow[]>("/auth/users");
}

export function createUser(body: AdminCreateUserIn): Promise<UserRow> {
  return apiFetch<UserRow>("/auth/users", { method: "POST", body: JSON.stringify(body) });
}

export function updateUser(id: number, body: UserUpdateIn): Promise<UserRow> {
  return apiFetch<UserRow>(`/auth/users/${id}`, { method: "PATCH", body: JSON.stringify(body) });
}

/** Soft-deactivate — see app/routers/auth.py: sets is_active=false and revokes tokens, doesn't delete the row. */
export function deactivateUser(id: number): Promise<void> {
  return apiFetch<void>(`/auth/users/${id}`, { method: "DELETE" });
}
