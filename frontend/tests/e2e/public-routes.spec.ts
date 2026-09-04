import { test, expect, type ConsoleMessage, type Page } from '@playwright/test';
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

/**
 * Console-error gate for every public route.
 *
 * Exists because a production React hydration error (#418) was reported from
 * the live site during a platform review and nobody noticed: no CI job loaded
 * a public page and looked at the console. This spec is that missing check.
 *
 * Run against a PRODUCTION build (PW_PROD=1), not `next dev` — hydration
 * mismatches are reported differently under the dev overlay, and minified
 * React errors only appear in a prod bundle.
 */

const PUBLIC_ROUTES = [
  '/',
  '/demo',
  '/scan',
  '/llm-pricing',
  '/cost-per-outcome',
  '/docs',
  '/docs/scan',
  '/docs/proxy',
  '/docs/budgets',
  '/docs/evidence',
  '/docs/limitations',
  '/docs/cli',
  '/security',
  '/privacy',
  '/terms',
  '/refund',
  '/faq',
  '/troubleshooting',
  '/status',
  '/setup',
  '/compare/burnlens-vs-helicone',
  '/compare/burnlens-vs-langfuse',
  '/compare/burnlens-vs-litellm',
];

/**
 * The Playwright webServer points NEXT_PUBLIC_API_URL at a host that does not
 * resolve, so every page that talks to the backend logs transport failures.
 * That noise is expected here; application errors are not.
 */
const NETWORK_NOISE =
  /Failed to fetch|NetworkError|net::ERR_|ERR_NAME_NOT_RESOLVED|api\.example\.test|Failed to load resource|CORS policy/i;

function isRealError(text: string): boolean {
  return !NETWORK_NOISE.test(text);
}

/** Attach listeners before the first navigation so load-time errors are caught. */
function collectErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on('console', (msg: ConsoleMessage) => {
    if (msg.type() === 'error' && isRealError(msg.text())) {
      errors.push(`console.error: ${msg.text()}`);
    }
  });
  page.on('pageerror', (err: Error) => {
    if (isRealError(err.message)) {
      errors.push(`uncaught: ${err.message}`);
    }
  });
  return errors;
}

for (const route of PUBLIC_ROUTES) {
  test(`${route} loads with no console errors`, async ({ page }) => {
    const errors = collectErrors(page);

    const response = await page.goto(route, { waitUntil: 'networkidle' });
    expect(response?.status(), `${route} should not be an error page`).toBeLessThan(400);

    // Hydration errors surface a tick after the bundle executes, not at
    // networkidle — give React a beat to finish and complain.
    await page.waitForTimeout(1000);

    expect(errors, `${route} logged errors:\n${errors.join('\n')}`).toEqual([]);
  });
}

test('support dialog opens, closes with Escape, and logs no errors', async ({ page }) => {
  const errors = collectErrors(page);

  await page.goto('/demo', { waitUntil: 'networkidle' });

  const trigger = page.getByRole('button', { name: 'Ask BurnLens' });
  await trigger.click();

  const dialog = page.getByRole('dialog', { name: 'BurnLens support search' });
  await expect(dialog).toBeVisible();

  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();

  // Focus must return to the trigger, or a keyboard user is stranded at the
  // top of the document after closing.
  await expect(trigger).toBeFocused();

  expect(errors, `support dialog logged errors:\n${errors.join('\n')}`).toEqual([]);
});

test('scan guidance ends at the economics journey', async ({ page }) => {
  await page.goto('/scan', { waitUntil: 'networkidle' });
  await expect(page.getByText('burnlens economics')).toBeVisible();
  await expect(page.getByText('$ unknown', { exact: false })).toBeVisible();
});

test('unpriced cost is $ unknown, not a measured zero', async ({ page }) => {
  await page.goto('/', { waitUntil: 'networkidle' });
  await expect(page.getByText('$ unknown', { exact: false })).toBeVisible();
  const body = await page.locator('body').innerText();
  expect(body).not.toMatch(/unpriced[\s\S]{0,80}\$0\.00/i);
});

test('demo is labeled as fixture data, not live telemetry', async ({ page }) => {
  await page.goto('/demo', { waitUntil: 'networkidle' });
  await expect(page.getByText('DETERMINISTIC_DEMO_FIXTURE')).toBeVisible();
  await expect(page.getByText('not live telemetry', { exact: false })).toBeVisible();
});

test('routing rewrite is described as explicit opt-in', async ({ page }) => {
  await page.goto('/docs/budgets', { waitUntil: 'networkidle' });
  await expect(page.getByText('routing.budget_downgrade', { exact: false })).toBeVisible();
  const budgets = await page.locator('body').innerText();
  expect(budgets.toLowerCase()).toMatch(/off by default|opt[- ]in|false/);

  await page.goto('/security', { waitUntil: 'networkidle' });
  const security = await page.locator('body').innerText();
  expect(security).toContain('routing.budget_downgrade');
  expect(security.toLowerCase()).toMatch(/opt[- ]in|off by default|observation mode/);
});

test('main public navigation is intact on home', async ({ page }) => {
  await page.goto('/', { waitUntil: 'networkidle' });
  const nav = page.locator('nav').first();
  await expect(nav.getByRole('link', { name: /Scan/i })).toBeVisible();
  await expect(nav.getByRole('link', { name: /Docs/i })).toBeVisible();
  await expect(nav.getByRole('link', { name: /Security/i })).toBeVisible();
  await expect(nav.getByRole('link', { name: /Live demo/i })).toBeVisible();
  await nav.getByRole('link', { name: /Docs/i }).click();
  await expect(page).toHaveURL(/\/docs/);
});

test('no horizontal overflow at mobile width', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  for (const route of ['/', '/demo', '/scan', '/docs/budgets', '/security']) {
    await page.goto(route, { waitUntil: 'networkidle' });
    const overflow = await page.evaluate(() => {
      const doc = document.documentElement;
      return doc.scrollWidth - window.innerWidth;
    });
    expect(overflow, `${route} horizontal overflow ${overflow}px`).toBeLessThanOrEqual(1);
  }
});

test('persist public route screenshots and results', async ({ page }, info) => {
  const out = join(__dirname, '..', '..', '..', 'artifacts', 'burnlens-unification', 'blu-812');
  mkdirSync(out, { recursive: true });
  const results: { route: string; status: number | null }[] = [];
  for (const route of PUBLIC_ROUTES) {
    const response = await page.goto(route, { waitUntil: 'domcontentloaded' });
    results.push({ route, status: response?.status() ?? null });
    const name = route === '/' ? 'home' : route.slice(1).replace(/\//g, '-');
    await page.screenshot({ path: join(out, `${name}.png`), fullPage: true });
  }
  writeFileSync(join(out, 'routes.json'), JSON.stringify({
    project: info.project.name,
    results,
  }, null, 2));
  expect(results.every((r) => r.status !== null && r.status < 400)).toBeTruthy();
});
