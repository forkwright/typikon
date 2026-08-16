// Negative-case fixture for the pure contrast/threshold logic in
// interactive-state-contrast.spec.ts (forkwright/typikon#64).
//
// WHY a separate spec file rather than a bare test.describe() in the main
// one: this file needs neither TYPIKON_CONSUMER_ROOT nor a real page — it
// proves the MATH the browser-driven assertions depend on is sound on its
// own, independent of a live route or build. Colocated in ci/smoke/ so
// playwright's existing testDir collection (ci/playwright.config.ts) picks
// it up with no new pipeline wiring — it runs in the same
// `npx playwright test` invocation that already runs the other two specs.
//
// WHY this exists at all: the static Python counterpart
// (ci/check-interactive-contrast.py) shipped with an unanchored property
// regex that silently resolved the WRONG CSS property's value with no
// error — a class of defect where a check keeps reporting a plausible
// result while measuring the wrong thing. Nothing on this Playwright side
// ever exercised assertContrast()/textContrastFloor() against a KNOWN-bad
// input, so an equivalent silent-wrong-pass here would have gone
// unnoticed the same way. These are that missing negative case, run
// against the theme's own real, current token values so a future edit
// that breaks the threshold comparison — not the color, the LOGIC — fails
// here before it ever reaches a live route.
import { test, expect } from '@playwright/test';
import { assertContrast, contrastRatio, textContrastFloor, type EffectiveStyle } from './interactive-state-contrast.spec';

// static/css/style.css's real :root tokens, converted to the rgb() shape
// getComputedStyle reports. Kept in sync by hand deliberately, not
// derived: a derivation would risk the fixture silently tracking whatever
// the source says instead of pinning the values the #64 regression and
// its fix were actually measured against.
const BG = 'rgb(247, 243, 232)'; // --bg: #F7F3E8
const APORIA = 'rgb(92, 142, 99)'; // --aporia: #5C8E63 — the pre-#64 dye color
const APORIA_INTERACTIVE = 'rgb(74, 115, 80)'; // --aporia-interactive: #4A7350 — the fix

// .nav-links a:nth-child(3):hover's real computed size/weight (also the
// MATRIX entry in check-interactive-contrast.py for this exact rule).
const NAV_HOVER_FONT_PX = 11.1;
const NAV_HOVER_FONT_WEIGHT = 400;

test('assertContrast throws on the exact #64 regression (--aporia on --bg, normal text)', () => {
  // 3.44:1 against a 4.5:1 normal-text floor — the failing ratio the PR
  // body itself quotes from the static checker.
  const regressed: EffectiveStyle = {
    color: APORIA,
    backgroundColor: BG,
    fontSizePx: NAV_HOVER_FONT_PX,
    fontWeight: NAV_HOVER_FONT_WEIGHT,
  };
  expect(() => assertContrast('selftest: reverted #64 fix', regressed)).toThrow();
});

test('assertContrast does not throw on the shipped #64 fix (--aporia-interactive on --bg)', () => {
  // 4.91:1 clears the same 4.5:1 floor — proves the assertion isn't
  // failing everything, only the genuinely-bad case above.
  const fixed: EffectiveStyle = {
    color: APORIA_INTERACTIVE,
    backgroundColor: BG,
    fontSizePx: NAV_HOVER_FONT_PX,
    fontWeight: NAV_HOVER_FONT_WEIGHT,
  };
  expect(() => assertContrast('selftest: shipped #64 fix', fixed)).not.toThrow();
});

test('the large-text floor is a real branch: the SAME failing pair passes at large scale', () => {
  // --aporia on --bg is 3.44:1 — below the 4.5:1 normal floor (asserted
  // above) but above the 3:1 large-text floor. Holding the color pair
  // fixed and only changing declared size proves textContrastFloor's
  // size/weight branch is what selects the floor, not the color.
  const sameColorsLargeText: EffectiveStyle = {
    color: APORIA,
    backgroundColor: BG,
    fontSizePx: 24,
    fontWeight: 400,
  };
  expect(() => assertContrast('selftest: same failing colors at large scale', sameColorsLargeText)).not.toThrow();
});

test('textContrastFloor matches WCAG G18/G145 at both boundary edges', () => {
  expect(textContrastFloor(23.99, 400)).toBe(4.5); // just under 24px/regular: still normal floor
  expect(textContrastFloor(24, 400)).toBe(3.0); // 24px/regular: large floor begins
  expect(textContrastFloor(18.66, 699)).toBe(4.5); // just under 700 weight: still normal floor
  expect(textContrastFloor(18.66, 700)).toBe(3.0); // 18.66px/bold: large floor begins
});

test('contrastRatio matches the canonical WCAG black-on-white worked example', () => {
  expect(contrastRatio([0, 0, 0], [255, 255, 255])).toBeCloseTo(21, 1);
});
