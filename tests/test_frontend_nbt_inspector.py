"""Pure inspector helpers keep analysis available without changing item data."""

import textwrap

from tests.node_runner import run_node

SETUP = """
const assert = require("assert");
const fs = require("fs");
const vm = require("vm");
const context = {window: {}};
vm.runInNewContext(fs.readFileSync("static/nbt_inspector.js", "utf8"), context);
const inspector = context.window.MCBENbtInspector;
"""


def test_frontend_nbt_inspector_accepts_new_and_edited_items_without_raw_nbt() -> None:
    run_node(
        SETUP
        + textwrap.dedent(
            """
            const normal = {name: "minecraft:stone", count: 1};
            for (const item of [normal, {...normal, replace_original_nbt: true},
                {...normal, special_edit: {kind: "banner", data: {patterns: []}}},
                {...normal, has_protected_nbt: true}, {name: "custom:unknown", count: 1}]) {
                assert.strictEqual(inspector.itemHasInspectableNbt(item), true);
                assert.strictEqual(inspector.itemHasInspectableNbt(item, {visible: false}), false);
            }
            for (const item of [null, undefined, {}, {name: "minecraft:air", count: 1},
                {...normal, count: 0}, {...normal, count: -1}, {...normal, count: undefined}]) {
                assert.strictEqual(inspector.itemHasInspectableNbt(item), false);
            }
            """
        )
    )


def test_frontend_nbt_inspector_preserves_known_protection_summaries() -> None:
    run_node(
        SETUP
        + textwrap.dedent(
            r"""
            const item = {
                protected_nbt_summary: ["Unbekanntes Tag <Text>", 7],
                preserved_nbt_summary: ["Eigener Name & Beschreibung"],
                has_protected_nbt: true, has_preserved_nbt: true,
                has_unknown_enchantments: true, protected_nbt_dropped: true,
            };
            const before = JSON.stringify(item);
            const details = inspector.itemProtectedNbtDetails(item);
            assert.deepStrictEqual(Array.from(details), ["Unbekanntes Tag <Text>", "7", "Eigener Name & Beschreibung",
                "Unbekannte/future Verzauberungen werden erhalten.",
                "Beim Itemtyp-Wechsel wird Zusatz-NBT vom vorherigen Item nicht übernommen."]);
            assert.deepStrictEqual(Array.from(inspector.itemProtectedNbtDetails(item, {visible: false})), []);
            assert.strictEqual(JSON.stringify(item), before);
            """
        )
    )


def test_frontend_nbt_inspector_summary_fallbacks_handle_missing_or_malformed_metadata() -> None:
    run_node(
        SETUP
        + textwrap.dedent(
            """
            const protectedMessage = "Zusatz-NBT vorhanden, Kategorien in diesem Datensatz nicht genauer aufgeschlüsselt.";
            const preservedMessage = "Bekannte Zusatz-NBT vorhanden, wird bei gleicher Item-ID erhalten.";
            assert.deepStrictEqual(Array.from(inspector.itemProtectedNbtDetails(null)), []);
            assert.deepStrictEqual(Array.from(inspector.itemProtectedNbtDetails({})), []);
            for (const malformed of [undefined, null, [], "not an array", {length: 1}, 17]) {
                assert.deepStrictEqual(Array.from(inspector.itemProtectedNbtDetails({
                    has_protected_nbt: true, has_preserved_nbt: true, protected_nbt_summary: malformed,
                })), [protectedMessage]);
                assert.deepStrictEqual(Array.from(inspector.itemProtectedNbtDetails({
                    has_preserved_nbt: true, preserved_nbt_summary: malformed,
                })), [preservedMessage]);
            }
            """
        )
    )


def test_frontend_nbt_inspector_json_keeps_types_exact_values_and_item_context_separate() -> None:
    run_node(
        SETUP
        + textwrap.dedent(
            r"""
            const nbt_view = {type: "CompoundTag", value: {
                Large: {type: "LongTag", value: "9223372036854775807"},
                Number: {type: "DoubleTag", value: "NaN"},
                Text: {type: "StringTag", value: "<script> & \\\""},
                Partial: {type: "StringTag", value: "abc", truncation: {reason: "string", total: 5, shown: 3}},
            }};
            const item = {name: "minecraft:stone", nbt_view,
                source_player_key: "synthetic_player", source_world_path: "C:/SyntheticWorld",
                display_name: "UNSAVED DRAFT NAME"};
            const before = JSON.stringify(item);
            const text = inspector.itemNbtViewText(item);
            assert.deepStrictEqual(JSON.parse(text), nbt_view);
            for (const extra of ["synthetic_player", "C:/SyntheticWorld", "UNSAVED DRAFT NAME"]) {
                assert.strictEqual(text.includes(extra), false);
            }
            assert.strictEqual(JSON.stringify(item), before);
            assert.strictEqual(inspector.itemNbtViewText(null), "");
            assert.strictEqual(inspector.itemNbtViewText({}), "");
            const cycle = {}; cycle.self = cycle;
            assert.strictEqual(inspector.itemNbtViewText({nbt_view: cycle}), "");
            """
        )
    )


def test_frontend_nbt_inspector_explanations_use_exact_paths_and_item_semantics() -> None:
    run_node(
        SETUP
        + textwrap.dedent(
            """
            const tool = {name: "minecraft:diamond_pickaxe"};
            const catalog = {itemUsesDurabilityDamage: name => name === tool.name};
            const explain = (id, item = tool, source = catalog) => inspector.nodeExplanation({id, type: "IntTag"}, item, source);
            const generic = "Originaler NBT-Wert. Nicht jeder Tag hat eine bekannte fachliche Bedeutung.";
            assert.strictEqual(explain("$.Name"), "Technische Kennung des geladenen Gegenstands.");
            assert.strictEqual(explain("$.Count"), "Gespeicherte Anzahl im Stapel.");
            assert.ok(explain("$.Slot").includes("Originaldaten"));
            assert.strictEqual(explain("$.tag.display.Name"), "Eigener Anzeigename des Gegenstands.");
            assert.strictEqual(explain("$.tag.display.Lore"), "Eigene Beschreibung, zeilenweise gespeichert.");
            assert.strictEqual(explain("$.tag.Damage"), "Verbrauchte Haltbarkeitspunkte des geladenen Gegenstands.");
            assert.strictEqual(explain("$.Damage"), "Datenwert des geladenen Gegenstands; die Bedeutung hängt vom Itemtyp ab.");
            for (const id of ["$.other.Damage", "$.tag.Items[0].Damage", "$.tag.display.Damage", "$['tag.Damage']", "$.future"]) {
                assert.strictEqual(explain(id), generic);
            }
            assert.strictEqual(explain("$.tag.Damage", {name: "minecraft:banner"}), generic);
            assert.strictEqual(explain("$.tag.Damage", tool, {}), generic);
            assert.strictEqual(inspector.nodeExplanation({id: "$.tag.Damage"}, tool), generic);
            for (const type of ["StringTag", "CompoundTag", "ListTag", "IntArrayTag", "FutureTag"]) {
                assert.strictEqual(inspector.nodeExplanation({id: "$.tag.Damage", type}, tool, catalog), generic);
            }
            """
        )
    )
