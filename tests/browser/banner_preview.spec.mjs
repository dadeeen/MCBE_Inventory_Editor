import { expect, test } from "@playwright/test";
import {
  openSpecialFixture,
  prepareBannerTextures,
  collectBrowserErrors,
} from "./fixtures/app.mjs";

test("shared banner icons render color and fixed motifs without replacing pending forms", async ({ page }) => {
  const errors = collectBrowserErrors(page);
  const banner = (slot, damage, type = 0) => ({ slot, name: "minecraft:banner", count: 1, damage,
    special_item: { kind: "banner", editable: true, data: { type, patterns: [] } } });
  await openSpecialFixture(page, { 0: banner(0, 4), 1: banner(1, 15, 1) });
  await page.locator('.inventory-slot[data-slot="0"]').click();
  await page.locator("#detailCount").fill("");
  await page.locator("#detailCustomName").fill("Keep pending name");
  const { assets } = await prepareBannerTextures(page, { synthetic: true });
  const pixels = await page.evaluate(async assets => {
    const colors = JSON.parse(document.getElementById("specialItemSchema").textContent).color_hex;
    const renderer = window.MCBEBannerPreview.createRenderer(document);
    const normal = await renderer.render(4, [], assets, colors);
    const ominous = await renderer.render(0, [], assets, colors, 1);
    return [normal, ominous].map(canvas => Array.from(canvas.getContext("2d").getImageData(8, 8, 1, 1).data));
  }, assets);
  expect(pixels).toEqual([[47, 53, 133, 255], [25, 155, 170, 255]]);
  for (const slot of [0, 1]) await expect(page.locator(`.inventory-slot[data-slot="${slot}"] img`)).toHaveAttribute("src", /^data:image\/png/);
  await expect(page.locator("#detailCustomName")).toHaveValue("Keep pending name");
  await expect(page.locator("#btnUndo")).toBeDisabled();
  // A late picture must not overwrite an element that already shows another item.
  await page.evaluate(async assets => {
    const colors = JSON.parse(document.getElementById("specialItemSchema").textContent).color_hex;
    const getIcon = window.MCBEBannerPreview.createIconProvider(document, () => assets, colors);
    const delayed = getIcon({ name: "minecraft:banner", damage: 4 });
    const image = document.createElement("img"); image.id = "qa-stale-banner"; image.src = delayed.url;
    document.body.append(image); image.src = "data:image/svg+xml," + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg"/>');
    window.qaBannerIcon = delayed;
  }, assets);
  await expect.poll(() => page.evaluate(() => window.qaBannerIcon.url.startsWith("data:image/png"))).toBe(true);
  await expect(page.locator("#qa-stale-banner")).toHaveAttribute("src", /^data:image\/svg/);
  expect(errors).toEqual([]);
});

