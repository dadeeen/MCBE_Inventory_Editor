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


def test_frontend_slot_display_tooltip_html_and_hover_position() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const htmlUtilsCode = fs.readFileSync("static/html_utils.js", "utf8");
            const slotDisplayCode = fs.readFileSync("static/slot_display.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(htmlUtilsCode, context, { filename: "static/html_utils.js" });
            vm.runInNewContext(slotDisplayCode, context, { filename: "static/slot_display.js" });

            const display = context.window.MCBESlotDisplay;
            const html = display.slotTooltipHtml(["<Titel>", "Slot & Technik", "Lore `Zeile`"]);
            assert.ok(html.includes("&lt;Titel&gt;"));
            assert.ok(html.includes("Slot &amp; Technik"));
            assert.ok(html.includes("Lore &#96;Zeile&#96;"));
            assert.ok(!html.includes("<Titel>"));

            assert.strictEqual(
                JSON.stringify(display.slotHoverPosition({
                    clientX: 50,
                    clientY: 30,
                    cardWidth: 120,
                    cardHeight: 80,
                    viewportWidth: 500,
                    viewportHeight: 400,
                })),
                JSON.stringify({ left: 66, top: 46 }),
            );
            assert.strictEqual(
                JSON.stringify(display.slotHoverPosition({
                    clientX: 490,
                    clientY: 390,
                    cardWidth: 120,
                    cardHeight: 80,
                    viewportWidth: 500,
                    viewportHeight: 400,
                })),
                JSON.stringify({ left: 366, top: 306 }),
            );
            """
        )
    )


def test_frontend_slot_display_detail_preview_and_quick_subtitle_html() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const htmlUtilsCode = fs.readFileSync("static/html_utils.js", "utf8");
            const slotDisplayCode = fs.readFileSync("static/slot_display.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(htmlUtilsCode, context, { filename: "static/html_utils.js" });
            vm.runInNewContext(slotDisplayCode, context, { filename: "static/slot_display.js" });

            const display = context.window.MCBESlotDisplay;
            assert.strictEqual(
                display.detailPreviewIconHtml({ isEmpty: false, iconUrl: 'textures/<bad>.png?x="y"' }),
                '<img src="textures/&lt;bad&gt;.png?x=&quot;y&quot;" alt="" loading="lazy" data-icon-fallback="□">',
            );
            assert.strictEqual(
                display.detailPreviewIconHtml({ isEmpty: true, fallbackIcon: "<>" }),
                "<span>▫️</span>",
            );
            assert.strictEqual(
                display.detailPreviewIconHtml({ fallbackIcon: "<>" }),
                "<span>&lt;&gt;</span>",
            );

            const quick = display.slotQuickSubtitleHtml({
                slotLabel: "Slot <A>",
                isEmpty: false,
                maxStack: "64&",
            });
            assert.ok(quick.includes("Slot &lt;A&gt;"));
            assert.ok(quick.includes("Max-Stack 64&amp;"));
            assert.ok(!quick.includes("Slot <A>"));
            assert.ok(display.slotQuickSubtitleHtml({ slotLabel: "Leer", isEmpty: true }).includes("&nbsp;"));
            """
        )
    )


