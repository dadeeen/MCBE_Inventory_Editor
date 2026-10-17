"""Special edits use production origin resolution, validation and NBT encoding."""

from copy import deepcopy
import json

import pytest

from mcbe_editor import inventory, nbt
from mcbe_editor.bedrock_nbt import load_player_nbt, save_player_nbt
from mcbe_editor.item_data import ENCHANTMENTS
from mcbe_editor.special_items import ITEM_KINDS, LIMITS
from tests.node_runner import run_node


def item(name, slot=0, count=1, **tags):
    result = nbt.CompoundTag({"Name": nbt.StringTag(name), "Slot": nbt.ByteTag(slot), "Count": nbt.ByteTag(count), "Damage": nbt.ShortTag(0)})
    if tags:
        result["tag"] = nbt.CompoundTag(tags)
    return result


def player_for(original):
    return nbt.CompoundTag({"Inventory": nbt.ListTag([original], 10)})


def parsed(original):
    return inventory.nbt_to_json(player_for(original))[0][0]


def clean_child(child):
    return {key: value for key, value in child.items() if key not in {"source_slot", "source_item_digest"}}


def save(original, data, **overrides):
    payload = parsed(original)
    payload.update(overrides)
    payload["special_edit"] = {"kind": ITEM_KINDS[payload["name"]], "data": data}
    root = player_for(original)
    result = inventory.build_inventory_nbt(root, [payload], ENCHANTMENTS)[0]
    # A real wire round trip catches wrong NBT scalar and list encodings.
    return load_player_nbt(save_player_nbt(nbt.NamedTag(result))).tag


@pytest.mark.parametrize("name", sorted(ITEM_KINDS))
def test_empty_special_editor_echo_is_byte_preserving(name):
    original = item(name)
    metadata = parsed(original)["special_item"]
    assert metadata["editable"]
    assert save(original, metadata["data"]).save_to() == original.save_to()


@pytest.mark.parametrize(
    "child",
    [
        item("minecraft:diamond"),
        item("minecraft:diamond", count=65),
        item("minecraft:writable_book", pages=nbt.ListTag([nbt.CompoundTag({"text": nbt.StringTag("Keep"), "addon": nbt.IntTag(7)})], 10)),
    ],
)
def test_browser_container_echo_preserves_sparse_storage_and_reverted_nested_edits(child):
    original = item("minecraft:bundle", storage_item_component_content=nbt.ListTag([child], 10))
    payload = parsed(original)
    data = deepcopy(payload["special_item"]["data"])
    nested = data["items"][0]
    if nested["special_item"] is not None:
        nested["special_edit"] = {"kind": nested["special_item"]["kind"], "data": deepcopy(nested["special_item"]["data"])}
    payload["special_edit"] = {"kind": "bundle", "data": data}
    result = run_node(
        "const item = "
        + json.dumps(payload)
        + ";\n"
        + r"""
        const fs = require('fs');
        global.window = {};
        eval(fs.readFileSync('static/save_payload_logic.js', 'utf8'));
        const empty = () => ({});
        const logic = window.MCBESavePayloadLogic.createSavePayloadLogic({
            getCleanSnapshot: empty, getInventory: () => ({0:item}), getEnderChestInventory: empty,
            getPlayerStats: empty, getPlayerEffects: () => [], getPlayerAbilities: empty, getProtectedNbt: empty,
            getAbilitiesTouched: () => false, getEffectsTouched: () => false,
            getCurrentPlayerKey: () => 'player', getCurrentPlayerRevision: () => 'revision',
            getServerGuardEpoch: () => 0, getWorldPath: () => 'world', getWorldPresenceSessionId: () => 'session',
            itemIsVisiblePresent: value => Boolean(value?.name), itemRequiresOriginalNbt: () => false,
            removeProtectedStatsFromPayload: value => value, sectionChanged: () => true,
        });
        console.log(JSON.stringify(logic.buildSavePayload().inventory[0]));
        """
    )
    serialized = json.loads(result.stdout)
    assert "special_item" not in serialized["special_edit"]["data"]["items"][0]
    stored = inventory.build_inventory_nbt(player_for(original), [serialized], ENCHANTMENTS)[0]
    assert stored.save_to() == original.save_to()


def test_container_echo_does_not_ignore_forbidden_child_origins():
    original = item("minecraft:bundle", storage_item_component_content=nbt.ListTag([item("minecraft:diamond")], 10))
    data = parsed(original)["special_item"]["data"]
    data["items"][0]["source_player_key"] = "other"
    with pytest.raises(ValueError, match="externe Originalquelle"):
        save(original, data)


