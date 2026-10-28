import { expect, test } from '@playwright/test';
import { NORMAL_BASE_URL, captureBrowserEvidence, openAppWithEmptyWorldScan, selectLayout, selectSetting } from './fixtures/app.mjs';

for (const language of ['de', 'en']) {
  test(`successful database apply resolves the earlier check error (${language})`, async ({page}) => {
    await page.context().addCookies([{name: 'mcbe_locale', value: language, url: NORMAL_BASE_URL}]);
    const itemDb = {status: 'ok', verification: {verified: true}, counts: {items: 1, effects: 1, enchantments: 1}};
    const icons = {success: true, icons: {}, count: 0, sources: [], warnings: []};
    await page.route('**/api/item-db/status', route => route.fulfill({json: {success: true, item_db: itemDb}}));
    await page.route('**/api/icons/status*', route => route.fulfill({json: icons}));
    await page.route('**/api/icons/vanilla/update', route => route.fulfill({json: {...icons, manifest: {mapped_items: 1, known_items: 1}}}));
    await page.route('**/api/update_db', route => route.fulfill({json: route.request().postDataJSON().dry_run
      ? {success: false, error: 'Fixture check failure', returncode: 1}
      : {success: true, reloaded: true, update_committed: true, summary: {status: 'current'}, verification_required: false, item_db: itemDb}}));
    await openAppWithEmptyWorldScan(page);
    await page.locator('.app-workflow-nav [data-workflow-view="tools"]').click();
    await page.locator('[data-tab-dash="dashUpdate"]').click();
    await page.locator('#btnUpdateDbDryRun').click();
    await expect(page.locator('#statusStackButton')).toHaveClass(/error/);
    await page.locator('[data-tab-dash="dashIcons"]').click();
    await page.locator('#btnUpdateVanillaIcons').click();
    await expect(page.locator('#iconUpdateResult')).toHaveAttribute('data-state', 'success');
    await expect(page.locator('#statusStackButton')).toHaveClass(/error/);
    await expect(page.locator('#statusStackSummary')).toContainText('Fixture check failure');
    await page.locator('[data-tab-dash="dashUpdate"]').click();
    await page.locator('#btnUpdateDbApply').click();
    await page.locator('#confirmOk').click();
    await expect(page.locator('#updateDbResult')).toContainText(language === 'en' ? 'No update required' : 'Kein Update erforderlich');
    await expect(page.locator('#statusStackButton')).not.toHaveClass(/error|warning/);
    await expect(page.locator('#statusStackSummary')).toContainText(language === 'en' ? 'No update required' : 'Kein Update erforderlich');
    await page.locator('#statusStackButton').click();
    await expect(page.locator('#statusStackPanel .error:not(.active)')).toContainText('Fixture check failure');
    await expect(page.locator('#statusStackPanel .error.active')).toHaveCount(0);
    await expect(page.locator('#statusStackPanel .success').first()).toContainText(language === 'en' ? 'No update required' : 'Kein Update erforderlich');
    await captureBrowserEvidence(page, `resolved-update-status-${language}`, '#statusStackPanel');
  });
}

