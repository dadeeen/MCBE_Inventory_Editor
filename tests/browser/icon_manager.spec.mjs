import { expect, test } from "@playwright/test";
import {
  NORMAL_BASE_URL,
  collectBrowserErrors,
  openAppWithEmptyWorldScan,
  openDragFixture,
  captureBrowserEvidence,
  selectSetting,
  selectLayout,
} from "./fixtures/app.mjs";

for (const layout of ['classic', 'studio', 'focus']) for (const theme of ['dark', 'light']) for (const language of ['de', 'en']) {
  test(`database result summary (${layout}/${theme}/${language})`, async ({page}) => {
    test.setTimeout(60_000);
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.context().addCookies([{name: 'mcbe_locale', value: language, url: NORMAL_BASE_URL}]);
    await page.route('**/api/item-db/status', route => route.fulfill({json: {success: true, item_db: {
      status: 'ok', verification: {verified: true}, source_version_present: true,
      source_version: {resource_pack_release: 'v1.26.40.05'}, counts: {items: 2048, effects: 37, enchantments: 42},
    }}}));
    let state = 'available';
    let issues = [];
    let includeNames = true;
    await page.route('**/api/update_db', route => route.fulfill({json: {
      success: state !== 'incomplete', returncode: state === 'incomplete' ? 1 : 0,
      error: state === 'incomplete' ? 'Synthetic source failure' : undefined,
      output: 'Synthetic detailed log', update_review_token: 'a'.repeat(64), resource_pack_release: 'v1.26.50.4',
      summary: {schema: 1, status: state, scope: 'all', previous_release: state === 'current' ? 'v1.26.50.4' : 'v1.26.40.05', release: 'v1.26.50.4', blocked: [],
        sections: state === 'available' ? {
          items: {added: 124, removed: 8, changed: 87}, stack_limits: {added: 1505, removed: 0, changed: 0},
          effects: {added: 0, removed: 0, changed: 37}, durability: {added: 0, removed: 0, changed: 3},
          addable_items: {added: 32, removed: 0, changed: 0},
        } : {},
        change_details: state === 'available' ? {
          stack_limits: {before_count: 123, after_count: 1628, added_existing_items: 1414},
          effects: {descriptions_only: 37, other_changes: 0}, items: {removed_non_items: ['minecraft:canbreak']},
          durability: {changes: [{id: 'minecraft:fishing_rod', before: 64, after: 384}]},
        } : {},
        audit: {checked_items: 2164, issues, expected_name_differences: includeNames ? [
          ['bed', 'Weißes Bett', 'White Bed', 'Bett', 'Bed'],
          ['yellow_flower', 'Löwenzahn', 'Dandelion', 'Blume', 'Flower'],
          ['stonecutter', 'Steinsäge (alt, ohne Funktion)', 'Stonecutter (Legacy, No Function)', 'Steinsäge', 'Stonecutter'],
        ].flatMap(([id, de, en, sourceDe, sourceEn]) => [
          {id: `minecraft:${id}`, locale: 'de', catalog: de, source: sourceDe},
          {id: `minecraft:${id}`, locale: 'en', catalog: en, source: sourceEn},
        ]) : []}},
    }}));
    await openAppWithEmptyWorldScan(page);
    await selectLayout(page, layout);
    await selectSetting(page, 'themeSelect', theme);
    await page.locator('.app-workflow-nav [data-workflow-view="tools"]').click();
    await page.locator('[data-tab-dash="dashUpdate"]').click();
    await expect(page.locator('.item-db-version-line')).toContainText('Mojang v1.26.40.05');
    await expect(page.locator('.item-db-status-hero')).not.toContainText(language === 'en' ? 'checked' : 'geprüft');
    const result = page.locator('#updateDbResult');
    for (const width of [320, 390, 1440]) {
      await page.setViewportSize({width, height: 1000});
      await page.locator('#btnUpdateDbDryRun').click();
      await expect(result).toContainText(language === 'en' ? 'Database update available' : 'Datenbank-Aktualisierung verfügbar');
      await expect(result).toContainText(language === 'en' ? 'Preview – not applied yet' : 'Vorschau – noch nicht übernommen');
      await expect(result.locator('.update-db-source-comparison')).toContainText('v1.26.40.05');
      await expect(result.locator('.update-db-source-comparison')).toContainText('v1.26.50.4');
      await expect(result).toContainText(language === 'en' ? '124 added' : '124 ergänzt');
      await expect(result).toContainText(language === 'en' ? '37 effect descriptions updated' : '37 Effektbeschreibungen aktualisiert');
      await expect(result).toContainText(language === 'en' ? '123 → 1,628' : '123 → 1.628');
      await expect(result).toContainText(language === 'en' ? '1,414' : '1.414');
      await expect(result).toContainText(language === 'en' ? 'No issues found' : 'Keine Auffälligkeiten');
      await expect(result).not.toContainText('minecraft:bed');
      await expect(page.locator('#updateDbOutput')).toBeHidden();
      await captureBrowserEvidence(page, `db-result-${layout}-${theme}-${language}-${width}`, ".update-db-output-wrapper");
      await page.locator('#updateDbDetails > summary').click();
      await expect(page.locator('.update-db-name-list')).toBeHidden();
      await expect(page.locator('#updateDbAudit')).toContainText('minecraft:fishing_rod: 64 → 384');
      await expect(page.locator('#updateDbAudit')).not.toContainText('minecraft:bed');
      await expect(page.locator('#updateDbOutput')).toBeHidden();
      await page.locator('#updateDbLogDetails summary').focus();
      await page.keyboard.press('Enter');
      await expect(page.locator('#updateDbOutput')).toBeVisible();
      await expect(page.locator('#updateDbTechnicalNotes > strong')).toHaveText(language === 'en' ? 'Preserved display names (3)' : 'Beibehaltene Anzeigenamen (3)');
      await expect(page.locator('.update-db-name-list')).toBeVisible();
      await expect(page.locator('.update-db-name-list > li')).toHaveCount(3);
      await expect(page.locator('.update-db-name-list > li').first()).toContainText(language === 'en' ? 'White Bed' : 'Weißes Bett');
      await expect(page.locator('.update-db-name-list')).not.toContainText(language === 'en' ? 'Weißes Bett' : 'White Bed');
      await expect(page.locator('#updateDbTechnicalNotes')).toContainText(language === 'en' ? 'not pending changes' : 'keine ausstehenden Änderungen');
      await expect(page.locator('#updateDbLogDetails details')).toHaveCount(0);
      await expect(page.locator('#updateDbDetails')).toHaveAttribute('open', '');
      await page.locator('#updateDbLogDetails summary').click();
      await captureBrowserEvidence(page, `db-details-${layout}-${theme}-${language}-${width}`, ".update-db-output-wrapper");
      await page.locator('#updateDbDetails > summary').click();
      expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
      for (const id of ['btnUpdateDbDryRun', 'btnUpdateDbApply', 'btnClearUpdateOutput']) {
        // Chromium DOMRect rounding can report 43.999992 px for a 44 px button.
        expect((await page.locator(`#${id}`).boundingBox()).height).toBeGreaterThanOrEqual(44 - 0.001);
      }
    }
    state = 'current';
    for (const width of [320, 1440]) {
      await page.setViewportSize({width, height: 1000});
      await page.locator('#btnUpdateDbDryRun').click();
      await expect(result).toContainText(language === 'en' ? 'No content changes' : 'Keine inhaltlichen Änderungen');
      await expect(result).toContainText(language === 'en' ? 'No update required.' : 'Kein Update erforderlich.');
      await expect(result).not.toContainText(language === 'en' ? 'not applied yet' : 'noch nicht übernommen');
      await expect(result).not.toContainText('124');
      await expect(page.locator('#btnUpdateDbApply')).toBeDisabled();
      await expect(page.locator('#btnUpdateDbDryRun')).toBeEnabled();
      await expect(page.locator('#btnUpdateDbApply')).toHaveAttribute('aria-describedby', 'updateDbActionHint');
      await expect(page.locator('#updateDbActionHint')).toContainText(language === 'en' ? 'No changes in the last check.' : 'Keine Änderungen bei der letzten Prüfung.');
      await captureBrowserEvidence(page, `db-current-controls-${layout}-${theme}-${language}-${width}`, '#dashUpdate');
      await expect(page.locator('#updateDbDetails')).toBeHidden();
      await expect(page.locator('.update-db-name-list')).toBeHidden();
      await captureBrowserEvidence(page, `db-current-${layout}-${theme}-${language}-${width}`, '.update-db-output-wrapper');
      await page.locator('#updateDbLogDetails > summary').click();
      await expect(page.locator('.update-db-name-list')).toBeVisible();
      await expect(page.locator('#updateDbOutput')).toBeVisible();
      await expect(page.locator('#updateDbLogDetails details')).toHaveCount(0);
      await captureBrowserEvidence(page, `db-current-names-${layout}-${theme}-${language}-${width}`, '.update-db-output-wrapper');
      expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
      await page.locator('#updateDbLogDetails > summary').focus();
      await page.keyboard.press('Space');
      await expect(page.locator('.update-db-name-list')).toBeHidden();
    }
    state = 'metadata_only';
    await page.locator('#btnUpdateDbDryRun').click();
    await expect(result).toContainText(language === 'en' ? 'Only source metadata changed' : 'Nur Quelleninformationen geändert');
    await expect(page.locator('#btnUpdateDbApply')).toBeEnabled();
    await expect(result).toContainText(language === 'en' ? 'Preview – not applied yet' : 'Vorschau – noch nicht übernommen');
    await expect(result).not.toContainText(language === 'en' ? 'No update required.' : 'Kein Update erforderlich.');
    state = 'available';
    issues = [{code: 'name_differences_de', severity: 'info', count: 1, items: ['<img src=x onerror=alert(1)>']}];
    await page.locator('#btnUpdateDbDryRun').click();
    await expect(result).toContainText(language === 'en' ? 'Differing German names: 1' : 'Abweichende deutsche Namen: 1');
    await page.locator('#updateDbDetails > summary').click();
    await expect(page.locator('#updateDbAudit')).toContainText('<img src=x');
    await expect(page.locator('#updateDbAudit img')).toHaveCount(0);
    state = 'incomplete';
    await page.locator('#btnUpdateDbDryRun').click();
    await expect(result).toContainText(language === 'en' ? 'Check incomplete or failed' : 'Prüfung unvollständig oder fehlgeschlagen');
    await expect(result).toContainText('Synthetic source failure');
    await expect(page.locator('#btnUpdateDbApply')).toBeEnabled();
    await expect(result).not.toContainText(language === 'en' ? 'not applied yet' : 'noch nicht übernommen');
    await expect(result).not.toContainText(language === 'en' ? 'No update required.' : 'Kein Update erforderlich.');
    await expect(page.locator('#updateDbOutput')).toBeHidden();
    state = 'current';
    issues = [];
    includeNames = false;
    await page.locator('#btnUpdateDbDryRun').click();
    await expect(result).toContainText(language === 'en' ? 'No update required.' : 'Kein Update erforderlich.');
    await expect(page.locator('#updateDbDetails')).toBeHidden();
    await page.locator('#updateDbLogDetails > summary').click();
    await expect(page.locator('#updateDbTechnicalNotes')).toBeEmpty();
    await expect(page.locator('#updateDbOutput')).toBeVisible();
    await page.locator('#btnClearUpdateOutput').click();
    await expect(page.locator('.update-db-output-wrapper')).toBeHidden();
    await expect(page.locator('#btnUpdateDbDryRun')).toBeFocused();
    expect(errors).toEqual([]);
  });
}

