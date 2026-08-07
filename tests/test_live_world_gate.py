from dataclasses import replace
from unittest.mock import Mock, patch


def _online_gate():
    return {
        "allowed": False,
        "read_allowed": True,
        "reason": "Server läuft noch. Bitte Server stoppen.",
        "server_status": {"status": "online"},
        "config": {"require_server_offline": True, "allow_edit_while_online": False},
    }


def _allowed_gate():
    return {
        "allowed": True,
        "read_allowed": True,
        "reason": "Bearbeitung erlaubt.",
        "server_status": {"status": "offline"},
        "config": {"require_server_offline": True, "allow_edit_while_online": False},
    }


def _unknown_gate():
    return {
        "allowed": False,
        "read_allowed": True,
        "requires_unknown_server_confirmation": True,
        "reason": "Serverstatus unbekannt. Schreibaktion aus Sicherheitsgründen blockiert.",
        "server_status": {"status": "unknown"},
        "config": {"require_server_offline": True, "allow_edit_while_online": False},
    }


def _client():
    from main import app

    client = app.test_client()
    client.testing = True
    return client


@patch("main.CSRF_TOKEN", "gate-token")
def test_players_route_allows_readonly_leveldb_access_when_server_online():
    import main

    with (
        patch("main.write_gate", return_value=_online_gate()),
        patch.object(
            main.editor_service,
            "list_players",
            Mock(return_value={"success": True, "players": [], "world_name": "w", "capabilities": {}, "compatibility": {}}),
        ) as list_players,
    ):
        resp = _client().post("/api/players", json={"world_path": "C:/world"}, headers={"X-CSRF-Token": "gate-token"})

    assert resp.status_code == 200
    assert resp.get_json()["success"] is True
    list_players.assert_called_once()


@patch("main.CSRF_TOKEN", "gate-token")
def test_player_load_route_allows_readonly_leveldb_access_when_server_online():
    import main

    with (
        patch("main.write_gate", return_value=_online_gate()),
        patch.object(
            main.editor_service,
            "load_player",
            Mock(return_value={"success": True, "player_revision": "r"}),
        ) as load_player,
    ):
        resp = _client().post(
            "/api/player/load",
            json={"world_path": "C:/world", "player_key": "local_player"},
            headers={"X-CSRF-Token": "gate-token"},
        )

    assert resp.status_code == 200
    assert resp.get_json()["success"] is True
    load_player.assert_called_once()


@patch("main.CSRF_TOKEN", "gate-token")
def test_player_loaded_while_server_online_is_immediately_stale():
    import main

    previous_epoch = main._SERVER_ONLINE_EPOCH
    main._SERVER_ONLINE_EPOCH = 0
    try:
        with (
            patch("main.write_gate", return_value=_online_gate()),
            patch.object(
                main.editor_service,
                "load_player",
                Mock(return_value={"success": True, "player_revision": "r"}),
            ),
        ):
            resp = _client().post(
                "/api/player/load",
                json={"world_path": "C:/world", "player_key": "local_player"},
                headers={"X-CSRF-Token": "gate-token"},
            )
    finally:
        main._SERVER_ONLINE_EPOCH = previous_epoch

    data = resp.get_json()
    assert resp.status_code == 200
    assert data["server_guard_epoch"] == 1
    assert data["player_server_guard_epoch"] == 0
    assert data["server_guard_token"]
    assert data["player_server_guard_token"]
    assert data["server_guard_token"] != data["player_server_guard_token"]
    assert data["server_guard_stale"] is True
    assert data["server_status"]["status"] == "online"
    assert "online" in data["server_guard_stale_reason"]