def test_book_reorder_and_edit_preserves_unknown_page_and_book_tags():
    pages = nbt.ListTag(
        [
            nbt.CompoundTag({"text": nbt.StringTag("old"), "photoname": nbt.StringTag("image-token"), "addon": nbt.LongTag(12)}),
            nbt.CompoundTag({"text": nbt.StringTag("second")}),
        ],
        10,
    )
    original = item(
        "minecraft:written_book",
        pages=pages,
        title=nbt.StringTag("Title"),
        author=nbt.StringTag("Author"),
        generation=nbt.IntTag(2),
        addon=nbt.ByteArrayTag([1, 2]),
    )
    data = parsed(original)["special_item"]["data"]
    data["pages"].reverse()
    data["pages"][1]["text"] = "Äöß\nLiteral ␛x41"
    data["pages"].append({"text": "New"})
    result = save(original, data)["tag"]
    assert result["generation"].py_data == 2
    assert result["addon"].save_to() == original["tag"]["addon"].save_to()
    assert result["pages"][0].save_to() == pages[1].save_to()
    assert result["pages"][1]["photoname"].py_data == "image-token"
    assert result["pages"][1]["addon"].py_data == 12
    assert result["pages"][1]["text"].py_data == "Äöß\nLiteral ␛x41"
    assert result["pages"][2]["photoname"].py_data == ""


def test_container_move_and_change_keep_original_child_unknown_data():
    sword = item("minecraft:diamond_sword", slot=8, addon=nbt.LongTag(712))
    original = item("minecraft:undyed_shulker_box", Items=nbt.ListTag([sword], 10), addon=nbt.StringTag("keep"))
    data = parsed(original)["special_item"]["data"]
    child = data["items"][0]
    child.update(slot=26, damage=12)
    data["items"].append({"slot": 4, "name": "minecraft:diamond", "count": 7, "damage": 0})
    result = save(original, data)["tag"]
    assert result["addon"].py_data == "keep"
    moved = result["Items"][1]
    assert moved["Slot"].py_data == 26
    assert moved["tag"]["addon"].py_data == 712
    assert parsed(item("minecraft:shulker_box", Items=result["Items"]))["special_item"]["data"]["items"][1]["damage"] == 12


@pytest.mark.parametrize("clear_first", [False, True])
def test_detail_replacement_does_not_resurrect_original_special_nbt(clear_first):
    original = item("minecraft:writable_book", pages=nbt.ListTag([nbt.CompoundTag({"text": nbt.StringTag("Original")})], 10), addon=nbt.StringTag("old"))
    script = "const previous = " + json.dumps(parsed(original)) + ";\nconst clearFirst = " + json.dumps(clear_first) + ";\n"
    result = run_node(
        script
        + r"""
        const fs = require('fs');
        global.window = {};
        eval(fs.readFileSync('static/slot_detail_logic.js', 'utf8'));
        const build = (previousItem, rawName) => window.MCBESlotDetailLogic.buildDetailItemFromForm({
            slotId:0,previousItem,rawName,rawCount:1,rawDamage:0
        }).item;
        const intermediate = clearFirst ? null : build(previous, 'minecraft:diamond');
        console.log(JSON.stringify(build(intermediate, previous.name)));
        """
    )
    payload = json.loads(result.stdout)
    stored = inventory.build_inventory_nbt(player_for(original), [payload], ENCHANTMENTS)[0]
    assert "pages" not in stored.get("tag", {})
    assert "addon" not in stored.get("tag", {})


@pytest.mark.parametrize(
    ("name", "count", "expected"),
    [("minecraft:diamond", 64, 68), ("minecraft:ender_pearl", 16, 68), ("minecraft:diamond_sword", 1, 68), ("minecraft:bundle", 1, 8)],
)
def test_bundle_weights_and_dense_slot_encoding(name, count, expected):
    original = item("minecraft:bundle")
    result = save(original, {"items": [{"slot": 63, "name": name, "count": count, "damage": 0}]})
    assert result["tag"]["bundle_weight"].py_data == expected
    assert len(result["tag"]["storage_item_component_content"]) == 64
    assert result["tag"]["storage_item_component_content"][63]["Name"].py_data == name
    assert parsed(result)["special_item"]["editable"]


