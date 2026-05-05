// pa11y-ci config for typikon-consuming sites.
// https://github.com/pa11y/pa11y-ci
//
// Run via: pa11y-ci --config ci/pa11y.config.js
// Expects a Zola build artifact under public/ and a static server
// (the GH Actions workflow spins one up at http://127.0.0.1:8080).
//
// Per-route URL list comes from the consumer site's tests/smoke/urls.json
// (one URL per line under the local server root). typikon ships only
// the defaults below; consumers extend by adding entries to urls.json.
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
  // The list of URLs to test gets injected by the GH Actions workflow:
  // it reads tests/smoke/urls.txt, prefixes each line with
  // http://127.0.0.1:8080, and concatenates onto this default.
  urls: [
    'http://127.0.0.1:8080/',
  ],
};