@patch("main.CSRF_TOKEN", "gate-token")
def test_player_save_rejects_stale_server_guard_token():
    import main

    previous_epoch = main._SERVER_ONLINE_EPOCH
    previous_config = main.APP_CONFIG
    main._SERVER_ONLINE_EPOCH = 2
    main.APP_CONFIG = replace(main.APP_CONFIG, require_server_offline=True, allow_edit_while_online=False)
    try:
        with patch("main.write_gate", return_value=_allowed_gate()), patch.object(main.editor_service, "save_player", Mock()) as save_player:
            resp = _client().post(
                "/api/player/save",
                json={
                    "world_path": "C:/world",
                    "player_key": "local_player",
                    "server_guard_epoch": 1,
                    "server_guard_token": "stale-token",
                },
                headers={"X-CSRF-Token": "gate-token"},
            )
    finally:
        main._SERVER_ONLINE_EPOCH = previous_epoch
        main.APP_CONFIG = previous_config

    assert resp.status_code == 409
    data = resp.get_json()
    assert data["success"] is False
    assert data["server_guard"]["blocked_operation"] == "server_guard"
    assert "neu laden" in data["error"]
    save_player.assert_not_called()


@patch("main.CSRF_TOKEN", "gate-token")
def test_deprecated_online_override_does_not_bypass_server_guard_token():
    import main

    previous_epoch = main._SERVER_ONLINE_EPOCH
    previous_config = main.APP_CONFIG
    main._SERVER_ONLINE_EPOCH = 2
    main.APP_CONFIG = replace(main.APP_CONFIG, require_server_offline=True, allow_edit_while_online=True)
    try:
        with patch("main.write_gate", return_value=_allowed_gate()), patch.object(main.editor_service, "save_player", Mock()) as save_player:
            resp = _client().post(
                "/api/player/save",
                json={
                    "world_path": "C:/world",
                    "player_key": "local_player",
                    "server_guard_epoch": 1,
                    "server_guard_token": "stale-token",
                },
                headers={"X-CSRF-Token": "gate-token"},
            )
    finally:
        main._SERVER_ONLINE_EPOCH = previous_epoch
        main.APP_CONFIG = previous_config

    assert resp.status_code == 409
    data = resp.get_json()
    assert data["success"] is False
    assert data["server_guard"]["blocked_operation"] == "server_guard"
    save_player.assert_not_called()


@patch("main.CSRF_TOKEN", "gate-token")
def test_player_save_rechecks_write_gate_before_service_call():
    import main

    previous_epoch = main._SERVER_ONLINE_EPOCH
    previous_config = main.APP_CONFIG
    main._SERVER_ONLINE_EPOCH = 0
    main.APP_CONFIG = replace(main.APP_CONFIG, require_server_offline=True, allow_edit_while_online=False)
    guard_token = main.server_guard_token()
    try:
        with (
            patch("main.write_gate", side_effect=[_allowed_gate(), _online_gate()]),
            patch.object(main.editor_service, "save_player", Mock()) as save_player,
        ):
            resp = _client().post(
                "/api/player/save",
                json={
                    "world_path": "C:/world",
                    "player_key": "local_player",
                    "server_guard_epoch": 0,
                    "server_guard_token": guard_token,
                },
                headers={"X-CSRF-Token": "gate-token"},
            )
    finally:
        main._SERVER_ONLINE_EPOCH = previous_epoch
        main.APP_CONFIG = previous_config

    assert resp.status_code == 409
    assert "Server läuft" in resp.get_json()["error"]
    save_player.assert_not_called()