def test_nested_bundle_and_book_are_editable_in_one_transaction():
    original = item("minecraft:undyed_shulker_box")
    data = {
        "items": [
            {
                "slot": 1,
                "name": "minecraft:bundle",
                "count": 1,
                "damage": 0,
                "special_edit": {
                    "kind": "bundle",
                    "data": {
                        "items": [
                            {
                                "slot": 2,
                                "name": "minecraft:writable_book",
                                "count": 1,
                                "damage": 0,
                                "special_edit": {"kind": "book", "data": {"pages": [{"text": "Nested"}]}},
                            }
                        ]
                    },
                },
            }
        ]
    }
    result = save(original, data)
    nested = result["tag"]["Items"][0]
    assert nested["tag"]["bundle_weight"].py_data == 68
    assert nested["tag"]["storage_item_component_content"][2]["tag"]["pages"][0]["text"].py_data == "Nested"


@pytest.mark.parametrize("count_type", [nbt.ShortTag, nbt.IntTag, nbt.LongTag])
def test_bundle_weights_preserve_readable_integer_count_types(count_type):
    child = item("minecraft:diamond")
    child["Count"] = count_type(2)
    original = item("minecraft:bundle", storage_item_component_content=nbt.ListTag([child], 10))
    metadata = parsed(original)["special_item"]
    assert metadata["editable"]
    metadata["data"]["items"].append({"slot": 1, "name": "minecraft:diamond", "count": 3, "damage": 0})
    stored = save(original, metadata["data"])
    assert stored["tag"]["bundle_weight"].py_data == 9
    assert stored["tag"]["storage_item_component_content"][0].save_to() == child.save_to()


@pytest.mark.parametrize("name", ["minecraft:bundle", "minecraft:undyed_shulker_box"])
def test_shulker_nesting_is_rejected(name):
    with pytest.raises(ValueError):
        save(item(name), {"items": [{"slot": 0, "name": "minecraft:blue_shulker_box", "count": 1, "damage": 0}]})


@pytest.mark.parametrize(
    "children",
    [
        [{"slot": 0, "name": "minecraft:diamond", "count": 64}, {"slot": 1, "name": "minecraft:stone", "count": 1}],
        [{"slot": 0, "name": "minecraft:diamond", "count": 1}, {"slot": 0, "name": "minecraft:stone", "count": 1}],
        [{"slot": 64, "name": "minecraft:diamond", "count": 1}],
        [{"slot": 0, "name": "minecraft:diamond", "count": 1, "source_player_key": "other"}],
        [{"slot": 0, "name": "minecraft:diamond", "count": 1, "source_index": True}],
        [{"slot": 0, "name": "minecraft:diamond", "count": 1, "source_index": 0}],
    ],
)
def test_invalid_container_payloads_fail_without_changing_original(children):
    original = item("minecraft:bundle")
    before = original.save_to()
    with pytest.raises(ValueError):
        save(original, {"items": children})
    assert original.save_to() == before


def test_duplicate_original_child_cannot_alias_unknown_tags():
    original = item("minecraft:shulker_box", Items=nbt.ListTag([item("minecraft:diamond", addon=nbt.StringTag("original"))], 10))
    data = parsed(original)["special_item"]["data"]
    data["items"].append({**data["items"][0], "slot": 1})
    with pytest.raises(ValueError):
        save(original, data)


def test_shulker_keeps_original_order_and_untouched_empty_records():
    empty = nbt.CompoundTag({"Slot": nbt.ByteTag(4)})
    original = item("minecraft:shulker_box", Items=nbt.ListTag([item("minecraft:diamond", slot=20), empty, item("minecraft:stone", slot=1)], 10))
    data = parsed(original)["special_item"]["data"]
    data["items"][0]["count"] = 7
    stored = save(original, data)["tag"]["Items"]
    assert [entry["Slot"].py_data for entry in stored] == [20, 4, 1]
    assert stored[1].save_to() == empty.save_to()
    assert stored[2].save_to() == original["tag"]["Items"][2].save_to()


@pytest.mark.parametrize("name, key", [("minecraft:shulker_box", "Items"), ("minecraft:bundle", "storage_item_component_content")])
@pytest.mark.parametrize("count", [nbt.ByteTag(1), nbt.ShortTag(0)])
def test_container_edits_preserve_the_readers_safe_empty_placeholders(name, key, count):
    empty = item("minecraft:air", slot=4)
    empty["Count"] = count
    original = item(name, **{key: nbt.ListTag([item("minecraft:diamond"), empty], 10)})
    data = parsed(original)["special_item"]["data"]
    assert len(data["items"]) == 1
    data["items"][0]["count"] = 2
    stored = save(original, data)["tag"][key]
    preserved = next(entry for entry in stored if entry["Slot"].py_data == 4)
    assert preserved.save_to() == empty.save_to()


