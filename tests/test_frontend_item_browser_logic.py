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


def test_frontend_item_browser_logic_count_text_formats_sort_and_category() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/item_browser_logic.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/item_browser_logic.js" });

            const view = context.window.MCBEItemBrowserLogic;
            assert.strictEqual(
                view.browserCountText({ count: 1, categoryLabel: "Waffen", sortMode: "az" }),
                "1 Item · Waffen · A-Z",
            );
            assert.strictEqual(
                view.browserCountText({ count: 2, categoryLabel: "Alle Kategorien", sortMode: "type" }),
                "2 Items · Alle Kategorien · Typ",
            );
            assert.strictEqual(
                view.browserEmptyHtml(),
                '<div class="no-backups">Keine Items gefunden.</div>',
            );
            """
        )
    )


def test_frontend_item_browser_finds_real_items_by_new_german_localizations() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {} };
            vm.runInNewContext(fs.readFileSync("static/item_browser_logic.js", "utf8"), context, {
                filename: "static/item_browser_logic.js",
            });

            const itemsDb = JSON.parse(fs.readFileSync("mcbe_editor/resources/item_db.json", "utf8")).items;
            const logic = context.window.MCBEItemBrowserLogic;
            const expected = [
                ["akazienboot", "minecraft:acacia_boat"],
                ["hilfsgeist-spawn-ei", "minecraft:allay_spawn_egg"],
                ["eichenstufe", "minecraft:oak_slab"],
                ["andesit", "minecraft:andesite"],
                ["andesitmauer", "minecraft:andesite_wall"],
            ];
            for (const [query, itemId] of expected) {
                const matches = logic.browserItems(itemsDb, { query });
                assert.ok(matches.some(([id]) => id === itemId), `${query} should find ${itemId}`);
                assert.ok(logic.autocompleteMatches(itemsDb, query, 20).some(item => item.id === itemId));
            }

            const andesite = logic.autocompleteMatches(itemsDb, "andesit", 20)
                .find(item => item.id === "minecraft:andesite");
            assert.deepStrictEqual(
                [andesite.de, andesite.en],
                ["Andesit", "Andesite"],
            );
            const autocompleteHtml = logic.autocompleteItemHtml(andesite);
            assert.ok(autocompleteHtml.includes("<strong>Andesit</strong> (Andesite)"));
            assert.ok(autocompleteHtml.includes("minecraft:andesite"));
            assert.ok(!autocompleteHtml.includes("Stein"));
            assert.ok(!autocompleteHtml.includes("Stone"));
            """
        )
    )


