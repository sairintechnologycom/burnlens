import { defineConfig, devices } from '@playwright/test';

/**
 * See https://playwright.dev/docs/test-configuration.
 */
export default defineConfig({
  testDir: './tests/e2e',
  /* Run tests in files in parallel */
  fullyParallel: true,
  /* Fail the build on CI if you accidentally left test.only in the source code. */
  forbidOnly: !!process.env.CI,
  /* Retry on CI only */
  retries: process.env.CI ? 2 : 0,
  /* Opt out of parallel tests on CI. */
  workers: process.env.CI ? 1 : undefined,
  /* Reporter to use. See https://playwright.dev/docs/test-reporters */
  reporter: 'html',
  /* Shared settings for all the projects below. See https://playwright.dev/docs/api/class-testoptions. */
  use: {
    /* Base URL to use in actions like `await page.goto('/')`. */
    baseURL: process.env.BASE_URL || 'http://localhost:3500',

    /* Collect trace when retrying the failed test. See https://playwright.dev/docs/trace-viewer */
    trace: 'on-first-retry',
    video: 'on-first-retry',
    screenshot: 'only-on-failure',
  },

  /* Configure projects for major browsers */
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },

    {
      name: 'firefox',
      use: { ...devices['Desktop Firefox'] },
    },

    {
      name: 'webkit',
      use: { ...devices['Desktop Safari'] },
    },

    /* Test against mobile viewports. */
    {
      name: 'Mobile Chrome',
      use: { ...devices['Pixel 5'] },
    },
    {
      name: 'Mobile Safari',
      use: { ...devices['iPhone 12'] },
    },

    /* Test against branded browsers. */
    // {
    //   name: 'Microsoft Edge',
    //   use: { ...devices['Desktop Edge'], channel: 'msedge' },
    // },
    // {
    //   name: 'Google Chrome',
    //   use: { ...devices['Desktop Chrome'], channel: 'chrome' },
    // },
  ],

  /* Run your local dev server before starting the tests.
   *
   * NEXT_PUBLIC_API_URL MUST be a non-localhost host so that
   * frontend/src/lib/hooks/useAuth.ts::isLocalBackend() returns false.
   * Otherwise useAuth short-circuits to LOCAL_SESSION (emailVerified: true,
   * isLocal: true), `showVerify` evaluates to false, and the
   * BillingStatusBanner under test never renders.
   *
   * The route-mocks in phase16_resend_banner.spec.ts use a host-agnostic
   * glob targeting the path suffix /auth/resend-verification, so they
   * intercept regardless of the base URL chosen here.
   */
  webServer: {
    // Port 3500 chosen because :3000 is often occupied by other dev servers on
    // this machine (an unrelated Next.js project); the previous reuseExistingServer
    // setting would silently reuse that server and every authenticated route 404'd.
    // PW_PROD=1 runs the specs against a production build. Required for
    // public-routes.spec.ts: minified React errors (e.g. the hydration #418
    // reported from the live site) only appear in a prod bundle, and the dev
    // overlay reports mismatches differently.
    //
    // next.config.ts sets output:"export", so there is no `next start` to run —
    // the build emits static HTML to out/ and Vercel serves it with clean URLs.
    // `serve` reproduces that (/demo -> out/demo.html); `next dev` would not.
    command: process.env.PW_PROD
      ? 'npm run build && npx --yes serve out -l 3500 --no-clipboard'
      : 'npm run dev -- -p 3500',
    url: 'http://127.0.0.1:3500',
    reuseExistingServer: !process.env.CI,
    timeout: process.env.PW_PROD ? 180_000 : 60_000,
    env: {
      NEXT_PUBLIC_API_URL: 'https://api.example.test',
    },
  },
});
