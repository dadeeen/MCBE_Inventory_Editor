import { expect, test } from '@playwright/test';
import { NORMAL_BASE_URL, captureBrowserEvidence, collectBrowserErrors, openAppWithEmptyWorldScan } from './fixtures/app.mjs';

for (const [width, locale] of [[1440, 'de'], [390, 'en']]) {
  test(`icon checks reuse current files and distinguish local verification from download (${width}/${locale})`, async ({page}) => {
    await page.setViewportSize({width, height: 950});
    await page.context().addCookies([{name: 'mcbe_locale', value: locale, url: NORMAL_BASE_URL}]);
    const errors = collectBrowserErrors(page);
    const icons = {success: true, count: 1, icons: {}, sources: [], warnings: [], missing_banner_patterns: [], vanilla_cache: {state: 'current'}};
    await page.route('**/api/icons/status*', route => route.fulfill({json: icons}));
    await page.route('**/api/item-db/status', route => route.fulfill({json: {success: true, item_db: {status: 'ok', verification: {verified: true}}}}));
    const calls = [];
    let next = {success: true, ...icons, update_committed: false, icon_update: {already_current: true, needs_update: false}};
    await page.route('**/api/icons/vanilla/update', route => {
      calls.push(route.request().postDataJSON());
      return route.fulfill({json: next});
    });
    await openAppWithEmptyWorldScan(page);
    await expect(page.locator('#firstRunSetupOverlay')).toBeHidden();
    await page.locator('.app-workflow-nav [data-workflow-view="tools"]').click();
    await page.locator('[data-tab-dash="dashIcons"]').click();
    const button = page.locator('#btnUpdateVanillaIcons');
    const result = page.locator('#iconUpdateResult');
    await expect(button).toHaveText(locale === 'de' ? 'Aktualität prüfen' : 'Check for updates');
    await button.focus();
    await page.keyboard.press('Enter');
    await expect(result).toHaveText(locale === 'de' ? 'Bereits aktuell.' : 'Already up to date.');
    expect(calls).toHaveLength(1);
    expect(calls[0].check_only).toBe(true);
    await expect(page.locator('#confirmOk')).toBeHidden();
    await captureBrowserEvidence(page, `icons-current-${width}-${locale}`, '#dashIcons');

    for (const kind of ['local', 'download']) {
      next = {success: true, update_committed: false, icon_update: {
        needs_update: true, check_only: true, update_kind: kind, reason: 'legacy', source_unchanged: true,
      }};
      const count = calls.length;
      await button.click();
      await expect(result).toHaveAttribute('data-state', 'available');
      await expect(button).toHaveText(kind === 'local'
        ? locale === 'de' ? 'Lokal aktualisieren' : 'Update locally'
        : locale === 'de' ? 'Icons herunterladen' : 'Download icons');
      expect(calls).toHaveLength(count + 1);
      expect(calls.at(-1).check_only).toBe(true);
      await expect(page.locator('#confirmOk')).toBeHidden();
      if (kind === 'download') await expect(page.locator('#iconUpdateHint')).toContainText(locale === 'de' ? 'bleiben nutzbar' : 'remain usable');
      await captureBrowserEvidence(page, `icons-${kind}-${width}-${locale}`, '#dashIcons');
      expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
      await button.click();
      await expect(page.locator('#confirmOk')).toBeVisible();
      expect(calls).toHaveLength(count + 1);
      next = {...icons, update_committed: true, icon_update: {already_current: true, needs_update: false, images_changed: false, metadata_updated: true}};
      await page.locator('#confirmOk').click();
      await expect(result).toHaveText(locale === 'de' ? 'Bereits aktuell.' : 'Already up to date.');
      expect(calls).toHaveLength(count + 2);
      expect(calls.at(-1).check_only).toBeUndefined();
      expect(calls.at(-1).allow_download).toBe(kind === 'local' ? false : undefined);
    }
    expect(errors).toEqual([]);
  });
}