def test_frontend_slot_display_preserves_lore_formatting_in_preview_model() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {} };
            vm.runInNewContext(fs.readFileSync("static/slot_display.js", "utf8"), context);

            const display = context.window.MCBESlotDisplay;
            assert.deepStrictEqual(
                JSON.parse(JSON.stringify(display.detailLoreLinesFromForm(
                    "Block A\n\n  indented  ",
                    { maxLoreLines: 3, maxLoreLineLength: 20 },
                ))),
                ["Block A", "", "  indented  "],
            );
            assert.deepStrictEqual(
                JSON.parse(JSON.stringify(display.detailLoreLinesFromForm(""))),
                [],
            );
            """
        )
    )


def test_frontend_slot_display_detail_preview_model_and_applier() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const htmlUtilsCode = fs.readFileSync("static/html_utils.js", "utf8");
            const slotDisplayCode = fs.readFileSync("static/slot_display.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(htmlUtilsCode, context, { filename: "static/html_utils.js" });
            vm.runInNewContext(slotDisplayCode, context, { filename: "static/slot_display.js" });

            const display = context.window.MCBESlotDisplay;
            const model = display.detailPreviewModel({
                itemId: "minecraft:test_<item>",
                displayName: "Test & Name",
                isEmpty: false,
                known: false,
                count: 3,
                damage: 2,
                damageLabel: "Abnutzung",
                usesDurability: true,
                maxDamage: 10,
                loreLines: ["Lore A", "Lore B"],
                enchantments: ["Schärfe 2", "Haltbarkeit 1"],
                enchantmentTotal: 3,
                fallbackIcon: "<>",
            });

            assert.strictEqual(model.isUnknown, true);
            assert.strictEqual(model.nameText, "Test & Name");
            assert.strictEqual(model.metaText, "minecraft:test_<item> · unbekannt/future · 3x · Haltbarkeit 8/10 · Abnutzung 2");
            assert.strictEqual(model.loreText, "Lore A · Lore B");
            assert.strictEqual(model.loreVisible, true);
            assert.strictEqual(model.enchantmentsText, "✨ Schärfe 2 · Haltbarkeit 1 +1");
            assert.ok(model.iconHtml.includes("&lt;&gt;"));

            // Nicht-blockierender Vanilla-Hinweis bei inkompatiblen Kombinationen.
            const conflictModel = display.detailPreviewModel({
                itemId: "minecraft:diamond_sword",
                displayName: "Schwert",
                enchantments: ["Schärfe 5", "Bann 5"],
                enchantmentTotal: 2,
                enchantmentConflicts: ["Schärfe ↔ Bann"],
            });
            assert.strictEqual(
                conflictModel.enchantmentsText,
                "✨ Schärfe 5 · Bann 5 · ⚠️ Laut Vanilla-Regeln inkompatibel: Schärfe ↔ Bann (bleibt speicherbar)",
            );
            const noConflictModel = display.detailPreviewModel({
                itemId: "minecraft:diamond_sword",
                displayName: "Schwert",
                enchantments: ["Schärfe 5"],
                enchantmentTotal: 1,
            });
            assert.strictEqual(noConflictModel.enchantmentsText, "✨ Schärfe 5");

            const toggles = [];
            const elements = {
                preview: { classList: { toggle(name, enabled) { toggles.push([name, enabled]); } } },
                icon: { innerHTML: "" },
                name: { textContent: "" },
                meta: { textContent: "" },
                lore: { textContent: "", style: { display: "" } },
                enchantments: { textContent: "", style: { display: "" } },
            };
            display.applyDetailPreviewModel(elements, model);

            assert.deepStrictEqual(toggles, [["empty", false], ["unknown", true]]);
            assert.strictEqual(elements.icon.innerHTML, model.iconHtml);
            assert.strictEqual(elements.name.textContent, "Test & Name");
            assert.strictEqual(elements.meta.textContent, "minecraft:test_<item> · unbekannt/future · 3x · Haltbarkeit 8/10 · Abnutzung 2");
            assert.strictEqual(elements.lore.textContent, "Lore A · Lore B");
            assert.strictEqual(elements.lore.style.display, "block");
            assert.strictEqual(elements.enchantments.textContent, "✨ Schärfe 2 · Haltbarkeit 1 +1");
            assert.strictEqual(elements.enchantments.style.display, "block");

            const empty = display.detailPreviewModel({ isEmpty: true, loreLines: [], enchantments: [] });
            display.applyDetailPreviewModel(elements, empty);
            assert.strictEqual(elements.lore.textContent, "Keine Lore");
            assert.strictEqual(elements.lore.style.display, "none");
            assert.strictEqual(elements.enchantments.textContent, "Keine Verzauberungen");
            assert.strictEqual(elements.enchantments.style.display, "none");

            const potionModel = display.detailPreviewModel({
                itemId: "minecraft:potion",
                displayName: "Trank: Wasseratmung (verlängert)",
                isEmpty: false,
                known: true,
                count: 1,
                damage: 20,
                damageLabel: "Potion-Datenwert",
                maxDamage: 32767,
            });
            assert.strictEqual(potionModel.metaText, "minecraft:potion · 1x · Potion-Datenwert 20");

            const axolotlModel = display.detailPreviewModel({
                itemId: "minecraft:axolotl_bucket",
                displayName: "Axolotleimer",
                isEmpty: false,
                known: true,
                count: 1,
                damage: 0,
                damageLabel: "Datenwert",
                maxDamage: 32767,
            });
            assert.strictEqual(axolotlModel.metaText, "minecraft:axolotl_bucket · 1x · Datenwert 0");
            """
        )
    )


