import { expect, test } from "@playwright/test";
import {
  NORMAL_BASE_URL,
  collectBrowserErrors,
  colorComponents,
  compositeColor,
  contrastRatio,
  openAppWithEmptyWorldScan,
  openDragFixture,
  selectSetting,
  selectLayout,
} from "./fixtures/app.mjs";

test("player stats, abilities and hints remain inside every layout on mobile", async ({ page }) => {
  test.setTimeout(90_000);
  const errors = collectBrowserErrors(page);
  await page.route("**/api/world/presence", route => route.fulfill({ json: { success: true, other_sessions: [] } }));
  for (const locale of ["de", "en"]) {
    await page.context().addCookies([{ name: "mcbe_locale", value: locale, url: NORMAL_BASE_URL }]);
    await page.setViewportSize({ width: 1440, height: 900 });
    await openDragFixture(page);
    await expect(page.locator("html")).toHaveAttribute("lang", locale);
    await selectSetting(page, "themeSelect", "light");
    for (const layout of ["classic", "studio", "focus"]) {
      await selectLayout(page, layout);
      await page.locator(`[data-workflow-view="${layout === "classic" ? "player" : "player-edit"}"]`).first().click();
      for (const tab of ["dashStats", "dashEffects"]) {
        await page.locator(`[data-tab-dash="${tab}"]`).click();
        const panel = page.locator(`#${tab}`);
        for (const width of [1440, 390, 320]) {
          await page.setViewportSize({ width, height: 900 });
          await expect(panel).toBeVisible();
          expect(await panel.evaluate(el => el.scrollWidth - el.clientWidth)).toBeLessThanOrEqual(1);
          const clipped = await panel.evaluate(el => {
            const panel = el.getBoundingClientRect();
            return Array.from(el.querySelectorAll("input, select, label, .field-note")).filter(field => {
              if (!field.getClientRects().length) return false;
              const rect = field.getBoundingClientRect();
              return rect.left < panel.left - 1 || rect.right > panel.right + 1;
            }).map(field => field.id || field.textContent);
          });
          expect(clipped, `${locale}/${layout}/${tab}/${width}`).toEqual([]);
          if (process.env.MCBE_BROWSER_EVIDENCE_DIR) await panel.screenshot({
            path: `${process.env.MCBE_BROWSER_EVIDENCE_DIR}/player-values-${locale}-${layout}-${tab}-${width}.png`,
            animations: "disabled",
          });
        }
      }
    }
  }
  expect(errors).toEqual([]);
});

test("help and long confirmations remain reachable in narrow and short windows", async ({ page }) => {
  const browserErrors = collectBrowserErrors(page);
  await openDragFixture(page);
  for (const layout of ["classic", "studio", "focus"]) {
    await selectLayout(page, layout);
    for (const theme of ["light", "dark"]) {
      await page.evaluate(theme => { document.documentElement.dataset.theme = theme; }, theme);
      for (const [width, height] of [[320, 740], [390, 844], [844, 390]]) {
        await page.setViewportSize({ width, height });
        await page.locator("#btnHelp").click();
        const help = page.locator(".help-box");
        await expect(help).toBeVisible();
        const box = await help.boundingBox();
        expect(box.y).toBeGreaterThanOrEqual(15);
        expect(box.y + box.height).toBeLessThanOrEqual(height - 15);
        expect(await help.evaluate(el => el.scrollWidth - el.clientWidth)).toBeLessThanOrEqual(1);
        const content = page.locator(".help-content");
        expect(await content.evaluate(el => el.scrollWidth - el.clientWidth)).toBeLessThanOrEqual(1);
        await content.evaluate(el => { el.scrollTop = el.scrollHeight; });
        await expect(page.locator(".help-hint")).toBeInViewport();
        await page.locator("#btnHelpClose").click();
        await expect(page.locator("#helpOverlay")).toBeHidden();

        await page.evaluate(() => {
          void showConfirmDialog("Wichtiger Hinweis: Prüfe die ausgewählte Welt und alle Änderungen.\n".repeat(15));
        });
        const confirm = page.locator("#confirmOverlay .modal-box");
        const confirmBox = await confirm.boundingBox();
        expect(confirmBox.y).toBeGreaterThanOrEqual(15);
        expect(confirmBox.y + confirmBox.height).toBeLessThanOrEqual(height - 15);
        await page.locator("#confirmCancel").click();
        await expect(page.locator("#confirmOverlay")).toBeHidden();
        await page.evaluate(() => { void openSaveReview(buildChangeSummary()); });
        const review = page.locator(".save-review-box");
        expect(await review.evaluate(el => el.scrollWidth - el.clientWidth)).toBeLessThanOrEqual(1);
        await expect(page.locator("#btnSaveReviewConfirm")).toBeInViewport();
        await page.locator("#btnSaveReviewCancel").click();
        await expect(page.locator("#saveReviewOverlay")).toBeHidden();
      }
    }
  }
  expect(browserErrors).toEqual([]);
});

