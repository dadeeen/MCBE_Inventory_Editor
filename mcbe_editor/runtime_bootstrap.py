"""Prepare writable runtime data before modules import the item catalog."""

from __future__ import annotations

from pathlib import Path

from mcbe_editor.config import load_config
from mcbe_editor.runtime_data import BUNDLED_ITEM_DB_JSON, prepare_persistent_item_db, prepare_persistent_json_file

APP_ROOT = Path(__file__).resolve().parents[1]
APP_CONFIG = load_config()
PERSISTENT_ITEM_DB_PATH = prepare_persistent_item_db(APP_CONFIG.item_db_path, BUNDLED_ITEM_DB_JSON)
PERSISTENT_SOURCE_VERSION_PATH = prepare_persistent_json_file(
    APP_CONFIG.source_version_path,
    APP_ROOT / "source_version.json",
    "source_version.json",
)
PERSISTENT_SOURCE_VERSION_HISTORY_PATH = prepare_persistent_json_file(
    APP_CONFIG.source_version_history_path,
    APP_ROOT / "source_version_history.json",
    "source_version_history.json",
)
