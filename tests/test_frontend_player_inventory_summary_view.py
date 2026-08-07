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


def test_frontend_player_inventory_summary_view_formats_loaded_and_empty_states() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/player_inventory_summary_view.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/player_inventory_summary_view.js" });

            const view = context.window.MCBEPlayerInventorySummaryView;
            const hidden = view.playerInventorySummaryModel({
                worldPath: "",
                currentPlayer: null,
                playerLabel: "",
                summary: null,
            });
            assert.strictEqual(hidden.visible, false);
            assert.strictEqual(hidden.summary, null);
            assert.strictEqual(hidden.inventoryText, "");

            const summary = {
                inventoryUsed: 12,
                inventoryTotal: 36,
                enderUsed: 4,
                enderTotal: 27,
                damaged: 3,
            };
            const loaded = view.playerInventorySummaryModel({
                worldPath: "C:/World",
                currentPlayer: { label: "Alex" },
                playerLabel: "Alex",
                summary,
            });
            assert.strictEqual(loaded.visible, true);
            assert.strictEqual(loaded.summary, summary);
            assert.strictEqual(loaded.playerName, "Alex");
            assert.strictEqual(loaded.inventoryText, "Inventar 12/36");
            assert.strictEqual(loaded.enderText, "Enderchest 4/27");
            assert.strictEqual(loaded.damagedText, "3 beschädigt");
            assert.strictEqual(loaded.enderMetaText, "4 / 27 belegt");
            """
        )
    )


def test_frontend_player_inventory_summary_view_applies_dom_model() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/player_inventory_summary_view.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/player_inventory_summary_view.js" });

            const view = context.window.MCBEPlayerInventorySummaryView;
            const elements = {
                container: { style: { display: "" } },
                playerName: { textContent: "" },
                inventoryBadge: { textContent: "" },
                enderBadge: { textContent: "" },
                damagedBadge: { textContent: "" },
                enderMeta: { textContent: "" },
            };

            const visible = view.applyPlayerInventorySummaryModel(elements, {
                visible: true,
                playerName: "Alex",
                inventoryText: "Inventar 12/36",
                enderText: "Enderchest 4/27",
                damagedText: "3 beschädigt",
                enderMetaText: "4 / 27 belegt",
            });
            assert.strictEqual(visible, true);
            assert.strictEqual(elements.container.style.display, "flex");
            assert.strictEqual(elements.playerName.textContent, "Alex");
            assert.strictEqual(elements.inventoryBadge.textContent, "Inventar 12/36");
            assert.strictEqual(elements.enderBadge.textContent, "Enderchest 4/27");
            assert.strictEqual(elements.damagedBadge.textContent, "3 beschädigt");
            assert.strictEqual(elements.enderMeta.textContent, "4 / 27 belegt");

            const hidden = view.applyPlayerInventorySummaryModel(elements, { visible: false });
            assert.strictEqual(hidden, false);
            assert.strictEqual(elements.container.style.display, "none");
            """
        )
    )
