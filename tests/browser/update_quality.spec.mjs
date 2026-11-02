import { expect, test } from "@playwright/test";
import { NORMAL_BASE_URL, captureBrowserEvidence, collectBrowserErrors } from "./fixtures/app.mjs";

const fallbackQuality = {
  schema: 1,
  sections: { effects: { status: "checked", release: "v-test", attempted_release: "v-test", locales: {
    de: { total: 2, official: 0, fallbacks: [
      { id: "freezing", source: "curated" }, { id: "<img src=x onerror=alert(1)>", source: "identifier" },
    ] },
    en: { total: 2, official: 1, fallbacks: [{ id: "freezing", source: "other_language" }] },
  } } },
};
const partialQuality = {
  schema: 1,
  sections: {
    items: { status: "checked", release: "v-test", attempted_release: "v-test", locales: {} },
    effects: { status: "blocked", release: "v-old", attempted_release: "v-test", reason: "Doppelte numerische IDs", locales: {} },
  },
};
const reviewedQuality = {
  schema: 1,
  sections: { items: { status: "checked", release: "v-test", locales: {
    de: { total: 3, official: 1, fallbacks: [
      { id: "minecraft:ice_ball", source: "curated", reason: "editorial" },
      { id: "minecraft:music_disc_11", source: "composed", reason: "composed" },
    ], retained: [{ id: "minecraft:petrified_oak_slab", source: "curated", reason: "editorial" }] },
    en: { total: 4, official: 2, fallbacks: [
      { id: "minecraft:chemical_heat", source: "curated", reason: "documented" },
      { id: "minecraft:colored_torch_bp", source: "curated", reason: "editorial" },
    ], retained: [{ id: "minecraft:oak_chest_boat", source: "existing" }] },
  } } },
};

fallbackQuality.sections.items = { status: "checked", release: "v-test", locales: {
  de: { total: 2, official: 0, fallbacks: [
    { id: "minecraft:music_disc_11", source: "existing", reason: "composed" },
    { id: "minecraft:potion", source: "curated", reason: "category" },
  ] },
} };

