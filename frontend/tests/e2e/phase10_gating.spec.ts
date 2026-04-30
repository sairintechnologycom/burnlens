import { test, expect } from './test-utils';

// Minimal billing summary for a free-plan org.
function freeSummary() {
  return {
    plan: 'free',
    status: 'active',
    usage: {
      start: '2026-04-01T00:00:00Z',
      end: '2026-04-30T23:59:59Z',
      request_count: 100,
      monthly_request_cap: 10000,
    },
    available_plans: [{ plan: 'teams', price_cents: 9900 }],
    api_keys: null,
  };
}

// Minimal billing summary for a teams-plan org.
function teamsSummary() {
  return {
    plan: 'teams',
    status: 'active',
    usage: {
      start: '2026-04-01T00:00:00Z',
      end: '2026-04-30T23:59:59Z',
      request_count: 100,
      monthly_request_cap: 50000,
    },
    available_plans: [],
    api_keys: null,
  };
}

// 402 body that the backend emits when a free-plan org hits a teams-gated endpoint.
const teams402Body = {
  error: 'feature_not_in_plan',
  required_feature: 'teams_view',
  current_plan: 'free',
  required_plan: 'teams',
  upgrade_url: '/billing/upgrade',
};

const customers402Body = {
  error: 'feature_not_in_plan',
  required_feature: 'customers_view',
  current_plan: 'free',
  required_plan: 'teams',
  upgrade_url: '/billing/upgrade',
};

test.describe('GATE-01 — /teams shows LockedPanel dialog for free plan', () => {
  test('role=dialog and upgrade copy visible when teams endpoint returns 402', async ({ authenticatedPage: page }) => {
    await page.route('**/billing/summary', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(freeSummary()),
      });
    });

    // Teams page calls /api/v1/usage/by-team — intercepted per teams/page.tsx line 107.
    await page.route('**/api/v1/usage/by-team**', (route) => {
      route.fulfill({
        status: 402,
        contentType: 'application/json',
        body: JSON.stringify(teams402Body),
      });
    });

    await page.goto('/teams');

    // LockedPanel renders role="dialog" on .locked-panel-card (LockedPanel.tsx line 83).
    const dialog = page.locator('[role="dialog"]');
    await expect(dialog).toBeVisible();

    // The dialog title is derived from FEATURE_LABELS["teams_view"] + plan.
    // Renders: "Team breakdowns requires Teams plan" (LockedPanel.tsx line 51).
    await expect(dialog).toContainText('Teams');
  });
});

test.describe('GATE-03 — /customers shows LockedPanel dialog for free plan', () => {
  test('role=dialog and upgrade copy visible when customers endpoint returns 402', async ({ authenticatedPage: page }) => {
    await page.route('**/billing/summary', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(freeSummary()),
      });
    });

    // Customers page calls /api/v1/usage/by-customer — customers/page.tsx line 97.
    await page.route('**/api/v1/usage/by-customer**', (route) => {
      route.fulfill({
        status: 402,
        contentType: 'application/json',
        body: JSON.stringify(customers402Body),
      });
    });

    await page.goto('/customers');

    const dialog = page.locator('[role="dialog"]');
    await expect(dialog).toBeVisible();

    // Title: "Customer attribution requires Teams plan"
    await expect(dialog).toContainText('Teams');
  });
});

test.describe('GATE unlocked — /teams does NOT show LockedPanel for teams plan', () => {
  test('role=dialog absent when teams endpoint returns 200', async ({ authenticatedPage: page }) => {
    await page.route('**/billing/summary', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(teamsSummary()),
      });
    });

    await page.route('**/api/v1/usage/by-team**', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ by_team: [] }),
      });
    });

    await page.goto('/teams');

    // No LockedPanel → .locked-panel-card[role="dialog"] must not be in the DOM.
    // (Using the specific class avoids matching the Next.js devtools overlay dialog.)
    const dialog = page.locator('.locked-panel-card[role="dialog"]');
    await expect(dialog).not.toBeAttached();
  });
});
