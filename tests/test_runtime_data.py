from __future__ import annotations

import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from mcbe_editor import runtime_data
from mcbe_editor.runtime_data import prepare_persistent_item_db, prepare_persistent_json_file, restrict_private_file

ROOT = Path(__file__).resolve().parents[1]


def test_prepare_persistent_json_file_seeds_missing_metadata(tmp_path):
    bundled = tmp_path / "source_version.json"
    bundled.write_text('{"generated_at":"release"}', encoding="utf-8")
    target = tmp_path / "data" / "source_version.json"

    result = prepare_persistent_json_file(str(target), bundled, "source_version.json")

    assert result == target.resolve()
    assert target.read_text(encoding="utf-8") == '{"generated_at":"release"}'


def test_prepare_persistent_json_file_keeps_existing_metadata(tmp_path):
    bundled = tmp_path / "source_version.json"
    bundled.write_text('{"generated_at":"release"}', encoding="utf-8")
    target = tmp_path / "data" / "source_version.json"
    target.parent.mkdir()
    target.write_text('{"generated_at":"local"}', encoding="utf-8")

    prepare_persistent_json_file(str(target), bundled, "source_version.json")

    assert target.read_text(encoding="utf-8") == '{"generated_at":"local"}'


def test_prepare_persistent_json_file_does_not_leave_partial_target_on_copy_failure(tmp_path, monkeypatch):
    bundled = tmp_path / "source_version.json"
    bundled.write_text('{"generated_at":"release"}', encoding="utf-8")
    target = tmp_path / "data" / "source_version.json"

    def fail_after_partial_copy(source, destination, length=0):
        del source, length
        destination.write(b'{"generated_at":')
        raise OSError("simulated interrupted seed")

    monkeypatch.setattr(runtime_data.shutil, "copyfileobj", fail_after_partial_copy)

    with pytest.raises(OSError, match="interrupted seed"):
        prepare_persistent_json_file(str(target), bundled, "source_version.json")

    assert not target.exists()
    assert list(target.parent.glob(f".{target.name}.*.tmp")) == []


def test_atomic_seed_file_keeps_an_existing_target(tmp_path):
    bundled = tmp_path / "bundled.json"
    bundled.write_text('{"generated_at":"release"}', encoding="utf-8")
    target = tmp_path / "data" / "source_version.json"
    target.parent.mkdir()
    target.write_text('{"generated_at":"local"}', encoding="utf-8")

    runtime_data.atomic_seed_file(bundled, target)

    assert target.read_text(encoding="utf-8") == '{"generated_at":"local"}'
    assert list(target.parent.glob(f".{target.name}.*.tmp")) == []


def test_prepare_persistent_json_file_is_safe_during_concurrent_first_start(tmp_path, monkeypatch):
    bundled = tmp_path / "source_version.json"
    expected = '{"generated_at":"release","items":[1,2,3]}'
    bundled.write_text(expected, encoding="utf-8")
    target = tmp_path / "data" / "source_version.json"
    workers = 8
    barrier = threading.Barrier(workers)
    original_copyfileobj = runtime_data.shutil.copyfileobj

    def synchronized_copy(source, destination, length=0):
        barrier.wait(timeout=5)
        return original_copyfileobj(source, destination, length=length)

    monkeypatch.setattr(runtime_data.shutil, "copyfileobj", synchronized_copy)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        results = list(
            executor.map(
                lambda _index: prepare_persistent_json_file(str(target), bundled, "source_version.json"),
                range(workers),
            )
        )

    assert results == [target.resolve()] * workers
    assert target.read_text(encoding="utf-8") == expected
    assert list(target.parent.glob(f".{target.name}.*.tmp")) == []


def test_prepare_persistent_json_file_rejects_wrong_filename(tmp_path):
    bundled = tmp_path / "source_version.json"
    bundled.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="source_version.json"):
        prepare_persistent_json_file(str(tmp_path / "wrong.json"), bundled, "source_version.json")


def test_prepare_persistent_item_db_sets_environment(tmp_path, monkeypatch):
    monkeypatch.delenv("MCBE_ITEM_DB_PATH", raising=False)
    bundled = tmp_path / "item_db.json"
    bundled.write_text('{"schema_version":1,"items":{}}', encoding="utf-8")
    target = tmp_path / "data" / "item_db.json"

    result = prepare_persistent_item_db(str(target), bundled)

    assert result == target.resolve()
    assert os.environ["MCBE_ITEM_DB_PATH"] == str(target.resolve())
    assert target.exists()


def test_main_bootstrap_loads_persistent_item_database_before_services(tmp_path):
    data_root = tmp_path / "data"
    item_db = data_root / "item_db.json"
    env = os.environ.copy()
    env.update(
        {
            "MCBE_DATA_ROOT": str(data_root),
            "MCBE_ITEM_DB_PATH": str(item_db),
            "MCBE_STARTUP_SECURITY_REPORT": "false",
        }
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import main; print(main.item_data_module.ITEM_DB_SOURCE_PATH)",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert result.stdout.strip() == str(item_db.resolve())
    assert item_db.is_file()


def test_main_bootstrap_recovers_corrupt_item_database_from_older_volume(tmp_path):
    data_root = tmp_path / "data"
    data_root.mkdir()
    item_db = data_root / "item_db.json"
    corrupt_payload = '{"schema_version":'
    item_db.write_text(corrupt_payload, encoding="utf-8")
    env = os.environ.copy()
    env.update(
        {
            "MCBE_DATA_ROOT": str(data_root),
            "MCBE_ITEM_DB_PATH": str(item_db),
            "MCBE_STARTUP_SECURITY_REPORT": "false",
        }
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import main; print(main.item_data_module.ITEM_DB_SOURCE_PATH)",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert result.stdout.strip() == str(item_db.resolve())
    assert '"minecraft:air"' in item_db.read_text(encoding="utf-8")
    quarantined = list(data_root.glob("item_db.invalid-*.json"))
    assert len(quarantined) == 1
    assert quarantined[0].read_text(encoding="utf-8") == corrupt_payload


def test_restrict_private_file_does_not_chmod_an_already_private_file(tmp_path, monkeypatch):
    if os.name == "nt":
        pytest.skip("POSIX mode check")
    path = tmp_path / "setup.json"
    path.write_text("{}", encoding="utf-8")
    path.chmod(0o600)

    def unexpected_chmod(_self, _mode):
        raise AssertionError("chmod must not be attempted for an already private file")

    monkeypatch.setattr(Path, "chmod", unexpected_chmod)
    restrict_private_file(path)
