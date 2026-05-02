/**
 * Phase 11 auth-essentials — Playwright E2E behavioral tests.
 *
 * Covers:
 * - B1 AUTH-06: "Forgot password?" flow on /setup — inline form appears, success message shown
 * - B2 AUTH-01/02: /reset-password page — no-token error state; with-token form renders
 * - B3 AUTH-03/07: /verify-email page — no-token error state; with-token loading/result
 * - B4 AUTH-05: BillingStatusBanner email verification banner visibility rules
 *
 * All network calls to the backend are mocked via page.route() so no live
 * backend is required.
 */

import { test, expect } from '@playwright/test';

// ---------------------------------------------------------------------------
// B1 — AUTH-06: "Forgot password?" flow on /setup
// ---------------------------------------------------------------------------

test.describe('B1 — AUTH-06: Forgot password flow on /setup', () => {
  test('clicking "Forgot password?" reveals inline form', async ({ page }) => {
    // Mock the backend redirect detection: /setup calls isLocalBackend(), which
    // reads NEXT_PUBLIC_API_URL. In tests the URL will point to localhost which
    // isLocalBackend() treats as local — causing an immediate redirect to /dashboard.
    // We intercept /dashboard to stop the redirect, then navigate to /setup directly.
    // The actual test verifies the Forgot password? button exists in login mode.

    // Stub the reset-password endpoint so the form can be submitted.
    await page.route('**/auth/reset-password', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          message: 'If an account with that email exists, a reset link has been sent.',
        }),
      });
    });

    // Stub /dashboard so that if setup redirects, we can go back.
    await page.route('**/dashboard**', (route) => route.fulfill({ status: 200, body: '<html></html>' }));

    await page.goto('/setup');

    // The "Forgot password?" button is only shown in login mode (not register).
    // Ensure we're in login mode — click Sign in tab if available.
    const signInTab = page.getByRole('button', { name: /sign in/i });
    if (await signInTab.isVisible()) {
      await signInTab.click();
    }

    // Locate and click "Forgot password?" button.
    const forgotBtn = page.getByRole('button', { name: /forgot password/i });
    await expect(forgotBtn).toBeVisible({ timeout: 5000 });
    await forgotBtn.click();

    // After click, the inline form should appear with an email input.
    const emailInput = page.getByPlaceholder('you@example.com');
    await expect(emailInput).toBeVisible({ timeout: 3000 });
  });

  test('submitting forgot-password form with email shows success message', async ({ page }) => {
    await page.route('**/auth/reset-password', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          message: 'If an account with that email exists, a reset link has been sent.',
        }),
      });
    });

    await page.goto('/setup');

    // Ensure login mode.
    const signInTab = page.getByRole('button', { name: /sign in/i });
    if (await signInTab.isVisible()) {
      await signInTab.click();
    }

    // Click "Forgot password?" to open the inline form.
    const forgotBtn = page.getByRole('button', { name: /forgot password/i });
    await expect(forgotBtn).toBeVisible({ timeout: 5000 });
    await forgotBtn.click();

    // Fill in the email input.
    const emailInput = page.getByPlaceholder('you@example.com');
    await emailInput.fill('test@example.com');

    // Submit the form by clicking "Send reset link".
    await page.getByRole('button', { name: /send reset link/i }).click();

    // Success: the page should display a message confirming the email was sent.
    await expect(
      page.getByText(/reset link is on its way/i)
    ).toBeVisible({ timeout: 5000 });
  });
});


// ---------------------------------------------------------------------------
// B2 — AUTH-01/02: /reset-password page
// ---------------------------------------------------------------------------

test.describe('B2 — AUTH-01/02: /reset-password page', () => {
  test('navigating to /reset-password with no token shows invalid-link error', async ({ page }) => {
    await page.goto('/reset-password');

    // Without a ?token= query param, the page renders an error state.
    // The reset-password/page.tsx renders "invalid or has expired" text.
    await expect(
      page.getByText(/invalid or has expired/i)
    ).toBeVisible({ timeout: 5000 });
  });

  test('navigating to /reset-password?token=sometoken renders password input form', async ({ page }) => {
    // The page should render the "Set a new password" form when a token is present.
    await page.goto('/reset-password?token=sometoken');

    // The form title "Set a new password" must be visible.
    await expect(
      page.getByText(/set a new password/i)
    ).toBeVisible({ timeout: 5000 });

    // The password input field must be present.
    const passwordInput = page.locator('input[type="password"]');
    await expect(passwordInput).toBeVisible({ timeout: 3000 });
  });
});