def test_frontend_item_browser_categories_are_multi_label_and_token_safe() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {} };
            vm.runInNewContext(fs.readFileSync("static/item_browser_logic.js", "utf8"), context, {
                filename: "static/item_browser_logic.js",
            });

            const logic = context.window.MCBEItemBrowserLogic;
            const data = JSON.parse(fs.readFileSync("mcbe_editor/resources/item_db.json", "utf8"));
            const blocked = new Set(data.block_only_items || []);
            const blockItems = new Set(data.block_items || []);
            const visibleIds = Object.keys(data.items).filter(id => !blocked.has(id));
            const categories = id => Array.from(logic.itemBrowserCategories(id, blockItems));

            assert.deepStrictEqual(categories("minecraft:diamond_sword"), ["common", "weapons"]);
            assert.deepStrictEqual(categories("minecraft:apple"), ["common", "food"]);
            assert.ok(categories("minecraft:chest").includes("containers"));
            assert.ok(categories("minecraft:chest").includes("blocks"));
            assert.ok(categories("minecraft:hopper_minecart").includes("redstone"));
            assert.ok(categories("minecraft:hopper_minecart").includes("transport"));
            assert.ok(categories("minecraft:hopper_minecart").includes("containers"));
            assert.ok(categories("minecraft:bamboo_chest_raft").includes("transport"));
            assert.ok(categories("minecraft:bamboo_chest_raft").includes("containers"));
            assert.deepStrictEqual(categories("minecraft:kelp"), ["blocks"]);
            assert.deepStrictEqual(categories("minecraft:chorus_fruit"), ["food", "consumables"]);
            assert.deepStrictEqual(categories("minecraft:popped_chorus_fruit"), ["materials"]);
            assert.deepStrictEqual(categories("minecraft:enchanted_golden_apple"), ["food", "consumables"]);
            assert.deepStrictEqual(categories("minecraft:fireworkscharge"), ["materials"]);
            assert.ok(categories("minecraft:trapped_chest").includes("redstone"));
            assert.ok(categories("minecraft:noteblock").includes("redstone"));
            assert.ok(categories("minecraft:golden_rail").includes("redstone"));
            assert.ok(categories("minecraft:black_shulker_box").includes("containers"));
            assert.ok(categories("minecraft:black_shulker_box").includes("blocks"));

            assert.strictEqual(logic.itemMatchesBrowserCategory("minecraft:bowl", "weapons"), false);
            assert.strictEqual(logic.itemMatchesBrowserCategory("minecraft:waxed_copper", "weapons"), false);
            assert.strictEqual(logic.itemMatchesBrowserCategory("minecraft:waxed_copper", "blocks"), true);
            assert.strictEqual(logic.itemMatchesBrowserCategory("minecraft:mace", "weapons"), true);
            assert.strictEqual(logic.itemMatchesBrowserCategory("minecraft:diamond_spear", "weapons"), true);
            assert.strictEqual(logic.itemMatchesBrowserCategory("minecraft:wolf_armor", "armor"), true);
            assert.strictEqual(logic.itemMatchesBrowserCategory("minecraft:diamond_nautilus_armor", "armor"), true);
            assert.strictEqual(logic.itemMatchesBrowserCategory("minecraft:shulkerboxred", "containers"), true);

            const waxedWeapons = visibleIds.filter(id => id.includes("waxed") && logic.itemMatchesBrowserCategory(id, "weapons", blockItems));
            assert.deepStrictEqual(waxedWeapons, []);
            const misplacedSpawnEggs = visibleIds.filter(id => (
                id.endsWith("_spawn_egg")
                && (!logic.itemMatchesBrowserCategory(id, "spawn_eggs") || logic.itemMatchesBrowserCategory(id, "food"))
            ));
            assert.deepStrictEqual(misplacedSpawnEggs, []);

            const allowed = new Set([
                "common", "armor", "food", "consumables", "redstone", "transport",
                "containers", "spawn_eggs", "weapons", "materials", "blocks", "other",
            ]);
            for (const id of visibleIds) {
                const assigned = categories(id);
                assert.ok(assigned.length > 0, `${id} has no category`);
                assert.ok(assigned.every(category => allowed.has(category)), `${id} has an unknown category`);
            }
            for (const id of blockItems) {
                assert.ok(categories(id).includes("blocks"), `${id} is registered as a block but misses the blocks category`);
            }
            """
        )
    )


def test_item_browser_offers_other_category() -> None:
    html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")

    assert '<option value="other">{{ t("Sonstiges") }}</option>' in html


def test_frontend_item_browser_logic_card_html_escapes_names_and_icons() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const htmlUtilsCode = fs.readFileSync("static/html_utils.js", "utf8");
            const code = fs.readFileSync("static/item_browser_logic.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(htmlUtilsCode, context, { filename: "static/html_utils.js" });
            vm.runInNewContext(code, context, { filename: "static/item_browser_logic.js" });

            const view = context.window.MCBEItemBrowserLogic;
            const html = view.browserItemCardHtml({
                id: "minecraft:test_<item>",
                names: ["Diamant & Test"],
                iconUrl: 'textures/<bad>.png?x="y"',
                availability: {
                    key: 'creative" onclick="bad',
                    label: "<Kreativ>",
                    description: 'Nicht "normal" & sicher',
                    ariaLabel: "Klassifikation <Kreativ>",
                },
            });

            assert.ok(html.includes("browser-item-icon"));
            assert.ok(html.includes('src="textures/&lt;bad&gt;.png?x=&quot;y&quot;"'));
            assert.ok(html.includes("Diamant &amp; Test"));
            assert.ok(html.includes("minecraft:test_&lt;item&gt;"));
            assert.ok(!html.includes("minecraft:test_<item>"));
            assert.ok(html.includes('data-item-availability="creative&quot; onclick=&quot;bad"'));
            assert.ok(html.includes("&lt;Kreativ&gt;"));
            assert.ok(html.includes('title="Nicht &quot;normal&quot; &amp; sicher"'));
            assert.ok(!html.includes('onclick="bad"'));

            const fallback = view.browserItemCardHtml({ fallbackIcon: "<>" });
            assert.ok(fallback.includes("&lt;&gt;"));
            assert.ok(view.browserItemCardHtml({ names: [null] }).includes('<div class="browser-item-name"></div>'));
            """
        )
    )


