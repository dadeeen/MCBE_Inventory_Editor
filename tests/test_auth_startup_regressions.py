from dataclasses import replace
from io import BytesIO
from unittest.mock import Mock
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.request

import pytest

from mcbe_editor.setup_state import FirstRunSetup
from tests.node_runner import run_node


def _configure(monkeypatch, tmp_path, *, password=None, host="0.0.0.0"):
    import main

    monkeypatch.setattr(
        main,
        "APP_CONFIG",
        replace(
            main.APP_CONFIG,
            mode="local",
            host="127.0.0.1",
            auth_required=False,
            auth_password=password,
            auth_password_hash=None,
            fail_on_insecure_config=False,
        ),
    )
    monkeypatch.setattr(main, "RUNTIME_BIND_HOST", host)
    monkeypatch.setattr(main, "SETUP_STATE", FirstRunSetup(tmp_path / "setup.json"))
    return main


def test_cli_bind_override_rechecks_unwritable_setup(monkeypatch, tmp_path):
    main = _configure(monkeypatch, tmp_path)
    monkeypatch.setattr(main.SETUP_STATE, "_storage_available", False)
    main.validate_startup_security("127.0.0.1")
    with pytest.raises(RuntimeError, match="persistent setup path is not writable"):
        main.validate_startup_security("0.0.0.0")
    monkeypatch.setattr(main, "APP_CONFIG", replace(main.APP_CONFIG, auth_password="configured-password"))
    main.validate_startup_security("0.0.0.0")


