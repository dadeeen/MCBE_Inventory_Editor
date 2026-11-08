import { test, expect } from "@playwright/test";
import fs from "node:fs/promises";
import path from "node:path";
import { collectBrowserErrors, openAppWithSmokeWorldScan, selectLayout, NORMAL_BASE_URL, VIEWER_BASE_URL } from "./fixtures/app.mjs";

function manyVillagers(count, locale = "de") {
    return Array.from({ length: count }, (_, index) => ({
        id: `actor:resident-${index + 1}`, unique_id: String(-9007199254740993n - BigInt(index)),
        revision: (index + 1).toString(16).padStart(64, "0"), identifier: "minecraft:villager_v2",
        name: `${locale === "en" ? "Villager" : "Bewohner"} ${String(index + 1).padStart(3, "0")}`,
        profession: index % 2 ? { id: "farmer", label: locale === "en" ? "Farmer" : "Farmer" }
            : { id: "librarian", label: locale === "en" ? "Librarian" : "Bibliothekar" },
        trade_tier: index % 5, trade_tier_label: (locale === "en" ? ["Novice", "Apprentice", "Journeyman", "Expert", "Master"] : ["Neuling", "Lehrling", "Geselle", "Experte", "Meister"])[index % 5],
        trade_experience: index * 2, health: { current: index % 3 ? 20 : 12, max: 20, editable: true, max_editable: true },
        position: { x: index * 4, y: 64, z: -index * 2 }, dimension: index % 10 ? 0 : 1,
        editable: true, storage: "actor", is_baby: false, issues: [], trade_count: 1, equipment_count: 0,
    }));
}

function villagerInventoryFixture({ editable = true, protectedSlot = false, locale = "de" } = {}) {
    return { capacity: 8, present: true, editable,
        slots: Array.from({ length: 8 }, (_, slot) => ({ slot, editable: editable && !(protectedSlot && slot === 7),
            item: slot === 0 ? { name: "minecraft:bread", count: 3 } : slot === 1 ? { name: "minecraft:carrot", count: 5 }
                : protectedSlot && slot === 7 ? { name: "minecraft:diamond", count: 1 } : null,
            reason: protectedSlot && slot === 7 ? "Geschützter Inhalt bleibt unverändert." : editable ? "" : "Älteres Format: nur lesen.",
        })),
        allowed_items: [
            { name: "minecraft:bread", label: locale === "en" ? "Bread" : "Brot", max_count: 64 },
            { name: "minecraft:carrot", label: locale === "en" ? "Carrot" : "Karotte", max_count: 64 },
            { name: "minecraft:wheat_seeds", label: locale === "en" ? "Wheat Seeds" : "Weizensamen", max_count: 64 },
        ],
    };
}

function villagerEquipmentFixture({ occupied = false, unknownExtra = false } = {}) {
    const slots = [
        ...Array.from({ length: 4 }, (_, index) => ({ container: "Armor", index })),
        { container: "Mainhand", index: 0 }, { container: "Offhand", index: 0 },
        { container: "Armor", index: 4 },
        ...(unknownExtra ? [{ container: "Armor", index: 5 }] : []),
    ].map(({ container, index }) => ({ container, index, slot: `${container}[${index}]`,
        state: occupied && container === "Mainhand" ? "occupied" : unknownExtra && container === "Armor" && index === 5 ? "unknown" : "empty",
        item: occupied && container === "Mainhand" ? { name: "minecraft:bread", count: 1, damage: 0 }
            : unknownExtra && container === "Armor" && index === 5 ? null : { name: "", count: 0, damage: 0 },
    }));
    return { slots, total: slots.length, occupied_count: occupied ? 1 : 0, unknown_count: unknownExtra ? 1 : 0, unknown_containers: [], truncated: false,
        containers: ["Armor", "Mainhand", "Offhand"].map(container => ({ container, present: true,
            total: slots.filter(slot => slot.container === container).length,
            occupied_count: slots.filter(slot => slot.container === container && slot.state === "occupied").length,
            unknown_count: slots.filter(slot => slot.container === container && slot.state === "unknown").length,
            truncated: false,
        })),
    };
}

function orphanVillagerFixture(index) {
    const original = manyVillagers(index + 1)[index];
    const reason = "Der Actor-Datensatz ist keinem lesbaren Chunk-Index zugeordnet.";
    return { ...original, id: `actor:orphan-${index + 1}`, name: `Ohne Chunk ${index + 1}`, dimension: null,
        editable: false, inventory_editable: false,
        health: { ...original.health, editable: false, max_editable: false, reason },
        inventory: { ...villagerInventoryFixture({ editable: false }), reason },
        issues: [{ code: "orphan_actor", message: reason }],
    };
}

async function openVillagerFixture(page, { layout = "classic", readOnly = false, rows: suppliedRows, locale = "de", preferences: suppliedPreferences, withPlayer = false, mapPlayers: suppliedMapPlayers = [], equipment: suppliedEquipment } = {}) {
    const rows = structuredClone(suppliedRows || [
        { id: "actor:a", unique_id: "-9007199254740993", revision: "a".repeat(64), identifier: "minecraft:villager_v2", name: "Bücherwart",
            profession: { id: "librarian", label: "Bibliothekar" }, trade_tier: 4, trade_tier_label: "Meister", trade_experience: 250,
            health: { current: 12, max: 20, editable: true, max_editable: true }, position: { x: 10, y: 64, z: -10 }, dimension: 0,
            editable: true, storage: "actor", is_baby: false, issues: [], trade_count: 1, equipment_count: 0 },
        { id: "actor:b", unique_id: "-9007199254740994", revision: "b".repeat(64), identifier: "minecraft:villager_v2", name: "Rüdiger",
            profession: { id: "farmer", label: "Farmer" }, trade_tier: 2, trade_tier_label: "Geselle", trade_experience: 80,
            health: { current: 20, max: 20, editable: true, max_editable: true }, position: { x: 50, y: 64, z: 50 }, dimension: 0,
            editable: true, storage: "actor", is_baby: false, issues: [], trade_count: 0, equipment_count: 0 },
        { id: "legacy:c", unique_id: "-9007199254740995", revision: "c".repeat(64), identifier: "minecraft:villager", name: "Altbestand",
            profession: { id: "nitwit", label: "Nichtsnutz" }, trade_tier: null, trade_tier_label: "—",
            health: { current: 10, max: 20, editable: false, max_editable: false, reason: "Älteres Format: nur lesen." }, position: { x: 10, y: 64, z: -10 }, dimension: 1,
            editable: false, storage: "legacy", is_baby: false, issues: [], trade_count: 0, equipment_count: 0 },
    ]);
    for (const row of rows) row.name_editable ??= row.storage !== "legacy" && row.editable;
    const inventories = new Map(rows.map(row => [row.id, structuredClone(row.inventory || villagerInventoryFixture({ editable: row.editable, locale }))]));
    const equipment = new Map(rows.map(row => [row.id, structuredClone(row.equipment || suppliedEquipment || { slots: [], total: 0, occupied_count: 0, unknown_count: 0, truncated: false })]));
    const writes = [], previews = [], preferencesWrites = [], scans = [], details = [], playerWrites = [];
    const baseURL = readOnly ? VIEWER_BASE_URL : NORMAL_BASE_URL;
    await page.context().addCookies([{ name: "mcbe_locale", value: locale, url: baseURL }]);
    let preferences = { revision: "prefs-1", aliases: {}, regions: [], ...suppliedPreferences };
    let worldRevision = "world-1";
    let lastPreview = null;
    const signedPreviews = new Map();
    const guard = { server_guard_epoch: 1, server_guard_token: "villager-guard" };
    await page.route("**/api/server_status", route => route.fulfill({ json: { success: true,
        server_status: { status: "offline" }, write_gate: { allowed: !readOnly, read_allowed: true,
            ...(readOnly ? { reason: "Read-Only-Modus", read_only: true } : {}), server_status: { status: "offline" }, ...guard }, ...guard,
    } }));
    for (const [url, json] of Object.entries({
        "**/api/item-db/status": { success: true, item_db: { status: "ready", counts: {} } },
        "**/api/icons/status*": { success: true, icons: {}, count: 0, sources: [], warnings: [] },
        "**/api/icons/scan": { success: true, icons: {}, count: 0 },
        "**/api/heartbeat": { success: true },
        "**/api/backups": { success: true, backups: [] },
    })) await page.route(url, route => route.fulfill({ json }));
    // Most scenarios also cover worlds without any player record.
    const player = { player_key: "villager-test-player", label: "Testspieler", editable: true, exportable: true,
        has_inventory_tag: true, has_ender_chest_tag: true, position: { x: 0, y: 64, z: 0 }, dimension: 0 };
    const mapPlayers = structuredClone([...(withPlayer ? [player] : []), ...suppliedMapPlayers]);
    await page.route("**/api/players", route => route.fulfill({ json: { success: true, world_name: "Villager Test World", players: withPlayer ? [player] : [], ...guard } }));
    if (withPlayer) await page.route("**/api/player/load", route => route.fulfill({ json: {
        success: true, player, player_revision: "player-1", world_fingerprint: worldRevision, ...guard,
        inventory: { 0: { slot: 0, name: "minecraft:stone", count: 2, damage: 0 } }, ender_chest: {}, has_ender_chest: true,
        stats: { pos: [0, 64, 0], dimension_id: 0, health: 20, xp_level: 0, xp_progress: 0, food_level: 20, food_saturation: 5, gamemode: 0 },
        protected_nbt: { has_inventory_tag: true, has_ender_chest_tag: true },
        hidden_unknown_slots: { inventory: 0, ender_chest: 0 },
        items_db: { "minecraft:stone": ["Stein", "Stone"] }, ench_db: {},
        stack_limits: { __default__: 64, "minecraft:stone": 64 }, max_damage: { __default__: 0 },
    } }));
    if (withPlayer) await page.route("**/api/player/save", route => {
        const request = route.request().postDataJSON();
        playerWrites.push(request);
        worldRevision = "world-after-player-save";
        return route.fulfill({ json: { success: true, write_committed: true, player_revision: "player-2",
            saved_items: { inventory: request.inventory, ender_chest: request.ender_chest || {} } } });
    });
    await page.route("**/api/world/presence", route => route.fulfill({ json: { success: true, other_sessions: [], world_fingerprint: worldRevision } }));
    await page.route("**/api/villagers/scan", route => {
        scans.push(route.request().postDataJSON());
        return route.fulfill({ json: { success: true, villagers: rows, map_players: mapPlayers,
            world_revision: worldRevision, preferences, diagnostics: [], summary: { total: rows.length }, ...guard,
        } });
    });
    await page.route("**/api/villagers/detail", route => {
        const request = route.request().postDataJSON();
        details.push(request);
        const row = rows.find(row => row.id === request.id);
        return route.fulfill({ json: { success: true, villager: { ...row,
            inventory: inventories.get(row.id),
            trades: { total: 1, offers: [{ buy_a: { name: "minecraft:emerald", count: 12 }, sell: { name: "minecraft:book", count: 1 }, uses: 0, max_uses: 12 }] },
            equipment: equipment.get(row.id),
            nbt: { type: "CompoundTag", value: { UniqueID: { type: "LongTag", value: row.unique_id },
                CustomName: { type: "StringTag", value: "<img src=x onerror=alert(1)>" } } },
        } } });
    });
    await page.route("**/api/villagers/preview", route => {
        const request = route.request().postDataJSON();
        previews.push(request);
        const previewRows = request.selection.map(selected => {
            const row = rows.find(row => row.id === selected.id);
            if (Object.hasOwn(request.changes, "name")) {
                return { id: row.id, name: row.name, kind: "name", before: { name: row.name }, after: { name: request.changes.name },
                    status: !row.name_editable ? "skipped" : row.name === request.changes.name ? "unchanged" : "changed" };
            }
            if (request.changes.inventory) {
                const inventory = inventories.get(row.id);
                const before = { slots: request.changes.inventory.map(change => ({ slot: change.slot, item: inventory.slots.find(slot => slot.slot === change.slot).item })) };
                const after = { slots: request.changes.inventory };
                return { id: row.id, name: row.name, kind: "inventory", before, after,
                    status: !inventory.editable ? "skipped" : JSON.stringify(before) === JSON.stringify(after) ? "unchanged" : "changed" };
            }
            const max = request.changes.max_health ?? row.health.max;
            const after = row.editable ? { current: request.changes.heal ? max : request.changes.current_health ?? Math.min(row.health.current, max), max } : row.health;
            return { id: row.id, name: row.name, status: !row.editable ? "skipped" : after.current === row.health.current && after.max === row.health.max ? "unchanged" : "changed", before: row.health,
                after,
                reason: row.editable ? "" : "Älteres Format: nur lesen." };
        });
        lastPreview = { success: true, rows: previewRows, preview_token: previewRows.some(row => row.status === "changed") ? `signed-preview-${previews.length}` : null,
            change_count: previewRows.filter(row => row.status === "changed").length,
            skipped_count: previewRows.filter(row => row.status === "skipped").length, unchanged_count: previewRows.filter(row => row.status === "unchanged").length };
        signedPreviews.set(lastPreview.preview_token, request);
        return route.fulfill({ json: lastPreview });
    });
    await page.route("**/api/workspace/save", route => {
        const payload = route.request().postDataJSON();
        writes.push(payload);
        if (payload.inventory) playerWrites.push(payload);
        for (const token of payload.villager_previews) {
        const request = signedPreviews.get(token);
        for (const selected of request.selection) {
            const row = rows.find(row => row.id === selected.id);
            if (!row.editable) continue;
            if (request.changes.inventory) {
                const inventory = inventories.get(row.id);
                for (const change of request.changes.inventory) {
                    const slot = inventory.slots.find(slot => slot.slot === change.slot);
                    if (inventory.editable && slot.editable) slot.item = structuredClone(change.item);
                }
            } else if (Object.hasOwn(request.changes, "name")) {
                if (row.name_editable) row.name = request.changes.name;
            } else {
                row.health.max = request.changes.max_health ?? row.health.max;
                row.health.current = request.changes.heal ? row.health.max : request.changes.current_health ?? Math.min(row.health.current, row.health.max);
            }
            row.revision = "d".repeat(64);
        }
        }
        worldRevision = "world-2";
        return route.fulfill({ json: { success: true, write_committed: true, changed_count: lastPreview.change_count, backup_file: "world-before-villagers.zip", validation: { ok: true }, player_revision: "player-2", saved_items: { inventory: payload.inventory || {}, ender_chest: {} } } });
    });
    await page.route("**/api/villagers/preferences", route => {
        const request = route.request().postDataJSON();
        preferencesWrites.push(request);
        preferences = { aliases: request.aliases, regions: request.regions, revision: `prefs-${preferencesWrites.length + 1}` };
        return route.fulfill({ json: { success: true, preferences } });
    });
    await openAppWithSmokeWorldScan(page, baseURL);
    await page.locator(".world-card").click();
    await page.locator("#btnLoad").click();
    await expect(page.locator("#loadingOverlay")).toBeHidden();
    await selectLayout(page, layout);
    await page.locator('.app-workflow-nav [data-workflow-view="villagers"]').click();
    await expect(page.locator("#villagerResults")).toBeVisible();
    await expect(page.locator("#villagerRows .villager-name")).toHaveCount(Math.min(rows.length, 50));
    return { rows, writes, previews, preferencesWrites, scans, details, playerWrites, mapPlayers, inventories, equipment };
}

