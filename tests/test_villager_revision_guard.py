"""Reject world drift at every boundary before the villager write batch."""

from __future__ import annotations

from pathlib import Path

import pytest

from mcbe_editor import villager_service
from mcbe_editor.leveldb_writer import LevelDbWriter
from tests.test_villager_workflow import _prepare, _records, villager_world as villager_world


def test_world_revision_is_checked_after_the_writer_lock_is_acquired(villager_world, monkeypatch):
    world, original = villager_world
    service, arguments, _ = _prepare(world)
    open_writer = service._open_db

    def concurrent_open(path):
        # A completed external write can land after the backup/revision check
        # and before this process acquires the writer lock. Selected actors and
        # their indexes remain identical, so an actor-only digest cannot see it.
        writer = LevelDbWriter(str(Path(path) / "db"))
        try:
            writer.put_batch({b"unrelated-world-record": b"changed after the backup"})
        finally:
            writer.close()
        return open_writer(path)

    monkeypatch.setattr(service, "_open_db", concurrent_open)
    with pytest.raises(villager_service.VillagerSnapshotStaleError):
        villager_service.save(service, world, **arguments, pre_write_check=lambda: None)
    assert _records(world) == {**original, b"unrelated-world-record": b"changed after the backup"}


def test_world_revision_is_checked_after_the_final_server_gate(villager_world):
    world, original = villager_world
    service, arguments, _ = _prepare(world)
    checks = 0

    def gate():
        nonlocal checks
        checks += 1
        if checks == 3:
            # The LevelDB lock cannot cover world metadata written by an
            # external process. No villager batch may use the older preview.
            (Path(world) / "level.dat").write_bytes(b"changed world metadata after the final server check")

    with pytest.raises(villager_service.VillagerSnapshotStaleError):
        villager_service.save(service, world, **arguments, pre_write_check=gate)
    assert checks == 3
    assert _records(world) == original
