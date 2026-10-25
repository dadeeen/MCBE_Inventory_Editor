import { defineConfig } from "@playwright/test";
import { createRequire } from "node:module";
import os from "node:os";
import path from "node:path";

const outputDir = process.env.MCBE_BROWSER_SMOKE_OUTPUT_DIR
  || path.join(os.tmpdir(), "mcbe-inventory-editor-tests", `playwright-${process.pid}`);

let launchOptions;
if (process.platform === "win32") {
  // Chromium's randomized TCP ports can fail during loopback smoke tests.
  // Preserve the pinned Playwright defaults: duplicate --disable-features flags
  // replace each other rather than merging. Recheck this internal API on upgrades.
  const require = createRequire(import.meta.url);
  const { server } = require("playwright-core/lib/coreBundle");
  const chromium = server.createPlaywright({ sdkLanguage: "javascript" }).chromium;
  const disabled = chromium._innerDefaultArgs({}).find(arg => arg.startsWith("--disable-features="));
  if (!disabled) throw new Error("Playwright Chromium defaults changed; review the Windows TCP workaround.");
  launchOptions = {
    ignoreDefaultArgs: [disabled],
    args: [`${disabled},TcpPortRandomizationWin`],
  };
}

export default defineConfig({
  testDir: "./tests/browser",
  // The UI suites share the normal/viewer servers and persistent settings.
  // Keep cross-file execution serial until each worker owns its own servers;
  // read quota isolation in browser_smoke.py does not isolate writes/settings.
  workers: 1,
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
    launchOptions,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
});
