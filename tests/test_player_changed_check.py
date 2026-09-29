"""Noticing that the loaded player changed outside the editor, e.g. in Minecraft."""

from __future__ import annotations

import threading
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from mcbe_editor.leveldb_readonly import WorldChangedWhileReadingError
from mcbe_editor.world import world_fingerprint
from mcbe_editor.world_locks import locked_world


def _files_world(tmp_path):
    world = tmp_path / "world"
    db = world / "db"
    db.mkdir(parents=True)
    (db / "CURRENT").write_bytes(b"MANIFEST-000002\n")
    (db / "MANIFEST-000002").write_bytes(b"manifest")
    (db / "000003.log").write_bytes(b"log")
    (db / "000004.ldb").write_bytes(b"table")
    (world / "level.dat").write_bytes(b"level")
    return world


def _append(path, data=b"more"):
    with path.open("ab") as handle:
        handle.write(data)


@pytest.mark.parametrize("change", ["log", "new_log", "manifest", "new_manifest", "level_dat"])
def test_the_world_fingerprint_follows_the_files_every_save_changes(tmp_path, change):
    world = _files_world(tmp_path)
    db = world / "db"
    before = world_fingerprint(str(world))
    assert world_fingerprint(str(world)) == before
    if change == "log":
        _append(db / "000003.log")
    elif change == "new_log":
        (db / "000005.log").write_bytes(b"")
    elif change == "manifest":
        _append(db / "MANIFEST-000002")
    elif change == "new_manifest":
        (db / "MANIFEST-000006").write_bytes(b"manifest")
        (db / "CURRENT").write_bytes(b"MANIFEST-000006\n")
    else:
        _append(world / "level.dat")
    assert world_fingerprint(str(world)) != before


def test_the_world_fingerprint_leaves_tables_out(tmp_path):
    world = _files_world(tmp_path)
    before = world_fingerprint(str(world))
    # A flush or compaction always changes the MANIFEST as well.
    (world / "db" / "000007.ldb").write_bytes(b"new table")
    (world / "db" / "000004.ldb").unlink()
    assert world_fingerprint(str(world)) == before


@pytest.fixture
def player_world(tmp_path, monkeypatch):
    from mcbe_editor.bedrock_nbt import save_player_nbt
    from mcbe_editor.db import LevelDbAdapter
    from mcbe_editor.world import LOCAL_PLAYER_KEY
    from mcbe_editor import nbt
    from tests.conftest import make_minimal_player_tag

    world = tmp_path / "world"
    (world / "db").mkdir(parents=True)
    monkeypatch.setattr("mcbe_editor.db._run_runtime_leveldb_write_guard", lambda *_args: None)

    def write_player(level):
        player = make_minimal_player_tag()
        player["PlayerLevel"] = nbt.IntTag(level)
        db = LevelDbAdapter(str(world / "db"))
        try:
            db.put(LOCAL_PLAYER_KEY, save_player_nbt(nbt.NamedTag(player)))
        finally:
            db.close()

    write_player(1)
    return world, write_player


def test_the_service_reports_the_stored_revision_of_the_loaded_player(player_world):
    from mcbe_editor.item_data import ENCHANTMENTS, ITEMS
    from mcbe_editor.players import encode_player_key
    from mcbe_editor.services import BedrockEditorService
    from mcbe_editor.world import LOCAL_PLAYER_KEY

    world, write_player = player_world
    service = BedrockEditorService(ITEMS, ENCHANTMENTS)
    key = encode_player_key(LOCAL_PLAYER_KEY)
    loaded = service.load_player(str(world), key)
    assert loaded["world_fingerprint"] == world_fingerprint(str(world))
    assert service.stored_player_revision(str(world), key) == loaded["player_revision"]
    assert service.stored_player_revision(str(world), encode_player_key(b"player_server_gone")) == ""

    # Minecraft changes the player while the page shows the loaded state.
    write_player(2)
    assert world_fingerprint(str(world)) != loaded["world_fingerprint"]
    assert service.stored_player_revision(str(world), key) not in ("", loaded["player_revision"])


