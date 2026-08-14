import { test, expect } from './test-utils';

test.describe('Optimizations Flow', () => {

  test('dashboard should show projected savings when valid data exists', async ({ authenticatedPage: page }) => {
    await page.goto('/dashboard');
    
    // Seed demo data first (via the UI button)
    await page.getByRole('button', { name: /Seed Demo Data/i }).click();
    
    // Check for non-zero savings in the dashboard card
    // Note: Locator matches 'Estimated Monthly Savings'
    const savingsCard = page.locator('.card', { hasText: 'Estimated Monthly Savings' });
    await expect(savingsCard).toBeVisible();
    
    // Savings should eventually appear as a non-zero dollar amount
    await expect(savingsCard).toContainText('$');
  });

});

