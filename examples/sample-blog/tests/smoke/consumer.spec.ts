// Consumer-owned smoke spec (forkwright/typikon#50 fixture).
//
// WHY this file exists: ci/playwright.config.ts's consumer-smoke project
// points testDir at TYPIKON_CONSUMER_ROOT, not at the staged config's own
// directory. This spec is the fixture that exercises that path — its test
// name is unique across the whole gate (ci/smoke/shared.spec.ts never emits
// this string), so its presence in a run's reporter output is proof this
// exact file was collected from the consumer tree, not merely that some
// test ran. See ci/run-fixtures.sh, which runs bin/typikon-check against
// this fixture root on every gate pass.
import { test, expect } from '@playwright/test';

test('consumer smoke: sample-blog home renders consumer-owned content', async ({ page }) => {
  const response = await page.goto('/');
  expect(response?.status()).toBe(200);
  await expect(page.locator('body')).toContainText('Notes on craft and attention.');
});
