from __future__ import annotations

import importlib
import os


def _fresh_config_module(monkeypatch):
    import mcbe_editor.config as config

    for name in list(os.environ):
        if not name.startswith("MCBE_"):
            continue
        monkeypatch.delenv(name, raising=False)
    return importlib.reload(config)


def _portable_path(path: str | None) -> str:
    return (path or "").replace("\\", "/")


def test_host_reachability_helper_keeps_loopback_local(monkeypatch):
    config = _fresh_config_module(monkeypatch)

    for host in ("127.0.0.1", "127.42.0.7", "::1", "[::1]", "localhost"):
        assert config.host_reaches_beyond_loopback(host) is False


def test_host_reachability_helper_treats_lan_and_wildcard_as_reachable(monkeypatch):
    config = _fresh_config_module(monkeypatch)

    for host in ("0.0.0.0", "::", "192.168.1.5", "10.0.0.12", "mcbe-host"):
        assert config.host_reaches_beyond_loopback(host) is True


def test_session_cookie_secure_defaults_to_false(monkeypatch):
    config = _fresh_config_module(monkeypatch)

    loaded = config.load_config()

    assert loaded.session_cookie_secure is False


def test_session_cookie_secure_env_true(monkeypatch):
    config = _fresh_config_module(monkeypatch)
    monkeypatch.setenv("MCBE_SESSION_COOKIE_SECURE", "true")

    loaded = config.load_config()

    assert loaded.session_cookie_secure is True


def test_secret_key_configured_flag(monkeypatch):
    config = _fresh_config_module(monkeypatch)
    monkeypatch.setenv("MCBE_SECRET_KEY", "stable-secret-for-tests")

    loaded = config.load_config()

    assert loaded.secret_key_configured is True
    assert loaded.secret_key == "stable-secret-for-tests"


def test_auth_password_hash_from_environment_is_trimmed(monkeypatch):
    config = _fresh_config_module(monkeypatch)
    monkeypatch.setenv("MCBE_AUTH_PASSWORD_HASH", "  scrypt:32768:8:1$salt$" + "00" * 64 + "  ")

    loaded = config.load_config()

    assert loaded.auth_password_hash == "scrypt:32768:8:1$salt$" + "00" * 64


def test_startup_security_report_can_be_disabled(monkeypatch):
    config = _fresh_config_module(monkeypatch)
    monkeypatch.setenv("MCBE_STARTUP_SECURITY_REPORT", "false")

    loaded = config.load_config()

    assert loaded.startup_security_report is False


def test_startup_network_check_defaults_to_disabled(monkeypatch):
    config = _fresh_config_module(monkeypatch)

    loaded = config.load_config()

    assert loaded.startup_network_check is False
    assert loaded.startup_network_check_timeout == 1.5


def test_startup_network_check_can_be_enabled_and_timeout_is_bounded(monkeypatch):
    config = _fresh_config_module(monkeypatch)
    monkeypatch.setenv("MCBE_STARTUP_NETWORK_CHECK", "true")
    monkeypatch.setenv("MCBE_STARTUP_NETWORK_CHECK_TIMEOUT", "99")

    loaded = config.load_config()

    assert loaded.startup_network_check is True
    assert loaded.startup_network_check_timeout == 10.0


def test_audit_log_defaults_to_enabled_in_docker_data_root(monkeypatch):
    config = _fresh_config_module(monkeypatch)
    monkeypatch.setenv("MCBE_EDITOR_MODE", "docker")
    monkeypatch.setenv("MCBE_DATA_ROOT", "/data")

    loaded = config.load_config()

    assert loaded.audit_log_enabled is True
    assert _portable_path(loaded.audit_log_path) == "/data/audit/events.jsonl"
    assert loaded.audit_log_max_bytes == 5_000_000