def test_the_check_skips_a_world_that_is_loading_or_saving(tmp_path):
    from mcbe_editor.services import BedrockEditorService

    world = _files_world(tmp_path)
    factory = Mock()
    service = BedrockEditorService({}, {}, readonly_db_factory=factory)
    holding = threading.Event()
    done = threading.Event()

    def save_meanwhile():
        with locked_world(str(world)):
            holding.set()
            done.wait(5)

    thread = threading.Thread(target=save_meanwhile)
    thread.start()
    try:
        assert holding.wait(5)
        assert service.stored_player_revision(str(world), "fake") is None
    finally:
        done.set()
        thread.join(5)
    factory.assert_not_called()


REVISION = "a" * 64


@pytest.fixture
def presence(monkeypatch):
    import main

    fingerprint = {"value": "now"}
    service = SimpleNamespace(stored_player_revision=Mock(return_value=REVISION))
    blocked = {"response": None}
    deps = replace(
        main.runtime_route_deps(),
        service=service,
        ensure_valid_world_path=lambda _path: None,
        world_fingerprint=lambda _path: fingerprint["value"],
        require_world_db_access_allowed=lambda: blocked["response"],
    )
    monkeypatch.setattr(main, "runtime_route_deps", lambda: deps)
    client = main.app.test_client()

    def post(**fields):
        response = client.post(
            "/api/world/presence",
            json={"session_id": "web-player-check", "world_path": "world", "player_key": "encoded", **fields},
            headers={"X-CSRF-Token": main.CSRF_TOKEN},
        )
        assert response.status_code == 200
        result = response.get_json()
        assert result["success"] is True
        return result

    return SimpleNamespace(post=post, service=service, fingerprint=fingerprint, blocked=blocked)


def test_the_presence_poll_only_reports_the_fingerprint_of_a_watched_player(presence):
    assert "world_fingerprint" not in presence.post()
    assert "world_fingerprint" not in presence.post(fingerprint_baseline="then", player_key="")
    result = presence.post(fingerprint_baseline="now", fingerprint_seen="")
    assert result["world_fingerprint"] == "now"
    assert "player_revision" not in result
    presence.service.stored_player_revision.assert_not_called()


def test_the_player_is_read_once_the_changed_world_stayed_the_same_for_a_poll(presence):
    # Just changed: the program that changed it may still be writing.
    first = presence.post(fingerprint_baseline="then", fingerprint_seen="")
    assert first["world_fingerprint"] == "now"
    assert "player_revision" not in first
    presence.service.stored_player_revision.assert_not_called()

    second = presence.post(fingerprint_baseline="then", fingerprint_seen="now")
    assert second["player_revision"] == REVISION
    presence.service.stored_player_revision.assert_called_once_with("world", "encoded")


@pytest.mark.parametrize(
    "outcome",
    [None, WorldChangedWhileReadingError("/worlds/Test/db"), RuntimeError("broken")],
    ids=["world_busy", "server_writing", "unreadable"],
)
def test_a_player_check_that_cannot_read_leaves_the_poll_working(presence, outcome):
    if isinstance(outcome, Exception):
        presence.service.stored_player_revision.side_effect = outcome
    else:
        presence.service.stored_player_revision.return_value = outcome
    result = presence.post(fingerprint_baseline="then", fingerprint_seen="now")
    assert result["world_fingerprint"] == "now"
    assert "player_revision" not in result


def test_no_player_check_while_reading_the_world_is_blocked(presence):
    presence.blocked["response"] = ("blocked", 409)
    result = presence.post(fingerprint_baseline="then", fingerprint_seen="now")
    assert result["world_fingerprint"] == "now"
    assert "player_revision" not in result
    presence.service.stored_player_revision.assert_not_called()