async function saveVillagers(page, { returnToVillagers = true } = {}) {
    await page.locator("#villagerSave").click();
    await expect(page.locator("#villagerPreviewDialog")).toBeHidden();
    await page.locator("#villagerReviewPending").click();
    await expect(page.locator("#saveWorkflowPanel")).toBeVisible();
    await page.locator("#btnSaveWorkflowRun").click();
    await expect.poll(() => page.evaluate(() => getSaveAppController().isSaving())).toBe(false);
    if (returnToVillagers) await page.locator('.app-workflow-nav [data-workflow-view="villagers"]').click();
}

test("world-only villagers: filter, select all, inspect skipped rows, save and reload", async ({ page }) => {
    const errors = collectBrowserErrors(page);
    const h = await openVillagerFixture(page);
    await expect(page.locator('#villagerRows tr')).toHaveCount(3);
    await page.locator("#villagerOnlyInjured").check();
    await expect(page.locator('#villagerRows tr')).toHaveCount(2);
    await page.locator("#villagerResetFilters").click();
    await page.locator("#villagerSelectFiltered").click();
    await page.locator("#villagerBatchMax").fill("40");
    await page.locator("#villagerBatchHeal").check();
    await page.locator("#villagerBatchPreview").click();
    await expect(page.locator("#villagerPreviewDialog")).toBeVisible();
    await expect(page.locator("#villagerPreviewSummary")).toContainText("2 Änderungen");
    await expect(page.locator("#villagerPreviewSummary")).toContainText("1 übersprungen");
    expect(h.previews[0].changes).toEqual({ max_health: 40, heal: true });
    expect(h.previews[0].selection).toHaveLength(3);
    await test.step("the mobile preview has an opaque surface, readable header and reachable actions", async () => {
        await page.setViewportSize({ width: 320, height: 844 });
        await page.locator("#villagerPreviewTitle").scrollIntoViewIfNeeded();
        const header = await page.locator("#villagerPreviewDialog").evaluate(dialog => {
            const bounds = dialog.getBoundingClientRect();
            const title = dialog.querySelector("#villagerPreviewTitle");
            const close = dialog.querySelector("#villagerPreviewClose");
            const background = getComputedStyle(dialog).backgroundColor;
            const alpha = background.startsWith("rgb(") ? 1 : Number(background.match(/^rgba\(.+,\s*([\d.]+)\)$/)?.[1] ?? 0);
            return { alpha, titleFits: title.scrollWidth <= title.clientWidth + 1,
                headerWithinDialog: [title, close].every(element => {
                    const rect = element.getBoundingClientRect();
                    return rect.left >= bounds.left && rect.right <= bounds.right + 1
                        && rect.top >= bounds.top && rect.bottom <= bounds.bottom + 1;
                }), dialogWithinViewport: bounds.left >= 0 && bounds.right <= window.innerWidth + 1 };
        });
        expect(header).toEqual({ alpha: 1, titleFits: true, headerWithinDialog: true, dialogWithinViewport: true });
        const afterColumn = page.locator(".villager-preview-table-scroll th").nth(2);
        await expect(afterColumn).toHaveText("Nachher");
        await expect(afterColumn).toBeVisible();
        await afterColumn.scrollIntoViewIfNeeded();
        expect(await afterColumn.evaluate(column => {
            const columnBounds = column.getBoundingClientRect();
            const viewport = column.closest(".villager-preview-table-scroll").getBoundingClientRect();
            return columnBounds.left >= viewport.left && columnBounds.right <= viewport.right + 1;
        })).toBe(true);
        await expect(page.locator("#villagerPreviewRows tr").first().locator("td").nth(2)).toBeVisible();
        await page.locator("#villagerPreviewCancel").focus();
        await page.keyboard.press("Tab");
        await expect(page.locator("#villagerSave")).toBeFocused();
        await page.locator(".villager-preview-table-scroll").focus();
        await page.keyboard.press("Shift+Tab");
        await expect(page.locator("#villagerPreviewClose")).toBeFocused();
    });
    await saveVillagers(page);
    await expect(page.locator("#villagerPreviewDialog")).toBeHidden();
    await expect(page.locator("#villagerStatus")).toContainText("world-before-villagers.zip");
    await expect(page.locator('#villagerRows tr').filter({ hasText: "Bücherwart" })).toContainText("40 / 40");
    expect(h.writes).toHaveLength(1);
    expect(h.writes[0].villager_previews).toEqual(["signed-preview-1"]);
    expect(h.writes[0].server_guard_token).toBe("villager-guard");
    expect(errors).toEqual([]);
});

async function openVillagerStock(page, id = "actor:a") {
    await page.locator(`#villagerRows .villager-name[data-id="${id}"]`).click();
    await page.locator("#villagerInventoryDetails > summary").click();
    await expect(page.locator("#villagerInventoryForm")).toBeVisible();
}

test("villager equipment shows seven stored empty slots as zero occupied in separate armor and hand groups", async ({ page }) => {
    const h = await openVillagerFixture(page, { equipment: villagerEquipmentFixture() });
    await page.locator('#villagerRows .villager-name[data-id="actor:a"]').click();
    const equipment = page.locator("#villagerEquipmentDetails");
    await expect(equipment.locator("summary")).toHaveText("Ausrüstung (0 belegt)");
    await equipment.locator("summary").click();
    await expect(equipment.locator('[data-equipment-group="Armor"] h4')).toHaveText("Rüstung (Armor)");
    await expect(equipment.getByRole("heading", { name: "Haupt- und Nebenhand" })).toBeVisible();
    await expect(equipment.locator('[data-equipment-group="Mainhand"] dt')).toHaveText("Haupthand");
    await expect(equipment.locator('[data-equipment-group="Offhand"] dt')).toHaveText("Nebenhand");
    await expect(equipment.locator("dd")).toHaveCount(7);
    for (const slot of await equipment.locator("dd").all()) await expect(slot).toHaveText("Leer");
    await expect(equipment.locator("form, input, select, textarea, [contenteditable='true']")).toHaveCount(0);
    expect(h.equipment.get("actor:a").total).toBe(7);
    expect(h.previews).toHaveLength(0);
    expect(h.writes).toHaveLength(0);
});

test("villager equipment counts the occupied hand and preserves an unknown extra armor slot", async ({ page }) => {
    const h = await openVillagerFixture(page, { equipment: villagerEquipmentFixture({ occupied: true, unknownExtra: true }) });
    await page.locator('#villagerRows .villager-name[data-id="actor:a"]').click();
    const equipment = page.locator("#villagerEquipmentDetails");
    await expect(equipment.locator("summary")).toHaveText("Ausrüstung (1 belegt, weitere unklar)");
    await equipment.locator("summary").click();
    await expect(equipment.locator('[data-equipment-group="Mainhand"] dd')).toContainText("minecraft:bread");
    await expect(equipment.locator('[data-equipment-group="Mainhand"] dd')).toContainText("1");
    const armor = equipment.locator('[data-equipment-group="Armor"]');
    await expect(armor.locator("dt")).toHaveCount(6);
    await expect(armor.locator("dd")).toHaveCount(6);
    await expect(armor.locator("dt").nth(4)).toHaveText("Zusatzslot (Body)");
    await expect(armor.locator("dt").last()).toHaveText("Zusätzlicher Rüstungsplatz 6");
    await expect(armor.locator("dd").last()).not.toHaveText("Leer");
    await expect(armor.locator("dd").last()).toContainText(/unbekannt|unlesbar|nicht.*lesbar/i);
    await expect(equipment.locator('[data-equipment-group="Offhand"] dd')).toHaveText("Leer");
    await expect(equipment.locator("form, input, select, textarea, [contenteditable='true']")).toHaveCount(0);
    expect(h.equipment.get("actor:a").slots).toHaveLength(8);
    expect(h.writes).toHaveLength(0);
});

test("villager equipment and orphan notices explain all four missing chunk assignments without weakening write protection", async ({ page }) => {
    const healthy = { ...manyVillagers(1)[0], id: "actor:healthy", name: "Gesunder Bewohner", dimension: 0, inventory_editable: true };
    const rows = [healthy, ...Array.from({ length: 4 }, (_, index) => orphanVillagerFixture(index))];
    const h = await openVillagerFixture(page, { rows, equipment: villagerEquipmentFixture() });
    await expect(page.locator("#villagerRows .villager-orphan-badge")).toHaveCount(4);
    for (const badge of await page.locator("#villagerRows .villager-orphan-badge").all()) await expect(badge).toHaveText("Chunk-Zuordnung fehlt");
    await expect(page.locator('#villagerRows tr[data-villager-id="actor:healthy"] .villager-orphan-badge')).toHaveCount(0);
    await page.locator('#villagerRows .villager-name[data-id="actor:orphan-1"]').click();
    const notice = page.locator("#villagerIntegrityNotice");
    await expect(notice).toBeVisible();
    await expect(notice).toContainText("Chunk-Zuordnung fehlt");
    expect(await notice.evaluate(element => Boolean(element.compareDocumentPosition(document.getElementById("villagerDetailHealthForm")) & Node.DOCUMENT_POSITION_FOLLOWING))).toBe(true);
    await expect(page.locator("#villagerDetailCurrent")).toBeDisabled();
    await expect(page.locator("#villagerDetailMax")).toBeDisabled();
    await expect(page.locator("#villagerDetailPreview")).toBeDisabled();
    await page.locator("#villagerInventoryDetails > summary").click();
    await expect(page.locator("#villagerInventoryFields")).toHaveJSProperty("disabled", true);
    await expect(page.locator("#villagerStockItem0, #villagerInventoryPreview")).toHaveCount(0);
    await page.locator("#villagerDetailTitle").press("Control+s");
    expect(h.previews).toHaveLength(0);
    await page.locator('#villagerRows .villager-name[data-id="actor:healthy"]').click();
    await expect(notice).toBeHidden();
    await expect(page.locator("#villagerDetailCurrent")).toBeEnabled();
    await page.locator("#villagerDetailCurrent").fill("18");
    await page.locator("#villagerDetailPreview").click();
    await expect(page.locator("#villagerPreviewDialog")).toBeVisible();
    expect(h.previews[0].selection.map(row => row.id)).toEqual(["actor:healthy"]);
    expect(h.previews[0].changes).toEqual({ current_health: 18 });
    expect(h.writes).toHaveLength(0);
});

for (const [layout, width, locale] of [["classic", 1440, "de"], ["studio", 768, "en"], ["focus", 320, "de"]]) {
    test(`villager equipment and orphan warnings fit ${layout} at ${width}px in ${locale}`, async ({ page }, testInfo) => {
        await page.setViewportSize({ width: 1440, height: 1050 });
        const h = await openVillagerFixture(page, { layout, locale, rows: [orphanVillagerFixture(0)],
            equipment: villagerEquipmentFixture({ occupied: true, unknownExtra: true }) });
        await page.setViewportSize({ width, height: 1024 });
        await page.locator('#villagerRows .villager-name[data-id="actor:orphan-1"]').click();
        await expect(page.locator("#villagerIntegrityNotice")).toBeVisible();
        await page.locator("#villagerEquipmentDetails > summary").click();
        await expect(page.locator("#villagerEquipmentDetails > summary")).toContainText(locale === "en" ? "1 occupied" : "1 belegt");
        const groups = page.locator("[data-equipment-group]");
        await expect(groups).toHaveCount(3);
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
        for (const group of await groups.all()) {
            const sizes = await group.evaluate(element => ({ width: element.clientWidth, scroll: element.scrollWidth }));
            expect(sizes.scroll).toBeLessThanOrEqual(sizes.width + 1);
        }
        await page.locator("#villagerEquipmentDetails").scrollIntoViewIfNeeded();
        const directory = process.env.MCBE_MAP_QA_DIR;
        if (directory) await fs.mkdir(directory, { recursive: true });
        await page.locator("#villagerEquipmentDetails").screenshot({ path: directory ? path.join(directory, `villager-equipment-${layout}-${width}.png`) : testInfo.outputPath(`villager-equipment-${layout}-${width}.png`) });
        await page.locator("#villagerIntegrityNotice").scrollIntoViewIfNeeded();
        await page.locator("#villagerDetail").screenshot({ path: directory ? path.join(directory, `villager-orphan-${layout}-${width}.png`) : testInfo.outputPath(`villager-orphan-${layout}-${width}.png`) });
        expect(h.writes).toHaveLength(0);
    });
}

test("villager stock saves only edited slots and preserves separate health and alias drafts in both directions", async ({ page }) => {
    const errors = collectBrowserErrors(page);
    const h = await openVillagerFixture(page);
    await openVillagerStock(page);
    await page.locator("#villagerDetailCurrent").fill("18");
    await page.locator("#villagerAliasDetails > summary").click();
    await page.locator("#villagerAlias").fill("Noch offen");
    await page.locator("#villagerStockCount0").fill("9");
    await page.locator("#villagerStockItem1").selectOption("");
    await expect(page.locator("#villagerStockCount1")).toBeDisabled();
    await page.locator("#villagerStockItem2").selectOption("minecraft:wheat_seeds");
    await expect(page.locator("#villagerStockCount2")).toHaveValue("1");
    await page.locator("#villagerStockCount2").fill("64");
    await page.locator("#villagerStockCount2").press("Control+s");
    await expect(page.locator("#villagerPreviewDialog")).toBeVisible();
    expect(h.previews[0].changes).toEqual({ inventory: [
        { slot: 0, item: { name: "minecraft:bread", count: 9 } }, { slot: 1, item: null },
        { slot: 2, item: { name: "minecraft:wheat_seeds", count: 64 } },
    ] });
    expect(h.previews[0].selection.map(row => row.id)).toEqual(["actor:a"]);
    await expect(page.locator("#villagerPreviewRows")).toContainText("Vorräte");
    await expect(page.locator("#villagerPreviewRows td").nth(1)).toContainText("3 × Brot");
    await expect(page.locator("#villagerPreviewRows td").nth(2)).toContainText("64 × Weizensamen");
    await saveVillagers(page);
    await expect(page.locator("#villagerPreviewDialog")).toBeHidden();
    await expect(page.locator("#villagerInventoryDirty")).toBeHidden();
    await expect(page.locator("#villagerStockCount0")).toHaveValue("9");
    await expect(page.locator("#villagerStockItem1")).toHaveValue("");
    await expect(page.locator("#villagerStockCount2")).toHaveValue("64");
    await expect(page.locator("#villagerDetailCurrent")).toHaveValue("18");
    await expect(page.locator("#villagerDetailDirty")).toBeVisible();
    await expect(page.locator("#villagerAlias")).toHaveValue("Noch offen");
    expect(h.rows[0].health.current).toBe(12);
    expect(h.inventories.get("actor:a").slots[0].item.count).toBe(9);
    await page.locator("#villagerStockCount0").fill("10");
    await page.locator("#villagerDetailCurrent").press("Control+s");
    await expect(page.locator("#villagerPreviewDialog")).toBeVisible();
    expect(h.previews[1].changes).toEqual({ current_health: 18 });
    await saveVillagers(page);
    await expect(page.locator("#villagerPreviewDialog")).toBeHidden();
    await expect(page.locator("#villagerDetailDirty")).toBeHidden();
    await expect(page.locator("#villagerStockCount0")).toHaveValue("10");
    await expect(page.locator("#villagerInventoryDirty")).toBeVisible();
    await expect(page.locator("#villagerAlias")).toHaveValue("Noch offen");
    expect(h.rows[0].health.current).toBe(18);
    expect(h.inventories.get("actor:a").slots[0].item.count).toBe(9);
    expect(h.writes).toHaveLength(2);
    expect(h.preferencesWrites).toHaveLength(0);
    expect(errors).toEqual([]);
});