test("status entries keep the color of their kind and stay readable in every theme", async ({ page }) => {
  await openAppWithEmptyWorldScan(page);
  for (const theme of ["dark", "system", "light", "minecraft"]) {
    await page.evaluate(value => { document.documentElement.dataset.theme = value; }, theme);
    const entries = await page.evaluate(() => {
      const panel = document.getElementById("statusStackPanel");
      const rgba = value => {
        const [r, g, b, a = 1] = value.match(/[\d.]+/g).map(Number);
        return { r, g, b, a };
      };
      const over = (top, bottom) => Object.fromEntries(["r", "g", "b"].map(channel => [
        channel, top[channel] * top.a + bottom[channel] * (1 - top.a),
      ]).concat([["a", 1]]));
      const luminance = color => ["r", "g", "b"].map(channel => {
        const value = color[channel] / 255;
        return value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
      }).reduce((sum, value, index) => sum + value * [0.2126, 0.7152, 0.0722][index], 0);
      const contrast = (first, second) => {
        const [light, dark] = [luminance(first), luminance(second)].sort((a, b) => b - a);
        return (light + 0.05) / (dark + 0.05);
      };
      const page = document.createElement("div");
      page.style.color = "var(--bg-main)";
      panel.appendChild(page);
      const panelBackground = over(rgba(getComputedStyle(panel).backgroundColor), rgba(getComputedStyle(page).color));
      page.remove();
      return Object.fromEntries(["success", "info", "warning", "error"].map(kind => {
        const probe = document.createElement("div");
        probe.className = `status-stack-entry save-status ${kind}`;
        probe.innerHTML = '<span class="status-stack-time">12:00</span>';
        panel.appendChild(probe);
        const style = getComputedStyle(probe);
        const background = over(rgba(style.backgroundColor), panelBackground);
        const entry = {
          color: style.color,
          text: Number(contrast(rgba(style.color), background).toFixed(2)),
          time: Number(contrast(rgba(getComputedStyle(probe.firstChild).color), background).toFixed(2)),
        };
        probe.remove();
        return [kind, entry];
      }));
    });
    const detail = `${theme}: ${JSON.stringify(entries)}`;
    // An error or a plain information must not look like a success.
    expect(new Set(Object.values(entries).map(entry => entry.color)).size, detail).toBe(4);
    for (const entry of Object.values(entries)) {
      expect(entry.text, detail).toBeGreaterThanOrEqual(4.5);
      expect(entry.time, detail).toBeGreaterThanOrEqual(4.5);
    }
  }
});

test("system theme matches explicit themes and follows preference changes", async ({ page }) => {
  await page.route("**/api/world/presence", route => route.fulfill({ json: { success: true, other_sessions: [] } }));
  await openDragFixture(page);
  const colors = () => page.evaluate(() => ["body", "#inventoryContainer", "#detailEditorPanel"].map(selector => {
    const style = getComputedStyle(document.querySelector(selector));
    return { color: style.color, background: style.backgroundColor, border: style.borderColor };
  }));
  const expected = {};
  for (const theme of ["light", "dark"]) {
    await selectSetting(page, "themeSelect", theme);
    expected[theme] = await colors();
  }
  await selectSetting(page, "themeSelect", "system");
  for (const colorScheme of ["light", "dark", "light"]) {
    await page.emulateMedia({ colorScheme });
    await expect.poll(colors).toEqual(expected[colorScheme]);
    await expect(page.locator("#themeSelect")).toHaveValue("system");
  }
  // A fixed choice ignores later operating-system changes.
  await selectSetting(page, "themeSelect", "dark");
  await page.emulateMedia({ colorScheme: "dark" });
  await page.emulateMedia({ colorScheme: "light" });
  await expect.poll(colors).toEqual(expected.dark);
  await selectSetting(page, "themeSelect", "system");
  await page.reload();
  await expect(page.locator("#themeSelect")).toHaveValue("system");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
});

