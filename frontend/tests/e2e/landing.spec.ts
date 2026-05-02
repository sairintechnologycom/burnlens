import { test, expect, devices } from '@playwright/test';

test.describe('Landing Page', () => {
  test('should load the landing page successfully', async ({ page }) => {
    await page.goto('/');
    
    // Check for main heading
    const heading = page.locator('h1');
    await expect(heading).toBeVisible();
    await expect(heading).toContainText(/See exactly what your/i);
  });

  test('should show pricing section', async ({ page }) => {
    await page.goto('/');
    
    // Check for pricing section by id
    const pricing = page.locator('#pricing');
    await expect(pricing).toBeVisible();
    
    // Check for plan names (Free, Cloud, Teams, Enterprise)
    await expect(page.getByText('Free', { exact: true })).toBeVisible();
    await expect(page.getByText('Cloud', { exact: true })).toBeVisible();
    await expect(page.getByText('Enterprise', { exact: true })).toBeVisible();
  });

  test('should navigate to setup when clicking Get Started', async ({ page }) => {
    await page.goto('/');

    // Find primary CTA "Get Started" in the hero/install section
    const getStarted = page.getByRole('link', { name: /Get Started/i }).first();
    await getStarted.click();

    // Should be on /setup
    await expect(page).toHaveURL(/\/setup/);
  });
});

test.describe('Landing Page — Mobile nav', () => {
  test.use({ ...devices['Pixel 5'] });

  test('hamburger menu opens and closes on mobile', async ({ page }) => {
    await page.goto('/');

    // Desktop nav links should be hidden on mobile
    await expect(page.locator('.lp-nav-right')).toBeHidden();

    // Hamburger button should be visible
    const btn = page.locator('.lp-mobile-menu-btn');
    await expect(btn).toBeVisible();

    // Open the drawer
    await btn.click();
    await expect(page.locator('.lp-mobile-drawer')).toBeVisible();

    // Close via overlay
    await page.locator('.lp-mobile-overlay').click();
    await expect(page.locator('.lp-mobile-drawer')).toBeHidden();
  });

  test('mobile drawer Get Started navigates to /setup', async ({ page }) => {
    await page.goto('/');
    await page.locator('.lp-mobile-menu-btn').click();
    await page.locator('.lp-mobile-drawer .lp-mobile-cta').click();
    await expect(page).toHaveURL(/\/setup/);
  });
});

test.describe('Register form — validation', () => {
  test('submit button stays disabled with short password', async ({ page }) => {
    await page.goto('/setup');

    // Switch to register mode
    await page.getByRole('button', { name: /register/i }).click();

    // Fill name and email but use a short password (< 8 chars)
    await page.getByPlaceholder(/workspace name/i).fill('My Workspace');
    await page.getByPlaceholder(/email/i).fill('test@example.com');
    await page.getByPlaceholder(/min 8 characters/i).fill('short');

    // Submit button should be disabled
    const submitBtn = page.getByRole('button', { name: /Create Workspace/i });
    await expect(submitBtn).toBeDisabled();
  });

  test('submit button enables when all fields are valid', async ({ page }) => {
    await page.goto('/setup');

    await page.getByRole('button', { name: /register/i }).click();

    await page.getByPlaceholder(/workspace name/i).fill('My Workspace');
    await page.getByPlaceholder(/email/i).fill('test@example.com');
    await page.getByPlaceholder(/min 8 characters/i).fill('validpassword123');

    const submitBtn = page.getByRole('button', { name: /Create Workspace/i });
    await expect(submitBtn).toBeEnabled();
  });
});
