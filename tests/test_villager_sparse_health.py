"""Regression coverage for BDS attributes that omit default-valued fields.

These fixtures model the native form observed in BDS 1.26.61.1. They test the
editor contract; actual engine acceptance belongs to the BDS villager profile.
"""

from __future__ import annotations

import pytest

from mcbe_editor import nbt
from mcbe_editor.bedrock_nbt import LOAD_KWARGS, SAVE_KWARGS
from mcbe_editor.villagers import prepare_health_changes, prepare_villager_changes, scan_villagers
from tests.test_villager_inventory import _supplies
from tests.test_villagers import populated_db, selection


def _native_db(*, current=None, health_changes=None, remove=(), root_changes=None):
    db, key = populated_db()
    root = nbt.load(db.records[key], **LOAD_KWARGS)
    health = nbt.CompoundTag(
        {
            "Base": nbt.FloatTag(20),
            "DefaultMax": nbt.FloatTag(20),
            "DefaultMin": nbt.FloatTag(0),
            "Name": nbt.StringTag("minecraft:health"),
        }
    )
    if current is not None:
        health["Current"] = nbt.FloatTag(current)
    if health_changes:
        health.update(health_changes)
    for field in remove:
        health.pop(field)
    root.tag["Attributes"] = nbt.ListTag([health])
    root.tag["ChestItems"] = _supplies()
    if root_changes:
        root.tag.update(root_changes)
    db.records[key] = root.save_to(**SAVE_KWARGS)
    return db, key


def _plan(db, changes):
    return prepare_health_changes(db, selection(scan_villagers(db)), changes)


@pytest.mark.parametrize("current, expected_current, injured", [(None, 20, 0), (6, 6, 1)])
def test_native_sparse_health_is_readable_editable_and_counted_as_injured(current, expected_current, injured):
    db, _ = _native_db(current=current)
    before = dict(db.records)
    result = scan_villagers(db)
    row = result["villagers"][0]
    assert row["health"] == {"current": expected_current, "max": 20, "editable": True, "max_editable": True, "reason": None}
    assert row["editable"] and row["inventory_editable"]
    assert result["summary"]["injured"] == injured
    assert db.records == before


@pytest.mark.parametrize(
    "fields, remove, expected_current, expected_max, max_editable",
    [
        ({"Current": nbt.FloatTag(7)}, (), 7, 20, True),
        ({"Max": nbt.FloatTag(40), "DefaultMax": nbt.FloatTag(40)}, (), 20, 40, True),
        ({"Current": nbt.FloatTag(7), "Max": nbt.FloatTag(40)}, (), 7, 40, False),
        ({"Current": nbt.FloatTag(7)}, ("Base",), 7, 20, True),
        ({"Current": nbt.FloatTag(7), "Max": nbt.FloatTag(20)}, ("Base", "DefaultMax"), 7, 20, True),
    ],
)
def test_explicit_health_values_have_precedence_and_do_not_require_unused_defaults(fields, remove, expected_current, expected_max, max_editable):
    db, _ = _native_db(health_changes=fields, remove=remove)
    health = scan_villagers(db)["villagers"][0]["health"]
    assert health["editable"]
    assert (health["current"], health["max"], health["max_editable"]) == (expected_current, expected_max, max_editable)


@pytest.mark.parametrize("field", ["Current", "Max", "Base", "DefaultMax"])
@pytest.mark.parametrize("value", [nbt.IntTag(20), nbt.DoubleTag(20), nbt.StringTag("20"), nbt.FloatTag(float("nan")), nbt.FloatTag(float("inf"))])
def test_wrong_or_nonfinite_explicit_tags_and_fallback_sources_never_gain_edit_permission(field, value):
    db, _ = _native_db(health_changes={field: value})
    before = dict(db.records)
    row = scan_villagers(db)["villagers"][0]
    assert not row["editable"] and not row["health"]["max_editable"]
    for changes in ({"heal": True}, {"current_health": 7}, {"max_health": 40, "heal": True}):
        plan = _plan(db, changes)
        assert not plan.writes and plan.summary["skipped"] == 1
    assert db.records == before


@pytest.mark.parametrize("missing", [("Base",), ("DefaultMax",), ("Base", "DefaultMax")])
def test_missing_native_value_sources_are_not_replaced_with_vanilla_constants(missing):
    db, _ = _native_db(remove=missing)
    health = scan_villagers(db)["villagers"][0]["health"]
    assert not health["editable"]
    if "Base" in missing:
        assert health["current"] is None
    if "DefaultMax" in missing:
        assert health["max"] is None
    assert not _plan(db, {"heal": True}).writes


@pytest.mark.parametrize(
    "changes",
    [{"heal": True}, {"current_health": 20}, {"max_health": 20}, {"current_health": 20, "max_health": 20}],
)
def test_sparse_noop_preserves_original_bytes_without_materializing_defaults(changes):
    db, key = _native_db()
    before = dict(db.records)
    plan = _plan(db, changes)
    assert plan.summary == {"selected": 1, "changed": 0, "skipped": 0, "unchanged": 1}
    assert not plan.writes and plan.before_records[key] == before[key]
    assert db.records == before
    health = nbt.load(before[key], **LOAD_KWARGS).tag["Attributes"][0]
    assert "Current" not in health and "Max" not in health