// ---------------------------------------------------------------------------
// B3 — AUTH-03/07: /verify-email page
// ---------------------------------------------------------------------------

test.describe('B3 — AUTH-03/07: /verify-email page', () => {
  test('navigating to /verify-email with no token shows error state', async ({ page }) => {
    await page.goto('/verify-email');

    // Without a token, the page should show "Verification failed" or
    // "invalid" error state. The verify-email/page.tsx sets message to
    // "This verification link is invalid." when no token is present.
    await expect(
      page.getByText(/invalid/i)
    ).toBeVisible({ timeout: 5000 });
  });

  test('navigating to /verify-email?token=sometoken shows loading state or result', async ({ page }) => {
    // Mock the backend verify-email POST to return success so we can observe
    // the result state without a live backend.
    await page.route('**/auth/verify-email', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ message: 'Email verified successfully.' }),
      });
    });

    await page.goto('/verify-email?token=sometoken');

    // Either the loading text ("Verifying your email") or the success state
    // ("Email verified") must appear. The page shows "loading" first then
    // transitions to "success" after the fetch resolves.
    const successTitle = page.getByText(/email verified/i);
    const loadingText = page.getByText(/verifying your email/i);

    // At least one of these must be visible.
    await expect(successTitle.or(loadingText)).toBeVisible({ timeout: 5000 });
  });
});


// ---------------------------------------------------------------------------
// B4 — AUTH-05: BillingStatusBanner email verification banner
// ---------------------------------------------------------------------------

test.describe('B4 — AUTH-05: BillingStatusBanner email verification banner', () => {
  /**
   * The BillingStatusBanner is rendered inside the dashboard Shell. It reads
   * session from useAuth, which in turn reads from localStorage.
   *
   * BillingStatusBanner shows the email-verification banner when:
   *   session.emailVerified === false  AND  session.isLocal === false
   *
   * We set localStorage values before navigation to seed the session.
   * We must also have a billing summary so the shell renders (mock the API).
   */

  async function stubDashboardApis(page: import('@playwright/test').Page) {
    // Stub billing summary — required by BillingContext.
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
    // Stub common dashboard data fetches to prevent unhandled network errors.
    await page.route('**/api/v1/**', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    );
  }

  test('email verification banner is visible when email_verified=false and session is cloud', async ({ page }) => {
    await stubDashboardApis(page);

    // Inject localStorage BEFORE navigation using addInitScript.
    await page.addInitScript(() => {
      localStorage.setItem('burnlens_workspace_id', 'test-ws-id');
      localStorage.setItem('burnlens_workspace_name', 'Test Workspace');
      localStorage.setItem('burnlens_plan', 'cloud');
      localStorage.setItem('burnlens_api_key', 'bl_live_testkey');
      localStorage.setItem('burnlens_owner_email', 'owner@example.com');
      // email_verified=false AND plan=cloud means isLocal=false
      localStorage.setItem('burnlens_email_verified', 'false');
    });

    await page.goto('/dashboard');

    // The BillingStatusBanner renders aria-label="Email verification required"
    // when the banner is shown.
    const banner = page.getByRole('status', { name: /email verification required/i });
    await expect(banner).toBeVisible({ timeout: 7000 });
  });

  test('email verification banner is NOT shown when email_verified=true', async ({ page }) => {
    await stubDashboardApis(page);

    await page.addInitScript(() => {
      localStorage.setItem('burnlens_workspace_id', 'test-ws-id');
      localStorage.setItem('burnlens_workspace_name', 'Test Workspace');
      localStorage.setItem('burnlens_plan', 'cloud');
      localStorage.setItem('burnlens_api_key', 'bl_live_testkey');
      localStorage.setItem('burnlens_owner_email', 'owner@example.com');
      localStorage.setItem('burnlens_email_verified', 'true');
    });

    await page.goto('/dashboard');

    // Wait briefly for the page to stabilise before asserting absence.
    await page.waitForTimeout(1500);

    const banner = page.getByRole('status', { name: /email verification required/i });
    await expect(banner).not.toBeVisible({ timeout: 3000 });
  });
});