test("villager stock rejects invalid quantities and keeps protected slots outside the editable form", async ({ page }) => {
    const rows = manyVillagers(1).map(row => ({ ...row, inventory: villagerInventoryFixture({ protectedSlot: true }) }));
    const h = await openVillagerFixture(page, { rows });
    await openVillagerStock(page, rows[0].id);
    await expect(page.locator("#villagerStockItem7, #villagerStockCount7")).toHaveCount(0);
    await expect(page.locator(".villager-stock-protected")).toContainText("minecraft:diamond");
    await expect(page.locator(".villager-stock-protected")).toContainText("Geschützter Inhalt");
    const count = page.locator("#villagerStockCount0");
    for (const invalid of ["0", "65", "1.5", ""]) {
        await count.fill(invalid);
        await count.press("Control+s");
        await expect(page.locator("#villagerStatus")).toContainText("ganze Anzahl zwischen 1 und 64");
        await expect(page.locator("#villagerPreviewDialog")).toBeHidden();
        expect(h.previews).toHaveLength(0);
    }
    await count.fill("");
    await count.press("-");
    expect(await count.evaluate(input => input.validity.badInput)).toBe(true);
    await count.press("Control+s");
    expect(h.previews).toHaveLength(0);
    await page.locator("#villagerInventoryReset").click();
    await expect(count).toHaveValue("3");
    await expect(page.locator("#villagerInventoryDirty")).toBeHidden();
    await page.locator("#villagerStockItem2").selectOption("minecraft:carrot");
    await page.locator("#villagerStockItem2").selectOption("");
    await expect(page.locator("#villagerStockCount2")).toBeDisabled();
    await expect(page.locator("#villagerInventoryDirty")).toBeHidden();
    await count.fill("4");
    await page.locator("#villagerInventoryPreview").click();
    await expect(page.locator("#villagerPreviewDialog")).toBeVisible();
    expect(h.previews[0].changes.inventory).toEqual([{ slot: 0, item: { name: "minecraft:bread", count: 4 } }]);
    expect(h.writes).toHaveLength(0);
});

test("villager stock draft survives a health save when its refreshed slot becomes protected", async ({ page }) => {
    const h = await openVillagerFixture(page);
    await openVillagerStock(page);
    await page.locator("#villagerStockCount0").fill("9");
    await page.locator("#villagerDetailCurrent").fill("18");
    await page.route("**/api/workspace/save", async route => {
        const slot = h.inventories.get("actor:a").slots[0];
        slot.editable = false;
        slot.reason = "Geschützter Inhalt bleibt unverändert.";
        await route.fallback();
    });
    await page.locator("#villagerDetailPreview").click();
    await expect(page.locator("#villagerPreviewDialog")).toBeVisible();
    await saveVillagers(page);
    await expect(page.locator("#villagerPreviewDialog")).toBeHidden();
    await expect(page.locator("#villagerStale")).toBeVisible();
    await expect(page.locator("#villagerStockCount0")).toHaveValue("9");
    await expect(page.locator("#villagerStockCount0")).toBeDisabled();
    await expect(page.locator("#villagerInventoryDirty")).toBeVisible();
    await expect(page.locator("#villagerInventoryPreview")).toBeDisabled();
    expect(h.writes).toHaveLength(1);
    expect(h.rows[0].health.current).toBe(18);
    expect(h.inventories.get("actor:a").slots[0].item.count).toBe(3);
});

test("villager stock drafts require discard before closing or changing the inspected resident", async ({ page }) => {
    const h = await openVillagerFixture(page);
    await openVillagerStock(page);
    await page.locator("#villagerStockCount0").fill("9");
    await page.locator('#villagerRows .villager-name[data-id="actor:b"]').click();
    await expect(page.locator("#confirmOverlay")).toBeVisible();
    await page.locator("#confirmCancel").click();
    await expect(page.locator("#villagerDetailTitle")).toHaveText("Bücherwart");
    await expect(page.locator("#villagerStockCount0")).toHaveValue("9");
    await page.locator('#villagerDetail [data-action="close-detail"]').click();
    await page.locator("#confirmCancel").click();
    await expect(page.locator("#villagerInventoryDirty")).toBeVisible();
    await page.locator('#villagerRows .villager-name[data-id="actor:b"]').click();
    await page.locator("#confirmOk").click();
    await expect(page.locator("#villagerDetailTitle")).toHaveText("Rüdiger");
    await openVillagerStock(page);
    await expect(page.locator("#villagerStockCount0")).toHaveValue("3");
    await page.locator("#villagerStockCount0").fill("8");
    await page.locator('#villagerDetail [data-action="close-detail"]').click();
    await page.locator("#confirmOk").click();
    await expect(page.locator("#villagerDetail")).toBeHidden();
    expect(h.writes).toHaveLength(0);
});

test("leaving a delayed villager stock preview cancels it while keeping the draft", async ({ page }) => {
    const h = await openVillagerFixture(page);
    let release, started, completed, readId;
    const held = new Promise(resolve => { release = resolve; });
    const begun = new Promise(resolve => { started = resolve; });
    const finished = new Promise(resolve => { completed = resolve; });
    const cancellations = [];
    await page.route("**/api/world_reads/*", route => {
        if (route.request().method() !== "DELETE" || !route.request().url().endsWith(readId)) return route.fallback();
        cancellations.push(readId);
        return route.fulfill({ json: { success: true, read_id: readId, cancelled: true } });
    });
    await page.route("**/api/villagers/preview", async route => {
        readId = route.request().headers()["x-mcbe-read-id"];
        started();
        await held;
        try { await route.fulfill({ json: { success: true, rows: [], change_count: 1, preview_token: "obsolete-stock-preview" } }); }
        finally { completed(); }
    });
    try {
        await openVillagerStock(page);
        await page.locator("#villagerStockCount0").fill("9");
        await page.locator("#villagerInventoryPreview").click();
        await begun;
        await page.locator('.app-workflow-nav [data-workflow-view="world"]').click();
        await page.locator('.app-workflow-nav [data-workflow-view="villagers"]').click();
        await expect.poll(() => cancellations).toEqual([readId]);
        release();
        await finished;
        await expect(page.locator("#villagerPreviewDialog")).toBeHidden();
        await expect(page.locator("#villagerStockCount0")).toHaveValue("9");
        await expect(page.locator("#villagerInventoryDirty")).toBeVisible();
        await expect(page.locator("#villagerInventoryPreview")).toBeEnabled();
        expect(h.writes).toHaveLength(0);
    } finally { release(); }
});

for (const readOnly of [true, false]) {
    test(`villager stock remains protected when ${readOnly ? "the viewer is read-only" : "the scan becomes stale"}`, async ({ page }) => {
        const h = await openVillagerFixture(page, { readOnly });
        await openVillagerStock(page);
        if (!readOnly) {
            await page.locator("#villagerStockCount0").fill("9");
            await page.evaluate(() => renderServerStatus({ write_gate: { allowed: false, server_status: { status: "online" },
                server_guard_token: "stock-new-server-state", server_guard_epoch: 2 }, server_guard_token: "stock-new-server-state", server_guard_epoch: 2 }));
            await expect(page.locator("#villagerStockCount0")).toHaveValue("9");
            await expect(page.locator("#villagerInventoryDirty")).toBeVisible();
        }
        await expect(page.locator("#villagerInventoryFields")).toHaveJSProperty("disabled", true);
        await expect(page.locator("#villagerStockItem0")).toBeDisabled();
        await expect(page.locator("#villagerStockCount0")).toBeDisabled();
        await expect(page.locator("#villagerInventoryPreview")).toBeDisabled();
        await page.locator("#villagerDetailTitle").press("Control+s");
        expect(h.previews).toHaveLength(0);
        expect(h.writes).toHaveLength(0);
    });
}

for (const [layout, width, locale] of [["classic", 1440, "de"], ["studio", 768, "en"], ["focus", 320, "de"]]) {
    test(`villager stock editor fits ${layout} at ${width}px in ${locale}`, async ({ page }, testInfo) => {
        await page.setViewportSize({ width: 1440, height: 1050 });
        const h = await openVillagerFixture(page, { layout, locale });
        await page.setViewportSize({ width, height: 1024 });
        await openVillagerStock(page);
        await expect(page.locator("#villagerInventoryDetails > summary")).toContainText(locale === "en" ? "Supplies" : "Vorräte");
        await page.locator("#villagerStockCount0").fill("4");
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
        const rows = await page.locator(".villager-stock-row").evaluateAll(elements => elements.map(element => ({
            width: element.clientWidth, scroll: element.scrollWidth,
            bounds: Array.from(element.querySelectorAll("input,select")).map(control => {
                const rect = control.getBoundingClientRect(); return { left: rect.left, right: rect.right };
            }),
        })));
        for (const row of rows) {
            expect(row.scroll).toBeLessThanOrEqual(row.width + 1);
            for (const bounds of row.bounds) { expect(bounds.left).toBeGreaterThanOrEqual(0); expect(bounds.right).toBeLessThanOrEqual(width + 1); }
        }
        await page.locator("#villagerInventoryDetails").scrollIntoViewIfNeeded();
        const directory = process.env.MCBE_MAP_QA_DIR;
        if (directory) await fs.mkdir(directory, { recursive: true });
        await page.locator("#villagerInventoryDetails").screenshot({ path: directory ? path.join(directory, `villager-stock-${layout}-${width}.png`) : testInfo.outputPath(`villager-stock-${layout}-${width}.png`) });
        await page.locator("#villagerInventoryPreview").click();
        await expect(page.locator("#villagerPreviewDialog")).toBeVisible();
        await expect(page.locator("#villagerPreviewRows")).toContainText(locale === "en" ? "4 × Bread" : "4 × Brot");
        await page.locator("#villagerPreviewCancel").click();
        await expect(page.locator("#villagerInventoryDirty")).toBeVisible();
        expect(h.writes).toHaveLength(0);
    });
}

for (const layout of ["classic", "studio", "focus"]) {
    test(`villager details, aliases, regions and map are usable in ${layout}`, async ({ page }) => {
        await page.setViewportSize({ width: 1440, height: 1050 });
        const errors = collectBrowserErrors(page);
        const h = await openVillagerFixture(page, { layout });
        await page.locator('.villager-name[data-id="actor:a"]').click();
        await expect(page.locator("#villagerDetail")).toBeVisible();
        await expect(page.locator("#villagerDetailMax")).toBeVisible();
        await expect(page.locator("#villagerTechnicalDetails")).toHaveJSProperty("open", false);
        await page.locator("#villagerDetail summary").filter({ hasText: "Handelsangebote" }).click();
        await expect(page.locator(".villager-trades")).toContainText("minecraft:emerald");
        await page.locator("#villagerTechnicalDetails > summary").click();
        await expect(page.locator("#villagerTechnicalDetails")).toContainText("-9007199254740993");
        await page.locator("#villagerDetail summary").filter({ hasText: "Rohdaten" }).click();
        await expect(page.locator(".villager-nbt")).toContainText("<img src=x onerror=alert(1)>");
        await expect(page.locator(".villager-nbt img")).toHaveCount(0);
        await page.locator("#villagerAliasDetails > summary").click();
        await page.locator("#villagerAlias").fill("Handelsmeister");
        await page.locator("#villagerAliasSave").click();
        await expect(page.locator("#villagerDetailTitle")).toHaveText("Bücherwart");
        await expect(page.locator('tr[data-villager-id="actor:a"]')).toContainText("Editor-Alias: Handelsmeister");
        await page.locator("#villagerRegionsToggle").click();
        await expect(page.locator("#villagerRegionsToggle")).toHaveAttribute("aria-expanded", "true");
        await page.locator("#villagerRegionName").fill("Hauptdorf");
        for (const [field, value] of Object.entries({ MinX: "-20", MaxX: "20", MinZ: "-20", MaxZ: "20" })) {
            await page.locator(`#villagerRegion${field}`).fill(value);
        }
        await page.locator("#villagerRegionSave").click();
        await expect(page.locator("#villagerRegionList")).toContainText("Hauptdorf");
        await expect(page.locator("#villagerRegionList")).toContainText("1 Bewohner");
        await page.locator("#villagerRegion").selectOption({ label: "Hauptdorf" });
        await expect(page.locator("#villagerRows tr")).toHaveCount(1);
        await page.locator("#villagerMapToggle").click();
        await expect(page.locator("#villagerMapToggle")).toHaveAttribute("aria-expanded", "true");
        await expect(page.locator(".villager-map-point")).toHaveCount(1);
        await page.locator(".villager-map-point").click();
        await expect(page.locator("#villagerDetailTitle")).toBeFocused();
        expect(h.preferencesWrites).toHaveLength(2);
        expect(h.writes).toHaveLength(0);
        expect(errors).toEqual([]);
    });
}

for (const [layout, width] of [["classic", 320], ["focus", 390], ["studio", 768]]) {
    test(`villager list and inspector remain readable without page overflow in ${layout} at ${width}px`, async ({ page }) => {
        await page.setViewportSize({ width: 1440, height: 1050 });
        await openVillagerFixture(page, { layout });
        await page.setViewportSize({ width, height: 844 });
        const row = page.locator('#villagerRows tr[data-villager-id="actor:a"]');
        await row.scrollIntoViewIfNeeded();
        const visibleText = await row.innerText();
        expect(visibleText).toContain("Bibliothekar");
        expect(visibleText).toContain("Meister");
        expect(visibleText).toMatch(/10\s*\/\s*64\s*\/\s*-10/);
        expect(visibleText).toMatch(/12\s*\/\s*20/);
        const sizing = await page.locator(".villager-table-scroll").evaluate(element => ({
            pageWidth: document.documentElement.scrollWidth, viewportWidth: window.innerWidth,
            tableWidth: element.scrollWidth, viewport: element.clientWidth,
        }));
        expect(sizing.pageWidth).toBeLessThanOrEqual(sizing.viewportWidth + 1);
        if (width <= 640) expect(sizing.tableWidth).toBeLessThanOrEqual(sizing.viewport + 1);
        await row.locator(".villager-name").click();
        await expect(page.locator("#villagerDetailTitle")).toHaveText("Bücherwart");
        await expect(page.locator("#villagerDetailMax")).toBeVisible();
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
    });
}

function mapVillagers() {
    return manyVillagers(5).map((row, index) => ({ ...row, dimension: 0,
        position: { x: [-80, -20, 0, 20, 80][index], y: 64, z: [-80, -20, 0, 20, 80][index] } }));
}

async function mapPointCenter(locator) {
    const bounds = await locator.boundingBox();
    expect(bounds).not.toBeNull();
    return { x: bounds.x + bounds.width / 2, y: bounds.y + bounds.height / 2 };
}