@pytest.mark.parametrize("count", [nbt.ByteTag(1), nbt.ShortTag(0)])
def test_nested_bundle_weight_ignores_safe_empty_placeholders(count):
    empty = item("minecraft:air", slot=4)
    empty["Count"] = count
    contents_key = "storage_item_component_content"
    nested = item("minecraft:bundle", **{contents_key: nbt.ListTag([item("minecraft:diamond", count=60), empty], 10)})
    original = item("minecraft:bundle", **{contents_key: nbt.ListTag([nested], 10)})
    data = parsed(original)["special_item"]["data"]
    data["items"][0]["display_name"] = "Inner bundle"
    stored = save(original, data)["tag"]
    assert stored["bundle_weight"].py_data == 68
    assert stored[contents_key][0]["tag"][contents_key].save_to() == nested["tag"][contents_key].save_to()


def effect(**overrides):
    return {"shape": 2, "colors": [1, 15], "fade": [4], "trail": True, "flicker": False, **overrides}


@pytest.mark.parametrize("name", ["minecraft:fireworks", "minecraft:firework_rocket", "minecraft:firework_star", "minecraft:fireworkscharge"])
def test_firework_typed_encoding_and_unknown_tags(name):
    data = {"explosions": [effect()]}
    if ITEM_KINDS[name] == "fireworks":
        data["flight"] = 3
    original = save(item(name), data)
    branch = original["tag"]["Fireworks"]["Explosions"][0] if "Fireworks" in original["tag"] else original["tag"]["FireworksItem"]
    assert isinstance(branch["FireworkColor"], nbt.ByteArrayTag)
    branch["unknown"] = nbt.StringTag("kept")
    data = parsed(original)["special_item"]["data"]
    data["explosions"][0]["shape"] = 4
    after = save(original, data)
    branch = after["tag"]["Fireworks"]["Explosions"][0] if "Fireworks" in after["tag"] else after["tag"]["FireworksItem"]
    assert branch["unknown"].py_data == "kept"
    assert branch["FireworkType"].py_data == 4
    assert list(branch["FireworkColor"]) == [1, 15]


def test_banner_layers_reorder_with_unknown_metadata_and_base_color_preserved():
    original = save(item("minecraft:banner"), {"patterns": [{"pattern": "bo", "color": 1}, {"pattern": "cre", "color": 0}]})
    original["Damage"] = nbt.ShortTag(4)
    original["tag"]["Patterns"][0]["addon"] = nbt.LongTag(8)
    data = parsed(original)["special_item"]["data"]
    data["patterns"].reverse()
    result = save(original, data)
    assert result["Damage"].py_data == 4
    assert result["tag"]["Patterns"][1]["addon"].py_data == 8


def test_firework_edit_preserves_absent_defaults_in_untouched_effects():
    minimal = nbt.CompoundTag({"FireworkColor": nbt.ByteArrayTag([1]), "addon": nbt.StringTag("keep")})
    original = item("minecraft:firework_rocket", Fireworks=nbt.CompoundTag({"Explosions": nbt.ListTag([minimal], 10)}))
    data = parsed(original)["special_item"]["data"]
    data["flight"] = 3
    result = save(original, data)["tag"]["Fireworks"]
    assert result["Flight"].py_data == 3
    assert result["Explosions"][0].save_to() == minimal.save_to()


def test_firework_edit_only_writes_changed_defaults_and_preserves_raw_true():
    minimal = nbt.CompoundTag({"FireworkColor": nbt.ByteArrayTag([1]), "FireworkTrail": nbt.ByteTag(-1)})
    original = item("minecraft:firework_rocket", Fireworks=nbt.CompoundTag({"Explosions": nbt.ListTag([minimal], 10)}))
    data = parsed(original)["special_item"]["data"]
    data["explosions"][0]["shape"] = 4
    result = save(original, data)["tag"]["Fireworks"]
    assert "Flight" not in result
    assert result["Explosions"][0]["FireworkType"].py_data == 4
    assert result["Explosions"][0]["FireworkTrail"].py_data == -1
    assert "FireworkFade" not in result["Explosions"][0]
    assert "FireworkFlicker" not in result["Explosions"][0]


