"""Official component absence and malformed input have distinct update semantics."""

from __future__ import annotations

import copy
import io
import json
import zipfile

import pytest

from mcbe_editor import _inventory_core, item_data
from tests.test_update_db import update_db
from tests.test_update_source_quality import _members
from tests.test_update_source_quality import updater as updater

ITEM_ID = "minecraft:component_probe"
MEMBER = "behavior_pack/items/component_probe.json"


def _definition():
    return {
        "minecraft:item": {
            "description": {"identifier": ITEM_ID},
            "components": {
                "minecraft:max_stack_size": 1,
                "minecraft:durability": {"max_durability": 190},
                "minecraft:enchantable": {"slot": "melee_spear", "value": 13},
            },
        }
    }


def _source(definition):
    members = _members()
    registry = json.loads(members["metadata/vanilladata_modules/mojang-items.json"])
    registry["data_items"].append({"name": ITEM_ID})
    members["metadata/vanilladata_modules/mojang-items.json"] = json.dumps(registry)
    members["resource_pack/texts/de_DE.lang"] += "item.component_probe.name=Quellenprobe\n"
    members["resource_pack/texts/en_US.lang"] += "item.component_probe.name=Source Probe\n"
    members[MEMBER] = json.dumps(definition)
    return members


def _parse(definition):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(MEMBER, json.dumps(definition))
    with zipfile.ZipFile(io.BytesIO(buffer.getvalue())) as archive:
        return update_db.parse_json_item_components(archive)


@pytest.mark.parametrize(
    "path,value",
    [
        ((), None),
        ((), []),
        ((), {}),
        (("minecraft:item",), None),
        (("minecraft:item",), []),
        (("minecraft:item", "description"), None),
        (("minecraft:item", "description"), []),
        (("minecraft:item", "description"), {}),
        *((("minecraft:item", "description", "identifier"), value) for value in (None, True, 7, "", "minecraft:bad ID", "other:probe")),
        *((("minecraft:item", "components"), value) for value in (None, [], True, "components")),
    ],
)
def test_malformed_item_structure_is_not_silently_removed(path, value):
    definition = _definition()
    if path:
        target = definition
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
    else:
        definition = value
    with pytest.raises(RuntimeError, match="component_probe.json"):
        _parse(definition)


@pytest.mark.parametrize(
    "component", [None, [], True, 190, {}, {"max_durability": None}, *({"max_durability": value} for value in (True, False, "190", 1.5, -1, 32768))]
)
def test_present_invalid_durability_is_a_source_error(component):
    definition = _definition()
    definition["minecraft:item"]["components"]["minecraft:durability"] = component
    with pytest.raises(RuntimeError, match="minecraft:durability.*component_probe.json"):
        _parse(definition)


@pytest.mark.parametrize("missing", [False, True])
def test_optional_components_may_be_empty_or_omitted(missing):
    definition = _definition()
    definition["minecraft:item"]["components"] = {}
    if missing:
        del definition["minecraft:item"]["components"]
    assert _parse(definition) == ({}, {}, {name: {} for name in update_db.TRACKED_ITEM_COMPONENTS})


@pytest.mark.parametrize("damage", ["components", "durability", "identifier"])
@pytest.mark.parametrize("dry_run", [False, True])
def test_structural_damage_preserves_complete_section_and_allows_repair(updater, damage, dry_run):
    valid = _definition()
    updater.write_source(_source(valid))
    assert updater.run()[0] == 0
    original = updater.read_db()
    original["effects"] = {}
    updater.write_db(original)
    before = updater.snapshot()
    broken = copy.deepcopy(valid)
    if damage == "components":
        broken["minecraft:item"]["components"] = []
    elif damage == "durability":
        broken["minecraft:item"]["components"]["minecraft:durability"]["max_durability"] = True
    else:
        broken["minecraft:item"]["description"]["identifier"] = None
    updater.write_source(_source(broken))

    code, report = updater.run(*(("--dry-run",) if dry_run else ()))

    assert code == 1
    assert report["quality"]["sections"]["items"]["status"] == "blocked"
    assert report["quality"]["sections"]["effects"]["status"] == "checked"
    if dry_run:
        assert updater.snapshot() == before
    else:
        result = updater.read_db()
        for key in original.keys() - {"schema_version", "effects", "enchantments"}:
            assert result[key] == original[key], key
        assert "38" in result["effects"]
        assert "verification" not in updater.read_metadata()
    catalog = item_data.prepare_item_catalog(update_db.ITEM_DB_PATH)
    assert catalog["DURABILITY"][ITEM_ID] == 190
    assert catalog["ITEM_COMPONENTS"]["enchantable"][ITEM_ID] == {"slot": "melee_spear", "value": 13}

    updater.write_source(_source(valid))
    assert updater.run()[0] == 0
    assert update_db.item_db_verification.item_db_verification_snapshot(updater.read_metadata(), update_db.ITEM_DB_PATH)["verified"]


def test_valid_removal_of_optional_components_is_published(updater):
    definition = _definition()
    updater.write_source(_source(definition))
    assert updater.run()[0] == 0
    definition["minecraft:item"]["components"] = {"minecraft:max_stack_size": 1}
    updater.write_source(_source(definition))

    code, report = updater.run()

    assert code == 0 and report["quality"]["sections"]["items"]["status"] == "checked"
    catalog = item_data.prepare_item_catalog(update_db.ITEM_DB_PATH)
    assert ITEM_ID not in catalog["DURABILITY"]
    assert ITEM_ID not in catalog["ITEM_COMPONENTS"]["enchantable"]
    assert update_db.item_db_verification.item_db_verification_snapshot(updater.read_metadata(), update_db.ITEM_DB_PATH)["verified"]