async function mapScreenshot(page, testInfo, filename) {
    const directory = process.env.MCBE_MAP_QA_DIR;
    if (directory) await fs.mkdir(directory, { recursive: true });
    await page.locator("#villagerMapPanel").screenshot({
        path: directory ? path.join(directory, filename) : testInfo.outputPath(filename),
    });
}

test("villager map mouse zoom anchors the pointed location and dragging does not open a resident", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1050 });
    const errors = collectBrowserErrors(page);
    const h = await openVillagerFixture(page, { rows: mapVillagers() });
    await page.locator("#villagerMapToggle").click();
    const map = page.locator("#villagerMap");
    await map.scrollIntoViewIfNeeded();
    const anchor = map.locator('[data-id="actor:resident-2"]');
    const center = map.locator('[data-id="actor:resident-3"]');
    const originalAnchor = await mapPointCenter(anchor);
    const originalCenter = await mapPointCenter(center);
    const scrollBefore = await page.evaluate(() => window.scrollY);
    await page.mouse.move(originalAnchor.x, originalAnchor.y);
    await page.mouse.wheel(0, -240);
    await expect.poll(async () => (await mapPointCenter(center)).x - (await mapPointCenter(anchor)).x)
        .toBeGreaterThan((originalCenter.x - originalAnchor.x) * 1.15);
    const anchored = await mapPointCenter(anchor);
    expect(Math.abs(anchored.x - originalAnchor.x)).toBeLessThan(1.5);
    expect(Math.abs(anchored.y - originalAnchor.y)).toBeLessThan(1.5);
    expect(await page.evaluate(() => window.scrollY)).toBe(scrollBefore);

    await page.locator("#villagerMapFit").click();
    const beforeDrag = await mapPointCenter(center);
    await page.mouse.move(beforeDrag.x, beforeDrag.y);
    await page.mouse.down();
    await page.mouse.move(beforeDrag.x + 36, beforeDrag.y + 24, { steps: 6 });
    await page.mouse.up();
    const afterDrag = await mapPointCenter(center);
    expect(afterDrag.x - beforeDrag.x).toBeCloseTo(36, 0);
    expect(afterDrag.y - beforeDrag.y).toBeCloseTo(24, 0);
    expect(h.details).toHaveLength(0);
    await expect(page.locator("#villagerDetail")).toBeHidden();
    await center.click();
    await expect(page.locator("#villagerDetailTitle")).toHaveText("Bewohner 003");
    expect(h.details).toHaveLength(1);
    expect(h.writes).toHaveLength(0);
    expect(errors).toEqual([]);
});

test("villager map buttons and keyboard zoom, pan and restore the whole view", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1050 });
    await openVillagerFixture(page, { rows: mapVillagers() });
    await page.locator("#villagerMapToggle").click();
    const map = page.locator("#villagerMap");
    await map.scrollIntoViewIfNeeded();
    const left = map.locator('[data-id="actor:resident-2"]');
    const center = map.locator('[data-id="actor:resident-3"]');
    const originalCenter = await mapPointCenter(center);
    const distance = async () => (await mapPointCenter(center)).x - (await mapPointCenter(left)).x;
    const originalDistance = await distance();
    await page.locator("#villagerMapZoomIn").click();
    expect(await distance()).toBeGreaterThan(originalDistance * 1.1);
    await page.locator("#villagerMapZoomOut").click();
    expect(await distance()).toBeCloseTo(originalDistance, 0);
    await map.focus();
    await expect(map).toBeFocused();
    await page.keyboard.press("+");
    expect(await distance()).toBeGreaterThan(originalDistance * 1.1);
    await page.keyboard.press("ArrowRight");
    const panned = await mapPointCenter(center);
    expect(Math.abs(panned.x - originalCenter.x)).toBeGreaterThan(15);
    await page.keyboard.press("Home");
    const restored = await mapPointCenter(center);
    expect(restored.x).toBeCloseTo(originalCenter.x, 0);
    expect(restored.y).toBeCloseTo(originalCenter.y, 0);
    expect(await distance()).toBeCloseTo(originalDistance, 0);
});

test("villager map player modes use saved scan positions and separate dimensions", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1050 });
    const errors = collectBrowserErrors(page);
    const h = await openVillagerFixture(page, { layout: "studio", rows: mapVillagers(), withPlayer: true, mapPlayers: [
        { player_key: "neighbor", label: "Nachbarin", position: { x: 40, y: 66, z: -30 }, dimension: 0 },
        { player_key: "nether-player", label: "Netherbesucher", position: { x: 10, y: 70, z: 12 }, dimension: 1 },
    ] });
    await page.locator("#villagerMapToggle").click();
    const markers = page.locator(".villager-map-player");
    await expect(page.locator("#villagerMapPlayers")).toHaveValue("selected");
    await expect(markers).toHaveCount(1);
    await expect(markers.first()).toHaveAttribute("aria-label", /Testspieler/);
    const playerInfo = page.locator("#villagerMapPlayerInfo");
    await expect(playerInfo).toBeVisible();
    await expect(playerInfo).toContainText("Testspieler · 0 / 64 / 0");
    const savedPosition = await markers.first().getAttribute("aria-label");
    // Editing the player's location must not move a marker sourced from the scan.
    await page.locator('.app-workflow-nav [data-workflow-view="player-edit"]').click();
    await page.locator("#statPosX").fill("5000");
    await page.locator("#statPosZ").fill("5000");
    await page.locator('.app-workflow-nav [data-workflow-view="villagers"]').click();
    await expect(markers.first()).toHaveAttribute("aria-label", savedPosition);
    await page.locator("#villagerMapPlayers").selectOption("all");
    await expect(markers).toHaveCount(2);
    await page.locator('.villager-map-player[data-player-key="neighbor"]').click();
    await expect(playerInfo).toContainText("Nachbarin · 40 / 66 / -30");
    await expect(playerInfo).toContainText("Zuletzt gespeicherte Position");
    await page.locator('.villager-map-player[data-player-key="villager-test-player"]').focus();
    await expect(playerInfo).toContainText("Testspieler · 0 / 64 / 0");
    await expect(page.locator('.villager-map-player[aria-label*="Netherbesucher"]')).toHaveCount(0);
    await page.locator("#villagerMapDimension").selectOption("1");
    await expect(markers).toHaveCount(1);
    await expect(markers.first()).toHaveAttribute("aria-label", /Netherbesucher/);
    await markers.first().click();
    await expect(playerInfo).toContainText("Netherbesucher · 10 / 70 / 12");
    await page.locator("#villagerMapPlayers").selectOption("selected");
    await expect(markers).toHaveCount(0);
    await expect(playerInfo).toBeHidden();
    await expect(page.locator("#villagerMapPlayerHint")).toContainText("anderen Dimension");
    await expect(page.locator("#villagerMapEmpty")).toBeVisible();
    await page.locator("#villagerMapDimension").selectOption("0");
    await expect(markers).toHaveCount(1);
    await page.locator("#villagerMapPlayers").selectOption("none");
    await expect(markers).toHaveCount(0);
    await page.locator("#villagerMapPlayers").selectOption("all");
    await expect(markers).toHaveCount(2);
    await page.evaluate(() => renderServerStatus({ write_gate: { allowed: false, server_status: { status: "online" },
        server_guard_token: "map-new-server-state", server_guard_epoch: 2 }, server_guard_token: "map-new-server-state", server_guard_epoch: 2 }));
    await expect(page.locator("#villagerStale")).toBeVisible();
    await expect(markers).toHaveCount(0);
    await expect(playerInfo).toBeHidden();
    expect(h.playerWrites).toHaveLength(0);
    expect(h.writes).toHaveLength(0);
    expect(errors).toEqual([]);
});

test.describe("touch villager map", () => {
    test.use({ hasTouch: true, isMobile: true, viewport: { width: 768, height: 1024 } });
    test("two fingers zoom and pan without activating a resident", async ({ page, context }, testInfo) => {
        const errors = collectBrowserErrors(page);
        const h = await openVillagerFixture(page, { rows: mapVillagers(), withPlayer: true, mapPlayers: [
            { player_key: "tablet-neighbor", label: "Tablet-Nachbarin", position: { x: 50, y: 66, z: -25 }, dimension: 0 },
        ] });
        await page.locator("#villagerMapToggle").click();
        const map = page.locator("#villagerMap");
        await map.scrollIntoViewIfNeeded();
        const center = map.locator('[data-id="actor:resident-3"]');
        const left = map.locator('[data-id="actor:resident-2"]');
        const originalCenter = await mapPointCenter(center);
        const gap = async () => (await mapPointCenter(center)).x - (await mapPointCenter(left)).x;
        const originalGap = await gap();
        const cdp = await context.newCDPSession(page);
        const fingers = (radius, x = 0, y = 0) => [-1, 1].map((direction, index) => ({
            id: index + 1, x: originalCenter.x + x + direction * radius, y: originalCenter.y + y,
        }));
        await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: fingers(35) });
        await cdp.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: fingers(65) });
        await expect.poll(gap).toBeGreaterThan(originalGap * 1.5);
        const zoomedGap = await gap();
        await cdp.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: fingers(65, 26, 18) });
        await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
        const panned = await mapPointCenter(center);
        expect(panned.x - originalCenter.x).toBeCloseTo(26, 0);
        expect(panned.y - originalCenter.y).toBeCloseTo(18, 0);
        expect(await gap()).toBeCloseTo(zoomedGap, 0);
        expect(h.details).toHaveLength(0);
        await expect(page.locator("#villagerDetail")).toBeHidden();
        await page.locator("#villagerMapFit").click();
        await page.locator("#villagerMapPlayers").selectOption("all");
        await page.locator('.villager-map-player[data-player-key="tablet-neighbor"]').tap();
        await expect(page.locator("#villagerMapPlayerInfo")).toContainText("Tablet-Nachbarin · 50 / 66 / -25");
        expect(h.details).toHaveLength(0);
        await mapScreenshot(page, testInfo, "villager-map-tablet-touch.png");
        await cdp.detach();
        expect(errors).toEqual([]);
    });
});

test("villager map zoom reveals residents beyond the first thousand without filtering them out", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1050 });
    const rows = manyVillagers(1002).map((row, index) => ({ ...row,
        name: `Bewohner ${String(index + 1).padStart(5, "0")}`, dimension: 0,
        position: { x: index < 1000 ? -100 : index === 1000 ? 90 : 100, y: 64, z: 0 },
    }));
    const h = await openVillagerFixture(page, { rows });
    await page.locator("#villagerMapToggle").click();
    const map = page.locator("#villagerMap");
    await map.scrollIntoViewIfNeeded();
    await expect(map.locator(".villager-map-point")).toHaveCount(1000);
    const last = map.locator('[data-id="actor:resident-1002"]');
    await expect(last).toHaveCount(0);
    await expect(page.locator("#villagerMapCaption")).toContainText("2 weitere Punkte");
    const bounds = await map.boundingBox();
    // The right-hand cluster is inside the fitted world bounds, but outside
    // the initial rendering budget. Zooming there must consider every row.
    await page.mouse.move(bounds.x + bounds.width * .92, bounds.y + bounds.height / 2);
    await page.mouse.wheel(0, -300);
    await expect(last).toBeVisible();
    await expect(map.locator(".villager-map-point")).toHaveCount(2);
    await expect(page.locator("#villagerMapCaption")).not.toContainText("weitere Punkte");
    await last.click();
    await expect(page.locator("#villagerDetailTitle")).toHaveText("Bewohner 01002");
    expect(h.details.at(-1).id).toBe("actor:resident-1002");
    expect(h.writes).toHaveLength(0);
});

test("empty English villager map explains missing positions and exposes translated help", async ({ page }) => {
    await page.setViewportSize({ width: 768, height: 1024 });
    const h = await openVillagerFixture(page, { rows: [], locale: "en" });
    await page.locator("#villagerMapToggle").click();
    await expect(page.locator("#villagerMapEmpty")).toBeVisible();
    await expect(page.locator("#villagerMapEmpty")).toHaveText("No matching coordinates in this dimension.");
    await expect(page.locator(".villager-map-point, .villager-map-player")).toHaveCount(0);
    await expect(page.locator("#villagerMapPlayerInfo")).toBeHidden();
    await expect(page.locator("#villagerMapPlayerHint")).toContainText("No selected player");
    await expect(page.locator("#villagerMapFit")).toHaveText("Show all");
    await expect(page.locator("#villagerMapScale")).toContainText("Grid:");
    const help = page.locator(".villager-map-help");
    await expect(help).toHaveJSProperty("open", false);
    await expect(help.locator("summary")).toHaveText("Map controls");
    await help.locator("summary").click();
    await expect(page.locator("#villagerMapHelp")).toBeVisible();
    await expect(page.locator("#villagerMapHelp")).toContainText("Mouse wheel:");
    await expect(page.locator("#villagerMapHelp")).toContainText("two fingers");
    await page.locator("#villagerMapPlayers").selectOption("all");
    await expect(page.locator("#villagerMapPlayerHint")).toContainText("No saved player positions");
    await page.locator("#villagerMapDimension").selectOption("2");
    await expect(page.locator("#villagerMapEmpty")).toBeVisible();
    await page.locator("#villagerMapZoomIn").click();
    await page.locator("#villagerMapFit").click();
    await expect(page.locator("#villagerMapZoom")).toHaveText("100 %");
    expect(h.writes).toHaveLength(0);
});

for (const [layout, width] of [["classic", 1440], ["studio", 768], ["focus", 320]]) {
    test(`villager map controls fit in ${layout} at ${width}px`, async ({ page }, testInfo) => {
        await page.setViewportSize({ width: 1440, height: 1050 });
        await openVillagerFixture(page, { layout, rows: manyVillagers(80), withPlayer: true });
        await page.setViewportSize({ width, height: 1024 });
        await page.locator("#villagerMapToggle").click();
        const map = page.locator("#villagerMap");
        await expect(map).toBeVisible();
        const widths = await map.evaluate(element => ({ map: element.getBoundingClientRect().width,
            page: document.documentElement.scrollWidth, viewport: window.innerWidth }));
        expect(widths.page).toBeLessThanOrEqual(widths.viewport + 1);
        expect(widths.map).toBeGreaterThan(180);
        for (const id of ["villagerMapZoomIn", "villagerMapZoomOut", "villagerMapFit", "villagerMapPlayers", "villagerMapDimension"]) {
            const control = page.locator(`#${id}`);
            await expect(control).toBeVisible();
            const bounds = await control.boundingBox();
            expect(bounds.x).toBeGreaterThanOrEqual(0);
            expect(bounds.x + bounds.width).toBeLessThanOrEqual(width + 1);
        }
        await mapScreenshot(page, testInfo, `villager-map-${layout}-${width}.png`);
    });
}

test("a changed server guard invalidates a prepared villager preview", async ({ page }) => {
    const h = await openVillagerFixture(page);
    await page.locator("#villagerSelectFiltered").click();
    await page.locator("#villagerBatchHeal").check();
    await page.locator("#villagerBatchPreview").click();
    await expect(page.locator("#villagerPreviewDialog")).toBeVisible();
    await page.evaluate(() => renderServerStatus({ write_gate: { allowed: false, server_status: { status: "online" },
        server_guard_token: "new-server-state", server_guard_epoch: 2 }, server_guard_token: "new-server-state", server_guard_epoch: 2 }));
    await expect(page.locator("#villagerPreviewDialog")).toBeHidden();
    await expect(page.locator("#villagerStale")).toBeVisible();
    await expect(page.locator("#villagerBatchFields")).toHaveJSProperty("disabled", true);
    await expect(page.locator("#villagerBatchMax")).toBeDisabled();
    await expect(page.locator("#villagerBatchPreview")).toBeDisabled();
    expect(h.writes).toHaveLength(0);
});

