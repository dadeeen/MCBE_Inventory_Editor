"""Lightweight list capabilities retain the full inventory's conservative rules."""

import copy

import pytest
from flask import Flask

from mcbe_editor import item_data, nbt, villager_inventory, villagers
from tests.test_entities import EntityDb, add_actor, entity_tag
from tests.test_villager_inventory import _slot, _supplies


def _inventory_tag(form):
    tag = entity_tag()
    tag["ChestItems"] = _supplies()
    if form == "missing":
        del tag["ChestItems"]
    elif form == "wrong_container":
        tag["ChestItems"] = nbt.StringTag("opaque")
    elif form == "wrong_list_type":
        tag["ChestItems"] = nbt.ListTag([nbt.IntTag(index) for index in range(8)])
    elif form == "seven_slots":
        tag["ChestItems"].pop()
    elif form == "nine_slots":
        tag["ChestItems"].append(_slot(8))
    elif form == "duplicate_tail_slot":
        tag["ChestItems"][7]["Slot"] = nbt.ByteTag(0)
    elif form == "wrong_tail_slot_type":
        tag["ChestItems"][7]["Slot"] = nbt.IntTag(7)
    elif form in {"Inventory", "Items"}:
        tag[form] = nbt.ListTag()
    elif form == "unknown_first_slot":
        tag["ChestItems"][0]["Opaque"] = nbt.IntTag(5)
    elif form == "all_unknown_slots":
        for slot in tag["ChestItems"]:
            slot["Opaque"] = nbt.IntTag(5)
    elif form == "all_wrong_counts":
        for slot in tag["ChestItems"]:
            slot["Count"] = nbt.ShortTag(0)
    elif form == "all_unsupported_items":
        tag["ChestItems"] = nbt.ListTag([_slot(index, "minecraft:diamond", 1) for index in range(8)])
    elif form == "all_empty":
        tag["ChestItems"] = nbt.ListTag([_slot(index) for index in range(8)])
    elif form == "all_bread":
        tag["ChestItems"] = nbt.ListTag([_slot(index, "minecraft:bread", 12) for index in range(8)])
    return tag


@pytest.mark.parametrize("locale", ["de", "en"])
@pytest.mark.parametrize("blocked", [None, "Actor identity is ambiguous"])
@pytest.mark.parametrize(
    "form,editable",
    [
        ("native", True),
        ("all_empty", True),
        ("missing", False),
        ("wrong_container", False),
        ("wrong_list_type", False),
        ("seven_slots", False),
        ("nine_slots", False),
        ("duplicate_tail_slot", False),
        ("wrong_tail_slot_type", False),
        ("Inventory", False),
        ("Items", False),
        ("unknown_first_slot", True),
        ("all_unknown_slots", False),
        ("all_wrong_counts", False),
        ("all_unsupported_items", False),
    ],
)
def test_list_inventory_capability_matches_full_details_without_mutation(locale, blocked, form, editable):
    tag = _inventory_tag(form)
    before = tag.save_to()
    with Flask(__name__).test_request_context(headers={"Accept-Language": locale}):
        full = villager_inventory.inventory_state(tag, blocked_reason=blocked)
        quick = villager_inventory.inventory_editable(tag, blocked_reason=blocked)
    assert quick is (editable and blocked is None)
    assert quick == full["editable"]
    assert tag.save_to() == before


@pytest.mark.parametrize("locale", ["de", "en"])
def test_list_inventory_capability_uses_the_current_catalog_and_stack_limits(locale):
    tag = _inventory_tag("all_bread")
    original = item_data.catalog_values()
    with Flask(__name__).test_request_context(headers={"Accept-Language": locale}):
        for allowed, maximum, expected in [(True, 64, True), (False, 64, False), (True, 2, False), (True, 64, True)]:
            catalog = {
                **original,
                "ADDABLE_ITEM_IDS": frozenset({"minecraft:bread"}) if allowed else frozenset(),
                "STACK_LIMITS": {**original["STACK_LIMITS"], "minecraft:bread": maximum},
            }
            with item_data.use_item_catalog(catalog):
                assert villager_inventory.inventory_editable(tag) is expected
                assert villager_inventory.inventory_state(tag)["editable"] is expected


@pytest.mark.parametrize("protected", ["none", "orphan", "duplicate_identity", "dead", "legacy"])
def test_list_scan_avoids_detail_allocation_but_keeps_actor_protection(monkeypatch, protected):
    tag = _inventory_tag("native")
    if protected == "dead":
        tag["Dead"] = nbt.ByteTag(1)
    elif protected == "legacy":
        tag["identifier"] = nbt.StringTag("minecraft:villager")
    db = EntityDb()
    add_actor(db, tag, with_index=protected != "orphan")
    if protected == "duplicate_identity":
        add_actor(db, entity_tag(identifier="minecraft:cow"), suffix=b"abcdefgh")
    original_records = copy.deepcopy(db.records)

    def details_are_not_needed(*_args, **_kwargs):
        raise AssertionError("List rows must not build the complete inventory detail payload")

    with monkeypatch.context() as scoped:
        scoped.setattr(villagers, "inventory_state", details_are_not_needed)
        result = villagers.scan_villagers(db)
    row = result["villagers"][0]
    assert row["inventory_editable"] is (protected == "none")
    detail = villagers.load_villager_detail(db, row["id"], row["revision"])
    assert detail["inventory"]["editable"] == row["inventory_editable"]
    assert detail["inventory"]["capacity"] == 8
    assert len(detail["inventory"]["slots"]) == 8
    assert db.records == original_records
