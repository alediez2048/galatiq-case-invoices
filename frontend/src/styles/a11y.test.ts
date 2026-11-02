import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const tokens = readFileSync("src/styles/tokens.css", "utf8");
const css = readFileSync("src/styles/app.css", "utf8");

const token = (name: string) => {
  const m = tokens.match(new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6})`));
  if (!m) throw new Error(`token ${name} not found`);
  return m[1]!;
};

function luminance(hex: string) {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const v = parseInt(hex.slice(i, i + 2), 16) / 255;
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r! + 0.7152 * g! + 0.0722 * b!;
}
const contrast = (a: string, b: string) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi! + 0.05) / (lo! + 0.05);
};

describe("accessibility tokens and CSS (P5-10)", () => {
  it("green accent text on black meets WCAG AA (4.5:1)", () => {
    expect(contrast(token("color-accent"), token("color-bg"))).toBeGreaterThanOrEqual(4.5);
    expect(contrast(token("color-accent"), token("color-surface-raised"))).toBeGreaterThanOrEqual(4.5);
  });

  it("primary button text meets WCAG AA in rest and hover states", () => {
    expect(css).toMatch(/\.button--primary\s*{[^}]*var\(--color-accent-strong\)/);
    expect(contrast(token("color-text"), token("color-accent-strong"))).toBeGreaterThanOrEqual(4.5);
    expect(contrast(token("color-text"), token("color-accent-hover"))).toBeGreaterThanOrEqual(4.5);
  });

  it("focus ring is visible against black", () => {
    expect(contrast(token("color-focus"), token("color-bg"))).toBeGreaterThanOrEqual(3);
    expect(css).toMatch(/:focus-visible\s*{[^}]*outline:\s*2px solid/);
  });

  it("prefers-reduced-motion disables animation and transitions", () => {
    const block = css.slice(css.indexOf("@media (prefers-reduced-motion: reduce)"));
    expect(block).toContain("animation: none !important");
    expect(block).toContain("transition: none !important");
  });

  it("defines the four responsive breakpoints", () => {
    for (const w of [991, 767, 479]) expect(css).toContain(`@media (max-width: ${w}px)`);
  });
});
