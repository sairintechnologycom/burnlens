import { test, expect, type Page } from '@playwright/test';
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';

/**
 * Signed-in /dashboard certification.
 *
 * Uses the existing remote-session client hint (burnlens_workspace_id in
 * localStorage) plus page.route API fixtures — the same architecture as
 * phase11_auth.spec.ts. Does not invent a new auth bypass.
 *
 * PW_PROD points NEXT_PUBLIC_API_URL at api.example.test, so useAuth does
 * not short-circuit to LOCAL_SESSION.
 */

const OUT = join(__dirname, '..', '..', '..', 'artifacts', 'burnlens-unification', 'blu-813');

const BILLING = {
  plan: 'cloud',
  price_cents: 2900,
  currency: 'USD',
  status: 'active',
  trial_ends_at: null,
  current_period_ends_at: null,
  cancel_at_period_end: false,
  usage: {
    start: '2026-09-01T00:00:00Z',
    end: '2026-10-01T00:00:00Z',
    request_count: 12,
    monthly_request_cap: 100000,
  },
  available_plans: [],
  api_keys: { active_count: 1, limit: 5 },
};

const EMPTY_SUMMARY = {
  total_cost_usd: 0,
  total_requests: 0,
  avg_cost_per_request_usd: 0,
  models_used: 0,
  cache_saved_usd: 0,
  cache_hits: 0,
};

const POSITIVE_SUMMARY = {
  total_cost_usd: 12.5,
  total_requests: 4,
  avg_cost_per_request_usd: 3.125,
  models_used: 2,
  cache_saved_usd: 0,
  cache_hits: 0,
};

const ECON_EMPTY = {
  total_spend_usd: 0,
  detected_waste_usd: 0,
  waste_rate: 0,
  open_finding_count: 0,
  error_spend_usd: 0,
  error_request_count: 0,
  cost_per_accepted_usd: null,
  accepted_count: 0,
  waste_by_detector: {},
  waste_estimate_clamped: false,
  trace_coverage: {
    request_count: 0,
    traced_count: 0,
    parented_count: 0,
    distinct_traces: 0,
    traced_rate: 0,
    columns_missing: false,
  },
};

const ECON_POSITIVE = {
  ...ECON_EMPTY,
  total_spend_usd: 12.5,
  accepted_count: 2,
  cost_per_accepted_usd: 6.25,
  trace_coverage: { ...ECON_EMPTY.trace_coverage, request_count: 4 },
};

const CONFIDENCE_EMPTY = {
  days: 7,
  total_cost_usd: 0,
  total_requests: 0,
  confidence_pct: 0,
  reconciled_spend_pct: 0,
  reconciled: { cost_usd: 0, requests: 0, share_pct: 0 },
  calculated: { cost_usd: 0, requests: 0, share_pct: 0 },
  estimated: { cost_usd: 0, requests: 0, share_pct: 0 },
  unpriced: { cost_usd: 0, requests: 0, share_pct: 0 },
  reasons: { no_billing_key: 0 },
  gaps: [],
};

const CONFIDENCE_NO_BILLING = {
  days: 7,
  total_cost_usd: 12.5,
  total_requests: 4,
  confidence_pct: 75,
  reconciled_spend_pct: 0,
  reconciled: { cost_usd: 0, requests: 0, share_pct: 0 },
  calculated: { cost_usd: 10, requests: 3, share_pct: 75 },
  estimated: { cost_usd: 2.5, requests: 1, share_pct: 25 },
  unpriced: { cost_usd: 0, requests: 0, share_pct: 0 },
  reasons: { no_billing_key: 4 },
  gaps: [],
};

const CONFIDENCE_RECONCILED = {
  ...CONFIDENCE_NO_BILLING,
  reconciled_spend_pct: 80,
  reconciled: { cost_usd: 10, requests: 3, share_pct: 75 },
  reasons: {},
};

