from dataclasses import replace
from io import BytesIO
from unittest.mock import Mock
import re
import subprocess
import urllib.request

import pytest

from mcbe_editor.setup_state import FirstRunSetup


def _configure(monkeypatch, tmp_path, *, password=None, host="0.0.0.0"):
    import main

    monkeypatch.setattr(main, "APP_CONFIG", replace(
        main.APP_CONFIG, mode="local", host="127.0.0.1", auth_required=False,
        auth_password=password, auth_password_hash=None, fail_on_insecure_config=False,
    ))
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
    result = subprocess.run(["node", "-e", r'''
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
    '''], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