def test_book_edit_preserves_absent_text_in_untouched_page():
    untouched = nbt.CompoundTag({"photoname": nbt.StringTag("image-token")})
    original = item("minecraft:writable_book", pages=nbt.ListTag([untouched, nbt.CompoundTag({"text": nbt.StringTag("old")})], 10))
    data = parsed(original)["special_item"]["data"]
    data["pages"][1]["text"] = "changed"
    result = save(original, data)["tag"]["pages"]
    assert result[0].save_to() == untouched.save_to()
    assert result[1]["text"].py_data == "changed"


def test_star_icon_follows_colors_but_preserves_explicit_override():
    original = save(item("minecraft:firework_star"), {"explosions": [effect(colors=[1])]})
    assert original["tag"]["customColor"].py_data == 0xB02E26 - (1 << 24)
    data = parsed(original)["special_item"]["data"]
    data["explosions"][0]["colors"] = [4]
    assert save(original, data)["tag"]["customColor"].py_data == 0x3C44AA - (1 << 24)
    original["tag"]["customColor"] = nbt.IntTag(-12345)
    assert save(original, data)["tag"]["customColor"].py_data == -12345


@pytest.mark.parametrize(
    "original",
    [
        item("minecraft:bundle", storage_item_component_content=nbt.StringTag("opaque")),
        item("minecraft:bundle", storage_item_component_content=nbt.ListTag([nbt.CompoundTag({"Slot": nbt.ByteTag(0), "addon": nbt.IntTag(2)})], 10)),
        item("minecraft:writable_book", pages=nbt.ListTag([nbt.StringTag("java format")], 8)),
        item("minecraft:banner", Type=nbt.IntTag(1)),
        item("minecraft:fireworks", Fireworks=nbt.CompoundTag({"Flight": nbt.IntTag(3)})),
    ],
)
def test_unknown_formats_are_read_only_and_survive_normal_changes(original):
    assert parsed(original)["special_item"]["editable"] is False
    with pytest.raises(ValueError):
        save(original, {})
    payload = parsed(original)
    payload["display_name"] = "A harmless name"
    result = inventory.build_inventory_nbt(player_for(original), [payload], ENCHANTMENTS)[0]
    for key, tag in original["tag"].items():
        assert result["tag"][key].save_to() == tag.save_to()


@pytest.mark.parametrize(
    "data",
    [
        {"pages": [{"text": "x" * (LIMITS["page_length"] + 1)}]},
        {"pages": [{"text": "😀" * 129}]},
        {"pages": [{"text": "x", "raw_nbt": {}}]},
        {"pages": [{"text": "x", "source_index": 0}]},
        {"pages": [{"text": "x"}] * 51},
        {"pages": "not a list"},
    ],
)
def test_book_payload_bounds(data):
    with pytest.raises(ValueError):
        save(item("minecraft:writable_book"), data)


def test_wrong_editor_and_stale_parent_origin_fail_closed():
    original = item("minecraft:writable_book")
    payload = parsed(original)
    payload["special_edit"] = {"kind": "bundle", "data": {"items": []}}
    with pytest.raises(ValueError):
        inventory.build_inventory_nbt(player_for(original), [payload], ENCHANTMENTS)
    payload = parsed(original)
    payload["special_edit"] = {"kind": "book", "data": {"pages": [{"text": "change"}]}}
    original["tag"] = nbt.CompoundTag({"addon": nbt.StringTag("changed since load")})
    with pytest.raises(ValueError):
        inventory.build_inventory_nbt(player_for(original), [payload], ENCHANTMENTS)


def test_nested_edit_budget_cannot_be_bypassed():
    child = {"slot": 0, "name": "minecraft:bundle", "count": 1, "damage": 0}
    for _ in range(LIMITS["depth"] + 1):
        child = {**deepcopy(child), "special_edit": {"kind": "bundle", "data": {"items": [child]}}}
    with pytest.raises(ValueError):
        save(item("minecraft:shulker_box"), {"items": [child]})


@pytest.mark.parametrize("levels", [LIMITS["depth"] - 2, LIMITS["depth"] - 1])
def test_bundle_weight_depth_boundary(levels):
    child = {"slot": 0, "name": "minecraft:diamond", "count": 1, "damage": 0}
    for _ in range(levels):
        child = {"slot": 0, "name": "minecraft:bundle", "count": 1, "damage": 0, "special_edit": {"kind": "bundle", "data": {"items": [child]}}}
    if levels == LIMITS["depth"] - 2:
        stored = save(item("minecraft:bundle"), {"items": [child]})
        assert stored["tag"]["bundle_weight"].py_data == 1 + 4 * (levels + 1)
        assert parsed(stored)["special_item"]["editable"]
    else:
        with pytest.raises(ValueError):
            save(item("minecraft:bundle"), {"items": [child]})


