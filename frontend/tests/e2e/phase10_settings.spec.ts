import { test, expect } from './test-utils';

// Minimal billing summary factory.
function billingSummary(overrides: Record<string, unknown> = {}) {
  return {
    plan: 'free',
    status: 'active',
    usage: {
      start: '2026-04-01T00:00:00Z',
      end: '2026-04-30T23:59:59Z',
      request_count: 5000,
      monthly_request_cap: 10000,
    },
    available_plans: [{ plan: 'cloud', price_cents: 2900 }],
    api_keys: { active_count: 0, limit: 5 },
    ...overrides,
  };
}

// Daily usage response that UsageCard fetches from /billing/usage/daily.
const dailyUsageResponse = {
  cycle_start: '2026-04-01T00:00:00Z',
  cycle_end: '2026-04-30T23:59:59Z',
  cap: 10000,
  current: 5000,
  daily: [{ date: '2026-04-28', requests: 200 }],
};

test.describe('METER-03 — Settings page mounts #usage anchor', () => {
  test('element with id="usage" is attached to DOM on /settings', async ({ authenticatedPage: page }) => {
    await page.route('**/billing/summary', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(billingSummary()),
      });
    });

    await page.route('**/billing/usage/daily', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(dailyUsageResponse),
      });
    });

    // Also stub /api-keys so settings page fully renders without errors.
    await page.route('**/api-keys', (route) => {
      if (route.request().method() === 'GET') {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify([]),
        });
      } else {
        route.continue();
      }
    });

    await page.goto('/settings');

    // UsageCard renders <div id="usage" class="card usage-card" ...>
    // This is the anchor target for the sidebar UsageMeter link "/settings#usage".
    const usageAnchor = page.locator('#usage');
    await expect(usageAnchor).toBeAttached();
  });
});

test.describe('D-26 — Create key button disabled when at cap', () => {
  test('Create key button is disabled when active_count equals limit', async ({ authenticatedPage: page }) => {
    // billing.api_keys.active_count === limit → atCap = true → button disabled.
    await page.route('**/billing/summary', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(
          billingSummary({ api_keys: { active_count: 1, limit: 1 } }),
        ),
      });
    });

    await page.route('**/billing/usage/daily', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(dailyUsageResponse),
      });
    });

    await page.route('**/api-keys', (route) => {
      if (route.request().method() === 'GET') {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify([
            {
              id: 'k1',
              name: 'Primary',
              last4: 'xxxx',
              created_at: '2026-04-01T00:00:00Z',
              revoked_at: null,
            },
          ]),
        });
      } else {
        route.continue();
      }
    });

    await page.goto('/settings');

    // ApiKeysCard renders: <button class="btn btn-cyan" disabled={atCap}>Create key</button>
    // (ApiKeysCard.tsx lines 214–221)
    const createBtn = page.getByRole('button', { name: 'Create key' }).first();
    await expect(createBtn).toBeDisabled();
  });
});

test.describe('D-24 — NewApiKeyModal is blocking: Escape does not close it', () => {
  test('modal stays open on Escape and closes only on "I\'ve saved it"', async ({ authenticatedPage: page }) => {
    await page.route('**/billing/summary', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(
          billingSummary({ api_keys: { active_count: 0, limit: 5 } }),
        ),
      });
    });

    await page.route('**/billing/usage/daily', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(dailyUsageResponse),
      });
    });

    await page.route('**/api-keys', (route) => {
      if (route.request().method() === 'GET') {
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify([]),
        });
      } else if (route.request().method() === 'POST') {
        route.fulfill({
          status: 201,
          contentType: 'application/json',
          body: JSON.stringify({
            id: 'k1',
            name: 'Primary',
            key: 'bl_live_TESTKEY1234',
            last4: '1234',
            created_at: '2026-04-01T00:00:00Z',
            revoked_at: null,
          }),
        });
      } else {
        route.continue();
      }
    });

    await page.goto('/settings');

    // Open the create-key form modal (header button in ApiKeysCard).
    // There may be two "Create key" buttons (header + EmptyState); use the header one.
    const createBtn = page.getByRole('button', { name: 'Create key' }).first();
    await expect(createBtn).toBeEnabled();
    await createBtn.click();

    // ApiKeysCard renders a backdrop dialog with aria-labelledby="ak-create-title"
    // when showCreate=true (ApiKeysCard.tsx lines 381-433).
    const createDialog = page.locator('[aria-labelledby="ak-create-title"]');
    await expect(createDialog).toBeVisible();

    // The name input has placeholder "Primary" (ApiKeysCard.tsx line 397).
    const nameInput = createDialog.locator('input[placeholder="Primary"]');
    await nameInput.fill('Primary');

    // Submit: the "Create key" button inside the create dialog (line 428).
    const submitBtn = createDialog.getByRole('button', { name: 'Create key' });
    await submitBtn.click();

    // After POST /api-keys resolves, ApiKeysCard sets plaintextKey → mounts NewApiKeyModal.
    // NewApiKeyModal renders role="dialog" aria-modal="true" aria-labelledby="nak-title"
    // (NewApiKeyModal.tsx lines 57-60).
    const modal = page.locator('[aria-labelledby="nak-title"]');
    await expect(modal).toBeVisible();

    // D-24 invariant: pressing Escape must NOT close the modal.
    // NewApiKeyModal has no keydown handler — the modal remains open.
    await page.keyboard.press('Escape');
    await expect(modal).toBeVisible();

    // The only dismissal path is the "I've saved it" button (NewApiKeyModal.tsx line 91).
    const dismissBtn = page.getByRole('button', { name: "I've saved it" });
    await expect(dismissBtn).toBeVisible();
    await dismissBtn.click();

    // After dismiss, plaintextKey is set to null → NewApiKeyModal returns null → detached.
    await expect(modal).not.toBeAttached();
  });
});
