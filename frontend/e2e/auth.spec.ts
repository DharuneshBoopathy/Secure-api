import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

test.describe("Authentication", () => {
  test("logs in with valid admin credentials and lands on the dashboard", async ({ page }) => {
    await page.goto("/login");
    await page.getByPlaceholder("Username").fill(process.env.E2E_ADMIN_USERNAME ?? "admin");
    await page.getByPlaceholder("Password").fill(process.env.E2E_ADMIN_PASSWORD ?? "E2eAdminPass123!");
    await page.getByRole("button", { name: "Sign in" }).click();

    await expect(page).toHaveURL("/");
    await expect(page.getByText("Overview")).toBeVisible();
  });

  test("shows an error message for invalid credentials", async ({ page }) => {
    await page.goto("/login");
    await page.getByPlaceholder("Username").fill("admin");
    await page.getByPlaceholder("Password").fill("definitely-not-the-password");
    await page.getByRole("button", { name: "Sign in" }).click();

    await expect(page.getByText(/invalid|incorrect|failed/i)).toBeVisible();
    await expect(page).toHaveURL("/login");
  });

  test("registers a new account and lands on the dashboard as a viewer", async ({ page }) => {
    const username = `e2e_user_${Date.now()}`;
    await page.goto("/register");
    // The register form has no placeholders; its labels are htmlFor-bound.
    await page.getByLabel("Username").fill(username);
    await page.getByLabel("Email").fill(`${username}@example.com`);
    await page.getByLabel("Password", { exact: true }).fill("Str0ng!Passw0rd");
    await page.getByLabel("Confirm password").fill("Str0ng!Passw0rd");
    await page.getByRole("button", { name: "Create account" }).click();

    await expect(page).toHaveURL("/");
    await expect(page.getByText("Overview")).toBeVisible();
  });

  // Reuses the session established once by global-setup rather than logging
  // in through the form again. /api/auth/login is rate-limited to 5/min, and
  // this file already spends two of those on the login tests above — a third
  // here put a single suite run right at the limit and made it flake. This
  // test is about logout anyway, so a fresh login is incidental setup, not
  // the thing under test.
  test.describe("already signed in", () => {
    test.use({ storageState: path.join(__dirname, ".auth", "admin.json") });

    test("logs out and redirects to login", async ({ page }) => {
      await page.goto("/");
      await expect(page.getByText("Overview")).toBeVisible();

      // Mobile-nav vs desktop-sidebar: the Logout button always exists in the
      // DOM (the sidebar itself is just translated off-screen below md), so
      // this works at any viewport without first opening the hamburger menu.
      await page.getByRole("button", { name: "Logout" }).click();
      await expect(page).toHaveURL("/login");
    });
  });
});