test("icon setup and missing-source previews remain usable on narrow screens", async ({ page }) => {
  test.setTimeout(90_000);
  const errors = collectBrowserErrors(page);
  const iconData = { success: true, count: 0, icons: {}, warnings: [], sources: [{
    label: "Vanilla Icons aus Mojang/bedrock-samples", path: "", enabled: true, exists: false, count: 0,
  }], health: { enabled_sources: 1, existing_sources: 0, sample_found: 0, sample_total: 8,
    sample: ["diamond_sword", "apple", "stone", "bow", "carrot", "chest", "firework_rocket", "banner"]
      .map(id => ({ item_id: `minecraft:${id}`, found: false })),
  } };
  await page.route("**/api/icons/status*", route => route.fulfill({ json: iconData }));
  await page.route("**/api/icons/scan", route => route.fulfill({ json: iconData }));
  for (const locale of ["de", "en"]) {
    await page.context().addCookies([{ name: "mcbe_locale", value: locale, url: NORMAL_BASE_URL }]);
    await page.setViewportSize({ width: 1440, height: 900 });
    await openAppWithEmptyWorldScan(page);
    await expect(page.locator("html")).toHaveAttribute("lang", locale);
    await selectSetting(page, "themeSelect", "light");
    for (const layout of ["classic", "studio", "focus"]) {
      await selectLayout(page, layout);
      await page.locator('.app-workflow-nav [data-workflow-view="tools"]').click();
      await page.locator('[data-tab-dash="dashIcons"]').click();
      const panel = page.locator("#dashIcons");
      for (const width of [1440, 390, 320]) {
        await page.setViewportSize({ width, height: 900 });
        await expect(page.locator("#btnFocusIconSource")).toBeVisible();
        expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
        expect(await panel.evaluate(el => el.scrollWidth - el.clientWidth), `${locale}/${layout}/${width}`).toBeLessThanOrEqual(1);
        if (process.env.MCBE_BROWSER_EVIDENCE_DIR) await panel.screenshot({
          path: `${process.env.MCBE_BROWSER_EVIDENCE_DIR}/icon-setup-${locale}-${layout}-${width}.png`,
          animations: "disabled",
        });
        await page.locator("#btnFocusIconSource").click();
        await expect(page.locator("#iconSourceDialog")).toBeVisible();
        await page.keyboard.press("Escape");
        await expect(page.locator("#iconSourceDialog")).toBeHidden();
      }
    }
  }
  expect(errors).toEqual([]);
});

