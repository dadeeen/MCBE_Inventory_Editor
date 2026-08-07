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


def test_frontend_enchantment_compatibility_allows_unbreaking_on_golden_sword() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/item_catalog.js", "utf8");
            const enchantmentCompatibility = JSON.parse(fs.readFileSync("mcbe_editor/enchantment_compatibility.json", "utf8"));
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/item_catalog.js" });

            const catalog = context.window.MCBEItemCatalog.createItemCatalog({
                getItemsDb: () => ({ "minecraft:golden_sword": ["Goldschwert", "Golden Sword"] }),
                getCompatItemAliases: () => ({}),
                getItemIconIndex: () => ({}),
                getStackLimits: () => ({}),
                getMaxDamageMap: () => ({}),
                getEnchantmentCompatibility: () => enchantmentCompatibility,
                itemIdRe: /^minecraft:[a-z0-9_.-]+$/,
                defaultMaxDamage: 32767,
                maxBedrockStackCount: 255,
            });

            assert.deepStrictEqual(Array.from(catalog.enchantmentSlotsForItem("minecraft:golden_sword")), ["sword"]);
            assert.strictEqual(catalog.isEnchantmentCompatibleWithItem(17, "minecraft:golden_sword"), true);
            assert.strictEqual(catalog.isEnchantmentCompatibleWithItem(26, "minecraft:golden_sword"), true);
            assert.strictEqual(catalog.isEnchantmentCompatibleWithItem(28, "minecraft:golden_sword"), true);
            assert.strictEqual(catalog.isEnchantmentCompatibleWithItem(18, "minecraft:golden_sword"), false);
            """
        )
    )


def test_frontend_item_catalog_separates_known_from_newly_addable_ids() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {} };
            vm.runInNewContext(fs.readFileSync("static/item_catalog.js", "utf8"), context, {
                filename: "static/item_catalog.js",
            });
            const catalog = context.window.MCBEItemCatalog.createItemCatalog({
                getItemsDb: () => ({
                    "minecraft:apple": ["Apfel", "Apple"],
                    "minecraft:element_32": ["Element 32", "Element 32"],
                }),
                getCompatItemAliases: () => ({}),
                getAddableItems: () => new Set(["minecraft:apple"]),
                getItemIconIndex: () => ({}),
                getStackLimits: () => ({}),
                getMaxDamageMap: () => ({}),
                itemIdRe: /^minecraft:[a-z0-9_.-]+$/,
                defaultMaxDamage: 32767,
                maxBedrockStackCount: 127,
            });
            assert.strictEqual(catalog.isKnownItemId("minecraft:element_32"), true);
            assert.strictEqual(catalog.isAddableItemId("minecraft:element_32"), false);
            assert.strictEqual(catalog.isAddableItemId("minecraft:apple"), true);
            """
        )
    )


