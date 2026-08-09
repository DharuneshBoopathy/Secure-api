import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { request } from "@playwright/test";

// This project is ESM ("type": "module" in package.json), so the CommonJS
// __dirname global isn't available here (unlike in .spec.ts files, which
// Playwright transpiles through a CJS-compatible loader).
const __dirname = path.dirname(fileURLToPath(import.meta.url));

const BASE_URL = process.env.E2E_BASE_URL ?? "http://localhost:5173";
const ADMIN_USERNAME = process.env.E2E_ADMIN_USERNAME ?? "admin";
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? "E2eAdminPass123!";

/** Logs in as admin once via the API (faster/more reliable than driving the
 * login form) and writes a Playwright storageState file so spec files that
 * need an authenticated admin session can `test.use({ storageState: ... })`
 * instead of re-logging-in per test. This app keeps auth in localStorage
 * (see frontend/src/store/appStore.ts), not cookies, hence building the
 * `origins[].localStorage` shape by hand rather than relying on
 * page.context().storageState()'s cookie-only default. */
export default async function globalSetup() {
  const ctx = await request.newContext({ baseURL: BASE_URL });
  const res = await ctx.post("/api/auth/login", {
    data: { username: ADMIN_USERNAME, password: ADMIN_PASSWORD },
  });
  if (!res.ok()) {
    throw new Error(
      `global-setup: admin login failed (${res.status()}) — is the backend running against a migrated DB with this admin account? See e2e/README.md.`,
    );
  }
  const body = await res.json();
  await ctx.dispose();

  const origin = new URL(BASE_URL).origin;
  const storageState = {
    cookies: [],
    origins: [
      {
        origin,
        localStorage: [
          { name: "apimonitor_access_token", value: body.access_token },
          { name: "apimonitor_refresh_token", value: body.refresh_token },
          { name: "apimonitor_user", value: JSON.stringify(body.user) },
        ],
      },
    ],
  };

  const outDir = path.join(__dirname, ".auth");
  fs.mkdirSync(outDir, { recursive: true });
  fs.writeFileSync(path.join(outDir, "admin.json"), JSON.stringify(storageState, null, 2));
}
