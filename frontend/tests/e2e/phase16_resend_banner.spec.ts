/**
 * Phase 16 CR-03 regression — BillingStatusBanner.handleResend must inspect
 * `response.ok` before flipping to the "email sent!" state.
 *
 * Covers:
 *  - Happy path: POST /auth/resend-verification → 200 → banner shows "email sent!"
 *  - AUTH-08 sad path (THE regression test): 401 → banner shows "try again", NOT "email sent!"
 *
 * Network calls are mocked via page.route(); no live backend required.
 * The banner only renders when session.emailVerified === false && session.isLocal === false,
 * so we seed localStorage to drive that state before navigating. The seed keys
 * MUST match the keys consumed by frontend/src/lib/hooks/useAuth.ts (verified
 * against L62-74 of that file at plan-write time).
 */

import { test, expect } from '@playwright/test';

// Drives `useAuth()` to emit a session that triggers the verify banner.
// Keys verified against frontend/src/lib/hooks/useAuth.ts:62-74.
//
// Why these specific keys:
//   - burnlens_workspace_id: required — useAuth pushes to /setup if absent (L82-85).
//   - burnlens_workspace_name / _plan / _owner_email / _role: cosmetic but
//     mirror what /setup writes on a real successful login.
//   - burnlens_email_verified='false': drives session.emailVerified === false,
//     which is half of the `showVerify` predicate in BillingStatusBanner.tsx:29.
//
// Why NOT these keys:
//   - burnlens_session_token: NOT read by useAuth (the real JWT is the HttpOnly
//     `burnlens_session` cookie); seeding it is pure noise.
//   - burnlens_is_local: NOT read by useAuth (`isLocal` is derived from API_BASE
//     hostname via isLocalBackend()). The `isLocal === false` half of `showVerify`
//     is driven by playwright.config.ts webServer.env.NEXT_PUBLIC_API_URL pointing
//     at a non-localhost host (https://api.example.test).
async function seedUnverifiedSession(page: import('@playwright/test').Page) {
  await page.addInitScript(() => {
    window.localStorage.setItem('burnlens_workspace_id', 'ws-test-fixture');
    window.localStorage.setItem('burnlens_workspace_name', 'Test WS');
    window.localStorage.setItem('burnlens_plan', 'cloud');
    window.localStorage.setItem('burnlens_owner_email', 'unverified@example.com');
    window.localStorage.setItem('burnlens_email_verified', 'false');
    window.localStorage.setItem('burnlens_role', 'owner');
  });
}

// BillingProvider fetches /billing/summary on Shell mount. With
// NEXT_PUBLIC_API_URL=https://api.example.test that request would otherwise
// hang or fail. Stubbing it lets Shell render past its loading skeleton so the
// banner under test can actually mount. Same pattern as phase11_auth.spec.ts.
async function stubBillingApis(page: import('@playwright/test').Page) {
  await page.route('**/billing/summary', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        plan: 'cloud',
        status: 'active',
        usage: {
          start: '2026-04-01T00:00:00Z',
          end: '2026-04-30T23:59:59Z',
          request_count: 10,
          monthly_request_cap: 10000,
        },
        available_plans: [],
        api_keys: null,
      }),
    })
  );
  await page.route('**/api/v1/**', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
  );
}

test.describe('Phase 16 CR-03 — resend-verification banner truthfulness', () => {
  test('200 response → banner shows "email sent!"', async ({ page }) => {
    await stubBillingApis(page);
    await page.route('**/auth/resend-verification', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ message: 'If applicable, a verification email has been sent.' }),
      });
    });

    await seedUnverifiedSession(page);
    await page.goto('/dashboard');

    const resendBtn = page.getByRole('button', { name: /resend verification email/i });
    await expect(resendBtn).toBeVisible({ timeout: 5000 });
    await resendBtn.click();

    await expect(page.getByText(/email sent!/i)).toBeVisible({ timeout: 3000 });
  });

  test('401 response → banner shows "try again" (CR-03 regression)', async ({ page }) => {
    await stubBillingApis(page);
    await page.route('**/auth/resend-verification', (route) => {
      route.fulfill({
        status: 401,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'not authenticated' }),
      });
    });

    await seedUnverifiedSession(page);
    await page.goto('/dashboard');

    const resendBtn = page.getByRole('button', { name: /resend verification email/i });
    await expect(resendBtn).toBeVisible({ timeout: 5000 });
    await resendBtn.click();

    // The CR-03 regression: must NOT see "email sent!" on a 401.
    await expect(page.getByText(/email sent!/i)).not.toBeVisible({ timeout: 1500 });

    // And must reach the error state — button text becomes "try again".
    const tryAgainBtn = page.getByRole('button', { name: /try again/i });
    await expect(tryAgainBtn).toBeVisible({ timeout: 3000 });
  });
});