test("stale health drafts can be discarded separately without losing metadata drafts or keyboard focus", async ({ page }) => {
    const errors = collectBrowserErrors(page);
    const h = await openVillagerFixture(page);
    await page.locator('.villager-name[data-id="actor:a"]').click();
    await page.locator("#villagerDetailCurrent").fill("18");
    await page.locator("#villagerAliasDetails > summary").click();
    await page.locator("#villagerAlias").fill("Offener Alias");
    await page.locator("#villagerRegionsToggle").click();
    await page.locator("#villagerRegionName").fill("Offene Region");
    await page.locator('#villagerRows input[data-action="select"][data-id="actor:b"]').check();
    await page.locator("#villagerBatchMax").fill("40");

    await page.evaluate(() => renderServerStatus({ write_gate: { allowed: false, server_status: { status: "online" },
        server_guard_token: "new-server-state", server_guard_epoch: 2 }, server_guard_token: "new-server-state", server_guard_epoch: 2 }));
    await expect(page.locator("#villagerStale")).toBeVisible();
    await expect(page.locator("#villagerDetailCurrent")).toBeDisabled();
    await expect(page.locator("#villagerDetailPreview")).toBeDisabled();
    await expect(page.locator("#villagerDetailReset")).toBeEnabled();
    await page.locator("#villagerDetailReset").click();
    await expect(page.locator("#villagerDetailCurrent")).toHaveValue("12");
    await expect(page.locator("#villagerDetailDirty")).toBeHidden();
    await expect(page.locator("#villagerDetailTitle")).toBeFocused();
    await expect(page.locator("#villagerBatchDirty")).toBeVisible();
    await page.locator("#villagerBatchReset").click();
    await expect(page.locator("#villagerBatchDirty")).toBeHidden();
    await expect(page.locator("#villagerSelectFiltered")).toBeFocused();
    await expect(page.locator('#villagerRows input[data-action="select"][data-id="actor:b"]')).toBeChecked();
    await expect(page.locator("#villagerAlias")).toHaveValue("Offener Alias");
    await expect(page.locator("#villagerAliasDirty")).toBeVisible();
    await expect(page.locator("#villagerRegionName")).toHaveValue("Offene Region");
    await expect(page.locator("#villagerRegionDirty")).toBeVisible();
    expect(h.previews).toHaveLength(0);
    expect(h.writes).toHaveLength(0);
    expect(h.preferencesWrites).toHaveLength(0);
    expect(errors).toEqual([]);
});

test("legacy aliases stay with their exact identity after slot reuse and a chunk move", async ({ page }) => {
    const errors = collectBrowserErrors(page);
    const rows = manyVillagers(2).map((row, index) => ({ ...row, storage: "legacy", id: `legacy:chunk-a:${index}`,
        alias_key: `legacy-uid:${row.unique_id}` }));
    const firstKey = rows[0].alias_key, secondKey = rows[1].alias_key;
    const h = await openVillagerFixture(page, { rows, preferences: { aliases: {
        [rows[0].id]: "Unsichere alte Zuordnung", [firstKey]: "Bibliothek", [secondKey]: "Bauernhof",
    } } });
    await expect(page.locator("#villagerRows")).not.toContainText("Unsichere alte Zuordnung");
    await page.locator('.villager-name[data-id="legacy:chunk-a:0"]').click();
    await page.locator("#villagerAliasDetails > summary").click();
    await expect(page.locator("#villagerAlias")).toHaveValue("Bibliothek");
    await page.locator("#villagerAlias").fill("Hauptbibliothek");
    await page.locator("#villagerAliasSave").click();
    await expect(page.locator("#villagerAliasDirty")).toBeHidden();
    expect(h.preferencesWrites).toHaveLength(1);
    expect(h.preferencesWrites[0].aliases[firstKey]).toBe("Hauptbibliothek");
    expect(h.preferencesWrites[0].aliases[rows[0].id]).toBe("Unsichere alte Zuordnung");

    h.rows.splice(0, 1);
    h.rows[0].id = "legacy:chunk-a:0";
    await page.locator("#villagerScan").click();
    await expect(page.locator("#villagerRows .villager-name")).toHaveCount(1);
    await expect(page.locator("#villagerRows .villager-name")).toHaveText(h.rows[0].name);
    await expect(page.locator("#villagerRows")).toContainText("Bauernhof");
    await page.locator("#villagerRows .villager-name").click();
    await page.locator("#villagerAliasDetails > summary").click();
    await expect(page.locator("#villagerAlias")).toHaveValue("Bauernhof");

    h.rows[0].id = "legacy:chunk-b:0";
    await page.locator("#villagerScan").click();
    await page.locator('.villager-name[data-id="legacy:chunk-b:0"]').click();
    await expect(page.locator("#villagerDetailTitle")).toHaveText(h.rows[0].name);
    await page.locator("#villagerAliasDetails > summary").click();
    await expect(page.locator("#villagerAlias")).toHaveValue("Bauernhof");

    h.rows[0].alias_key = null;
    h.rows[0].unique_id = null;
    await page.locator("#villagerScan").click();
    await expect(page.locator("#villagerRows .villager-name")).toHaveText(h.rows[0].name);
    await page.locator("#villagerRows .villager-name").click();
    await page.locator("#villagerAliasDetails > summary").click();
    await expect(page.locator("#villagerAliasDetails")).toContainText("keine eindeutige, dauerhafte Kennung");
    await expect(page.locator("#villagerAlias")).toHaveValue("");
    await expect(page.locator("#villagerAlias")).toBeDisabled();
    await expect(page.locator("#villagerAliasSave")).toBeDisabled();
    expect(h.preferencesWrites).toHaveLength(1);
    expect(h.writes).toHaveLength(0);
    expect(errors).toEqual([]);
});

test("300 villagers keep selection across pages and filters without replacing rows during health input", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1050 });
    const errors = collectBrowserErrors(page);
    const h = await openVillagerFixture(page, { rows: manyVillagers(300) });
    await expect(page.locator("#villagerBatchForm")).toBeHidden();
    await expect(page.locator("#villagerRows tr[data-villager-id]")).toHaveCount(50);
    await page.locator("#villagerSelectPage").check();
    await expect(page.locator("#villagerDetail")).toBeHidden();
    await page.locator("#villagerNextPage").click();
    await page.locator('#villagerRows input[data-action="select"]').first().check();
    await expect(page.locator("#villagerSelectionInfo")).toContainText("51");
    await page.locator("#villagerSearch").fill("Bewohner 299");
    await expect(page.locator("#villagerRows .villager-name")).toHaveCount(1);
    await page.locator('#villagerRows input[data-action="select"]').check();
    await expect(page.locator("#villagerSelectionInfo")).toContainText("52");
    await expect(page.locator("#villagerSelectionInfo")).toContainText("51");

    await page.evaluate(() => {
        window.__villagerRowReplacements = 0;
        window.__villagerRowObserver = new MutationObserver(records => {
            window.__villagerRowReplacements += records.filter(record => record.type === "childList").length;
        });
        window.__villagerRowObserver.observe(document.getElementById("villagerRows"), { childList: true });
    });
    await page.locator("#villagerBatchMax").fill("40");
    await expect(page.locator("#villagerBatchMax")).toBeFocused();
    await expect(page.locator("#villagerBatchDirty")).toBeVisible();
    await page.locator("#villagerBatchHeal").check();
    expect(await page.evaluate(() => {
        window.__villagerRowObserver.disconnect();
        return window.__villagerRowReplacements;
    })).toBe(0);

    await page.locator("#villagerBatchPreview").click();
    await expect(page.locator("#villagerPreviewDialog")).toBeVisible();
    const expectedIds = [...h.rows.slice(0, 51), h.rows[298]].map(row => row.id).sort();
    expect(h.previews[0].selection.map(row => row.id).sort()).toEqual(expectedIds);
    expect(h.previews[0].selection.every(selected => h.rows.some(row => row.id === selected.id && row.revision === selected.revision))).toBe(true);
    await expect(page.locator("#villagerPreviewRows tr")).toHaveCount(52);
    await page.locator("#villagerPreviewCancel").click();
    await expect(page.locator("#villagerBatchDirty")).toBeVisible();
    await page.locator("#villagerBatchReset").click();
    await expect(page.locator("#villagerBatchDirty")).toBeHidden();
    await expect(page.locator("#villagerBatchMax")).toHaveValue("");
    await page.locator("#villagerClearSelection").click();
    await expect(page.locator("#villagerBatchForm")).toBeHidden();
    expect(h.scans).toHaveLength(1);
    expect(h.writes).toHaveLength(0);
    expect(errors).toEqual([]);
});

test("villager column headings sort every criterion in both directions with unknown values last", async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 1440, height: 1050 });
    const [a, b, c] = manyVillagers(3);
    const rows = [
        { ...a, id: "actor:a", name: "Zoe", profession: { id: "farmer", label: "Farmer" }, trade_tier: 0,
            health: { ...a.health, current: 2 }, dimension: 1, position: { x: 10, y: 64, z: 10 } },
        { ...b, id: "actor:b", name: "Anna", profession: { id: "librarian", label: "Bibliothekar" }, trade_tier: 4,
            health: { ...b.health, current: 20 }, dimension: 0, position: { x: 100, y: 64, z: 100 } },
        { ...c, id: "actor:c", name: "", profession: { id: "unknown", label: "Unbekannt" }, trade_tier: null,
            health: { current: null, max: null, editable: false }, dimension: null, position: null },
    ];
    const h = await openVillagerFixture(page, { rows, preferences: { regions: [
        { id: "alpha", name: "Alpha", dimension: 1, min_x: 0, max_x: 20, min_z: 0, max_z: 20 },
        { id: "zulu", name: "Zulu", dimension: 0, min_x: 90, max_x: 110, min_z: 90, max_z: 110 },
    ] } });
    const ids = () => page.locator("#villagerRows tr").evaluateAll(elements => elements.map(element => element.dataset.villagerId));
    const heading = key => page.locator(`#villagerTableHead [data-sort="${key}"]`);
    await expect(page.locator("#villagerSort")).toBeHidden();
    expect(await ids()).toEqual(["actor:b", "actor:a", "actor:c"]);
    await heading("name").focus();
    await page.keyboard.press("Enter");
    expect(await ids()).toEqual(["actor:a", "actor:b", "actor:c"]);
    await expect(heading("name")).toBeFocused();
    await expect(heading("name").locator(".villager-sort-arrow")).toHaveText("↓");
    await expect(heading("name").locator("..")).toHaveAttribute("aria-sort", "descending");
    await page.keyboard.press("Space");
    expect(await ids()).toEqual(["actor:b", "actor:a", "actor:c"]);
    for (const [key, order] of [
        ["profession", ["actor:b", "actor:a", "actor:c"]], ["tier", ["actor:a", "actor:b", "actor:c"]],
        ["health", ["actor:a", "actor:b", "actor:c"]], ["region", ["actor:a", "actor:b", "actor:c"]],
        ["dimension", ["actor:b", "actor:a", "actor:c"]],
    ]) {
        await heading(key).click();
        expect(await ids()).toEqual(order);
        await expect(heading(key)).toHaveAttribute("aria-pressed", "true");
        await expect(page.locator("#villagerTableHead th[aria-sort]")).toHaveCount(1);
        await expect(page.locator("#villagerTableHead th[aria-sort]")).toHaveAttribute("aria-sort", "ascending");
        await heading(key).click();
        expect(await ids()).toEqual([order[1], order[0], order[2]]);
        await expect(heading(key)).toBeFocused();
        await expect(page.locator("#villagerTableHead th[aria-sort]")).toHaveAttribute("aria-sort", "descending");
    }
    expect(h.writes).toHaveLength(0);
    const directory = process.env.MCBE_MAP_QA_DIR;
    if (directory) await fs.mkdir(directory, { recursive: true });
    await page.locator(".villager-table-scroll").screenshot({ path: directory ? path.join(directory, "villager-sort-classic-1440.png") : testInfo.outputPath("villager-sort-classic-1440.png") });
});

test("villager heading sorting resets pagination and preserves marked residents and keyboard focus", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 1050 });
    await openVillagerFixture(page, { rows: manyVillagers(65) });
    await page.locator('#villagerRows [data-action="select"]').first().check();
    await page.locator("#villagerNextPage").click();
    await expect(page.locator("#villagerPreviousPage")).toBeEnabled();
    const tier = page.locator('#villagerTableHead [data-sort="tier"]');
    await tier.focus();
    await page.keyboard.press("Enter");
    await expect(page.locator("#villagerPreviousPage")).toBeDisabled();
    await expect(tier).toBeFocused();
    await expect(page.locator('#villagerRows [data-action="select"][data-id="actor:resident-1"]')).toBeChecked();
    await expect(page.locator("#villagerSelectionInfo")).toContainText("1 markiert");
    await expect(page.locator("#villagerSort")).toHaveValue("tier");
});

test("villager mobile sorting retains all criteria and matches the visible column heading", async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 1440, height: 1050 });
    await openVillagerFixture(page, { layout: "focus", rows: manyVillagers(65) });
    await page.setViewportSize({ width: 320, height: 844 });
    const select = page.locator("#villagerSort");
    await expect(select).toBeVisible();
    expect(await select.locator("option").evaluateAll(options => options.map(option => option.value)))
        .toEqual(["name", "profession", "tier", "health", "region", "dimension"]);
    await page.locator("#villagerNextPage").click();
    await select.selectOption("tier");
    await expect(page.locator("#villagerPreviousPage")).toBeDisabled();
    await expect(page.locator("#villagerRows .villager-mobile-profession").first()).toContainText("Neuling");
    await page.locator("#villagerSortDirection").click();
    await expect(page.locator("#villagerRows .villager-mobile-profession").first()).toContainText("Meister");
    await select.selectOption("health");
    await expect(page.locator("#villagerRows .villager-health").first()).toContainText("12 / 20");
    const health = page.locator('#villagerTableHead [data-sort="health"]');
    await expect(health).toBeVisible();
    await expect(health).toHaveAttribute("aria-pressed", "true");
    await health.click();
    await expect(page.locator("#villagerSortDirection")).toHaveText("↓");
    await expect(page.locator("#villagerRows .villager-health").first()).toContainText("20 / 20");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
    const directory = process.env.MCBE_MAP_QA_DIR;
    if (directory) await fs.mkdir(directory, { recursive: true });
    await page.locator(".villager-list-toolbar").scrollIntoViewIfNeeded();
    await page.screenshot({ path: directory ? path.join(directory, "villager-sort-focus-320.png") : testInfo.outputPath("villager-sort-focus-320.png") });
});

