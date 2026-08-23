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


def test_frontend_inventory_rendering_escapes_icon_and_fallback_visuals() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");

            class FakeClassList {
                constructor(el) {
                    this.el = el;
                }
                add(name) {
                    const classes = new Set(String(this.el.className || "").split(/\s+/).filter(Boolean));
                    classes.add(name);
                    this.el.className = Array.from(classes).join(" ");
                }
                contains(name) {
                    return String(this.el.className || "").split(/\s+/).includes(name);
                }
            }

            class FakeElement {
                constructor(tagName = "div") {
                    this.tagName = tagName;
                    this.children = [];
                    this.attributes = {};
                    this.dataset = {};
                    this.style = {};
                    this.className = "";
                    this.classList = new FakeClassList(this);
                    this.innerHTML = "";
                    this.textContent = "";
                    this.parentNode = null;
                }
                appendChild(child) {
                    child.parentNode = this;
                    this.children.push(child);
                    return child;
                }
                remove() {
                    if (!this.parentNode) return;
                    this.parentNode.children = this.parentNode.children.filter(child => child !== this);
                    this.parentNode = null;
                }
                querySelector(selector) {
                    const className = selector.startsWith(".") ? selector.slice(1) : selector;
                    return this.children.find(child => child.classList.contains(className)) || null;
                }
                hasAttribute(name) {
                    return Object.prototype.hasOwnProperty.call(this.attributes, name);
                }
                getAttribute(name) {
                    return this.attributes[name] ?? null;
                }
                setAttribute(name, value) {
                    this.attributes[name] = String(value);
                }
                removeAttribute(name) {
                    delete this.attributes[name];
                }
            }

            const context = {
                window: {},
                document: {
                    createElement: tagName => new FakeElement(tagName),
                },
            };
            vm.runInNewContext(fs.readFileSync("static/html_utils.js", "utf8"), context, {
                filename: "static/html_utils.js",
            });
            vm.runInNewContext(fs.readFileSync("static/inventory_rendering.js", "utf8"), context, {
                filename: "static/inventory_rendering.js",
            });

            const renderer = context.window.MCBEInventoryRendering.createInventoryRenderer({
                buildSlotTooltipLines: () => ["Titel", "Technik"],
                currentSelectionState: () => ({}),
                entityVariantDisplayName: item => item?.entity_variant?.display_name_de || "",
                entityVariantSearchText: item => item?.entity_variant?.searchText || "",
                getItemEmoji: () => "<>",
                getItemIconMeta: item => item.iconMeta || null,
                getMaxDamage: () => 0,
                isKnownItemId: () => true,
                itemNamesForId: () => ["", ""],
                itemRequiresOriginalNbt: () => false,
                isProtectedKnownSlot: () => false,
                isSlotSelected: () => false,
                showSlotNumbers: () => false,
                slotAreaLabel: () => "Slot <A>",
            });

            const iconSlot = new FakeElement();
            iconSlot.attributes["data-slot"] = "1";
            renderer.renderSlot(iconSlot, 1, {
                name: "minecraft:stone",
                count: 1,
                damage: 0,
                iconMeta: { url: 'textures/<stone>.png?x="y"' },
            });
            assert.ok(iconSlot.classList.contains("local-icon-item"));
            assert.strictEqual(
                iconSlot.querySelector(".item-visual").innerHTML,
                '<img src="textures/&lt;stone&gt;.png?x=&quot;y&quot;" alt="" loading="lazy" data-icon-fallback="&lt;&gt;">',
            );

            const axolotlSlot = new FakeElement();
            axolotlSlot.attributes["data-slot"] = "6";
            const axolotl = {
                name: "minecraft:axolotl_bucket",
                count: 1,
                damage: 0,
                iconMeta: { url: "textures/bucket_axolotl.png" },
                entity_variant: {
                    key: "gold",
                    display_name_de: "Gold-Axolotl",
                },
            };
            renderer.renderSlot(axolotlSlot, 6, axolotl);
            assert.strictEqual(axolotlSlot.querySelector(".item-variant-preview"), null);
            assert.strictEqual(renderer.slotMatchesGridFilter(axolotl, "gold-axolotl"), true);

            const tropicalFish = {
                name: "minecraft:buckettropical",
                count: 1,
                damage: 0,
                entity_variant: {
                    key: "clownfish_orange_white",
                    display_name_de: "Tropenfisch: Clownfisch, Orange/Weiß",
                    searchText: "tropicalSchoolClownfish tropicalColorOrange",
                },
            };
            assert.strictEqual(renderer.slotMatchesGridFilter(tropicalFish, "tropicalschoolclownfish"), true);

            const emojiSlot = new FakeElement();
            emojiSlot.attributes["data-slot"] = "2";
            renderer.renderSlot(emojiSlot, 2, { name: "minecraft:dirt", count: 1, damage: 0 });
            assert.strictEqual(emojiSlot.querySelector(".item-visual").innerHTML, "<span>&lt;&gt;</span>");

            const unknownIconRenderer = context.window.MCBEInventoryRendering.createInventoryRenderer({
                buildSlotTooltipLines: () => ["Unbekannt", "Technik"],
                currentSelectionState: () => ({}),
                getItemEmoji: () => "??",
                getItemIconMeta: item => item.iconMeta || null,
                getMaxDamage: () => 0,
                isKnownItemId: () => false,
                itemNamesForId: () => ["", ""],
                itemRequiresOriginalNbt: () => false,
                isProtectedKnownSlot: () => false,
                isSlotSelected: () => false,
                showSlotNumbers: () => false,
                slotAreaLabel: () => "Slot",
            });
            const unknownIconSlot = new FakeElement();
            unknownIconSlot.attributes["data-slot"] = "4";
            unknownIconRenderer.renderSlot(unknownIconSlot, 4, {
                name: "minecraft:mundane_potion",
                count: 1,
                damage: 0,
                iconMeta: { url: "textures/potion.png" },
            });
            assert.ok(unknownIconSlot.classList.contains("unknown-item"));
            assert.ok(unknownIconSlot.classList.contains("local-icon-item"));
            assert.strictEqual(
                unknownIconSlot.querySelector(".item-visual").innerHTML,
                '<img src="textures/potion.png" alt="" loading="lazy" data-icon-fallback="❓">',
            );

            const protectedRenderer = context.window.MCBEInventoryRendering.createInventoryRenderer({
                buildSlotTooltipLines: () => ["Geschützt", "Technik"],
                currentSelectionState: () => ({}),
                getItemEmoji: () => "<>",
                getItemIconMeta: () => null,
                getMaxDamage: () => 0,
                isKnownItemId: () => true,
                itemNamesForId: () => ["", ""],
                itemRequiresOriginalNbt: () => false,
                isProtectedKnownSlot: () => true,
                isSlotSelected: () => false,
                showSlotNumbers: () => false,
                slotAreaLabel: () => "Slot",
            });
            const protectedSlot = new FakeElement();
            protectedSlot.attributes["data-slot"] = "3";
            protectedRenderer.renderSlot(protectedSlot, 3, null);
            assert.ok(protectedSlot.classList.contains("protected-known-slot"));
            assert.strictEqual(protectedSlot.querySelector(".item-visual").innerHTML, "<span>🔒</span>");

            const potionRenderer = context.window.MCBEInventoryRendering.createInventoryRenderer({
                buildSlotTooltipLines: () => ["Trank", "Technik"],
                currentSelectionState: () => ({}),
                getItemEmoji: () => "??",
                getItemIconMeta: () => null,
                getMaxDamage: () => 32767,
                itemDamageLabel: itemName => itemName === "minecraft:potion" ? "Potion-Datenwert" : "Abnutzung",
                itemUsesDurabilityDamage: itemName => itemName !== "minecraft:potion",
                isKnownItemId: () => true,
                itemNamesForId: () => ["Trank", "Potion"],
                itemRequiresOriginalNbt: () => false,
                isProtectedKnownSlot: () => false,
                isSlotSelected: () => false,
                showSlotNumbers: () => false,
                slotAreaLabel: () => "Slot",
                variantItemNamesForId: () => ["Trank: Wasseratmung (verlängert)", "Potion of Water Breathing (Long)"],
            });
            const potionSlot = new FakeElement();
            potionSlot.attributes["data-slot"] = "5";
            const potion = { name: "minecraft:potion", count: 1, damage: 20 };
            potionRenderer.renderSlot(potionSlot, 5, potion);
            assert.strictEqual(potionSlot.querySelector(".item-damage-bar"), null);
            assert.strictEqual(potionRenderer.slotMatchesGridFilter(potion, "wasseratmung"), true);
            assert.strictEqual(potionRenderer.slotMatchesGridFilter(potion, "water breathing"), true);

            const spearSlot = new FakeElement();
            spearSlot.attributes["data-slot"] = "6";
            potionRenderer.renderSlot(spearSlot, 6, { name: "minecraft:copper_spear", count: 1, damage: 10 });
            assert.ok(spearSlot.querySelector(".item-damage-bar"));
            """
        )
    )


def test_frontend_inventory_rendering_runtime_guard_blocks_direct_mutations() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = {
                window: {
                    MCBESlotInteractionLogic: {
                        keyboardSlotPlan: () => ({ action: "clear", ok: true }),
                    },
                },
            };
            vm.runInNewContext(
                fs.readFileSync("static/inventory_rendering.js", "utf8"),
                context,
                { filename: "static/inventory_rendering.js" },
            );

            let guardCalls = 0;
            let dirtyWrites = 0;
            let undoWrites = 0;
            let prevented = 0;
            const inventory = {
                0: { name: "minecraft:lead", count: 21 },
                1: { name: "minecraft:apple", count: 1 },
            };
            const controller = context.window.MCBEInventoryRendering.createInventoryGridController({
                doc: { querySelectorAll: () => [], querySelector: () => null, body: {} },
                getInventory: () => inventory,
                guardEditingAction: () => { guardCalls += 1; return true; },
                pushUndo: () => { undoWrites += 1; },
                setDirty: () => { dirtyWrites += 1; },
            });

            assert.strictEqual(controller.moveOrCopySlot("inventory", 0, "inventory", 1, false), false);
            controller.handleSlotKeyboard({ key: "Delete", preventDefault: () => { prevented += 1; } }, 0, "inventory");
            assert.strictEqual(guardCalls, 2);
            assert.strictEqual(undoWrites, 0);
            assert.strictEqual(dirtyWrites, 0);
            assert.strictEqual(prevented, 0);
            assert.strictEqual(inventory[0].count, 21);
            """
        )
    )