def test_frontend_enchantment_compatibility_uses_shared_catalog_for_new_slots() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/item_catalog.js", "utf8");
            const enchantmentCompatibility = JSON.parse(fs.readFileSync("mcbe_editor/enchantment_compatibility.json", "utf8"));
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/item_catalog.js" });

            const catalog = context.window.MCBEItemCatalog.createItemCatalog({
                getItemsDb: () => ({}),
                getCompatItemAliases: () => ({}),
                getItemIconIndex: () => ({}),
                getStackLimits: () => ({}),
                getMaxDamageMap: () => ({}),
                getEnchantmentCompatibility: () => enchantmentCompatibility,
                itemIdRe: /^minecraft:[a-z0-9_.-]+$/,
                defaultMaxDamage: 32767,
                maxBedrockStackCount: 255,
            });

            assert.deepStrictEqual(Array.from(catalog.enchantmentSlotsForItem("minecraft:copper_spear")), ["melee_spear"]);
            assert.strictEqual(catalog.isEnchantmentCompatibleWithItem(41, "minecraft:copper_spear"), true);
            assert.strictEqual(catalog.isEnchantmentCompatibleWithItem(31, "minecraft:copper_spear"), false);
            assert.deepStrictEqual(Array.from(catalog.enchantmentSlotsForItem("minecraft:player_head")), ["cosmetic_head"]);
            assert.strictEqual(catalog.isEnchantmentCompatibleWithItem(27, "minecraft:carved_pumpkin"), true);
            assert.strictEqual(catalog.isEnchantmentCompatibleWithItem(17, "minecraft:player_head"), false);
            assert.strictEqual(catalog.isEnchantmentCompatibleWithItem(41, "minecraft:enchanted_book"), true);
            assert.strictEqual(catalog.isEnchantableItemForEditor("minecraft:book"), false);
            """
        )
    )


def test_frontend_item_catalog_uses_official_item_components_before_heuristics() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {} };
            vm.runInNewContext(fs.readFileSync("static/item_catalog.js", "utf8"), context, {
                filename: "static/item_catalog.js",
            });
            const compatibility = {
                slot_groups: {
                    melee_spear: ["melee_spear"],
                    sword: ["sword"],
                },
                item_slots: {},
                item_slot_suffixes: [["_sword", "sword"]],
                official_item_slots: {
                    "minecraft:future_sword": [],
                    "minecraft:future_tool": ["melee_spear"],
                },
                compatible_slots: {
                    "41": ["melee_spear"],
                },
            };
            const components = {
                wearable: {
                    "minecraft:future_tool": { slot: "slot.weapon.offhand" },
                },
                // Nicht verfolgte Komponenten dürfen keine Wirkung mehr haben.
                dyeable: {
                    "minecraft:future_tool": { default_color: [1, 160, 255] },
                },
            };
            const catalog = context.window.MCBEItemCatalog.createItemCatalog({
                getItemsDb: () => ({}),
                getCompatItemAliases: () => ({}),
                getItemIconIndex: () => ({}),
                getStackLimits: () => ({}),
                getMaxDamageMap: () => ({}),
                getEnchantmentCompatibility: () => compatibility,
                getItemComponents: () => components,
                itemIdRe: /^minecraft:[a-z0-9_.-]+$/,
                defaultMaxDamage: 32767,
                maxBedrockStackCount: 255,
            });

            // Explizit "nicht verzauberbar" darf nicht durch das _sword-Suffix
            // wieder verzauberbar werden.
            assert.deepStrictEqual(Array.from(catalog.enchantmentSlotsForItem("minecraft:future_sword")), []);
            assert.deepStrictEqual(Array.from(catalog.enchantmentSlotsForItem("minecraft:future_tool")), ["melee_spear"]);
            assert.strictEqual(catalog.isEnchantmentCompatibleWithItem(41, "minecraft:future_tool"), true);
            assert.strictEqual(catalog.itemComponent("minecraft:future_tool", "wearable").slot, "slot.weapon.offhand");
            // minecraft:dyeable ist die Fabrikfarbe, nicht tag.customColor —
            // ohne kuratierten Eintrag darf daraus kein Tint entstehen.
            assert.strictEqual(catalog.getItemIconTint("minecraft:future_tool"), "");
            """
        )
    )