test("100 villagers remain searchable and sortable with removable filters and editable regions", async ({ page }) => {
    const h = await openVillagerFixture(page, { rows: manyVillagers(100), preferences: {
        regions: [{ id: "north", name: "Norddorf", dimension: 0, min_x: 0, max_x: 196, min_z: -98, max_z: 0 }],
    } });
    await expect(page.locator("#villagerMoreFilters")).toHaveJSProperty("open", false);
    await page.locator("#villagerProfession").selectOption("librarian");
    await page.locator("#villagerMoreFilters > summary").click();
    await page.locator("#villagerDimension").selectOption("0");
    await expect(page.locator("#villagerRows .villager-name")).toHaveCount(40);
    await page.locator("#villagerMoreFilters > summary").click();
    await page.locator('[data-action="remove-filter"][data-filter="dimension"]').click();
    await expect(page.locator("#villagerProfession")).toHaveValue("librarian");
    await expect(page.locator("#villagerDimension")).toHaveValue("");
    await expect(page.locator("#villagerRows .villager-name")).toHaveCount(50);
    await page.locator("#villagerMoreFilters > summary").click();
    await page.locator("#villagerTier").selectOption("4");
    await expect(page.locator("#villagerRows .villager-name")).toHaveCount(10);
    await page.locator("#villagerResetFilters").click();
    await page.locator('#villagerTableHead [data-sort="health"]').click();
    await expect(page.locator("#villagerRows .villager-health").first()).toContainText("12 / 20");
    await page.locator('#villagerTableHead [data-sort="health"]').click();
    await expect(page.locator("#villagerRows .villager-health").first()).toContainText("20 / 20");
    await page.locator("#villagerRegion").selectOption("north");
    await expect(page.locator("#villagerRows .villager-name")).toHaveCount(45);
    await page.locator("#villagerRegionsToggle").click();
    await page.locator('[data-action="edit-region"][data-id="north"]').click();
    await expect(page.locator("#villagerRegionName")).toHaveValue("Norddorf");
    await expect(page.locator("#villagerRegionDirty")).toBeHidden();
    await page.locator("#villagerRegionName").fill("Handelsplatz");
    await expect(page.locator("#villagerRegionDirty")).toBeVisible();
    await page.locator("#villagerRegionSave").click();
    await expect(page.locator("#villagerRegion option:checked")).toHaveText("Handelsplatz");
    await page.locator('[data-action="delete-region"][data-id="north"]').click();
    await page.locator("#confirmOk").click();
    await expect(page.locator("#villagerRegion")).toHaveValue("");
    await expect(page.locator("#villagerRegionList")).not.toContainText("Handelsplatz");
    await page.locator("#villagerSearch").fill(h.rows[98].unique_id);
    await expect(page.locator("#villagerRows .villager-name")).toHaveText("Bewohner 099");
    await page.locator("#villagerSearch").fill("this villager does not exist");
    await expect(page.locator("#villagerRows .villager-name")).toHaveCount(0);
    await expect(page.locator("#villagerRows")).toContainText("Keine Dorfbewohner entsprechen diesen Filtern.");
    await page.locator("#villagerResetFilters").click();
    await expect(page.locator("#villagerRows .villager-name")).toHaveCount(50);
    expect(h.preferencesWrites).toHaveLength(2);
    expect(h.writes).toHaveLength(0);
});

test("editing a region preserves a dimension without currently discovered villagers", async ({ page }) => {
    const errors = collectBrowserErrors(page);
    const region = { id: "remote", name: "Remote village", dimension: 7, min_x: 0, max_x: 10, min_z: 0, max_z: 10 };
    const h = await openVillagerFixture(page, { preferences: { regions: [region] } });
    await page.locator("#villagerRegionsToggle").click();
    await page.locator('#villagerRegionList [data-action="edit-region"]').click();
    await expect(page.locator("#villagerRegionDimension")).toHaveValue("7");
    await page.locator("#villagerRegionName").fill("Remote trading village");
    await page.locator("#villagerRegionSave").click();
    await expect(page.locator("#villagerRegionList")).toContainText("Remote trading village");
    expect(h.preferencesWrites).toHaveLength(1);
    expect(h.preferencesWrites[0].regions).toEqual([{ ...region, name: "Remote trading village" }]);
    expect(errors).toEqual([]);
});

test("deleting a saved region keeps the custom dimension of another unsaved region", async ({ page }) => {
    const errors = collectBrowserErrors(page);
    const region = { id: "remote", name: "Altes Dorf", dimension: 7, min_x: 0, max_x: 10, min_z: 0, max_z: 10 };
    const h = await openVillagerFixture(page, { preferences: { regions: [region] } });
    await page.locator("#villagerRegionsToggle").click();
    await page.locator("#villagerRegionName").fill("Neues Dorf");
    await page.locator("#villagerRegionDimension").selectOption("7");
    for (const [field, value] of Object.entries({ MinX: "20", MaxX: "30", MinZ: "40", MaxZ: "50" })) {
        await page.locator(`#villagerRegion${field}`).fill(value);
    }
    await page.locator('[data-action="delete-region"][data-id="remote"]').click();
    await page.locator("#confirmOk").click();
    await expect(page.locator("#villagerRegionList")).not.toContainText("Altes Dorf");
    await expect(page.locator("#villagerRegionDimension")).toHaveValue("7");
    await expect(page.locator("#villagerRegionName")).toHaveValue("Neues Dorf");
    await expect(page.locator("#villagerRegionDirty")).toBeVisible();
    await page.locator("#villagerRegionSave").click();
    await expect(page.locator("#villagerRegionList")).toContainText("Neues Dorf");
    expect(h.preferencesWrites).toHaveLength(2);
    expect(h.preferencesWrites[1].regions).toEqual([expect.objectContaining({ name: "Neues Dorf", dimension: 7,
        min_x: 20, max_x: 30, min_z: 40, max_z: 50 })]);
    expect(h.writes).toHaveLength(0);
    expect(errors).toEqual([]);
});

test("keyboard shortcuts reject incomplete number text without dropping health or optional region bounds", async ({ page }) => {
    const errors = collectBrowserErrors(page);
    const h = await openVillagerFixture(page);
    await page.locator('#villagerRows .villager-name[data-id="actor:a"]').click();
    await page.locator("#villagerDetailCurrent").fill("18");
    await page.locator("#villagerDetailMax").fill("");
    await page.locator("#villagerDetailMax").press("-");
    expect(await page.locator("#villagerDetailMax").evaluate(input => input.validity.badInput)).toBe(true);
    await page.locator("#villagerDetailMax").press("ControlOrMeta+s");
    await expect(page.locator("#villagerStatus")).toContainText("Lebenspunkte müssen zwischen 1 und 2048 liegen.");
    await expect(page.locator("#villagerPreviewDialog")).not.toBeVisible();
    expect(h.previews).toHaveLength(0);
    await page.locator("#villagerDetailHealAction").click();
    await expect(page.locator("#villagerPreviewDialog")).not.toBeVisible();
    expect(h.previews).toHaveLength(0);
    await page.locator("#villagerRegionsToggle").click();
    for (const [field, value] of [["Name", "Town"], ["MinX", "0"], ["MaxX", "10"], ["MinZ", "0"], ["MaxZ", "10"]]) {
        await page.locator(`#villagerRegion${field}`).fill(value);
    }
    await page.locator("#villagerRegionMinY").press("-");
    expect(await page.locator("#villagerRegionMinY").evaluate(input => input.validity.badInput)).toBe(true);
    await page.locator("#villagerRegionMinY").press("ControlOrMeta+s");
    await expect(page.locator("#villagerStatus")).toContainText("Trage für jede verwendete Achse zwei gültige Koordinaten ein.");
    expect(h.preferencesWrites).toHaveLength(0);
    await expect(page.locator("#villagerRegionName")).toHaveValue("Town");
    await expect(page.locator("#villagerRegionDirty")).toBeVisible();
    expect(errors).toEqual([]);
});

test("leaving and returning while a preview loads keeps drafts without reopening the old modal", async ({ page }) => {
    const errors = collectBrowserErrors(page);
    const h = await openVillagerFixture(page);
    let started, release, completed, previewReadId;
    const cancellations = [];
    const previewStarted = new Promise(resolve => { started = resolve; });
    const previewReleased = new Promise(resolve => { release = resolve; });
    const previewCompleted = new Promise(resolve => { completed = resolve; });
    // The delayed preview is synthetic, so its cancellation must not be sent
    // to the real job registry, which has no record of this request.
    await page.route("**/api/world_reads/*", route => {
        if (route.request().method() !== "DELETE" || new URL(route.request().url()).pathname.split("/").at(-1) !== previewReadId) return route.fallback();
        cancellations.push(previewReadId);
        return route.fulfill({ json: { success: true, read_id: previewReadId, cancelled: true } });
    });
    await page.route("**/api/villagers/preview", async route => {
        previewReadId = route.request().headers()["x-mcbe-read-id"];
        started();
        await previewReleased;
        try {
            await route.fulfill({ json: { success: true, rows: [], change_count: 1, preview_token: "obsolete-preview" } });
        } finally { completed(); }
    });
    await page.locator("#villagerSelectFiltered").click();
    await page.locator("#villagerBatchMax").fill("40");
    await page.locator("#villagerBatchPreview").click();
    await previewStarted;
    await page.locator('.app-workflow-nav [data-workflow-view="world"]').click();
    await page.locator('.app-workflow-nav [data-workflow-view="villagers"]').click();
    await expect.poll(() => cancellations).toEqual([previewReadId]);
    release();
    await previewCompleted;
    await expect(page.locator("#villagerBatchPreview")).toBeEnabled();
    await expect(page.locator("#villagerPreviewDialog")).not.toBeVisible();
    await expect(page.locator("#villagerBatchMax")).toHaveValue("40");
    await expect(page.locator("#villagerBatchDirty")).toBeVisible();
    expect(h.writes).toHaveLength(0);
    expect(errors).toEqual([]);
});

test("a delayed health preview leaves a pending discard confirmation reachable and focused", async ({ page }) => {
    const errors = collectBrowserErrors(page);
    const h = await openVillagerFixture(page);
    let releasePreview;
    const held = new Promise(resolve => { releasePreview = resolve; });
    await page.route("**/api/villagers/preview", async route => { await held; await route.fallback(); });
    await page.locator('.villager-name[data-id="actor:a"]').click();
    await page.locator("#villagerDetailCurrent").fill("18");
    await page.locator("#villagerDetailPreview").click();
    await page.locator('#villagerDetail [data-action="close-detail"]').click();
    await expect(page.locator("#confirmOverlay")).toBeVisible();
    await page.locator("#confirmCancel").focus();
    releasePreview();
    await expect.poll(() => page.evaluate(() => getVillagerController().getState().busy)).toBe(false);
    await expect(page.locator("#villagerPreviewDialog")).toBeHidden();
    await expect(page.locator("#confirmCancel")).toBeFocused();
    await page.locator("#confirmCancel").click();
    await expect(page.locator("#villagerDetailCurrent")).toHaveValue("18");
    await expect(page.locator("#villagerDetailDirty")).toBeVisible();
    await page.locator("#villagerDetailPreview").click();
    await expect(page.locator("#villagerPreviewDialog")).toBeVisible();
    await page.locator("#villagerPreviewCancel").click();
    expect(h.writes).toHaveLength(0);
    expect(errors).toEqual([]);
});

test("Ctrl+S cannot start a preferences write while a health preview is still loading", async ({ page }) => {
    const errors = collectBrowserErrors(page);
    const h = await openVillagerFixture(page);
    let releasePreview, releasePreferences, preferencesRequests = 0;
    const previewHeld = new Promise(resolve => { releasePreview = resolve; });
    const preferencesHeld = new Promise(resolve => { releasePreferences = resolve; });
    await page.route("**/api/villagers/preview", async route => { await previewHeld; await route.fallback(); });
    await page.route("**/api/villagers/preferences", async route => {
        preferencesRequests++;
        await preferencesHeld;
        await route.fallback();
    });
    try {
        await page.locator('.villager-name[data-id="actor:a"]').click();
        await page.locator("#villagerAliasDetails > summary").click();
        await page.locator("#villagerAlias").fill("Neuer Anzeigename");
        await page.locator("#villagerDetailCurrent").fill("18");
        await page.locator("#villagerDetailPreview").click();
        await expect(page.locator("#villagerAliasSave")).toBeDisabled();
        await page.locator("#villagerAlias").press("Control+s");
        expect(await page.evaluate(() => getVillagerController().getState().preferencesBusy)).toBe(false);
        expect(preferencesRequests).toBe(0);

        releasePreview();
        await expect(page.locator("#villagerPreviewDialog")).toBeVisible();
        await page.locator("#villagerPreviewCancel").click();
        await expect(page.locator("#villagerAlias")).toHaveValue("Neuer Anzeigename");
        await page.locator("#villagerAlias").press("Control+s");
        await expect.poll(() => preferencesRequests).toBe(1);
        releasePreferences();
        await expect(page.locator("#villagerAliasDirty")).toBeHidden();
        await expect(page.locator("#villagerDetailCurrent")).toHaveValue("18");
        expect(h.preferencesWrites).toHaveLength(1);
        expect(h.writes).toHaveLength(0);
        expect(errors).toEqual([]);
    } finally {
        releasePreview(); releasePreferences();
    }
});

test("a maximum-only edit preserves an original sub-one health value through the normal form", async ({ page }) => {
    const errors = collectBrowserErrors(page);
    const rows = manyVillagers(1);
    rows[0].health.current = 0.5;
    const h = await openVillagerFixture(page, { rows });
    await page.locator("#villagerRows .villager-name").click();
    await page.locator("#villagerDetailMax").fill("40");
    await page.locator("#villagerDetailPreview").click();
    await expect(page.locator("#villagerPreviewDialog")).toBeVisible();
    expect(h.previews).toHaveLength(1);
    expect(h.previews[0].changes).toEqual({ max_health: 40 });
    await saveVillagers(page);
    await expect(page.locator("#villagerPreviewDialog")).not.toBeVisible();
    await expect(page.locator("#villagerDetailMax")).toHaveValue("40");
    await expect(page.locator("#villagerDetailCurrent")).toHaveValue("0.5");
    await page.locator("#villagerDetailCurrent").fill("0.75");
    await page.locator("#villagerDetailPreview").click();
    await expect(page.locator("#villagerStatus")).toContainText("Lebenspunkte müssen zwischen 1 und 2048 liegen.");
    await expect(page.locator("#villagerPreviewDialog")).not.toBeVisible();
    expect(h.previews).toHaveLength(1);
    expect(h.writes).toHaveLength(1);
    expect(errors).toEqual([]);
});

test("a rejected stale save closes the modal so the user can rescan without Escape", async ({ page }) => {
    const errors = collectBrowserErrors(page);
    await openVillagerFixture(page);
    let writes = 0;
    await page.route("**/api/workspace/save", route => {
        writes += 1;
        return route.fulfill({ status: 409, json: { success: false, code: "villager_preview_stale", error: "Die Änderungsvorschau ist veraltet." } });
    });
    await page.locator("#villagerSelectFiltered").click();
    await page.locator("#villagerBatchMax").fill("40");
    await page.locator("#villagerBatchPreview").click();
    await expect(page.locator("#villagerPreviewDialog")).toBeVisible();
    await saveVillagers(page);
    await expect(page.locator("#villagerPreviewDialog")).not.toBeVisible();
    await expect(page.locator("#villagerStale")).toContainText("Die Änderungsvorschau ist veraltet.");
    await expect(page.locator("#villagerScan")).toBeEnabled();
    await expect(page.locator("#villagerPending")).toBeVisible();
    expect(writes).toBe(1);
    expect(errors).toEqual([]);
});

