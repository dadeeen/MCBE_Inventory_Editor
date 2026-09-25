from __future__ import annotations

import ast
import errno
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from mcbe_editor.db import LevelDbAdapter
from mcbe_editor.service_errors import LevelDbInUseError, LevelDbPermissionError, denied_write_actor, denied_write_permission_hint

ROOT = Path(__file__).resolve().parents[1]


def _as_posix_container():
    """Pretend to be the Docker image: POSIX, non-root UID/GID 10001."""

    return (
        patch.object(os, "name", "posix"),
        patch.object(os, "getuid", lambda: 10001, create=True),
        patch.object(os, "getgid", lambda: 10001, create=True),
    )


def test_windows_hint_stays_windows_specific() -> None:
    with patch.object(os, "name", "nt"):
        assert denied_write_actor() == "Windows"
        hint = denied_write_permission_hint()
    assert "Antivirus" in hint
    assert "setfacl" not in hint


def test_posix_hint_names_the_effective_uid_instead_of_windows() -> None:
    name_patch, uid_patch, gid_patch = _as_posix_container()
    with name_patch, uid_patch, gid_patch:
        actor = denied_write_actor()
        hint = denied_write_permission_hint()

    # A Docker user is told to close Minecraft and check Windows write
    # protection otherwise, while the real cause is a missing ACL for this UID.
    assert actor != "Windows"
    assert "Windows" not in hint
    assert "10001" in hint
    assert "Default-ACL" in hint
    assert "vollständige Befehle" in hint


def test_leveldb_permission_error_becomes_stable_service_error() -> None:
    def refuse_open(_path):
        raise PermissionError(errno.EACCES, "Permission denied", "/worlds/Test/db/LOCK")

    name_patch, uid_patch, gid_patch = _as_posix_container()
    with (
        patch("mcbe_editor.db.LevelDbWriter", refuse_open),
        patch("mcbe_editor.db._run_runtime_leveldb_write_guard"),
        name_patch,
        uid_patch,
        gid_patch,
        pytest.raises(LevelDbPermissionError) as raised,
    ):
        LevelDbAdapter("/worlds/Test/db")

    message = str(raised.value)
    assert "UID/GID 10001/10001" in message
    assert "/worlds/Test/db" in message
    assert "Errno" not in message


def test_leveldb_in_use_error_is_not_reported_as_a_permission_problem() -> None:
    expected = LevelDbInUseError(db_path="/worlds/Test/db")

    def refuse_open(_path):
        raise expected

    with (
        patch("mcbe_editor.db.LevelDbWriter", refuse_open),
        patch("mcbe_editor.db._run_runtime_leveldb_write_guard"),
        pytest.raises(LevelDbInUseError) as raised,
    ):
        LevelDbAdapter("/worlds/Test/db")

    assert raised.value is expected


def test_leveldb_permission_error_during_write_uses_the_same_translation() -> None:
    class FakeDb:
        def put(self, _key, _value):
            raise PermissionError(errno.EACCES, "Access is denied", "/worlds/Test/db/000007.log")

    name_patch, uid_patch, gid_patch = _as_posix_container()
    with (
        patch("mcbe_editor.db.LevelDbWriter", lambda _path: FakeDb()),
        patch("mcbe_editor.db._run_runtime_leveldb_write_guard"),
        name_patch,
        uid_patch,
        gid_patch,
    ):
        adapter = LevelDbAdapter("/worlds/Test/db")
        with pytest.raises(LevelDbPermissionError, match="Schreiben") as raised:
            adapter.put(b"player", b"state")

    assert raised.value.operation == "Schreiben"


def test_no_write_error_message_hardcodes_windows() -> None:
    """Guard the fix: these messages also fire in the Linux Docker image."""

    offenders: list[str] = []
    for path in [ROOT / "main.py", *sorted((ROOT / "mcbe_editor").glob("*.py"))]:
        if path.name == "service_errors.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and "Windows verweigert" in node.value:
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")

    assert not offenders, "Use denied_write_actor()/denied_write_permission_hint() instead of a hardcoded Windows message:\n" + "\n".join(offenders)
