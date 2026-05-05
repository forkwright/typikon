// Playwright config for typikon-consuming sites — per-route smoke tests.
// https://playwright.dev/
//
// The actual route assertions live in the consumer site's tests/smoke/.
// This config only sets up the test runner; consumer test files use the
// `test` and `expect` exports from @playwright/test.
//
// Lifecycle:
//   1. typikon-check spins up `python3 -m http.server 8080` against
//      public/ in the background.
//   2. Playwright runs every *.spec.ts under tests/smoke/.
//   3. Each spec hits routes via http://127.0.0.1:8080/<path>.
//   4. The static server is torn down after the suite completes.

import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests/smoke',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 2 : undefined,
  reporter: [
    ['list'],
    ['json', { outputFile: 'test-results/playwright.json' }],
  ],
  timeout: 30_000,
  expect: {
    timeout: 5_000,
  },
  use: {
    baseURL: process.env.TYPIKON_BASE_URL || 'http://127.0.0.1:8080',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
  },
  // Single browser channel by default — playwright in CI is heavy enough
  // without multiplying by every browser. Add chromium-mobile etc. in
  // consumer-specific config when relevant.
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
