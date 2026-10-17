from __future__ import annotations

from pathlib import Path
import urllib.request
from types import SimpleNamespace

import pytest

from mcbe_editor.config import load_config
from mcbe_editor.deployment import worlds_root_status, write_gate_setup_status
from mcbe_editor import healthcheck


def test_docker_worlds_root_empty_warns(tmp_path, monkeypatch):
    monkeypatch.setenv("MCBE_EDITOR_MODE", "docker")
    monkeypatch.setenv("MCBE_WORLDS_ROOT", str(tmp_path))
    config = load_config()

    status = worlds_root_status(config)

    assert status["status"] == "empty"
    assert status["bind_mount_required"] is True


def test_docker_worlds_root_detects_world_hint(tmp_path, monkeypatch):
    world = tmp_path / "Survival"
    (world / "db").mkdir(parents=True)
    monkeypatch.setenv("MCBE_EDITOR_MODE", "docker")
    monkeypatch.setenv("MCBE_WORLDS_ROOT", str(tmp_path))
    config = load_config()

    status = worlds_root_status(config)

    assert status["status"] == "ok"
    assert status["contains_world_hint"] is True


def test_write_gate_reports_missing_server_host(monkeypatch):
    monkeypatch.setenv("MCBE_EDITOR_MODE", "docker")
    monkeypatch.delenv("MCBE_SERVER_HOST", raising=False)
    config = load_config()

    status = write_gate_setup_status(config)

    assert status["status"] == "server-host-missing"
    assert status["writes_blocked_without_server_host"] is True


def test_write_gate_reports_offline_gate_configured(monkeypatch):
    monkeypatch.setenv("MCBE_EDITOR_MODE", "docker")
    monkeypatch.setenv("MCBE_SERVER_HOST", "192.168.175.2")
    config = load_config()

    status = write_gate_setup_status(config)

    assert status["status"] == "configured"
    assert status["writes_blocked_without_server_host"] is False


def test_write_gate_reports_disabled(monkeypatch):
    monkeypatch.setenv("MCBE_EDITOR_MODE", "docker")
    monkeypatch.setenv("MCBE_REQUIRE_SERVER_OFFLINE", "false")
    config = load_config()

    status = write_gate_setup_status(config)

    assert status["status"] == "disabled"
    assert status["writes_blocked_without_server_host"] is False
    assert status["local_world_access_warning"] is False


def test_local_write_gate_disabled_reports_world_access_warning(monkeypatch):
    monkeypatch.setenv("MCBE_EDITOR_MODE", "local")
    monkeypatch.delenv("MCBE_REQUIRE_SERVER_OFFLINE", raising=False)
    config = load_config()

    status = write_gate_setup_status(config)

    assert status["status"] == "disabled"
    assert status["writes_blocked_without_server_host"] is False
    assert status["local_world_access_warning"] is True
    assert "Lokalmodus" in status["message"]


@pytest.mark.parametrize(
    ("configured", "expected_host"),
    [
        ("", "127.0.0.1:8091"),
        ("editor.home.arpa", "editor.home.arpa:8091"),
        ("editor.home.arpa:8443", "editor.home.arpa:8091"),
        ("127.0.0.1:8443", "127.0.0.1:8091"),
        (".home.arpa", "home.arpa:8091"),
        (".home.arpa:8443", "home.arpa:8091"),
        ("[::1]", "[::1]:8091"),
        ("::1", "[::1]:8091"),
        ("invalid/path, editor.home.arpa", "editor.home.arpa:8091"),
        ("invalid:65536, editor.home.arpa:8443", "editor.home.arpa:8091"),
        ("münchen.example", "xn--mnchen-3ya.example:8091"),
        ("münchen.example:8443", "xn--mnchen-3ya.example:8091"),
    ],
)
def test_dockerfile_uses_configured_internal_port_for_runtime_and_direct_healthcheck(monkeypatch, configured, expected_host):
    import main

    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    assert "${MCBE_EDITOR_PORT:-8080}" in dockerfile
    assert 'CMD ["python", "-m", "mcbe_editor.healthcheck"]' in dockerfile
    requests = []

    class LocalConnection:
        def __init__(self, host, port, *, timeout):
            assert (host, port, timeout) == ("127.0.0.1", 8091, 2)

        def request(self, method, path, *, headers):
            requests.append((method, path, headers))
            # Exercise the actual app's host/auth/setup boundary with the
            # check's header while the connection destination stays loopback.
            self.response = main.app.test_client().open(path, method=method, headers=headers)

        def getresponse(self):
            return SimpleNamespace(status=self.response.status_code, read=lambda size: self.response.data[:size])

        def close(self):
            pass

    monkeypatch.setenv("MCBE_EDITOR_PORT", "8091")
    monkeypatch.setenv("MCBE_TRUSTED_HOSTS", configured)
    monkeypatch.setitem(main.app.config, "MCBE_TRUSTED_HOSTS", list(load_config().trusted_hosts) or None)
    monkeypatch.setattr(urllib.request, "getproxies", lambda: {"http": "http://proxy.invalid:3128"})
    monkeypatch.setattr(urllib.request, "proxy_bypass", lambda _host: False)
    monkeypatch.setattr(healthcheck, "HTTPConnection", LocalConnection)
    assert healthcheck.main() == 0
    assert requests == [("GET", "/healthz", {"Host": expected_host})]