def test_frontend_icon_lookup_falls_back_to_base_potion_icons() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/item_catalog.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/item_catalog.js" });

            const catalog = context.window.MCBEItemCatalog.createItemCatalog({
                getItemsDb: () => ({}),
                getCompatItemAliases: () => ({}),
                getItemIconIndex: () => ({
                    "minecraft:potion": { url: "/api/icons/base-potion", token: "base-potion" },
                    "minecraft:potion#12": { url: "/api/icons/fire-resistance", token: "fire-resistance" },
                    "minecraft:splash_potion": { url: "/api/icons/splash-potion", token: "splash-potion" },
                    "minecraft:splash_potion#0": { url: "/api/icons/splash-potion", token: "splash-potion-0" },
                    "minecraft:splash_potion#1": { url: "/api/icons/splash-potion", token: "splash-potion-1" },
                    "minecraft:splash_potion#2": { url: "/api/icons/splash-potion", token: "splash-potion-2" },
                    "minecraft:splash_potion#3": { url: "/api/icons/splash-potion", token: "splash-potion-3" },
                    "minecraft:splash_potion#4": { url: "/api/icons/splash-potion", token: "splash-potion-4" },
                    "minecraft:splash_potion#25": { url: "/api/icons/splash-poison", token: "splash-poison" },
                    "minecraft:lingering_potion": { url: "/api/icons/lingering-potion", token: "lingering-potion" },
                    "minecraft:tipped_arrow": { url: "/api/icons/tipped-arrow", token: "tipped-arrow" },
                    "minecraft:tipped_arrow#14": { url: "/api/icons/tipped-swift", token: "tipped-swift" },
                }),
                getStackLimits: () => ({}),
                getMaxDamageMap: () => ({}),
                getEnchantmentCompatibility: () => ({}),
                itemIdRe: /^minecraft:[a-z0-9_.-]+$/,
                defaultMaxDamage: 32767,
                maxBedrockStackCount: 255,
            });

            assert.strictEqual(catalog.getItemIconMeta("minecraft:mundane_potion").token, "base-potion");
            assert.strictEqual(catalog.getItemIconMeta({ name: "minecraft:potion", damage: 12 }).token, "fire-resistance");
            assert.strictEqual(catalog.getItemIconMeta({ name: "minecraft:potion", damage: 1 }).token, "base-potion");
            assert.strictEqual(catalog.getItemIconMeta("minecraft:splash_mundane_potion").token, "splash-potion");
            for (let damage = 0; damage <= 4; damage += 1) {
                assert.strictEqual(catalog.getItemIconMeta({ name: "minecraft:splash_potion", damage }).token, `splash-potion-${damage}`);
                assert.deepStrictEqual(
                    Array.from(catalog.iconLookupCandidates({ name: "minecraft:splash_potion", damage }).slice(0, 2)),
                    [`minecraft:splash_potion#${damage}`, "minecraft:splash_potion"],
                );
            }
            assert.strictEqual(catalog.getItemIconMeta({ name: "minecraft:splash_potion", damage: 25 }).token, "splash-poison");
            assert.strictEqual(catalog.getItemIconMeta("minecraft:mundane_lingering_potion").token, "lingering-potion");
            assert.strictEqual(catalog.getItemIconMeta("minecraft:mundane_tipped_arrow").token, "tipped-arrow");
            assert.strictEqual(catalog.getItemIconMeta({ name: "minecraft:tipped_arrow", damage: 14 }).token, "tipped-swift");
            assert.deepStrictEqual(
                Array.from(catalog.iconLookupCandidates({ name: "minecraft:potion", damage: 12 }).slice(0, 2)),
                ["minecraft:potion#12", "minecraft:potion"],
            );
            """
        )
    )


def test_frontend_icon_lookup_uses_compat_item_aliases() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/item_catalog.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/item_catalog.js" });

            const catalog = context.window.MCBEItemCatalog.createItemCatalog({
                getItemsDb: () => ({
                    "minecraft:ender_chest": ["Endertruhe", "Ender Chest"],
                    "minecraft:enderchest": ["Endertruhe", "Ender Chest"],
                }),
                getCompatItemAliases: () => ({
                    "minecraft:enderchest": "minecraft:ender_chest",
                }),
                getItemIconIndex: () => ({
                    "minecraft:ender_chest": { url: "/api/icons/ender-chest", token: "ender-chest" },
                }),
                getStackLimits: () => ({}),
                getMaxDamageMap: () => ({}),
                getEnchantmentCompatibility: () => ({}),
                itemIdRe: /^minecraft:[a-z0-9_.-]+$/,
                defaultMaxDamage: 32767,
                maxBedrockStackCount: 255,
            });

            assert.strictEqual(catalog.canonicalItemId("minecraft:enderchest"), "minecraft:ender_chest");
            assert.strictEqual(catalog.getItemIconMeta("minecraft:enderchest").token, "ender-chest");
            assert.deepStrictEqual(
                Array.from(catalog.iconLookupCandidates("minecraft:enderchest").slice(0, 2)),
                ["minecraft:enderchest", "minecraft:ender_chest"],
            );
            """
        )
    )


