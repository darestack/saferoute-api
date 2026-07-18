import { test, expect } from '@playwright/test';

test.describe('Payment Flow', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/login.html');
  });

  test('shows payment error when initialization fails', async ({ page }) => {
    await page.evaluate(() => localStorage.setItem('saferoute_token', 'test-token'));
    
    await page.route('/v1/me', route => {
      route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: 'test-user', email: 'test@example.com', full_name: 'Test User', credits: 100, tier: 'free' })
      });
    });
    
    await page.route(/\/v1\/routes(\?.*)?$/, route => {
      route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify([])
      });
    });
    
    await page.route('/v1/payments/initialize', route => {
      route.fulfill({
        status: 500,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ detail: 'Payment system not configured' })
      });
    });
    
    await page.goto('/dashboard.html');
    await page.getByRole('button', { name: 'Starter' }).click();
    await page.waitForSelector('#payment-error:not(.hidden)', { timeout: 5000 });
    await expect(page.getByText('Payment system not configured')).toBeVisible();
  });

  test('changes currency display when selector changes', async ({ page }) => {
    await page.evaluate(() => localStorage.setItem('saferoute_token', 'test-token'));
    
    await page.route('/v1/me', route => {
      route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: 'test-user', email: 'test@example.com', full_name: 'Test User', credits: 100, tier: 'free' })
      });
    });
    
    await page.route(/\/v1\/routes(\?.*)?$/, route => {
      route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify([])
      });
    });

    await page.route(/\/v1\/rates(\?.*)?$/, route => {
      route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ base: 'USD', rates: { NGN: 500 } })
      });
    });
    
    await page.goto('/dashboard.html');
    await page.waitForSelector('.price-display', { timeout: 5000 });
    
    const currencySelect = page.locator('#currency-select');
    await currencySelect.selectOption('NGN');
    await page.waitForTimeout(300);
    
    await expect(page.getByText('₦2,500')).toBeVisible();
  });

  test('shows error when route creation fails', async ({ page }) => {
    await page.evaluate(() => localStorage.setItem('saferoute_token', 'test-token'));
    
    await page.route('/v1/me', route => {
      route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: 'test-user', email: 'test@example.com', full_name: 'Test User' })
      });
    });
    
    await page.route(/\/v1\/routes(\?.*)?$/, route => {
      route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify([])
      });
    });
    
    await page.route('/v1/routes', route => {
      route.fulfill({
        status: 500,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ detail: 'Database error' })
      });
    });
    
    await page.goto('/dashboard.html');
    await page.getByRole('button', { name: 'Create New Route' }).click();
    
    await page.fill('#route-name', 'Test Route');
    await page.fill('#destination-url', 'https://example.com/webhook');
    await page.locator('#create-route-modal button[type="submit"]').click();
    await page.waitForSelector('#auth-error:not(.hidden)', { timeout: 5000 });
    
    await expect(page.getByText('Database error')).toBeVisible();
  });

  test('shows login error from query param', async ({ page }) => {
    await page.goto('/login.html?error=Test+error+message');
    await expect(page.getByText('Test error message')).toBeVisible();
  });
});
