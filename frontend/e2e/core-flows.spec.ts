import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

test.use({ storageState: path.join(__dirname, ".auth", "admin.json") });

test.describe("Core CRUD flows", () => {
  test("acknowledge alert: ingest undocumented traffic, then acknowledge the resulting alert in the UI", async ({
    page,
    request,
  }) => {
    // No hyphens: app.services.pathutil.normalize_path_for_discovery
    // templates any "word-word-word" segment into "{slug}" before it's
    // ever stored, which would make a hyphenated marker unrecoverable from
    // the rendered alert/shadow-row text. A single alnum token (not pure
    // digits, so it also dodges the {id} numeric-segment rule) survives
    // normalization unchanged.
    const marker = `/api/e2ealert${Date.now()}`;
    const res = await request.post("/api/ingest/batch", {
      headers: { "X-Monitor-Key": process.env.E2E_MONITOR_API_KEY ?? "e2e-test-monitor-key-minimum-32-characters" },
      data: { events: [{ method: "GET", path: marker, status_code: 200, latency_ms: 5 }] },
    });
    expect(res.ok()).toBeTruthy();

    await page.goto("/alerts");
    // Alerts.tsx defaults to "Open only" — an acknowledged alert would
    // vanish from that filtered list on the post-ack reload, so there'd be
    // nothing left to assert "Acknowledged" against. Uncheck it first.
    await page.getByLabel("Open only").uncheck();

    const card = page.locator("article", { hasText: marker });
    await expect(card).toBeVisible();
    // exact: true — the alert detail text contains "...not present in
    // registered OpenAPI.", and a substring match on "Open" hits that too.
    await expect(card.getByText("Open", { exact: true })).toBeVisible();

    await card.getByRole("button", { name: "Acknowledge" }).click();
    await expect(card.getByText("Acknowledged")).toBeVisible();
  });

  test("acknowledge shadow endpoint: ingest undocumented traffic, then acknowledge it in the UI", async ({
    page,
    request,
  }) => {
    const marker = `/api/e2eshadow${Date.now()}`; // see the no-hyphens note in the alert test above
    const res = await request.post("/api/ingest/batch", {
      headers: { "X-Monitor-Key": process.env.E2E_MONITOR_API_KEY ?? "e2e-test-monitor-key-minimum-32-characters" },
      data: { events: [{ method: "GET", path: marker, status_code: 200, latency_ms: 5 }] },
    });
    expect(res.ok()).toBeTruthy();

    await page.goto("/shadow");
    const row = page.locator("tr", { hasText: marker });
    await expect(row).toBeVisible();

    await row.getByRole("button", { name: "Ack" }).click();
    const dialog = page.getByRole("heading", { name: "Acknowledge shadow API" });
    await expect(dialog).toBeVisible();
    await page.getByRole("button", { name: "Acknowledge", exact: true }).click(); // ConfirmDialog's confirm button

    // "Acknowledge" here means "reviewed," not "resolved" — Shadow.tsx has
    // no acknowledged-state badge and list_shadow doesn't filter it out, so
    // the row staying visible is correct; the dialog closing without an
    // error banner appearing is the actual signal the POST succeeded.
    await expect(dialog).not.toBeVisible();
    await expect(page.locator("[class*='rose-50']", { hasText: /fail/i })).toHaveCount(0);
    await expect(row).toBeVisible();
  });

  test("retire zombie endpoint: seed a zombie row, then retire it in the UI", async ({ page }) => {
    // Zombie state is normally produced by a 30-minute background job, far
    // too slow for a test — so seed a row directly. E2E_DB_PATH lets this
    // point at whichever SQLite file the backend under test is actually
    // using (e2e.db for a dedicated run, apimonitor.db when pointed at a
    // local dev instance); it defaults to the dedicated e2e database.
    const dbPath = process.env.E2E_DB_PATH ?? path.join(__dirname, "..", "..", "e2e.db");
    const pythonExe = process.env.E2E_PYTHON ?? "python";
    execFileSync(pythonExe, [path.join(__dirname, "seed_zombie.py")], {
      stdio: "inherit",
      env: { ...process.env, E2E_DB_PATH: dbPath },
    });

    await page.goto("/zombie");
    const row = page.locator("div", { hasText: "/api/legacy/report" }).first();
    await expect(row).toBeVisible();

    await row.getByRole("button", { name: "Retire" }).click();
    await page.getByRole("textbox").fill("Confirmed decommissioned in e2e test");
    await page.getByRole("button", { name: "Retire", exact: true }).last().click();

    // Zombie.tsx does a full window.location.reload() after a successful
    // retire, and the status filter is component state (not URL-driven),
    // so it resets to "All statuses" on that reload — re-select RETIRED.
    // getByLabel, not getByRole("combobox").first() — the org switcher in
    // the sidebar is also a <select> and renders before this one in the DOM.
    await page.waitForLoadState("networkidle");
    await page.getByLabel("Filter by status").selectOption("RETIRED");
    await expect(page.locator("div", { hasText: "/api/legacy/report" }).first()).toBeVisible();
  });
});
