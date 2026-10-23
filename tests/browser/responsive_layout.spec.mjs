import { expect, test } from "@playwright/test";
import {
  collectBrowserErrors,
  openAppWithEmptyWorldScan,
  openDragFixture,
  captureBrowserEvidence,
  selectSetting,
  selectLayout,
} from "./fixtures/app.mjs";

test("Studio uses one stable inspector track for empty, single and multiple slot selections", async ({ page }) => {
  const errors = collectBrowserErrors(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await openDragFixture(page);
  await selectSetting(page, "layoutSelect", "studio");

  const measurements = async () => page.evaluate(() => {
    const slot = document.querySelector('.main-inventory-grid [data-slot="9"]');
    const workspace = document.querySelector(".workspace");
    return {
      slotWidth: slot.getBoundingClientRect().width,
      gridWidth: document.querySelector(".main-inventory-grid").getBoundingClientRect().width,
      columns: getComputedStyle(workspace).gridTemplateColumns,
      overflow: document.documentElement.scrollWidth - innerWidth,
    };
  });

  await expect(page.locator("#studioInspectorStandby")).toBeVisible();
  await expect(page.locator("#detailEditorPanel")).toBeHidden();
  await expect(page.locator("#dashboardPanel")).toBeHidden();
  await expect(page.locator("#safeEditBanner")).toBeHidden();
  const initial = await measurements();
  expect(initial.slotWidth).toBeGreaterThanOrEqual(44);
  expect(initial.slotWidth).toBeLessThanOrEqual(85);
  expect(initial.overflow).toBeLessThanOrEqual(0);

  await page.locator('.main-inventory-grid [data-slot="9"]').click();
  await expect(page.locator("#detailEditorPanel")).toBeVisible();
  await expect(page.locator("#studioInspectorStandby")).toBeHidden();
  const single = await measurements();
  expect(single.slotWidth).toBeCloseTo(initial.slotWidth, 1);
  expect(single.gridWidth).toBeCloseTo(initial.gridWidth, 1);
  expect(single.columns).toBe(initial.columns);

  await page.locator('.main-inventory-grid [data-slot="10"]').click({ modifiers: ["Control"] });
  await expect(page.locator("#multiSelectPanel")).toBeVisible();
  await expect(page.locator("#studioInspectorStandby")).toBeHidden();
  const multiple = await measurements();
  expect(multiple.slotWidth).toBeCloseTo(initial.slotWidth, 1);
  expect(multiple.columns).toBe(initial.columns);

  await page.locator("#btnClearSelection").click();
  await expect(page.locator("#studioInspectorStandby")).toBeVisible();
  await expect(page.locator("#multiSelectPanel")).toBeHidden();
  expect((await measurements()).slotWidth).toBeCloseTo(initial.slotWidth, 1);

  // The new placeholder is exclusively a Studio desktop feature; the real
  // forms and their selected data are shared unchanged across layouts.
  await selectSetting(page, "layoutSelect", "focus");
  await expect(page.locator("#studioInspectorStandby")).toBeHidden();
  await selectLayout(page, "classic");
  await expect(page.locator("#studioInspectorStandby")).toBeHidden();
  expect(errors).toEqual([]);
});

for (const width of [390, 1440]) {
test(`inventory review actions stay in the global change workflow (${width}px)`, async ({ page }) => {
  await page.setViewportSize({width, height: 900});
  await openDragFixture(page, {stack_limits: {"minecraft:stone": 64}});
  if (width === 390) await selectSetting(page, 'themeSelect', 'light');
  for (const layout of ['classic', 'studio', 'focus']) {
    await selectLayout(page, layout);
    await page.locator('.app-workflow-nav [data-workflow-view="inventory"]').click();
    const before = await page.locator('#inventoryContainer').evaluate(el => el.getBoundingClientRect().top + scrollY);
    await page.locator('[data-slot="0"]').click();
    if (layout === 'classic' && width <= 1024) await page.locator('.btn-toggle[data-panel="right"]').click();
    await page.locator('#detailCount').fill(layout === 'classic' ? '2' : layout === 'studio' ? '3' : '4');
    await page.locator("#detailSlotNum").click();
    await expect(page.locator('#safeEditBanner')).toBeHidden();
    if (width > 1024) expect(await page.locator('#inventoryContainer').evaluate(el => el.getBoundingClientRect().top + scrollY)).toBeCloseTo(before, 0);
    await page.locator(layout === 'classic' ? '.app-workflow-nav [data-workflow-view="save"]' : '#layoutSaveAction').click();
    await expect(page.locator('#btnReviewDiscardChanges')).toBeVisible();
    await expect(page.locator('#btnReviewDiscardChanges')).toBeEnabled();
    await page.locator('#btnReviewDiscardChanges').click();
    await expect(page.locator('#confirmOverlay')).toBeVisible();
    await page.locator('#confirmCancel').click();
    await expect(page.locator('body')).toHaveClass(/app-dirty/);
  }
  await page.locator('#btnReviewDiscardChanges').click();
  await page.locator('#confirmOk').click();
  await expect(page.locator('body')).not.toHaveClass(/app-dirty/);
  await expect(page.locator('#btnReviewDiscardChanges')).toBeDisabled();
});
}

test("Studio sidebar only scrolls internally when the available height really demands it", async ({ page }) => {
  await openDragFixture(page);
  await selectSetting(page, "layoutSelect", "studio");

  for (const height of [650, 900]) {
    await page.setViewportSize({ width: 1440, height });
    const fit = await page.locator(".layout-controls").evaluate(rail => {
      rail.scrollTop = 100;
      return { extraHeight: rail.scrollHeight - rail.clientHeight, scrollTop: rail.scrollTop };
    });
    expect(fit.extraHeight, `unexpected rail scroll at ${height}px`).toBeLessThanOrEqual(1);
    expect(fit.scrollTop).toBe(0);
  }

  await page.setViewportSize({ width: 1440, height: 390 });
  const compact = await page.locator(".layout-controls").evaluate(rail => {
    const nav = rail.querySelector(".app-workflow-nav");
    const lastLink = nav.querySelector("#btnHelp");
    const saveArea = rail.querySelector(".layout-context-action");
    return {
      needsScroll: rail.scrollHeight > rail.clientHeight,
      linkBottom: lastLink.getBoundingClientRect().bottom,
      saveTop: saveArea.getBoundingClientRect().top,
    };
  });
  expect(compact.needsScroll).toBe(true);
  expect(compact.linkBottom).toBeLessThan(compact.saveTop);
  await page.locator(".layout-controls").evaluate(rail => { rail.scrollTop = rail.scrollHeight; });
  await expect(page.locator("#layoutSaveAction")).toBeInViewport();
});

test("player management dialogs preserve selection and return keyboard focus", async ({ page }) => {
  const errors = collectBrowserErrors(page);
  await openDragFixture(page);
  await expect(page.locator(".player-manager-tools")).toBeHidden();
  await page.locator('.app-section-nav button[data-workflow-view="player"]').click();
  const selectedName = await page.locator('#playersList .player-row.active .player-name').innerText();
  for (const kind of ["Transfer", "Export", "Import"]) {
    const trigger = page.locator(`[data-player-tool="player${kind}Dialog"]`);
    const overlay = page.locator(`#player${kind}Dialog`);
    await trigger.click();
    await expect(overlay).toBeVisible();
    expect(await page.locator('.app-container').evaluate(el => el.inert)).toBe(true);
    if (kind !== "Transfer") await expect(overlay.locator('[data-player-tool-context]')).toHaveText(selectedName);
    await expect(overlay.locator('[data-close-player-tool]')).toBeFocused();
    await page.keyboard.press("Shift+Tab");
    expect(await overlay.evaluate(el => el.contains(document.activeElement))).toBe(true);
    await page.keyboard.press("Tab");
    await expect(overlay.locator('[data-close-player-tool]')).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(overlay).toBeHidden();
    await expect(trigger).toBeFocused();
    expect(await page.locator('.app-container').evaluate(el => el.inert)).toBe(false);
  }
  await expect(page.locator('#playersList .player-row.active .player-name')).toHaveText(selectedName);
  expect(errors).toEqual([]);
});

test("dimension conversion help is keyboard accessible and keeps safety guidance visible", async ({ page }) => {
  await openDragFixture(page);
  await page.locator('.app-section-nav button[data-workflow-view="player"]').click();
  const help = page.locator('#conversionHelp');
  await expect(help.locator('.location-conversion-explanation')).toBeHidden();
  await expect(page.locator('.location-conversion-safety')).toBeVisible();
  await expect(page.locator('#btnConvertOverworldNether')).toBeEnabled();
  await expect(page.locator('#locationConversionNote')).toBeHidden();
  await page.locator('#btnConversionHelp').focus();
  const healthTop = await page.locator('#statHealth').evaluate(el => el.getBoundingClientRect().top + scrollY);
  await page.keyboard.press('Enter');
  await expect(help.locator('.location-conversion-explanation')).toBeVisible();
  await expect(help).toContainText('Die Höhe (Y) bleibt unverändert');
  expect(await page.locator('#statHealth').evaluate(el => el.getBoundingClientRect().top + scrollY)).toBeCloseTo(healthTop, 0);
  await page.keyboard.press('Escape');
  await expect(help.locator('.location-conversion-explanation')).toBeHidden();
  await expect(page.locator('#btnConversionHelp')).toBeFocused();
  await page.locator('#btnConversionHelp').click();
  await help.getByRole('button', { name: 'Schließen' }).click();
  await expect(help).toBeHidden();
  await page.locator('#btnConversionHelp').click();
  await page.locator('#statHealth').click();
  await expect(help).toBeHidden();
  await page.locator('#statDimensionId').selectOption('1');
  await expect(page.locator('#btnConvertOverworldNether')).toBeEnabled();
});

test("player view survives resizing across the compact panel breakpoint", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 1000 });
  await openDragFixture(page);
  await page.locator('.app-section-nav button[data-workflow-view="player"]').click();
  for (const layout of ["classic", "studio", "focus"]) {
    await page.setViewportSize({ width: 1280, height: 1000 });
    await selectSetting(page, "layoutSelect", layout);
    await page.locator(layout === "classic"
      ? '.app-section-nav button[data-workflow-view="player"]'
      : '.layout-context-chip[data-workflow-view="player"]').click();
    for (const width of [1080, 1025, 1024, 1000, 768, 390, 1280, 1000]) {
    await page.setViewportSize({ width, height: 1000 });
    await expect(page.locator('#playerManager')).toBeVisible();
    await expect(page.locator('#playersList')).toBeVisible();
    if (layout === "classic") await expect(page.locator('#dashboardPanel')).toBeVisible();
    await expect(page.locator('.panel-toggle')).toBeHidden();
    }
  }
});

