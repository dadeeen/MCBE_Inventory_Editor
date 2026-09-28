"""Discovery reuse must agree with a fresh scan after saves and external edits."""

import hashlib
import os
import random
import shutil
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from flask import Flask

from mcbe_editor import db as db_module, nbt, players as players_module, services as services_module
from mcbe_editor.db import LevelDbAdapter
from mcbe_editor.item_data import ENCHANTMENTS, ITEMS
from mcbe_editor.leveldb_readonly import ReadonlyLevelDbAdapter
from mcbe_editor.leveldb_writer import LevelDbWriter
from mcbe_editor.players import PlayerScanner, encode_player_key
from mcbe_editor.services import BedrockEditorService
from mcbe_editor.world import LOCAL_PLAYER_KEY


def _player_bytes(*, inventory=True, xp=1):
    tag = nbt.CompoundTag({"PlayerGameType": nbt.IntTag(0), "XPLevel": nbt.IntTag(xp)})
    if inventory:
        tag["Inventory"] = nbt.ListTag([])
    return nbt.NamedTag(tag).save_to(compressed=False, little_endian=True)


def _write(world, entries):
    writer = LevelDbWriter(str(world / "db"))
    try:
        writer.put_batch(entries)
    finally:
        writer.close()


def _raw(world, key=LOCAL_PLAYER_KEY):
    reader = ReadonlyLevelDbAdapter(str(world / "db"))
    try:
        return reader.get(key)
    finally:
        reader.close()


def _save(service, world, *, key=LOCAL_PLAYER_KEY, xp=2, **kwargs):
    return service.save_player(
        str(world), encode_player_key(key), None, {"xp_level": xp},
        base_revision=hashlib.sha256(_raw(world, key)).hexdigest(), **kwargs,
    )


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(db_module, "_run_runtime_leveldb_write_guard", lambda _label: None)
    world = tmp_path / "world"
    (world / "db").mkdir(parents=True)
    (world / "levelname.txt").write_text("Synthetic directory test", encoding="utf-8")
    _write(world, {
        LOCAL_PLAYER_KEY: _player_bytes(),
        b"player_remote": _player_bytes(),
        b"unusual-key": _player_bytes(),
        b"chunk-data": b"not NBT",
    })
    return world


@pytest.fixture
def service():
    return BedrockEditorService(ITEMS, ENCHANTMENTS)


@pytest.fixture
def scans():
    with patch.object(PlayerScanner, "list_players", autospec=True, side_effect=PlayerScanner.list_players) as counted:
        yield counted


def _assert_fresh_directory(service, world):
    expected = BedrockEditorService(ITEMS, ENCHANTMENTS).list_players(str(world))
    assert service.list_players(str(world)) == expected


def test_repeated_normal_saves_reuse_complete_directory_and_match_fresh_scan(world, service, scans):
    listed = service.list_players(str(world))
    assert len(listed["players"]) == 3
    # Returned nested data never belongs to the retained directory.
    listed["players"][0]["debug"]["raw_length"] = -1
    for xp in (2, 3, 4):
        assert _save(service, world, xp=xp)["success"]
        loaded = service.load_player(str(world), encode_player_key(LOCAL_PLAYER_KEY))
        assert loaded["stats"]["xp_level"] == xp
        assert loaded["capabilities"]["player_count"] == 3
        assert loaded["capabilities"]["editable_player_count"] == 3
        assert scans.call_count == 1
    _assert_fresh_directory(service, world)
    assert scans.call_count == 2  # Only the independent reference scan.


def test_known_player_save_without_a_directory_does_not_discover_the_world(world, service, scans):
    assert _save(service, world)["success"]
    assert scans.call_count == 0
    assert service.load_player(str(world), encode_player_key(LOCAL_PLAYER_KEY))["capabilities"]["player_count"] == 3
    assert scans.call_count == 1