@pytest.mark.parametrize("durability", [0, 32767])
def test_valid_durability_bounds_survive_full_update_and_runtime_reload(updater, durability):
    definition = _definition()
    definition["minecraft:item"]["components"]["minecraft:durability"]["max_durability"] = durability
    updater.write_source(_source(definition))

    code, report = updater.run()

    assert code == 0 and report["quality"]["sections"]["items"]["status"] == "checked"
    catalog = item_data.prepare_item_catalog(update_db.ITEM_DB_PATH)
    with item_data.use_item_catalog(catalog):
        assert item_data.get_max_damage(ITEM_ID) == durability
        assert _inventory_core._item_is_damageable(ITEM_ID)
        payload = {"slot": 0, "name": ITEM_ID, "count": 1, "damage": durability}
        assert _inventory_core.validate_inventory_item(payload, {})["damage"] == durability
        with pytest.raises(ValueError, match="Damage"):
            _inventory_core.validate_inventory_item({**payload, "damage": durability + 1}, {})
    assert update_db.item_db_verification.item_db_verification_snapshot(updater.read_metadata(), update_db.ITEM_DB_PATH)["verified"]


def _parse_definitions(*definitions):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for index, definition in enumerate(definitions):
            archive.writestr(f"behavior_pack/items/probe_{index}.json", json.dumps(definition))
    with zipfile.ZipFile(io.BytesIO(buffer.getvalue())) as archive:
        return update_db.parse_json_item_components(archive)


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("remove", [False, True])
@pytest.mark.parametrize(
    "component,changed",
    [
        ("minecraft:max_stack_size", 16),
        ("minecraft:durability", {"max_durability": 1}),
        ("minecraft:enchantable", {"slot": "armor_head", "value": 1}),
        ("minecraft:wearable", {"slot": "slot.armor.chest", "protection": 2}),
        ("minecraft:allow_off_hand", True),
    ],
)
def test_duplicate_identity_rejects_any_consumed_component_conflict(component, changed, remove, reverse):
    first = _definition()
    first["minecraft:item"]["components"].update({"minecraft:wearable": {"slot": "slot.armor.head", "protection": 1}, "minecraft:allow_off_hand": False})
    second = copy.deepcopy(first)
    if remove:
        del second["minecraft:item"]["components"][component]
    else:
        second["minecraft:item"]["components"][component] = changed
    definitions = (second, first) if reverse else (first, second)
    with pytest.raises(RuntimeError, match="widersprüchliche Itemkomponenten.*minecraft:component_probe"):
        _parse_definitions(*definitions)


@pytest.mark.parametrize("identifier", [ITEM_ID, "component_probe", "MINECRAFT:COMPONENT_PROBE", " minecraft:component_probe "])
def test_duplicate_identity_compares_normalized_consumed_values_only(identifier):
    first = _definition()
    first["minecraft:item"]["components"]["minecraft:allow_off_hand"] = False
    second = copy.deepcopy(first)
    second["minecraft:item"]["description"]["identifier"] = identifier
    second["minecraft:item"]["components"].update(
        {
            "minecraft:max_stack_size": {"value": 1},
            "minecraft:allow_off_hand": {"value": False},
            "minecraft:unconsumed_probe": {"unrelated": [1, 2, 3]},
        }
    )
    assert _parse_definitions(first, second) == _parse_definitions(first)


def test_duplicate_empty_definition_treats_omitted_and_empty_components_equally():
    first = _definition()
    first["minecraft:item"]["components"] = {}
    second = copy.deepcopy(first)
    del second["minecraft:item"]["components"]
    assert _parse_definitions(first, second) == _parse_definitions(first)


def test_duplicate_component_conflict_preserves_reviewed_section_through_apply_and_repair(updater):
    valid = _definition()
    updater.write_source(_source(valid))
    assert updater.run()[0] == 0
    original = updater.read_db()
    original["effects"] = {}
    updater.write_db(original)
    before = updater.snapshot()
    second = copy.deepcopy(valid)
    second["minecraft:item"]["components"].update({"minecraft:durability": {"max_durability": 1}, "minecraft:enchantable": {"slot": "armor_head", "value": 1}})
    members = _source(valid)
    members["behavior_pack/items/duplicate_probe.json"] = json.dumps(second)
    updater.write_source(members)

    code, preview = updater.run("--dry-run")

    assert code == 1
    assert updater.snapshot() == before
    assert preview["quality"]["sections"]["items"]["status"] == "blocked"
    review = update_db.item_db_verification.update_review_snapshot(
        update_cache_dir=update_db.CACHE_DIR,
        item_db_path=update_db.ITEM_DB_PATH,
        source_version_path=update_db.SOURCE_VERSION_JSON,
        source_version_history_path=update_db.SOURCE_VERSION_HISTORY,
        scope=None,
    )
    code, applied = updater.run("--expected-review-token", review["token"])

    assert code == 1 and applied["applied"]
    assert applied["blocked"] == preview["blocked"]
    assert applied["sections"]["items"] == preview["sections"]["items"] == {"added": 0, "removed": 0, "changed": 0}
    for key in original.keys() - {"schema_version", "effects", "enchantments"}:
        assert updater.read_db()[key] == original[key], key
    assert "38" in updater.read_db()["effects"]
    assert "verification" not in updater.read_metadata()
    catalog = item_data.prepare_item_catalog(update_db.ITEM_DB_PATH)
    assert catalog["DURABILITY"][ITEM_ID] == 190
    assert catalog["ITEM_COMPONENTS"]["enchantable"][ITEM_ID] == {"slot": "melee_spear", "value": 13}

    updater.write_source(_source(valid))
    assert updater.run()[0] == 0
    assert update_db.item_db_verification.item_db_verification_snapshot(updater.read_metadata(), update_db.ITEM_DB_PATH)["verified"]
