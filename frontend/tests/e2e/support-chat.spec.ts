import { test, expect } from "@playwright/test";

test.describe("Support chat widget", () => {
  test("opens, asks a question, and streams an answer with citations", async ({ page }) => {
    await page.goto("/");

    const trigger = page.getByRole("button", { name: /ask burnlens/i });
    await expect(trigger).toBeVisible();
    await trigger.click();

    const dialog = page.getByRole("dialog", { name: /burnlens support chat/i });
    await expect(dialog).toBeVisible();

    const input = dialog.getByPlaceholder(/ask a question/i);
    await input.fill("How do I install BurnLens?");
    await dialog.getByRole("button", { name: /^send$/i }).click();

    await expect(dialog).toContainText(/pip install burnlens/i, { timeout: 30_000 });

    const citations = dialog.locator('a[href*="github.com"], a[href*="burnlens.app"]');
    await expect(citations.first()).toBeVisible();
  });

  test("send button stays disabled when input is empty", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: /ask burnlens/i }).click();
    const sendBtn = page.getByRole("button", { name: /^send$/i });
    await expect(sendBtn).toBeDisabled();
  });
});