async function prepareQualityFlow(page, { width, locale, mode }) {
  await page.setViewportSize({ width, height: 980 });
  await page.context().addCookies([{ name: "mcbe_locale", value: locale, url: NORMAL_BASE_URL }]);
  const errors = collectBrowserErrors(page);
  let updated = false, updates = 0, downloads = 0;
  const quality = mode === "partial" ? partialQuality : mode === "reviewed" ? reviewedQuality : fallbackQuality;
  const itemDb = () => ({
    status: "ok", source_version_present: true, source_version: { resource_pack_release: "v-test" },
    verification: { verified: updated && mode !== "partial" }, counts: { items: 20, effects: 2, enchantments: 1 },
    update_quality: updated ? quality : undefined,
  });
  await page.route("**/api/item-db/status", route => route.fulfill({ json: { success: true, item_db: itemDb() } }));
  await page.route("**/api/update_db", route => {
    const current = updated;
    updates++;
    updated = true;
    const partial = mode === "partial";
    return route.fulfill({ json: {
      success: !partial, returncode: partial ? 1 : 0, update_committed: !current, reloaded: true,
      outcome: partial ? "partial" : current ? "current" : mode === "reviewed" ? "updated" : "updated_with_warnings",
      verification_required: partial, item_db: itemDb(),
      summary: { schema: 1, status: partial ? "incomplete" : current ? "current" : "available",
        quality, sections: {},
        blocked: partial ? [{ section: "effects", reason: "Doppelte numerische IDs" }] : [],
      },
    } });
  });
  await page.route("**/api/icons/status*", route => route.fulfill({ json: {
    success: true, icons: {}, count: 1, sources: [], warnings: [], missing_banner_patterns: [],
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
  await expect(overlay).toBeVisible();
  const row = overlay.locator('[data-first-run-todo="item_db"]');
  return { overlay, row, errors, counts: () => ({ updates, downloads }) };
}

async function openTools(page) {
  await page.locator("#btnFirstRunSetupClose").click();
  await page.locator('.app-section-nav button[data-workflow-view="tools"]').click();
  await page.locator('.tab-btn-dash[data-tab-dash="dashUpdate"]').click();
}

for (const [width, locale] of [[1440, "de"], [390, "en"]]) {
  test(`fallback names finish setup and remain visible after reload (${width}/${locale})`, async ({ page }) => {
    const flow = await prepareQualityFlow(page, { width, locale, mode: "fallback" });
    await flow.row.locator('[data-role="run"]').focus();
    await page.keyboard.press("Enter");
    await expect(flow.row.locator('[data-role="mark"]')).toHaveText("✓");
    await expect(flow.row).not.toHaveClass(/is-error/);
    await expect(flow.row.locator('[data-role="state"]')).toHaveText(locale === "de" ? "Erledigt. Hinweise in den Details." : "Done. See the details for notes.");
    await expect(flow.row.locator('[data-role="details-content"]')).toBeHidden();
    await expect(flow.row).toContainText(locale === "de" ? "Für 2 Sprachwerte" : "For 2 language values");
    await expect(flow.row.locator('[data-role="run"]')).toBeHidden();
    await captureBrowserEvidence(page, `update-names-setup-${width}-${locale}`, ".first-run-box");
    await openTools(page);
    const result = page.locator("#updateDbResult");
    await expect(result).toContainText(locale === "de" ? "Aktualisiert mit Hinweisen" : "Updated with notes");
    await expect(result).not.toContainText(locale === "de" ? "Für 2 Sprachwerte" : "For 2 language values");
    await expect(page.locator('#updateDbAudit')).toBeHidden();
    await expect(page.locator('#updateDbAudit')).toContainText(locale === "de" ? "Für 2 Sprachwerte" : "For 2 language values");
    // A second check can confirm current data even while names still use fallbacks.
    await page.locator("#btnUpdateDbDryRun").click();
    await expect(page.locator("#btnUpdateDbApply")).toBeDisabled();
    expect(flow.counts()).toEqual({ updates: 2, downloads: 0 });
    await page.reload();
    await expect(flow.overlay).toBeHidden();
    await page.locator('.app-section-nav button[data-workflow-view="tools"]').click();
    await page.locator('.tab-btn-dash[data-tab-dash="dashUpdate"]').click();
    const status = page.locator("#itemDbStatusPanel");
    await expect(status).toContainText(locale === "de" ? "geprüft mit Hinweisen" : "verified with notes");
    await expect(status).toContainText(locale === "de" ? "0 von 2 offiziellen Namen" : "0 of 2 official names");
    const details = status.locator("[data-db-quality] details");
    await details.locator("summary").click();
    await expect(details).toContainText("<img src=x onerror=alert(1)>");
    await expect(details.locator("img")).toHaveCount(0);
    await expect(details).toContainText(locale === "de" ? "technische Kennung" : "technical identifier");
    await expect(details).toContainText(locale === "de" ? "andere Sprache" : "another language");
    await expect(details).toContainText(locale === "de" ? "Bezeichnung und Titel stehen in der Quelle getrennt" : "the source provides the name and title separately");
    await expect(details).toContainText(locale === "de" ? "geprüfte Sammelbezeichnung für Varianten" : "reviewed category name for variants");
    await expect(status).toContainText(locale === "de" ? "Deutsch und Englisch werden getrennt gezählt" : "German and English are counted separately");
    await captureBrowserEvidence(page, `update-names-status-${width}-${locale}`, "#itemDbStatusPanel");
    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
    expect(flow.errors).toEqual([]);
  });

  test(`reviewed translations finish setup without an action warning (${width}/${locale})`, async ({ page }) => {
    const flow = await prepareQualityFlow(page, { width, locale, mode: "reviewed" });
    await flow.row.locator('[data-role="run"]').click();
    await expect(flow.row.locator('[data-role="mark"]')).toHaveText("✓");
    await expect(flow.row).not.toHaveClass(/is-warning|is-error/);
    await expect(flow.row.locator('[data-role="state"]')).toHaveText(locale === "de" ? "Erledigt." : "Done.");
    await expect(flow.row.locator('[data-role="details-content"]')).toBeHidden();
    await expect(flow.row).toContainText(locale === "de" ? "Kein Handlungsbedarf wegen der Namen" : "No action is needed for these names");
    await expect(flow.row).not.toContainText("160");
    await captureBrowserEvidence(page, `reviewed-names-setup-${width}-${locale}`, ".first-run-box");
    await openTools(page);
    const status = page.locator("#itemDbStatusPanel");
    await expect(status.locator(".item-db-status-hero")).toHaveClass(/ok/);
    await page.locator("#btnUpdateDbDryRun").click();
    await expect(page.locator("#btnUpdateDbApply")).toBeDisabled();
    await page.reload();
    await expect(flow.overlay).toBeHidden();
    await page.locator('.app-section-nav button[data-workflow-view="tools"]').click();
    await page.locator('.tab-btn-dash[data-tab-dash="dashUpdate"]').click();
    await expect(status.locator(".item-db-status-hero")).toHaveClass(/ok/);
    const details = status.locator("[data-db-quality] details");
    await expect(details).not.toHaveAttribute("open");
    await details.locator("summary").focus();
    await page.keyboard.press("Enter");
    await expect(details).toContainText(locale === "de" ? "redaktionelle Bezeichnung des Editors" : "editorial label by the editor");
    await expect(details).toContainText(locale === "de" ? "Bezeichnung aus offizieller Mojang-Dokumentation" : "name from official Mojang documentation");
    await expect(details).toContainText(locale === "de" ? "beibehaltener Name" : "preserved name");
    await expect(details).toContainText("minecraft:chemical_heat");
    await expect(details).toContainText("minecraft:colored_torch_bp");
    await expect(details).toContainText("minecraft:petrified_oak_slab");
    await captureBrowserEvidence(page, `reviewed-names-status-${width}-${locale}`, "#itemDbStatusPanel");
    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
    expect(flow.counts()).toEqual({ updates: 2, downloads: 0 });
    expect(flow.errors).toEqual([]);
  });

  test(`partial updates retain the blocked section and setup warning after reload (${width}/${locale})`, async ({ page }) => {
    const flow = await prepareQualityFlow(page, { width, locale, mode: "partial" });
    await flow.row.locator('[data-role="run"]').click();
    await expect(flow.row).toHaveClass(/is-warning/);
    await expect(flow.row).not.toHaveClass(/is-done|is-error/);
    await expect(flow.row.locator('[data-role="state"]')).toHaveText(locale === "de" ? "Teilweise aktualisiert. Details prüfen." : "Partially updated. Check the details.");
    await expect(flow.row.locator('[data-role="state"]')).not.toContainText('Doppelte numerische IDs');
    await expect(flow.row.locator('[data-role="details-content"]')).toBeHidden();
    await expect(flow.row).toContainText("Doppelte numerische IDs");
    await expect(flow.row).toContainText("v-old");
    await expect(flow.row.locator('[data-role="run"]')).toBeEnabled();
    await captureBrowserEvidence(page, `update-partial-setup-${width}-${locale}`, ".first-run-box");
    await page.reload();
    await expect(flow.overlay).toBeVisible();
    await expect(flow.row).toHaveClass(/is-warning/);
    await expect(flow.row.locator('[data-role="state"]')).toHaveText(locale === "de" ? "Prüfung unvollständig. Details prüfen." : "Verification incomplete. Check the details.");
    await expect(flow.row).toContainText("Doppelte numerische IDs");
    await openTools(page);
    const status = page.locator("#itemDbStatusPanel");
    await expect(status).toContainText(locale === "de" ? "Prüfung unvollständig" : "Verification incomplete");
    await expect(status).toContainText("v-old");
    expect(flow.counts()).toEqual({ updates: 1, downloads: 0 });
    expect(flow.errors).toEqual([]);
  });
}
