"""Read caches preserve global validation, locale and immutable responses."""

import hashlib
import struct

import pytest
from flask import Flask

from mcbe_editor import villagers
from mcbe_editor.leveldb_readonly import WorldChangedWhileReadingError
from mcbe_editor.villager_directory import VillagerDirectory
from tests.test_entities import EntityDb, add_actor, entity_tag


class SnapshotDb(EntityDb):
    scans = 0
    world = "world-a"

    def content_token(self):
        return self.world, hashlib.sha256(repr(sorted(self.records.items())).encode()).hexdigest()

    def iter_items(self):
        self.scans += 1
        return super().iter_items()


def populated():
    db = SnapshotDb()
    add_actor(db, entity_tag())
    return db


def test_details_and_repeat_scan_reuse_discovery_without_sharing_mutable_responses():
    db, directory = populated(), VillagerDirectory()
    expected = villagers.scan_villagers(db)
    row = expected["villagers"][0]
    expected_detail = villagers.load_villager_detail(db, row["id"], row["revision"])
    first = directory.scan(db)
    scans = db.scans
    first["villagers"][0]["health"]["current"] = 999
    first["diagnostics"].append({"code": "injected"})
    detail = directory.detail(db, row["id"], row["revision"])
    assert detail == expected_detail
    detail["nbt"]["value"].clear()
    assert directory.detail(db, row["id"], row["revision"]) == expected_detail
    assert directory.scan(db) == expected
    assert db.scans == scans
    with pytest.raises(ValueError, match="verändert"):
        directory.detail(db, row["id"], "0" * 64)


def test_other_mob_identity_change_invalidates_cached_editability():
    db, directory = populated(), VillagerDirectory()
    row = directory.scan(db)["villagers"][0]
    add_actor(db, entity_tag(1, identifier="minecraft:cow"), suffix=b"abcdefgh")
    detail = directory.detail(db, row["id"], row["revision"])
    assert not detail["editable"]
    assert "duplicate_unique_id" in {issue["code"] for issue in detail["issues"]}
    assert db.scans == 2


def test_legacy_detail_uses_exact_root_and_matches_uncached_read():
    key = struct.pack("<ii", 0, 0) + b"\x32"
    db = SnapshotDb({key: entity_tag(1).save_to() + entity_tag(2, identifier="minecraft:villager").save_to()})
    directory = VillagerDirectory()
    rows = directory.scan(db)["villagers"]
    for row in rows:
        assert directory.detail(db, row["id"], row["revision"]) == villagers.load_villager_detail(db, row["id"], row["revision"])


@pytest.mark.parametrize("limits", [{"max_bytes": 1}, {"max_residents": 0}, {"max_entries": 0}])
def test_oversized_snapshots_work_without_retention(limits):
    db, directory = populated(), VillagerDirectory(**limits)
    assert directory.scan(db) == directory.scan(db)
    assert db.scans == 2
    assert not directory._entries


def test_lru_evicts_worlds_and_payload_budget_is_shared():
    a, b = populated(), populated()
    b.world = "world-b"
    directory = VillagerDirectory(max_entries=1)
    directory.scan(a)
    directory.scan(b)
    directory.scan(a)
    assert a.scans == 2
    size = directory._bytes
    directory = VillagerDirectory(max_bytes=size)
    directory.scan(a)
    directory.scan(b)
    assert len(directory._entries) == 1 and directory._bytes <= size


def test_cache_separates_locales():
    db, directory, app = populated(), VillagerDirectory(), Flask(__name__)
    with app.test_request_context(headers={"Accept-Language": "de"}):
        german = directory.scan(db)
    with app.test_request_context(headers={"Accept-Language": "en"}):
        english = directory.scan(db)
    assert german["villagers"][0]["trade_tier_label"] == "Meister"
    assert english["villagers"][0]["trade_tier_label"] == "Master"
    assert db.scans == 2


def test_unknown_or_changing_database_state_is_not_cached(monkeypatch):
    db, directory = populated(), VillagerDirectory()
    monkeypatch.setattr(db, "content_token", lambda: None)
    directory.scan(db)
    directory.scan(db)
    assert not directory._entries and db.scans == 2
    tokens = iter([("world", 1), ("world", 2)])
    monkeypatch.setattr(db, "content_token", lambda: next(tokens))
    with pytest.raises(WorldChangedWhileReadingError):
        directory.scan(db)
    assert not directory._entries


def test_failed_or_cancelled_scan_does_not_publish_cache(monkeypatch):
    from mcbe_editor.read_operation import ReadStoppedError

    db, directory = populated(), VillagerDirectory()

    def cancelled(_db):
        raise ReadStoppedError()

    monkeypatch.setattr(villagers, "_scan", cancelled)
    with pytest.raises(ReadStoppedError):
        directory.scan(db)
    assert not directory._entries