def test_frontend_potion_damage_values_have_variant_names_and_data_label() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/item_catalog.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/item_catalog.js" });

            const catalog = context.window.MCBEItemCatalog.createItemCatalog({
                getItemsDb: () => ({
                    "minecraft:potion": ["Trank", "Potion"],
                    "minecraft:bow": ["Bogen", "Bow"],
                    "minecraft:copper_spear": ["Kupferspeer", "Copper Spear"],
                    "minecraft:mace": ["Streitkolben", "Mace"],
                }),
                getCompatItemAliases: () => ({}),
                getItemIconIndex: () => ({}),
                getStackLimits: () => ({}),
                getMaxDamageMap: () => ({
                    "minecraft:bow": 384,
                    "minecraft:copper_spear": 190,
                    "minecraft:mace": 500,
                    "__default__": 32767,
                }),
                getEnchantmentCompatibility: () => ({}),
                itemIdRe: /^minecraft:[a-z0-9_.-]+$/,
                defaultMaxDamage: 32767,
                maxBedrockStackCount: 255,
            });

            assert.deepStrictEqual(
                Array.from(catalog.variantItemNamesForId({ name: "minecraft:potion", damage: 20 })),
                ["Trank: Wasseratmung (verlängert)", "Potion of Water Breathing (Long)"],
            );
            assert.deepStrictEqual(
                Array.from(catalog.variantItemNamesForId({ name: "minecraft:splash_potion", damage: 25 })),
                ["Wurftrank: Vergiftung", "Splash Potion of Poison"],
            );
            assert.deepStrictEqual(Array.from(catalog.variantItemNamesForId({ name: "minecraft:potion", damage: 0 })), ["Wasserflasche", "Water Bottle"]);
            assert.strictEqual(catalog.itemDamageLabel("minecraft:potion"), "Potion-Datenwert");
            assert.strictEqual(catalog.itemDamageLabel("minecraft:bow"), "Abnutzung");
            assert.strictEqual(catalog.itemDamageLabel("minecraft:copper_spear"), "Abnutzung");
            assert.strictEqual(catalog.itemDamageLabel("minecraft:mace"), "Abnutzung");
            assert.strictEqual(catalog.itemDamageLabel("minecraft:stone"), "Datenwert");
            assert.strictEqual(catalog.itemUsesDurabilityDamage("minecraft:potion"), false);
            assert.strictEqual(catalog.itemUsesDurabilityDamage("minecraft:bow"), true);
            assert.strictEqual(catalog.itemUsesDurabilityDamage("minecraft:copper_spear"), true);
            assert.strictEqual(catalog.itemUsesDurabilityDamage("minecraft:mace"), true);
            assert.strictEqual(catalog.itemUsesDurabilityDamage("minecraft:stone"), false);
            """
        )
    )


def test_frontend_item_icon_tint_marks_grayscale_leather_sprites() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/item_catalog.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/item_catalog.js" });

            const catalog = context.window.MCBEItemCatalog.createItemCatalog({
                getItemsDb: () => ({}),
                getCompatItemAliases: () => ({}),
                getItemIconIndex: () => ({}),
                getStackLimits: () => ({}),
                getMaxDamageMap: () => ({}),
                getEnchantmentCompatibility: () => ({}),
                itemIdRe: /^minecraft:[a-z0-9_.-]+$/,
                defaultMaxDamage: 32767,
            });

            // Leder-Rüstung: Graustufen-Basistextur wird mit Standard-Lederfarbe getintet.
            assert.strictEqual(catalog.getItemIconTint("minecraft:leather_helmet"), "#a06540");
            assert.strictEqual(catalog.getItemIconTint("minecraft:leather_boots"), "#a06540");
            assert.strictEqual(catalog.getItemIconTint("minecraft:horsearmorleather"), "#a06540");
            assert.strictEqual(catalog.getItemIconTint({ name: "minecraft:leather_chestplate" }), "#a06540");
            // Normale Items bleiben ungetintet.
            assert.strictEqual(catalog.getItemIconTint("minecraft:leather"), "");
            assert.strictEqual(catalog.getItemIconTint("minecraft:diamond_helmet"), "");
            assert.strictEqual(catalog.getItemIconTint(null), "");
            """
        )
    )