for (const [layout, theme] of [['classic', 'dark'], ['studio', 'light'], ['focus', 'dark']]) {
  for (const language of ['de', 'en']) {
    test(`update failures stay visible in their own tab (${layout}/${theme}/${language})`, async ({page}) => {
      test.setTimeout(60_000);
      const browserErrors = [];
      page.on('pageerror', error => browserErrors.push(error.message));
      await page.context().addCookies([{name: 'mcbe_locale', value: language, url: NORMAL_BASE_URL}]);
      const limit = language === 'en'
        ? 'GitHub request limit reached. Please try again later.'
        : 'GitHub-Anfragelimit erreicht. Bitte später erneut versuchen.';
      const hint = language === 'en'
        ? 'Try again no earlier than 2033-05-18 03:35:20 (UTC).'
        : 'Erneuter Versuch frühestens ab 2033-05-18 03:35:20 (UTC).';
      const protocol = 'https://api.github.com/repos/Mojang/bedrock-samples/releases/latest: HTTP 403\n<script>unexpectedMarkup()</script>';
      const failure = {success: false, returncode: 1, error: limit, hint, output: protocol,
        category: 'github-rate-limit', http_status: 403, retry_at: 2000000120};
      let iconResult = failure;
      const dbRequests = [];
      let iconRequests = 0;
      const icons = {success: true, icons: {}, count: 0, sources: [], warnings: [], health: {}};
      await page.route('**/api/icons/status*', route => route.fulfill({json: icons}));
      await page.route('**/api/item-db/status', route => route.fulfill({json: {success: true, item_db: {
        status: 'ok', verification: {verified: true}, source_version_present: true,
        source_version: {resource_pack_release: 'fixture'}, counts: {items: 10, effects: 1, enchantments: 1},
      }}}));
      await page.route('**/api/update_db', route => {
        dbRequests.push(route.request().postDataJSON());
        return route.fulfill({json: failure});
      });
      await page.route('**/api/icons/vanilla/update', route => {
        iconRequests += 1;
        return route.fulfill({json: iconResult});
      });
      await openAppWithEmptyWorldScan(page);
      await selectLayout(page, layout);
      await selectSetting(page, 'themeSelect', theme);
      await page.locator('.app-workflow-nav [data-workflow-view="tools"]').click();
      const runIcons = async () => {
        await page.locator('#btnUpdateVanillaIcons').click();
        await expect(page.locator('#loadingOverlay')).toBeHidden();
      };

      for (const width of [390, 1440]) {
        await page.setViewportSize({width, height: 1000});
        await page.locator('[data-tab-dash="dashUpdate"]').click();
        await page.locator('#btnUpdateDbDryRun').click();
        await expect(page.locator('#updateDbResult')).toContainText(limit);
        await expect(page.locator('#updateDbResult')).toContainText(hint);
        expect(dbRequests.at(-1).dry_run).toBe(true);
        await page.locator('#btnUpdateDbApply').click();
        await page.locator('#confirmOk').click();
        await expect(page.locator('#loadingOverlay')).toBeHidden();
        expect(dbRequests.at(-1).dry_run).toBe(false);
        await expect(page.locator('#updateDbResult')).toContainText(limit);
        await expect(page.locator('#updateDbOutput')).toBeHidden();
        const dbOutput = await page.locator('#updateDbOutput').textContent();

        await page.locator('[data-tab-dash="dashIcons"]').click();
        iconResult = failure;
        await runIcons();
        await expect(page.locator('#iconUpdateResult')).toHaveText(limit);
        await expect(page.locator('#iconUpdateHint')).toHaveText(hint);
        await expect(page.locator('#iconUpdateOutput')).toBeHidden();
        await captureBrowserEvidence(page, `update-error-${layout}-${theme}-${language}-${width}`, '#dashIcons');
        await page.locator('#iconUpdateLogDetails > summary').focus();
        await page.keyboard.press('Enter');
        await expect(page.locator('#iconUpdateOutput')).toBeVisible();
        await expect(page.locator('#iconUpdateOutput')).toContainText(protocol);
        await expect(page.locator('#iconUpdateOutput script')).toHaveCount(0);
        await expect(page.locator('#updateDbOutput')).toHaveText(dbOutput);
        await captureBrowserEvidence(page, `update-log-${layout}-${theme}-${language}-${width}`, '#iconUpdateFeedback');
        expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);

        await page.locator('[data-tab-dash="dashUpdate"]').click();
        await expect(page.locator('#updateDbResult')).toContainText(limit);
        await page.locator('[data-tab-dash="dashIcons"]').click();
        await expect(page.locator('#iconUpdateResult')).toHaveText(limit);

        // A later failure without Retry-After must not retain an old deadline.
        iconResult = {...failure, hint: undefined, retry_at: undefined, error: 'HTTP 404', output: 'missing source'};
        await runIcons();
        await expect(page.locator('#iconUpdateResult')).toHaveText('HTTP 404');
        await expect(page.locator('#iconUpdateHint')).toBeHidden();
        await expect(page.locator('#iconUpdateOutput')).not.toContainText('2033');

        // Recovery replaces the failure and leaves both update actions usable.
        iconResult = {...icons, output: 'Icons loaded', manifest: {mapped_items: 1, known_items: 1}};
        await runIcons();
        await expect(page.locator('#iconUpdateResult')).toHaveAttribute('data-state', 'success');
        await expect(page.locator('#iconUpdateResult')).not.toContainText(limit);
        await expect(page.locator('#btnUpdateVanillaIcons')).toBeEnabled();
        await expect(page.locator('#iconUpdateOutput')).not.toContainText('missing source');
        await page.locator('#btnClearIconUpdateOutput').focus();
        await page.keyboard.press('Enter');
        await expect(page.locator('#iconUpdateFeedback')).toBeHidden();
        await expect(page.locator('#btnUpdateVanillaIcons')).toBeFocused();
        await expect(page.locator('#updateDbOutput')).toHaveText(dbOutput);
      }
      expect(iconRequests).toBe(6);
      expect(dbRequests).toHaveLength(4);
      expect(browserErrors).toEqual([]);
    });
  }
}
