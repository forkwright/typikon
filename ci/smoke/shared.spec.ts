// Shared semantic smoke assertions for every typikon-consuming site.
//
// WHY these run regardless of consumer specs (forkwright/typikon#52): a
// consumer with no tests/smoke/*.spec.ts previously made the whole
// playwright-smoke stage report skip, so the browser gate could go green
// having exercised zero routes. This file always exists, so the stage
// always has at least this coverage; consumers add to it, they cannot
// subtract from it (typikon-check does not let a consumer file replace it).
//
// WHY the route list comes from public-local/sitemap.xml rather than a
// hand-maintained list here: sitemap.xml is Zola's own generated manifest
// of every real page in the build under test, so a page added to the site
// is covered automatically and a page that stops existing drops out
// automatically — no second place to keep in sync (see also
// ci/pa11y.config.js, which derives its route corpus the same way).
import { test, expect } from '@playwright/test';
import * as fs from 'node:fs';
import * as path from 'node:path';

const CONSUMER_ROOT = process.env.TYPIKON_CONSUMER_ROOT;
if (!CONSUMER_ROOT) {
  throw new Error('TYPIKON_CONSUMER_ROOT must be set (typikon-check sets it before invoking playwright)');
}

const sitemapPath = path.join(CONSUMER_ROOT, 'public-local', 'sitemap.xml');
let sitemapXml: string;
try {
  sitemapXml = fs.readFileSync(sitemapPath, 'utf-8');
} catch (error) {
  throw new Error(`no route corpus at ${sitemapPath} (Zola did not generate a sitemap for this build): ${error}`);
}
const routes = [...sitemapXml.matchAll(/<loc>(.*?)<\/loc>/g)]
  .map((match) => new URL(match[1]).pathname);

// INVARIANT: an empty corpus must fail loudly at collection time, not
// report a quiet zero-test pass — the same fail-closed requirement as the
// pa11y side of this defect (forkwright/typikon#52).
if (routes.length === 0) {
  throw new Error(`sitemap.xml at ${sitemapPath} has no <loc> entries; refusing to run zero shared assertions`);
}

for (const route of routes) {
  test(`shared smoke: ${route}`, async ({ page }) => {
    const consoleErrors: string[] = [];
    page.on('console', (message) => {
      if (message.type() === 'error') {
        consoleErrors.push(message.text());
      }
    });

    const response = await page.goto(route);
    expect(response?.status(), `${route} should respond 200`).toBe(200);

    await expect(page.locator('html'), `${route} <html> should declare a non-empty lang attribute`)
      .toHaveAttribute('lang', /.+/);

    const title = await page.title();
    expect(title.trim(), `${route} should have a non-empty <title>`).not.toBe('');

    expect(consoleErrors, `${route} should load with no console errors: ${consoleErrors.join('; ')}`).toEqual([]);
  });
}
