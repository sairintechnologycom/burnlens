import { test, expect } from "@playwright/test";

test.describe("Support search widget", () => {
  test("opens, searches, and shows matching docs with citations", async ({ page }) => {
    await page.goto("/");

    const trigger = page.getByRole("button", { name: /ask burnlens/i });
    await expect(trigger).toBeVisible();
    await trigger.click();

    const dialog = page.getByRole("dialog", { name: /burnlens support/i });
    await expect(dialog).toBeVisible();

    const input = dialog.getByPlaceholder(/search the docs/i);
    await input.fill("How do I install BurnLens?");
    await dialog.getByRole("button", { name: /^search$/i }).click();

    await expect(dialog).toContainText(/pip install burnlens/i, { timeout: 10_000 });

    const sourceLinks = dialog.locator('a[href*="github.com"], a[href*="burnlens.app"]');
    await expect(sourceLinks.first()).toBeVisible();
  });

  test("search button stays disabled when input is empty", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: /ask burnlens/i }).click();
    const searchBtn = page.getByRole("button", { name: /^search$/i });
    await expect(searchBtn).toBeDisabled();
  });
});
