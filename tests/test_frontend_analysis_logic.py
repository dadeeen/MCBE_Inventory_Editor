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


def test_frontend_analysis_logic_counts_only_repairable_damage_as_damaged() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/analysis_logic.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/analysis_logic.js" });

            const inventory = {
                0: { name: "minecraft:potion", count: 1, damage: 20 },
                1: { name: "minecraft:iron_pickaxe", count: 1, damage: 4 },
                2: { name: "minecraft:stone", count: 64, damage: 2 },
            };
            const enderChestInventory = {
                0: { name: "minecraft:splash_potion", count: 1, damage: 25 },
            };
            const isVisible = item => !!(item && item.name && item.name !== "minecraft:air" && Number(item.count || 0) > 0);
            const logic = context.window.MCBEAnalysisLogic.createAnalysisLogic({
                appConfig: {},
                currentPlayerLabel: () => "Alex",
                firstEmptyWritableSlot: () => 3,
                getCurrentCompatibility: () => ({}),
                getEnderChestInventory: () => enderChestInventory,
                getHasEnderChest: () => true,
                getHiddenUnknownSlots: () => ({}),
                getInventory: () => inventory,
                getPlayers: () => [],
                getProtectedKnownSlots: () => ({}),
                getProtectedNbt: () => ({}),
                getSelectedWorld: () => ({ name: "Welt" }),
                getWorldName: () => "Welt",
                getWorldPath: () => "world",
                inventorySlotCount: 36,
                enderChestSlotCount: 27,
                isKnownItemId: () => true,
                itemIsVisiblePresent: isVisible,
                itemHasRepairableDamage: item => isVisible(item)
                    && item.name === "minecraft:iron_pickaxe"
                    && Number(item.damage || 0) > 0,
                maxDamage: () => ({ "minecraft:iron_pickaxe": 250 }),
                protectedAbilityFields: () => ({}),
                protectedStatFields: () => ({}),
                getCreateRequiresConfirmation: () => ({}),
            });

            assert.strictEqual(logic.getInventoryStatsForMap(inventory).damaged, 1);
            assert.strictEqual(logic.getInventoryStatsForMap(enderChestInventory).damaged, 0);
            assert.strictEqual(logic.buildInventorySummary().damaged, 1);
            assert.strictEqual(logic.buildWorldAnalysis().inventory.damaged, 1);
            """
        )
    )


def test_analysis_logic_keeps_world_notes_informational() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/analysis_logic.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/analysis_logic.js" });

            const preservedNote = "Zusätzliche Weltdateien/-ordner vorhanden; sie werden nicht verändert.";
            const logic = context.window.MCBEAnalysisLogic.createAnalysisLogic({
                appConfig: { distribution: { project_version: "test" }, mode: "test" },
                currentPlayerLabel: () => "Alex",
                firstEmptyWritableSlot: () => 0,
                getCurrentCompatibility: () => ({
                    player: { warnings: [], notes: ["Player note"] },
                    world: { status: "ok", warnings: [], notes: ["World note", preservedNote], errors: [] },
                }),
                getEnderChestInventory: () => ({}),
                getHasEnderChest: () => false,
                getHiddenUnknownSlots: () => ({}),
                getInventory: () => ({}),
                getPlayers: () => [],
                getProtectedNbt: () => ({}),
                getProtectedKnownSlots: () => ({}),
                getSelectedWorld: () => ({ name: "Welt" }),
                getWorldName: () => "Welt",
                getWorldPath: () => "/world",
                inventorySlotCount: 36,
                enderChestSlotCount: 27,
                isKnownItemId: () => true,
                itemIsVisiblePresent: () => false,
                maxDamage: () => ({}),
                protectedAbilityFields: () => ({}),
                protectedStatFields: () => ({}),
                getCreateRequiresConfirmation: () => ({}),
            });

            assert.deepStrictEqual(logic.currentCompatibilityWarnings(), []);
            assert.ok(logic.currentCompatibilityNotes().includes(preservedNote));
            assert.strictEqual(logic.compatibilitySummaryText(), "");

            const analysis = logic.buildWorldAnalysis();
            assert.deepStrictEqual(analysis.compat_warnings, []);
            assert.ok(analysis.compat_notes.includes(preservedNote));
            assert.ok(logic.worldAnalysisText().includes("Erhaltene Zusatzdaten:"));
            assert.ok(!logic.worldAnalysisText().includes("Kompatibilitätswarnungen:"));
            """
        )
    )


def test_analysis_logic_keeps_real_world_warnings_as_warnings() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/analysis_logic.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/analysis_logic.js" });

            const realWarning = "level.dat wurde nicht gefunden. Spieler-Inventare können trotzdem lesbar sein, aber die Weltstruktur wirkt unvollständig.";
            const logic = context.window.MCBEAnalysisLogic.createAnalysisLogic({
                appConfig: { distribution: { project_version: "test" }, mode: "test" },
                currentPlayerLabel: () => "Alex",
                firstEmptyWritableSlot: () => 0,
                getCurrentCompatibility: () => ({
                    player: { warnings: [], notes: [] },
                    world: { warnings: [realWarning], notes: [], errors: [] },
                }),
                getEnderChestInventory: () => ({}),
                getHasEnderChest: () => false,
                getHiddenUnknownSlots: () => ({}),
                getInventory: () => ({}),
                getPlayers: () => [],
                getProtectedNbt: () => ({}),
                getProtectedKnownSlots: () => ({}),
                getSelectedWorld: () => ({ name: "Welt" }),
                getWorldName: () => "Welt",
                getWorldPath: () => "/world",
                inventorySlotCount: 36,
                enderChestSlotCount: 27,
                isKnownItemId: () => true,
                itemIsVisiblePresent: () => false,
                maxDamage: () => ({}),
                protectedAbilityFields: () => ({}),
                protectedStatFields: () => ({}),
                getCreateRequiresConfirmation: () => ({}),
            });

            assert.deepStrictEqual(logic.currentCompatibilityWarnings(), [realWarning]);
            assert.deepStrictEqual(logic.currentCompatibilityNotes(), []);
            assert.strictEqual(logic.compatibilitySummaryText(), "1 Kompatibilitätshinweis(e)");
            assert.ok(logic.buildWorldAnalysis().compat_warnings.includes(realWarning));
            assert.ok(logic.worldAnalysisText().includes("Kompatibilitätswarnungen:"));
            """
        )
    )
