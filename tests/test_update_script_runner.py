import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from mcbe_editor import update_script_runner


class Completed:
    returncode = 7
    stdout = "script output"


def test_run_update_db_builds_command_env_and_directories(tmp_path, monkeypatch):
    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return Completed()

    monkeypatch.setattr(update_script_runner.subprocess, "run", fake_run)
    config = SimpleNamespace(
        item_db_path=str(tmp_path / "data" / "item_db.json"),
        update_cache_dir=str(tmp_path / "cache"),
        source_version_path=str(tmp_path / "meta" / "source_version.json"),
        source_version_history_path=str(tmp_path / "meta" / "source_version_history.json"),
    )

    result = update_script_runner.run_update_db(
        tmp_path,
        config,
        dry_run=True,
        force=True,
        only="items",
        use_cache=True,
        expected_review_token="a" * 64,
    )

    assert result == (7, "script output")
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args[0] == [
        update_script_runner.sys.executable,
        "-m",
        "scripts.update_db",
        "--dry-run",
        "--force",
        "--cache",
        "--expected-review-token",
        "a" * 64,
        "--only",
        "items",
    ]
    assert kwargs["cwd"] == str(tmp_path)
    assert kwargs["timeout"] == 180
    assert kwargs["check"] is False
    assert kwargs["env"]["NO_COLOR"] == "1"
    assert kwargs["env"]["MCBE_UPDATE_LOCALE"] == "de"
    assert kwargs["env"]["MCBE_ITEM_DB_PATH"] == config.item_db_path
    assert kwargs["env"]["MCBE_UPDATE_CACHE_DIR"] == config.update_cache_dir
    assert (tmp_path / "data").is_dir()
    assert (tmp_path / "cache").is_dir()
    assert (tmp_path / "meta").is_dir()


def test_run_update_icons_builds_icon_cache_env_and_directories(tmp_path, monkeypatch):
    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return Completed()

    monkeypatch.setattr(update_script_runner.subprocess, "run", fake_run)
    config = SimpleNamespace(
        data_root=str(tmp_path / "data"),
        item_db_path=str(tmp_path / "data" / "item_db.json"),
        update_cache_dir=str(tmp_path / "cache"),
    )

    result = update_script_runner.run_update_icons(tmp_path, config, force=True, use_cache=False, locale="en")

    assert result == (7, "script output")
    args, kwargs = calls[0]
    assert args[0] == [update_script_runner.sys.executable, "-m", "scripts.update_icons", "--force"]
    assert kwargs["cwd"] == str(tmp_path)
    assert kwargs["timeout"] == 300
    assert kwargs["env"]["NO_COLOR"] == "1"
    assert kwargs["env"]["MCBE_UPDATE_LOCALE"] == "en"
    assert kwargs["env"]["MCBE_DATA_ROOT"] == str(tmp_path / "data")
    assert kwargs["env"]["MCBE_ICON_CACHE_ROOT"] == str(tmp_path / "data" / "icons" / "vanilla")
    assert (tmp_path / "data").is_dir()
    assert (tmp_path / "data" / "icons").is_dir()
    assert (tmp_path / "cache").is_dir()


def test_looks_like_network_failure_classifies_common_errors():
    assert update_script_runner.looks_like_network_failure("Temporary failure in name resolution")
    assert update_script_runner.looks_like_network_failure("urlopen error timed out")
    assert not update_script_runner.looks_like_network_failure("schema validation failed")


def test_strip_terminal_formatting_removes_ansi_and_normalizes_newlines():
    output = "\x1b[1m\x1b[96mÜberschrift\x1b[0m\r\n\x1b[92mFertig\x1b[0m\r"

    assert update_script_runner.strip_terminal_formatting(output) == "Überschrift\nFertig\n"


def test_update_runner_falls_back_to_german_for_an_unknown_locale(tmp_path, monkeypatch):
    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return Completed()

    monkeypatch.setattr(update_script_runner.subprocess, "run", fake_run)
    config = SimpleNamespace(
        data_root=str(tmp_path / "data"),
        item_db_path=str(tmp_path / "data" / "item_db.json"),
        update_cache_dir=str(tmp_path / "cache"),
    )

    update_script_runner.run_update_icons(tmp_path, config, locale="fr")

    assert calls[0][1]["env"]["MCBE_UPDATE_LOCALE"] == "de"


@pytest.mark.parametrize("script_name", ["update_db.py", "update_icons.py"])
def test_update_scripts_support_isolated_direct_execution(script_name):
    root = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        [sys.executable, "-I", str(root / "scripts" / script_name), "--help"],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30,
        check=False,
    )

    assert proc.returncode == 0, proc.stdout
    assert "usage:" in proc.stdout.lower()
