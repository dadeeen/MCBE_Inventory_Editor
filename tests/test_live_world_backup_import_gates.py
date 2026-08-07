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


def _client():
    from main import app

    client = app.test_client()
    client.testing = True
    return client


@patch("main.CSRF_TOKEN", "gate-token")
def test_manual_backup_rejects_live_server_before_snapshot():
    import main

    with (
        patch("main.write_gate", return_value=_online_gate()),
        patch.object(main.editor_service, "create_manual_backup", Mock()) as create_manual_backup,
    ):
        resp = _client().post(
            "/api/backup/create",
            json={"world_path": "C:/world"},
            headers={"X-CSRF-Token": "gate-token"},
        )

    assert resp.status_code == 409
    data = resp.get_json()
    assert data["success"] is False
    assert "Server läuft" in data["error"]
    assert data["write_gate"]["server_status"]["status"] == "online"
    create_manual_backup.assert_not_called()


@patch("main.CSRF_TOKEN", "gate-token")
def test_player_import_final_gate_blocks_before_service_call():
    import main

    with (
        patch("main.write_gate", side_effect=[_allowed_gate(), _allowed_gate(), _online_gate()]),
        patch.object(main.editor_service, "import_player", Mock()) as import_player,
        patch("main.audit_event") as audit_event,
    ):
        resp = _client().post(
            "/api/player/import",
            json={
                "world_path": "C:/world",
                "target_player_key": "local_player",
                "export_zip": "C:/export.mcbe-player.zip",
                "confirm_overwrite": True,
                "import_token": {"version": 1},
                "base_revision": "a" * 64,
            },
            headers={"X-CSRF-Token": "gate-token"},
        )

    data = resp.get_json()
    assert resp.status_code == 409
    assert "Import abgelehnt" in data["error"]
    assert "Server läuft" in data["error"]
    assert data["write_gate"]["blocked_operation"] == "final_write_gate"
    assert data["write_gate"]["server_status"]["status"] == "online"
    import_player.assert_not_called()
    audit_event.assert_called_once()
    assert audit_event.call_args.args == ("player.import", "blocked")
    assert audit_event.call_args.kwargs["details"] == {"reason": "final_write_gate"}


@patch("main.CSRF_TOKEN", "gate-token")
def test_player_import_service_gate_callback_blocks_before_backup_and_write():
    import main

    def fake_import_player(*_args, write_gate_check=None, **_kwargs):
        # Mimics the real service contract: the callback runs before backup/write.
        assert main._SAVING_COUNTER == 1
        assert write_gate_check is not None
        try:
            write_gate_check()
        except main.FinalWriteGateBlockedError as exc:
            exc.cleanup_warning = "Import-Snapshot blieb unter C:/import-snapshot.zip zurück."
            exc.source_snapshot_path = "C:/import-snapshot.zip"
            raise
        return {"success": True}

    with (
        patch("main.write_gate", side_effect=[_allowed_gate(), _allowed_gate(), _allowed_gate(), _online_gate()]),
        patch.object(main.editor_service, "import_player", Mock(side_effect=fake_import_player)) as import_player,
    ):
        resp = _client().post(
            "/api/player/import",
            json={
                "world_path": "C:/world",
                "target_player_key": "local_player",
                "export_zip": "C:/export.mcbe-player.zip",
                "confirm_overwrite": True,
                "import_token": {"version": 1},
                "base_revision": "a" * 64,
            },
            headers={"X-CSRF-Token": "gate-token"},
        )

    data = resp.get_json()
    assert resp.status_code == 409
    assert "Import abgelehnt" in data["error"]
    assert "Server läuft" in data["error"]
    assert data["write_gate"]["blocked_operation"] == "final_write_gate"
    assert "C:/import-snapshot.zip" in data["cleanup_warning"]
    assert data["source_snapshot_path"] == "C:/import-snapshot.zip"
    import_player.assert_called_once()
    assert main._SAVING_COUNTER == 0


@patch("main.CSRF_TOKEN", "gate-token")
def test_player_import_rejects_removed_world_copy_request_without_writing():
    import main

    with (
        patch("main.require_world_write_allowed", return_value=None),
        patch("main.require_server_guard_current", return_value=None),
        patch("main.presence_conflict_response", return_value=None),
        patch("mcbe_editor.player_api_routes._validated_player_export_zip_path", return_value="C:/export.mcbe-player.zip"),
        patch.object(main.editor_service, "import_player", Mock()) as import_player,
    ):
        resp = _client().post(
            "/api/player/import",
            json={
                "world_path": "C:/world",
                "target_player_key": "local_player",
                "export_zip": "C:/export.mcbe-player.zip",
                "confirm_overwrite": True,
                "import_into_world_copy": True,
                "import_token": {"version": 1},
            },
            headers={"X-CSRF-Token": "gate-token"},
        )

    assert resp.status_code == 400
    assert "nicht mehr unterstützt" in resp.get_json()["error"]
    import_player.assert_not_called()


