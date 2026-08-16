// Pure WCAG 1.4.3 contrast math shared between the browser-driven smoke
// spec (interactive-state-contrast.spec.ts) and its negative-case selftest
// (interactive-state-contrast-selftest.spec.ts) (forkwright/typikon#64).
//
// WHY this lives in its own non-.spec.ts module rather than one spec
// exporting to the other: Playwright refuses to load a test file that is
// imported by another test file ("should not import test file") — the
// selftest originally imported these symbols straight from
// interactive-state-contrast.spec.ts, which collided with that rule and
// failed test collection entirely (`Total: 0 tests in 0 files`), taking
// down every check in the same `npx playwright test` invocation, not just
// the new ones. Reproduce: revert this split (move everything below back
// into interactive-state-contrast.spec.ts and re-point the selftest's
// import at it) and run `npx playwright test --list`.
import { expect } from '@playwright/test';

// WCAG technique G18/G145 "large scale" text: >=24px at every weight, or
// >=14pt (18.66px) at bold (>=700) weight.
const LARGE_TEXT_PX_REGULAR = 24;
const LARGE_TEXT_PX_BOLD = 18.66;
const BOLD_WEIGHT_THRESHOLD = 700;
const TEXT_FLOOR_NORMAL = 4.5;
const TEXT_FLOOR_LARGE = 3.0;

export function textContrastFloor(fontPx: number, fontWeight: number): number {
  const isLarge = fontPx >= LARGE_TEXT_PX_REGULAR
    || (fontPx >= LARGE_TEXT_PX_BOLD && fontWeight >= BOLD_WEIGHT_THRESHOLD);
  return isLarge ? TEXT_FLOOR_LARGE : TEXT_FLOOR_NORMAL;
}

export function parseRgb(css: string): [number, number, number] {
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

export function contrastRatio(a: [number, number, number], b: [number, number, number]): number {
  const la = relativeLuminance(a);
  const lb = relativeLuminance(b);
  const lighter = Math.max(la, lb);
  const darker = Math.min(la, lb);
  return (lighter + 0.05) / (darker + 0.05);
}

export interface EffectiveStyle {
  color: string;
  backgroundColor: string;
  fontSizePx: number;
  fontWeight: number;
}

export function assertContrast(context: string, style: EffectiveStyle): void {
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
