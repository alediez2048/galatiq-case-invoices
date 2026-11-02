import { defineConfig, devices } from "@playwright/test";

const PORT = 18765;

// One FastAPI process serves the built UI and the API on a temporary offline database
// (e2e/serve.py). Tests run serially because they share that database. Not part of
// `npm test` (vitest) or `uv run pytest`; run with `npm run test:e2e`.
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: { baseURL: `http://127.0.0.1:${PORT}`, trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: `uv run --project .. python e2e/serve.py --port ${PORT}`,
    url: `http://127.0.0.1:${PORT}/api/health`,
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
