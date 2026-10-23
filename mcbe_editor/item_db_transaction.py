"""Recover a catalog and its provenance as one generation after worker death.

The journal is durable before any target changes. A prepared journal restores
the old generation; a committed journal verifies and retains the new generation.
It survives successful worker completion until the parent (or next launch)
acknowledges it, including a worker killed before emitting its final report.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

from .runtime_data import _resolved_runtime_path, atomic_write_private_text
from .world_locks import locked_operation

PARENT_LOCK_ENV = "MCBE_ITEM_DB_PARENT_LOCK"


class ItemDbRecoveryError(RuntimeError):
    """Persistent state cannot safely be recovered; leave the journal intact."""


def configured_targets(item_db_path, source_version_path, source_version_history_path) -> tuple[Path, ...]:
    paths = [item_db_path, source_version_path, source_version_history_path]
    if not all(paths):
        raise ItemDbRecoveryError("Item database transaction requires all three configured paths")
    targets = tuple(_resolved_runtime_path(str(path)) for path in paths)
    if len(set(targets)) != 3:
        raise ItemDbRecoveryError("Item database transaction targets must be distinct")
    if journal_path(targets) in targets:
        raise ItemDbRecoveryError("Item database transaction journal cannot be a publication target")
    return targets


def journal_path(targets: Sequence[Path]) -> Path:
    return targets[0].with_name(f".{targets[0].name}.transaction.json")


@contextmanager
def item_db_update_operation(targets: tuple[Path, ...], *, allow_parent_lock: bool = False) -> Iterator[None]:
    """Keep input reads, worker completion and recovery acknowledgement together.

    Only the updater CLI accepts the runner's exact-target marker. Its parent
    holds this outer lock while waiting; the child still takes the separate
    publication lock. Bootstrap and direct runner calls always acquire it.
    """
    targets = configured_targets(*targets)
    if allow_parent_lock and os.environ.get(PARENT_LOCK_ENV) == str(targets[0]):
        yield
    else:
        with locked_operation("item-db-update", root=targets[0].parent):
            yield


def _snapshot(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def _digest(content: bytes | None) -> str | None:
    return hashlib.sha256(content).hexdigest() if content is not None else None


def _sync_directory(path: Path) -> None:
    # Windows does not expose directory fsync through the Python file API.
    # File contents are fsynced there; process-death recovery uses atomic replace.
    if os.name != "nt":
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _save_journal(path: Path, data: dict) -> None:
    atomic_write_private_text(path, json.dumps(data, separators=(",", ":")) + "\n")
    _sync_directory(path.parent)


def _restore(path: Path, content: bytes | None) -> None:
    if content is None:
        path.unlink(missing_ok=True)
    else:
        # JSON targets are UTF-8, but preserve arbitrary old bytes exactly.
        import tempfile

        path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".rollback", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, path)
        finally:
            Path(name).unlink(missing_ok=True)
    if path.parent.exists():
        _sync_directory(path.parent)


def _recover_locked(targets: tuple[Path, ...], *, acknowledge_committed: bool = True) -> str:
    path = journal_path(targets)
    if not path.exists():
        return "none"
    try:
        journal = json.loads(path.read_text(encoding="utf-8"))
        if journal["version"] != 1 or journal["phase"] not in {"prepared", "committed"}:
            raise ValueError("unknown journal format")
        entries = journal["entries"]
        if not isinstance(entries, list) or len(entries) != len(targets):
            raise ValueError("unexpected journal targets")
        snapshots = []
        for target, entry in zip(targets, entries, strict=True):
            # Journal paths are evidence, never destinations supplied to writes.
            if entry["path"] != str(target):
                raise ValueError("journal does not match configured targets")
            old = entry["old"]
            content = base64.b64decode(old, validate=True) if old is not None else None
            if _digest(content) != entry["old_sha256"]:
                raise ValueError("journal snapshot hash mismatch")
            snapshots.append(content)
        if journal["phase"] == "committed":
            if [_digest(_snapshot(target)) for target in targets] != journal["new_sha256"]:
                raise ValueError("committed generation hash mismatch")
            result = "committed"
        else:
            for target, content in zip(targets, snapshots, strict=True):
                _restore(target, content)
            result = "rolled_back"
        if result != "committed" or acknowledge_committed:
            path.unlink()
            _sync_directory(path.parent)
        return result
    except (OSError, ValueError, TypeError, KeyError, RecursionError) as exc:
        raise ItemDbRecoveryError("Item database generation recovery failed; journal retained") from exc


def recover_item_db(targets: tuple[Path, ...]) -> str:
    """Wait for active commits, then finish pending recovery idempotently."""
    targets = configured_targets(*targets)
    with locked_operation(f"item-db-transaction:{targets[0].name}", root=targets[0].parent):
        return _recover_locked(targets)


@contextmanager
def item_db_transaction(targets: tuple[Path, ...]) -> Iterator[None]:
    targets = configured_targets(*targets)
    with locked_operation(f"item-db-transaction:{targets[0].name}", root=targets[0].parent):
        _recover_locked(targets)
        entries = []
        for target in targets:
            content = _snapshot(target)
            entries.append(
                {"path": str(target), "old": base64.b64encode(content).decode("ascii") if content is not None else None, "old_sha256": _digest(content)}
            )
        journal = {"version": 1, "phase": "prepared", "entries": entries}
        _save_journal(journal_path(targets), journal)
        try:
            yield
            for target in targets:
                if target.exists():
                    with target.open("r+b") as handle:
                        os.fsync(handle.fileno())
                    _sync_directory(target.parent)
            journal.update(phase="committed", new_sha256=[_digest(_snapshot(target)) for target in targets])
            _save_journal(journal_path(targets), journal)
        except BaseException:
            _recover_locked(targets, acknowledge_committed=False)
            raise