def test_fail_on_insecure_config_can_be_enabled(monkeypatch):
    config = _fresh_config_module(monkeypatch)
    monkeypatch.setenv("MCBE_FAIL_ON_INSECURE_CONFIG", "true")

    loaded = config.load_config()

    assert loaded.fail_on_insecure_config is True


def test_security_boolean_flags_reject_invalid_values(monkeypatch):
    config = _fresh_config_module(monkeypatch)

    for name in ("MCBE_READ_ONLY", "MCBE_AUTH_REQUIRED", "MCBE_FAIL_ON_INSECURE_CONFIG"):
        monkeypatch.setenv(name, "ture")
        try:
            try:
                config.load_config()
            except RuntimeError as exc:
                assert name in str(exc)
                assert "Ungültiger Boolean-Wert" in str(exc)
            else:
                raise AssertionError(f"{name} accepted an invalid boolean value")
        finally:
            monkeypatch.delenv(name, raising=False)


def test_proxy_headers_are_not_trusted_by_default(monkeypatch):
    config = _fresh_config_module(monkeypatch)

    loaded = config.load_config()

    assert loaded.trust_proxy_headers is False


def test_proxy_headers_can_be_trusted_explicitly(monkeypatch):
    config = _fresh_config_module(monkeypatch)
    monkeypatch.setenv("MCBE_TRUST_PROXY_HEADERS", "true")

    loaded = config.load_config()

    assert loaded.trust_proxy_headers is True


def test_presence_conflict_guard_defaults_to_enabled(monkeypatch):
    config = _fresh_config_module(monkeypatch)

    loaded = config.load_config()

    assert loaded.presence_conflict_guard_enabled is True


def test_presence_conflict_guard_can_be_disabled(monkeypatch):
    config = _fresh_config_module(monkeypatch)
    monkeypatch.setenv("MCBE_PRESENCE_CONFLICT_GUARD", "false")

    loaded = config.load_config()

    assert loaded.presence_conflict_guard_enabled is False


def test_setup_path_defaults_under_data_root(monkeypatch):
    config = _fresh_config_module(monkeypatch)
    monkeypatch.setenv("MCBE_EDITOR_MODE", "docker")
    monkeypatch.setenv("MCBE_DATA_ROOT", "/data")

    loaded = config.load_config()

    assert _portable_path(loaded.setup_path) == "/data/setup.json"


def test_setup_path_can_be_overridden(monkeypatch):
    config = _fresh_config_module(monkeypatch)
    monkeypatch.setenv("MCBE_SETUP_PATH", "/custom/setup.json")

    loaded = config.load_config()

    assert _portable_path(loaded.setup_path) == "/custom/setup.json"


def test_local_mode_uses_portable_data_root(monkeypatch):
    config = _fresh_config_module(monkeypatch)
    monkeypatch.setenv("MCBE_EDITOR_MODE", "local")

    loaded = config.load_config()

    assert loaded.data_root.endswith("data")
    assert _portable_path(loaded.settings_path).endswith("data/settings.json")
    assert _portable_path(loaded.backup_root).endswith("data/backups")


def test_ipv6_loopback_origin_uses_url_brackets(monkeypatch):
    config = _fresh_config_module(monkeypatch)
    monkeypatch.setenv("MCBE_EDITOR_HOST", "::1")
    monkeypatch.setenv("MCBE_EDITOR_PORT", "5050")

    loaded = config.load_config()

    assert "http://[::1]:5050" in loaded.allowed_origins
    assert "http://::1:5050" not in loaded.allowed_origins


def test_bracketed_ipv6_loopback_origin_is_not_double_bracketed(monkeypatch):
    config = _fresh_config_module(monkeypatch)
    monkeypatch.setenv("MCBE_EDITOR_HOST", "[::1]")
    monkeypatch.setenv("MCBE_EDITOR_PORT", "5051")

    loaded = config.load_config()

    assert "http://[::1]:5051" in loaded.allowed_origins
    assert "http://[[::1]]:5051" not in loaded.allowed_origins
