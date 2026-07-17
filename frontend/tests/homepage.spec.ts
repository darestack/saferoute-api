import { test, expect } from '@playwright/test';

test.describe('Homepage', () => {
  test('loads successfully', async ({ page }) => {
    await page.goto('/');
    await expect(page).toHaveTitle(/SafeRoute/);
  });

  test('has navigation links', async ({ page }) => {
    await page.goto('/');
    const nav = page.getByRole('navigation');
    await expect(nav.getByRole('link', { name: 'Features' })).toBeVisible();
    await expect(nav.getByRole('link', { name: 'How It Works' })).toBeVisible();
    await expect(nav.getByRole('link', { name: 'Pricing' })).toBeVisible();
    await expect(nav.getByRole('link', { name: 'Dashboard' })).toBeVisible();
  });

  test('has CTA buttons', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('link', { name: 'Start Building Free' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'See How It Works' })).toBeVisible();
  });

  test('shows stats bar', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText('99.9%')).toBeVisible();
    await expect(page.getByText('<50ms')).toBeVisible();
  });
});
