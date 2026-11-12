import textwrap

from tests.node_runner import run_node


def test_villager_career_save_summary_includes_before_after_and_trade_reset_impact() -> None:
    run_node(r"""
        const assert = require("node:assert/strict");
        const fs = require("fs");
        const vm = require("vm");
        const context = { window: {} };
        for (const file of ["villager_model", "save_logic"]) {
            vm.runInNewContext(fs.readFileSync(`static/${file}.js`, "utf8"), context);
        }
        const snapshot = { inv: {}, ec: {}, stats: {}, effects: [], abilities: {} };
        const row = {
            kind: "career", label: "Händler <&>",
            before: { profession: "librarian", profession_label: "Bibliothekar", trade_tier: 4, trade_tier_label: "Meister" },
            after: { profession: "farmer", profession_label: "Farmer", trade_tier: 0, trade_tier_label: "Neuling" },
            warnings: ["Bisherige Handelsangebote werden zurückgesetzt."],
        };
        const logic = context.window.MCBESaveLogic.createSaveLogic({
            getCleanSnapshot: () => snapshot,
            takeSnapshot: () => snapshot,
            sectionChanged: () => false,
            getHasEditablePlayer: () => false,
            getPendingVillagers: () => [{ rows: [row] }],
        });
        const summary = logic.buildChangeSummary();
        assert.equal(summary.total, 1);
        const label = summary.shown[0].label;
        assert.match(label, /Händler <&>.*Beruf und Handelsstufe/);
        assert.match(label, /Bibliothekar.*Meister.*→.*Farmer.*Neuling/);
        assert.ok(label.includes(row.warnings[0]));
        row.after = { profession: "librarian", profession_label: "Bibliothekar", trade_tier: 2, trade_tier_label: "Geselle" };
        delete row.warnings;
        assert.match(logic.buildChangeSummary().shown[0].label, /Bibliothekar.*Geselle/);
        assert.ok(!logic.buildChangeSummary().shown[0].label.includes("zurückgesetzt"));
    """)


def test_save_validation_rejects_enchantment_levels_above_backend_maximum() -> None:
    run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {} };
            vm.runInNewContext(fs.readFileSync("static/save_logic.js", "utf8"), context, {
                filename: "static/save_logic.js",
            });

            const logic = context.window.MCBESaveLogic.createSaveLogic({
                getEnchantmentsDb: () => ({
                    9: { name_de: "Schärfe", name_en: "Sharpness", max_lvl: 5 },
                }),
                getMaxDamage: () => 1561,
                getMaxStack: () => 1,
                isKnownItemId: () => true,
                isValidItemId: () => true,
                maxBedrockStackCount: 127,
                slotDisplayName: slot => `Slot ${slot}`,
            });
            const item = {
                slot: 0,
                name: "minecraft:diamond_sword",
                count: 1,
                damage: 0,
                enchantments: [{ id: 9, lvl: 6 }],
            };

            const invalid = logic.validateItemInSlot(item, 0, "inventory");
            assert.ok(invalid.some(issue => issue.level === "error" && issue.label.includes("Verzauberungslevel")));

            item.enchantments[0].lvl = 5;
            const valid = logic.validateItemInSlot(item, 0, "inventory");
            assert.strictEqual(valid.filter(issue => issue.level === "error").length, 0);

            const opaqueTagEdit = logic.validateItemInSlot({
                ...item,
                display_name: "Neuer Name",
                item_tag_opaque: true,
            }, 0, "inventory");
            assert.ok(opaqueTagEdit.some(issue =>
                issue.level === "error" && issue.label.includes("unbekannten NBT-Typ")
            ));
            """
        )
    )


def test_save_validation_rejects_duplicate_or_unknown_enchantments() -> None:
    run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {} };
            vm.runInNewContext(fs.readFileSync("static/save_logic.js", "utf8"), context, {
                filename: "static/save_logic.js",
            });

            const logic = context.window.MCBESaveLogic.createSaveLogic({
                getEnchantmentsDb: () => ({ 9: { max_lvl: 5 } }),
                getMaxDamage: () => 1561,
                getMaxStack: () => 1,
                isKnownItemId: () => true,
                isValidItemId: () => true,
                maxBedrockStackCount: 127,
                slotDisplayName: slot => `Slot ${slot}`,
            });
            const base = {
                slot: 0,
                name: "minecraft:diamond_sword",
                count: 1,
                damage: 0,
            };

            const duplicate = logic.validateItemInSlot({
                ...base,
                enchantments: [{ id: 9, lvl: 1 }, { id: 9, lvl: 2 }],
            }, 0, "inventory");
            assert.ok(duplicate.some(issue => issue.level === "error"));

            const unknown = logic.validateItemInSlot({
                ...base,
                enchantments: [{ id: 999, lvl: 1 }],
            }, 0, "inventory");
            assert.ok(unknown.some(issue => issue.level === "error"));
            """
        )
    )


