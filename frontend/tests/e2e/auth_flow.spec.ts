import { test, expect, simulateAuthError } from './test-utils';

test.describe('Authentication and Session Recovery', () => {
  
  test('unauthenticated users are redirected to setup', async ({ browser }) => {
    const context = await browser.newContext();
    const page = await context.newPage();
    
    // Attempt to access dashboard without local storage
    await page.goto('/dashboard');
    
    // Should be redirected to setup
    await page.waitForURL(/\/setup/);
    await expect(page.getByText('Initialize TokenLens')).toBeVisible();
    await context.close();
  });

  test('successfully completing setup registers an organization', async ({ browser }) => {
    const context = await browser.newContext();
    const page = await context.newPage();
    
    await page.goto('/setup');
    
    // Fill the registration form
    await page.getByPlaceholder('e.g. Acme AI').fill('E2E Test Org');
    await page.getByRole('button', { name: /Launch Organization/i }).click();
    
    // Should be redirected to dashboard
    await page.waitForURL(/\/dashboard/);
    await expect(page.getByText('E2E Test Org')).toBeVisible();

    
    // Verify local storage was persisted
    const apiKey = await page.evaluate(() => localStorage.getItem('tokenlens_api_key'));
    expect(apiKey).toBeTruthy();
    
    await context.close();
  });

  test('invalid API key triggers redirect to setup (session recovery)', async ({ authenticatedPage: page }) => {
    // 1. Initial state: dashboard
    await page.goto('/dashboard');
    await expect(page).toHaveURL(/\/dashboard/);
    
    // 2. Simulate 401 Unauthorized for usage endpoints
    await simulateAuthError(page);
    
    // 3. Trigger a fetch by clicking something or just reloading
    // The dashboard fetches on mount, so a reload will trigger it.
    await page.reload();
    
    // 4. Should be redirected automatically due to AuthError -> logout()
    await page.waitForURL(/\/setup\?expired=1/);
    
    // 5. Check for the specific alert UI
    const alert = page.getByText('Session expired');
    await expect(alert).toBeVisible({ timeout: 10000 });
    
    // 6. Verify local storage clean-up
    const apiKey = await page.evaluate(() => localStorage.getItem('tokenlens_api_key'));
    expect(apiKey).toBeNull();
  });


});
