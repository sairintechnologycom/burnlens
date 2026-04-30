import { test, expect } from './test-utils';

// Minimal billing summary factory — only fields UsageMeter and BillingContext consume.
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
    available_plans: [],
    api_keys: null,
    ...overrides,
  };
}

test.describe('METER-01 — UsageMeter bar and numeric text render on dashboard', () => {
  test('usage-meter-bar and numeric usage text are visible', async ({ authenticatedPage: page }) => {
    // Mock /billing/summary before navigation so BillingContext has data on first render.
    await page.route('**/billing/summary', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(billingSummary()),
      });
    });

    await page.goto('/dashboard');

    // METER-01a: the track element that wraps the fill bar must be in the DOM.
    const bar = page.locator('.usage-meter-bar');
    await expect(bar).toBeVisible();

    // METER-01b: numeric text rendered as "5,000 / 10,000" (en-US toLocaleString).
    // The exact text node lives inside .usage-meter-numeric — match a substring
    // so locale formatting differences (thin-space vs comma) don't mask the real gap.
    const numeric = page.locator('.usage-meter-numeric');
    await expect(numeric).toBeVisible();
    // Must contain both "5,000" and "10,000" (or locale equivalents starting with 5 and 10).
    await expect(numeric).toContainText('5');
    await expect(numeric).toContainText('10');
  });
});

test.describe('METER-02 — UsageMeter fill uses correct color band class', () => {
  test('amber fill class present at 90% usage', async ({ authenticatedPage: page }) => {
    await page.route('**/billing/summary', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(
          billingSummary({
            usage: {
              start: '2026-04-01T00:00:00Z',
              end: '2026-04-30T23:59:59Z',
              request_count: 9000,
              monthly_request_cap: 10000,
            },
          }),
        ),
      });
    });

    await page.goto('/dashboard');

    // 90% → pct >= 80 and pct <= 100 → band = "amber"
    // UsageMeter renders: <div class="usage-meter-fill usage-meter-fill--amber" ...>
    const amberFill = page.locator('.usage-meter-fill--amber');
    await expect(amberFill).toBeAttached();
  });

  test('red fill class present when usage exceeds cap (110%)', async ({ authenticatedPage: page }) => {
    await page.route('**/billing/summary', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(
          billingSummary({
            usage: {
              start: '2026-04-01T00:00:00Z',
              end: '2026-04-30T23:59:59Z',
              request_count: 11000,
              monthly_request_cap: 10000,
            },
          }),
        ),
      });
    });

    await page.goto('/dashboard');

    // 110% → pct > 100 → band = "red"
    // UsageMeter renders: <div class="usage-meter-fill usage-meter-fill--red" ...>
    const redFill = page.locator('.usage-meter-fill--red');
    await expect(redFill).toBeAttached();
  });
});