@patch("main.CSRF_TOKEN", "gate-token")
def test_player_import_route_reports_successful_record_rollback():
    import main

    from mcbe_editor.service_errors import PlayerImportRolledBackError

    rolled_back = PlayerImportRolledBackError(
        ValueError("Nachvalidierung fehlgeschlagen"),
        backup_file="C:/backups/world_before_import.zip",
    )
    rolled_back.cleanup_warning = "Import-Snapshot blieb unter C:/snapshots/import.zip zurück."
    rolled_back.source_snapshot_path = "C:/snapshots/import.zip"
    with (
        patch("main.require_world_write_allowed", return_value=None),
        patch("main.require_server_guard_current", return_value=None),
        patch("main.presence_conflict_response", return_value=None),
        patch("main.require_final_world_write_allowed", return_value=None),
        patch("mcbe_editor.player_api_routes._validated_player_export_zip_path", return_value="C:/export.mcbe-player.zip"),
        patch.object(main.editor_service, "import_player", side_effect=rolled_back),
    ):
        resp = _client().post(
            "/api/player/import",
            json={
                "world_path": "C:/world",
                "target_player_key": "local_player",
                "export_zip": "C:/export.mcbe-player.zip",
                "confirm_overwrite": True,
                "import_token": {"version": 1},
                "base_revision": "a" * 64,
            },
            headers={"X-CSRF-Token": "gate-token"},
        )

    data = resp.get_json()
    assert resp.status_code == 500
    assert data["code"] == "player_import_rolled_back"
    assert data["rolled_back"] is True
    assert data["write_committed"] is False
    assert data["backup_file"] == "world_before_import.zip"
    assert "C:/snapshots/import.zip" in data["cleanup_warning"]
    assert data["source_snapshot_path"] == "C:/snapshots/import.zip"


@patch("main.CSRF_TOKEN", "gate-token")
def test_player_import_route_reports_failed_record_rollback():
    import main

    from mcbe_editor.service_errors import PlayerImportRecordRollbackError

    rollback_failed = PlayerImportRecordRollbackError(
        ValueError("Nachvalidierung fehlgeschlagen"),
        backup_file="C:/backups/world_before_import.zip",
        rollback_failures=(("Zielzustand konnte nicht zurückgeschrieben werden", OSError("locked")),),
    )
    with (
        patch("main.require_world_write_allowed", return_value=None),
        patch("main.require_server_guard_current", return_value=None),
        patch("main.presence_conflict_response", return_value=None),
        patch("main.require_final_world_write_allowed", return_value=None),
        patch("mcbe_editor.player_api_routes._validated_player_export_zip_path", return_value="C:/export.mcbe-player.zip"),
        patch.object(main.editor_service, "import_player", side_effect=rollback_failed),
    ):
        resp = _client().post(
            "/api/player/import",
            json={
                "world_path": "C:/world",
                "target_player_key": "local_player",
                "export_zip": "C:/export.mcbe-player.zip",
                "confirm_overwrite": True,
                "import_token": {"version": 1},
                "base_revision": "a" * 64,
            },
            headers={"X-CSRF-Token": "gate-token"},
        )

    data = resp.get_json()
    assert resp.status_code == 500
    assert data["code"] == "player_import_rollback_failed"
    assert data["rolled_back"] is False
    assert data["write_committed"] is True
    assert data["backup_file"] == "world_before_import.zip"
    assert "locked" in data["rollback_warning"]


@patch("main.CSRF_TOKEN", "gate-token")
def test_player_state_transfer_preview_is_read_only_and_calls_service():
    import main

    preview_result = {
        "success": True,
        "direction": "local_to_multiplayer",
        "transfer_token": {"version": 1},
    }
    with (
        patch("main.require_world_db_access_allowed", return_value=None),
        patch.object(main.editor_service, "preview_player_state_transfer", return_value=preview_result) as preview,
    ):
        resp = _client().post(
            "/api/player/state_transfer_preview",
            json={
                "world_path": "C:/world",
                "source_player_key": "local",
                "target_player_key": "remote",
            },
            headers={"X-CSRF-Token": "gate-token"},
        )

    assert resp.status_code == 200
    assert resp.get_json()["direction"] == "local_to_multiplayer"
    preview.assert_called_once_with("C:/world", "local", "remote")