def test_frontend_item_browser_uses_english_names_and_sorting_in_english_locale() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const catalog = JSON.parse(fs.readFileSync("static/i18n/en.json", "utf8"));
            const t = (text, params) => String(catalog[text] ?? text).replace(
                /\{(\w+)\}/g,
                (match, key) => params && key in params ? String(params[key]) : match,
            );
            const context = { window: { t, MCBEI18n: {
                locale: "en",
                isEnglish: () => true,
                localizedPair: (de, en) => ({ primary: en || "", secondary: "" }),
                compare: (a, b) => a.localeCompare(b, "en", { sensitivity: "base" }),
                tp: (count, singular, plural) => t(count === 1 ? singular : plural, { count }),
            } } };
            vm.runInNewContext(fs.readFileSync("static/item_browser_logic.js", "utf8"), context, {
                filename: "static/item_browser_logic.js",
            });

            const logic = context.window.MCBEItemBrowserLogic;
            const items = {
                "minecraft:first": ["Zebra", "Apple"],
                "minecraft:second": ["Apfel", "Zebra"],
            };
            assert.deepStrictEqual(
                JSON.parse(JSON.stringify(logic.browserItems(items, { sortMode: "az" }).map(([id]) => id))),
                ["minecraft:first", "minecraft:second"],
            );
            assert.ok(logic.browserItemCardHtml({ names: ["Diamant", "Diamond"] }).includes(">Diamond<"));
            const autocomplete = logic.autocompleteItemHtml({ de: "Diamant", en: "Diamond" });
            assert.ok(autocomplete.includes("<strong>Diamond</strong>"));
            assert.ok(!autocomplete.includes("Diamant"));
            assert.deepStrictEqual(
                JSON.parse(JSON.stringify(logic.autocompleteMatches(items, "zebra").map(item => item.id))),
                ["minecraft:second"],
            );
            assert.deepStrictEqual(
                JSON.parse(JSON.stringify(logic.browserItems(items, { query: "apfel" }).map(([id]) => id))),
                [],
            );
            assert.deepStrictEqual(
                JSON.parse(JSON.stringify(logic.browserItems(items, { query: "minecraft:first" }).map(([id]) => id))),
                ["minecraft:first"],
            );
            assert.strictEqual(logic.browserCountText({ count: 2 }), "2 Items · All categories · Type");
            assert.strictEqual(
                logic.browserRenderChunkPlan({ totalCount: 450, renderedCount: 0 }).buttonLabel,
                "Show 200 more of 250",
            );
            """
        )
    )


def test_frontend_item_browser_logic_autocomplete_html_escapes_item_fields() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const htmlUtilsCode = fs.readFileSync("static/html_utils.js", "utf8");
            const code = fs.readFileSync("static/item_browser_logic.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(htmlUtilsCode, context, { filename: "static/html_utils.js" });
            vm.runInNewContext(code, context, { filename: "static/item_browser_logic.js" });

            const view = context.window.MCBEItemBrowserLogic;
            const html = view.autocompleteItemHtml({
                id: "minecraft:test_<item>",
                de: "Diamant & Test",
                en: "Diamond <Test>",
            }, {
                iconUrl: 'textures/<bad>.png?x="y"',
                fallbackIcon: "<>",
                iconTint: 'rgb(1, "2", 3)',
            });

            assert.ok(html.includes('class="autocomplete-emoji"'));
            assert.ok(html.includes('src="textures/&lt;bad&gt;.png?x=&quot;y&quot;"'));
            assert.ok(html.includes('data-icon-fallback="&lt;&gt;"'));
            assert.ok(html.includes('data-icon-tint="rgb(1, &quot;2&quot;, 3)"'));
            assert.ok(html.includes('class="autocomplete-name"'));
            assert.ok(html.includes("Diamant &amp; Test"));
            assert.ok(html.includes("Diamond &lt;Test&gt;"));
            assert.ok(html.includes("minecraft:test_&lt;item&gt;"));
            assert.ok(!html.includes("minecraft:test_<item>"));
            assert.ok(view.autocompleteItemHtml({ id: null, de: null, en: null }).includes('<span class="autocomplete-emoji">□</span>'));
            """
        )
    )


