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


def test_frontend_item_browser_controller_autocomplete_selects_and_applies_detail_item() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/item_browser_controller.js", "utf8");
            const context = {
                window: {},
                document: { addEventListener() {} },
                Event: function Event(type, options = {}) { this.type = type; this.options = options; },
            };
            vm.runInNewContext(code, context, { filename: "static/item_browser_controller.js" });

            function input(value = "") {
                return {
                    value,
                    listeners: {},
                    dispatched: [],
                    addEventListener(type, fn) { this.listeners[type] = fn; },
                    dispatchEvent(event) { this.dispatched.push(event); },
                };
            }

            const rows = [];
            const detailInput = input("minecraft:stone");
            const detailList = {
                innerHTML: "",
                style: { display: "none" },
                appendChild(row) { rows.push(row); },
                contains() { return false; },
            };
            const calls = [];
            const controller = context.window.MCBEItemBrowserController.createItemBrowserController({
                elements: { detailInput, detailAutocomplete: detailList },
                itemBrowserLogic: {
                    autocompleteMatches: () => [{ id: "minecraft:apple", de: "Apfel", en: "Apple" }],
                    autocompleteItemElement(item, icon, availability) {
                        return { item, icon, availability, addEventListener(type, fn) { this[type] = fn; } };
                    },
                    browserItems: () => [],
                },
                getItemEmoji: id => id === "minecraft:apple" ? "🍎" : "□",
                getItemIconMeta: id => id === "minecraft:apple" ? { url: "/api/icons/apple" } : null,
                getItemIconTint: id => id === "minecraft:apple" ? "#c06040" : "",
                getItemAvailability: id => id === "minecraft:apple" ? { key: "creative", label: "Kreativ" } : null,
                onDetailItemChanged: item => calls.push({ changed: item }),
                onApplyDetailItem: () => calls.push({ applied: true }),
                documentObj: { addEventListener() {} },
            });

            controller.wire();
            detailInput.listeners.input({ target: { value: "app" } });
            assert.strictEqual(detailList.style.display, "block");
            assert.strictEqual(rows.length, 1);
            assert.strictEqual(JSON.stringify(rows[0].icon), JSON.stringify({
                iconUrl: "/api/icons/apple",
                fallbackIcon: "🍎",
                iconTint: "#c06040",
            }));
            assert.strictEqual(JSON.stringify(rows[0].availability), JSON.stringify({ key: "creative", label: "Kreativ" }));
            rows[0].click();

            assert.strictEqual(detailInput.value, "minecraft:apple");
            assert.strictEqual(detailList.style.display, "none");
            assert.deepStrictEqual(calls, [{ changed: "minecraft:apple" }, { applied: true }]);
            assert.strictEqual(detailInput.dispatched[0].type, "input");
            assert.strictEqual(detailInput.dispatched[0].options.bubbles, true);
            """
        )
    )


def test_frontend_item_browser_controller_applies_selected_bed_damage_before_save() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = {
                window: {},
                document: { addEventListener() {} },
                Event: function Event(type, options = {}) { this.type = type; this.options = options; },
            };
            vm.runInNewContext(fs.readFileSync("static/item_browser_controller.js", "utf8"), context, {
                filename: "static/item_browser_controller.js",
            });
            const detailInput = {
                value: "minecraft:bed",
                dispatched: [],
                dispatchEvent(event) { this.dispatched.push(event); },
            };
            const detailList = { style: {}, innerHTML: "" };
            const calls = [];
            const controller = context.window.MCBEItemBrowserController.createItemBrowserController({
                elements: { detailInput },
                onDetailItemChanged: value => calls.push(["changed", value]),
                onDetailItemVariantSelected: item => calls.push(["variant", item.damage]),
                onApplyDetailItem: () => calls.push(["apply"]),
                documentObj: { addEventListener() {} },
            });

            controller.selectAutocompleteItem(
                detailInput,
                detailList,
                { id: "minecraft:bed", damage: 15 },
                { applyOnSelect: true },
            );

            assert.deepStrictEqual(calls, [["variant", 15], ["apply"]]);
            assert.strictEqual(detailInput.value, "minecraft:bed");
            assert.strictEqual(detailInput.dispatched.length, 1);
            """
        )
    )


