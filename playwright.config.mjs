import { defineConfig } from "@playwright/test";
import os from "node:os";
import path from "node:path";

const outputDir = process.env.MCBE_BROWSER_SMOKE_OUTPUT_DIR
  || path.join(os.tmpdir(), "mcbe-inventory-editor-tests", `playwright-${process.pid}`);

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
  },
});
