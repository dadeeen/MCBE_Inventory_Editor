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


def test_frontend_enchantment_editor_logic_rows_and_counts() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/enchantment_editor_logic.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/enchantment_editor_logic.js" });

            const logic = context.window.MCBEEnchantmentEditorLogic;
            const db = {
                1: { name_de: "Schärfe", max_lvl: 5 },
                2: { name_de: "Bann", max_lvl: 4 },
                3: { name_de: "Unpassend", max_lvl: 2 },
            };
            const compatible = id => id !== 3;
            assert.strictEqual(logic.countMaxableEnchantments({
                enchantments: [{ id: 1, lvl: 2 }, { id: 2, lvl: 4 }, { id: 3, lvl: 1 }],
                itemName: "minecraft:sword",
                enchantmentsDb: db,
                isCompatible: compatible,
            }), 1);

            const rows = logic.enchantmentRowsForItem({
                enchantmentsDb: db,
                itemName: "minecraft:sword",
                activeEnchantments: [{ id: 3, lvl: 1 }],
                isCompatible: compatible,
            });
            assert.deepStrictEqual(JSON.parse(JSON.stringify(rows.map(row => ({
                id: row.id,
                active: Boolean(row.activeEnchantment),
                compatible: row.compatible,
            })))), [
                { id: 2, active: false, compatible: true },
                { id: 1, active: false, compatible: true },
                { id: 3, active: true, compatible: false },
            ]);
            """
        )
    )


def test_frontend_enchantment_editor_logic_sorts_by_active_locale() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: { MCBEI18n: {
                locale: "en",
                localizedPair: (de, en) => ({ primary: en || "", secondary: "" }),
                compare: (a, b) => a.localeCompare(b, "en", { sensitivity: "base" }),
            } } };
            vm.runInNewContext(fs.readFileSync("static/enchantment_editor_logic.js", "utf8"), context, {
                filename: "static/enchantment_editor_logic.js",
            });

            const rows = context.window.MCBEEnchantmentEditorLogic.enchantmentRowsForItem({
                enchantmentsDb: {
                    1: { name_de: "Aqua-Affinität", name_en: "Aqua Affinity" },
                    2: { name_de: "Bann", name_en: "Smite" },
                    3: { name_de: "Schärfe", name_en: "Sharpness" },
                },
                itemName: "minecraft:sword",
                isCompatible: () => true,
            });
            assert.deepStrictEqual(JSON.parse(JSON.stringify(rows.map(row => row.id))), [1, 3, 2]);
            """
        )
    )


def test_frontend_enchantment_editor_logic_updates_toggles_and_maxes() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/enchantment_editor_logic.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/enchantment_editor_logic.js" });

            const logic = context.window.MCBEEnchantmentEditorLogic;
            assert.deepStrictEqual(JSON.parse(JSON.stringify(logic.updateEnchantmentLevel(
                [{ id: 1, lvl: 1 }, { id: 2, lvl: 3 }],
                1,
                "4",
            ))), [{ id: 1, lvl: 4 }, { id: 2, lvl: 3 }]);
            assert.deepStrictEqual(JSON.parse(JSON.stringify(logic.toggleEnchantment(
                [{ id: 1, lvl: 1 }],
                { id: 2, checked: true, level: "3" },
            ))), [{ id: 1, lvl: 1 }, { id: 2, lvl: 3 }]);
            assert.deepStrictEqual(JSON.parse(JSON.stringify(logic.toggleEnchantment(
                [{ id: 1, lvl: 1 }, { id: 2, lvl: 3 }],
                { id: 1, checked: false },
            ))), [{ id: 2, lvl: 3 }]);

            const plan = logic.maxAllEnchantmentsPlan({
                itemName: "minecraft:sword",
                enchantments: [{ id: 1, lvl: 1 }, { id: 2, lvl: 4 }],
                enchantmentsDb: { 1: { max_lvl: 5 }, 2: { max_lvl: 4 } },
                isEnchantableItem: () => true,
                isCompatible: () => true,
            });
            assert.strictEqual(plan.ok, true);
            assert.strictEqual(plan.changed, 1);
            assert.deepStrictEqual(JSON.parse(JSON.stringify(plan.enchantments)), [{ id: 1, lvl: 5 }, { id: 2, lvl: 4 }]);
            assert.strictEqual(plan.toast, null);

            const blocked = logic.maxAllEnchantmentsPlan({
                itemName: "minecraft:stone",
                enchantments: [{ id: 1, lvl: 1 }],
                isEnchantableItem: () => false,
            });
            assert.strictEqual(blocked.ok, false);
            assert.strictEqual(blocked.toast.message, "Dieses Item ist nach Vanilla-Regeln nicht verzauberbar.");
            """
        )
    )


def test_frontend_enchantment_editor_logic_manual_reset_plan() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/enchantment_editor_logic.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/enchantment_editor_logic.js" });

            const logic = context.window.MCBEEnchantmentEditorLogic;
            assert.deepStrictEqual(JSON.parse(JSON.stringify(logic.manualItemResetPlan({
                previousName: "minecraft:stone",
                nextName: " minecraft:diamond_sword ",
                lastResetName: "",
                isValidItemId: () => true,
            }))), { shouldReset: true, nextName: "minecraft:diamond_sword" });
            assert.deepStrictEqual(JSON.parse(JSON.stringify(logic.manualItemResetPlan({
                previousName: "minecraft:stone",
                nextName: "minecraft:stone",
                isValidItemId: () => true,
            }))), { shouldReset: false });
            assert.deepStrictEqual(JSON.parse(JSON.stringify(logic.manualItemResetPlan({
                previousName: "minecraft:stone",
                nextName: "minecraft:diamond_sword",
                lastResetName: "minecraft:diamond_sword",
                isValidItemId: () => true,
            }))), { shouldReset: false });
            """
        )
    )