def test_frontend_vanilla_exclusive_enchantment_conflicts() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/item_catalog.js", "utf8");
            const enchantmentCompatibility = JSON.parse(fs.readFileSync("mcbe_editor/enchantment_compatibility.json", "utf8"));
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/item_catalog.js" });

            const catalog = context.window.MCBEItemCatalog.createItemCatalog({
                getItemsDb: () => ({}),
                getCompatItemAliases: () => ({}),
                getItemIconIndex: () => ({}),
                getStackLimits: () => ({}),
                getMaxDamageMap: () => ({}),
                getEnchantmentCompatibility: () => enchantmentCompatibility,
                itemIdRe: /^minecraft:[a-z0-9_.-]+$/,
                defaultMaxDamage: 32767,
            });

            const conflicts = catalog.vanillaExclusiveEnchantmentConflicts;

            // Schärfe + Bann sind laut Vanilla-Regeln inkompatibel.
            assert.deepStrictEqual(JSON.parse(JSON.stringify(conflicts([{ id: 9, lvl: 5 }, { id: 10, lvl: 5 }]))), [[9, 10]]);
            // Drei Schutzarten in einer Gruppe.
            assert.deepStrictEqual(JSON.parse(JSON.stringify(conflicts([{ id: 0, lvl: 4 }, { id: 1, lvl: 4 }, { id: 3, lvl: 4 }]))), [[0, 1, 3]]);
            // Sog konfligiert mit Treue UND Entladung (zwei Paare);
            // Treue + Entladung allein sind kompatibel.
            assert.deepStrictEqual(JSON.parse(JSON.stringify(conflicts([{ id: 30, lvl: 3 }, { id: 31, lvl: 3 }, { id: 32, lvl: 1 }]))), [[30, 31], [30, 32]]);
            assert.deepStrictEqual(JSON.parse(JSON.stringify(conflicts([{ id: 31, lvl: 3 }, { id: 32, lvl: 1 }]))), []);
            // Dichte + Bann (Streitkolben) konfligieren.
            assert.deepStrictEqual(JSON.parse(JSON.stringify(conflicts([{ id: 39, lvl: 5 }, { id: 10, lvl: 5 }]))), [[10, 39]]);
            // Ein verzaubertes Buch speichert mehrere Verzauberungen; erst das
            // Zielitem bestimmt, welche davon gemeinsam angewendet werden.
            assert.deepStrictEqual(JSON.parse(JSON.stringify(conflicts(
                [{ id: 9, lvl: 5 }, { id: 10, lvl: 5 }],
                "minecraft:enchanted_book",
            ))), []);
            // Einzelne/kompatible Verzauberungen und leere Eingaben.
            assert.deepStrictEqual(JSON.parse(JSON.stringify(conflicts([{ id: 9, lvl: 5 }]))), []);
            assert.deepStrictEqual(JSON.parse(JSON.stringify(conflicts([]))), []);
            assert.deepStrictEqual(JSON.parse(JSON.stringify(conflicts(null))), []);
            """
        )
    )


def test_frontend_bed_data_values_have_names_icons_and_addable_variants() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {} };
            vm.runInNewContext(fs.readFileSync("static/item_catalog.js", "utf8"), context, {
                filename: "static/item_catalog.js",
            });

            const catalog = context.window.MCBEItemCatalog.createItemCatalog({
                getItemsDb: () => ({ "minecraft:bed": ["Weißes Bett", "White Bed"] }),
                getCompatItemAliases: () => ({ "minecraft:item.bed": "minecraft:bed" }),
                getItemIconIndex: () => ({
                    "minecraft:bed": { token: "base" },
                    "minecraft:bed#0": { token: "white" },
                    "minecraft:bed#15": { token: "black" },
                }),
                getStackLimits: () => ({}),
                getMaxDamageMap: () => ({}),
                getEnchantmentCompatibility: () => ({}),
                itemIdRe: /^minecraft:[a-z0-9_.-]+$/,
                defaultMaxDamage: 32767,
                maxBedrockStackCount: 255,
            });

            const variants = catalog.addableItemVariantsForId("minecraft:bed");
            assert.strictEqual(variants.length, 16);
            variants.forEach((variant, damage) => {
                assert.strictEqual(variant.damage, damage);
                assert.deepStrictEqual(
                    Array.from(catalog.variantItemNamesForId({ name: "minecraft:bed", damage })),
                    Array.from(variant.names),
                );
                assert.strictEqual(catalog.variantIconKey({ name: "minecraft:bed", damage }), `minecraft:bed#${damage}`);
                assert.strictEqual(
                    catalog.variantTargetItemId({ name: "minecraft:bed", damage }),
                    variant.searchIds[0],
                );
            });
            assert.deepStrictEqual(Array.from(variants[0].names), ["Weißes Bett", "White Bed"]);
            assert.strictEqual(variants[0].searchIds[0], "minecraft:white_bed");
            assert.deepStrictEqual(Array.from(variants[15].names), ["Schwarzes Bett", "Black Bed"]);
            assert.strictEqual(variants[15].searchIds[0], "minecraft:black_bed");
            assert.strictEqual(catalog.getItemIconMeta({ name: "minecraft:bed", damage: 0 }).token, "white");
            assert.strictEqual(catalog.getItemIconMeta({ name: "minecraft:bed", damage: 15 }).token, "black");
            assert.deepStrictEqual(
                Array.from(catalog.variantItemNamesForId({ name: "minecraft:item.bed", damage: 15 })),
                ["Schwarzes Bett", "Black Bed"],
            );
            """
        )
    )


