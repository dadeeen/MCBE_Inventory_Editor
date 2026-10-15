"""Explicit operator secrets survive startup and first-run setup completion."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from mcbe_editor.config import load_config


@pytest.fixture
def application():
    import main

    return main


def _secret_environment(kind, root):
    if kind == "environment":
        return {"MCBE_SECRET_KEY": "explicit-operator-secret-for-tests"}
    if kind == "file":
        path = root / "operator-secret.txt"
        path.write_text("explicit-operator-secret-for-tests\n", encoding="utf-8")
        return {"MCBE_SECRET_KEY_FILE": str(path)}
    return {}


@pytest.mark.parametrize("kind", ["environment", "file", "generated"])
@pytest.mark.parametrize("candidate", ["persisted-setup-secret", "newly-created-setup-secret"])
def test_setup_completion_preserves_explicit_secret(application, monkeypatch, tmp_path, kind, candidate):
    for name in ("MCBE_SECRET_KEY", "MCBE_SECRET_KEY_FILE"):
        monkeypatch.delenv(name, raising=False)
    for name, value in _secret_environment(kind, tmp_path).items():
        monkeypatch.setenv(name, value)
    config = load_config()
    monkeypatch.setattr(application, "APP_CONFIG", config)
    monkeypatch.setattr(application.app, "secret_key", "previous-in-memory-key")

    application.set_app_secret_key(candidate)

    assert application.app.secret_key == (config.secret_key if kind != "generated" else candidate)


@pytest.mark.parametrize("kind", ["environment", "file", "generated"])
@pytest.mark.parametrize("persisted", [False, True])
def test_startup_preserves_explicit_secret(tmp_path, kind, persisted):
    root = Path(__file__).resolve().parents[1]
    setup = tmp_path / "setup.json"
    stable = "persisted-setup-secret-for-tests"
    if persisted:
        setup.write_text(json.dumps({"secret_key": stable}), encoding="utf-8")
    env = {name: value for name, value in os.environ.items() if not name.startswith("MCBE_")}
    env.update(
        {
            "MCBE_DATA_ROOT": str(tmp_path / "data"),
            "MCBE_BACKUP_ROOT": str(tmp_path / "backups"),
            "MCBE_SETUP_PATH": str(setup),
            "MCBE_READ_ONLY": "true",
            "MCBE_STARTUP_SECURITY_REPORT": "false",
            **_secret_environment(kind, tmp_path),
        }
    )
    script = """
import json
import main
print(json.dumps({"active": main.app.secret_key, "configured": main.APP_CONFIG.secret_key}))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=root,
        env=env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    state = json.loads(result.stdout.strip().splitlines()[-1])
    expected = stable if persisted and kind == "generated" else state["configured"]
    assert state["active"] == expected
    if persisted:
        assert json.loads(setup.read_text(encoding="utf-8")) == {"secret_key": stable}
