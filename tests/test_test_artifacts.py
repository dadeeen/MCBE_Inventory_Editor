from __future__ import annotations

import os
from pathlib import Path

import pytest

from scripts import test_artifacts, test_full


def _set_mtime(path: Path, value: float) -> None:
    os.utime(path, (value, value))


def test_stale_test_artifact_pruning_is_scoped_and_preserves_active_runs(tmp_path, monkeypatch):
    root = tmp_path / "artifact-root"
    root.mkdir()
    now = 2_000_000_000.0
    expired = [
        root / "browser-smoke-101-aaaaaaaa",
        root / "playwright-202",
    ]
    active = root / "full-suite-basetemp-303-bbbbbbbb"
    protected = root / "browser-smoke-404-cccccccc"
    fresh = root / "browser-smoke-505-dddddddd"
    unknown = root / "keep-me"

    for path in [*expired, active, protected, fresh, unknown]:
        path.mkdir()
        (path / "diagnostic.txt").write_text(path.name, encoding="utf-8")
    for path in [*expired, active, protected, unknown]:
        _set_mtime(path, now - test_artifacts.DEFAULT_TEST_ARTIFACT_RETENTION_SECONDS - 1)
    _set_mtime(fresh, now)

    monkeypatch.setenv(test_artifacts.TEST_ARTIFACT_ROOT_ENV, str(root))
    monkeypatch.setattr(test_artifacts, "_process_is_running", lambda pid: pid == 303)

    removed = test_artifacts.prune_stale_test_artifacts(protected=(protected,), now=now)

    assert set(removed) == {path.resolve() for path in expired}
    assert all(not path.exists() for path in expired)
    assert active.is_dir()
    assert protected.is_dir()
    assert fresh.is_dir()
    assert unknown.is_dir()


def test_current_process_is_recognized_as_an_active_test_run():
    assert test_artifacts._process_is_running(os.getpid()) is True


def test_default_basetemp_preparation_prunes_before_creating_parent(tmp_path, monkeypatch):
    basetemp = tmp_path / "artifacts" / "full-suite-basetemp-606-eeeeeeee"
    calls = []
    monkeypatch.setattr(test_full, "_default_basetemp", lambda: basetemp)
    monkeypatch.setattr(test_full, "prune_stale_test_artifacts", lambda **kwargs: calls.append(kwargs) or [])

    assert test_full._prepare_default_basetemp() == basetemp
    assert calls == [{"protected": (basetemp,)}]
    assert basetemp.parent.is_dir()


def test_full_runner_prunes_stale_artifacts_with_explicit_basetemp(monkeypatch):
    calls = []
    monkeypatch.setattr(test_full, "_missing_core_dependencies", lambda: [])
    monkeypatch.setattr(test_full, "prune_stale_test_artifacts", lambda **kwargs: calls.append(kwargs) or [])
    monkeypatch.setattr(test_full, "_run_pytest", lambda _command: 0)

    assert test_full.main(["--basetemp=custom", "-q"]) == 0
    assert calls == [{}]


def test_full_runner_reports_retained_failure_diagnostics(tmp_path, monkeypatch, capsys):
    basetemp = tmp_path / "artifacts" / "full-suite-basetemp-707-ffffffff"
    basetemp.mkdir(parents=True)
    monkeypatch.setattr(test_full, "_missing_core_dependencies", lambda: [])
    monkeypatch.setattr(test_full, "_prepare_default_basetemp", lambda: basetemp)
    monkeypatch.setattr(test_full, "_run_pytest", lambda _command: 7)

    assert test_full.main(["-q"]) == 7
    assert basetemp.is_dir()
    assert str(basetemp) in capsys.readouterr().err


@pytest.mark.parametrize("failure", [ImportError("missing oracle"), OSError("unloadable DLL")])
def test_reference_runner_rejects_missing_or_broken_oracles(monkeypatch, capsys, failure):
    monkeypatch.setattr(test_full, "_missing_core_dependencies", lambda: [])
    def unavailable(_name):
        raise failure
    monkeypatch.setattr(test_full.importlib, "import_module", unavailable)
    monkeypatch.setattr(test_full, "_run_pytest", lambda _command: pytest.fail("Must fail before optional tests can skip"))
    assert test_full.main(["--require-references", "-q"]) == 2
    assert "leveldb, amulet_nbt" in capsys.readouterr().err


def test_reference_runner_checks_oracles_and_forwards_only_pytest_arguments(monkeypatch):
    imports, commands = [], []
    monkeypatch.setattr(test_full, "_missing_core_dependencies", lambda: [])
    monkeypatch.setattr(test_full.importlib, "import_module", lambda name: imports.append(name))
    monkeypatch.setattr(test_full, "prune_stale_test_artifacts", lambda **kwargs: [])
    monkeypatch.setattr(test_full, "_run_pytest", lambda command: commands.append(command) or 0)
    assert test_full.main(["--require-references", "--basetemp=custom", "-q"]) == 0
    assert imports == ["leveldb", "amulet_nbt"]
    assert "--require-references" not in commands[0]
    assert "-q" in commands[0]


def test_default_runner_does_not_require_native_oracles(monkeypatch):
    monkeypatch.setattr(test_full, "_missing_core_dependencies", lambda: [])
    monkeypatch.setattr(test_full, "_missing_reference_dependencies", lambda: pytest.fail("Native references are opt-in"))
    monkeypatch.setattr(test_full, "prune_stale_test_artifacts", lambda **kwargs: [])
    monkeypatch.setattr(test_full, "_run_pytest", lambda _command: 0)
    assert test_full.main(["--basetemp=custom", "-q"]) == 0
