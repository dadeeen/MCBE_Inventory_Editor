"""Prepare writable runtime data before modules import the item catalog."""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path

from mcbe_editor.config import load_config
from mcbe_editor.item_db_transaction import configured_targets, item_db_update_operation, recover_item_db
from mcbe_editor.runtime_data import (
    BUNDLED_ITEM_DB_JSON,
    BUNDLED_SOURCE_VERSION_HISTORY_RELATIVE_PATH,
    BUNDLED_SOURCE_VERSION_RELATIVE_PATH,
    item_db_matches_bundled,
    prepare_persistent_item_db,
    prepare_persistent_json_file,
)

APP_ROOT = Path(__file__).resolve().parents[1]
APP_CONFIG = load_config()
_TARGETS = (
    configured_targets(APP_CONFIG.item_db_path, APP_CONFIG.source_version_path, APP_CONFIG.source_version_history_path)
    if all((APP_CONFIG.item_db_path, APP_CONFIG.source_version_path, APP_CONFIG.source_version_history_path))
    else None
)
with item_db_update_operation(_TARGETS) if _TARGETS else nullcontext():
    if _TARGETS:
        recover_item_db(_TARGETS)
    PERSISTENT_ITEM_DB_PATH = prepare_persistent_item_db(APP_CONFIG.item_db_path, BUNDLED_ITEM_DB_JSON)
    # Older packages omitted provenance. Repair it only for the unchanged bundled
    # database; a different persistent database must keep its provenance unknown.
    _SEED_BUNDLED_METADATA = item_db_matches_bundled(PERSISTENT_ITEM_DB_PATH or BUNDLED_ITEM_DB_JSON, BUNDLED_ITEM_DB_JSON)
    PERSISTENT_SOURCE_VERSION_PATH = prepare_persistent_json_file(
        APP_CONFIG.source_version_path,
        APP_ROOT / BUNDLED_SOURCE_VERSION_RELATIVE_PATH,
        "source_version.json",
        seed_bundled=_SEED_BUNDLED_METADATA,
    )
    PERSISTENT_SOURCE_VERSION_HISTORY_PATH = prepare_persistent_json_file(
        APP_CONFIG.source_version_history_path,
        APP_ROOT / BUNDLED_SOURCE_VERSION_HISTORY_RELATIVE_PATH,
        "source_version_history.json",
        seed_bundled=_SEED_BUNDLED_METADATA,
    )
