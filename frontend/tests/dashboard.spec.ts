import { test, expect } from '@playwright/test';

test.describe('Dashboard', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/dashboard.html');
  });

  test('redirects to login when no token', async ({ page }) => {
    await page.waitForURL(/login/, { timeout: 5000 });
  });

  test('shows dashboard with valid token', async ({ page }) => {
    await page.evaluate(() => localStorage.setItem('saferoute_token', 'test-token'));
    
    await page.route('/v1/me', route => {
      route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: 'test-user', email: 'test@example.com', full_name: 'Test User' })
      });
    });
    
    await page.route('/v1/routes', route => {
      route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify([])
      });
    });
    
    await page.goto('/dashboard.html');
    await page.waitForSelector('h1:has-text("Dashboard")', { timeout: 5000 });
    await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();
  });

  test('has sidebar navigation', async ({ page }) => {
    await page.evaluate(() => localStorage.setItem('saferoute_token', 'test-token'));
    
    await page.route('/v1/me', route => {
      route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: 'test-user', email: 'test@example.com', full_name: 'Test User' })
      });
    });
    
    await page.route('/v1/routes', route => {
      route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify([])
      });
    });
    
    await page.goto('/dashboard.html');
    await expect(page.getByRole('link', { name: 'Dashboard' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Routes' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Logs' })).toBeVisible();
  });

  test('shows stats cards', async ({ page }) => {
    await page.evaluate(() => localStorage.setItem('saferoute_token', 'test-token'));
    
    await page.route('/v1/me', route => {
      route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: 'test-user', email: 'test@example.com', full_name: 'Test User' })
      });
    });
    
    await page.route('/v1/routes', route => {
      route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify([])
      });
    });
    
    await page.goto('/dashboard.html');
    await expect(page.getByText('Total Requests')).toBeVisible();
    await expect(page.getByText('Success Rate')).toBeVisible();
    await expect(page.getByText('Avg Response')).toBeVisible();
    await expect(page.getByText('Spam Blocked')).toBeVisible();
  });

  test('shows create route modal on button click', async ({ page }) => {
    await page.evaluate(() => localStorage.setItem('saferoute_token', 'test-token'));
    
    await page.route('/v1/me', route => {
      route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: 'test-user', email: 'test@example.com', full_name: 'Test User' })
      });
    });
    
    await page.route('/v1/routes', route => {
      route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify([])
      });
    });
    
    await page.goto('/dashboard.html');
    await page.getByRole('button', { name: 'Create New Route' }).click();
    await expect(page.getByRole('heading', { name: 'Create New Route' })).toBeVisible();
  });

  test('shows Buy Credits section', async ({ page }) => {
    await page.evaluate(() => localStorage.setItem('saferoute_token', 'test-token'));
    
    await page.route('/v1/me', route => {
      route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: 'test-user', email: 'test@example.com', full_name: 'Test User', credits: 100, tier: 'free' })
      });
    });
    
    await page.route('/v1/routes', route => {
      route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify([])
      });
    });
    
    await page.goto('/dashboard.html');
    await expect(page.getByText('Buy Credits')).toBeVisible();
    await expect(page.getByText('Starter')).toBeVisible();
    await expect(page.getByText('Builder')).toBeVisible();
    await expect(page.getByText('Agency')).toBeVisible();
  });

  test('clicking Buy Credits button initializes payment', async ({ page }) => {
    await page.evaluate(() => localStorage.setItem('saferoute_token', 'test-token'));
    
    await page.route('/v1/me', route => {
      route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: 'test-user', email: 'test@example.com', full_name: 'Test User', credits: 100, tier: 'free' })
      });
    });
    
    await page.route('/v1/routes', route => {
      route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify([])
      });
    });
    
    await page.route('/v1/payments/initialize', route => {
      route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ authorization_url: 'https://checkout.paystack.com/test', reference: 'sr_test_starter', amount: 250000, currency: 'NGN' })
      });
    });
    
    await page.goto('/dashboard.html');
    await page.getByRole('button', { name: 'Starter' }).click();
    
    await page.waitForURL('https://checkout.paystack.com/test', { timeout: 5000 });
  });
});
