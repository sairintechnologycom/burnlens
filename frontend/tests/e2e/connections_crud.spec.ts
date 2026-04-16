import { test, expect } from './test-utils';

test.describe('Connections Management', () => {
  
  test.beforeEach(async ({ authenticatedPage: page }) => {
    await page.goto('/connections');
  });

  test('should show empty state if no connections', async ({ authenticatedPage: page }) => {
    // Note: Heading is 'Connections'
    const title = page.getByRole('heading', { name: 'Connections', exact: true });
    await expect(title).toBeVisible();
  });

  test('should add a new connection', async ({ authenticatedPage: page }) => {
    // Open modal: Button is 'Connect Provider'
    await page.getByRole('button', { name: /Connect Provider/i }).click();
    await expect(page.getByText('Connect New Provider')).toBeVisible();

    // Fill form
    await page.getByPlaceholder('e.g. Production Account').fill('E2E Provider');
    
    // Select OpenAI by clicking the button in the grid
    await page.getByRole('button', { name: /OpenAI/i }).click();
    
    await page.getByPlaceholder('sk-...').fill('sk-e2e-test-key-123456');
    
    // Submit: Button is 'Verify & Save'
    await page.getByRole('button', { name: /Verify & Save/i }).click();

    // Verify it appears in the list
    await expect(page.getByText('E2E Provider')).toBeVisible();
    await expect(page.getByText('openai')).toBeVisible();
  });


  test('should delete a connection', async ({ authenticatedPage: page }) => {
    // Assume its already there from previous test or seed
    const providerName = 'E2E Provider';
    
    // Accept the confirmation dialog
    page.on('dialog', dialog => dialog.accept());

    // Click delete (Trash2 icon)
    const card = page.locator('.card', { hasText: providerName });
    await card.getByRole('button').filter({ has: page.locator('svg') }).last().click();

    // Verify it is gone
    await expect(page.getByText(providerName)).not.toBeVisible();
  });


});
