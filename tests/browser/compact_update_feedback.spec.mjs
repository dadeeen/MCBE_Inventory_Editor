import { expect, test } from "@playwright/test";
import { NORMAL_BASE_URL, captureBrowserEvidence, collectBrowserErrors } from "./fixtures/app.mjs";

for (const [width, locale] of [[1440, "de"], [390, "en"]]) {
  test(`compact setup and update details survive failure, partial apply and recovery (${width}/${locale})`, async ({ page }) => {
    await page.setViewportSize({ width, height: 980 });
    await page.context().addCookies([{ name: "mcbe_locale", value: locale, url: NORMAL_BASE_URL }]);
    const errors = collectBrowserErrors(page);
    const longCause = "Source conflict <img src=x onerror=alert(1)> " + "identifier:unresolved ".repeat(80);
    const blocked = [
      { section: "effects", reason: longCause },
      { section: "enchants", reason: "Enchantment identities conflict; existing values retained." },
    ];
    const checked = { status: "checked", release: "v-checked", locales: {} };
    const partialQuality = { schema: 1, sections: {
      items: checked,
      ...Object.fromEntries(blocked.map(({ section, reason }) => [section, {
        status: "blocked", release: "v-retained", attempted_release: "v-checked", reason, locales: {},
      }])),
    } };
    let attempts = 0, downloads = 0, unavailableReads = 0;
    let status = { status: "ok", verification: { verified: false }, counts: { items: 10 } };
    await page.route("**/api/item-db/status", route => {
      if (unavailableReads > 0) {
        unavailableReads--;
        return route.fulfill({ json: { success: false, error: "Status unavailable after publication" } });
      }
      return route.fulfill({ json: { success: true, item_db: status } });
    });
    await page.route("**/api/update_db", route => {
      attempts++;
      if (attempts === 1) {
        // All sections are blocked. Only their failure report is published.
        const allBlocked = [...blocked, {section: "items", reason: "Invalid item registry"}];
        const quality = {schema: 1, sections: Object.fromEntries(allBlocked.map(({section, reason}) => [section,
          { status: "blocked", release: "v-retained", attempted_release: "v-checked", reason, locales: {} }]))};
        status = {...status, update_quality: quality};
        return route.fulfill({ json: {
          success: false, outcome: "failed", update_committed: true, reloaded: true, item_db: status, error: longCause, hint: "Retry after source repair.",
          summary: { schema: 1, status: "incomplete", blocked: allBlocked, sections: {}, quality },
        } });
      }
      const partial = attempts === 2;
      if (partial) unavailableReads = 2;
      status = { ...status, verification: { verified: !partial }, update_quality: partial
        ? partialQuality : { schema: 1, sections: { items: checked, effects: checked, enchants: checked } } };
      return route.fulfill({ json: {
        success: !partial, outcome: partial ? "partial" : "updated", update_committed: true, reloaded: true,
        item_db: status, summary: { schema: 1, status: partial ? "incomplete" : "available",
          blocked: partial ? blocked : [], sections: {}, quality: status.update_quality },
      } });
    });
    await page.route("**/api/icons/status*", route => route.fulfill({ json: {
      success: true, icons: {}, count: 0, sources: [], warnings: [], missing_banner_patterns: [],
    } }));
    await page.route("**/api/icons/vanilla/update", route => {
      downloads++;
      return route.fulfill({ json: { success: true } });
    });
    await page.route("**/api/scan_worlds", route => route.fulfill({ json: { success: true, worlds: [] } }));
    await page.route("**/api/server_status", route => route.fulfill({ json: {
      success: true, status: "offline", write_gate: { allowed: true, read_allowed: true },
    } }));
    await page.route("**/api/diagnostics/status", route => route.fulfill({ json: {
      success: true, mode: "local", data_root: { writable: true }, write_gate: { allowed: true, read_allowed: true },
    } }));
    await page.goto(NORMAL_BASE_URL + "/");
    const overlay = page.locator("#firstRunSetupOverlay");
    const row = overlay.locator('[data-first-run-todo="item_db"]');
    const state = row.locator('[data-role="state"]');
    const details = row.locator('[data-role="details"]');
    const content = row.locator('[data-role="details-content"]');
    await expect(overlay).toBeVisible();
    await row.locator('[data-role="run"]').click();
    await expect(state).toHaveText(locale === "de" ? "Fehlgeschlagen. Details prüfen." : "Failed. Check the details.");
    await expect(row).toHaveClass(/is-error/);
    await expect(page.locator("#statusStackButton")).toHaveClass(/error/);
    await expect(page.locator("#updateDbResult")).toHaveAttribute('data-state', 'failed');
    await expect(page.locator("#updateDbResult strong").first()).toHaveText(locale === "de" ? "Fehlgeschlagen – nichts übernommen" : "Failed – no changes applied");
    await expect(page.locator('#updateDbOutput')).toContainText(locale === 'de' ? 'Prüfbericht gespeichert und Status neu geladen.' : 'Verification report saved and status reloaded.');
    await expect(page.locator('#updateDbOutput')).not.toContainText(locale === 'de' ? 'Item-Datenbank aktualisiert.' : 'Item database updated.');
    await expect(content).toBeHidden();
    await expect(content).toContainText(longCause);
    await expect(content).toContainText(blocked[1].reason);
    await expect(content.locator("img, script")).toHaveCount(0);
    await captureBrowserEvidence(page, `compact-failure-${width}-${locale}`, ".first-run-box");
    await details.locator("summary").focus();
    await page.keyboard.press("Enter");
    await expect(content).toBeVisible();
    await page.keyboard.press("Tab");
    await expect(content).toBeFocused();
    expect(await content.evaluate(node => node.scrollHeight > node.clientHeight)).toBe(true);
    await page.keyboard.press("Tab");
    await expect(row.locator('[data-role="run"]')).toBeFocused();
    await captureBrowserEvidence(page, `compact-failure-details-${width}-${locale}`, ".first-run-box");
    await page.keyboard.press("Enter");
    for (const remaining of [1, 0]) {
      await expect.poll(() => unavailableReads).toBe(remaining);
      await expect(state).toHaveText(locale === "de" ? "Änderungen gespeichert. Status erneut prüfen." : "Changes saved. Check the status again.");
      await expect(content).toContainText(blocked[1].reason);
      await expect(row.locator('[data-role="run"]')).toHaveText(locale === "de" ? "Status erneut prüfen" : "Check status again");
      await row.locator('[data-role="run"]').click();
    }
    await expect(state).toHaveText(locale === "de" ? "Teilweise aktualisiert. Details prüfen." : "Partially updated. Check the details.");
    await expect(content).toBeHidden();
    await expect(content).not.toContainText("Retry after source repair.");
    await expect(content).toContainText("v-retained");
    await expect(row).toHaveClass(/is-warning/);
    await expect(row).not.toHaveClass(/is-error|is-done/);
    await captureBrowserEvidence(page, `compact-partial-${width}-${locale}`, ".first-run-box");
    await page.locator("#btnFirstRunSetupClose").click();
    await page.locator('.app-section-nav button[data-workflow-view="tools"]').click();
    await page.locator('.tab-btn-dash[data-tab-dash="dashUpdate"]').click();
    await expect(page.locator("#updateDbResult")).not.toContainText("Source conflict");
    await expect(page.locator("#updateDbAudit")).toBeHidden();
    await page.locator("#updateDbDetails > summary").focus();
    await page.keyboard.press("Enter");
    await expect(page.locator("#updateDbAudit")).toBeVisible();
    for (const cause of blocked) await expect(page.locator("#updateDbAudit")).toContainText(cause.reason);
    await expect(page.locator("#updateDbAudit img, #updateDbAudit script")).toHaveCount(0);
    await page.locator("#btnUpdateDbApply").click();
    await page.locator("#confirmOk").click();
    await expect(page.locator("#updateDbResult")).toContainText(locale === "de" ? "Aktualisierung abgeschlossen" : "Update completed");
    await expect(page.locator("#updateDbAudit")).not.toContainText("Source conflict");
    await expect(page.locator("#updateDbAudit")).toBeHidden();
    expect(attempts).toBe(3);
    expect(downloads).toBe(0);
    await page.locator('.app-section-nav [data-workflow-view="world"]').click();
    await page.locator('#btnSetupTodoBanner').click();
    await expect(state).toHaveText(locale === "de" ? "Erledigt." : "Done.");
    await expect(details).toBeHidden();
    await expect(content).not.toContainText(longCause);
    await page.locator("#btnFirstRunSetupClose").click();
    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
    await page.reload();
    await expect(overlay).toBeHidden();
    await expect(page.locator("#itemDbStatusPanel")).not.toContainText("v-retained");
    expect(errors).toEqual([]);
  });
}
