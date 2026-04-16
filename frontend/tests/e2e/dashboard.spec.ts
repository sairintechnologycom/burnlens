import { test, expect } from './test-utils';

test.describe('Dashboard Features', () => {
  test('should show the dashboard summary cards', async ({ authenticatedPage: page }) => {
    await page.goto('/dashboard');
    
    // Summary card checks
    await expect(page.getByText('Monthly Spend')).toBeVisible();
    await expect(page.getByText('Total Tokens')).toBeVisible();
    await expect(page.getByText('API Calls')).toBeVisible();
  });

  test('should provide a button to sync and seed data', async ({ authenticatedPage: page }) => {
    await page.goto('/dashboard');
    
    // Check buttons
    const syncButton = page.getByRole('button', { name: /Sync Now/i });
    const seedButton = page.getByRole('button', { name: /Seed Demo Data/i });
    
    await expect(syncButton).toBeVisible();
    await expect(seedButton).toBeVisible();
  });

  test('should show optimization opportunities card', async ({ authenticatedPage: page }) => {
    await page.goto('/dashboard');
    
    // Check for optimization message or card
    await expect(page.getByText('Optimization Opportunities')).toBeVisible();
    await expect(page.getByText('Estimated Monthly Savings', { exact: false })).toBeVisible();
    
    // Navigate to optimizations
    await page.getByRole('link', { name: /View All/i }).click();
    await expect(page).toHaveURL(/\/optimizations/);
  });
});
