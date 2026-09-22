import pytest

from mcbe_editor.inventory import validate_inventory_item


@pytest.mark.parametrize("slot", [None, True, "invalid", 1.5, -1, 36, 104])
def test_explicit_invalid_source_slot_is_rejected(slot):
    with pytest.raises(ValueError, match="Quellslot"):
        validate_inventory_item({"slot": 0, "name": "minecraft:stone", "count": 1, "source_slot": slot}, {})


def test_source_slot_is_validated_against_source_container():
    payload = {"slot": 0, "name": "minecraft:stone", "count": 1, "source_slot": 30, "source_container": "ender_chest"}
    with pytest.raises(ValueError, match="Quellslot"):
        validate_inventory_item(payload, {})
    payload["source_container"] = "inventory"
    assert validate_inventory_item(payload, {})["source_slot"] == 30
    payload["source_slot"] = 100
    assert validate_inventory_item(payload, {})["source_slot"] == 100