test("modal dialogs isolate editor shortcuts and restore focus", async ({ page }) => {
  const errors = collectBrowserErrors(page);
  await openDragFixture(page);
  await page.locator('[data-slot="0"]').dragTo(page.locator('[data-slot="1"]'));
  const state = () => page.evaluate(() => ({
    inventory: JSON.stringify(inventory), selection: [...selectedSlots], dirty: isDirty,
    undo: document.getElementById('btnUndo').dataset.historyCount,
  }));
  const before = await state();
  for (const layout of ['classic', 'studio', 'focus']) {
    await selectLayout(page, layout);
    await page.locator('.app-workflow-nav [data-workflow-view="tools"]').click();
    await page.locator('[data-tab-dash="dashIcons"]').click();
    await page.locator('#btnOpenIconSource').click();
    await page.locator('#btnCloseIconSource').focus();
    for (const key of ['Control+z', 'Control+y', 'Control+s', 'Control+Shift+p', 'Meta+Shift+p']) {
      await page.keyboard.press(key);
      expect(await state()).toEqual(before);
      await expect(page.locator('#dashIcons')).toBeVisible();
      await expect(page.locator('#iconSourceDialog')).toBeVisible();
    }
    await expect(page.locator('#iconSourceDialog')).toBeVisible();
    await expect(page.locator('#saveReviewOverlay')).toBeHidden();
    expect(await state()).toEqual(before);
    await page.keyboard.press('Escape');
    await expect(page.locator('#iconSourceDialog')).toBeHidden();
    await expect(page.locator('#btnOpenIconSource')).toBeFocused();
    expect(await state()).toEqual(before);
    await page.keyboard.press('Control+Shift+p');
    await expect(page.locator('#dashWorkspace')).toBeVisible();
    await page.locator('[data-workflow-view="player"]').first().evaluate(el => el.click());
    for (const dialog of ['playerTransferDialog', 'playerExportDialog', 'playerImportDialog']) {
      const opener = page.locator(`[data-player-tool="${dialog}"]`);
      await opener.click();
      await expect(page.locator(`#${dialog} [data-close-player-tool]`)).toBeFocused();
      const activeTab = await page.locator('.tab-content-dash.active').getAttribute('id');
      for (const key of ['Control+z', 'Control+y', 'Control+s', 'Control+Shift+p', 'Meta+Shift+p']) {
        await page.keyboard.press(key);
        expect(await state()).toEqual(before);
        await expect(page.locator('.tab-content-dash.active')).toHaveAttribute('id', activeTab);
      }
      await expect(page.locator('#saveReviewOverlay')).toBeHidden();
      await page.keyboard.press('Escape');
      await expect(page.locator(`#${dialog}`)).toBeHidden();
      await expect(opener).toBeFocused();
      expect(await state()).toEqual(before);
    }
  }
  expect(errors).toEqual([]);
});

