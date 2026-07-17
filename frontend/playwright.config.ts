import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: 'list',
  use: {
    baseURL: 'http://127.0.0.1:8000',
    trace: 'on-first-retry',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: {
    command: '.venv/bin/python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000',
    cwd: '..',
    url: 'http://127.0.0.1:8000/docs',
    reuseExistingServer: !process.env.CI,
    timeout: 120000,
  },
});
