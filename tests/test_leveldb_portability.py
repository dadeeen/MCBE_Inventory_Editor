"""Real-engine persistence, batch and lock checks on every supported runtime."""

import os
import subprocess
import sys

import pytest

from mcbe_editor.db import LevelDbAdapter
from mcbe_editor.leveldb_readonly import ReadonlyLevelDbAdapter


@pytest.fixture(autouse=True)
def _offline_disposable_databases(monkeypatch):
    import mcbe_editor.db as db_module

    monkeypatch.setattr(db_module, "_runtime_app_modules", lambda: ())
    monkeypatch.setattr(db_module, "_registered_write_guard", None)


def test_native_batch_persists_deletes_and_unrelated_records(tmp_path):
    import leveldb

    path = tmp_path / "db"
    seed = leveldb.LevelDB(str(path), True)
    seed.putBatch({b"untouched": b"\x00\xffopaque", b"deleted": b"old", b"updated": b"old"})
    seed.close()
    adapter = LevelDbAdapter(str(path))
    adapter.put_batch({b"updated": b"new", b"deleted": None, b"added": b"value"})
    adapter.close()
    expected = {b"untouched": b"\x00\xffopaque", b"updated": b"new", b"added": b"value"}
    for cls in (ReadonlyLevelDbAdapter, LevelDbAdapter):
        reopened = cls(str(path))
        try:
            assert dict(reopened.iter_items()) == expected
            with pytest.raises(KeyError):
                reopened.get(b"deleted")
        finally:
            reopened.close()


def test_native_lock_rejects_a_second_process(tmp_path):
    import leveldb

    path = tmp_path / "db"
    db = leveldb.LevelDB(str(path), True)
    try:
        child = subprocess.run(
            [sys.executable, "-c", "import leveldb,sys; db=leveldb.LevelDB(sys.argv[1]); db.close()", str(path)],
            capture_output=True, timeout=20,
        )
        assert child.returncode != 0
        assert b"lock" in (child.stdout + child.stderr).lower()
    finally:
        db.close()


def test_native_reopens_after_process_exit_without_close(tmp_path):
    # Process exit is not a power-loss durability claim. This verifies recovery
    # of a completed write from the WAL when Python cleanup did not run.
    path = tmp_path / "db"
    child = subprocess.run(
        [sys.executable, "-c",
         "import leveldb,os,sys; db=leveldb.LevelDB(sys.argv[1],True); "
         "db.putBatch({b'a':b'1',b'b':b'2'}); os._exit(0)", str(path)],
        capture_output=True, timeout=20, env=os.environ.copy(),
    )
    assert child.returncode == 0
    adapter = LevelDbAdapter(str(path))
    try:
        assert dict(adapter.iter_items()) == {b"a": b"1", b"b": b"2"}
    finally:
        adapter.close()
