"""Wire-compatible results for confirmed writes and their post-write failures.

An unknown write outcome is an exception, never a retryable success result.
The constructors keep no-op, committed and post-write-failure flags coherent.
"""

from collections.abc import Callable
from typing import Any, Literal, NotRequired, TypedDict

from .db import BedrockDb


class SavedItemState(TypedDict):
    item_source_digests: dict[str, dict[str, str]]
    saved_items: dict[str, Any]


class SaveNoOp(SavedItemState):
    success: Literal[True]
    no_op: Literal[True]
    backup_file: None
    message: str
    player_revision: str


class SaveCommitted(SavedItemState):
    success: Literal[True]
    no_op: Literal[False]
    backup_file: str
    message: str
    player_revision: str
    workspace: dict[str, Any] | None


class SavePostWriteFailure(SavedItemState):
    success: Literal[False]
    no_op: Literal[False]
    write_committed: Literal[True]
    validation_failed: Literal[True]
    backup_file: str | None
    message: str
    error: str
    player_revision: NotRequired[str]
    workspace: NotRequired[dict[str, Any] | None]
    error_phase: NotRequired[Literal["post_write"]]


type SaveResult = SaveNoOp | SaveCommitted | SavePostWriteFailure


class ExtraBatch(TypedDict):
    writes: dict[bytes, bytes | None]
    result: NotRequired[dict[str, Any]]
    records: NotRequired[list[Any]]


type WriteCheck = Callable[[], None]
type ExtraBatchBuilder = Callable[[BedrockDb, bytes], ExtraBatch]
type ExtraBatchValidator = Callable[[BedrockDb, ExtraBatch], None]


class ImportResult(TypedDict):
    success: Literal[True]
    write_committed: Literal[True]
    world_path: str
    backup_file: str
    target_player: dict[str, Any]
    import_preview: dict[str, Any]
    created_new_player: bool
    post_write_validated: Literal[True]
    cleanup_warning: NotRequired[str]


class RestoreResult(TypedDict):
    success: Literal[True]
    message: str
    pre_restore_backup: str
    restored_backup: str
    cleanup_warning: NotRequired[str]


def import_completed(world_path: str, backup_file: str, target_player: dict[str, Any], preview: dict[str, Any], created_new_player: bool) -> ImportResult:
    return {
        "success": True,
        "write_committed": True,
        "world_path": world_path,
        "backup_file": backup_file,
        "target_player": target_player,
        "import_preview": preview,
        "created_new_player": created_new_player,
        "post_write_validated": True,
    }


def restore_completed(pre_restore_backup: str, restored_backup: str) -> RestoreResult:
    return {
        "success": True,
        "message": "Backup erfolgreich wiederhergestellt!",
        "pre_restore_backup": pre_restore_backup,
        "restored_backup": restored_backup,
    }


def save_no_op(state: SavedItemState, revision: str) -> SaveNoOp:
    return {
        "item_source_digests": state["item_source_digests"],
        "saved_items": state["saved_items"],
        "success": True,
        "message": "Keine Änderungen erkannt. Es wurde kein Backup erstellt und nichts geschrieben.",
        "backup_file": None,
        "player_revision": revision,
        "no_op": True,
    }


def save_completed(
    state: SavedItemState, revision: str, backup_file: str, workspace: dict[str, Any] | None, errors: list[str]
) -> SaveCommitted | SavePostWriteFailure:
    if errors:
        return {
            "item_source_digests": state["item_source_digests"],
            "saved_items": state["saved_items"],
            "success": False,
            "message": "; ".join(errors),
            "backup_file": backup_file,
            "player_revision": revision,
            "no_op": False,
            "workspace": workspace,
            "write_committed": True,
            "validation_failed": True,
            "error": (
                "Änderungen wurden geschrieben, aber der Abschluss nach dem Schreiben ist fehlgeschlagen. "
                "Nicht erneut speichern; stelle bei Zweifeln das angegebene Backup wieder her. " + "; ".join(errors)
            ),
        }
    return {
        "item_source_digests": state["item_source_digests"],
        "saved_items": state["saved_items"],
        "success": True,
        "message": "Erfolgreich gespeichert!",
        "backup_file": backup_file,
        "player_revision": revision,
        "no_op": False,
        "workspace": workspace,
    }


def save_post_write_failure(state: SavedItemState, backup_file: str | None) -> SavePostWriteFailure:
    message = (
        "Änderungen wurden geschrieben, aber der Abschluss nach dem Schreiben ist fehlgeschlagen. "
        "Nicht erneut speichern; stelle bei Zweifeln das angegebene Backup wieder her."
    )
    return {
        "item_source_digests": state["item_source_digests"],
        "saved_items": state["saved_items"],
        "success": False,
        "write_committed": True,
        "validation_failed": True,
        "error_phase": "post_write",
        "error": message,
        "message": message,
        "no_op": False,
        "backup_file": backup_file,
    }