def test_frontend_item_browser_controller_browser_renders_filters_and_selects_bulk_item() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/item_browser_controller.js", "utf8");
            const context = {
                window: {},
                document: { addEventListener() {} },
                Event: function Event(type, options = {}) { this.type = type; this.options = options; },
            };
            vm.runInNewContext(code, context, { filename: "static/item_browser_controller.js" });

            function element() {
                return {
                    value: "",
                    listeners: {},
                    style: { display: "none" },
                    dispatched: [],
                    addEventListener(type, fn) { this.listeners[type] = fn; },
                    dispatchEvent(event) { this.dispatched.push(event); },
                    focus(options) { this.focused = true; this.focusOptions = options; },
                    setAttribute(name, value) { this.attributes = { ...(this.attributes || {}), [name]: value }; },
                    contains() { return false; },
                };
            }

            const cards = [];
            const overlay = element();
            const bulkInput = element();
            const bulkButton = element();
            const searchInput = element();
            const grid = {
                innerHTML: "old",
                children: [],
                appendChild(card) { cards.push(card); },
            };
            const count = { textContent: "" };
            const categorySelect = { value: "weapons", selectedIndex: 0, options: [{ text: "Alle Kategorien" }], addEventListener() {} };
            const sortSelect = { value: "az", addEventListener() {} };
            const rootClasses = new Set();
            const bodyClasses = new Set();
            const classList = classes => ({
                add(name) { classes.add(name); },
                remove(name) { classes.delete(name); },
            });
            const scrollCalls = [];
            const fakeDocument = {
                addEventListener() {},
                documentElement: { classList: classList(rootClasses) },
                body: { classList: classList(bodyClasses), style: {} },
                defaultView: { scrollY: 320, scrollTo(x, y) { scrollCalls.push([x, y]); } },
            };
            const controller = context.window.MCBEItemBrowserController.createItemBrowserController({
                elements: { overlay, grid, searchInput, categorySelect, sortSelect, count, bulkInput, bulkBrowserButton: bulkButton },
                itemBrowserLogic: {
                    autocompleteMatches: () => [],
                    browserItems: (_itemsDb, options) => {
                        assert.strictEqual(JSON.stringify(options), JSON.stringify({
                            query: "", category: "all", sortMode: "type", blockOnlyIds: null, addableIds: null, blockItemIds: null,
                        }));
                        return [["minecraft:apple", ["Apfel", "Apple"]]];
                    },
                    browserItemCardElement(model) {
                        return { model, addEventListener(type, fn) { this[type] = fn; } };
                    },
                    browserCountText: ({ count, categoryLabel, sortMode }) => `${count}:${categoryLabel}:${sortMode}`,
                    browserEmptyHtml: () => "empty",
                },
                getItemEmoji: () => "🍎",
                getItemIconMeta: () => ({ url: "/icons/apple.png" }),
                getItemAvailability: id => id === "minecraft:apple" ? { key: "creative", label: "Kreativ" } : null,
                documentObj: fakeDocument,
            });

            controller.wire();
            bulkButton.listeners.click();
            assert.strictEqual(overlay.style.display, "flex");
            assert.strictEqual(overlay.attributes["aria-hidden"], "false");
            assert.strictEqual(searchInput.focused, true);
            assert.strictEqual(categorySelect.value, "all");
            assert.strictEqual(sortSelect.value, "type");
            assert.strictEqual(count.textContent, "1:Alle Kategorien:type");
            assert.strictEqual(cards[0].model.iconUrl, "/icons/apple.png");
            assert.strictEqual(JSON.stringify(cards[0].model.availability), JSON.stringify({ key: "creative", label: "Kreativ" }));
            assert.strictEqual(rootClasses.has("item-browser-open"), true);
            assert.strictEqual(bodyClasses.has("item-browser-open"), true);
            assert.strictEqual(fakeDocument.body.style.top, "-320px");

            cards[0].click();
            assert.strictEqual(bulkInput.value, "minecraft:apple");
            assert.strictEqual(overlay.style.display, "none");
            assert.strictEqual(overlay.attributes["aria-hidden"], "true");
            assert.strictEqual(bulkButton.focused, true);
            assert.strictEqual(bulkButton.focusOptions.preventScroll, true);
            assert.strictEqual(rootClasses.has("item-browser-open"), false);
            assert.strictEqual(bodyClasses.has("item-browser-open"), false);
            assert.strictEqual(fakeDocument.body.style.top, "");
            assert.deepStrictEqual(scrollCalls, [[0, 320]]);
            assert.strictEqual(bulkInput.dispatched[0].type, "input");
            """
        )
    )


def test_frontend_item_browser_controller_renders_in_chunks_with_load_more() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = {
                window: {},
                document: { addEventListener() {} },
                Event: function Event(type, options = {}) { this.type = type; this.options = options; },
            };
            vm.runInNewContext(fs.readFileSync("static/item_browser_logic.js", "utf8"), context, { filename: "static/item_browser_logic.js" });
            vm.runInNewContext(fs.readFileSync("static/item_browser_controller.js", "utf8"), context, { filename: "static/item_browser_controller.js" });

            function element() {
                return {
                    value: "",
                    listeners: {},
                    style: { display: "none" },
                    addEventListener(type, fn) { this.listeners[type] = fn; },
                    dispatchEvent() {},
                    focus() {},
                    contains() { return false; },
                };
            }

            // 450 Items ergeben 200 + 200 + 50 in drei Portionen.
            const itemsDb = {};
            for (let i = 0; i < 450; i++) {
                const id = `minecraft:item_${String(i).padStart(4, "0")}`;
                itemsDb[id] = [`Item ${i}`, `Item ${i}`];
            }

            const gridChildren = [];
            const grid = {
                innerHTML: "",
                appendChild(node) { gridChildren.push(node); },
            };
            const fakeDocument = {
                addEventListener() {},
                createElement(tag) {
                    return {
                        tagName: String(tag).toUpperCase(),
                        className: "",
                        textContent: "",
                        innerHTML: "",
                        listeners: {},
                        addEventListener(type, fn) { this.listeners[type] = fn; },
                        remove() {
                            const index = gridChildren.indexOf(this);
                            if (index >= 0) gridChildren.splice(index, 1);
                        },
                    };
                },
            };
            // Karten werden über browserItemCardElement mit dem globalen document gebaut.
            context.document = fakeDocument;

            const overlay = element();
            const searchInput = element();
            const count = { textContent: "" };
            const controller = context.window.MCBEItemBrowserController.createItemBrowserController({
                elements: { overlay, grid, searchInput, count, bulkInput: element(), bulkBrowserButton: element() },
                itemBrowserLogic: context.window.MCBEItemBrowserLogic,
                getItemsDb: () => itemsDb,
                getItemEmoji: () => "📦",
                getItemIconMeta: () => null,
                documentObj: fakeDocument,
            });

            controller.renderBrowserItems("");
            // 200 Karten plus der Nachlade-Button.
            assert.strictEqual(gridChildren.length, 201);
            const moreButton = gridChildren[200];
            assert.strictEqual(moreButton.className, "browser-load-more");
            assert.strictEqual(moreButton.textContent, "Weitere 200 von 250 anzeigen");
            assert.ok(count.textContent.startsWith("450 Items"));

            moreButton.listeners.click();
            // 400 Karten, Button mit aktualisiertem Label wieder am Ende.
            assert.strictEqual(gridChildren.length, 401);
            assert.strictEqual(gridChildren[400], moreButton);
            assert.strictEqual(moreButton.textContent, "Weitere 50 von 50 anzeigen");

            moreButton.listeners.click();
            // Alle 450 Karten, kein Button mehr.
            assert.strictEqual(gridChildren.length, 450);
            assert.ok(!gridChildren.includes(moreButton));

            // Eine Suche rendert klein und ohne Button.
            gridChildren.length = 0;
            controller.renderBrowserItems("item_0001");
            assert.strictEqual(gridChildren.length, 1);
            """
        )
    )
