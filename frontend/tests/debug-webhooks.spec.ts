import { test, expect } from '@playwright/test';

test('debug webhooks loading', async ({ page }) => {
  await page.goto('/dashboard.html');
  await page.evaluate(() => localStorage.setItem('saferoute_token', 'test-token'));
  
  await page.route('/v1/me', route => route.fulfill({
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id: 'test-user', email: 'test@example.com', full_name: 'Test User' })
  }));
  
  await page.route(/\/v1\/routes(\?.*)?$/, route => route.fulfill({
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify([{ id: 'route-1', name: 'Test Route', slug: 'test-route', destination_url: 'https://example.com', method: 'POST', headers: {}, is_active: true, requests_count: 0, rate_limit: 30, has_webhook_secret: false, has_transform: false, transform_headers: {}, form_schema: {}, spam_blocked_ua: [], spam_allowed_countries: [], spam_blocked_ips: [], turnstile_enabled: false, email_notifications: {}, created_at: new Date().toISOString(), updated_at: new Date().toISOString() }])
  }));
  
  await page.route('/v1/webhooks/failures', route => route.fulfill({
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ route_id: 'test-user', failures: [{ id: 'failure-1', route_id: 'route-1', route_name: 'Test Route', status_code: 500, error_message: 'Timeout', retry_count: 3, max_retries: 3, created_at: new Date().toISOString(), updated_at: new Date().toISOString() }], next_cursor: null })
  }));
  
  // Reload to trigger init with token set
  await page.reload();
  await page.waitForTimeout(2000);
  
  // Click webhooks
  await page.getByRole('link', { name: 'Webhooks' }).click();
  await page.waitForTimeout(2000);
  
  // Check DOM state
  const domState = await page.evaluate(() => {
    const list = document.getElementById('webhook-failures-list');
    const rows = list ? list.querySelectorAll('tr').length : 0;
    const text = list ? list.textContent?.substring(0, 200) : 'no list';
    const retryBtn = document.querySelector('[data-retry-failure-id]');
    return {
      rows,
      text,
      hasRetryBtn: !!retryBtn
    };
  });
  
  console.log('DOM state:', JSON.stringify(domState, null, 2));
  
  // Try to find the text
  const testRoute = await page.getByText('Test Route').count();
  console.log('Test Route count:', testRoute);
});
