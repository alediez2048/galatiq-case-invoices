// Fails the build if the production bundle could make a request to an external origin.
// HTML and CSS may not contain any absolute URL (no fonts, CDNs, stylesheets, images).
// JS may contain absolute URLs only from a short allowlist of non-request strings:
// XML namespace identifiers and documentation links inside React / React Router messages.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, extname } from "node:path";

// Usage: node scripts/check-bundle-origins.mjs [distDir]
const dist = (process.argv[2] ?? new URL("../dist/", import.meta.url).pathname).replace(/\/?$/, "/");
const URL_RE = /(?:https?:)?\/\/[a-z0-9.-]+\.[a-z]{2,}[^\s"'`)<>]*/gi;
const JS_ALLOWED = [
  /^https?:\/\/www\.w3\.org\//,
  /^https?:\/\/reactjs\.org\/docs\/error-decoder\.html/,
  /^https?:\/\/react\.dev\/errors\//,
  // React Router 7 invariant/warning messages (text only, never fetched).
  /^https:\/\/reactrouter\.com\/en\/main\/routers\/picking-a-router\.?$/,
  /^https:\/\/github\.com\/ungap\/url-search-params\.?$/,
];

function walk(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? walk(path) : [path];
  });
}

let files;
try {
  files = walk(dist);
} catch {
  console.error(`check-bundle-origins: ${dist} not found; run vite build first.`);
  process.exit(1);
}

// Test fixtures carry this sentinel; it must never reach a production bundle.
const FIXTURE_SENTINEL = "fixture-inventory.db";

const problems = [];
for (const file of files) {
  const ext = extname(file);
  if (![".html", ".css", ".js", ".mjs", ".json", ".svg", ".webmanifest"].includes(ext)) continue;
  const text = readFileSync(file, "utf8");
  if (text.includes(FIXTURE_SENTINEL)) problems.push(`${file.slice(dist.length)}: test fixtures bundled`);
  for (const match of text.matchAll(URL_RE)) {
    const url = match[0];
    // Skip regex/comment fragments such as "//." that are not host references.
    if (!/^(?:https?:)?\/\/[a-z0-9-]+(?:\.[a-z0-9-]+)+/i.test(url)) continue;
    const allowed = (ext === ".js" || ext === ".mjs") && JS_ALLOWED.some((re) => re.test(url));
    if (!allowed) problems.push(`${file.slice(dist.length)}: ${url}`);
  }
}

if (problems.length) {
  console.error("check-bundle-origins: external origins or fixtures in the built bundle:");
  for (const p of problems) console.error(`  ${p}`);
  process.exit(1);
}
console.log(`check-bundle-origins: ${files.length} files, no external origins.`);
