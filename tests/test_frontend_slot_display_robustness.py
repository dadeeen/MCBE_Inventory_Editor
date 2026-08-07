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


def test_item_display_name_tolerates_null_options() -> None:
    _run_node(
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