test("catalog conflicts lock effect editing while preserving other editor controls", async ({ page }) => {
  const errors = collectBrowserErrors(page);
  const warning = 'Effekte: Kollidierende Einträge im numerischen Katalog. Betroffene IDs: 1, 99. Bearbeitung gesperrt; vorhandene Daten bleiben erhalten.';
  await openDragFixture(page, {
    effects: [{id: 1, amplifier: 0, duration: 200, show_particles: true}],
    effects_db: {}, catalog_warnings: [warning],
    ench_db: {17: {name_de: 'Haltbarkeit', name_en: 'Unbreaking', max_lvl: 3}},
  });
  await expect(page.locator('#statusStackButton')).toContainText('Betroffene IDs: 1, 99');
  await page.locator('.app-section-nav button[data-workflow-view="player"]').click();
  await page.locator('[data-tab-dash="dashEffects"]').click();
  await expect(page.locator('#btnOpenEffectPicker')).toBeDisabled();
  await expect(page.locator('#effectsContainer .effect-row')).toHaveCount(1);
  await expect(page.locator('#effectsContainer .eff-level')).toBeDisabled();
  await expect(page.locator('#effectsContainer .eff-duration')).toBeDisabled();
  await page.locator('[data-tab-dash="dashStats"]').click();
  await expect(page.locator('#statHealth')).toBeEnabled();
  expect(errors).toEqual([]);
});

