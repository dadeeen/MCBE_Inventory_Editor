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


def test_frontend_nbt_inspector_body_html_formats_editable_slot_details() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const htmlUtilsCode = fs.readFileSync("static/html_utils.js", "utf8");
            const inspectorCode = fs.readFileSync("static/nbt_inspector.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(htmlUtilsCode, context, { filename: "static/html_utils.js" });
            vm.runInNewContext(inspectorCode, context, { filename: "static/nbt_inspector.js" });

            const view = context.window.MCBENbtInspector;
            const html = view.slotInspectorBodyHtml({
                label: "Inventar <Slot>",
                slotId: 5,
                containerName: "inventory",
                item: {
                    name: "minecraft:diamond_sword",
                    source_slot: 1,
                    nbt_view: { value: { Slot: { value: 1 } } },
                },
                inspectableDetails: ["CustomName <Name>", "Enchantments & Lore"],
                nbtViewText: '{"tag":"<unsafe>"}',
                inspectorText: "Detail <Log>",
            });

            assert.ok(html.includes("slot-inspector-callout info"));
            assert.ok(html.includes("Inventar &lt;Slot&gt; enthält Zusatzdaten."));
            assert.ok(html.includes("<li>CustomName &lt;Name&gt;</li>"));
            assert.ok(html.includes("<li>Enchantments &amp; Lore</li>"));
            assert.ok(html.includes("Inventory Slot 5"));
            assert.ok(html.includes("Originalquelle: Inventory Slot 1"));
            assert.ok(html.includes("Roh-NBT Slot-Feld: 1"));
            assert.ok(html.includes('{&quot;tag&quot;:&quot;&lt;unsafe&gt;&quot;}'));
            assert.ok(html.includes("Detail &lt;Log&gt;"));
            assert.ok(!html.includes("Inventar <Slot>"));
            """
        )
    )


def test_frontend_nbt_inspector_body_html_formats_protected_slot_details() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const inspectorCode = fs.readFileSync("static/nbt_inspector.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(inspectorCode, context, { filename: "static/nbt_inspector.js" });

            const view = context.window.MCBENbtInspector;
            const html = view.slotInspectorBodyHtml({
                label: "Enderchest",
                protectedKnown: true,
                slotId: 2,
                containerName: "ender_chest",
                item: { name: "minecraft:apple" },
                inspectableDetails: ["Should not render"],
                nbtViewText: "Should not render",
                inspectorText: "Read-only details",
            });

            assert.ok(html.includes("slot-inspector-callout warning"));
            assert.ok(html.includes("Enderchest bleibt geschützt."));
            assert.ok(html.includes("Read-only"));
            assert.ok(html.includes("Nicht darstellbarer/future NBT-Eintrag"));
            assert.ok(html.includes("Read-only details"));
            assert.ok(!html.includes("Should not render"));
            assert.ok(!html.includes("slot-inspector-json"));
            """
        )
    )


def test_frontend_nbt_inspector_panel_model_and_applier() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const inspectorCode = fs.readFileSync("static/nbt_inspector.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(inspectorCode, context, { filename: "static/nbt_inspector.js" });

            const view = context.window.MCBENbtInspector;
            const model = view.slotInspectorPanelModel({
                label: "Hotbar 1",
                protectedKnown: false,
                slotId: 0,
                containerName: "inventory",
                item: { name: "minecraft:stone" },
                inspectableDetails: ["Preserved"],
                inspectorText: "Detail log",
            });

            assert.strictEqual(model.visible, true);
            assert.strictEqual(model.titleText, "Hotbar 1: NBT-Details");
            assert.ok(model.bodyHtml.includes("Hotbar 1 enthält Zusatzdaten."));
            assert.ok(model.bodyHtml.includes("Detail log"));

            const elements = {
                panel: { style: { display: "" } },
                title: { textContent: "" },
                body: { innerHTML: "" },
            };
            view.applySlotInspectorPanelModel(elements, model);
            assert.strictEqual(elements.panel.style.display, "flex");
            assert.strictEqual(elements.title.textContent, "Hotbar 1: NBT-Details");
            assert.strictEqual(elements.body.innerHTML, model.bodyHtml);

            const protectedModel = view.slotInspectorPanelModel({
                label: "Helm",
                protectedKnown: true,
                slotId: 103,
                containerName: "inventory",
                inspectorText: "Read-only log",
            });
            view.applySlotInspectorPanelModel(elements, protectedModel);
            assert.strictEqual(elements.title.textContent, "Helm ist read-only");
            assert.ok(elements.body.innerHTML.includes("Helm bleibt geschützt."));

            view.applySlotInspectorPanelModel(elements, { visible: false });
            assert.strictEqual(elements.panel.style.display, "none");
            """
        )
    )
