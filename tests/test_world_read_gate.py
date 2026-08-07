"""Regression tests for read-vs-write server gates."""

from dataclasses import replace
from unittest.mock import Mock, patch


def _client():
    from main import app

    client = app.test_client()
    client.testing = True
    return client


def test_normal_editor_allows_read_gate_while_server_online():
    from mcbe_editor.server_status import write_gate

    import main

    config = replace(
        main.APP_CONFIG,
        read_only=False,
        require_server_offline=True,
        allow_edit_while_online=False,
    )
    gate = write_gate(config, status={"status": "online"})
    assert gate["allowed"] is False
    assert gate["read_allowed"] is True
    assert gate["read_only"] is False
    assert "Server läuft noch" in gate["reason"]


def test_normal_editor_allows_read_gate_when_server_status_unknown():
    from mcbe_editor.server_status import write_gate

    import main

    config = replace(
        main.APP_CONFIG,
        read_only=False,
        require_server_offline=True,
        allow_edit_while_online=False,
    )
    gate = write_gate(config, status={"status": "unknown"})
    assert gate["allowed"] is False
    assert gate["read_allowed"] is True
    assert gate["read_only"] is False
    assert "Serverstatus unbekannt" in gate["reason"]


@patch("main.CSRF_TOKEN", "read-token")
def test_normal_read_endpoint_stays_available_with_online_server_gate():
    import main

    gate_payload = {
        "allowed": False,
        "reason": "Server läuft noch. Bitte Server stoppen.",
        "override_active": False,
        "read_allowed": True,
        "read_only": False,
        "server_status": {"status": "online"},
        "config": {"read_only": False, "require_server_offline": True},
    }
    with (
        patch("main.write_gate", Mock(return_value=gate_payload)) as write_gate_mock,
        patch.object(
            main.editor_service,
            "list_players",
            Mock(return_value={"success": True, "players": [], "world_name": "w", "capabilities": {}, "compatibility": {}}),
        ) as list_players,
    ):
        resp = _client().post(
            "/api/players",
            json={"world_path": "/worlds/test"},
            headers={"X-CSRF-Token": "read-token"},
        )

    assert resp.status_code == 200
    assert resp.get_json()["success"] is True
    write_gate_mock.assert_called()
    list_players.assert_called_once()


@patch("main.CSRF_TOKEN", "read-token")
def test_normal_write_endpoint_still_blocks_with_online_server_gate():
    import main

    gate_payload = {
        "allowed": False,
        "reason": "Server läuft noch. Bitte Server stoppen.",
        "override_active": False,
        "read_allowed": True,
        "read_only": False,
        "server_status": {"status": "online"},
        "config": {"read_only": False, "require_server_offline": True},
    }
    with (
        patch("main.write_gate", Mock(return_value=gate_payload)) as write_gate_mock,
        patch.object(main.editor_service, "save_player", Mock()) as save_player,
    ):
        resp = _client().post(
            "/api/player/save",
            json={"world_path": "/worlds/test", "player_key": "local_player"},
            headers={"X-CSRF-Token": "read-token"},
        )

    assert resp.status_code == 409
    data = resp.get_json()
    assert data["success"] is False
    assert "Server läuft noch" in data["error"]
    write_gate_mock.assert_called()
    save_player.assert_not_called()