@patch("main.CSRF_TOKEN", "gate-token")
def test_player_state_transfer_final_gate_blocks_before_service_call():
    import main

    blocked = main.FinalWriteGateBlockedError("Spielermigration", _online_gate())
    with (
        patch("main.require_world_write_allowed", return_value=None),
        patch("main.require_server_guard_current", return_value=None),
        patch("main.presence_conflict_response", return_value=None),
        patch("main.require_final_world_write_allowed", side_effect=blocked),
        patch.object(main.editor_service, "transfer_player_state", Mock()) as transfer,
        patch("main.audit_event") as audit_event,
    ):
        resp = _client().post(
            "/api/player/state_transfer",
            json={
                "world_path": "C:/world",
                "source_player_key": "local",
                "target_player_key": "remote",
                "confirm_transfer": True,
                "transfer_token": {"version": 1},
            },
            headers={"X-CSRF-Token": "gate-token"},
        )

    assert resp.status_code == 409
    assert resp.get_json()["write_gate"]["blocked_operation"] == "final_write_gate"
    transfer.assert_not_called()
    audit_event.assert_called_once()
    assert audit_event.call_args.args == ("player.state_transfer", "blocked")
    assert audit_event.call_args.kwargs["details"] == {"reason": "final_write_gate"}


@patch("main.CSRF_TOKEN", "gate-token")
def test_player_state_transfer_service_cleanup_warning_reaches_client():
    import main

    blocked = main.FinalWriteGateBlockedError("Spielermigration", _online_gate())
    blocked.cleanup_warning = "Zusätzliches Backup blieb unter C:/backups/transfer.zip zurück."

    with (
        patch("main.require_world_write_allowed", return_value=None),
        patch("main.require_server_guard_current", return_value=None),
        patch("main.presence_conflict_response", return_value=None),
        patch("main.require_final_world_write_allowed", return_value=None),
        patch.object(main.editor_service, "transfer_player_state", side_effect=blocked),
    ):
        resp = _client().post(
            "/api/player/state_transfer",
            json={
                "world_path": "C:/world",
                "source_player_key": "local",
                "target_player_key": "remote",
                "confirm_transfer": True,
                "transfer_token": {"version": 1},
            },
            headers={"X-CSRF-Token": "gate-token"},
        )

    data = resp.get_json()
    assert resp.status_code == 409
    assert "C:/backups/transfer.zip" in data["cleanup_warning"]


@patch("main.CSRF_TOKEN", "gate-token")
def test_player_state_transfer_reports_successful_record_rollback():
    import main

    from mcbe_editor.service_errors import PlayerStateTransferRolledBackError

    rolled_back = PlayerStateTransferRolledBackError(
        ValueError("Nachvalidierung fehlgeschlagen"),
        backup_file="C:/backups/world_before_transfer.zip",
    )
    with (
        patch("main.require_world_write_allowed", return_value=None),
        patch("main.require_server_guard_current", return_value=None),
        patch("main.presence_conflict_response", return_value=None),
        patch("main.require_final_world_write_allowed", return_value=None),
        patch.object(main.editor_service, "transfer_player_state", side_effect=rolled_back),
    ):
        resp = _client().post(
            "/api/player/state_transfer",
            json={
                "world_path": "C:/world",
                "source_player_key": "local",
                "target_player_key": "remote",
                "confirm_transfer": True,
                "transfer_token": {"version": 1},
            },
            headers={"X-CSRF-Token": "gate-token"},
        )

    data = resp.get_json()
    assert resp.status_code == 500
    assert data["code"] == "player_state_transfer_rolled_back"
    assert data["rolled_back"] is True
    assert data["write_committed"] is False
    assert data["backup_file"] == "world_before_transfer.zip"


@patch("main.CSRF_TOKEN", "gate-token")
def test_player_state_transfer_reports_failed_record_rollback():
    import main

    from mcbe_editor.service_errors import PlayerStateTransferRollbackError

    rollback_failed = PlayerStateTransferRollbackError(
        ValueError("Nachvalidierung fehlgeschlagen"),
        backup_file="C:/backups/world_before_transfer.zip",
        rollback_failures=(("Zielzustand konnte nicht zurückgeschrieben werden", OSError("locked")),),
    )

    def fail_during_guarded_transfer(*_args, **_kwargs):
        assert main._SAVING_COUNTER == 1
        raise rollback_failed

    with (
        patch("main.require_world_write_allowed", return_value=None),
        patch("main.require_server_guard_current", return_value=None),
        patch("main.presence_conflict_response", return_value=None),
        patch("main.require_final_world_write_allowed", return_value=None),
        patch.object(main.editor_service, "transfer_player_state", side_effect=fail_during_guarded_transfer),
    ):
        resp = _client().post(
            "/api/player/state_transfer",
            json={
                "world_path": "C:/world",
                "source_player_key": "local",
                "target_player_key": "remote",
                "confirm_transfer": True,
                "transfer_token": {"version": 1},
            },
            headers={"X-CSRF-Token": "gate-token"},
        )

    data = resp.get_json()
    assert resp.status_code == 500
    assert data["code"] == "player_state_transfer_rollback_failed"
    assert data["rolled_back"] is False
    assert data["write_committed"] is True
    assert data["backup_file"] == "world_before_transfer.zip"
    assert "locked" in data["rollback_warning"]
    assert main._SAVING_COUNTER == 0