for (const layout of ['classic', 'studio', 'focus']) for (const theme of ['dark', 'light']) {
  test(`compact asset tools keep actions and diagnostics accessible (${layout}/${theme})`, async ({page}) => {
    test.setTimeout(60_000);
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const itemDb = {status: 'ok', verification: {verified: true}, source_version_present: true,
      source_version: {resource_pack_release: 'v1.26.40.05'}, counts: {items: 2164, effects: 37, enchantments: 42},
      schema_version: 3, history_count: 2, path: 'synthetic/item_db.json'};
    const iconData = {success: true, count: 1868, icons: {}, warnings: [], scanned_files: 1675,
      sources: [{label: 'Vanilla', path: 'synthetic/vanilla', enabled: true, exists: true, count: 1868}],
      health: {status: 'ok', enabled_sources: 1, existing_sources: 1, sample_found: 4, sample_total: 4,
        sample: ['diamond_sword', 'apple', 'stone', 'bow'].map(id => ({item_id: `minecraft:${id}`, found: true}))},
      cache: {state: 'hit', path: 'synthetic/cache.json'}, settings_path: 'synthetic/icon_sources.json'};
    await page.route('**/api/item-db/status', route => route.fulfill({json: {success: true, item_db: itemDb}}));
    await page.route('**/api/item-db/versions', route => route.fulfill({json: {success: true, entries: Array.from({length: 40}, (_, index) => ({resource_pack_release: index === 39 ? 'oldest-release' : 'v1.26.40.05', generated_at: '2026-10-17T14:16:23+00:00'}))}}));
    await page.route('**/api/icons/status*', route => route.fulfill({json: iconData}));
    await page.route('**/api/icons/scan', route => route.fulfill({json: iconData}));
    let updateRequest;
    await page.route('**/api/update_db', route => {
      updateRequest = route.request().postDataJSON();
      return route.fulfill({json: updateRequest.dry_run
        ? {success: true, output: 'Synthetic preview completed', update_review_token: 'synthetic-review', resource_pack_release: 'v1.26.40.05'}
        : {success: false, error: 'Synthetic update failure', returncode: 1}});
    });
    await page.route('**/api/icons/sources/add', route => route.fulfill({json:
      route.request().postDataJSON().path === 'bad' ? {success: false, error: 'Synthetic invalid source'} : iconData}));
    await page.route('**/api/icons/pick_pack', route => route.fulfill({json: {success: true, path: 'synthetic/pack.mcpack'}}));
    await page.route('**/api/icons/pick_folder', route => route.fulfill({json: {success: false, error: 'Synthetic picker unavailable'}}));
    await openAppWithEmptyWorldScan(page);
    await selectLayout(page, layout);
    await selectSetting(page, 'themeSelect', theme);
    await page.locator('.app-workflow-nav [data-workflow-view="tools"]').click();
    for (const width of [390, 1440]) {
      await page.setViewportSize({width, height: 1000});
      for (const tab of ['dashUpdate', 'dashIcons']) {
        await page.locator(`[data-tab-dash="${tab}"]`).click();
        await expect(page.locator(`#${tab}`)).toBeVisible();
        await captureBrowserEvidence(page, `compact-tools-${layout}-${theme}-${width}-${tab}`);
        const overflow = await page.evaluate(() => ({width: document.documentElement.scrollWidth - innerWidth,
          elements: [...document.querySelectorAll('body *')].filter(el => el.getBoundingClientRect().right > innerWidth + 1 && el.getBoundingClientRect().width > 0).slice(-12).map(el => [el.id, el.className, el.getBoundingClientRect().width])}));
        expect(overflow.width, JSON.stringify(overflow.elements)).toBeLessThanOrEqual(1);
      }
      await expect(page.locator('#assetDataStatusPanel')).toBeHidden();
      await expect(page.locator('#iconManagerPanel .tool-status-line')).toContainText('1.868');
      await expect(page.locator('#iconManagerPanel .tool-facts')).toBeHidden();
      await page.locator('#btnOpenIconSource').click();
      await expect(page.locator('#iconSourceDialog')).toBeVisible();
      await page.locator('#iconSourceDialog summary').click();
      await expect(page.locator('#iconSourcePath')).toBeVisible();
      expect(await page.locator('#iconSourceDialog').evaluate(el => el.scrollWidth - el.clientWidth)).toBeLessThanOrEqual(1);
      await captureBrowserEvidence(page, `compact-tools-${layout}-${theme}-${width}-source-dialog`);
      await page.keyboard.press('Escape');
      await expect(page.locator('#iconSourceDialog')).toBeHidden();
      await expect(page.locator('#btnOpenIconSource')).toBeFocused();
      // Reset the native disclosure for the next viewport.
      await page.locator('#iconSourceDialog details').evaluate(el => { el.open = false; });
    }
    await page.locator('#iconManagerPanel summary').click();
    await expect(page.locator('#btnCopyIconDiagnostics')).toBeVisible();
    await page.locator('#btnRescanIcons').click();
    await expect(page.locator('#iconManagerPanel .tool-facts')).toBeVisible();
    await page.locator('#btnOpenIconSource').click();
    await page.locator('#btnPickIconFolder').click();
    await expect(page.locator('#iconSourceFeedback')).toHaveText('Synthetic picker unavailable');
    await page.locator('#iconSourceDialog summary').click();
    await page.locator('#iconSourcePath').fill('bad');
    await page.locator('#btnAddIconSource').click();
    await expect(page.locator('#iconSourceFeedback')).toHaveText('Synthetic invalid source');
    await expect(page.locator('#iconSourcePath')).toHaveValue('bad');
    await page.locator('#btnPickIconPack').click();
    await expect(page.locator('#iconSourceDialog')).toBeHidden();
    await page.locator('[data-tab-dash="dashUpdate"]').click();
    await expect(page.locator('.update-db-output-wrapper')).toBeHidden();
    await page.locator('[data-db-details] summary').click();
    await page.locator('[data-toggle-db-versions]').click();
    await expect(page.locator('.item-db-version-history')).toContainText('v1.26.40.05');
    await expect(page.locator('[data-db-details]')).toHaveAttribute('open', '');
    const history = page.locator('.item-db-version-history');
    await expect(page.locator('[data-toggle-db-versions]')).toHaveText('Versionsverlauf (40)');
    for (const width of [320, 390, 1440]) {
      await page.setViewportSize({width, height: 900});
      await history.scrollIntoViewIfNeeded();
      await history.focus();
      await expect(history).toBeFocused();
      await page.keyboard.press('Control+End');
      await expect.poll(() => history.evaluate(el => el.scrollTop)).toBeGreaterThan(0);
      await expect(history.locator('tr').last()).toBeInViewport();
      await expect(history.locator('th').first()).toBeInViewport();
      expect(await history.evaluate(el => el.scrollWidth - el.clientWidth)).toBeLessThanOrEqual(1);
      expect(await history.evaluate(el => el.clientHeight)).toBeLessThanOrEqual(300);
      await captureBrowserEvidence(page, `version-history-${layout}-${theme}-${width}`, '[data-db-details]');
      await page.keyboard.press('Control+Home');
      await expect.poll(() => history.evaluate(el => el.scrollTop)).toBe(0);
    }
    await page.locator('[data-toggle-db-versions]').click();
    await expect(history).toBeHidden();
    await page.locator('[data-toggle-db-versions]').press('Enter');
    await expect(history).toBeVisible();
    await page.locator('.update-db-options summary').click();
    await page.locator('#updateOnlySelect').selectOption('items');
    await page.locator('.update-db-options summary').click();
    await expect(page.locator('#updateScopeSummary')).toHaveText('Nur Items');
    await page.locator('#btnUpdateDbDryRun').click();
    await expect(page.locator('#updateDbOutput')).toContainText('Synthetic preview completed');
    expect(updateRequest.only).toBe('items');
    expect(updateRequest.dry_run).toBe(true);
    await page.locator('#btnUpdateDbApply').click();
    await expect(page.locator('#confirmOverlay')).toBeVisible();
    await page.locator('#confirmCancel').click();
    await page.locator('#btnUpdateDbApply').click();
    await page.locator('#confirmOk').click();
    await expect(page.locator('#updateDbOutput')).toContainText('Synthetic update failure');
    expect(updateRequest.expected_update_review_token).toBe('synthetic-review');
    expect(updateRequest.only).toBe('items');
    await page.locator('#btnClearUpdateOutput').click();
    await expect(page.locator('.update-db-output-wrapper')).toBeHidden();
    await expect(page.locator('#btnUpdateDbDryRun')).toBeFocused();
    expect(errors).toEqual([]);
  });
}

