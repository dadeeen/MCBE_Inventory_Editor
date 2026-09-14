import { defineConfig } from "@playwright/test";
import { createRequire } from "node:module";
import os from "node:os";
import path from "node:path";

const outputDir = process.env.MCBE_BROWSER_SMOKE_OUTPUT_DIR
  || path.join(os.tmpdir(), "mcbe-inventory-editor-tests", `playwright-${process.pid}`);

let launchOptions;
if (process.platform === "win32") {
  // Chromium 143's randomized TCP ports can collide during loopback smoke tests.
  // Preserve the pinned Playwright defaults: duplicate --disable-features flags
  // replace each other rather than merging. Recheck this internal API on upgrades.
  const require = createRequire(import.meta.url);
  const coreRoot = path.dirname(require.resolve("playwright-core/package.json"));
  const { chromiumSwitches } = require(path.join(coreRoot, "lib/server/chromium/chromiumSwitches.js"));
  const disabled = chromiumSwitches(false).find(arg => arg.startsWith("--disable-features="));
  if (!disabled) throw new Error("Playwright Chromium defaults changed; review the Windows TCP workaround.");
  launchOptions = {
    ignoreDefaultArgs: [disabled],
    args: [`${disabled},TcpPortRandomizationWin`],
  };
}

export default defineConfig({
  testDir: "./tests/browser",
  outputDir,
  timeout: 30_000,
  expect: {
    timeout: 10_000,
  },
  use: {
    baseURL: "http://127.0.0.1:8765",
    browserName: "chromium",
    launchOptions,
  },
});
