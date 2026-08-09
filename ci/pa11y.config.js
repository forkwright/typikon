// pa11y-ci config for typikon-consuming sites.
// https://github.com/pa11y/pa11y-ci
//
// Run via: pa11y-ci --config ci/pa11y.config.js --sitemap <url>
//
// Per-route URL list comes from the loopback build's own generated
// sitemap.xml (Zola writes one for every real page under public-local/ —
// see typikon-check's zola-build-local stage), passed in by the caller
// via the --sitemap CLI flag: that is what actually populates config.urls
// at runtime (pa11y-ci's own loader appends the fetched sitemap entries to
// this file's `urls` array — see loadSitemapIntoConfig in pa11y-ci's bin).
// This file carries no route list itself (forkwright/typikon#52): a
// hand-maintained list here would be a second, driftable source of routes
// alongside the one Zola already derives from the actual content tree.
//
// Standard: WCAG 2.1 AA. The strict CSP guarantees no third-party scripts
// load, so accessibility issues are entirely typikon's + content's
// responsibility — there is no CDN to blame.

module.exports = {
  defaults: {
    standard: 'WCAG2AA',
    timeout: 30000,
    wait: 500,
    chromeLaunchConfig: {
      args: ['--no-sandbox', '--disable-dev-shm-usage'],
    },
    // Hide rules that the typikon design family deliberately accepts:
    //   - color-contrast on the dye-color hover backgrounds is ratio-aware
    //     by design (the gradient is decorative; underlying text is on
    //     archival-paper bg, contrast-AA-clean).
    //   - Empty <span> elements used as triad-mark slots have no
    //     accessible name by design (the parent <a> has aria-label).
    //
    // Keep this list short; every entry is a deliberate accept, not a
    // todo. When adding to it, document the why inline.
    ignore: [
      'WCAG2AA.Principle1.Guideline1_3.1_3_1.H49.AlignAttr',
    ],
    // Hide alerts on selectors known to be design-intentional (decorative
    // SVG without role, etc.). Leave empty for now; populate as the
    // smoke runs find specific false positives that would otherwise
    // require code churn.
    hideElements: '',
  },
  // Deliberately empty — see the header comment. The caller's --sitemap
  // flag is the sole route source, so there is exactly one place a route
  // can come from.
  urls: [],
};