const COVERAGE = {
  days: 7,
  window_seconds: 86400,
  cost_total_usd: 12.5,
  cost_attributed_usd: 10,
  cost_unattributed_usd: 2.5,
  cost_untagged_usd: 0,
  cost_accepted_usd: 8,
  cost_rework_usd: 2,
  coverage_pct: 80,
  by_workflow: [],
};

const SAVINGS_EMPTY = {
  open_projected_monthly_usd: 0,
  resolved_predicted_monthly_usd: 0,
  verified_monthly_usd: 0,
  missed_predicted_monthly_usd: 0,
  verifying_predicted_monthly_usd: 0,
  inconclusive_predicted_monthly_usd: 0,
  realisation_pct: null,
  counts: { verified: 0, missed: 0 },
};

const SAVINGS_VERIFIED = {
  ...SAVINGS_EMPTY,
  verified_monthly_usd: 4.2,
  realisation_pct: 70,
  counts: { verified: 1, missed: 0 },
};

async function seedSession(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem('burnlens_workspace_id', 'ws-cert-1');
    localStorage.setItem('burnlens_workspace_name', 'Certification Workspace');
    localStorage.setItem('burnlens_plan', 'cloud');
    localStorage.setItem('burnlens_email_verified', 'true');
    localStorage.setItem('burnlens_role', 'owner');
  });
}

async function mockApis(
  page: Page,
  payload: {
    summary: Record<string, unknown>;
    econ: Record<string, unknown>;
    confidence: Record<string, unknown> | null;
    coverage: Record<string, unknown> | null;
    savings: Record<string, unknown>;
    reconciliation: unknown[];
    requests: unknown[];
  },
) {
  const json = (body: unknown) => ({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(body),
  });

  await page.route('**/billing/summary', (route) => route.fulfill(json(BILLING)));
  await page.route('**/api/v1/usage/summary**', (route) => route.fulfill(json(payload.summary)));
  await page.route('**/api/v1/usage/timeseries**', (route) => route.fulfill(json([])));
  await page.route('**/api/v1/requests**', (route) => route.fulfill(json(payload.requests)));
  await page.route('**/api/v1/reconciliation**', (route) => route.fulfill(json(payload.reconciliation)));
  await page.route('**/api/v1/economics**', (route) => route.fulfill(json(payload.econ)));
  await page.route('**/api/v1/cost-confidence**', (route) =>
    route.fulfill(json(payload.confidence)),
  );
  await page.route('**/api/v1/outcomes/coverage**', (route) =>
    route.fulfill(json(payload.coverage)),
  );
  await page.route('**/api/v1/findings/savings**', (route) =>
    route.fulfill(json(payload.savings)),
  );
  await page.route('**/api/v1/recommendations**', (route) => route.fulfill(json([])));
}

function economicsHero(page: Page) {
  return page.locator('.card').filter({ hasText: 'AI Economics' }).first();
}

