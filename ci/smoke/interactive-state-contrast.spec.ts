// Browser-rendered counterpart to ci/check-interactive-contrast.py
// (forkwright/typikon#64).
//
// WHY this file exists alongside the static Python check rather than
// instead of it: ci/check-interactive-contrast.py resolves colors by
// parsing style.css's own cascade/inheritance, which is exact for what it
// can see but cannot see a bug where some OTHER, more specific rule this
// theme's author didn't anticipate silently overrides what the static
// resolver assumes. This file drives a real Chromium instance through
// default -> focus -> hover -> active on every interactive text element
// this theme ships and reads getComputedStyle's actual composited output,
// which does catch that class of bug.
//
// `:visited` is deliberately absent from the states this file exercises:
// every major browser engine makes getComputedStyle on a :visited element
// report color/background/border/outline as if unvisited, specifically to
// prevent history-sniffing, so a computed-style assertion cannot observe
// a real :visited color even if one existed. ci/check-interactive-contrast.py
// covers that state instead, by parsing the CSS source directly (unaffected
// by the browser restriction) and confirming no :visited rule exists.
//
// WHY the route list comes from public-local/sitemap.xml rather than a
// hand-maintained list here: see ci/smoke/shared.spec.ts's header comment
// (forkwright/typikon#52) — same reasoning, same mechanism.
import { test, expect, type Locator } from '@playwright/test';
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
// report a quiet zero-test pass (forkwright/typikon#52).
if (routes.length === 0) {
  throw new Error(`sitemap.xml at ${sitemapPath} has no <loc> entries; refusing to run zero shared assertions`);
}

// Every selector this theme renders as clickable/focusable text whose
// color or background changes (or is asserted unchanged) across an
// interactive state — kept in step with ci/check-interactive-contrast.py's
// MATRIX. `.mark`, the `.home-page:has(...)` decorative-gradient hovers,
// and the `:focus-visible` outline are deliberately absent here for the
// same reasons that script's module docstring gives: no text color is
// involved, or the class is pre-adjudicated elsewhere.
const TARGETS = [
  '.nav-links a',
  '.home-nav a',
  '.buy-btn',
  '.back-link',
  '.notify-link',
  '.footer-links a',
  '.entry-nav a',
  '.faq-anchor',
  '.products-list a',
  '.journal-list a',
];

// WCAG technique G18/G145 "large scale" text: >=24px at every weight, or
// >=14pt (18.66px) at bold (>=700) weight. Read live from the element's
// own computed style rather than hardcoded per-selector, so a font-size
// change in style.css is reflected here automatically instead of needing
// a matching edit to this file.
const LARGE_TEXT_PX_REGULAR = 24;
const LARGE_TEXT_PX_BOLD = 18.66;
const BOLD_WEIGHT_THRESHOLD = 700;
const TEXT_FLOOR_NORMAL = 4.5;
const TEXT_FLOOR_LARGE = 3.0;

function textContrastFloor(fontPx: number, fontWeight: number): number {
  const isLarge = fontPx >= LARGE_TEXT_PX_REGULAR
    || (fontPx >= LARGE_TEXT_PX_BOLD && fontWeight >= BOLD_WEIGHT_THRESHOLD);
  return isLarge ? TEXT_FLOOR_LARGE : TEXT_FLOOR_NORMAL;
}

function parseRgb(css: string): [number, number, number] {
  const match = css.match(/rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)/);
  if (!match) {
    throw new Error(`could not parse a computed color as rgb()/rgba(): "${css}"`);
  }
  return [Number(match[1]), Number(match[2]), Number(match[3])];
}

function srgbToLinear(channel: number): number {
  const c = channel / 255;
  return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

function relativeLuminance([r, g, b]: [number, number, number]): number {
  return 0.2126 * srgbToLinear(r) + 0.7152 * srgbToLinear(g) + 0.0722 * srgbToLinear(b);
}

function contrastRatio(a: [number, number, number], b: [number, number, number]): number {
  const la = relativeLuminance(a);
  const lb = relativeLuminance(b);
  const lighter = Math.max(la, lb);
  const darker = Math.min(la, lb);
  return (lighter + 0.05) / (darker + 0.05);
}

interface EffectiveStyle {
  color: string;
  backgroundColor: string;
  fontSizePx: number;
  fontWeight: number;
}

// WHY walk ancestors in-page: none of this theme's interactive text sets
// its own `background` in the common case (.nav-links a, .footer-links a,
// .entry-nav a, ...) — the applicable background is whichever ancestor
// actually paints one, ordinarily <body>. An element that DOES set its own
// (.buy-btn, .notify-link:hover) is caught before the walk ever looks at
// an ancestor, since the loop starts at the element itself.
async function readEffectiveStyle(locator: Locator): Promise<EffectiveStyle> {
  return locator.evaluate((el) => {
    const computed = getComputedStyle(el);
    let probe: Element | null = el;
    let backgroundColor = 'rgba(0, 0, 0, 0)';
    while (probe) {
      const bg = getComputedStyle(probe).backgroundColor;
      if (bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent') {
        backgroundColor = bg;
        break;
      }
      probe = probe.parentElement;
    }
    return {
      color: computed.color,
      backgroundColor,
      fontSizePx: parseFloat(computed.fontSize),
      fontWeight: parseInt(computed.fontWeight, 10) || 400,
    };
  });
}

function assertContrast(context: string, style: EffectiveStyle): void {
  const fg = parseRgb(style.color);
  const bg = parseRgb(style.backgroundColor);
  const ratio = contrastRatio(fg, bg);
  const floor = textContrastFloor(style.fontSizePx, style.fontWeight);
  expect(
    ratio,
    `${context}: ${style.color} on ${style.backgroundColor} = ${ratio.toFixed(2)}:1, `
      + `needs ${floor}:1 at ${style.fontSizePx}px/${style.fontWeight} (WCAG 1.4.3)`,
  ).toBeGreaterThanOrEqual(floor);
}

for (const route of routes) {
  test(`interactive-state contrast: ${route}`, async ({ page }) => {
    await page.goto(route);

    for (const selector of TARGETS) {
      const matches = page.locator(selector);
      const count = await matches.count();

      for (let i = 0; i < count; i++) {
        const el = matches.nth(i);
        if (!(await el.isVisible())) continue;

        const label = `${route} ${selector}[${i}]`;

        // Clear a residual :hover from a previous element before
        // reading "default" and "focus" — Chromium keeps :hover matched
        // at wherever the pointer last was, not wherever focus moved to.
        await page.mouse.move(0, 0);

        assertContrast(`${label} default`, await readEffectiveStyle(el));

        await el.focus();
        assertContrast(`${label} focus`, await readEffectiveStyle(el));

        await el.hover();
        assertContrast(`${label} hover`, await readEffectiveStyle(el));

        // :active — the realistic path is mouse-down WHILE hovering (both
        // pseudo-classes match simultaneously in every engine); this
        // theme defines no :active rule, so this also re-confirms that
        // the browser's OWN default doesn't quietly regress the hover
        // color once the mouse button is down.
        const box = await el.boundingBox();
        if (box) {
          await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
          await page.mouse.down();
          assertContrast(`${label} active`, await readEffectiveStyle(el));
          await page.mouse.up();
        }
      }
    }
  });
}
