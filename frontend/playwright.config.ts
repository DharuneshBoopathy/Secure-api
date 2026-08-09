import { defineConfig, devices } from "@playwright/test";

/**
 * Runs against a real backend + frontend, not mocks — see e2e/README.md for
 * how to stand up the backend (it needs a migrated database; there's no
 * webServer entry for it here because it isn't a `npm` command this config
 * can own the lifecycle of the way it can for the Vite dev server below).
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false, // tests share one backend + DB; parallel runs would race on the same seeded accounts
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: [["html", { open: "never" }], ["list"]],
  globalSetup: "./e2e/global-setup.ts",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:5173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: {
    command: "npm run dev",
    url: "http://localhost:5173",
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
});
