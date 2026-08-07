from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from scripts import browser_smoke


def test_playwright_command_uses_node_cli_instead_of_platform_shim(tmp_path, monkeypatch):
    cli = tmp_path / "node_modules" / "playwright" / "cli.js"
    cli.parent.mkdir(parents=True)
    cli.write_text("", encoding="utf-8")
    monkeypatch.setattr(browser_smoke, "ROOT", tmp_path)
    monkeypatch.setattr(browser_smoke.shutil, "which", lambda name: "/usr/bin/node" if name == "node" else None)

    assert browser_smoke._playwright_command() == ["/usr/bin/node", str(cli)]


def test_playwright_command_reports_missing_install(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(browser_smoke, "ROOT", tmp_path)

    try:
        browser_smoke._playwright_command()
    except SystemExit as exc:
        assert exc.code == 2
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("SystemExit erwartet")

    assert "npm ci --ignore-scripts" in capsys.readouterr().err


def test_browser_smoke_relaunches_through_repository_venv(tmp_path, monkeypatch):
    relative_python = "Scripts/python.exe" if browser_smoke.os.name == "nt" else "bin/python"
    project_python = tmp_path / ".venv" / relative_python
    project_python.parent.mkdir(parents=True)
    project_python.write_text("", encoding="utf-8")
    global_python = tmp_path / "global" / "python"
    global_python.parent.mkdir()
    global_python.write_text("", encoding="utf-8")
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=7)

    monkeypatch.setattr(browser_smoke, "ROOT", tmp_path)
    monkeypatch.setattr(browser_smoke.sys, "executable", str(global_python))
    monkeypatch.delenv(browser_smoke.VENV_REEXEC_ENV, raising=False)
    monkeypatch.setattr(browser_smoke.subprocess, "run", fake_run)

    assert browser_smoke._run_in_project_venv(["--grep", "smoke"]) == 7
    assert calls[0][0][0] == str(project_python)
    assert calls[0][0][-2:] == ["--grep", "smoke"]
    assert calls[0][1]["cwd"] == tmp_path
    assert calls[0][1]["env"][browser_smoke.VENV_REEXEC_ENV] == "1"


def test_browser_smoke_runtime_paths_stay_in_external_run_root(tmp_path, monkeypatch):
    run_root = tmp_path / "browser-run"
    monkeypatch.setattr(browser_smoke, "TMP", run_root)

    env = browser_smoke._server_env(browser_smoke.SERVER_SPECS[0])

    assert Path(env["MCBE_DATA_ROOT"]).is_relative_to(run_root)
    for key in browser_smoke.PROFILE_DIRS:
        assert Path(env[key]).is_relative_to(run_root)


def test_browser_smoke_prunes_stale_runs_before_playwright(tmp_path, monkeypatch):
    run_root = tmp_path / "browser-smoke-123-aaaaaaaa"
    calls = []
    monkeypatch.setattr(browser_smoke, "TMP", run_root)
    monkeypatch.setattr(browser_smoke, "SERVER_SPECS", ())
    monkeypatch.setattr(browser_smoke, "_run_in_project_venv", lambda _args: None)
    monkeypatch.setattr(browser_smoke, "prune_stale_test_artifacts", lambda **kwargs: calls.append(("prune", kwargs)) or [])
    monkeypatch.setattr(browser_smoke, "_run_playwright", lambda args: calls.append(("playwright", args)) or 0)

    assert browser_smoke.main(["--grep", "smoke"]) == 0
    assert calls == [
        ("prune", {"protected": (run_root,)}),
        ("playwright", ["--grep", "smoke"]),
    ]


def test_browser_smoke_server_failure_is_not_masked_by_external_log_path(tmp_path, monkeypatch, capsys):
    repository = tmp_path / "checkout"
    log_path = tmp_path / "artifacts" / "server.log"
    repository.mkdir()
    log_path.parent.mkdir()
    log_path.write_text("server startup failed\n", encoding="utf-8")
    process = SimpleNamespace(returncode=17, poll=lambda: 17)
    spec = browser_smoke.ServerSpec(65530, "data", "false", "false")
    monkeypatch.setattr(browser_smoke, "ROOT", repository)

    assert not log_path.is_relative_to(browser_smoke.ROOT)

    try:
        browser_smoke._wait_for_health(spec, process, log_path)
    except RuntimeError as exc:
        assert "exited with code 17" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("RuntimeError erwartet")

    stderr = capsys.readouterr().err
    assert str(log_path) in stderr
    assert "server startup failed" in stderr