test("central save combines villager health with the loaded player inventory", async ({ page }) => {
    const errors = collectBrowserErrors(page);
    const h = await openVillagerFixture(page, { withPlayer: true });
    await page.locator('.app-workflow-nav [data-workflow-view="inventory"]').click();
    await page.locator('.inventory-slot[data-slot="0"]').click();
    await page.locator("#detailCount").fill("7");
    expect(await page.evaluate(() => isDirty)).toBe(true);

    await page.locator('.app-workflow-nav [data-workflow-view="villagers"]').click();
    await page.locator('.villager-name[data-id="actor:a"]').click();
    await page.locator("#villagerDetailCurrent").fill("18");
    await page.locator("#villagerDetailCurrent").press("Control+s");
    await expect(page.locator("#villagerPreviewDialog")).toBeVisible();
    await saveVillagers(page);
    await expect(page.locator("#villagerPreviewDialog")).toBeHidden();
    await expect(page.locator("#villagerDetailCurrent")).toHaveValue("18");
    await expect(page.locator("#villagerDetailDirty")).toBeHidden();
    expect(await page.evaluate(() => ({ dirty: isDirty, count: inventory[0].count }))).toEqual({ dirty: false, count: 7 });

    await page.locator('.app-workflow-nav [data-workflow-view="inventory"]').click();
    await expect(page.locator("#detailCount")).toHaveValue("7");
    await expect(page.locator("#btnUndo")).toBeDisabled();
    expect(await page.evaluate(() => isDirty)).toBe(false);
    expect(h.writes).toHaveLength(1);
    expect(h.playerWrites).toHaveLength(1);
    expect(errors).toEqual([]);
});

test("saving a player preserves villager drafts while invalidating their older world snapshot", async ({ page }) => {
    const errors = collectBrowserErrors(page);
    const h = await openVillagerFixture(page, { withPlayer: true });
    await page.locator('.villager-name[data-id="actor:a"]').click();
    await page.locator("#villagerDetailCurrent").fill("18");
    await page.locator("#villagerAliasDetails > summary").click();
    await page.locator("#villagerAlias").fill("Noch nicht gespeichert");
    await page.locator('.app-workflow-nav [data-workflow-view="inventory"]').click();
    await page.locator('.inventory-slot[data-slot="0"]').click();
    await page.locator("#detailCount").fill("7");
    await page.keyboard.press("Control+s");
    await expect(page.locator("#saveReviewOverlay")).toBeVisible();
    await page.locator("#btnSaveReviewConfirm").click();
    await expect.poll(() => page.evaluate(() => getSaveAppController().isSaving())).toBe(false);
    expect(await page.evaluate(() => isDirty)).toBe(false);

    await page.locator('.app-workflow-nav [data-workflow-view="villagers"]').click();
    await expect(page.locator("#villagerStale")).toBeVisible();
    await expect(page.locator("#villagerDetailCurrent")).toHaveValue("18");
    await expect(page.locator("#villagerDetailCurrent")).toBeDisabled();
    await expect(page.locator("#villagerAlias")).toHaveValue("Noch nicht gespeichert");
    await expect(page.locator("#villagerDraftStatus")).toBeVisible();
    expect(h.playerWrites).toHaveLength(1);
    expect(h.writes).toHaveLength(0);
    expect(h.preferencesWrites).toHaveLength(0);
    expect(errors).toEqual([]);
});

test("English tablet single editing shows real drafts and preserves aliases and regions after saving health", async ({ page }) => {
    await page.setViewportSize({ width: 1024, height: 900 });
    const errors = collectBrowserErrors(page);
    const h = await openVillagerFixture(page, { layout: "studio", locale: "en", rows: manyVillagers(10, "en") });
    await expect(page.locator("#villagersTitle")).toHaveText("Villagers");
    await expect(page.locator("#villagerMoreFilters > summary")).toContainText("filters");
    await page.locator('.villager-name[data-id="actor:resident-1"]').click();
    await expect(page.locator("#villagerTechnicalDetails > summary")).toContainText("Technical");
    await page.locator("#villagerDetailCurrent").fill("18");
    await expect(page.locator("#villagerDetailDirty")).toBeVisible();
    await expect(page.locator("#villagerDraftStatus")).toContainText(/unsaved|pending/i);
    await page.locator("#villagerDetailCurrent").fill("12");
    await expect(page.locator("#villagerDetailDirty")).toBeHidden();
    await expect(page.locator("#villagerDraftStatus")).toBeHidden();
    await page.locator("#villagerAliasDetails > summary").click();
    await page.locator("#villagerAlias").fill("Bookkeeper");
    await page.locator("#villagerDetailMax").fill("40");
    await page.locator("#villagerDetailHeal").check();
    await page.locator("#villagerDetailReset").click();
    await expect(page.locator("#villagerDetailMax")).toHaveValue("20");
    await expect(page.locator("#villagerDetailCurrent")).toHaveValue("12");
    await expect(page.locator("#villagerAlias")).toHaveValue("Bookkeeper");
    await expect(page.locator("#villagerAliasDirty")).toBeVisible();
    await page.locator("#villagerRegionsToggle").click();
    await page.locator("#villagerRegionName").fill("Trading hall");
    await page.locator("#villagerDetailCurrent").fill("18");
    await page.locator('#villagerDetailHealthForm button[type="submit"]').click();
    await expect(page.locator("#villagerPreviewDialog")).toBeVisible();
    expect(h.previews[0].selection.map(row => row.id)).toEqual(["actor:resident-1"]);
    await saveVillagers(page);
    await expect(page.locator("#villagerPreviewDialog")).toBeHidden();
    await expect(page.locator("#villagerDetailCurrent")).toHaveValue("18");
    await expect(page.locator("#villagerDetailDirty")).toBeHidden();
    await expect(page.locator("#villagerAlias")).toHaveValue("Bookkeeper");
    await expect(page.locator("#villagerRegionName")).toHaveValue("Trading hall");
    await expect(page.locator("#villagerDraftStatus")).toContainText(/unsaved|pending/i);
    expect(h.preferencesWrites).toHaveLength(0);
    expect(h.writes).toHaveLength(1);
    expect(h.scans).toHaveLength(2);
    expect(errors).toEqual([]);
});

test("keyboard review targets the focused villager and closing details restores row focus", async ({ page }) => {
    const h = await openVillagerFixture(page);
    await page.locator('#villagerRows input[data-action="select"][data-id="actor:b"]').check();
    await expect(page.locator("#villagerDetail")).toBeHidden();
    await page.locator("#villagerBatchMax").fill("40");
    for (const closeWith of ["escape", "button"]) {
        await page.locator("#villagerBatchPreview").click();
        await expect(page.locator("#villagerPreviewDialog")).toBeVisible();
        if (closeWith === "escape") await page.keyboard.press("Escape");
        else await page.locator("#villagerPreviewClose").click();
        await expect(page.locator("#villagerPreviewDialog")).toBeHidden();
        await expect(page.locator("#villagerBatchPreview")).toBeFocused();
        await expect(page.locator("#villagerBatchMax")).toHaveValue("40");
        await expect(page.locator('#villagerRows input[data-action="select"][data-id="actor:b"]')).toBeChecked();
    }
    const name = page.locator('.villager-name[data-id="actor:a"]');
    await name.focus(); await name.press("Enter");
    await page.locator("#villagerDetailCurrent").fill("18");
    await page.locator("#villagerDetailCurrent").press("Control+s");
    await expect(page.locator("#villagerPreviewDialog")).toBeVisible();
    expect(h.previews.at(-1).selection.map(row => row.id)).toEqual(["actor:a"]);
    expect(h.previews.at(-1).changes.current_health).toBe(18);
    await page.keyboard.press("Escape");
    await expect(page.locator("#villagerPreviewDialog")).toBeHidden();
    await expect(page.locator("#villagerDetail")).toBeVisible();
    await expect(page.locator("#villagerDetailCurrent")).toBeFocused();
    await expect(page.locator("#villagerDetailCurrent")).toHaveValue("18");
    await page.locator("#villagerDetailReset").click();
    await expect(page.locator("#villagerBatchMax")).toHaveValue("40");
    await page.locator("#villagerDetailHealAction").click();
    await expect(page.locator("#villagerPreviewDialog")).toBeVisible();
    expect(h.previews.at(-1).selection.map(row => row.id)).toEqual(["actor:a"]);
    expect(h.previews.at(-1).changes.heal).toBe(true);
    expect(h.previews.at(-1).changes.current_health).toBeUndefined();
    await page.locator("#villagerPreviewCancel").click();
    await expect(page.locator("#villagerDetailHealAction")).toBeFocused();
    await page.locator("#villagerDetailReset").click();
    await page.locator("#villagerDetailTitle").focus();
    await page.keyboard.press("Escape");
    await expect(page.locator("#villagerDetail")).toBeHidden();
    await expect(name).toBeFocused();
    await expect(page.locator("#villagerBatchDirty")).toBeVisible();
    expect(h.writes).toHaveLength(0);
});

test("unsupported records explain read-only fields and protected maxima still allow current health", async ({ page }) => {
    const rows = manyVillagers(2);
    rows[0].health.max_editable = false;
    rows[0].health.max_reason = "Dieses Maximum bleibt geschützt.";
    rows[1].editable = false;
    rows[1].health = { current: 12, max: 20, editable: false, max_editable: false, reason: "Älteres Format: nur lesen." };
    const h = await openVillagerFixture(page, { rows });
    await page.locator('.villager-name[data-id="actor:resident-2"]').click();
    await expect(page.locator("#villagerDetail")).toContainText("Älteres Format: nur lesen.");
    await expect(page.locator("#villagerDetailCurrent")).toBeDisabled();
    await page.locator('.villager-name[data-id="actor:resident-1"]').click();
    await expect(page.locator("#villagerDetail")).toContainText("Dieses Maximum bleibt geschützt.");
    await expect(page.locator("#villagerDetailMax")).toBeDisabled();
    await expect(page.locator("#villagerDetailCurrent")).toBeEnabled();
    await page.locator("#villagerDetailCurrent").fill("18");
    await page.locator('#villagerDetailHealthForm button[type="submit"]').click();
    await expect(page.locator("#villagerPreviewDialog")).toBeVisible();
    expect(h.previews[0].changes).toEqual({ current_health: 18 });
    expect(h.writes).toHaveLength(0);
});

test("read-only viewer retains discovery and detail access while all edit forms stay protected", async ({ page }) => {
    const h = await openVillagerFixture(page, { readOnly: true });
    await page.locator('.villager-name[data-id="actor:a"]').click();
    await expect(page.locator("#villagerDetailMax")).toBeDisabled();
    await expect(page.locator("#villagerDetailCurrent")).toBeDisabled();
    await page.locator("#villagerAliasDetails > summary").click();
    await expect(page.locator("#villagerAlias")).toBeDisabled();
    await expect(page.locator("#villagerAliasSave")).toBeDisabled();
    await page.locator("#villagerRegionsToggle").click();
    await expect(page.locator("#villagerRegionName")).toBeDisabled();
    await expect(page.locator("#villagerRegionSave")).toBeDisabled();
    expect(h.details).toHaveLength(1);
    expect(h.previews).toHaveLength(0);
    expect(h.preferencesWrites).toHaveLength(0);
    expect(h.writes).toHaveLength(0);
});

test("empty scans and recoverable failures remain distinct from a populated world", async ({ page }) => {
    const h = await openVillagerFixture(page, { rows: [] });
    await expect(page.locator("#villagerRows")).toContainText(/Keine.*Dorfbewohner/);
    await expect(page.locator("#villagerBatchForm")).toBeHidden();
    const failure = route => route.fulfill({ status: 503, json: { success: false, error: "Lesen derzeit nicht möglich." } });
    await page.route("**/api/villagers/scan", failure);
    await page.locator("#villagerScan").click();
    await expect(page.locator("#villagerStatus")).toContainText("Lesen derzeit nicht möglich.");
    await expect(page.locator("#villagerScan")).toBeEnabled();
    await page.unroute("**/api/villagers/scan", failure);
    h.rows.push(...manyVillagers(10));
    await page.locator("#villagerScan").click();
    await expect(page.locator("#villagerRows .villager-name")).toHaveCount(10);
    await expect(page.locator("#villagerStatus")).not.toContainText("Lesen derzeit nicht möglich.");
});


for (const waitForDetail of [true, false]) {
    test(`a pending alias save stays clean when reopened detail loads ${waitForDetail ? "before" : "after"} its response`, async ({ page }) => {
        const errors = collectBrowserErrors(page);
        const h = await openVillagerFixture(page);
        let releasePreferences, releaseDetail, preferencesRequests = 0, detailRequests = 0;
        const preferencesHeld = new Promise(resolve => { releasePreferences = resolve; });
        const detailHeld = new Promise(resolve => { releaseDetail = resolve; });
        await page.route("**/api/villagers/preferences", async route => {
            preferencesRequests++;
            await preferencesHeld;
            await route.fallback();
        });
        try {
            await page.locator('.villager-name[data-id="actor:a"]').click();
            await page.locator("#villagerAliasDetails > summary").click();
            await page.locator("#villagerAlias").fill("Hauptbibliothek");
            await page.locator("#villagerAliasSave").click();
            await expect.poll(() => preferencesRequests).toBe(1);
            await page.locator('#villagerDetail [data-action="close-detail"]').click();
            await page.locator("#confirmOk").click();
            await expect(page.locator("#villagerDetail")).toBeHidden();
            if (!waitForDetail) await page.route("**/api/villagers/detail", async route => {
                detailRequests++;
                await detailHeld;
                await route.fallback();
            });
            await page.locator('.villager-name[data-id="actor:a"]').click();
            if (waitForDetail) {
                await page.locator("#villagerAliasDetails > summary").click();
                await expect(page.locator("#villagerAlias")).toHaveValue("");
            } else await expect.poll(() => detailRequests).toBe(1);
            releasePreferences();
            await expect.poll(() => h.preferencesWrites.length).toBe(1);
            await expect.poll(() => page.evaluate(() => getVillagerController().getState().preferencesBusy)).toBe(false);
            releaseDetail();
            if (!waitForDetail) await page.locator("#villagerAliasDetails > summary").click();
            await expect(page.locator("#villagerAlias")).toHaveValue("Hauptbibliothek");
            await expect(page.locator("#villagerAliasDirty")).toBeHidden();
            await expect(page.locator("#villagerAliasSave")).toBeDisabled();
            await expect(page.locator("#villagerDetailTitle")).toHaveText("Bücherwart");
            await page.locator("#villagerAlias").press("Control+s");
            expect(h.preferencesWrites).toHaveLength(1);
            expect(h.writes).toHaveLength(0);
            expect(errors).toEqual([]);
        } finally {
            releasePreferences(); releaseDetail();
        }
    });
}

