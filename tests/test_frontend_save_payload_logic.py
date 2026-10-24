import textwrap

from tests.node_runner import run_node


def test_frontend_save_payload_logic_builds_delta_sections() -> None:
    run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/save_payload_logic.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/save_payload_logic.js" });

            function changed(a, b) {
                return JSON.stringify(a ?? null) !== JSON.stringify(b ?? null);
            }

            function makeLogic(overrides = {}) {
                const state = {
                    cleanSnapshot: { inv: {}, ec: {}, stats: {}, effects: [], abilities: {} },
                    worldPath: "C:/World",
                    currentPlayerKey: "local_player",
                    currentPlayerRevision: "rev-1",
                    serverGuardEpoch: 0,
                    serverGuardToken: "guard-token",
                    inventory: {},
                    enderChestInventory: {},
                    playerStats: {},
                    playerEffects: [],
                    playerAbilities: {},
                    protectedNbt: {},
                    effectsTouched: false,
                    abilitiesTouched: false,
                    syncEffectsCount: 0,
                    collectAbilitiesCount: 0,
                    preparedItems: [],
                    collectedAbilities: null,
                    protectedStats: new Set(),
                    ...overrides,
                };
                const logic = context.window.MCBESavePayloadLogic.createSavePayloadLogic({
                    collectAbilitiesFromUI: () => {
                        state.collectAbilitiesCount += 1;
                        return state.collectedAbilities;
                    },
                    getAbilitiesTouched: () => state.abilitiesTouched,
                    getCleanSnapshot: () => state.cleanSnapshot,
                    getCurrentPlayerKey: () => state.currentPlayerKey,
                    getCurrentPlayerRevision: () => state.currentPlayerRevision,
                    getEnderChestInventory: () => state.enderChestInventory,
                    getEffectsTouched: () => state.effectsTouched,
                    getInventory: () => state.inventory,
                    getPlayerAbilities: () => state.playerAbilities,
                    getPlayerEffects: () => state.playerEffects,
                    getPlayerStats: () => state.playerStats,
                    getProtectedNbt: () => state.protectedNbt,
                    getServerGuardEpoch: () => state.serverGuardEpoch,
                    getServerGuardToken: () => state.serverGuardToken,
                    getWorldPath: () => state.worldPath,
                    getWorldPresenceSessionId: () => "presence-1",
                    itemIsVisiblePresent: item => Boolean(item && item.name && item.name !== "minecraft:air"),
                    itemRequiresOriginalNbt: item => {
                        state.preparedItems.push(item);
                        return Boolean(item && (item.has_protected_nbt || item.has_preserved_nbt || item.requires_original_nbt));
                    },
                    removeProtectedStatsFromPayload: stats => Object.fromEntries(Object.entries(stats).filter(([key]) => !state.protectedStats.has(key))),
                    sectionChanged: changed,
                    setPlayerAbilities: value => {
                        state.playerAbilities = value;
                    },
                    syncEffectsFromUI: () => {
                        state.syncEffectsCount += 1;
                    },
                });
                return { logic, state };
            }

            for (const [inventoryChanged, enderChestChanged, hasSnapshot] of [
                [false, false, true], [true, false, true], [false, true, true],
                [true, true, true], [false, false, false],
            ]) {
                const inventory = {0: {slot: 0, name: "minecraft:stone", count: 1}};
                const enderChestInventory = {2: {slot: 2, name: "minecraft:diamond", count: 1}};
                const cleanSnapshot = JSON.parse(JSON.stringify({
                    inv: inventory, ec: enderChestInventory, stats: {health: 20}, effects: [], abilities: {},
                }));
                if (inventoryChanged) inventory[0].count = 2;
                if (enderChestChanged) enderChestInventory[2].count = 3;
                const { logic, state } = makeLogic({
                    inventory, enderChestInventory, playerStats: {health: 19},
                    cleanSnapshot: hasSnapshot ? cleanSnapshot : null,
                });
                const before = JSON.stringify([inventory, enderChestInventory, cleanSnapshot]);
                const payload = logic.buildSavePayload();
                const expectedPreparedItems = [];
                if (inventoryChanged || !hasSnapshot) expectedPreparedItems.push(inventory[0]);
                if (enderChestChanged || !hasSnapshot) expectedPreparedItems.push(enderChestInventory[2]);
                assert.deepStrictEqual(state.preparedItems, expectedPreparedItems,
                    "unchanged inventory sections must not prepare items for saving");
                assert.strictEqual(Object.hasOwn(payload, "inventory"), inventoryChanged || !hasSnapshot);
                assert.strictEqual(Object.hasOwn(payload, "root_equipment_editable"), inventoryChanged || !hasSnapshot);
                assert.strictEqual(Object.hasOwn(payload, "ender_chest"), enderChestChanged || !hasSnapshot);
                if (payload.inventory) assert.deepStrictEqual(JSON.parse(JSON.stringify(payload.inventory)), [inventory[0]]);
                if (payload.ender_chest) assert.deepStrictEqual(JSON.parse(JSON.stringify(payload.ender_chest)), [enderChestInventory[2]]);
                assert.deepStrictEqual(JSON.parse(JSON.stringify(payload.stats)), {health: 19});
                assert.strictEqual(JSON.stringify([inventory, enderChestInventory, cleanSnapshot]), before);
            }

            {
                const book = {slot:2, source_index:7, name:"minecraft:writable_book", count:1,
                    special_item:{kind:"book",editable:true,data:{pages:[]}}, nbt_view:{private:"presentation"},
                    special_edit:{kind:"book",data:{pages:[{text:"Nested page"}]}}};
                const container = {slot:0,name:"minecraft:bundle",count:1,source_item_digest:"parent-digest",
                    special_item:{kind:"bundle",editable:true,data:{items:[]}},
                    special_edit:{kind:"bundle",data:{items:[book]}}};
                const { logic } = makeLogic({inventory:{0:container}});
                const saved = logic.buildSavePayload().inventory[0];
                assert.strictEqual(saved.source_item_digest,"parent-digest");
                assert.strictEqual(saved.special_item,undefined);
                const child = saved.special_edit.data.items[0];
                assert.strictEqual(child.source_index,7);
                assert.strictEqual(child.special_item,undefined);
                assert.strictEqual(child.nbt_view,undefined);
                assert.strictEqual(child.special_edit.data.pages[0].text,"Nested page");
                assert(book.special_item && book.nbt_view, "serializing must not mutate the local draft");
            }

            {
                const { logic } = makeLogic({
                    cleanSnapshot: {
                        inv: { 0: { slot: 0, name: "minecraft:stone", count: 1, damage: 0 } },
                        ec: {},
                        stats: {},
                        effects: [],
                        abilities: {},
                    },
                    inventory: {
                        0: {
                            slot: 0,
                            name: "minecraft:stone",
                            count: 2,
                            damage: 0,
                            nbt_view: { display: "frontend-only" },
                            protected_nbt_summary: "summary",
                            preserved_nbt_summary: "summary",
                            protected_nbt_dropped: false,
                            previous_name: "minecraft:dirt",
                            special_nbt_defaulted: true,
                            special_nbt_requirement: "requires data",
                        },
                    },
                });
                const payload = logic.buildSavePayload();
                const expectedKeys = [
                    "base_revision", "inventory", "player_key", "root_equipment_editable",
                    "server_guard_epoch", "server_guard_token", "session_id", "stats", "world_path",
                ];
                assert.deepStrictEqual(Object.keys(payload).sort(), expectedKeys.sort());
                assert.strictEqual(payload.server_guard_epoch, 0);
                assert.strictEqual(payload.server_guard_token, "guard-token");
                assert.strictEqual(payload.root_equipment_editable, true);
                assert.strictEqual(payload.inventory.length, 1);
                assert.strictEqual(payload.inventory[0].count, 2);
                assert.strictEqual(Object.prototype.hasOwnProperty.call(payload.inventory[0], "nbt_view"), false);
                assert.strictEqual(Object.prototype.hasOwnProperty.call(payload.inventory[0], "protected_nbt_summary"), false);
                assert.deepStrictEqual(JSON.parse(JSON.stringify(payload.stats)), {});
            }

            {
                const { logic } = makeLogic({
                    cleanSnapshot: {
                        inv: {},
                        ec: { 2: { slot: 2, name: "minecraft:diamond", count: 1, damage: 0 } },
                        stats: {},
                        effects: [],
                        abilities: {},
                    },
                    enderChestInventory: {
                        2: { slot: 2, name: "minecraft:diamond", count: 3, damage: 0 },
                    },
                });
                const payload = logic.buildSavePayload();
                const expectedKeys = [
                    "base_revision", "ender_chest", "player_key", "server_guard_epoch", "server_guard_token",
                    "session_id", "stats", "world_path",
                ];
                assert.deepStrictEqual(Object.keys(payload).sort(), expectedKeys.sort());
                assert.strictEqual(payload.ender_chest.length, 1);
                assert.strictEqual(payload.ender_chest[0].count, 3);
                assert.strictEqual(Object.prototype.hasOwnProperty.call(payload, "inventory"), false);
                assert.strictEqual(Object.prototype.hasOwnProperty.call(payload, "effects"), false);
                assert.strictEqual(Object.prototype.hasOwnProperty.call(payload, "abilities"), false);
            }

            {
                const { logic } = makeLogic({
                    cleanSnapshot: {
                        inv: {},
                        ec: {},
                        stats: { health: 20, pos: [1, 2, 3], xp_level: 5 },
                        effects: [],
                        abilities: {},
                    },
                    playerStats: { health: "18", pos: [1, "2", 4], xp_level: 5, food_level: 20 },
                    protectedStats: new Set(["food_level"]),
                });
                const payload = logic.buildSavePayload();
                assert.deepStrictEqual(JSON.parse(JSON.stringify(payload.stats)), { health: "18", pos: [1, "2", 4] });
                assert.strictEqual(Object.prototype.hasOwnProperty.call(payload, "inventory"), false);
                assert.strictEqual(Object.prototype.hasOwnProperty.call(payload, "ender_chest"), false);
            }

            {
                const { logic } = makeLogic({
                    cleanSnapshot: {
                        inv: {},
                        ec: {},
                        stats: { pos: [80, 70, -40], dimension_id: 0 },
                        effects: [],
                        abilities: {},
                    },
                    playerStats: { pos: [80, 70, -40], dimension_id: 1 },
                });
                assert.deepStrictEqual(
                    JSON.parse(JSON.stringify(logic.buildChangedStatsPayload())),
                    { pos: [80, 70, -40], dimension_id: 1 },
                );
            }

            {
                const { logic } = makeLogic({
                    cleanSnapshot: {
                        inv: {},
                        ec: {},
                        stats: { pos: [80, 70, -40], dimension_id: null },
                        effects: [],
                        abilities: {},
                    },
                    playerStats: { pos: [81, 70, -40], dimension_id: null },
                });
                assert.deepStrictEqual(
                    JSON.parse(JSON.stringify(logic.buildChangedStatsPayload())),
                    { pos: [81, 70, -40] },
                );
            }

            {
                const { logic } = makeLogic({
                    cleanSnapshot: {
                        inv: {},
                        ec: {},
                        stats: { pos: [80, 70, -40], dimension_id: 0 },
                        effects: [],
                        abilities: {},
                    },
                    playerStats: { pos: [81, 70, -40], dimension_id: 0 },
                });
                assert.deepStrictEqual(
                    JSON.parse(JSON.stringify(logic.buildChangedStatsPayload())),
                    { pos: [81, 70, -40], dimension_id: 0 },
                );
            }

            {
                const { logic } = makeLogic({
                    cleanSnapshot: { inv: {}, ec: {}, stats: {}, effects: [], abilities: {} },
                    playerEffects: [{ id: 1, amplifier: 0 }],
                    effectsTouched: true,
                    protectedNbt: { active_effects_opaque: true },
                });
                const payload = logic.buildSavePayload();
                assert.strictEqual(Object.prototype.hasOwnProperty.call(payload, "effects"), false);
            }

            {
                const { logic, state } = makeLogic({
                    cleanSnapshot: { inv: {}, ec: {}, stats: {}, effects: [{ id: 1, amplifier: 0 }], abilities: {} },
                    playerEffects: [{ id: 1, amplifier: 0 }],
                    protectedNbt: { has_active_effects_tag: true },
                });
                const payload = logic.buildSavePayload();
                assert.strictEqual(state.syncEffectsCount, 1);
                assert.strictEqual(Object.prototype.hasOwnProperty.call(payload, "effects"), false);
            }

            {
                const { logic, state } = makeLogic({
                    cleanSnapshot: { inv: {}, ec: {}, stats: {}, effects: [], abilities: {} },
                    playerEffects: [{ id: 1, amplifier: 0 }],
                    protectedNbt: { active_effects_opaque: true, has_active_effects_tag: true },
                });
                const payload = logic.buildSavePayload();
                assert.strictEqual(state.syncEffectsCount, 0);
                assert.strictEqual(Object.prototype.hasOwnProperty.call(payload, "effects"), false);
            }

            {
                const { logic, state } = makeLogic({
                    cleanSnapshot: { inv: {}, ec: {}, stats: {}, effects: [], abilities: { mayfly: false } },
                    playerAbilities: { mayfly: false },
                    abilitiesTouched: false,
                    collectedAbilities: { mayfly: true },
                });
                let payload = logic.buildSavePayload();
                assert.strictEqual(Object.prototype.hasOwnProperty.call(payload, "abilities"), false);
                assert.strictEqual(state.collectAbilitiesCount, 0);

                state.abilitiesTouched = true;
                payload = logic.buildSavePayload();
                assert.deepStrictEqual(JSON.parse(JSON.stringify(payload.abilities)), { mayfly: true });
                assert.strictEqual(state.collectAbilitiesCount, 1);
            }

            {
                const { logic, state } = makeLogic({
                    cleanSnapshot: { inv: {}, ec: {}, stats: {}, effects: [], abilities: { mayfly: false } },
                    playerAbilities: { mayfly: false },
                    abilitiesTouched: true,
                    collectedAbilities: { mayfly: true },
                    protectedNbt: { abilities_opaque: true },
                });
                const payload = logic.buildSavePayload();
                assert.strictEqual(Object.prototype.hasOwnProperty.call(payload, "abilities"), false);
                assert.strictEqual(state.collectAbilitiesCount, 0);
            }

            {
                const { logic, state } = makeLogic({
                    cleanSnapshot: { inv: {}, ec: {}, stats: {}, effects: [], abilities: { mayfly: false } },
                    playerAbilities: { mayfly: false },
                    abilitiesTouched: true,
                    collectedAbilities: null,
                });
                const payload = logic.buildSavePayload();
                assert.strictEqual(Object.prototype.hasOwnProperty.call(payload, "abilities"), false);
                assert.strictEqual(state.collectAbilitiesCount, 1);
            }

            {
                const protectedItem = {
                    slot: 5,
                    name: "minecraft:filled_map",
                    count: 1,
                    damage: 0,
                    has_protected_nbt: true,
                    nbt_view: { map_uuid: "abc" },
                };
                const { logic } = makeLogic({
                    cleanSnapshot: {
                        inv: { 5: protectedItem },
                        ec: {},
                        stats: {},
                        effects: [],
                        abilities: {},
                    },
                    inventory: {
                        8: {
                            slot: 8,
                            name: "minecraft:filled_map",
                            count: 1,
                            damage: 0,
                            has_protected_nbt: true,
                            nbt_view: { map_uuid: "abc" },
                        },
                    },
                });
                const payload = logic.buildSavePayload();
                assert.strictEqual(payload.inventory[0].source_container, "inventory");
                assert.strictEqual(payload.inventory[0].source_slot, 5);
                assert.strictEqual(payload.inventory[0].source_player_key, "local_player");
                assert.strictEqual(payload.inventory[0].source_world_path, "C:/World");
                assert.strictEqual(Object.prototype.hasOwnProperty.call(payload.inventory[0], "nbt_view"), false);
            }

            {
                const cleanItem = {
                    slot: 5,
                    name: "minecraft:filled_map",
                    count: 1,
                    damage: 0,
                    has_protected_nbt: true,
                    source_item_digest: "a".repeat(64),
                    nbt_view: { map_uuid: "truncated-view" },
                };
                const { logic } = makeLogic({
                    cleanSnapshot: {
                        inv: { 5: cleanItem },
                        ec: {},
                        stats: {},
                        effects: [],
                        abilities: {},
                    },
                    inventory: {
                        8: {
                            slot: 8,
                            name: "minecraft:filled_map",
                            count: 1,
                            damage: 0,
                            has_protected_nbt: true,
                            source_item_digest: "b".repeat(64),
                            nbt_view: { map_uuid: "truncated-view" },
                        },
                    },
                });
                const payload = logic.buildSavePayload();
                assert.strictEqual(Object.prototype.hasOwnProperty.call(payload.inventory[0], "source_slot"), false);
                assert.strictEqual(payload.inventory[0].source_item_digest, "b".repeat(64));
            }

            {
                const digest = "c".repeat(64);
                const cleanItem = {
                    slot: 5,
                    name: "minecraft:filled_map",
                    count: 1,
                    damage: 0,
                    has_protected_nbt: true,
                    source_item_digest: digest,
                };
                const { logic } = makeLogic({
                    cleanSnapshot: {
                        inv: { 5: cleanItem },
                        ec: {},
                        stats: {},
                        effects: [],
                        abilities: {},
                    },
                    inventory: {
                        8: {
                            slot: 8,
                            name: "minecraft:filled_map",
                            count: 1,
                            damage: 0,
                            has_protected_nbt: true,
                            source_item_digest: digest,
                        },
                    },
                });
                const payload = logic.buildSavePayload();
                assert.strictEqual(payload.inventory[0].source_container, "inventory");
                assert.strictEqual(payload.inventory[0].source_slot, 5);
                assert.strictEqual(payload.inventory[0].source_player_key, "local_player");
                assert.strictEqual(payload.inventory[0].source_item_digest, digest);
            }

            {
                const { logic } = makeLogic({
                    cleanSnapshot: {
                        inv: { 0: { slot: 0, name: "minecraft:filled_map", count: 1, damage: 0, has_protected_nbt: true } },
                        ec: {},
                        stats: {},
                        effects: [],
                        abilities: {},
                    },
                    inventory: {
                        0: {
                            slot: 0,
                            name: "minecraft:filled_map",
                            count: 2,
                            damage: 0,
                            has_protected_nbt: true,
                            source_container: "inventory",
                            source_slot: 7,
                            source_player_key: "external_player",
                            source_world_path: "D:/OtherWorld",
                            nbt_view: { map_uuid: "external" },
                        },
                    },
                });
                const payload = logic.buildSavePayload();
                assert.strictEqual(payload.inventory[0].source_container, "inventory");
                assert.strictEqual(payload.inventory[0].source_slot, 7);
                assert.strictEqual(payload.inventory[0].source_player_key, "external_player");
                assert.strictEqual(payload.inventory[0].source_world_path, "D:/OtherWorld");
                assert.strictEqual(Object.prototype.hasOwnProperty.call(payload.inventory[0], "nbt_view"), false);
            }

            {
                const { logic } = makeLogic({
                    cleanSnapshot: {
                        inv: { 1: { slot: 1, name: "minecraft:filled_map", count: 1, damage: 0, has_protected_nbt: true } },
                        ec: { 2: { slot: 2, name: "minecraft:filled_map", count: 1, damage: 0, has_protected_nbt: true } },
                        stats: {},
                        effects: [],
                        abilities: {},
                    },
                    inventory: {
                        5: { slot: 5, name: "minecraft:filled_map", count: 1, damage: 0, has_protected_nbt: true },
                    },
                });
                const payload = logic.buildSavePayload();
                assert.strictEqual(Object.prototype.hasOwnProperty.call(payload.inventory[0], "source_container"), false);
                assert.strictEqual(Object.prototype.hasOwnProperty.call(payload.inventory[0], "source_slot"), false);
                assert.strictEqual(Object.prototype.hasOwnProperty.call(payload.inventory[0], "source_player_key"), false);
                assert.strictEqual(Object.prototype.hasOwnProperty.call(payload.inventory[0], "source_world_path"), false);
            }

            {
                const { logic } = makeLogic();
                const payload = logic.buildSavePayload();
                assert.strictEqual(logic.payloadContainsUserChanges(payload), false);
                assert.strictEqual(context.window.MCBESavePayloadLogic.payloadContainsUserChanges({ stats: { health: 19 } }), true);
            }
            """
        )
    )


def test_frontend_save_validation_keeps_pending_mount_risks_without_generic_notices() -> None:
    run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/save_logic.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/save_logic.js" });

            let stats = { pos: [10, 70, -5], dimension_id: 1 };
            const mount = {mountLabel:"Pferd", selectedPosition:{x:1,y:64,z:2}, safetyStatus:"safe"};
            const logic = context.window.MCBESaveLogic.createSaveLogic({
                buildChangedStatsPayload: () => stats,
                getPendingMounts: () => [mount],
                getInventory: () => ({}),
                getEnderChestInventory: () => ({}),
                getHasEnderChest: () => true,
                getCreateRequiresConfirmation: () => ({}),
                getPlayerEffects: () => [],
                getPlayerAbilities: () => ({}),
                itemIsVisiblePresent: () => false,
                hasMeaningfulObjectKeys: () => false,
            });

            const validation = logic.validateInventoryState({ limit: 20 });
            assert.strictEqual(validation.errors, 1);
            assert.ok(validation.shown.some(issue => issue.label.includes("nicht gemeinsam gespeichert")));
            assert.strictEqual(validation.infos, 0);

            stats = {};
            assert.strictEqual(logic.validateInventoryState().total, 0, "Sicher geprüfte Mounts brauchen keinen Zusatzhinweis");
            mount.safetyStatus = "unchecked";
            const unchecked = logic.validateInventoryState();
            assert.strictEqual(unchecked.warnings, 1);
            assert.ok(unchecked.shown[0].label.includes("erneut serverseitig bewertet"));
            mount.selectedPosition.x = "invalid";
            const invalid = logic.validateInventoryState();
            assert.strictEqual(invalid.errors, 1);
            assert.ok(invalid.shown[0].label.includes("Position ist ungültig"));
            """
        )
    )


def test_frontend_change_summary_rounds_float32_mount_positions() -> None:
    run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/save_logic.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/save_logic.js" });

            // The server sends the exact Float32 values it will store.
            const logic = context.window.MCBESaveLogic.createSaveLogic({
                getPendingMounts: () => [{
                    mountLabel: "Pferd",
                    selectedPosition: { x: 101.30000305175781, y: 64, z: -5.699999809265137 },
                    safetyStatus: "safe",
                }],
                getCleanSnapshot: () => ({ inv: {}, ec: {} }),
                takeSnapshot: () => ({ inv: {}, ec: {} }),
            });

            const labels = logic.buildChangeSummary({ includeSections: false }).shown.map(change => change.label);
            assert.strictEqual(labels.length, 1);
            assert.strictEqual(labels[0], "Pferd wird bei 101.30 / 64 / -5.70 erzeugt (sicher geprüft).");
            """
        )
    )
