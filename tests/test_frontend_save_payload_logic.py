import subprocess
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run_node(source: str) -> None:
    result = subprocess.run(
        ["node", "-e", source],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout


def test_frontend_save_payload_logic_builds_delta_sections() -> None:
    _run_node(
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
                    itemRequiresOriginalNbt: item => Boolean(item && (item.has_protected_nbt || item.has_preserved_nbt || item.requires_original_nbt)),
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


def test_frontend_save_validation_blocks_location_change_with_pending_mount() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/save_logic.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/save_logic.js" });

            const logic = context.window.MCBESaveLogic.createSaveLogic({
                buildChangedStatsPayload: () => ({ pos: [10, 70, -5], dimension_id: 1 }),
                getPendingMounts: () => [{
                    mountLabel: "Pferd",
                    selectedPosition: { x: 1, y: 64, z: 2 },
                    safetyStatus: "safe",
                }],
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
            """
        )
    )
