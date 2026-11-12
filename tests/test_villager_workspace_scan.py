"""Each workspace validation shares discovery only inside its current DB view."""

from unittest.mock import Mock

import pytest

from mcbe_editor import nbt, villager_service
from mcbe_editor.bedrock_nbt import LOAD_KWARGS, SAVE_KWARGS
from mcbe_editor.villagers import prepare_villager_changes, scan_villagers
from tests.test_entities import add_actor, entity_tag
from tests.test_villager_inventory import _populated_inventory_db
from tests.test_villagers import selection


def _previews(db):
    chosen = selection(scan_villagers(db))
    changes = [
        {"max_health": 40, "heal": True},
        {"name": "Egon"},
        {"inventory": [{"slot": 7, "item": {"name": "minecraft:carrot", "count": 4}}]},
    ]
    return [
        {"selection": chosen, "changes": change, "plan_digest": villager_service.plan_digest(prepare_villager_changes(db, chosen, change))}
        for change in changes
    ]


@pytest.mark.parametrize("reverse", [False, True])
def test_workspace_shares_one_scan_and_combines_disjoint_fields_losslessly(reverse):
    db, key = _populated_inventory_db()
    previews = _previews(db)
    if reverse:
        previews.reverse()
    before = dict(db.records)
    db.iter_items = Mock(wraps=db.iter_items)

    plan = villager_service.prepare_workspace_changes(db, previews)

    assert db.iter_items.call_count == 1
    assert db.records == before
    assert plan.before_records == before
    assert set(plan.writes) == {key}
    after = nbt.load(plan.writes[key], **LOAD_KWARGS)
    assert after.tag["CustomName"].py_data == "Egon"
    assert after.tag["ChestItems"][7]["Name"].py_data == "minecraft:carrot"
    assert after.tag["ChestItems"][7]["Count"].py_data == 4
    assert after.tag["Attributes"][0]["Current"].py_data == after.tag["Attributes"][0]["Max"].py_data == 40
    original = nbt.load(before[key], **LOAD_KWARGS)
    for field in ("CustomName", "ChestItems", "Attributes"):
        after.tag[field] = original.tag[field]
    assert after.save_to(**SAVE_KWARGS) == before[key]


def test_workspace_still_refuses_overlapping_field_edits():
    db, _ = _populated_inventory_db()
    previews = _previews(db)
    before = dict(db.records)
    with pytest.raises(ValueError, match="denselben"):
        villager_service.prepare_workspace_changes(db, [*previews, previews[1]])
    assert db.records == before


@pytest.mark.parametrize("change", ["actor", "index", "identity"])
def test_next_workspace_validation_scans_again_and_rejects_new_stale_evidence(change):
    db, key = _populated_inventory_db()
    previews = _previews(db)
    db.iter_items = Mock(wraps=db.iter_items)
    assert villager_service.prepare_workspace_changes(db, previews).writes
    assert db.iter_items.call_count == 1

    if change == "actor":
        actor = nbt.load(db.records[key], **LOAD_KWARGS)
        actor.tag["CustomName"] = nbt.StringTag("Changed after preview")
        db.records[key] = actor.save_to(**SAVE_KWARGS)
    elif change == "index":
        del db.records[next(key for key in db.records if key.startswith(b"digp"))]
    else:
        actor = nbt.load(db.records[key], **LOAD_KWARGS)
        add_actor(db, entity_tag(actor.tag["UniqueID"].py_data, identifier="minecraft:cow"), suffix=b"othermob")
    changed = dict(db.records)

    with pytest.raises(ValueError):
        villager_service.prepare_workspace_changes(db, previews)
    assert db.iter_items.call_count == 2
    assert db.records == changed
