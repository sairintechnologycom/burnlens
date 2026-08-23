import { test, expect, type ConsoleMessage, type Page } from '@playwright/test';

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
  '/docs',
  '/docs/scan',
  '/docs/proxy',
  '/docs/budgets',
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
  /Failed to fetch|NetworkError|net::ERR_|ERR_NAME_NOT_RESOLVED|api\.example\.test|Failed to load resource/i;

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