def test_directory_updates_changed_player_shape_and_request_language(world, service, scans):
    _write(world, {LOCAL_PLAYER_KEY: _player_bytes(inventory=False)})
    app = Flask(__name__)
    with app.test_request_context("/", headers={"Accept-Language": "en"}):
        service.list_players(str(world))
        saved = service.save_player(
            str(world), encode_player_key(LOCAL_PLAYER_KEY),
            [{"slot": 0, "name": "minecraft:stone", "count": 1, "damage": 0}], {},
            base_revision=hashlib.sha256(_raw(world)).hexdigest(), allow_create_inventory=True,
        )
        assert saved["success"]
    with app.test_request_context("/", headers={"Accept-Language": "de"}):
        listed = service.list_players(str(world))
        local = listed["players"][0]
        assert local["label"] == local["raw_key_preview"] == local["debug"]["key_label"] == "Lokaler Spieler"
        assert local["has_inventory_tag"]
        assert not local["inventory_create_requires_confirmation"]
        assert scans.call_count == 1
        _assert_fresh_directory(service, world)


@pytest.mark.parametrize("phase", ["before_backup", "after_backup", "after_commit"])
def test_unrelated_external_changes_cannot_be_certified_as_our_save(world, service, scans, monkeypatch, phase):
    service.list_players(str(world))

    def external_change():
        _write(world, {b"player_added": _player_bytes(), b"player_remote": None})

    if phase == "before_backup":
        external_change()
    else:
        hook_name = "create_backup" if phase == "after_backup" else "prune_backups"
        original = getattr(services_module, hook_name)

        def hook(*args, **kwargs):
            result = original(*args, **kwargs)
            external_change()
            return result

        monkeypatch.setattr(services_module, hook_name, hook)
    assert _save(service, world)["success"]
    listed = service.list_players(str(world))
    assert scans.call_count == 2
    keys = {p["player_key"] for p in listed["players"]}
    assert encode_player_key(b"player_added") in keys
    assert encode_player_key(b"player_remote") not in keys
    _assert_fresh_directory(service, world)


def test_ambiguous_write_never_promotes_directory(world, scans):
    from mcbe_editor.service_errors import WriteOutcomeUnknownError

    class AmbiguousWriter(LevelDbAdapter):
        def put(self, key, value):
            super().put(key, value)
            raise OSError("failure after durable write")

    service = BedrockEditorService(ITEMS, ENCHANTMENTS, db_factory=AmbiguousWriter)
    service.list_players(str(world))
    with pytest.raises(WriteOutcomeUnknownError) as caught:
        _save(service, world)
    assert isinstance(caught.value.original_error, OSError)
    assert "after durable write" in str(caught.value.original_error)
    assert caught.value.backup_file
    loaded = service.load_player(str(world), encode_player_key(LOCAL_PLAYER_KEY))
    assert loaded["stats"]["xp_level"] == 2
    assert scans.call_count == 2
    _assert_fresh_directory(service, world)


def test_directory_failure_does_not_turn_committed_save_into_an_error(world, service, scans, monkeypatch):
    service.list_players(str(world))

    def exhausted(_change):
        raise MemoryError("directory allocation")

    monkeypatch.setattr(service._player_directory, "_apply_change", exhausted)
    result = _save(service, world)
    assert result["success"] and not result["no_op"]
    assert service.load_player(str(world), encode_player_key(LOCAL_PLAYER_KEY))["stats"]["xp_level"] == 2
    assert scans.call_count == 2


def test_unknown_player_save_uses_complete_fallback(world, service, scans):
    service.list_players(str(world))
    assert _save(service, world, key=b"unusual-key")["success"]
    assert service.load_player(str(world), encode_player_key(b"unusual-key"))["stats"]["xp_level"] == 2
    assert scans.call_count == 2
    _assert_fresh_directory(service, world)


def test_unknown_selection_keeps_discovery_candidate_limit(world, service, monkeypatch):
    monkeypatch.setattr(players_module, "FALLBACK_PLAYER_SCAN_LIMIT", 1)
    _write(world, {b"a-unknown": _player_bytes(), b"z-unknown": _player_bytes()})
    with pytest.raises(ValueError, match="nicht als Spieler erkannt"):
        service.load_player(str(world), encode_player_key(b"z-unknown"))


