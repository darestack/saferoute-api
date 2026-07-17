import { test, expect } from '@playwright/test';

test.describe('Login Page', () => {
  test('loads successfully', async ({ page }) => {
    await page.goto('/login.html');
    await expect(page).toHaveTitle(/Sign In/);
  });

  test('has OAuth buttons', async ({ page }) => {
    await page.goto('/login.html');
    await expect(page.getByRole('button', { name: 'Continue with Google' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Continue with GitHub' })).toBeVisible();
  });

  test('redirects to dashboard when token exists', async ({ page }) => {
    await page.goto('/login.html');
    await page.evaluate(() => localStorage.setItem('saferoute_token', 'test-token'));
    
    // Mock the /v1/me endpoint to return a valid user
    await page.route('/v1/me', route => {
      route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: 'test-user', email: 'test@example.com' })
      });
    });
    
    await page.goto('/login.html');
    await expect(page).toHaveURL(/dashboard/);
  });

  test('shows error message from query param', async ({ page }) => {
    await page.goto('/login.html?error=test+error');
    const errorEl = page.locator('#auth-error');
    await expect(errorEl).toHaveText('test error');
  });
});
