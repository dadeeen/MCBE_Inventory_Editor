from __future__ import annotations

import json
import os
import stat
from dataclasses import replace

import pytest
from werkzeug.security import generate_password_hash

from mcbe_editor.setup_state import FirstRunSetup, is_supported_password_hash


def test_first_run_setup_defaults_to_pending(tmp_path):
    setup = FirstRunSetup(tmp_path / "setup.json")

    summary = setup.summary()

    assert summary.enabled is True
    assert summary.completed is False
    assert summary.mode == "pending"
    assert setup.password_hash() is None
    assert setup.open_acknowledged() is False


def test_first_run_setup_can_store_password_mode(tmp_path):
    path = tmp_path / "setup.json"
    setup = FirstRunSetup(path)
    password_hash = generate_password_hash("correct horse battery staple")

    secret = setup.save_password(username="admin", password_hash=password_hash)

    assert secret
    reloaded = FirstRunSetup(path)
    assert reloaded.completed() is True
    assert reloaded.mode() == "password"
    assert reloaded.username() == "admin"
    assert reloaded.password_hash() == password_hash
    assert reloaded.secret_key() == secret

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["auth_mode"] == "password"
    assert data["password_hash"] == password_hash
    assert "created_at" in data


def test_first_run_setup_uses_owner_only_file_mode_on_posix(tmp_path):
    if os.name == "nt":
        return
    path = tmp_path / "private" / "setup.json"
    setup = FirstRunSetup(path)

    setup.save_password(username="admin", password_hash=generate_password_hash("correct horse battery staple"))

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_first_run_setup_repairs_existing_file_mode_on_posix(tmp_path):
    if os.name == "nt":
        return
    path = tmp_path / "setup.json"
    path.write_text('{"auth_mode":"open","risk_acknowledged":true}', encoding="utf-8")
    path.chmod(0o644)

    setup = FirstRunSetup(path)

    assert setup.completed() is True
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_first_run_setup_can_store_open_acknowledgement(tmp_path):
    path = tmp_path / "setup.json"
    setup = FirstRunSetup(path)

    setup.save_open()

    reloaded = FirstRunSetup(path)
    assert reloaded.completed() is True
    assert reloaded.mode() == "open"
    assert reloaded.open_acknowledged() is True
    assert reloaded.password_hash() is None


def _patch_main_for_bind(monkeypatch, tmp_path, bind_host: str, *, configured_host: str = "127.0.0.1"):
    import main

    setup = FirstRunSetup(tmp_path / "setup.json")
    config = replace(
        main.APP_CONFIG,
        mode="local",
        host=configured_host,
        data_root=str(tmp_path),
        setup_path=str(tmp_path / "setup.json"),
        auth_required=False,
        auth_password_hash=None,
        auth_password=None,
    )
    monkeypatch.setattr(main, "APP_CONFIG", config)
    monkeypatch.setattr(main, "SETUP_STATE", setup)
    monkeypatch.setattr(main, "RUNTIME_BIND_HOST", bind_host)
    monkeypatch.setattr(main, "RUNTIME_BIND_PORT", 5000)
    return main


def test_first_run_setup_not_required_on_loopback_bind(monkeypatch, tmp_path):
    main = _patch_main_for_bind(monkeypatch, tmp_path, "127.0.0.1")

    assert main.first_run_setup_required() is False
    assert main.auth_enabled() is False


def test_first_run_setup_required_for_explicit_local_lan_bind(monkeypatch, tmp_path):
    main = _patch_main_for_bind(monkeypatch, tmp_path, "192.168.1.5", configured_host="192.168.1.5")

    assert main.first_run_setup_required() is True
    assert main.auth_enabled() is False


def test_first_run_setup_required_for_cli_lan_bind_override(monkeypatch, tmp_path):
    main = _patch_main_for_bind(monkeypatch, tmp_path, "192.168.1.5", configured_host="127.0.0.1")

    assert main.first_run_setup_required() is True


def test_first_run_setup_rejects_incomplete_persisted_modes(tmp_path):
    password_path = tmp_path / "password-setup.json"
    password_path.write_text('{"auth_mode":"password","password_hash":"   "}', encoding="utf-8")
    open_path = tmp_path / "open-setup.json"
    open_path.write_text('{"auth_mode":"open","risk_acknowledged":false}', encoding="utf-8")

    password_setup = FirstRunSetup(password_path)
    assert password_setup.completed() is False
    assert password_setup.password_hash() is None
    assert FirstRunSetup(open_path).completed() is False


def test_first_run_setup_rejects_malformed_password_hash(tmp_path):
    path = tmp_path / "setup.json"
    path.write_text('{"auth_mode":"password","password_hash":"unknown$salt$deadbeef"}', encoding="utf-8")
    setup = FirstRunSetup(path)

    assert setup.completed() is False
    assert setup.password_hash() is None
    with pytest.raises(ValueError, match="Werkzeug-Format"):
        setup.save_password(username="admin", password_hash="unknown$salt$deadbeef")