@pytest.mark.parametrize("host", ["", "   "])
def test_cli_rejects_empty_bind_host_before_listening(tmp_path, host):
    app_root = Path(__file__).resolve().parents[1]
    env = {key: value for key, value in os.environ.items() if not key.startswith("MCBE_")}
    env.update(
        {
            "MCBE_DATA_ROOT": str(tmp_path / "data"),
            "MCBE_BACKUP_ROOT": str(tmp_path / "backups"),
            "MCBE_WORLDS_ROOT": str(tmp_path / "no-worlds"),
            "MCBE_READ_ONLY": "true",
            "MCBE_STARTUP_SECURITY_REPORT": "false",
        }
    )
    # An invalid port also prevents a listener if host validation regresses.
    result = subprocess.run(
        [sys.executable, str(app_root / "main.py"), f"--host={host}", "--port=-1", "--no-browser"],
        cwd=app_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 2, result.stderr
    assert "--host must not be empty" in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("page,password,config_status", [("setup", None, 428), ("login", "secret", 401)])
def test_auth_pages_keep_alive_with_csrf_without_unlocking_api(monkeypatch, tmp_path, page, password, config_status):
    main = _configure(monkeypatch, tmp_path, password=password)
    monkeypatch.setattr(main, "LAST_HEARTBEAT", 0.0)
    monkeypatch.setattr(main, "_heartbeat_now", lambda: 42.0)
    with main.app.test_client() as client:
        response = client.get(f"/{page}")
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-store"
        assert b"auth_heartbeat.js" in response.data
        token = re.search(rb'<meta name="csrf-token" content="([^"]+)"', response.data).group(1).decode()
        assert client.get("/healthz").status_code == 200
        assert client.get("/api/config").status_code == config_status
        assert client.post("/api/heartbeat").status_code == 403
        assert main.LAST_HEARTBEAT == 0.0
        headers = {"X-CSRF-Token": token, "Origin": "https://untrusted.example"}
        assert client.post("/api/heartbeat", headers=headers).status_code == 403
        assert main.LAST_HEARTBEAT == 0.0
        headers["Origin"] = "http://localhost"
        assert client.post("/api/heartbeat", headers=headers).status_code == 200
        assert main.LAST_HEARTBEAT == 42.0
        assert client.get("/api/config").status_code == config_status


@pytest.mark.parametrize("action", ["open", "password"])
def test_failed_setup_storage_write_keeps_unauthenticated_api_blocked(monkeypatch, tmp_path, action):
    import mcbe_editor.setup_state as setup_state_module

    main = _configure(monkeypatch, tmp_path)
    audit = Mock()
    monkeypatch.setattr(main, "audit_event", audit)
    original_secret = main.app.secret_key
    with main.app.test_client() as client:
        assert client.get("/setup").status_code == 200
        assert client.get("/api/config").status_code == 428
        with client.session_transaction() as session:
            token = session["setup_csrf_token"]

        # The directory becomes unwritable after startup and after the setup
        # form was loaded. The operation lock itself can still be acquired.
        monkeypatch.setattr(setup_state_module, "atomic_write_private_text", Mock(side_effect=PermissionError("storage unavailable")))
        response = client.post(
            "/setup",
            data={
                "_setup_token": token,
                "action": action,
                "risk_ack": "yes",
                "username": "admin",
                "password": "long password",
                "password_confirm": "long password",
            },
        )

        assert response.status_code == 200
        assert "Die Ersteinrichtung konnte nicht gespeichert werden." in response.get_data(as_text=True)
        assert main.SETUP_STATE.storage_available is False
        assert main.SETUP_STATE.completed() is False
        assert not main.SETUP_STATE.path.exists()
        assert main.app.secret_key == original_secret
        assert main.first_run_setup_required() is True
        assert client.get("/api/config").status_code == 428
        assert client.post("/api/scan_paths/add", json={"path": "unused"}).status_code == 428
        assert client.get("/setup").status_code == 200
        with client.session_transaction() as session:
            assert session["setup_csrf_token"] == token
            assert session.get("authenticated") is not True
    audit.assert_not_called()

    with main.app.test_client() as fresh_client:
        assert fresh_client.get("/api/config").status_code == 428


@pytest.mark.parametrize("host,open_acknowledged", [("127.0.0.1", False), ("0.0.0.0", True)])
def test_unwritable_setup_storage_preserves_authorized_open_modes(monkeypatch, tmp_path, host, open_acknowledged):
    main = _configure(monkeypatch, tmp_path, host=host)
    if open_acknowledged:
        main.SETUP_STATE.save_open()
    monkeypatch.setattr(main.SETUP_STATE, "_storage_available", False)

    assert main.first_run_setup_required() is False
    with main.app.test_client() as client:
        assert client.get("/api/config").status_code == 200


@pytest.mark.parametrize("host,browser_host", [("::1", "[::1]"), ("::", "[::1]"), ("0.0.0.0", "127.0.0.1")])
def test_auto_browser_uses_public_health_endpoint_and_ipv6_brackets(monkeypatch, host, browser_host):
    import main
    import webbrowser

    ready = Mock(return_value=BytesIO(b"ok"))
    opened = Mock(return_value=True)
    monkeypatch.setattr(urllib.request, "urlopen", ready)
    monkeypatch.setattr(main.sys, "platform", "test-posix")
    monkeypatch.setattr(webbrowser, "open", opened)
    main.open_browser_when_ready(host, 5010)
    ready.assert_called_once_with(f"http://{browser_host}:5010/healthz", timeout=2)
    opened.assert_called_once_with(f"http://{browser_host}:5010/", new=2)


def test_auth_heartbeat_script_sends_token_immediately_and_every_five_seconds():
    run_node(r"""
        const vm = require("vm"), fs = require("fs"), assert = require("assert");
        const sent = [];
        let tick;
        vm.runInNewContext(fs.readFileSync("static/auth_heartbeat.js", "utf8"), {
            document: {querySelector: () => ({content: "session-token"})},
            window: {setInterval: (callback, delay) => {assert.equal(delay, 5000); tick = callback;}},
            fetch: (url, options) => {sent.push({url, options}); return Promise.resolve();},
        });
        assert.equal(sent.length, 1);
        tick(); tick(); tick(); tick();
        assert.equal(sent.length, 5);
        for (const {url, options} of sent) {
            assert.equal(url, "/api/heartbeat");
            assert.equal(options.method, "POST");
            assert.equal(options.headers["X-CSRF-Token"], "session-token");
        }
    """)