def test_frontend_item_browser_logic_element_helpers_build_expected_rows() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const htmlUtilsCode = fs.readFileSync("static/html_utils.js", "utf8");
            const code = fs.readFileSync("static/item_browser_logic.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(htmlUtilsCode, context, { filename: "static/html_utils.js" });
            vm.runInNewContext(code, context, { filename: "static/item_browser_logic.js" });

            const created = [];
            const doc = {
                createElement(tagName) {
                    const el = { tagName, className: "", innerHTML: "" };
                    created.push(el);
                    return el;
                },
            };

            const view = context.window.MCBEItemBrowserLogic;
            const row = view.autocompleteItemElement({
                id: "minecraft:test_<item>",
                de: "Diamant & Test",
                en: "Diamond <Test>",
            }, { fallbackIcon: "<>" }, doc);
            assert.strictEqual(row.tagName, "div");
            assert.strictEqual(row.className, "autocomplete-item");
            assert.ok(row.innerHTML.includes("&lt;&gt;"));
            assert.ok(row.innerHTML.includes("Diamant &amp; Test"));
            assert.ok(row.innerHTML.includes("minecraft:test_&lt;item&gt;"));

            const card = view.browserItemCardElement({
                id: "minecraft:test_<item>",
                names: ["Diamant & Test"],
                iconUrl: 'textures/<bad>.png?x="y"',
            }, doc);
            assert.strictEqual(card.tagName, "div");
            assert.strictEqual(card.className, "browser-item");
            assert.ok(card.innerHTML.includes("browser-item-icon"));
            assert.ok(card.innerHTML.includes("Diamant &amp; Test"));
            assert.ok(card.innerHTML.includes('src="textures/&lt;bad&gt;.png?x=&quot;y&quot;"'));
            assert.strictEqual(created.length, 2);
            """
        )
    )


def test_frontend_item_browser_render_chunk_plan() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {} };
            vm.runInNewContext(fs.readFileSync("static/item_browser_logic.js", "utf8"), context, { filename: "static/item_browser_logic.js" });

            const plan = context.window.MCBEItemBrowserLogic.browserRenderChunkPlan;

            // Erste Portion einer großen Liste.
            const first = plan({ totalCount: 2102, renderedCount: 0 });
            assert.deepStrictEqual(JSON.parse(JSON.stringify(first)), {
                start: 0, end: 200, remaining: 1902, hasMore: true,
                buttonLabel: "Weitere 200 von 1902 anzeigen",
            });

            // Folgeportion.
            const second = plan({ totalCount: 2102, renderedCount: 200 });
            assert.strictEqual(second.start, 200);
            assert.strictEqual(second.end, 400);
            assert.strictEqual(second.hasMore, true);

            // Letzte Portion: Restanzeige und kein Button mehr.
            const last = plan({ totalCount: 450, renderedCount: 400 });
            assert.deepStrictEqual(JSON.parse(JSON.stringify(last)), { start: 400, end: 450, remaining: 0, hasMore: false, buttonLabel: "" });

            // Kleine Liste passt in eine Portion.
            const small = plan({ totalCount: 42, renderedCount: 0 });
            assert.strictEqual(small.end, 42);
            assert.strictEqual(small.hasMore, false);

            // Vorletzte Portion mit weniger Rest als Chunk.
            const tail = plan({ totalCount: 250, renderedCount: 200 });
            assert.strictEqual(tail.end, 250);
            assert.strictEqual(tail.hasMore, false);

            // Defensive Eingaben.
            const weird = plan({ totalCount: -5, renderedCount: 99 });
            assert.strictEqual(weird.end, 0);
            assert.strictEqual(weird.hasMore, false);
            """
        )
    )


