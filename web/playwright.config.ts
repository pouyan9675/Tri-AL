/**
 * End-to-end tests against the real API on the installed database in ../data (607k
 * trials), served the production way: `tri-al serve` with the built front end. Build first:
 *
 *   npm run build && npm run test:e2e
 *
 * They use the installed Google Chrome (no browser download). Not run in CI, which has no
 * database; `TRI_AL_E2E_URL` points them at a server that's already running.
 */
import { defineConfig, devices } from "@playwright/test";

const PORT = 8765;
const url = process.env.TRI_AL_E2E_URL ?? `http://127.0.0.1:${PORT}`;

export default defineConfig({
  testDir: "e2e",
  timeout: 30_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: url,
    channel: "chrome",
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "desktop",
      use: {
        ...devices["Desktop Chrome"],
        channel: "chrome",
        viewport: { width: 1440, height: 900 },
      },
    },
  ],
  webServer: process.env.TRI_AL_E2E_URL
    ? undefined
    : {
        command: `uv run tri-al serve --port ${PORT} --no-job-worker`,
        cwd: "..",
        url: `${url}/api/meta`,
        reuseExistingServer: true,
        timeout: 120_000,
        stdout: "ignore",
      },
});
