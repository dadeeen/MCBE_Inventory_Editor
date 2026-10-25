"""Legacy slab families keep their own materials in API and browser lookups."""

import json
import textwrap
from urllib.parse import parse_qs, urlsplit

import pytest

from mcbe_editor import icon_api_routes as routes
from mcbe_editor import icons
from tests.node_runner import run_node
from tests.test_resource_pack_icons import _pack, _scan, _world

# Microsoft Learn, Aux Value to Block State Map, stone_block_slab2/3/4:
# https://learn.microsoft.com/en-us/minecraft/creator/reference/content/blockreference/examples/auxvaluetoblockstatemap
FAMILY_TARGETS = {
    "2": [
        "red_sandstone_slab",
        "purpur_slab",
        "prismarine_slab",
        "dark_prismarine_slab",
        "prismarine_brick_slab",
        "mossy_cobblestone_slab",
        "smooth_sandstone_slab",
        "red_nether_brick_slab",
    ],
    "3": [
        "end_stone_brick_slab",
        "smooth_red_sandstone_slab",
        "polished_andesite_slab",
        "andesite_slab",
        "diorite_slab",
        "polished_diorite_slab",
        "granite_slab",
        "polished_granite_slab",
    ],
    "4": ["mossy_stone_brick_slab", "smooth_quartz_slab", "normal_stone_slab", "cut_sandstone_slab", "cut_red_sandstone_slab"],
}
FIRST_FAMILY_TARGETS = {
    "double_stone_slab": [
        "stone_slab",
        "sandstone_slab",
        "wooden_slab",
        "cobblestone_slab",
        "brick_slab",
        "stone_brick_slab",
        "quartz_slab",
        "nether_brick_slab",
    ],
    "stone_block_slab": [
        "smooth_stone_slab",
        "sandstone_slab",
        "petrified_oak_slab",
        "cobblestone_slab",
        "brick_slab",
        "stone_brick_slab",
        "quartz_slab",
        "nether_brick_slab",
    ],
}


@pytest.mark.parametrize("family", ["", *FAMILY_TARGETS])
@pytest.mark.parametrize("prefix", ["double_stone_slab", "stone_block_slab"])
@pytest.mark.parametrize("top_bit", [0, 8])
def test_icon_api_uses_correct_legacy_slab_family(tmp_path, monkeypatch, family, prefix, top_bit):
    monkeypatch.setenv("MCBE_ICON_ROOTS", "")
    monkeypatch.setattr(icons, "_default_roots", lambda: [])
    monkeypatch.setattr(icons, "_vanilla_icon_roots", lambda: [])
    targets = FAMILY_TARGETS[family] if family else FIRST_FAMILY_TARGETS[prefix]
    available = [*targets, *FIRST_FAMILY_TARGETS["double_stone_slab"], *FIRST_FAMILY_TARGETS["stone_block_slab"]]
    _, pack = _pack(tmp_path / "resource_packs", "slabs", {f"textures/items/{target}.png": target.encode() for target in available})
    public, worker = _scan(tmp_path, _world(tmp_path, "world", [pack]))

    for damage, target in enumerate(targets):
        url = urlsplit(public["icons"][f"minecraft:{prefix}{family}#{damage + top_bit}"]["url"])
        context = parse_qs(url.query)["context"][0]
        response = routes.icon_file(url.path.rsplit("/", 1)[1], worker, context_id=context)
        assert response["data"] == target.encode()
    unsupported = [-1, 16, 32767, *([5, 7, 13, 15] if family == "4" else [])]
    for damage in unsupported:
        assert f"minecraft:{prefix}{family}#{damage}" not in public["icons"]


@pytest.mark.parametrize("family", ["", *FAMILY_TARGETS])
@pytest.mark.parametrize("top_bit", [0, 8])
def test_browser_catalog_uses_correct_legacy_slab_family(family, top_bit):
    run_node(
        textwrap.dedent(r"""
        const assert = require("assert");
        const fs = require("fs");
        const vm = require("vm");
        const context = { window: {} };
        vm.runInNewContext(fs.readFileSync("static/item_catalog.js", "utf8"), context);
        const family = FAMILY;
        const expected = EXPECTED;
        const first = FIRST;
        const topBit = TOP;
        const all = Object.values(expected).flat().concat(Object.values(first).flat());
        const iconIndex = Object.fromEntries(all.map(name => [`minecraft:${name}`, { url: `/${name}.png` }]));
        const catalog = context.window.MCBEItemCatalog.createItemCatalog({
            getItemsDb: () => ({}), getCompatItemAliases: () => ({}), getItemIconIndex: () => iconIndex,
            getStackLimits: () => ({}), getMaxDamageMap: () => ({}),
            itemIdRe: /^minecraft:[a-z0-9_.-]+$/, defaultMaxDamage: 32767, maxBedrockStackCount: 127,
        });
        for (const prefix of ["double_stone_slab", "stone_block_slab"]) {
            (family ? expected[family] : first[prefix]).forEach((target, damage) => {
                const item = { name: `minecraft:${prefix}${family}`, damage: damage + topBit };
                assert.strictEqual(catalog.variantTargetItemId(item), `minecraft:${target}`);
                assert.strictEqual(catalog.getItemIconMeta(item)?.url, `/${target}.png`);
            });
            const unsupported = [-1, 16, 32767, ...(family === "4" ? [5, 7, 13, 15] : [])];
            for (const damage of unsupported) {
                assert.strictEqual(catalog.variantTargetItemId({name: `minecraft:${prefix}${family}`, damage}), "");
            }
        }
    """)
        .replace("FAMILY", json.dumps(family))
        .replace("EXPECTED", json.dumps(FAMILY_TARGETS))
        .replace("FIRST", json.dumps(FIRST_FAMILY_TARGETS))
        .replace("TOP", str(top_bit))
    )