def test_frontend_slot_display_uses_item_specific_damage_label() -> None:
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
            const potion = { name: "minecraft:potion", count: 1, damage: 20 };
            const label = (itemName, _customName, damage) => itemName === "minecraft:potion" && damage === 20
                ? "Trank: Wasseratmung (verlängert)"
                : itemName;
            const damageLabel = itemName => itemName === "minecraft:potion" ? "Potion-Datenwert" : "Abnutzung";

            // itemDisplayName behält Abnutzung/Datenwert im Titel (Standard), damit
            // Änderungsübersichten unverändert bleiben.
            assert.strictEqual(
                display.itemDisplayName(potion, label, damageLabel),
                "Trank: Wasseratmung (verlängert) x1 · Potion-Datenwert 20",
            );
            // Mit includeDamage:false entfällt Abnutzung/Datenwert im Titel.
            assert.strictEqual(
                display.itemDisplayName(potion, label, damageLabel, { includeDamage: false }),
                "Trank: Wasseratmung (verlängert) x1",
            );
            // Der Tooltip-Titel enthält nur Name/Variante/Menge; der Datenwert
            // erscheint ausschließlich in der Detailzeile.
            assert.deepStrictEqual(
                Array.from(display.buildSlotTooltipLines(35, "inventory", potion, false, {
                    detailItemLabel: label,
                    getMaxDamage: () => 32767,
                    itemDamageLabel: damageLabel,
                    itemUsesDurabilityDamage: () => false,
                    isKnownItemId: () => true,
                }).slice(0, 6)),
                [
                    "Trank: Wasseratmung (verlängert) x1",
                    "minecraft:potion",
                    "Inventar 27",
                    "Technischer Slot: 35",
                    "Menge: 1",
                    "Potion-Datenwert: 20",
                ],
            );

            // Getaggte Einträge markieren die Abnutzungs- und Verzauberungszeilen
            // für die farbliche Hervorhebung in der Hover-Card.
            const enchantedPickaxe = {
                name: "minecraft:diamond_pickaxe",
                count: 1,
                damage: 13,
                enchantments: [{ id: 17, lvl: 5 }, { id: 15, lvl: 3 }],
            };
            const entries = display.buildSlotTooltipEntries(20, "inventory", enchantedPickaxe, false, {
                detailItemLabel: name => "Diamantspitzhacke",
                getMaxDamage: () => 481,
                itemDamageLabel: () => "Abnutzung",
                itemUsesDurabilityDamage: () => true,
                isKnownItemId: () => true,
            });
            assert.strictEqual(entries[0].kind, "title");
            assert.strictEqual(entries[0].text, "Diamantspitzhacke x1");
            const damageEntry = entries.find(entry => entry.kind === "damage");
            assert.strictEqual(damageEntry.text, "Haltbarkeit: 468 / 481 · Abnutzung: 13");
            const enchantEntry = entries.find(entry => entry.kind === "enchant");
            assert.strictEqual(enchantEntry.text, "Verzauberungen: 2");

            // slotTooltipHtml gibt die Haltbarkeit fett (tt-damage) und Verzauberungen
            // in Lavendel (tt-enchant) aus.
            const html = display.slotTooltipHtml(entries);
            assert.ok(html.includes('<small class="tt-damage">Haltbarkeit: 468 / 481 · Abnutzung: 13</small>'));
            assert.ok(html.includes('<small class="tt-enchant">Verzauberungen: 2</small>'));
            // Reine Strings bleiben unterstützt (aria/dataset-Pfad).
            assert.ok(display.slotTooltipHtml(["Titel", "tech", "Detail"]).includes("<small>Detail</small>"));

            const axolotl = {
                name: "minecraft:axolotl_bucket",
                count: 1,
                damage: 0,
                entity_variant: {
                    variant: 2,
                    key: "gold",
                    display_name_de: "Gold-Axolotl",
                    value_label_de: "Axolotl-Datenwert",
                    source: "ColorID",
                },
            };
            assert.strictEqual(display.entityVariantDisplayName(axolotl), "Gold-Axolotl");
            assert.strictEqual(
                display.itemDisplayName(axolotl, () => "Axolotleimer", () => "Datenwert"),
                "Axolotleimer · Gold-Axolotl x1",
            );
            const axolotlTooltip = display.buildSlotTooltipLines(0, "inventory", axolotl, false, {
                detailItemLabel: () => "Axolotleimer",
                getMaxDamage: () => 32767,
                itemDamageLabel: () => "Datenwert",
                isKnownItemId: () => true,
            });
            assert.ok(axolotlTooltip.includes("Entity-Variante: Gold-Axolotl"));
            assert.ok(axolotlTooltip.includes("Axolotl-Datenwert: 2"));
            assert.ok(axolotlTooltip.includes("Variant-Quelle: ColorID"));

            const tropicalFish = {
                name: "minecraft:buckettropical",
                count: 1,
                damage: 0,
                entity_variant: {
                    key: "clownfish_orange_white",
                    kind_label_de: "Tropenfisch-Bucket",
                    display_name_de: "Tropenfisch: Clownfisch, Orange/Weiß",
                    fields: [
                        { key: "BodyID", label_de: "Körperform", raw: "tropicalSchoolClownfish", display_de: "Clownfisch" },
                        { key: "ColorID", label_de: "Farbe 1", raw: "tropicalColorOrange", display_de: "Orange" },
                        { key: "Color2ID", label_de: "Farbe 2", raw: "tropicalColorWhite", display_de: "Weiß" },
                    ],
                    source: "BodyID, ColorID, Color2ID",
                },
            };
            assert.strictEqual(display.entityVariantDisplayName(tropicalFish), "Tropenfisch: Clownfisch, Orange/Weiß");
            assert.ok(display.entityVariantSearchText(tropicalFish).includes("tropicalSchoolClownfish"));
            const tropicalTooltip = display.buildSlotTooltipLines(3, "inventory", tropicalFish, false, {
                detailItemLabel: () => "Eimer voll Tropenfisch",
                getMaxDamage: () => 32767,
                itemDamageLabel: () => "Datenwert",
                isKnownItemId: () => true,
            });
            assert.ok(tropicalTooltip.includes("Tropenfisch-Bucket: Tropenfisch: Clownfisch, Orange/Weiß"));
            assert.ok(tropicalTooltip.includes("Körperform: Clownfisch"));
            assert.ok(tropicalTooltip.includes("Farbe 1: Orange"));
            assert.ok(tropicalTooltip.includes("Farbe 2: Weiß"));
            """
        )
    )


def test_frontend_slot_display_slot_quick_actions_model_and_applier() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const htmlUtilsCode = fs.readFileSync("static/html_utils.js", "utf8");
            const writeStatusCode = fs.readFileSync("static/write_status_view.js", "utf8");
            const slotDisplayCode = fs.readFileSync("static/slot_display.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(htmlUtilsCode, context, { filename: "static/html_utils.js" });
            vm.runInNewContext(writeStatusCode, context, { filename: "static/write_status_view.js" });
            vm.runInNewContext(slotDisplayCode, context, { filename: "static/slot_display.js" });

            const display = context.window.MCBESlotDisplay;
            const model = display.slotQuickActionsModel({
                slotLabel: "Slot <1>",
                isEmpty: false,
                itemLabel: "Schwert & Schild",
                maxStack: "1&",
                isValidItem: true,
                damage: 7,
                hasInspectableNbt: true,
            });

            assert.strictEqual(model.titleText, "Schwert & Schild");
            assert.ok(model.subtitleHtml.includes("Slot &lt;1&gt;"));
            assert.ok(model.subtitleHtml.includes("Max-Stack 1&amp;"));
            assert.strictEqual(model.inspectDisabled, false);
            assert.strictEqual(model.inspectTitle, "Geschützte Zusatzdaten für diesen Slot anzeigen");
            assert.strictEqual(model.clearDisabled, false);
            assert.strictEqual(model.maxStackDisabled, false);
            assert.strictEqual(model.repairDisabled, false);

            const elements = {
                title: { textContent: "" },
                subtitle: { innerHTML: "" },
                inspectButton: { disabled: true, title: "" },
                clearButton: { disabled: true, title: "", dataset: {} },
                maxStackButton: {
                    disabled: true,
                    title: "",
                    dataset: {},
                    setAttribute(name, value) { this[name] = value; },
                    removeAttribute(name) { delete this[name]; },
                },
                repairButton: { disabled: true, title: "", dataset: {} },
            };
            display.applySlotQuickActionsModel(elements, model);

            assert.strictEqual(elements.title.textContent, "Schwert & Schild");
            assert.strictEqual(elements.subtitle.innerHTML, model.subtitleHtml);
            assert.strictEqual(elements.inspectButton.disabled, false);
            assert.strictEqual(elements.inspectButton.title, "Geschützte Zusatzdaten für diesen Slot anzeigen");
            assert.strictEqual(elements.clearButton.disabled, false);
            assert.strictEqual(elements.maxStackButton.disabled, false);
            assert.strictEqual(elements.repairButton.disabled, false);

            context.window.MCBEWriteStatusView.applyWriteControlModel({
                editControls: [elements.maxStackButton],
            }, {
                editDisabled: true,
                editTitle: "Nur ansehen: Server online.",
            });
            display.applySlotQuickActionsModel(elements, model);
            assert.strictEqual(elements.maxStackButton.disabled, true);
            assert.strictEqual(elements.maxStackButton.title, "Nur ansehen: Server online.");
            assert.strictEqual(elements.maxStackButton.dataset.writeGatePreviousDisabled, "false");

            context.window.MCBEWriteStatusView.applyWriteControlModel({
                editControls: [elements.maxStackButton],
            }, {
                editDisabled: false,
            });
            assert.strictEqual(elements.maxStackButton.disabled, false);
            assert.strictEqual(elements.maxStackButton.title, "");

            const empty = display.slotQuickActionsModel({
                slotLabel: "Slot 2",
                isEmpty: true,
                isValidItem: false,
                damage: 0,
                hasInspectableNbt: false,
            });
            display.applySlotQuickActionsModel(elements, empty);

            assert.strictEqual(elements.title.textContent, "Leerer Slot");
            assert.ok(elements.subtitle.innerHTML.includes("&nbsp;"));
            assert.strictEqual(elements.inspectButton.disabled, true);
            assert.strictEqual(elements.inspectButton.title, "Keine geschützten Zusatzdaten in diesem Slot erkannt");
            assert.strictEqual(elements.clearButton.disabled, true);
            assert.strictEqual(elements.maxStackButton.disabled, true);
            assert.strictEqual(elements.repairButton.disabled, true);

            const potionDataValue = display.slotQuickActionsModel({
                slotLabel: "Hotbar 1",
                isEmpty: false,
                itemLabel: "Trank: Wasseratmung (verlängert)",
                maxStack: 1,
                isValidItem: true,
                damage: 20,
                repairableDamage: false,
                hasInspectableNbt: false,
            });
            assert.strictEqual(potionDataValue.repairDisabled, true);
            """
        )
    )