for (const layout of ['classic', 'studio', 'focus']) {
  for (const theme of ['dark', 'light']) {
    test(`many-player search and bounded scrolling (${layout}/${theme})`, async ({ page }, testInfo) => {
      test.setTimeout(60_000);
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.route('**/api/world/presence', route => route.fulfill({json: {success: true, other_sessions: []}}));
      const players = Array.from({length: 150}, (_, i) => ({
        player_key: i === 0 ? 'drag-player' : `synthetic-key-${i}`,
        label: i === 0 ? 'Drag Test' : i === 80 ? 'VeryLongSyntheticPlayerName'.repeat(4) : `Testspieler ${i}`,
        kind: i === 0 ? 'local' : 'remote', editable: i !== 80, exportable: true,
        has_inventory_tag: true, has_ender_chest_tag: true,
      }));
      await openDragFixture(page, request => ({player: players.find(p => p.player_key === request.player_key)}), players);
      await selectLayout(page, layout);
      await selectSetting(page, 'themeSelect', theme);
      const list = page.locator('#playersList');
      const rows = list.locator('.player-row');
      const search = page.locator('#playerManagerSearch');
      async function openManager(currentLayout = layout) {
        await page.locator(currentLayout === 'classic'
          ? '.app-workflow-nav [data-workflow-view="player"]'
          : '.layout-context-chip[data-workflow-view="player"]').click();
        await expect(search).toBeVisible();
      }
      async function checkList(width, rail = false) {
        await expect(rows).toHaveCount(150);
        await list.scrollIntoViewIfNeeded();
        const bounds = await list.evaluate(el => ({
          height: el.clientHeight, content: el.scrollHeight, overflow: getComputedStyle(el).overflowY,
          horizontalOverflow: el.scrollWidth - el.clientWidth,
          pageOverflow: document.documentElement.scrollWidth - innerWidth,
          minRow: Math.min(...Array.from(el.children, row => row.getBoundingClientRect().height)),
        }));
        expect(bounds.height).toBeGreaterThan(100);
        expect(bounds.height).toBeLessThanOrEqual(Math.min(rail ? 650 : 420, (rail ? .58 : .52) * page.viewportSize().height) + 1);
        expect(bounds.content).toBeGreaterThan(bounds.height * 5);
        expect(bounds.overflow).toBe('auto');
        expect(bounds.minRow).toBeGreaterThanOrEqual(44);
        expect(bounds.horizontalOverflow).toBeLessThanOrEqual(1);
        expect(bounds.pageOverflow).toBeLessThanOrEqual(1);
        await list.evaluate(el => { el.scrollTop = el.scrollHeight; });
        const lastReachable = await rows.last().evaluate(el => {
          const row = el.getBoundingClientRect(), parent = el.parentElement.getBoundingClientRect();
          return row.top >= parent.top - 1 && row.bottom <= parent.bottom + 1;
        });
        expect(lastReachable).toBe(true);
        await list.evaluate(el => { el.scrollTop = 0; });
        await testInfo.attach(`${layout}-${theme}-${width}${rail ? '-rail' : ''}`, {
          body: await page.screenshot(), contentType: 'image/png',
        });
        await captureBrowserEvidence(page, `players-${layout}-${theme}-${width}-${await page.locator('body').getAttribute('data-workflow-view')}${rail ? '-rail' : ''}`);
      }
      for (const width of [390, 1024, 1830]) {
        await page.setViewportSize({width, height: width === 390 ? 844 : 1000});
        await openManager();
        await search.fill('');
        await checkList(width);
        await search.fill('TESTSPIELER 149');
        await expect(list.locator('.player-row:visible')).toHaveCount(1);
        await expect(page.locator('#playerManagerCount')).toHaveText('1 / 150');
        await search.fill('synthetic-KEY-80');
        await expect(list.locator('.player-row:visible')).toHaveCount(1);
        await expect(list.locator('.player-row:visible .player-name')).toHaveText(players[80].label);
        expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
        await search.fill('no matching synthetic player');
        await expect(list.locator('.player-row:visible')).toHaveCount(0);
        await expect(page.locator('#playerManagerSearchEmpty')).toBeVisible();
        await search.fill('');
        await expect(page.locator('#playerManagerSearchEmpty')).toBeHidden();
        await expect(list.locator('.player-row:visible')).toHaveCount(150);
        // Refresh recreates the rows; the query must still filter the new DOM.
        await search.fill('Testspieler 149');
        await page.locator('#btnRefreshPlayers').click();
        await expect(list.locator('.player-row:visible')).toHaveCount(1);
        await expect(list.locator('.player-row:visible')).toContainText('Testspieler 149');
        await list.locator('.player-row:visible').click();
        await expect.poll(() => page.evaluate(() => currentPlayerKey)).toBe('synthetic-key-149');
        await openManager();
        await search.fill('');
        await page.locator('.app-workflow-nav [data-workflow-view="inventory"]').click();
        if (layout === 'focus' && width > 760) {
          await checkList(width, true);
          await page.locator('#focusPlayerSearch').fill('Testspieler 149');
          await expect(list.locator('.player-row:visible')).toHaveCount(1);
          await openManager();
          await expect(search).toHaveValue('Testspieler 149');
          await search.fill('');
        } else if (layout === 'classic') {
          if (width <= 1024) await page.locator('.btn-toggle[data-panel="right"]').click();
          await expect(search).toBeVisible();
          await checkList(width);
        }
      }
      await openManager();
      await search.fill('Testspieler 149');
      for (const nextLayout of ['classic', 'studio', 'focus']) {
        await selectLayout(page, nextLayout);
        await openManager(nextLayout);
        await expect(search).toHaveValue('Testspieler 149');
        await expect(list.locator('.player-row:visible')).toHaveCount(1);
        await expect(page.locator('#playerManagerCount')).toHaveText('1 / 150');
      }
      await list.locator('.player-row:visible').click();
      await expect.poll(() => page.evaluate(() => currentPlayerKey)).toBe('synthetic-key-149');
      expect(errors).toEqual([]);
    });
  }
}