def test_combined_player_and_actor_write_falls_back(world, service, scans):
    service.list_players(str(world))
    result = _save(service, world, extra_batch_builder=lambda _db, _key: {"writes": {b"actor": b"changed"}})
    assert result["success"]
    service.list_players(str(world))
    assert scans.call_count == 2
    _assert_fresh_directory(service, world)


def test_restore_cannot_reuse_directory_from_a_later_save(world, service, scans):
    snapshot = world.parent / "saved-db"
    shutil.copytree(world / "db", snapshot)
    service.list_players(str(world))
    assert _save(service, world)["success"]
    # Swap only synthetic test directories; copy2 preserves table timestamps.
    os.replace(world / "db", world.parent / "edited-db")
    os.replace(snapshot, world / "db")
    loaded = service.load_player(str(world), encode_player_key(LOCAL_PLAYER_KEY))
    assert loaded["stats"]["xp_level"] == 1
    assert scans.call_count == 2
    _assert_fresh_directory(service, world)


def test_native_recovery_and_compaction_invalidate_promoted_directory(world, service, scans):
    leveldb = pytest.importorskip("leveldb")
    service.list_players(str(world))
    assert _save(service, world)["success"]
    native = leveldb.LevelDB(str(world / "db"))
    try:
        native.put(b"player_added", _player_bytes())
        native.compact()
    finally:
        native.close()
    assert len(service.list_players(str(world))["players"]) == 4
    assert scans.call_count == 2
    _assert_fresh_directory(service, world)


def test_selected_record_revalidation_rejects_new_opaque_inventory(world, service, scans):
    service.list_players(str(world))
    tag = nbt.CompoundTag({"Inventory": nbt.StringTag("future format"), "PlayerGameType": nbt.IntTag(0)})
    _write(world, {LOCAL_PLAYER_KEY: nbt.NamedTag(tag).save_to(compressed=False, little_endian=True)})
    with pytest.raises(ValueError, match="read-only"):
        service.load_player(str(world), encode_player_key(LOCAL_PLAYER_KEY))
    assert scans.call_count == 1  # Direct validation rejects before discovery.


def test_interleaved_world_saves_keep_their_own_directory_state(world, service, scans):
    other = world.parent / "other-world"
    shutil.copytree(world, other)
    for selected in (world, other):
        service.list_players(str(selected))
    assert _save(service, world, xp=8)["success"]
    assert _save(service, other, xp=9)["success"]
    for selected, expected_xp in ((world, 8), (other, 9)):
        loaded = service.load_player(str(selected), encode_player_key(LOCAL_PLAYER_KEY))
        assert loaded["stats"]["xp_level"] == expected_xp
        assert loaded["capabilities"]["player_count"] == 3
    assert scans.call_count == 2
    for selected in (world, other):
        _assert_fresh_directory(service, selected)


def test_no_op_and_rejected_save_keep_existing_directory(world, service, scans):
    service.list_players(str(world))
    assert _save(service, world, xp=1)["no_op"]
    with pytest.raises(ValueError, match="seit dem Laden geändert"):
        service.save_player(str(world), encode_player_key(LOCAL_PLAYER_KEY), None, {"xp_level": 2}, base_revision="0" * 64)
    service.list_players(str(world))
    assert scans.call_count == 1


def test_directory_eviction_requires_rediscovery_not_cross_world_reuse(world, service, scans):
    from mcbe_editor.player_directory import PlayerDirectory

    service._player_directory = PlayerDirectory(max_worlds=1)
    other = world.parent / "other-world"
    shutil.copytree(world, other)
    service.list_players(str(world))
    service.list_players(str(other))
    assert _save(service, world)["success"]
    loaded = service.load_player(str(world), encode_player_key(LOCAL_PLAYER_KEY))
    assert loaded["stats"]["xp_level"] == 2
    assert scans.call_count == 3