def test_save_validation_allows_only_unchanged_original_values_outside_catalog_limits() -> None:
    run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {} };
            vm.runInNewContext(fs.readFileSync("static/save_logic.js", "utf8"), context, {
                filename: "static/save_logic.js",
            });

            const cleanSnapshot = {
                inv: {
                    0: {
                        slot: 0,
                        name: "minecraft:diamond_sword",
                        count: 1,
                        damage: 9999,
                    },
                    1: {
                        slot: 1,
                        name: "minecraft:bed",
                        count: 64,
                        damage: 0,
                    },
                },
                ec: {},
            };
            const logic = context.window.MCBESaveLogic.createSaveLogic({
                getCleanSnapshot: () => cleanSnapshot,
                getEnchantmentsDb: () => ({}),
                getMaxDamage: name => name === "minecraft:diamond_sword" ? 1561 : 0,
                getMaxStack: name => name === "minecraft:bed" ? 1 : 64,
                isKnownItemId: () => true,
                isValidItemId: () => true,
                maxBedrockStackCount: 127,
                slotDisplayName: slot => `Slot ${slot}`,
            });
            const errors = issues => issues.filter(issue => issue.level === "error");

            const unchangedDamage = logic.validateItemInSlot({
                slot: 0,
                source_slot: 0,
                source_container: "inventory",
                name: "minecraft:diamond_sword",
                count: 1,
                damage: 9999,
                enchantments: [],
            }, 0, "inventory");
            assert.strictEqual(errors(unchangedDamage).length, 0);

            const changedDamage = logic.validateItemInSlot({
                slot: 0,
                source_slot: 0,
                source_container: "inventory",
                name: "minecraft:diamond_sword",
                count: 1,
                damage: 8888,
                enchantments: [],
            }, 0, "inventory");
            assert.ok(errors(changedDamage).some(issue => issue.label.includes("Abnutzung")));

            const movedUnchangedOverstack = logic.validateItemInSlot({
                slot: 5,
                source_slot: 1,
                source_container: "inventory",
                name: "minecraft:bed",
                count: 64,
                damage: 0,
                enchantments: [],
            }, 5, "inventory");
            assert.strictEqual(errors(movedUnchangedOverstack).length, 0);

            const changedOverstack = logic.validateItemInSlot({
                slot: 5,
                source_slot: 1,
                source_container: "inventory",
                name: "minecraft:bed",
                count: 32,
                damage: 0,
                enchantments: [],
            }, 5, "inventory");
            assert.ok(errors(changedOverstack).some(issue => issue.label.includes("Stacklimit")));

            const impossibleCount = logic.validateItemInSlot({
                slot: 5,
                source_slot: 1,
                source_container: "inventory",
                name: "minecraft:bed",
                count: 128,
                damage: 0,
                enchantments: [],
            }, 5, "inventory");
            assert.ok(errors(impossibleCount).some(issue => issue.label.includes("1 bis 127")));
            """
        )
    )
