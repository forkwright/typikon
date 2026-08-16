// Shared semantic smoke assertions for every typikon-consuming site.
//
// WHY these run regardless of consumer specs (forkwright/typikon#52): the
// browser gate must never report a verdict having exercised zero routes.
// This file always exists, so the stage always carries at least this
// coverage; consumers add to it and cannot subtract from it — typikon-check
// does not let a consumer file replace it.
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

    // WHY every route, unconditionally (forkwright/typikon#149): every
    // content-bearing template now sources its <h1> from structured front
    // matter (page.title / section.title) — index.html from a
    // visually-hidden heading tied to section.title, journal-entry.html/
    // faq.html/sizing-guide.html/journal-section.html from their own
    // literal <h1>, and page.html/section.html the same way as of #149 —
    // rather than depending on a markdown body's leading `# ` line, so
    // the guarantee holds on every route, with no path-based carve-out.
    await expect(page.locator('h1'), `${route} should expose exactly one <h1>`).toHaveCount(1);

    // WHY read the accessibility tree rather than the DOM (forkwright/typikon#61):
    // an aria-label override on .faq-anchor passed pa11y's WCAG2AA ruleset
    // while collapsing every question's computed accessible name to one
    // repeated string. ariaSnapshot() reads what a screen reader actually
    // gets, so a future aria-label/aria-labelledby regression fails here
    // regardless of route content. Runs only on routes that render the FAQ
    // template; a non-FAQ route has zero .faq-anchor elements and the
    // block is skipped.
    const faqAnchors = page.locator('.faq-anchor');
    const faqAnchorCount = await faqAnchors.count();
    if (faqAnchorCount > 0) {
      const visibleTexts = await faqAnchors.evaluateAll((elements) =>
        elements.map((element) => element.textContent?.trim() ?? ''),
      );
      const snapshot = await page.locator('.faq-list').ariaSnapshot();
      const accessibleNames = [...snapshot.matchAll(/-\s*link\s+"([^"]*)"/g)].map((match) => match[1]);

      expect(
        accessibleNames.length,
        `${route} FAQ accessibility tree should expose exactly one link per question: ${snapshot}`,
      ).toBe(faqAnchorCount);
      expect(
        accessibleNames,
        `${route} each FAQ link's computed accessible name should match its own visible question text, in order`,
      ).toEqual(visibleTexts);
      expect(
        new Set(accessibleNames).size,
        `${route} FAQ link accessible names should be unique within the page: ${JSON.stringify(accessibleNames)}`,
      ).toBe(accessibleNames.length);
    }

    // Sizing-table header/cell association (forkwright/typikon#57):
    // guarded on the .sizing-table marker so it runs against every route
    // using the sizing-guide template, but its assertions are driven by
    // sizing-heterogeneous.md's two rows specifically — "S" (sets only
    // waist) and "M" (sets only note) — because a table with two rows
    // whose optional columns are DISJOINT is what the pre-#114 defect
    // could not survive. That template derived thead's column set from
    // row 0 alone, then emitted a cell for every field present on each
    // later row regardless of whether that field had a column: row "M"
    // would render its `note` value as the row's only optional cell,
    // positionally landing under the "Waist" header row 0 produced —
    // same cell COUNT as the fixed table, wrong LABEL. A per-row
    // cell-count check cannot see that; reading the value out from
    // under its header by name can, which is why this checks headers by
    // name and then indexes each row's cells by that header's position,
    // rather than only counting cells.
    const sizingTable = page.locator('.sizing-table');
    if ((await sizingTable.count()) > 0) {
      const rowHeaderCells = sizingTable.locator('tbody tr th[scope="row"]');
      const rowLabels = await rowHeaderCells.allTextContents();
      if (rowLabels.includes('S') && rowLabels.includes('M')) {
        const headers = await sizingTable.locator('thead th').allTextContents();
        expect(
          headers,
          `${route} sizing-table should expose both a Waist and a Note column when row S sets only waist and row M sets only note: ${JSON.stringify(headers)}`,
        ).toEqual(expect.arrayContaining(['Waist', 'Note']));

        const waistIdx = headers.indexOf('Waist');
        const noteIdx = headers.indexOf('Note');
        const rowS = sizingTable.locator('tbody tr').filter({ has: page.locator('th[scope="row"]', { hasText: /^S$/ }) });
        const rowM = sizingTable.locator('tbody tr').filter({ has: page.locator('th[scope="row"]', { hasText: /^M$/ }) });
        const rowSCells = await rowS.locator('th, td').allTextContents();
        const rowMCells = await rowM.locator('th, td').allTextContents();

        expect(rowSCells[waistIdx], `${route} row S's own waist value should render under the Waist column`).toBe('30');
        expect(rowSCells[noteIdx], `${route} row S sets no note; the Note column must render blank for it, not row M's value`).toBe('');
        expect(rowMCells[noteIdx], `${route} row M's own note value should render under the Note column`).toBe('custom');
        expect(rowMCells[waistIdx], `${route} row M sets no waist; the Waist column must render blank for it, not shift row M's note into it`).toBe('');
      }
    }
  });
}
