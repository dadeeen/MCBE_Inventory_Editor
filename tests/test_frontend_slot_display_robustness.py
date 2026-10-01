import textwrap

from tests.node_runner import run_node


def test_item_display_name_tolerates_null_options() -> None:
    run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/slot_display.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/slot_display.js" });

            const display = context.window.MCBESlotDisplay;
            const item = { name: "minecraft:diamond_pickaxe", count: 1, damage: 13 };

            assert.strictEqual(
                display.itemDisplayName(item, () => "Diamantspitzhacke", () => "Abnutzung", null),
                "Diamantspitzhacke x1 · Abnutzung 13",
            );
            assert.strictEqual(
                display.itemDisplayName(item, () => "Diamantspitzhacke", () => "Abnutzung", { includeDamage: false }),
                "Diamantspitzhacke x1",
            );
            """
        )
    )
