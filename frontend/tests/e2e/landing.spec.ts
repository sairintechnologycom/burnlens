import { test, expect } from '@playwright/test';

test.describe('Landing Page', () => {
  test('should load the landing page successfully', async ({ page }) => {
    await page.goto('/');
    
    // Check for main heading
    const heading = page.locator('h1');
    await expect(heading).toBeVisible();
    await expect(heading).toContainText(/Stop overpaying for/i);
  });

  test('should show pricing section', async ({ page }) => {
    await page.goto('/');
    
    // Check for pricing section by id
    const pricing = page.locator('#pricing');
    await expect(pricing).toBeVisible();
    
    // Check for plan names (Personal, Team, Enterprise)
    await expect(page.getByText('Personal', { exact: true })).toBeVisible();
    await expect(page.getByText('Team', { exact: true })).toBeVisible();
    await expect(page.getByText('Enterprise', { exact: true })).toBeVisible();
  });

  test('should navigate to setup when clicking Launch Dashboard', async ({ page }) => {
    await page.goto('/');
    
    // Find "Launch Dashboard" link in the hero
    const launchDashboard = page.getByRole('link', { name: /Launch Dashboard/i }).first();
    await launchDashboard.click();
    
    // Should be on /setup
    await expect(page).toHaveURL(/\/setup/);
  });
});