@patch("main.CSRF_TOKEN", "gate-token")
def test_player_save_final_service_guard_blocks_write():
    import main

    previous_epoch = main._SERVER_ONLINE_EPOCH
    previous_config = main.APP_CONFIG
    main._SERVER_ONLINE_EPOCH = 0
    main.APP_CONFIG = replace(main.APP_CONFIG, require_server_offline=True, allow_edit_while_online=False)
    guard_token = main.server_guard_token()

    def fake_save_player(*_args, **kwargs):
        try:
            kwargs["pre_write_check"]()
        except main.FinalWriteGateBlockedError as exc:
            exc.cleanup_warning = "Zusätzliches Backup blieb unter C:/backups/pre-write.zip zurück."
            raise

    try:
        with (
            patch("main.write_gate", side_effect=[_allowed_gate(), _allowed_gate(), _online_gate()]),
            patch.object(main.editor_service, "save_player", Mock(side_effect=fake_save_player)) as save_player,
        ):
            resp = _client().post(
                "/api/player/save",
                json={
                    "world_path": "C:/world",
                    "player_key": "local_player",
                    "server_guard_epoch": 0,
                    "server_guard_token": guard_token,
                },
                headers={"X-CSRF-Token": "gate-token"},
            )
    finally:
        main._SERVER_ONLINE_EPOCH = previous_epoch
        main.APP_CONFIG = previous_config

    data = resp.get_json()
    assert resp.status_code == 409
    assert "Speichern abgelehnt" in data["error"]
    assert "Server läuft" in data["error"]
    assert data["write_gate"]["blocked_operation"] == "final_write_gate"
    assert data["write_gate"]["server_status"]["status"] == "online"
    assert "C:/backups/pre-write.zip" in data["cleanup_warning"]
    save_player.assert_called_once()


@patch("main.CSRF_TOKEN", "gate-token")
def test_player_save_final_guard_rejects_token_rotated_after_validation():
    import main

    previous_config = main.APP_CONFIG
    main.APP_CONFIG = replace(main.APP_CONFIG, require_server_offline=True, allow_edit_while_online=False)
    guard_token = main.server_guard_token()

    def fake_save_player(*_args, **kwargs):
        main._SERVER_GUARD_STATE.observe(online=True)
        kwargs["pre_write_check"]()

    try:
        with (
            patch("main.write_gate", side_effect=[_allowed_gate(), _allowed_gate(), _allowed_gate()]),
            patch.object(main.editor_service, "save_player", Mock(side_effect=fake_save_player)) as save_player,
        ):
            resp = _client().post(
                "/api/player/save",
                json={
                    "world_path": "C:/world",
                    "player_key": "local_player",
                    "server_guard_epoch": main.server_online_epoch(),
                    "server_guard_token": guard_token,
                },
                headers={"X-CSRF-Token": "gate-token"},
            )
    finally:
        main.APP_CONFIG = previous_config

    data = resp.get_json()
    assert resp.status_code == 409
    assert "Serverzustand hat sich" in data["error"]
    assert data["write_gate"]["blocked_operation"] == "final_write_gate"
    save_player.assert_called_once()


@patch("main.CSRF_TOKEN", "gate-token")
def test_player_load_returns_current_server_guard_epoch():
    import main

    previous_epoch = main._SERVER_ONLINE_EPOCH
    main._SERVER_ONLINE_EPOCH = 7
    try:
        with (
            patch("main.write_gate", return_value=_allowed_gate()),
            patch.object(main.editor_service, "load_player", Mock(return_value={"success": True, "player_revision": "r"})),
        ):
            resp = _client().post(
                "/api/player/load",
                json={"world_path": "C:/world", "player_key": "local_player"},
                headers={"X-CSRF-Token": "gate-token"},
            )
    finally:
        main._SERVER_ONLINE_EPOCH = previous_epoch

    assert resp.status_code == 200
    assert resp.get_json()["server_guard_epoch"] == 7
    assert resp.get_json()["player_server_guard_epoch"] == 7
    assert resp.get_json()["server_guard_token"] == resp.get_json()["player_server_guard_token"]
    assert resp.get_json()["server_guard_stale"] is False


def test_server_status_online_advances_server_guard_epoch():
    import main

    previous_epoch = main._SERVER_ONLINE_EPOCH
    main._SERVER_ONLINE_EPOCH = 0
    try:
        with patch("main.check_server_status", return_value={"status": "online", "message": "Server erreichbar."}):
            resp = _client().get("/api/server_status")
            second = _client().get("/api/server_status")
    finally:
        main._SERVER_ONLINE_EPOCH = previous_epoch

    assert resp.status_code == 200
    assert resp.get_json()["server_guard_epoch"] == 1
    assert second.get_json()["server_guard_epoch"] == 2