for (const layout of ['classic', 'studio', 'focus']) {
  test(`main workflows retain their content across responsive breakpoints (${layout})`, async ({ page }) => {
    await openDragFixture(page);
    await page.setViewportSize({ width: 1440, height: 1000 });
    await selectSetting(page, 'layoutSelect', layout);
    for (const [view, content] of [['world', '#worldPicker'], ['player', '#playerManager'], ['inventory', '#inventoryContainer'], ['save', '#saveWorkflowPanel'], ['tools', '#dashboardPanel'], ['mounts', '#mountsPanel']]) {
      await page.setViewportSize({ width: 1440, height: 1000 });
      // Use the existing navigation handler even when a layout places the action in its footer.
      await page.locator(`[data-workflow-view="${view}"]`).first().evaluate(el => el.click());
      for (const width of [1440, 1181, 1180, 1025, 1024, 1000, 761, 760, 390, 1025, 1440]) {
        await page.setViewportSize({ width, height: 1000 });
        await expect(page.locator(content), `${layout}/${view}/${width}`).toBeVisible();
      }
    }
  });
}

test("compact inventory preserves the chosen editor panel through resizes and navigation", async ({ page }) => {
  await page.setViewportSize({ width: 1000, height: 900 });
  await openDragFixture(page);
  await page.locator('.btn-toggle[data-panel="right"]').click();
  await expect(page.locator('.right-panel')).toBeVisible();
  for (const width of [1025, 1024, 390, 1000]) {
    await page.setViewportSize({ width, height: 900 });
    await expect(page.locator('.right-panel')).toBeVisible();
  }
  await page.locator('.app-section-nav button[data-workflow-view="player"]').click();
  await page.locator('.app-section-nav button[data-workflow-view="inventory"]').click();
  await expect(page.locator('#inventoryContainer')).toBeVisible();
});

