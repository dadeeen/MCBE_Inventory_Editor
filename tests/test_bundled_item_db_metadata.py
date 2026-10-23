"""Packaged startup keeps public provenance separate from private runtime state."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from mcbe_editor import item_db_verification
from scripts.make_release_zip import should_include
from scripts.release_rules import BLOCKED_RELEASE_FILE_NAMES
from scripts.runtime_layout import REQUIRED_RUNTIME_FILES, iter_runtime_files

ROOT = Path(__file__).resolve().parents[1]
RESOURCE_METADATA = {
    "source_version.json": Path("mcbe_editor/resources/item_db_source.json"),
    "source_version_history.json": Path("mcbe_editor/resources/item_db_source_history.json"),
}
PROBE = """
import json
from types import SimpleNamespace
from mcbe_editor import runtime_bootstrap as runtime, status_snapshots
status = status_snapshots.item_db_status_snapshot(
    runtime.APP_CONFIG,
    SimpleNamespace(ITEM_DB_SOURCE_PATH=str(runtime.PERSISTENT_ITEM_DB_PATH)),
    runtime.APP_ROOT,
)
print(json.dumps({
    'app_root': str(runtime.APP_ROOT),
    'status': status,
    'bundled_history': status_snapshots.source_version_history_entries(None, runtime.APP_ROOT),
}))
"""


@pytest.fixture
def packaged_runtime(tmp_path):
    """Copy the actual package inputs without checkout-only root metadata."""
    runtime = tmp_path / "runtime"
    for path in iter_runtime_files(ROOT):
        relative = path.relative_to(ROOT)
        if relative.parts[0] == "mcbe_editor" and should_include(path):
            target = runtime / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
    assert not (runtime / "source_version.json").exists()
    assert not (runtime / "source_version_history.json").exists()
    return runtime


def _probe(runtime, data_root):
    env = {key: value for key, value in os.environ.items() if not key.startswith("MCBE_")}
    env.update(PYTHONPATH=str(runtime), PYTHONDONTWRITEBYTECODE="1", MCBE_DATA_ROOT=str(data_root))
    result = subprocess.run([sys.executable, "-c", PROBE], cwd=runtime.parent, env=env, text=True, capture_output=True, timeout=30, check=True)
    payload = json.loads(result.stdout)
    assert payload["app_root"] == str(runtime)
    return payload


def test_public_provenance_resources_ship_without_relaxing_private_file_rules():
    for private_name, relative in RESOURCE_METADATA.items():
        assert relative.as_posix() in REQUIRED_RUNTIME_FILES
        assert should_include(ROOT / relative)
        assert (ROOT / relative).read_bytes() == (ROOT / private_name).read_bytes()
        assert private_name in BLOCKED_RELEASE_FILE_NAMES
        assert not should_include(ROOT / private_name)
        assert not should_include(ROOT / "mcbe_editor" / private_name)


def test_packaged_first_start_seeds_database_and_public_metadata_without_verifying_it(packaged_runtime, tmp_path):
    data = tmp_path / "data"
    payload = _probe(packaged_runtime, data)

    assert (data / "item_db.json").read_bytes() == (packaged_runtime / "mcbe_editor/resources/item_db.json").read_bytes()
    for private_name, relative in RESOURCE_METADATA.items():
        assert (data / private_name).read_bytes() == (packaged_runtime / relative).read_bytes()
    status = payload["status"]
    assert status["status"] == "ok"
    assert status["source_version_present"] is True
    assert status["matches_bundled_snapshot"] is True
    assert status["history_count"] == len(payload["bundled_history"]) > 0
    assert status["verification"]["verified"] is False
    assert status["verification"]["reason"] == "missing"
    assert "verification" not in status["source_version"]


@pytest.mark.parametrize("same_database", [True, False])
def test_upgrade_repairs_missing_provenance_only_for_the_actual_bundled_bytes(packaged_runtime, tmp_path, same_database):
    data = tmp_path / "data"
    data.mkdir()
    database = (packaged_runtime / "mcbe_editor/resources/item_db.json").read_bytes()
    if not same_database:
        # Same byte length: file name and size cannot prove the source identity.
        database = database.replace(b"Stone", b"stone", 1)
        assert database != (packaged_runtime / "mcbe_editor/resources/item_db.json").read_bytes()
    (data / "item_db.json").write_bytes(database)

    payload = _probe(packaged_runtime, data)

    assert (data / "item_db.json").read_bytes() == database
    for private_name, relative in RESOURCE_METADATA.items():
        if same_database:
            assert (data / private_name).read_bytes() == (packaged_runtime / relative).read_bytes()
        else:
            assert not (data / private_name).exists()
    status = payload["status"]
    assert status["source_version_present"] is same_database
    assert status["matches_bundled_snapshot"] is same_database
    assert status["verification"]["verified"] is False
    if not same_database:
        assert status["status"] == "metadata-missing"
        assert status["source_version"] == {}
        assert status["history_count"] == 0


@pytest.mark.parametrize("same_database", [True, False])
def test_restart_preserves_existing_provenance_receipt_history_and_settings(packaged_runtime, tmp_path, same_database):
    data = tmp_path / "data"
    data.mkdir()
    database = (packaged_runtime / "mcbe_editor/resources/item_db.json").read_bytes()
    item_db = data / "item_db.json"
    item_db.write_bytes(database if same_database else database + b"\n")
    metadata = json.loads((packaged_runtime / RESOURCE_METADATA["source_version.json"]).read_text(encoding="utf-8"))
    verified = item_db_verification.attach_item_db_verification(metadata, item_db, verified_at="2026-10-01T00:00:00+00:00")
    (data / "source_version.json").write_text(json.dumps(verified), encoding="utf-8")
    (data / "source_version_history.json").write_text(json.dumps([verified]), encoding="utf-8")
    (data / "settings.json").write_text('{"item_db_verified":true,"custom_setting":"keep"}', encoding="utf-8")
    before = {path.name: path.read_bytes() for path in data.iterdir()}

    payload = _probe(packaged_runtime, data)

    assert {name: (data / name).read_bytes() for name in before} == before
    assert payload["status"]["source_version"] == verified
    assert payload["status"]["history_count"] == 1
    assert payload["status"]["verification"]["verified"] is True
    assert payload["status"]["verification"]["verified_at"] == "2026-10-01T00:00:00+00:00"
