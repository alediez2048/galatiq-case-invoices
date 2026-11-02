// @vitest-environment node
import { readFileSync } from "node:fs";
import openapiTS, { astToString } from "openapi-typescript";
import { describe, expect, it } from "vitest";

const here = new URL("./", import.meta.url);

/** schema.d.ts must be the generator's output for the committed openapi.json (npm run gen:api). */
describe("generated API types", () => {
  it("are current with openapi.json", async () => {
    const ast = await openapiTS(new URL("openapi.json", here));
    const expected = astToString(ast).trim();
    const committed = readFileSync(new URL("schema.d.ts", here), "utf8");
    const body = committed.replace(/^\/\*\*[\s\S]*?\*\/\s*/, "").trim();
    expect(body).toBe(expected);
  });
});