for (const width of [390, 1024, 1440]) {
  test(`design transitions preserve pending edits and the active editor (${width}px)`, async ({ page }) => {
    const errors = collectBrowserErrors(page);
    await page.setViewportSize({ width, height: 900 });
    await openDragFixture(page, { stack_limits: { "minecraft:stone": 64, __default__: 64 } });
    if (width === 1024) await selectSetting(page, 'themeSelect', 'light');
    await selectLayout(page, 'studio');
    await page.locator('[data-slot="0"]').click();
    await page.locator('#detailCount').fill('12');
    await page.locator("#detailSlotNum").click();
    await expect(page.locator('body')).toHaveClass(/app-dirty/);
    await page.locator('#detailCustomName').fill('Unapplied slot draft');
    await page.locator('#detailLore').fill('Draft line one\nDraft line two');
    const unexpectedRequests = [];
    page.on('request', request => {
      if (/\/api\/(player\/(load|save)|world\/load|workspace\/save)(?:\?|$)/.test(request.url())) unexpectedRequests.push(request.url());
    });
    const initial = await page.evaluate(() => ({
      inventory: JSON.stringify(inventory), player: currentPlayerKey, world: worldPath,
    }));
    const transitions = ['focus', 'classic', 'studio', 'classic', 'focus', 'studio'];
    for (const layout of transitions) {
      await selectLayout(page, layout);
      await expect(page.locator('#detailEditorPanel')).toBeVisible();
      await expect(page.locator('#detailCustomName')).toHaveValue('Unapplied slot draft');
      await expect(page.locator('#detailLore')).toHaveValue('Draft line one\nDraft line two');
      await expect(page.locator('#detailSlotNum')).toHaveText('0');
      expect(await page.evaluate(() => ({
        inventory: JSON.stringify(inventory), player: currentPlayerKey, world: worldPath,
      }))).toEqual(initial);
      await expect(page.locator('body')).toHaveClass(/app-dirty/);
    }
    await page.locator('.app-workflow-nav [data-workflow-view="player-edit"]').click();
    await page.locator('#statHealth').fill('13');
    await page.locator('[data-tab-dash="dashEffects"]').click();
    await page.locator('#abMovementSpeed').fill('0.17');
    for (const layout of transitions) {
      await selectLayout(page, layout);
      await expect(page.locator('#dashboardPanel')).toBeVisible();
      await expect(page.locator('#dashEffects')).toBeVisible();
      await expect(page.locator('#abMovementSpeed')).toHaveValue('0.17');
      await expect(page.locator('#statHealth')).toHaveValue('13');
      await expect(page.locator('body')).toHaveClass(/app-dirty/);
      expect(await page.evaluate(() => ({
        inventory: JSON.stringify(inventory), player: currentPlayerKey, world: worldPath,
      }))).toEqual(initial);
    }
    expect(unexpectedRequests).toEqual([]);
    expect(errors).toEqual([]);
  });
}