@pytest.mark.parametrize(
    "host",
    [
        "",
        " ",
        "https://editor.home.arpa",
        "user@editor.home.arpa",
        "editor.home.arpa/path",
        "editor\r\nInjected: value",
        "editor.home.arpa:0",
        "editor.home.arpa:65536",
        "editor.home.arpa:invalid",
        "editor.home.arpa:8443:8091",
        "editor.home.arpa:",
    ],
)
def test_healthcheck_rejects_invalid_configured_hosts_before_connecting(monkeypatch, host):
    def unexpected_connection(*args, **kwargs):
        pytest.fail("An invalid health-check host must not open a connection")

    monkeypatch.setattr(healthcheck, "HTTPConnection", unexpected_connection)
    with pytest.raises(ValueError, match="no valid health-check hostname"):
        healthcheck.check_health(8080, trusted_hosts=(host,))


@pytest.mark.parametrize(("status", "body"), [(302, b""), (200, b"not json"), (200, b'{"status":"unhealthy"}')])
def test_healthcheck_rejects_redirects_and_unexpected_health_payloads(monkeypatch, status, body, capsys):
    response = SimpleNamespace(status=status, read=lambda size: body[:size])
    connection = SimpleNamespace(request=lambda *args, **kwargs: None, getresponse=lambda: response, close=lambda: None)
    monkeypatch.setattr(healthcheck, "HTTPConnection", lambda *args, **kwargs: connection)
    monkeypatch.delenv("MCBE_TRUSTED_HOSTS", raising=False)
    assert healthcheck.main() == 1
    assert "Local health check failed" in capsys.readouterr().err


def test_write_gate_public_payload_does_not_expose_secrets(monkeypatch):
    from mcbe_editor.server_status import write_gate

    monkeypatch.setenv("MCBE_EDITOR_MODE", "docker")
    monkeypatch.setenv("MCBE_SERVER_HOST", "192.168.175.2")
    monkeypatch.setenv("MCBE_AUTH_PASSWORD", "plain-secret")
    monkeypatch.setenv("MCBE_AUTH_PASSWORD_HASH", "hash-secret")
    monkeypatch.setenv("MCBE_SECRET_KEY", "session-secret")
    config = load_config()

    gate = write_gate(config, {"status": "offline", "message": "test"})

    assert gate["config"] == {
        "mode": "docker",
        "server_name": "Bedrock Server",
        "server_host": "192.168.175.2",
        "server_port": 19132,
        "require_server_offline": True,
        "allow_edit_while_online": False,
        "read_only": False,
    }
    assert "auth_password" not in gate["config"]
    assert "auth_password_hash" not in gate["config"]
    assert "secret_key" not in gate["config"]
    assert "allowed_origins" not in gate["config"]


def test_compose_example_uses_simple_host_port_mapping():
    compose = __import__("pathlib").Path("docker-compose.example.yml").read_text(encoding="utf-8")

    assert '- "8088:8080"' in compose
    assert '- "192.168.1.100:8088:8080"' not in compose
    assert 'Optional tighter bind: "192.168.1.100:8088:8080"' in compose
