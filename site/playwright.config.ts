import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  testMatch: /app\.spec\.ts/,
  timeout: 30_000,
  expect: { timeout: 5_000 },
  webServer: {
    command: 'VITE_DATA_MODE=seed npm run dev -- --port 4177',
    url: 'http://127.0.0.1:4177',
    reuseExistingServer: false
  },
  use: {
    baseURL: 'http://127.0.0.1:4177',
    trace: 'on-first-retry'
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 1000 } } },
    {
      name: 'tablet',
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 820, height: 1180 }
      }
    },
    { name: 'mobile', use: { ...devices['Pixel 7'], viewport: { width: 393, height: 852 } } }
  ]
});