for (const layout of ['classic', 'studio', 'focus']) {
  test(`conversion can be reverted before applying and globally undone after applying (${layout})`, async ({ page }) => {
    await openDragFixture(page, { stats: { pos: [94.41, 71.62, 93.52], dimension_id: 0, health: 20, xp_level: 0, xp_progress: 0, food_level: 20, food_saturation: 5, gamemode: 0 } });
    await selectLayout(page, layout);
    await page.locator(`.app-workflow-nav [data-workflow-view="${layout === 'classic' ? 'player' : 'player-edit'}"]`).click();
    const convert = page.locator('#btnConvertOverworldNether');
    await convert.click();
    await expect(page.locator('#statPosX')).toHaveValue('11.80125');
    await expect(convert).toHaveText('Umrechnung zurücknehmen');
    await expect(page.locator('#btnUndo')).toBeDisabled();
    await page.locator('#statPosY').fill('75');
    await convert.click();
    await expect(page.locator('#statPosX')).toHaveValue('94.41');
    await expect(page.locator('#statPosZ')).toHaveValue('93.52');
    await expect(page.locator('#statPosY')).toHaveValue('75');
    await expect(page.locator('#statDimensionId')).toHaveValue('0');
    await convert.click();
    await page.locator('#btnApplyStats').click();
    await expect(convert).toHaveText('Zur Oberwelt umrechnen (X/Z × 8)');
    await page.locator('#btnUndo').click();
    await expect(page.locator('#statDimensionId')).toHaveValue('0');
    await expect(page.locator('#statPosX')).toHaveValue('94.41');
    await page.locator('#btnRedo').click();
    await expect(page.locator('#statDimensionId')).toHaveValue('1');
    await expect(page.locator('#statPosX')).toHaveValue('11.80');
    expect(await page.evaluate(() => playerStats.pos[0])).toBe(11.80125);
    await page.locator('#statDimensionId').selectOption('0');
    await convert.click();
    await expect(page.locator('#statPosX')).toHaveValue('94.41');
    await convert.click();
    await expect(page.locator('#statPosX')).toHaveValue('11.80');
  });
}

test('effect cards use one to three columns based on available width in every design', async ({ page }) => {
  await openDragFixture(page, {
    effects: [1, 2, 3, 4].map(id => ({ id, amplifier: 0, duration: 600, show_particles: true })),
    effects_db: {1: ['Tempo', 'Speed'], 2: ['Langsamkeit', 'Slowness'], 3: ['Eile', 'Haste'], 4: ['Abbaulähmung', 'Mining Fatigue']},
  });
  for (const layout of ['classic', 'studio', 'focus']) {
    await selectLayout(page, layout);
    await page.locator(`.app-workflow-nav [data-workflow-view="${layout === 'classic' ? 'player' : 'player-edit'}"]`).click();
    await page.locator('[data-tab-dash="dashEffects"]').click();
    for (const theme of ['dark', 'light']) {
      await selectSetting(page, 'themeSelect', theme);
      for (const width of [390, 1024, 1830, 2560]) {
        await page.setViewportSize({width, height: 1000});
        const grid = page.locator('#effectsContainer');
        await expect(grid).toBeVisible();
        const geometry = await grid.evaluate(el => {
          const style = getComputedStyle(el);
          return { columns: style.gridTemplateColumns.split(' ').length, width: el.clientWidth,
            overflow: document.documentElement.scrollWidth - innerWidth };
        });
        const min = 23 * await page.locator('html').evaluate(el => parseFloat(getComputedStyle(el).fontSize));
        const expected = Math.min(3, Math.max(1, Math.floor((geometry.width + 12) / (min + 12))));
        expect(geometry.columns, `${layout}/${theme}/${width}`).toBe(expected);
        expect(geometry.overflow).toBeLessThanOrEqual(1);
      }
    }
  }
});

test('Focus header status labels share a font size at desktop and mobile widths', async ({ page }) => {
  await openDragFixture(page);
  await selectLayout(page, 'focus');
  for (const width of [390, 1440]) {
    await page.setViewportSize({width, height: 900});
    const fonts = await page.evaluate(() => {
      const status = getComputedStyle(document.getElementById('serverStatusBadge'), '::after');
      const messages = getComputedStyle(document.getElementById('statusStackButton'), '::after');
      return {status: status.fontSize, messages: messages.fontSize, statusWeight: status.fontWeight, messageWeight: messages.fontWeight};
    });
    expect(fonts.status).toBe(fonts.messages);
    console.log(`Focus header ${width}px: ${JSON.stringify(fonts)}`);
  }
});

