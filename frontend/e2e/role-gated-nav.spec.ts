import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test } from "@playwright/test";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

test.describe("Role-gated navigation: Users admin page", () => {
  test.describe("as admin", () => {
    test.use({ storageState: path.join(__dirname, ".auth", "admin.json") });

    test("can see the create-user form and existing accounts", async ({ page }) => {
      await page.goto("/users");
      await expect(page.getByRole("heading", { name: "Users" })).toBeVisible();
      await expect(page.getByPlaceholder("Username")).toBeVisible();
      await expect(page.getByText("admin", { exact: true }).first()).toBeVisible();
    });
  });

  test.describe("as a freshly-registered viewer", () => {
    test("sees an admin-access-required message, not the user table", async ({ page }) => {
      const username = `e2e_viewer_${Date.now()}`;
      await page.goto("/register");
      // The register form has no placeholders; its labels are htmlFor-bound.
      await page.getByLabel("Username").fill(username);
      await page.getByLabel("Email").fill(`${username}@example.com`);
      await page.getByLabel("Password", { exact: true }).fill("Str0ng!Passw0rd");
      await page.getByLabel("Confirm password").fill("Str0ng!Passw0rd");
      await page.getByRole("button", { name: "Create account" }).click();
      await expect(page).toHaveURL("/");

      await page.goto("/users");
      await expect(page.getByText(/admin access required/i)).toBeVisible();
      await expect(page.getByPlaceholder("Username")).not.toBeVisible();
    });
  });
});
