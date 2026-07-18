import { test, expect } from '@playwright/test';

test.describe('Platform Error States', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/login.html');
  });

  test('shows 401 error when token is invalid', async ({ page }) => {
    await page.evaluate(() => localStorage.setItem('saferoute_token', 'invalid-token'));

    await page.route('/v1/me', route => {
      route.fulfill({
        status: 401,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ detail: 'Invalid token' })
      });
    });

    await page.goto('/dashboard.html');
    await page.waitForURL(/login/, { timeout: 5000 });
  });

  test('shows 403 error when access is forbidden', async ({ page }) => {
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
        status: 403,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ detail: 'Forbidden' })
      });
    });

    await page.goto('/dashboard.html');
    await page.waitForTimeout(500);
    const errorText = await page.locator('#auth-error').textContent();
    expect(errorText?.trim()).toBe('Forbidden');
  });

  test('shows 500 error on server failure', async ({ page }) => {
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
        status: 500,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ detail: 'Internal server error' })
      });
    });

    await page.goto('/dashboard.html');
    await page.waitForTimeout(500);
    const errorText = await page.locator('#auth-error').textContent();
    expect(errorText?.trim()).toBe('Internal server error');
  });

  test('shows empty state when no routes exist', async ({ page }) => {
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

    await page.goto('/dashboard.html');
    await page.getByRole('link', { name: 'Routes' }).click();
    await expect(page.getByText('No routes yet. Create your first route to get started.')).toBeVisible();
  });

  test('shows empty state when no logs exist', async ({ page }) => {
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
        body: JSON.stringify([{ id: 'route-1', name: 'Test Route', slug: 'test-route', destination_url: 'https://example.com', method: 'POST', headers: {}, is_active: true, requests_count: 0, rate_limit: 30, has_webhook_secret: false, has_transform: false, transform_headers: {}, form_schema: {}, spam_blocked_ua: [], spam_allowed_countries: [], spam_blocked_ips: [], turnstile_enabled: false, email_notifications: {}, created_at: new Date().toISOString(), updated_at: new Date().toISOString() }])
      });
    });

    await page.route(/\/v1\/routes\/route-1\/logs(\?.*)?$/, route => {
      route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify([])
      });
    });

    await page.goto('/dashboard.html');
    await page.getByRole('link', { name: 'Logs' }).click();
    await page.waitForSelector('#logs-list', { timeout: 5000 });
    await expect(page.getByText('No logs yet')).toBeVisible();
  });

  test('shows empty payment history state', async ({ page }) => {
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

    await page.route('/v1/payments/history', route => {
      route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify([])
      });
    });

    await page.goto('/dashboard.html');
    await page.getByRole('link', { name: 'Payments' }).click();
    await page.waitForSelector('#payment-history-body', { timeout: 5000 });
    await expect(page.getByText('No payment history yet.')).toBeVisible();
  });

  test('shows login error from query parameter', async ({ page }) => {
    await page.goto('/login.html?error=Authentication+failed');
    await expect(page.getByText('Authentication failed')).toBeVisible();
  });

  test('handles network timeout on API request', async ({ page }) => {
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

    await page.route(/\/v1\/routes\/route-1\/logs(\?.*)?$/, route => {
      route.abort('timedout');
    });

    await page.goto('/dashboard.html');
    await page.waitForTimeout(1000);
  });

  test('handles malformed JSON response', async ({ page }) => {
    await page.evaluate(() => localStorage.setItem('saferoute_token', 'test-token'));

    await page.route('/v1/me', route => {
      route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'application/json' },
        body: 'not valid json'
      });
    });

    await page.goto('/dashboard.html');
    await page.waitForURL(/login/, { timeout: 5000 });
  });

  test('shows empty webhook failures state', async ({ page }) => {
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

    await page.route('/v1/webhooks/failures', route => {
      route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ route_id: 'test-user', failures: [], next_cursor: null })
      });
    });

    await page.goto('/dashboard.html');
    await page.getByRole('link', { name: 'Webhooks' }).click();
    await page.waitForSelector('#webhook-failures-list', { timeout: 5000 });
    await expect(page.getByText('No failed webhook deliveries.')).toBeVisible();
  });
});
