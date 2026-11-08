"""Real-name patches preserve actor data and reject ambiguous inputs."""

import pytest

from mcbe_editor import nbt
from mcbe_editor.bedrock_nbt import LOAD_KWARGS, SAVE_KWARGS
from mcbe_editor.villagers import normalize_name_changes, prepare_villager_changes, scan_villagers
from tests.test_entities import EntityDb, add_actor, entity_tag
from tests.test_villagers import populated_db, selection


@pytest.mark.parametrize("name", ["Egon (Braune Wolle)", "Jörg <&> 🐑", "Ä" * 79 + "🌾", "", "  Egon  "])
@pytest.mark.parametrize("original", [None, "", "Alter Name"])
def test_name_set_rename_remove_is_lossless_and_repeat_is_noop(name, original):
    db, key = populated_db()
    root = nbt.load(db.records[key], **LOAD_KWARGS)
    if original is None:
        del root.tag["CustomName"]
    else:
        root.tag["CustomName"] = nbt.StringTag(original)
    root.tag["CustomNameVisible"] = nbt.ByteTag(1)
    root.tag["AlwaysShowName"] = nbt.ByteTag(0)
    db.records[key] = root.save_to(**SAVE_KWARGS)
    before = dict(db.records)
    plan = prepare_villager_changes(db, selection(scan_villagers(db)), {"name": name})
    assert db.records == before
    assert plan.rows[0]["kind"] == "name"
    assert plan.rows[0]["before"] == {"name": original or ""}
    assert plan.rows[0]["after"] == {"name": name.strip()}
    assert bool(plan.writes) == (name.strip() != (original or ""))
    db.records.update(plan.writes)
    after = nbt.load(db.records[key], **LOAD_KWARGS).tag
    if name.strip():
        assert isinstance(after["CustomName"], nbt.StringTag)
        assert after["CustomName"].py_data == name.strip()
    elif original:
        assert "CustomName" not in after
    for field, value in root.tag.items():
        if field != "CustomName":
            assert after[field].save_to() == value.save_to(), field
    assert all(db.records[k] == v for k, v in before.items() if k != key)
    repeat = prepare_villager_changes(db, selection(scan_villagers(db)), {"name": name})
    assert not repeat.writes and repeat.summary["unchanged"] == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"name": None},
        {"name": 12},
        {"name": True},
        {"name": []},
        {"name": "x", "heal": True},
        {"name": "x", "inventory": []},
        {"name": "Ä" * 81},
        {"name": "🐑" * 81},
        *[{"name": value} for value in ["\n", "Egon\x00", "\tEgon", "X\ud800", "X\udcff", "X\x7f", "X\u2028"]],
    ],
)
def test_invalid_names_cannot_be_normalized_into_changes(changes):
    with pytest.raises(ValueError):
        normalize_name_changes(changes)


@pytest.mark.parametrize("fault", ["type", "dead", "dying", "zero_health", "legacy", "orphan", "duplicate"])
def test_unsafe_name_records_are_read_only(fault):
    db = EntityDb()
    tag = entity_tag()
    if fault == "type":
        tag["CustomName"] = nbt.IntTag(3)
    elif fault in {"dead", "dying"}:
        tag["Dead" if fault == "dead" else "DeathTime"] = nbt.ShortTag(1)
    elif fault == "zero_health":
        tag["Attributes"][0]["Current"] = nbt.FloatTag(0)
    elif fault == "legacy":
        tag["identifier"] = nbt.StringTag("minecraft:villager")
    add_actor(db, tag, with_index=fault != "orphan")
    if fault == "duplicate":
        add_actor(db, entity_tag(identifier="minecraft:cow"), suffix=b"abcdefgh")
    scan = scan_villagers(db)
    row = scan["villagers"][0]
    assert row["name_editable"] is False and row["name_reason"]
    plan = prepare_villager_changes(db, selection(scan), {"name": "Egon"})
    assert not plan.writes and plan.summary["skipped"] == 1


def test_name_patch_rejects_stale_actor_and_multiple_selection():
    db, _ = populated_db()
    chosen = selection(scan_villagers(db))
    with pytest.raises(ValueError):
        prepare_villager_changes(db, [{**chosen[0], "revision": "0" * 64}], {"name": "Egon"})
    add_actor(db, entity_tag(99), suffix=b"abcdefgh")
    with pytest.raises(ValueError):
        prepare_villager_changes(db, selection(scan_villagers(db)), {"name": "Egon"})