test("banner conversion restores the pending normal design until accepted", async ({ page }) => {
  const original = { slot: 0, name: "minecraft:banner", count: 1, damage: 4, display_name: "Keep name", lore: ["Keep lore"],
    special_item: { kind: "banner", editable: true, data: { patterns: [{ pattern: "bri", color: 1, source_index: 0 }] } } };
  await openSpecialFixture(page, { 0: original });
  await prepareBannerTextures(page);
  await page.locator('.inventory-slot[data-slot="0"]').click(); await page.locator("#btnSpecialItem").click();
  const dialog = page.locator("#specialItemDialog");
  await dialog.getByLabel("Farbe", { exact: true }).selectOption("5");
  await dialog.getByRole("button", { name: "Muster hinzufügen" }).click();
  await dialog.getByLabel("Muster", { exact: true }).nth(1).selectOption("mc");
  await dialog.getByLabel("Bannerart", { exact: true }).selectOption("1");
  await expect(dialog.locator(".special-banner-layers")).toBeHidden();
  await expect(dialog.locator(".special-banner-warning")).toHaveCount(0);
  await dialog.getByLabel("Bannerart", { exact: true }).selectOption("0");
  await expect(dialog.locator(".special-banner-preview")).toContainText("Grundfarbe: Blau");
  await expect(dialog.getByLabel("Farbe", { exact: true }).first()).toHaveValue("5");
  await expect(dialog.getByLabel("Muster", { exact: true }).nth(1)).toHaveValue("mc");
  await dialog.locator('[data-special-row="1"] [data-special-action="up"]').click();
  await expect(dialog.getByLabel("Muster", { exact: true }).first()).toHaveValue("mc");
  for (const [name, width, height] of [["desktop", 1440, 1000], ["mobile", 390, 844]]) {
    await page.setViewportSize({ width, height });
    expect(await dialog.locator(".special-body").evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
    if (process.env.MCBE_QA_SPECIAL_DIR) await dialog.screenshot({ path: `${process.env.MCBE_QA_SPECIAL_DIR}/banner-controls-${name}.png` });
  }
  await dialog.getByLabel("Bannerart", { exact: true }).selectOption("1");
  await expect(dialog.locator(".special-banner-warning")).toHaveCount(0);
  await dialog.locator('[data-special="accept"]').click();
  expect(await page.evaluate(() => inventory[0])).toMatchObject({ damage: 15, display_name: "Keep name", lore: ["Keep lore"],
    special_edit: { kind: "banner", data: { type: 1, patterns: [] } } });
  await page.locator("#btnUndo").click();
  expect(await page.evaluate(() => inventory[0].special_item.data)).toEqual(original.special_item.data);
  expect(await page.evaluate(() => inventory[0].damage)).toBe(4);
});

test("existing ominous hybrids show their overlay and stay unchanged on cancel and accept", async ({ page }) => {
  await openSpecialFixture(page, { 0: { slot: 0, name: "minecraft:banner", count: 1, damage: 4,
    display_name: "Keep name", lore: ["Keep lore"],
    special_item: { kind: "banner", editable: true, data: { type: 1, patterns: [{ pattern: "bri", color: 1, source_index: 0 }] } } } });
  const before = await page.evaluate(() => JSON.stringify(inventory[0]));
  await prepareBannerTextures(page, { synthetic: true });
  await page.locator('.inventory-slot[data-slot="0"]').click(); await page.locator("#btnSpecialItem").click();
  const dialog = page.locator("#specialItemDialog");
  const preview = dialog.locator(".special-banner-preview");
  await expect(preview).toHaveAttribute("data-state", "ready");
  await expect(dialog).toContainText("Abweichendes Bannerdesign");
  await expect(preview.locator("canvas")).toHaveAccessibleName(/Ominöses Banner; Ebene 1/);
  await expect(dialog.getByRole("button", { name: "Vanilla-Design wiederherstellen" })).toHaveCount(0);
  await expect(dialog.locator(".special-banner-layers")).toBeHidden();
  const mixed = await preview.locator("canvas").evaluate(el => el.toDataURL());
  await dialog.locator('[data-special="cancel"]').last().click();
  expect(await page.evaluate(() => JSON.stringify(inventory[0]))).toBe(before);
  await page.locator("#btnSpecialItem").click();
  await expect(dialog).toContainText("Abweichendes Bannerdesign");
  await expect(preview).toHaveAttribute("data-state", "ready");
  expect(await preview.locator("canvas").evaluate(el => el.toDataURL())).toBe(mixed);
  if (process.env.MCBE_QA_SPECIAL_DIR) await dialog.screenshot({ path: `${process.env.MCBE_QA_SPECIAL_DIR}/ominous-hybrid.png` });
  await dialog.locator('[data-special="accept"]').click();
  expect(await page.evaluate(() => JSON.stringify(inventory[0]))).toBe(before);
  await expect(page.locator("#btnUndo")).toBeDisabled();
});

test("a colored ominous banner is preserved on open and normalized by an explicit type conversion", async ({ page }) => {
  const original = { slot: 0, name: "minecraft:banner", count: 1, damage: 4,
    special_item: { kind: "banner", editable: true, data: { type: 1, patterns: [] } } };
  await openSpecialFixture(page, { 0: original });
  await page.locator('.inventory-slot[data-slot="0"]').click(); await page.locator("#btnSpecialItem").click();
  const dialog = page.locator("#specialItemDialog");
  await expect(dialog.locator(".special-banner-warning")).toBeVisible();
  await dialog.locator('[data-special="accept"]').click();
  expect(await page.evaluate(() => inventory[0])).toMatchObject(original);
  expect(await page.evaluate(() => inventory[0].special_edit)).toBeUndefined();
  await page.locator("#btnSpecialItem").click();
  await dialog.getByLabel("Bannerart", { exact: true }).selectOption("0");
  await expect(dialog.locator(".special-banner-preview")).toContainText("Grundfarbe: Blau");
  await dialog.getByRole("button", { name: "Muster hinzufügen" }).click();
  await dialog.getByLabel("Farbe", { exact: true }).selectOption("5");
  await dialog.getByLabel("Bannerart", { exact: true }).selectOption("1");
  await expect(dialog.locator(".special-banner-warning")).toHaveCount(0);
  await dialog.getByLabel("Bannerart", { exact: true }).selectOption("0");
  await expect(dialog.locator(".special-banner-preview")).toContainText("Grundfarbe: Blau");
  await expect(dialog.getByLabel("Farbe", { exact: true })).toHaveValue("5");
  await dialog.getByLabel("Bannerart", { exact: true }).selectOption("1");
  await dialog.locator('[data-special="accept"]').click();
  expect(await page.evaluate(() => inventory[0].damage)).toBe(15);
  expect(await page.evaluate(() => inventory[0].special_item.data)).toEqual(original.special_item.data);
});

test("ominous banner preview stays usable at desktop and mobile sizes", async ({ page }) => {
  await openSpecialFixture(page, { 0: { slot: 0, name: "minecraft:banner", count: 1, damage: 15,
    special_item: { kind: "banner", editable: true, data: { type: 1, patterns: [] } } } });
  await prepareBannerTextures(page);
  await page.locator('.inventory-slot[data-slot="0"]').click(); await page.locator("#btnSpecialItem").click();
  const dialog = page.locator("#specialItemDialog");
  await expect(dialog.locator(".special-banner-preview")).toHaveAttribute("data-state", "ready");
  await expect(dialog.locator(".special-banner-layers")).toBeHidden();
  for (const [name, width, height] of [["desktop", 1440, 1000], ["mobile", 390, 844]]) {
    await page.setViewportSize({ width, height });
    expect(await dialog.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
    await expect(dialog.locator('footer [data-special="accept"]')).toBeInViewport();
    if (process.env.MCBE_QA_SPECIAL_DIR) await dialog.screenshot({ path: `${process.env.MCBE_QA_SPECIAL_DIR}/ominous-${name}.png` });
  }
  await page.keyboard.press("Escape");
  await expect(page.locator("#btnUndo")).toBeDisabled();
});

test("banner preview renders all motifs and keeps desktop and mobile layouts usable", async ({ page }) => {
  const errors = collectBrowserErrors(page);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await openSpecialFixture(page, { 0: { slot: 0, name: "minecraft:banner", count: 1, damage: 15 } });
  const { assets } = await prepareBannerTextures(page);
  await page.locator('.inventory-slot[data-slot="0"]').click(); await page.locator("#btnSpecialItem").click();
  const dialog = page.locator("#specialItemDialog");
  const preview = dialog.locator(".special-banner-preview");
  const canvas = preview.locator("canvas");
  await dialog.getByRole("button", { name: "Muster hinzufügen" }).click();
  await dialog.getByLabel("Farbe", { exact: true }).selectOption("4");
  const images = [];
  for (const pattern of Object.keys(assets).filter(code => !["base", "illager"].includes(code))) {
    await dialog.getByLabel("Muster", { exact: true }).selectOption(pattern);
    await expect(preview).toHaveAttribute("data-state", "ready");
    images.push({ pattern, url: await canvas.evaluate(el => el.toDataURL()) });
  }
  expect(new Set(images.map(image => image.url)).size).toBe(42);
  await dialog.getByLabel("Muster", { exact: true }).selectOption("glb");
  await expect(canvas).toHaveAccessibleName(/Globus, Blau/);
  await expect(preview).toHaveAttribute("data-state", "ready");
  for (const [name, width, height] of [["desktop", 1440, 1000], ["mobile", 390, 844], ["narrow", 320, 568], ["landscape", 844, 390]]) {
    await page.setViewportSize({ width, height });
    await canvas.scrollIntoViewIfNeeded();
    expect(await dialog.evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
    expect(await dialog.locator(".special-body").evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
    const bounds = await dialog.evaluate(el => ({
      bottom: el.getBoundingClientRect().bottom, footerTop: el.querySelector("footer").getBoundingClientRect().top,
      footerBottom: el.querySelector("footer").getBoundingClientRect().bottom, bodyBottom: el.querySelector(".special-body").getBoundingClientRect().bottom,
    }));
    expect(bounds.bodyBottom).toBeLessThanOrEqual(bounds.footerTop + 1);
    expect(bounds.footerBottom).toBeLessThanOrEqual(bounds.bottom + 1);
    const size = await canvas.boundingBox(); expect(size.height / size.width).toBe(2);
    if (process.env.MCBE_QA_SPECIAL_DIR) await dialog.screenshot({ path: `${process.env.MCBE_QA_SPECIAL_DIR}/banner-${name}.png`, animations: "disabled" });
    // The inputs and apply action remain reachable at every viewport size.
    await dialog.getByLabel("Farbe", { exact: true }).selectOption("1");
    await expect(preview).toHaveAttribute("data-state", "ready");
    await dialog.getByLabel("Farbe", { exact: true }).selectOption("4");
  }
  await dialog.getByRole("button", { name: "Übernehmen", exact: true }).click();
  expect(await page.evaluate(() => inventory[0].special_edit.data.patterns)).toEqual([{ pattern: "glb", color: 4 }]);
  await page.locator("#btnUndo").click();
  expect(await page.evaluate(() => inventory[0].special_edit)).toBeUndefined();
  if (process.env.MCBE_QA_SPECIAL_DIR) {
    await page.setViewportSize({ width: 1200, height: 1200 });
    await page.evaluate(images => {
      const gallery = document.createElement("div"); gallery.id = "qa-banner-gallery";
      gallery.style.cssText = "position:absolute;inset:0;z-index:99999;display:grid;grid-template-columns:repeat(7,1fr);gap:16px;padding:24px;background:#17232c;color:white;";
      images.forEach(({ pattern, url }) => {
        const cell = document.createElement("div"); cell.style.cssText = "display:grid;justify-items:center;gap:6px;";
        const image = document.createElement("img"); image.src = url; image.style.cssText = "width:60px;height:120px;image-rendering:pixelated";
        cell.append(image, document.createTextNode(pattern)); gallery.append(cell);
      }); document.body.append(gallery);
    }, images);
    await page.locator("#qa-banner-gallery").screenshot({ path: `${process.env.MCBE_QA_SPECIAL_DIR}/banner-all-patterns.png` });
  }
  expect(errors).toEqual([]);
});

test("banner preview preserves alpha, dye color and layer order through edits and cancel", async ({ page }) => {
  await openSpecialFixture(page, { 0: { slot: 0, name: "minecraft:banner", count: 1, damage: 15, special_item: { kind: "banner", editable: true,
    data: { patterns: [{ pattern: "cre", color: 1 }, { pattern: "glb", color: 4 }] } } } });
  await prepareBannerTextures(page, { synthetic: true });
  await page.locator('.inventory-slot[data-slot="0"]').click(); await page.locator("#btnSpecialItem").click();
  const dialog = page.locator("#specialItemDialog");
  const preview = dialog.locator(".special-banner-preview");
  async function pixel(x, y) {
    await expect(preview).toHaveAttribute("data-state", "ready");
    return preview.locator("canvas").evaluate((el, [x, y]) => Array.from(el.getContext("2d").getImageData(x, y, 1, 1).data), [x, y]);
  }
  // Bottom-right is tinted base cloth; lower-left is opaque red; upper-left
  // is half-transparent blue over red (rounded source-over blend).
  expect(await pixel(15, 30)).toEqual([188, 188, 188, 255]);
  expect(await pixel(5, 30)).toEqual([176, 46, 38, 255]);
  const blend = await pixel(5, 5);
  for (const [index, value] of [118, 57, 104, 255].entries()) expect(Math.abs(blend[index] - value)).toBeLessThanOrEqual(1);
  await dialog.getByRole("button", { name: "Nach oben", exact: true }).nth(1).click();
  expect(await pixel(5, 5)).toEqual([176, 46, 38, 255]);
  await dialog.getByRole("button", { name: "Entfernen", exact: true }).nth(1).click();
  await dialog.getByLabel("Muster", { exact: true }).selectOption("gra");
  expect(await pixel(5, 0)).toEqual([188, 188, 188, 255]);
  expect(await pixel(5, 39)).toEqual([60, 68, 170, 255]);
  await page.keyboard.press("Escape");
  await expect(page.locator("#btnUndo")).toBeDisabled();
});

test("banner preview recovers missing assets without losing a draft", async ({ page }) => {
  await openSpecialFixture(page, { 0: { slot: 0, name: "minecraft:banner", count: 1, damage: 15 } });
  const { response } = await prepareBannerTextures(page, { synthetic: true, publish: false });
  let attempts = 0;
  await page.route("**/api/icons/vanilla/update", route => {
    attempts++;
    return route.fulfill({ json: attempts === 1 ? { success: false, error: "Test: Download unterbrochen" } : response });
  });
  await page.locator('.inventory-slot[data-slot="0"]').click(); await page.locator("#btnSpecialItem").click();
  const dialog = page.locator("#specialItemDialog");
  await dialog.getByRole("button", { name: "Muster hinzufügen" }).click();
  await dialog.getByLabel("Muster", { exact: true }).selectOption("sku");
  await expect(dialog.locator(".special-banner-preview")).toHaveAttribute("data-state", "missing");
  await expect(dialog.locator("canvas")).toBeHidden();
  await dialog.getByRole("button", { name: "Bannermuster laden" }).click();
  await expect(dialog.getByRole("status")).toContainText("Download unterbrochen");
  await dialog.getByRole("button", { name: "Bannermuster laden" }).click();
  await expect(dialog.locator(".special-banner-preview")).toHaveAttribute("data-state", "ready");
  await expect(dialog.getByLabel("Muster", { exact: true })).toHaveValue("sku");
  await expect(page.locator("#btnUndo")).toBeDisabled();
  expect(attempts).toBe(2);
  await page.keyboard.press("Escape");
});

test("banner preview rejects broken textures, retries, and discards late renders", async ({ page }) => {
  await openSpecialFixture(page, { 0: { slot: 0, name: "minecraft:banner", count: 1, damage: 15 } });
  const { generated, response } = await prepareBannerTextures(page, { synthetic: true, publish: false });
  await page.route("**/api/icons/qa-banner-base", route => route.fulfill({ contentType: "image/png", body: Buffer.from("invalid") }));
  // Install the broken texture before publishing assets can warm the renderer cache.
  await page.route("**/api/icons/status*", route => route.fulfill({ json: response }));
  await page.evaluate(() => loadLocalIconIndex());
  await page.locator('.inventory-slot[data-slot="0"]').click(); await page.locator("#btnSpecialItem").click();
  const dialog = page.locator("#specialItemDialog");
  const preview = dialog.locator(".special-banner-preview");
  await expect(preview).toHaveAttribute("data-state", "error");
  await page.unroute("**/api/icons/qa-banner-base");
  await dialog.getByRole("button", { name: "Erneut versuchen" }).click();
  await expect(preview).toHaveAttribute("data-state", "ready");
  let release;
  const delayed = new Promise(resolve => { release = resolve; });
  await page.route("**/api/icons/qa-banner-cre", async route => {
    await delayed; await route.fulfill({ contentType: "image/png", body: Buffer.from(generated.cre, "base64") });
  });
  await dialog.getByRole("button", { name: "Muster hinzufügen" }).click();
  await dialog.getByLabel("Muster", { exact: true }).selectOption("cre");
  await expect(preview).toHaveAttribute("data-state", "loading");
  await dialog.getByLabel("Muster", { exact: true }).selectOption("glb");
  await expect(preview).toHaveAttribute("data-state", "ready");
  const before = await preview.locator("canvas").evaluate(el => el.toDataURL());
  const lateResponse = page.waitForResponse("**/api/icons/qa-banner-cre");
  release();
  await (await lateResponse).finished();
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  expect(await preview.locator("canvas").evaluate(el => el.toDataURL())).toBe(before);
  await expect(preview.locator("canvas")).toHaveAccessibleName(/Globus/);
  await page.keyboard.press("Escape");
});

test.describe("banner preview touch interaction", () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 3 });
  test("six layers remain editable with a sharp preview on a mobile device", async ({ page }) => {
    await openSpecialFixture(page, { 0: { slot: 0, name: "minecraft:banner", count: 1, damage: 15, special_item: { kind: "banner", editable: true,
      data: { patterns: ["gra", "cre", "bri", "flw", "bo", "sku"].map((pattern, index) => ({ pattern, color: index })) } } } });
    await prepareBannerTextures(page);
    await page.locator('.inventory-slot[data-slot="0"]').tap();
    await page.locator('.btn-toggle[data-panel="right"]').tap();
    await page.locator("#btnSpecialItem").tap();
    const dialog = page.locator("#specialItemDialog");
    const preview = dialog.locator(".special-banner-preview");
    await expect(preview).toHaveAttribute("data-state", "ready");
    await expect(dialog.getByRole("button", { name: "Muster hinzufügen" })).toBeDisabled();
    await dialog.getByLabel("Muster", { exact: true }).nth(5).selectOption("gus");
    await dialog.getByLabel("Farbe", { exact: true }).nth(5).selectOption("1");
    await dialog.getByRole("button", { name: "Nach oben", exact: true }).nth(5).tap();
    await expect(preview).toHaveAttribute("data-state", "ready");
    await expect(preview.locator("canvas")).toHaveAccessibleName(/Ebene 5: Windstoßer, Rot/);
    await preview.scrollIntoViewIfNeeded();
    if (process.env.MCBE_QA_SPECIAL_DIR) await dialog.screenshot({ path: `${process.env.MCBE_QA_SPECIAL_DIR}/banner-touch.png`, animations: "disabled" });
    await dialog.getByRole("button", { name: "Übernehmen", exact: true }).tap();
    expect(await page.evaluate(() => inventory[0].special_edit.data.patterns[4])).toEqual({ pattern: "gus", color: 1 });
    await page.locator("#btnUndo").tap();
    expect(await page.evaluate(() => inventory[0].special_edit)).toBeUndefined();
  });
});