def test_empty_bundle_at_maximum_depth_stays_editable_after_reload():
    from mcbe_editor.item_containers import empty_slot

    child = {"slot": 0, "name": "minecraft:bundle", "count": 1, "damage": 0, "special_edit": {"kind": "bundle", "data": {"items": []}}}
    for _ in range(LIMITS["depth"] - 2):
        child = {"slot": 0, "name": "minecraft:bundle", "count": 1, "damage": 0, "special_edit": {"kind": "bundle", "data": {"items": [child]}}}
    stored = save(item("minecraft:bundle"), {"items": [child]})
    assert stored["tag"]["bundle_weight"].py_data == 4 * LIMITS["depth"]
    deepest = stored
    for _ in range(LIMITS["depth"] - 1):
        deepest = deepest["tag"]["storage_item_component_content"][0]
    deepest["tag"] = nbt.CompoundTag(
        {"storage_item_component_content": nbt.ListTag([empty_slot(slot) for slot in range(64)], 10), "bundle_weight": nbt.IntTag(4)}
    )
    assert parsed(stored)["special_item"]["editable"]
    contents = parsed(stored)["special_item"]["data"]
    contents["items"][0]["slot"] = 1
    assert parsed(save(stored, contents))["special_item"]["editable"]


def test_container_read_and_write_share_the_occupied_item_budget():
    contents = {
        "items": [
            {
                "slot": slot,
                "name": "minecraft:bundle",
                "count": 1,
                "special_edit": {"kind": "bundle", "data": {"items": [{"slot": i, "name": "minecraft:diamond", "count": 1} for i in range(31)]}},
            }
            for slot in range(8)
        ]
    }
    original = item("minecraft:undyed_shulker_box")
    stored = save(original, contents)
    assert parsed(stored)["special_item"]["editable"]
    contents["items"].append({"slot": 8, "name": "minecraft:diamond", "count": 1})
    with pytest.raises(ValueError):
        save(original, contents)
    # The read side protects a larger original too, including its untouched NBT.
    stored["tag"]["Items"].append(item("minecraft:diamond", slot=8))
    assert parsed(stored)["special_item"]["editable"] is False


@pytest.mark.parametrize("added", [0, 1])
@pytest.mark.parametrize("echo_special_edit", [False, True])
def test_container_budget_includes_unchanged_original_descendants(added, echo_special_edit):
    bundles = [
        item("minecraft:bundle", slot=slot, storage_item_component_content=nbt.ListTag([item("minecraft:diamond", slot=i) for i in range(31)], 10))
        for slot in range(8)
    ]
    original = item("minecraft:undyed_shulker_box", Items=nbt.ListTag(bundles, 10))
    before = original.save_to()
    data = parsed(original)["special_item"]["data"]
    data["items"][0]["display_name"] = "Renamed bundle"
    if echo_special_edit:
        for child in data["items"]:
            child["special_edit"] = {"kind": "bundle", "data": deepcopy(child["special_item"]["data"])}
    if added:
        data["items"].append({"slot": 8, "name": "minecraft:diamond", "count": 1})
        with pytest.raises(ValueError):
            save(original, data)
    else:
        stored = save(original, data)
        assert parsed(stored)["special_item"]["editable"]
        assert stored["tag"]["Items"][0]["tag"]["storage_item_component_content"].save_to() == bundles[0]["tag"]["storage_item_component_content"].save_to()
    assert original.save_to() == before


def test_offhand_fireworks_use_special_writer_without_inventing_slot_tag():
    from mcbe_editor.root_equipment import apply_root_equipment_writes

    original = item("minecraft:firework_rocket", addon=nbt.StringTag("keep"))
    del original["Slot"]
    root = nbt.CompoundTag({"Offhand": nbt.ListTag([original], 10)})
    payload = {
        "slot": -106,
        "name": "minecraft:firework_rocket",
        "count": 1,
        "damage": 0,
        "special_edit": {"kind": "fireworks", "data": {"flight": 3, "explosions": [effect()]}},
    }
    apply_root_equipment_writes(root, [payload], ENCHANTMENTS)
    assert "Slot" not in root["Offhand"][0]
    assert root["Offhand"][0]["tag"]["Fireworks"]["Flight"].py_data == 3
    assert root["Offhand"][0]["tag"]["addon"].py_data == "keep"