def test_frontend_item_browser_logic_hides_block_only_ids_from_suggestions() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/item_browser_logic.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/item_browser_logic.js" });

            const logic = context.window.MCBEItemBrowserLogic;
            const itemsDb = {
                "minecraft:oak_slab": ["Eichenholzstufe", "Oak Slab"],
                "minecraft:oak_double_slab": ["Oak Double Slab", "Oak Double Slab"],
                "minecraft:acacia_sign": ["Akazienschild", "Acacia Sign"],
                "minecraft:acacia_standing_sign": ["Akazienschild", "Acacia Sign"],
            };
            const blockOnly = new Set(["minecraft:oak_double_slab", "minecraft:acacia_standing_sign"]);

            // Autocomplete: Block-only-IDs tauchen nicht mehr als Vorschlag auf.
            const signMatches = logic.autocompleteMatches(itemsDb, "akazienschild", 10, blockOnly);
            assert.strictEqual(JSON.stringify(signMatches.map(m => m.id)), JSON.stringify(["minecraft:acacia_sign"]));
            const slabMatches = logic.autocompleteMatches(itemsDb, "slab", 10, blockOnly);
            assert.strictEqual(JSON.stringify(slabMatches.map(m => m.id)), JSON.stringify(["minecraft:oak_slab"]));

            // Die deutsche Oberfläche findet weiterhin deutsche und englische Namen.
            assert.strictEqual(
                JSON.stringify(logic.browserItems(itemsDb, { query: "slab", blockOnlyIds: blockOnly }).map(([id]) => id)),
                JSON.stringify(["minecraft:oak_slab"]),
            );

            // Item-Browser: gleiche Filterung.
            const browser = logic.browserItems(itemsDb, { query: "", category: "all", sortMode: "az", blockOnlyIds: blockOnly });
            assert.strictEqual(JSON.stringify(browser.map(([id]) => id).sort()), JSON.stringify(["minecraft:acacia_sign", "minecraft:oak_slab"]));

            // Ohne Set bleibt das bisherige Verhalten unverändert.
            assert.strictEqual(logic.autocompleteMatches(itemsDb, "slab").length, 2);
            assert.strictEqual(logic.browserItems(itemsDb, {}).length, 4);
            """
        )
    )


def test_frontend_item_browser_logic_uses_positive_addable_registry() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {} };
            vm.runInNewContext(fs.readFileSync("static/item_browser_logic.js", "utf8"), context, {
                filename: "static/item_browser_logic.js",
            });

            const logic = context.window.MCBEItemBrowserLogic;
            const itemsDb = {
                "minecraft:apple": ["Apfel", "Apple"],
                "minecraft:element_32": ["Element 32", "Element 32"],
                "minecraft:written_book": ["Beschriebenes Buch", "Written Book"],
            };
            const addable = new Set(["minecraft:apple"]);
            assert.deepStrictEqual(
                JSON.parse(JSON.stringify(logic.autocompleteMatches(itemsDb, "item", 10, null, addable))),
                [],
            );
            assert.deepStrictEqual(
                JSON.parse(JSON.stringify(logic.browserItems(itemsDb, { addableIds: addable }).map(([id]) => id))),
                ["minecraft:apple"],
            );
            """
        )
    )