for (const [width, enlargedText] of [[1440, false], [768, false], [390, false], [768, true]]) {
    test(`staged health and supplies share one world-only save at ${width}px${enlargedText ? " with enlarged text" : ""}`, async ({ page }, testInfo) => {
        await page.setViewportSize({width, height: 1000});
        const errors = collectBrowserErrors(page);
        const h = await openVillagerFixture(page);
        if (enlargedText) await page.addStyleTag({content: ":root { font-size: 20px; }"});
        await openVillagerStock(page);
        await page.locator("#villagerDetailCurrent").fill("18");
        await page.locator("#villagerDetailPreview").click();
        await page.locator("#villagerSave").click();
        expect(h.writes).toHaveLength(0);
        await page.locator("#villagerStockCount0").fill("9");
        await page.locator("#villagerInventoryPreview").click();
        await page.locator("#villagerSave").click();
        expect(h.writes).toHaveLength(0);
        await expect(page.locator("#villagerPendingRows button")).toHaveCount(2);
        await page.locator("#villagerReviewPending").click();
        await expect(page.locator("#saveWorkflowSummary")).toContainText("12 / 20 → 18 / 20");
        await expect(page.locator("#saveWorkflowSummary")).toContainText("9 × Brot");
        await expect(page.locator("#btnSaveWorkflowRun")).toBeEnabled();
        if (enlargedText) {
            const navigation = page.locator(".app-workflow-nav");
            for (const name of ["Hilfe", "Welt"]) {
                const button = navigation.getByRole("button", {name, exact: true});
                await button.focus();
                await expect(button).toBeInViewport({ratio: 1});
            }
        }
        const pageWidth = await page.evaluate(() => ({
            viewport: innerWidth,
            document: document.documentElement.scrollWidth,
            overflow: [...document.querySelectorAll("body *")].flatMap(element => {
                const rect = element.getBoundingClientRect();
                return rect.width && rect.right > innerWidth + 1
                    ? [{element: element.id || element.className || element.tagName, right: rect.right, width: rect.width}]
                    : [];
            }),
        }));
        expect(pageWidth.document, JSON.stringify(pageWidth)).toBeLessThanOrEqual(pageWidth.viewport + 1);
        const screenshotName = `central-save-${width}${enlargedText ? "-enlarged" : ""}.png`;
        const directory = process.env.MCBE_MAP_QA_DIR;
        if (directory) await fs.mkdir(directory, {recursive: true});
        await page.screenshot({path: directory ? path.join(directory, screenshotName) : testInfo.outputPath(screenshotName), fullPage: true});
        await page.locator("#btnSaveWorkflowRun").click();
        await expect.poll(() => h.writes.length).toBe(1);
        await expect.poll(() => page.evaluate(() => isDirty)).toBe(false);
        expect(h.writes[0].villager_previews).toHaveLength(2);
        expect(h.rows[0].health.current).toBe(18);
        expect(h.inventories.get("actor:a").slots[0].item.count).toBe(9);
        expect(h.playerWrites).toHaveLength(0);
        expect(errors).toEqual([]);
    });
}

test("removing one staged preview retains the other and writes nothing", async ({page}) => {
    const h = await openVillagerFixture(page);
    await openVillagerStock(page);
    await page.locator("#villagerDetailCurrent").fill("18");
    await page.locator("#villagerDetailPreview").click();
    await page.locator("#villagerSave").click();
    await page.locator("#villagerStockCount0").fill("9");
    await page.locator("#villagerInventoryPreview").click();
    await page.locator("#villagerSave").click();
    await page.locator("#villagerPendingRows button").first().click();
    await expect(page.locator("#villagerPendingRows button")).toHaveCount(1);
    await page.locator("#villagerReviewPending").click();
    await expect(page.locator("#saveWorkflowSummary")).not.toContainText("18 / 20");
    await expect(page.locator("#saveWorkflowSummary")).toContainText("9 × Brot");
    await page.locator("#btnReviewDiscardChanges").click();
    await page.locator("#confirmOk").click();
    await expect(page.locator("#btnSaveWorkflowRun")).toBeDisabled();
    expect(h.writes).toHaveLength(0);
});

test("an unreadable world-only commit blocks replay until the world is reloaded", async ({page}) => {
    await openVillagerFixture(page);
    let requests = 0;
    await page.route("**/api/workspace/save", route => { requests++; return route.fulfill({status: 200, body: "incomplete"}); });
    await page.locator('.villager-name[data-id="actor:a"]').click();
    await page.locator("#villagerDetailCurrent").fill("18");
    await page.locator("#villagerDetailPreview").click();
    await saveVillagers(page, {returnToVillagers: false});
    await expect(page.locator("#btnSaveWorkflowRun")).toBeDisabled();
    await page.evaluate(() => saveCurrentPlayer({skipReview: true}));
    expect(requests).toBe(1);
    expect(await page.evaluate(() => getVillagerController().getPendingChanges().length)).toBe(1);
});

for (const withPlayer of [false, true]) {
    test(`reloading the same world discards villager staging only after a successful read (${withPlayer ? "player" : "world-only"})`, async ({page}) => {
        const h = await openVillagerFixture(page, {withPlayer});
        await page.locator('.villager-name[data-id="actor:a"]').click();
        await page.locator("#villagerDetailCurrent").fill("18");
        await page.locator("#villagerDetailPreview").click();
        await page.locator("#villagerSave").click();
        await page.locator('.app-workflow-nav [data-workflow-view="world"]').click();

        await page.locator("#btnLoad").click();
        await page.locator("#confirmCancel").click();
        await expect(page.locator("#confirmOverlay")).toBeHidden();
        expect(await page.evaluate(() => getVillagerController().getPendingChanges().length)).toBe(1);
        expect(await page.evaluate(() => isDirty)).toBe(true);

        const failRead = route => route.fulfill({json: {success: false, error: "Welt vorübergehend nicht lesbar."}});
        await page.route("**/api/players", failRead);
        await page.locator("#btnLoad").click();
        await page.locator("#confirmOk").click();
        await expect(page.locator("#loadingOverlay")).toBeHidden();
        expect(await page.evaluate(() => getVillagerController().getPendingChanges().length)).toBe(1);
        expect(await page.evaluate(() => isDirty)).toBe(true);
        await page.unroute("**/api/players", failRead);

        await page.locator("#btnLoad").click();
        await page.locator("#confirmOk").click();
        await expect(page.locator("#loadingOverlay")).toBeHidden();
        expect(await page.evaluate(() => getVillagerController().getPendingChanges().length)).toBe(0);
        expect(await page.evaluate(() => getVillagerController().getState().loaded)).toBe(false);
        expect(await page.evaluate(() => isDirty)).toBe(false);
        await page.locator('.app-workflow-nav [data-workflow-view="villagers"]').click();
        await expect.poll(() => h.scans.length).toBe(2);
        await expect(page.locator("#villagerPending")).toBeHidden();
        expect(h.writes).toHaveLength(0);
    });
}

test("player list refresh and export-only selection preserve saveable villager staging", async ({page}) => {
    const errors = collectBrowserErrors(page);
    const h = await openVillagerFixture(page);
    await page.locator('.villager-name[data-id="actor:a"]').click();
    await page.locator("#villagerDetailCurrent").fill("18");
    await page.locator("#villagerDetailPreview").click();
    await page.locator("#villagerSave").click();
    await page.route("**/api/players", route => route.fulfill({json: {
        success: true, world_name: "Villager Test World", server_guard_epoch: 1, server_guard_token: "villager-guard",
        players: [{player_key: "export-only", label: "Archivspieler", editable: false, exportable: true}],
    }}));
    await page.locator('.app-workflow-nav [data-workflow-view="player"]').click();
    await page.locator("#btnRefreshPlayers").click();
    await page.locator("#confirmOk").click();
    await expect(page.locator('.player-row[data-player-key="export-only"]')).toBeVisible();
    expect(await page.evaluate(() => isDirty)).toBe(true);
    expect(await page.evaluate(() => getVillagerController().getPendingChanges().length)).toBe(1);
    await page.locator('.player-row[data-player-key="export-only"]').click();
    await page.locator("#confirmOk").click();
    await expect.poll(() => page.evaluate(() => currentPlayerKey)).toBe("export-only");
    expect(await page.evaluate(() => isDirty)).toBe(true);
    await page.locator('.app-workflow-nav [data-workflow-view="save"]').click();
    await expect(page.locator("#btnSaveWorkflowRun")).toBeEnabled();
    await page.locator("#btnSaveWorkflowRun").click();
    await expect.poll(() => h.writes.length).toBe(1);
    expect(h.writes[0].player_key).toBeUndefined();
    expect(h.rows[0].health.current).toBe(18);
    expect(errors).toEqual([]);
});


for (const [width, layout] of [[1440, "classic"], [390, "focus"]]) {
    test(`Minecraft names use central save and preserve other drafts at ${width}px`, async ({ page }, testInfo) => {
        await page.setViewportSize({ width, height: 1000 });
        const errors = collectBrowserErrors(page);
        const h = await openVillagerFixture(page, { layout, preferences: { aliases: { "actor:a": "Bibliothek" } } });
        await page.locator('.villager-name[data-id="actor:a"]').click();
        await expect(page.locator("#villagerName")).toHaveValue("Bücherwart");
        await expect(page.locator("#villagerNamePreview")).toBeDisabled();
        await page.locator("#villagerDetailCurrent").fill("18");
        await page.locator("#villagerName").fill('Jörg <img src=x onerror=alert(1)> 🐑');
        await page.locator("#villagerName").press("Control+s");
        await expect(page.locator("#villagerPreviewRows")).toContainText('Jörg <img src=x onerror=alert(1)> 🐑');
        await expect(page.locator("#villagerPreviewRows img")).toHaveCount(0);
        expect(h.previews.at(-1).changes).toEqual({ name: 'Jörg <img src=x onerror=alert(1)> 🐑' });
        await page.locator("#villagerSave").click();
        expect(h.writes).toHaveLength(0);
        await expect(page.locator("#villagerDetailCurrent")).toHaveValue("18");
        await expect(page.locator("#villagerNameDirty")).toBeHidden();
        await page.locator("#villagerDetailPreview").click();
        await page.locator("#villagerSave").click();
        await page.locator("#villagerReviewPending").click();
        await expect(page.locator("#saveWorkflowPanel")).toContainText("Name in Minecraft: Bücherwart → Jörg");
        expect(h.writes).toHaveLength(0);
        await page.locator("#btnSaveWorkflowRun").click();
        await expect.poll(() => h.writes.length).toBe(1);
        expect(h.writes[0].villager_previews).toHaveLength(2);
        await expect.poll(() => page.evaluate(() => getSaveAppController().isSaving())).toBe(false);
        await page.locator('.app-workflow-nav [data-workflow-view="villagers"]').click();
        await expect(page.locator("#villagerName")).toHaveValue('Jörg <img src=x onerror=alert(1)> 🐑');
        await expect(page.locator("#villagerDetailCurrent")).toHaveValue("18");
        await expect(page.locator("#villagerDetailTitle")).toHaveText('Jörg <img src=x onerror=alert(1)> 🐑');
        await expect(page.locator("#villagerDetail img")).toHaveCount(0);
        await page.locator("#villagerAliasDetails > summary").click();
        await expect(page.locator("#villagerAlias")).toHaveValue("Bibliothek");
        expect(h.preferencesWrites).toHaveLength(0);
        await page.locator("#villagerDetailTitle").scrollIntoViewIfNeeded();
        await page.screenshot({ path: testInfo.outputPath(`villager-name-${width}.png`), fullPage: true });
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
        expect(errors).toEqual([]);
    });
}

test("removing a Minecraft name is reviewed explicitly, cancellable and persisted", async ({ page }) => {
    const h = await openVillagerFixture(page);
    await page.locator('.villager-name[data-id="actor:a"]').click();
    await page.locator("#villagerNameRemove").click();
    await expect(page.locator("#villagerName")).toBeFocused();
    await expect(page.locator("#villagerName")).toHaveValue("");
    await expect(page.locator("#villagerNameDirty")).toBeVisible();
    await page.locator("#villagerNameReset").click();
    await expect(page.locator("#villagerName")).toHaveValue("Bücherwart");
    await expect(page.locator("#villagerNameDirty")).toBeHidden();
    await page.locator("#villagerNameRemove").click();
    await page.locator("#villagerName").press("Enter");
    await expect(page.locator("#villagerPreviewRows")).toContainText("Ohne Namen");
    await page.locator("#villagerPreviewCancel").click();
    await expect(page.locator("#villagerName")).toHaveValue("");
    expect(h.writes).toHaveLength(0);
    await page.locator("#villagerNamePreview").click();
    await saveVillagers(page);
    expect(h.rows[0].name).toBe("");
    await expect(page.locator("#villagerName")).toHaveValue("");
    await expect(page.locator("#villagerNameRemove")).toBeDisabled();
    await expect(page.locator("#villagerDetailTitle")).toContainText("Dorfbewohner #");
});

test("name drafts survive health saves and leaving a detail requires a discard decision", async ({ page }) => {
    const h = await openVillagerFixture(page);
    await page.locator('.villager-name[data-id="actor:a"]').click();
    await page.locator("#villagerName").fill("Offener Name");
    await page.locator('.villager-name[data-id="actor:b"]').click();
    await expect(page.locator("#confirmOverlay")).toBeVisible();
    await page.locator("#confirmCancel").click();
    await expect(page.locator("#villagerName")).toHaveValue("Offener Name");
    await page.locator("#villagerDetailCurrent").fill("18");
    await page.locator("#villagerDetailPreview").click();
    await saveVillagers(page);
    await expect(page.locator("#villagerName")).toHaveValue("Offener Name");
    await expect(page.locator("#villagerNameDirty")).toBeVisible();
    expect(h.rows[0].name).toBe("Bücherwart");
    expect(h.previews).toHaveLength(1);
});

test("invalid name lengths, read-only worlds and unsupported actors block name writes", async ({ page }) => {
    const h = await openVillagerFixture(page);
    await page.locator('.villager-name[data-id="actor:a"]').click();
    await page.locator("#villagerName").fill("🐑".repeat(81));
    await page.locator("#villagerName").press("Control+s");
    await expect(page.locator("#villagerStatus")).toContainText("höchstens 80 Zeichen");
    expect(h.previews).toHaveLength(0);
    await page.locator("#villagerNameReset").click();
    await page.locator('.villager-name[data-id="legacy:c"]').click();
    await expect(page.locator("#villagerName")).toBeDisabled();
    await expect(page.locator("#villagerNamePreview")).toBeDisabled();
    await expect(page.locator("#villagerNameRemove")).toBeDisabled();
});

test("Minecraft name controls remain read-only in viewer mode", async ({ page }) => {
    const h = await openVillagerFixture(page, { readOnly: true });
    await page.locator('.villager-name[data-id="actor:a"]').click();
    for (const id of ["villagerName", "villagerNamePreview", "villagerNameRemove"]) await expect(page.locator(`#${id}`)).toBeDisabled();
    expect(h.previews).toHaveLength(0);
});


test("an unchanged stored name with whitespace does not become a draft after another field is saved", async ({ page }) => {
    const rows = manyVillagers(1);
    rows[0].name = "  Egon  ";
    const h = await openVillagerFixture(page, { rows });
    await page.locator("#villagerRows .villager-name").click();
    await page.locator("#villagerDetailCurrent").fill("18");
    await page.locator("#villagerDetailPreview").click();
    await saveVillagers(page);
    await expect(page.locator("#villagerName")).toHaveValue("  Egon  ");
    await expect(page.locator("#villagerNameDirty")).toBeHidden();
    await expect(page.locator("#villagerNamePreview")).toBeDisabled();
    expect(h.previews).toHaveLength(1);
});