@patch("main.CSRF_TOKEN", "gate-token")
def test_player_export_route_allows_readonly_leveldb_access_when_server_online():
    import main

    with (
        patch("main.write_gate", return_value=_online_gate()),
        patch.object(
            main.editor_service,
            "export_player",
            Mock(return_value={"success": True, "export_path": "C:/exports/player.mcbe-player.zip"}),
        ) as export_player,
    ):
        resp = _client().post(
            "/api/player/export",
            json={"world_path": "C:/world", "player_key": "local_player"},
            headers={"X-CSRF-Token": "gate-token"},
        )

    assert resp.status_code == 200
    export_player.assert_called_once()


@patch("main.CSRF_TOKEN", "gate-token")
def test_world_compatibility_allows_readonly_player_nbt_access_when_server_online():
    import main

    with (
        patch("main.write_gate", return_value=_online_gate()),
        patch.object(main.editor_service, "compatibility_report", Mock(return_value={"success": True})) as report,
    ):
        resp = _client().post(
            "/api/world/compatibility",
            json={"world_path": "C:/world", "player_key": "local_player"},
            headers={"X-CSRF-Token": "gate-token"},
        )
    assert resp.status_code == 200
    report.assert_called_once_with("C:/world", "local_player")


@patch("main.CSRF_TOKEN", "gate-token")
def test_player_import_rechecks_write_gate_before_service_call():
    import main

    with (
        patch("main.write_gate", side_effect=[_allowed_gate(), _online_gate()]),
        patch.object(main.editor_service, "import_player", Mock()) as import_player,
    ):
        resp = _client().post(
            "/api/player/import",
            json={
                "world_path": "C:/world",
                "target_player_key": "local_player",
                "export_zip": "C:/export.zip",
                "confirm_overwrite": True,
            },
            headers={"X-CSRF-Token": "gate-token"},
        )

    assert resp.status_code == 409
    assert "Server läuft" in resp.get_json()["error"]
    import_player.assert_not_called()


@patch("main.CSRF_TOKEN", "gate-token")
def test_restore_rechecks_write_gate_before_service_call():
    import main

    with (
        patch("main.write_gate", side_effect=[_allowed_gate(), _online_gate()]),
        patch.object(main.editor_service, "restore_backup", Mock()) as restore_backup,
    ):
        resp = _client().post(
            "/api/restore_backup",
            json={"world_path": "C:/world", "backup_file": "backup.zip", "backup_token": {}},
            headers={"X-CSRF-Token": "gate-token"},
        )

    assert resp.status_code == 409
    assert "Server läuft" in resp.get_json()["error"]
    restore_backup.assert_not_called()


@patch("main.CSRF_TOKEN", "gate-token")
def test_restore_final_service_guard_blocks_world_replace():
    import main

    def fake_restore_backup(*_args, **kwargs):
        try:
            kwargs["pre_restore_check"]()
        except main.FinalWriteGateBlockedError as exc:
            exc.cleanup_warning = "Restore-Snapshot blieb unter C:/restore-snapshot.zip zurück."
            exc.source_snapshot_path = "C:/restore-snapshot.zip"
            raise

    with (
        patch("main.write_gate", side_effect=[_allowed_gate(), _allowed_gate(), _unknown_gate()]),
        patch.object(main.editor_service, "restore_backup", Mock(side_effect=fake_restore_backup)) as restore_backup,
    ):
        resp = _client().post(
            "/api/restore_backup",
            json={"world_path": "C:/world", "backup_file": "backup.zip", "backup_token": {}},
            headers={"X-CSRF-Token": "gate-token"},
        )

    data = resp.get_json()
    assert resp.status_code == 409
    assert "Restore abgelehnt" in data["error"]
    assert "Serverstatus unbekannt" in data["error"]
    assert data["write_gate"]["blocked_operation"] == "final_write_gate"
    assert data["write_gate"]["server_status"]["status"] == "unknown"
    assert "C:/restore-snapshot.zip" in data["cleanup_warning"]
    assert data["source_snapshot_path"] == "C:/restore-snapshot.zip"
    restore_backup.assert_called_once()