def test_supported_password_hash_validation_accepts_werkzeug_methods():
    assert is_supported_password_hash(generate_password_hash("password", method="scrypt")) is True
    assert is_supported_password_hash(generate_password_hash("password", method="pbkdf2:sha256:1000")) is True
    assert is_supported_password_hash("pbkdf2:missing:1000$salt$" + "00" * 32) is False
    assert is_supported_password_hash("scrypt:1073741824:8:1$salt$" + "00" * 64) is False
    assert is_supported_password_hash("pbkdf2:sha256:10000001$salt$" + "00" * 32) is False


def test_auth_required_reopens_setup_after_previous_open_mode(monkeypatch, tmp_path):
    main = _patch_main_for_bind(monkeypatch, tmp_path, "192.168.1.5", configured_host="192.168.1.5")
    main.SETUP_STATE.save_open()
    monkeypatch.setattr(main, "APP_CONFIG", replace(main.APP_CONFIG, auth_required=True))

    assert main.auth_enabled() is True
    assert main.SETUP_STATE.completed() is True
    assert main.SETUP_STATE.password_hash() is None
    assert main.first_run_setup_required() is True


def test_open_to_required_auth_transition_remains_startable(monkeypatch, tmp_path):
    main = _patch_main_for_bind(monkeypatch, tmp_path, "192.168.1.5", configured_host="192.168.1.5")
    main.SETUP_STATE.save_open()
    required_config = replace(main.APP_CONFIG, auth_required=True, fail_on_insecure_config=True)

    assert main._setup_storage_can_complete_auth(required_config, main.SETUP_STATE) is True


def test_open_to_required_auth_transition_exposes_setup_route(monkeypatch, tmp_path):
    main = _patch_main_for_bind(monkeypatch, tmp_path, "192.168.1.5", configured_host="192.168.1.5")
    main.SETUP_STATE.save_open()
    monkeypatch.setattr(main, "APP_CONFIG", replace(main.APP_CONFIG, auth_required=True))

    with main.app.test_client() as client:
        setup_response = client.get("/setup")
        index_response = client.get("/", follow_redirects=False)

    assert setup_response.status_code == 200
    # The test client pins the German source locale (see conftest).
    assert b"Passwort" in setup_response.data
    assert index_response.status_code == 302
    assert "/setup" in index_response.headers["Location"]


def test_unwritable_setup_storage_is_not_reported_as_available(monkeypatch, tmp_path):
    import mcbe_editor.setup_state as setup_state_module

    def deny_write(_path, _text):
        raise PermissionError("simulated read-only volume")

    monkeypatch.setattr(setup_state_module, "atomic_write_private_text", deny_write)
    setup = FirstRunSetup(tmp_path / "setup.json")

    assert setup.storage_available is False
    assert setup.storage_error is not None
    assert setup.summary().reason == "setup-storage-unwritable"


def test_auth_setup_gate_rejects_unwritable_persistent_storage(monkeypatch, tmp_path):
    import main
    import mcbe_editor.setup_state as setup_state_module

    def deny_write(_path, _text):
        raise PermissionError("simulated read-only volume")

    monkeypatch.setattr(setup_state_module, "atomic_write_private_text", deny_write)
    setup = FirstRunSetup(tmp_path / "setup.json")
    required_config = replace(main.APP_CONFIG, auth_required=True, auth_password=None, auth_password_hash=None)

    assert main._setup_storage_can_complete_auth(required_config, setup) is False


def test_wide_bind_does_not_fall_back_to_unacknowledged_open_mode_when_setup_storage_is_unwritable(monkeypatch, tmp_path):
    import main
    import mcbe_editor.setup_state as setup_state_module

    def deny_write(_path, _text):
        raise PermissionError("simulated read-only volume")

    monkeypatch.setattr(setup_state_module, "atomic_write_private_text", deny_write)
    setup = FirstRunSetup(tmp_path / "setup.json")

    assert (
        main._wide_bind_has_unresolved_unwritable_setup(
            wide_bind=True,
            env_auth_available=False,
            persistent_auth_available=False,
            setup_state=setup,
        )
        is True
    )


def test_wide_bind_allows_existing_acknowledged_open_mode_on_unwritable_storage(monkeypatch, tmp_path):
    import main
    import mcbe_editor.setup_state as setup_state_module

    setup_path = tmp_path / "setup.json"
    setup_path.write_text('{"auth_mode":"open","risk_acknowledged":true}', encoding="utf-8")
    setup = FirstRunSetup(setup_path)

    def deny_write(_path, _text):
        raise PermissionError("simulated read-only volume")

    monkeypatch.setattr(setup_state_module, "atomic_write_private_text", deny_write)
    setup.reload()

    assert setup.storage_available is False
    assert setup.open_acknowledged() is True
    assert (
        main._wide_bind_has_unresolved_unwritable_setup(
            wide_bind=True,
            env_auth_available=False,
            persistent_auth_available=False,
            setup_state=setup,
        )
        is False
    )


@pytest.mark.parametrize(
    "payload",
    [
        b"\xff\xfe",
        ('{"x":' * 10000 + "0" + "}" * 10000).encode("utf-8"),
    ],
    ids=["invalid-utf8", "deep-json"],
)
def test_first_run_setup_tolerates_unreadable_json_payloads(tmp_path, payload):
    path = tmp_path / "setup.json"
    path.write_bytes(payload)

    setup = FirstRunSetup(path)

    assert setup.completed() is False
    assert setup.mode() == "pending"
    assert setup.storage_available is True
