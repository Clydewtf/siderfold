import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  testMatch: /api\.spec\.ts/,
  timeout: 30_000,
  expect: { timeout: 5_000 },
  webServer: {
    command: 'VITE_DATA_MODE=api npm run dev -- --port 4188',
    url: 'http://127.0.0.1:4188',
    reuseExistingServer: false
  },
  use: {
    baseURL: 'http://127.0.0.1:4188',
    trace: 'on-first-retry'
  },
  projects: [
    { name: 'api-desktop', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 1000 } } },
    { name: 'api-mobile', use: { ...devices['Pixel 7'], viewport: { width: 393, height: 852 } } }
  ]
});
