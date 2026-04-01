import { defineConfig } from '@playwright/test';

// Default to local dev server; override with PLAYWRIGHT_BASE_URL when targeting a remote env.
// Remote example: PLAYWRIGHT_BASE_URL=https://ca-qprisma-web-dev.lemoncoast-87c1f692.westeurope.azurecontainerapps.io
const BASE_URL =
  process.env.PLAYWRIGHT_BASE_URL ||
  'http://localhost:3000';

// Remote example: PLAYWRIGHT_BACKEND_URL=https://ca-qprisma-api-dev.lemoncoast-87c1f692.westeurope.azurecontainerapps.io
const BACKEND_URL =
  process.env.PLAYWRIGHT_BACKEND_URL ||
  'http://localhost:8000';

export { BACKEND_URL };

export default defineConfig({
  testDir: './e2e',
  timeout: 120_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  retries: 0,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: BASE_URL,
    headless: true,
    screenshot: 'on',
    trace: 'on',
    video: 'retain-on-failure',
    actionTimeout: 30_000,
    navigationTimeout: 30_000,
  },
  projects: [
    {
      name: 'chromium',
      use: { browserName: 'chromium' },
    },
  ],
  outputDir: './e2e/test-results',
});