@pytest.mark.parametrize(
    "current, changes, expected_current, expected_max, added_fields",
    [
        (6, {"heal": True}, 20, 20, set()),
        (None, {"current_health": 7}, 7, 20, {"Current"}),
        (None, {"current_health": 1.5}, 1.5, 20, {"Current"}),
        (None, {"max_health": 40}, 20, 40, {"Max"}),
        (None, {"max_health": 40, "heal": True}, 40, 40, {"Current", "Max"}),
        (6, {"max_health": 2048, "current_health": 2048}, 2048, 2048, {"Max"}),
    ],
)
def test_sparse_edits_materialize_only_changed_values_and_preserve_every_other_byte(current, changes, expected_current, expected_max, added_fields):
    db, key = _native_db(current=current)
    before = dict(db.records)
    plan = _plan(db, changes)
    assert plan.summary["changed"] == 1 and set(plan.writes) == {key}
    assert db.records == before
    old = nbt.load(before[key], **LOAD_KWARGS)
    updated = nbt.load(plan.writes[key], **LOAD_KWARGS)
    old_health, new_health = old.tag["Attributes"][0], updated.tag["Attributes"][0]
    assert set(new_health) - set(old_health) == added_fields
    assert new_health["Base"].py_data == 20
    assert new_health["DefaultMax"].py_data == expected_max
    for field in ("Current", "Max"):
        if field in new_health:
            assert isinstance(new_health[field], nbt.FloatTag)
    assert plan.rows[0]["after"] == {"current": expected_current, "max": expected_max}
    db.records.update(plan.writes)
    health = scan_villagers(db)["villagers"][0]["health"]
    assert (health["current"], health["max"], health["editable"]) == (expected_current, expected_max, True)
    assert not _plan(db, changes).writes
    updated.tag["Attributes"] = old.tag["Attributes"]
    assert updated.save_to(**SAVE_KWARGS) == before[key]


def test_lowering_a_previously_raised_native_maximum_clamps_current_without_rewriting_base():
    db, key = _native_db()
    raised = _plan(db, {"max_health": 40, "heal": True})
    db.records.update(raised.writes)
    lowered = _plan(db, {"max_health": 20})
    assert lowered.rows[0]["after"] == {"current": 20, "max": 20}
    health = nbt.load(lowered.writes[key], **LOAD_KWARGS).tag["Attributes"][0]
    assert [health[field].py_data for field in ("Current", "Max", "DefaultMax", "Base")] == [20, 20, 20, 20]
    assert not _plan(db, {"max_health": 19}).writes


def test_sparse_current_respects_an_explicit_maximum_with_an_uncoupled_default_max():
    db, key = _native_db(health_changes={"Max": nbt.FloatTag(40)})
    assert not _plan(db, {"max_health": 60}).writes
    healed = _plan(db, {"heal": True})
    health = nbt.load(healed.writes[key], **LOAD_KWARGS).tag["Attributes"][0]
    assert (health["Current"].py_data, health["Max"].py_data, health["DefaultMax"].py_data) == (40, 40, 20)


@pytest.mark.parametrize(
    "health_changes, root_changes",
    [
        ({"Modifiers": nbt.ListTag([nbt.CompoundTag({"amount": nbt.FloatTag(2)})])}, {}),
        ({}, {"AttributeModifiers": nbt.ListTag([nbt.CompoundTag()])}),
        ({}, {"ActiveEffects": nbt.ListTag([nbt.CompoundTag({"Id": nbt.ByteTag(21)})])}),
        ({}, {"Health": nbt.ShortTag(20)}),
        ({}, {"Dead": nbt.ByteTag(1)}),
        ({}, {"DeathTime": nbt.ShortTag(1)}),
    ],
)
def test_native_defaults_do_not_bypass_modifiers_or_lifecycle_guards(health_changes, root_changes):
    db, _ = _native_db(health_changes=health_changes, root_changes=root_changes)
    before = dict(db.records)
    assert not scan_villagers(db)["villagers"][0]["editable"]
    assert not _plan(db, {"max_health": 40, "heal": True}).writes
    assert db.records == before


@pytest.mark.parametrize("field,value", [("Base", 0), ("Base", -1), ("Current", 0), ("Current", -1)])
def test_native_dead_health_blocks_both_health_and_supply_changes(field, value):
    db, _ = _native_db(health_changes={field: nbt.FloatTag(value)})
    scan = scan_villagers(db)
    row = scan["villagers"][0]
    assert not row["editable"] and not row["inventory_editable"]
    assert not _plan(db, {"heal": True}).writes
    supplies = prepare_villager_changes(db, selection(scan), {"inventory": [{"slot": 0, "item": None}]})
    assert not supplies.writes


def test_explicit_live_current_overrides_zero_base_for_supply_lifecycle_checks():
    db, _ = _native_db(current=6, health_changes={"Base": nbt.FloatTag(0)})
    row = scan_villagers(db)["villagers"][0]
    assert row["editable"] and row["inventory_editable"]