@pytest.mark.parametrize("seed", [19, 927, 2048])
def test_mixed_change_sequences_always_match_independent_discovery(world, monkeypatch, seed):
    from mcbe_editor.player_directory import PlayerDirectory

    monkeypatch.setattr(players_module, "FALLBACK_PLAYER_SCAN_LIMIT", 2)
    directory = PlayerDirectory()
    rng = random.Random(seed)
    keys = [LOCAL_PLAYER_KEY, b"local_player", b"player_remote", b"PLAYER_added", b"a-opaque", b"b-opaque", b"c-opaque", b"chunk-data"]
    values = [None, b"broken NBT", _player_bytes(), _player_bytes(inventory=False), _player_bytes(xp=9)]
    writer = LevelDbWriter(str(world / "db"))
    try:
        for step in range(80):
            reader = ReadonlyLevelDbAdapter(str(world / "db"))
            try:
                # A fresh scanner is deliberately independent of the directory.
                assert directory.list_players(reader) == PlayerScanner(reader).list_players(), (seed, step)
            finally:
                reader.close()
            entries = {rng.choice(keys): rng.choice(values) for _ in range(1 if step % 4 else 2)}
            writer.put_batch(entries)
            if step % 7:
                directory.accept_committed_write(writer)
            # Missing notifications and unsupported transitions must be safe too.
            if step % 11 == 0:
                writer.close()
                writer = LevelDbWriter(str(world / "db"))
        reader = ReadonlyLevelDbAdapter(str(world / "db"))
        try:
            assert directory.list_players(reader) == PlayerScanner(reader).list_players()
        finally:
            reader.close()
    finally:
        writer.close()


def test_simultaneous_saves_from_the_same_revision_commit_only_once(world, service, scans):
    loaded = service.load_player(str(world), encode_player_key(LOCAL_PLAYER_KEY))
    barrier = Barrier(4)

    def save(xp):
        barrier.wait(timeout=10)
        try:
            result = service.save_player(
                str(world), encode_player_key(LOCAL_PLAYER_KEY), None, {"xp_level": xp},
                base_revision=loaded["player_revision"],
            )
            assert result["success"]
            return xp
        except ValueError as exc:
            assert "seit dem Laden geändert" in str(exc)
            return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(save, (2, 3, 4, 5)))
    winners = [value for value in results if value is not None]
    assert len(winners) == 1
    assert service.load_player(str(world), encode_player_key(LOCAL_PLAYER_KEY))["stats"]["xp_level"] == winners[0]
    assert scans.call_count == 1
    _assert_fresh_directory(service, world)


def test_parallel_world_requests_do_not_mix_directory_entries(world, service, scans):
    worlds = [world, world.parent / "world-b", world.parent / "world-c"]
    for other in worlds[1:]:
        shutil.copytree(world, other)
    barrier = Barrier(len(worlds))

    def edit_world(index):
        selected = worlds[index]
        service.list_players(str(selected))
        barrier.wait(timeout=10)
        for offset in range(3):
            target = 10 * (index + 1) + offset
            assert _save(service, selected, xp=target)["success"]
            loaded = service.load_player(str(selected), encode_player_key(LOCAL_PLAYER_KEY))
            assert loaded["stats"]["xp_level"] == target
            assert loaded["capabilities"]["player_count"] == 3

    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(edit_world, range(3)))
    assert scans.call_count == 3
    for selected in worlds:
        _assert_fresh_directory(service, selected)


def test_delayed_write_notification_cannot_replace_a_newer_directory(world, service, scans, monkeypatch):
    from mcbe_editor import player_directory as directory_module

    service.list_players(str(world))
    writer = LevelDbWriter(str(world / "db"))
    try:
        writer.put(LOCAL_PLAYER_KEY, _player_bytes(xp=2))
        change = writer.committed_change()
    finally:
        writer.close()
    entered, release = Event(), Event()
    original = directory_module.classify_player_record

    def delayed_classification(*args, **kwargs):
        entered.set()
        assert release.wait(timeout=10)
        return original(*args, **kwargs)

    monkeypatch.setattr(directory_module, "classify_player_record", delayed_classification)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(service._player_directory.accept_committed_write, SimpleNamespace(committed_change=lambda: change))
        try:
            assert entered.wait(timeout=10)
            _write(world, {b"player_added": _player_bytes()})
            assert len(service.list_players(str(world))["players"]) == 4
        finally:
            release.set()
        future.result(timeout=10)
    assert len(service.list_players(str(world))["players"]) == 4
    assert scans.call_count == 2
    _assert_fresh_directory(service, world)
