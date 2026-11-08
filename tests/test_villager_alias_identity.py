"""Editor aliases follow legacy villagers, never their reused chunk-list slots."""

from __future__ import annotations

import struct

import pytest

from mcbe_editor import nbt
from mcbe_editor.bedrock_nbt import SAVE_KWARGS
from mcbe_editor.villager_preferences import VillagerPreferences
from mcbe_editor.villagers import load_villager_detail, scan_villagers
from tests.test_entities import EntityDb, add_actor, entity_tag


def _legacy_db(roots, *, chunk=(0, 0)):
    key = struct.pack("<ii", *chunk) + b"\x32"
    raw = b"".join(nbt.NamedTag(root).save_to(**SAVE_KWARGS) for root in roots)
    return EntityDb({key: raw})


@pytest.mark.parametrize("change", ["remove_first", "reorder", "move_chunk"])
def test_saved_legacy_aliases_follow_exact_identity_across_chunk_changes(tmp_path, change):
    first_id, second_id = 9007199254740992, 9007199254740993
    first = entity_tag(first_id, identifier="minecraft:villager")
    second = entity_tag(second_id, identifier="minecraft:villager")
    before = scan_villagers(_legacy_db([first, second]))["villagers"]
    store = VillagerPreferences(tmp_path / "preferences")
    preferences = store.read("world")
    saved = store.save(
        "world",
        revision=preferences["revision"],
        aliases={before[0]["alias_key"]: "Erster Bewohner", before[1]["alias_key"]: "Zweiter Bewohner"},
        regions=[],
    )

    if change == "remove_first":
        changed = _legacy_db([second])
    elif change == "reorder":
        changed = _legacy_db([second, first])
    else:
        second["Pos"] = nbt.ListTag([nbt.FloatTag(17), nbt.FloatTag(64), nbt.FloatTag(2)])
        changed = _legacy_db([second], chunk=(1, 0))
    after = scan_villagers(changed)["villagers"]
    survivor = next(row for row in after if row["unique_id"] == str(second_id))

    assert survivor["id"] != before[1]["id"]
    assert survivor["alias_key"] == before[1]["alias_key"]
    assert survivor["alias_key"] != before[0]["alias_key"]
    assert saved["aliases"][survivor["alias_key"]] == "Zweiter Bewohner"
    if change != "move_chunk":
        # The old positional ID is now occupied by a different villager.
        assert survivor["id"] == before[0]["id"]
    detail = load_villager_detail(changed, survivor["id"], survivor["revision"])
    assert detail["alias_key"] == survivor["alias_key"]


@pytest.mark.parametrize("unique_id", [-(2**63), 9007199254740993, 2**63 - 1])
def test_legacy_alias_key_keeps_signed_64_bit_identity_exact(unique_id):
    row = scan_villagers(_legacy_db([entity_tag(unique_id)]))["villagers"][0]
    assert row["alias_key"] == f"legacy-uid:{unique_id}"


@pytest.mark.parametrize("identity", [None, nbt.IntTag(42), nbt.StringTag("42"), nbt.FloatTag(42)])
def test_legacy_aliases_require_a_typed_unique_identity(identity):
    tag = entity_tag(42)
    if identity is None:
        del tag["UniqueID"]
    else:
        tag["UniqueID"] = identity
    row = scan_villagers(_legacy_db([tag]))["villagers"][0]
    assert row["alias_key"] is None


@pytest.mark.parametrize("other_storage", ["legacy", "actor"])
def test_legacy_aliases_reject_duplicate_identity_outside_the_villager_filter(other_storage):
    villager = entity_tag(42)
    cow = entity_tag(42, identifier="minecraft:cow")
    db = _legacy_db([villager, cow] if other_storage == "legacy" else [villager])
    if other_storage == "actor":
        add_actor(db, cow)
    row = scan_villagers(db)["villagers"][0]
    assert row["alias_key"] is None


def test_modern_alias_keys_remain_compatible_with_saved_preferences():
    db = EntityDb()
    add_actor(db, entity_tag(9007199254740993))
    row = scan_villagers(db)["villagers"][0]
    assert row["alias_key"] == row["id"]
