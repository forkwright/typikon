// Playwright config for typikon-consuming sites — per-route smoke tests.
// https://playwright.dev/
//
// Two projects, both driven off absolute paths (forkwright/typikon#50):
//   - typikon-shared-smoke: this repo's ci/smoke/, mandatory, always runs.
//   - consumer-smoke: the consumer site's tests/smoke/, optional additions.
//
// WHY absolute env-derived paths, not testDir defaults: typikon-check
// stages this file at a mktemp path outside the consumer tree so a
// pre-existing consumer playwright.config.ts is never touched. Playwright
// resolves a relative testDir against the CONFIG FILE's directory, not the
// shell's cwd, so a relative testDir here silently stopped collecting the
// consumer's tracked specs once staged in /tmp. Absolute paths make the
// config's own location irrelevant to what gets collected.
//
// Lifecycle:
//   1. typikon-check builds public-local/ with a loopback base_url and
//      spins up a static server against it, on an OS-allocated port.
//   2. typikon-check sets TYPIKON_ROOT, TYPIKON_CONSUMER_ROOT and
//      TYPIKON_BASE_URL, then runs playwright with this config.
//   3. Each spec hits routes via TYPIKON_BASE_URL.

import { defineConfig, devices } from '@playwright/test';
import * as path from 'node:path';

function requiredRoot(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(`${name} must be set (typikon-check sets it before invoking playwright)`);
  }
  return path.resolve(value);
}

const TYPIKON_ROOT = requiredRoot('TYPIKON_ROOT');
const CONSUMER_ROOT = requiredRoot('TYPIKON_CONSUMER_ROOT');

export default defineConfig({
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 2 : undefined,
  reporter: [
    ['list'],
    ['json', { outputFile: path.join(CONSUMER_ROOT, 'test-results', 'playwright.json') }],
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
      name: 'typikon-shared-smoke',
      testDir: path.join(TYPIKON_ROOT, 'ci', 'smoke'),
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'consumer-smoke',
      testDir: path.join(CONSUMER_ROOT, 'tests', 'smoke'),
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