def test_frontend_item_browser_logic_does_not_duplicate_registry_with_hidden_names() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {} };
            vm.runInNewContext(fs.readFileSync("static/item_browser_logic.js", "utf8"), context, {
                filename: "static/item_browser_logic.js",
            });

            const logic = context.window.MCBEItemBrowserLogic;
            const itemsDb = {
                "minecraft:armor": ["Upgrade:", "Upgrade:"],
                "minecraft:canbreak": ["Kann abbauen:", "Can break:"],
                "minecraft:smithing_template": ["Gilt für:", "Applies to:"],
                "minecraft:diamond": ["Diamant", "Diamond"],
            };
            const addable = new Set(["minecraft:diamond"]);

            // Ohne Registry bleibt die Logik neutral; mit Registry gilt genau
            // die Positivliste. So gibt es keine zweite, veraltbare Denylist.
            assert.strictEqual(logic.autocompleteMatches(itemsDb, "upgrade").length, 1);
            assert.strictEqual(logic.autocompleteMatches(itemsDb, "upgrade", 10, null, addable).length, 0);
            assert.strictEqual(logic.autocompleteMatches(itemsDb, "kann abbauen", 10, null, addable).length, 0);
            assert.strictEqual(
                JSON.stringify(logic.browserItems(itemsDb, { addableIds: addable }).map(([id]) => id)),
                JSON.stringify(["minecraft:diamond"]),
            );
            """
        )
    )


def test_frontend_item_browser_expands_bed_variants_and_respects_locale_search() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/item_browser_logic.js", "utf8");
            const variants = () => [
                { damage: 0, names: ["Weißes Bett", "White Bed"], searchIds: ["minecraft:white_bed"] },
                { damage: 15, names: ["Schwarzes Bett", "Black Bed"], searchIds: ["minecraft:black_bed"] },
            ];
            const context = { window: {
                t: value => value === "Datenwert" ? "Data value" : value,
                MCBEI18n: {
                    isEnglish: () => true,
                    localizedPair: (de, en) => ({ primary: en || de, secondary: "" }),
                },
            } };
            vm.runInNewContext(code, context, { filename: "static/item_browser_logic.js" });
            const logic = context.window.MCBEItemBrowserLogic;
            const db = { "minecraft:bed": ["Weißes Bett", "White Bed"] };

            const all = logic.browserItems(db, { itemVariantsForId: variants });
            assert.strictEqual(all.length, 2);
            assert.deepStrictEqual(JSON.parse(JSON.stringify(all.map(entry => entry[2].damage))), [15, 0]);
            assert.strictEqual(logic.browserItems(db, { query: "schwarz", itemVariantsForId: variants }).length, 0);
            assert.strictEqual(logic.browserItems(db, { query: "black", itemVariantsForId: variants })[0][2].damage, 15);
            assert.strictEqual(logic.browserItems(db, { query: "minecraft:black_bed", itemVariantsForId: variants })[0][2].damage, 15);
            const exact = logic.autocompleteMatches(db, "minecraft:black_bed", 10, null, null, variants);
            assert.strictEqual(exact[0].damage, 15);
            assert.ok(logic.browserItemCardHtml({
                id: "minecraft:bed", names: ["Schwarzes Bett", "Black Bed"], damage: 15,
            }).includes("minecraft:bed · Data value 15"));
            """
        )
    )
