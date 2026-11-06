import { defineConfig } from "@playwright/test";
import os from "node:os";
import path from "node:path";

const outputDir = process.env.MCBE_BROWSER_SMOKE_OUTPUT_DIR
  || path.join(os.tmpdir(), "mcbe-inventory-editor-tests", `playwright-${process.pid}`);

export default defineConfig({
  testDir: "./tests/browser",
  // The UI suites share the normal/viewer servers and persistent settings.
  // Keep cross-file execution serial until each worker owns its own servers;
  // read quota isolation in browser_smoke.py does not isolate writes/settings.
  workers: 1,
  forbidOnly: Boolean(process.env.CI),
  globalTimeout: 30 * 60_000,
  outputDir,
  timeout: 30_000,
  expect: {
    timeout: 10_000,
  },
  use: {
    // Most assertions use German UI literals; locale-specific cases override it.
    locale: "de-DE",
    baseURL: "http://127.0.0.1:8765",
    browserName: "chromium",
    launchOptions: { chromiumSandbox: true },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
});
