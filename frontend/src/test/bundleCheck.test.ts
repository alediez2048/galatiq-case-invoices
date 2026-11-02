// @vitest-environment node
import { execFileSync } from "node:child_process";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const script = join(__dirname, "../../scripts/check-bundle-origins.mjs");

function check(files: Record<string, string>) {
  const dir = mkdtempSync(join(tmpdir(), "bundle-"));
  mkdirSync(join(dir, "assets"));
  for (const [name, text] of Object.entries(files)) writeFileSync(join(dir, name), text);
  try {
    execFileSync("node", [script, dir], { stdio: "pipe" });
    return { ok: true, output: "" };
  } catch (e) {
    return { ok: false, output: String((e as { stderr: Buffer }).stderr) };
  }
}

describe("check-bundle-origins", () => {
  it("accepts a bundle with only namespace URIs", () => {
    expect(
      check({
        "index.html": '<script type="module" src="/assets/a.js"></script>',
        "assets/a.js": 'const ns="http://www.w3.org/2000/svg";',
      }).ok,
    ).toBe(true);
  });

  it("rejects a font or CDN origin in HTML or CSS", () => {
    const html = check({ "index.html": '<link href="https://fonts.googleapis.com/css2?family=X">' });
    expect(html.ok).toBe(false);
    expect(html.output).toContain("fonts.googleapis.com");
    expect(check({ "assets/a.css": "@import url(//cdn.example.com/x.css);" }).ok).toBe(false);
  });

  it("rejects an analytics request in JS", () => {
    expect(check({ "assets/a.js": 'fetch("https://analytics.example.com/hit")' }).ok).toBe(false);
  });

  it("rejects bundled test fixtures", () => {
    const result = check({ "assets/a.js": 'const db="fixture-inventory.db";' });
    expect(result.ok).toBe(false);
    expect(result.output).toContain("fixtures");
  });
});