test("load errors and notifications stay opaque and readable in every theme and layout", async ({ page }) => {
  await openAppWithEmptyWorldScan(page);
  await page.evaluate(() => {
    MCBEWorldStatusView.applyLoadErrorPanel(document.getElementById("loadErrorPanel"),
      MCBEWorldStatusView.loadErrorHtml({ message: "Testfehler", pathText: "/worlds/test" }));
    for (const kind of ["success", "warning", "error"]) MCBEUiFeedback.showToast("Testmeldung", kind, 60000);
  });
  for (const layout of ["classic", "studio", "focus"]) {
    await selectLayout(page, layout);
    for (const [theme, colorScheme] of [["dark", "dark"], ["light", "light"], ["minecraft", "dark"], ["system", "light"]]) {
      await page.emulateMedia({ colorScheme });
      if (!(await page.locator("#themeSelect").isVisible())) await page.locator("#focusSettingsToggle").click();
      await selectSetting(page, "themeSelect", theme);
      const samples = await page.evaluate(() => {
        const panel = document.getElementById("loadErrorPanel");
        const backdrop = document.createElement("span");
        backdrop.style.color = "var(--bg-main)";
        panel.appendChild(backdrop);
        const base = getComputedStyle(backdrop).color;
        backdrop.remove();
        const ancestors = [];
        for (let node = panel.parentElement; node; node = node.parentElement) ancestors.unshift(getComputedStyle(node).backgroundColor);
        return {
          base, ancestors,
          error: getComputedStyle(panel.querySelector(".load-error-title")).color,
          errorBackgrounds: getComputedStyle(panel).backgroundImage.match(/rgba?\([^)]+\)/g),
          logBackground: getComputedStyle(document.getElementById("statusStackPanel")).backgroundColor,
          toasts: [...document.querySelectorAll(".toast")].map(node => ({
            kind: node.className, color: getComputedStyle(node).color, background: getComputedStyle(node).backgroundColor,
          })),
        };
      });
      const detail = `${layout}/${theme}/${colorScheme}`;
      const parentBackground = samples.ancestors.reduce((background, layer) => compositeColor(layer, background), colorComponents(samples.base));
      for (const layer of samples.errorBackgrounds) {
        expect(contrastRatio(samples.error, compositeColor(layer, parentBackground)), `${detail} load error`).toBeGreaterThanOrEqual(4.5);
      }
      expect(colorComponents(samples.logBackground).a, `${detail} status log opacity`).toBe(1);
      for (const toast of samples.toasts) {
        expect(colorComponents(toast.background).a, `${detail} ${toast.kind} opacity`).toBe(1);
        expect(contrastRatio(toast.color, toast.background), `${detail} ${toast.kind} contrast`).toBeGreaterThanOrEqual(4.5);
      }
    }
  }
});

test("status overview follows the server status shown in the header", async ({ page }) => {
  const browserErrors = collectBrowserErrors(page);
  const onlineGate = {
    allowed: false,
    reason: "Server läuft noch. Bitte Server stoppen.",
    server_status: { status: "online" },
  };
  let serverStatus = { success: true, server_status: onlineGate.server_status, write_gate: onlineGate };
  await page.route("**/api/server_status", route => route.fulfill({ json: serverStatus }));
  await page.clock.install();
  await openAppWithEmptyWorldScan(page);

  await page.locator('.app-section-nav button[data-workflow-view="tools"]').click();
  const hero = page.locator("#statusCenterPanel .status-hero");
  const writing = page.locator("#statusCenterPanel .status-tile").filter({ hasText: "Schreiben" });
  await expect(hero).toHaveClass(/\berror\b/);
  await expect(hero).toContainText("Prüfen");
  await expect(writing.locator("strong")).toHaveText("gesperrt");

  // Loading the diagnostics again keeps the server status of the header.
  const diagnostics = page.waitForResponse(response => response.url().endsWith("/api/diagnostics/status"));
  await page.locator("#btnRefreshRuntimeDiagnostics").click();
  await diagnostics;
  await expect(hero).toHaveClass(/\berror\b/);
  await expect(writing.locator("strong")).toHaveText("gesperrt");

  // The next poll after the server stopped clears the overview.
  const offlineGate = { allowed: true, server_status: { status: "offline" } };
  serverStatus = { success: true, server_status: offlineGate.server_status, write_gate: offlineGate };
  await page.clock.fastForward(10_000);
  await expect(writing.locator("strong")).toHaveText("bereit");
  await expect(hero).not.toHaveClass(/\berror\b/);

  // The test server runs in local mode without a server address: its answer
  // is an unknown status, and writing works after confirming it.
  await page.unroute("**/api/server_status");
  await page.clock.fastForward(10_000);
  await expect(writing.locator("strong")).toHaveText("nach Bestätigung");
  await expect(writing).toHaveClass(/\bwarning\b/);
  await expect(hero).not.toHaveClass(/\berror\b/);
  expect(browserErrors, `unexpected browser errors: ${JSON.stringify(browserErrors)}`).toEqual([]);
});
