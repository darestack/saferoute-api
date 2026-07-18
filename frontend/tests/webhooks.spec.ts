import { test, expect } from '@playwright/test';

test.describe('Webhook Retry Management', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/login.html');
  });

  test('shows webhook failures section with data', async ({ page }) => {
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
        body: JSON.stringify([
          { id: 'route-1', name: 'Test Route', slug: 'test-route', destination_url: 'https://example.com', method: 'POST', headers: {}, is_active: true, requests_count: 0, rate_limit: 30, has_webhook_secret: false, has_transform: false, transform_headers: {}, form_schema: {}, spam_blocked_ua: [], spam_allowed_countries: [], spam_blocked_ips: [], turnstile_enabled: false, email_notifications: {}, created_at: new Date().toISOString(), updated_at: new Date().toISOString() }
        ])
      });
    });

    await page.route('/v1/webhooks/failures', route => {
      route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          route_id: 'test-user',
          failures: [
            { id: 'failure-1', route_id: 'route-1', route_name: 'Test Route', status_code: 500, error_message: 'Destination timeout', retry_count: 3, max_retries: 3, created_at: new Date().toISOString(), updated_at: new Date().toISOString() }
          ],
          next_cursor: null
        })
      });
    });

    await page.goto('/dashboard.html');
    await page.getByRole('link', { name: 'Webhooks' }).click();
    await page.waitForSelector('[data-retry-failure-id]', { timeout: 10000 });

    await expect(page.getByText('Test Route')).toBeVisible();
    await expect(page.getByText('500')).toBeVisible();
    await expect(page.getByText('Destination timeout')).toBeVisible();
    await expect(page.getByText('3/3')).toBeVisible();
  });

  test('queues retry when Retry button is clicked', async ({ page }) => {
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
        body: JSON.stringify({
          route_id: 'test-user',
          failures: [
            { id: 'failure-1', route_id: 'route-1', route_name: 'Test Route', status_code: 500, error_message: 'Timeout', retry_count: 3, max_retries: 3, created_at: new Date().toISOString(), updated_at: new Date().toISOString() }
          ],
          next_cursor: null
        })
      });
    });

    await page.route('/v1/webhooks/failures/failure-1/retry', route => {
      route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: 'queued', log_id: 42 })
      });
    });

    await page.goto('/dashboard.html');
    await page.getByRole('link', { name: 'Webhooks' }).click();
    await page.waitForSelector('[data-retry-failure-id="failure-1"]', { timeout: 10000 });
    await page.locator('#webhooks-refresh-btn').click();

    await expect(page.getByText('Retry queued')).toBeVisible();
  });

  test('refreshes webhook failures list', async ({ page }) => {
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
        body: JSON.stringify({
          route_id: 'test-user',
          failures: [
            { id: 'failure-1', route_id: 'route-1', route_name: 'Test Route', status_code: 500, error_message: 'Timeout', retry_count: 3, max_retries: 3, created_at: new Date().toISOString(), updated_at: new Date().toISOString() }
          ],
          next_cursor: null
        })
      });
    });

    await page.goto('/dashboard.html');
    await page.getByRole('link', { name: 'Webhooks' }).click();
    await expect(page.getByText('Test Route')).toBeVisible({ timeout: 10000 });

    let callCount = 0;
    await page.route('/v1/webhooks/failures', route => {
      callCount += 1;
      route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          route_id: 'test-user',
          failures: callCount === 1 ? [] : [{ id: 'failure-1', route_id: 'route-1', route_name: 'Test Route', status_code: 500, error_message: 'Timeout', retry_count: 3, max_retries: 3, created_at: new Date().toISOString(), updated_at: new Date().toISOString() }],
          next_cursor: null
        })
      });
    });

    await page.locator('#webhooks-refresh-btn').click();
    await expect(page.getByText('Test Route')).toBeVisible({ timeout: 10000 });
  });

  test('shows retry error when retry fails', async ({ page }) => {
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
        body: JSON.stringify({
          route_id: 'test-user',
          failures: [
            { id: 'failure-1', route_id: 'route-1', route_name: 'Test Route', status_code: 500, error_message: 'Timeout', retry_count: 3, max_retries: 3, created_at: new Date().toISOString(), updated_at: new Date().toISOString() }
          ],
          next_cursor: null
        })
      });
    });

    await page.route('/v1/webhooks/failures/failure-1/retry', route => {
      route.fulfill({
        status: 500,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ detail: 'Retry failed' })
      });
    });

    await page.goto('/dashboard.html');
    await page.getByRole('link', { name: 'Webhooks' }).click();
    await page.waitForSelector('[data-retry-failure-id="failure-1"]', { timeout: 10000 });
    await page.locator('#webhooks-refresh-btn').click();

    await expect(page.getByText('Retry failed')).toBeVisible();
  });

  test('shows empty state when no webhook failures exist', async ({ page }) => {
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
        body: JSON.stringify({
          route_id: 'test-user',
          failures: [],
          next_cursor: null
        })
      });
    });

    await page.goto('/dashboard.html');
    await page.getByRole('link', { name: 'Webhooks' }).click();
    await page.waitForSelector('#webhook-failures-list', { timeout: 5000 });
    await expect(page.getByText('No failed webhook deliveries.')).toBeVisible();
  });
});
