from __future__ import annotations


from mcbe_editor.config import load_config
from mcbe_editor.deployment import worlds_root_status, write_gate_setup_status


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


def test_dockerfile_uses_configured_internal_port_for_runtime_and_healthcheck():
    dockerfile = __import__("pathlib").Path("Dockerfile").read_text(encoding="utf-8")

    assert "${MCBE_EDITOR_PORT:-8080}" in dockerfile
    assert "os.environ.get('MCBE_EDITOR_PORT', '8080')" in dockerfile


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
