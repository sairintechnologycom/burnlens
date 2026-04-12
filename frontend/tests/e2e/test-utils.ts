import { test as base, expect, Page } from '@playwright/test';

// Define the type for our custom fixtures
type MyFixtures = {
  authenticatedPage: Page;
};

export const test = base.extend<MyFixtures>({
  // Use a new context for each authenticated page to ensure clean state
  authenticatedPage: async ({ browser }, use) => {
    const context = await browser.newContext();
    const apiKey = process.env.TEST_MASTER_KEY || 'test-api-key-123';
    
    // Inject auth values BEFORE the page loads
    await context.addInitScript((key) => {
      window.sessionStorage.setItem('tokenlens_org_id', 'test-org-123');
      window.sessionStorage.setItem('tokenlens_api_key', key);
      window.sessionStorage.setItem('tokenlens_org_name', 'Test Organization');
    }, apiKey);
    
    const page = await context.newPage();
    await use(page);
    
    // Clean up
    await context.close();
  },
});

// Helper to simulate 401 Unauthorized
export async function simulateAuthError(page: Page) {
  // Only mock endpoints that require authentication
  await page.route(url => 
    url.pathname.includes('/api/v1/') && 
    !url.pathname.includes('/setup') && 
    !url.pathname.includes('/debug'), 
    route => {
      route.fulfill({
        status: 401,
        contentType: 'application/json',
        body: JSON.stringify({ detail: "Invalid API key" }),
      });
    }
  );
}



export { expect };