def test_frontend_catalog_exposes_current_bedrock_data_value_item_families() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = {
                window: {
                    t: value => ({
                        Bettfarbe: "Bed color",
                        Bannerfarbe: "Banner color",
                        Hornklang: "Horn sound",
                        "Stufe von Drohendes Unheil": "Bad Omen level",
                        Suppeneffekt: "Stew effect",
                        Kartentyp: "Map type",
                    }[value] || value),
                },
            };
            vm.runInNewContext(
                fs.readFileSync("static/item_catalog.js", "utf8"),
                context,
                { filename: "static/item_catalog.js" },
            );
            const catalog = context.window.MCBEItemCatalog.createItemCatalog({
                getItemsDb: () => ({}),
                getCompatItemAliases: () => ({}),
                getItemIconIndex: () => ({}),
                getStackLimits: () => ({}),
                getMaxDamageMap: () => ({}),
                getEnchantmentCompatibility: () => ({}),
                itemIdRe: /^minecraft:[a-z0-9_.-]+$/,
                defaultMaxDamage: 32767,
                maxBedrockStackCount: 127,
            });

            const cases = [
                ["minecraft:banner", 16, 0, ["Schwarzes Banner", "Black Banner"]],
                ["minecraft:goat_horn", 8, 7, ["Bockshorn: Traum", "Goat Horn: Dream"]],
                ["minecraft:ominous_bottle", 5, 4, ["Ominöse Flasche (Drohendes Unheil V)", "Ominous Bottle (Bad Omen V)"]],
                ["minecraft:suspicious_stew", 13, 12, ["Verdächtige Suppe: Übelkeit (Geschlossene Augenblüte)", "Suspicious Stew: Nausea (Closed Eyeblossom)"]],
                ["minecraft:empty_map", 2, 2, ["Leere Lokator-Karte", "Empty Locator Map"]],
            ];
            for (const [itemId, expectedCount, damage, expectedNames] of cases) {
                const variants = catalog.dataValueVariantsForId(itemId);
                assert.strictEqual(variants.length, expectedCount);
                const variant = variants.find(entry => entry.damage === damage);
                assert.ok(variant);
                assert.deepStrictEqual(Array.from(variant.names), expectedNames);
                assert.deepStrictEqual(
                    Array.from(catalog.variantItemNamesForId({ name: itemId, damage })),
                    expectedNames,
                );
            }

            assert.strictEqual(catalog.itemDamageLabel("minecraft:banner"), "Banner color");
            assert.strictEqual(catalog.itemDamageLabel("minecraft:goat_horn"), "Horn sound");
            assert.strictEqual(catalog.itemDamageLabel("minecraft:ominous_bottle"), "Bad Omen level");
            assert.strictEqual(catalog.itemDamageLabel("minecraft:suspicious_stew"), "Stew effect");
            assert.strictEqual(catalog.itemDamageLabel("minecraft:empty_map"), "Map type");
            assert.strictEqual(
                catalog.dataValueVariantsForId("minecraft:empty_map")
                    .find(entry => entry.damage === 2).searchIds[0],
                "minecraft:empty_locator_map",
            );
            assert.strictEqual(
                catalog.variantTargetItemId({ name: "minecraft:banner", damage: 15 }),
                "minecraft:white_banner",
            );
            """
        )
    )