for (const width of [390, 1440]) {
  test.describe(`database update interaction at ${width}px`, () => {
    test.use({viewport: {width, height: 900}, hasTouch: width < 500, isMobile: width < 500});
    test('reviews, cancels, applies the reviewed sources and checks again', async ({page}) => {
      const errors = collectBrowserErrors(page);
      const activate = locator => width < 500 ? locator.tap() : locator.click();
      let applied = false;
      let releasePreview;
      const pendingPreview = new Promise(resolve => { releasePreview = resolve; });
      const requests = [];
      await page.route('**/api/item-db/status', route => route.fulfill({json: {success: true, item_db: {
        status: 'ok', verification: {verified: true}, counts: {items: 8},
        source_version: {resource_pack_release: applied ? 'v1.26.50.4' : 'v1.26.40.05'},
      }}}));
      await page.route('**/api/update_db', async route => {
        const request = route.request().postDataJSON();
        requests.push(request);
        if (requests.length === 1) await pendingPreview;
        const wasApplied = applied;
        if (!request.dry_run) applied = true;
        await route.fulfill({json: {
          success: true, reloaded: !request.dry_run, update_committed: !request.dry_run,
          update_review_token: request.dry_run ? 'a'.repeat(64) : undefined, resource_pack_release: 'v1.26.50.4',
          output: 'Synthetic local update check',
          summary: {schema: 1, status: wasApplied ? 'current' : 'available', scope: 'all',
            previous_release: wasApplied ? 'v1.26.50.4' : 'v1.26.40.05', release: 'v1.26.50.4', blocked: [],
            sections: {effects: {added: 0, removed: 0, changed: wasApplied ? 0 : 37}},
            change_details: {effects: {descriptions_only: wasApplied ? 0 : 37, other_changes: 0}},
            audit: {checked_items: 2164, issues: [], expected_name_differences: [
              {id: 'minecraft:bed', locale: 'de', catalog: 'Weißes Bett', source: 'Bett'},
              {id: 'minecraft:bed', locale: 'en', catalog: 'White Bed', source: 'Bed'},
            ]},
          },
        }});
      });
      await openAppWithEmptyWorldScan(page);
      await activate(page.locator('.app-workflow-nav [data-workflow-view="tools"]'));
      await activate(page.locator('[data-tab-dash="dashUpdate"]'));
      await activate(page.locator('#btnUpdateDbDryRun'));
      await expect(page.locator('#btnClearUpdateOutput')).toBeDisabled();
      await expect(page.locator('#btnUpdateDbApply')).toBeDisabled();
      releasePreview();
      const result = page.locator('#updateDbResult');
      await expect(result).toContainText('37 Effektbeschreibungen aktualisiert');
      await activate(page.locator('#btnUpdateDbApply'));
      await expect(page.locator('#confirmOverlay')).toContainText('zuvor geprüften Quellen (Mojang v1.26.50.4)');
      await activate(page.locator('#confirmCancel'));
      expect(requests).toHaveLength(1);
      await expect(result).toContainText('Vorschau – noch nicht übernommen');
      await activate(page.locator('#btnUpdateDbApply'));
      await activate(page.locator('#confirmOk'));
      await expect(result).toContainText('Änderungen an der Item-Datenbank übernommen.');
      await expect(result).not.toContainText('Vorschau');
      expect(requests[1]).toMatchObject({dry_run: false, force: true, only: null, expected_update_review_token: 'a'.repeat(64)});
      await expect(page.locator('.item-db-version-line')).toContainText('v1.26.50.4');
      await activate(page.locator('#btnUpdateDbDryRun'));
      await expect(result).toContainText('Keine inhaltlichen Änderungen');
      await expect(result).toContainText('Kein Update erforderlich.');
      await expect(result).not.toContainText('Vorschau');
      await expect(result).not.toContainText('37');
      await expect(result.locator('.update-db-source-comparison')).not.toContainText('v1.26.40.05');
      await expect(page.locator('#updateDbDetails')).toBeHidden();
      await expect(page.locator('.update-db-name-list')).toBeHidden();
      await activate(page.locator('#updateDbLogDetails > summary'));
      await expect(page.locator('.update-db-name-list')).toBeVisible();
      await expect(page.locator('#updateDbLogDetails details')).toHaveCount(0);
      await expect(page.locator('.update-db-name-list')).toContainText('Weißes Bett');
      await expect(page.locator('.update-db-name-list')).not.toContainText('White Bed');
      await expect(page.locator('#btnUpdateDbApply')).toBeDisabled();
      await expect(page.locator('#updateDbActionHint')).toContainText('Keine Änderungen bei der letzten Prüfung');
      expect(requests).toHaveLength(3);
      await activate(page.locator('#btnUpdateDbDryRun'));
      await expect(result).toContainText('Kein Update erforderlich.');
      await expect(page.locator('#btnUpdateDbApply')).toBeDisabled();
      await expect(page.locator('#updateDbDetails')).not.toHaveAttribute('open', '');
      await page.locator('#btnUpdateDbDryRun').focus();
      await page.keyboard.press('Tab');
      await expect(page.locator('#btnClearUpdateOutput')).toBeFocused();
      await captureBrowserEvidence(page, `db-current-controls-${width}`, '#dashUpdate');
      await activate(page.locator('#btnClearUpdateOutput'));
      await expect(page.locator('.update-db-output-wrapper')).toBeHidden();
      await expect(page.locator('#btnUpdateDbDryRun')).toBeFocused();
      await expect(page.locator('#btnUpdateDbApply')).toBeDisabled();
      await activate(page.locator('.update-db-options > summary'));
      await page.locator('#updateOnlySelect').selectOption('items');
      await expect(page.locator('#btnUpdateDbApply')).toBeEnabled();
      await expect(page.locator('#updateDbActionHint')).toContainText('Prüfe zuerst die Vorschau');
      await page.locator('#updateOnlySelect').selectOption('');
      await expect(page.locator('#btnUpdateDbApply')).toBeEnabled();
      await captureBrowserEvidence(page, `db-scope-width-${width}`, '#dashUpdate');
      expect(errors).toEqual([]);
    });
    test('shows a partial write and refreshes the active database after a section fails', async ({page}) => {
      const errors = collectBrowserErrors(page);
      const activate = locator => width < 500 ? locator.tap() : locator.click();
      let applied = false;
      await page.route('**/api/item-db/status', route => route.fulfill({json: {success: true, item_db: {
        status: 'ok', verification: {verified: false}, counts: {items: 8},
        source_version: {resource_pack_release: applied ? 'v1.26.50.4' : 'v1.26.40.05'},
      }}}));
      await page.route('**/api/update_db', route => {
        applied = true;
        return route.fulfill({json: {
          success: false, returncode: 1, update_committed: true, reloaded: true, error: 'Synthetic missing effect ID',
          summary: {schema: 1, status: 'incomplete', applied: true, previous_release: 'v1.26.40.05', release: 'v1.26.50.4',
            sections: {items: {added: 1, removed: 0, changed: 0}}, blocked: [{section: 'EFFECTS', reason: 'Synthetic missing effect ID'}]},
        }});
      });
      await openAppWithEmptyWorldScan(page);
      await activate(page.locator('.app-workflow-nav [data-workflow-view="tools"]'));
      await activate(page.locator('[data-tab-dash="dashUpdate"]'));
      await activate(page.locator('#btnUpdateDbApply'));
      await activate(page.locator('#confirmOk'));
      await expect(page.locator('#updateDbResult')).toContainText('Aktualisierung teilweise übernommen');
      await expect(page.locator('#updateDbResult')).toContainText('bereits gespeichert');
      await expect(page.locator('#updateDbResult')).toContainText('Effekte: Synthetic missing effect ID');
      await expect(page.locator('.item-db-version-line')).toContainText('v1.26.50.4');
      await expect(page.locator('#btnUpdateDbApply')).toBeEnabled();
      expect(errors).toEqual([]);
    });
  });
}
