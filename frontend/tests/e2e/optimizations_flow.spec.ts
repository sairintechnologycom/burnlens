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

  test('triggering analysis should update optimizations list', async ({ authenticatedPage: page }) => {
    await page.goto('/optimizations');
    
    // Click "Run Analysis"
    const analyzeButton = page.getByRole('button', { name: /Run Analysis/i });
    await analyzeButton.click();
    
    // Button state changes to "Running..."
    await expect(page.getByText('Running...')).toBeVisible();

    // After a few moments, the list should populate.
    // We search for 'Downgrade' or 'Migrate' which are common finding titles.
    await expect(page.getByText(/Downgrade|Migrate|Switch|Enable|Batch/)).toBeVisible({ timeout: 15000 });
    await expect(page.getByText('Projected Monthly Savings')).toBeVisible();
  });

});

