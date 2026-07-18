import { test, expect } from '@playwright/test';

test.describe('Payment Flow E2E', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/login.html');
  });

  test('completes full payment flow on success', async ({ page }) => {
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

    await page.route('/v1/payments/verify/sr_test_ref', route => {
      route.fulfill({
        status: 200,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: 'success', reference: 'sr_test_ref', amount: 250000, credits_added: 1000, new_balance: 1100 })
      });
    });

    await page.goto('/dashboard.html?status=success&reference=sr_test_ref');
    await page.waitForSelector('#auth-error:not(.hidden)', { timeout: 5000 });

    await expect(page.getByText('Payment successful! 1,000 credits added to your account.')).toBeVisible();
  });

  test('shows error on payment verification failure', async ({ page }) => {
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

    await page.route('/v1/payments/verify/sr_test_ref', route => {
      route.fulfill({
        status: 400,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ detail: 'Transaction not found' })
      });
    });

    await page.goto('/dashboard.html?status=failed&reference=sr_test_ref');
    await page.waitForSelector('#auth-error:not(.hidden)', { timeout: 5000 });

    await expect(page.getByText('Transaction not found')).toBeVisible();
  });

  test('shows error when payment initialize returns non-JSON', async ({ page }) => {
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

    await page.route('/v1/payments/initialize', route => {
      route.fulfill({
        status: 500,
        headers: { 'Content-Type': 'text/plain' },
        body: 'Internal Server Error'
      });
    });

    await page.goto('/dashboard.html');
    await page.getByRole('button', { name: 'Starter' }).click();
    await page.waitForSelector('#payment-error:not(.hidden)', { timeout: 5000 });

    await expect(page.getByText('Server error (500)')).toBeVisible();
  });

  test('shows error when payment initialize network fails', async ({ page }) => {
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

    await page.route('/v1/payments/initialize', route => {
      route.abort('failed');
    });

    await page.goto('/dashboard.html');
    await page.getByRole('button', { name: 'Starter' }).click();
    await page.waitForSelector('#payment-error:not(.hidden)', { timeout: 5000 });

    await expect(page.getByText('Payment failed')).toBeVisible();
  });

  test('redirects to Paystack checkout on successful initialization', async ({ page }) => {
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