def test_frontend_slot_display_reads_slot_item_from_element() -> None:
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
            const inventory = { 5: { name: "minecraft:stone" } };
            const enderChestInventory = { 2: { name: "minecraft:diamond" } };
            const inventorySlot = {
                hasAttribute(name) {
                    return name === "data-ender-slot" ? false : name === "data-slot";
                },
                getAttribute(name) {
                    return name === "data-slot" ? "5" : null;
                },
            };
            const enderSlot = {
                hasAttribute(name) {
                    return name === "data-ender-slot";
                },
                getAttribute(name) {
                    return name === "data-ender-slot" ? "2" : null;
                },
            };

            const inventoryState = display.slotItemFromElement(inventorySlot, { inventory, enderChestInventory });
            assert.strictEqual(inventoryState.slotId, 5);
            assert.strictEqual(inventoryState.containerName, "inventory");
            assert.strictEqual(inventoryState.item, inventory[5]);

            const enderState = display.slotItemFromElement(enderSlot, { inventory, enderChestInventory });
            assert.strictEqual(enderState.slotId, 2);
            assert.strictEqual(enderState.containerName, "ender_chest");
            assert.strictEqual(enderState.item, enderChestInventory[2]);

            const empty = display.slotItemFromElement(null, { inventory, enderChestInventory });
            assert.strictEqual(empty.slotId, 0);
            assert.strictEqual(empty.containerName, "inventory");
            assert.strictEqual(empty.item, null);
            """
        )
    )


def test_frontend_slot_display_builds_slot_button_elements() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/slot_display.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/slot_display.js" });

            const doc = {
                createElement(tagName) {
                    const attrs = {};
                    return {
                        tagName,
                        className: "",
                        dataset: {},
                        style: {},
                        setAttribute(name, value) {
                            attrs[name] = String(value);
                        },
                        getAttribute(name) {
                            return attrs[name] || null;
                        },
                    };
                },
            };

            const display = context.window.MCBESlotDisplay;
            const inventorySlot = display.slotButtonElement(9, "inventory", doc);
            assert.strictEqual(inventorySlot.tagName, "div");
            assert.strictEqual(inventorySlot.className, "inventory-slot");
            assert.strictEqual(inventorySlot.getAttribute("data-slot"), "9");
            assert.strictEqual(inventorySlot.dataset.tooltip, "Inventar 1");
            assert.strictEqual(inventorySlot.getAttribute("role"), "button");
            assert.strictEqual(inventorySlot.getAttribute("tabindex"), "0");
            assert.strictEqual(inventorySlot.getAttribute("aria-label"), "Inventar 1");

            const enderSlot = display.slotButtonElement(2, "ender_chest", doc);
            assert.strictEqual(enderSlot.getAttribute("data-ender-slot"), "2");
            assert.strictEqual(enderSlot.dataset.tooltip, "Enderchest Slot 3");
            assert.strictEqual(enderSlot.getAttribute("aria-label"), "Enderchest Slot 3");

            const hoverCard = display.slotHoverCardElement(doc);
            assert.strictEqual(hoverCard.tagName, "div");
            assert.strictEqual(hoverCard.className, "slot-hover-card");
            assert.strictEqual(hoverCard.style.display, "none");
            """
        )
    )