test.describe('authenticated dashboard certification', () => {
  test('empty state does not fake zeros', async ({ page }) => {
    mkdirSync(OUT, { recursive: true });
    await seedSession(page);
    await mockApis(page, {
      summary: EMPTY_SUMMARY,
      econ: ECON_EMPTY,
      confidence: CONFIDENCE_EMPTY,
      coverage: null,
      savings: SAVINGS_EMPTY,
      reconciliation: [],
      requests: [],
    });

    await page.goto('/dashboard', { waitUntil: 'networkidle' });
    const hero = economicsHero(page);
    await expect(hero.locator('.stat-label', { hasText: /^AI Spend$/ })).toBeVisible();
    await expect(hero.locator('.stat-label', { hasText: /^Accepted outcomes$/ })).toBeVisible();
    await expect(hero.locator('.stat-label', { hasText: /^Cost \/ accepted outcome$/ })).toBeVisible();
    await expect(hero.locator('.stat-label', { hasText: /^Cost Confidence$/ })).toBeVisible();
    await expect(hero.locator('.stat-label', { hasText: /^Outcome Coverage$/ })).toBeVisible();
    await expect(hero.locator('.stat-label', { hasText: /^Provider Reconciliation$/ })).toBeVisible();
    await expect(hero.locator('.stat-label', { hasText: /^Verified Savings$/ })).toBeVisible();

    await expect(hero.getByText('Not reconciled / connect billing evidence')).toBeVisible();
    await expect(hero.getByText('No verified changes yet')).toBeVisible();
    await expect(hero.getByText('No outcome data yet')).toBeVisible();
    await expect(hero.getByText('Not enough outcome data')).toBeVisible();

    const body = await page.locator('body').innerText();
    expect(body).not.toMatch(/0% reconciled/i);
    expect(body).not.toMatch(/\$0 verified savings/i);
    expect(body).not.toMatch(/\$0(?:\.00)?\s*\/\s*outcome/i);

    await page.screenshot({ path: join(OUT, 'dashboard-empty.png'), fullPage: true });
  });

  test('positive overview and unpriced request row', async ({ page }) => {
    mkdirSync(OUT, { recursive: true });
    await seedSession(page);
    await mockApis(page, {
      summary: POSITIVE_SUMMARY,
      econ: ECON_POSITIVE,
      confidence: CONFIDENCE_RECONCILED,
      coverage: COVERAGE,
      savings: SAVINGS_VERIFIED,
      reconciliation: [
        {
          provider: 'openai',
          status: 'reconciled',
          day: '2026-09-03',
          provider_cost_usd: 12.4,
          burnlens_cost_usd: 12.5,
          drift_pct: 0.8,
          computed_at: '2026-09-04T00:00:00Z',
        },
      ],
      requests: [
        {
          timestamp: '2026-09-04T10:00:00Z',
          provider: 'openai',
          model: 'gpt-4o',
          input_tokens: 100,
          output_tokens: 50,
          cost_usd: 0.0123,
          duration_ms: 800,
          tags: { feature: 'chat' },
          pricing_class: 'calculated',
        },
        {
          timestamp: '2026-09-04T10:01:00Z',
          provider: 'openai',
          model: 'mystery-model',
          input_tokens: 80,
          output_tokens: 20,
          cost_usd: 0,
          duration_ms: 400,
          tags: { feature: 'scan' },
          pricing_class: 'unpriced',
        },
      ],
    });

    await page.goto('/dashboard', { waitUntil: 'networkidle' });
    const hero = economicsHero(page);
    await expect(hero.locator('.stat-label', { hasText: /^AI Spend$/ })).toBeVisible();
    await expect(hero.getByText('$12.50')).toBeVisible();
    await expect(hero.getByText('$4.20')).toBeVisible();
    await expect(page.getByText('$ unknown')).toBeVisible();
    await expect(page.getByText('$0.0123')).toBeVisible();

    const body = await page.locator('body').innerText();
    expect(body).not.toMatch(/mystery-model[\s\S]{0,80}\$0\.00/);

    await page.screenshot({ path: join(OUT, 'dashboard-positive.png'), fullPage: true });
  });

  test('spend without billing evidence is not 0% reconciled', async ({ page }) => {
    mkdirSync(OUT, { recursive: true });
    await seedSession(page);
    await mockApis(page, {
      summary: POSITIVE_SUMMARY,
      econ: ECON_POSITIVE,
      confidence: CONFIDENCE_NO_BILLING,
      coverage: COVERAGE,
      savings: SAVINGS_EMPTY,
      reconciliation: [],
      requests: [],
    });

    await page.goto('/dashboard', { waitUntil: 'networkidle' });
    const hero = economicsHero(page);
    await expect(hero.getByText('$12.50')).toBeVisible();
    await expect(hero.getByText('Not reconciled / connect billing evidence')).toBeVisible();
    await expect(hero.getByText('No verified changes yet')).toBeVisible();
    const heroText = await hero.innerText();
    expect(heroText).not.toMatch(/0% reconciled/i);
    expect(heroText).not.toMatch(/\$0 verified savings/i);

    await page.screenshot({ path: join(OUT, 'dashboard-no-billing.png'), fullPage: true });
  });
});
