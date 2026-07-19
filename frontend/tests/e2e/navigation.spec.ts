import { test, expect } from './test-utils';

test.describe('App Navigation', () => {
  test('should load the dashboard and show the sidebar navigation', async ({ authenticatedPage: page }) => {
    await page.goto('/dashboard');
    
    // Check for dashboard header
    await expect(page.locator('h1')).toHaveText('Overview');
    
    // Check for sidebar links
    const sidebar = page.locator('aside.desktop-sidebar');
    await expect(sidebar.getByText('Overview')).toBeVisible();
    await expect(sidebar.getByText('Optimizations')).toBeVisible();
    await expect(sidebar.getByText('Alerts')).toBeVisible();
    await expect(sidebar.getByText('Settings')).toBeVisible();
  });

  test('should navigate between dashboard and optimizations', async ({ authenticatedPage: page }) => {
    await page.goto('/dashboard');

    // Navigate to Optimizations via sidebar
    const sidebar = page.locator('aside.desktop-sidebar');
    await sidebar.getByText('Optimizations').click();

    // Wait for URL
    await expect(page).toHaveURL(/\/optimizations/);

    // Navigate back to Dashboard via sidebar
    await sidebar.getByText('Overview').click();
    await expect(page).toHaveURL(/\/dashboard/);
    await expect(page.locator('h1')).toHaveText('Overview');
  });
});
