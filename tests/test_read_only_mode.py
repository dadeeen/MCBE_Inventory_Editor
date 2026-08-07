"""Tests for the MCBE_READ_ONLY viewer deployment mode."""

from dataclasses import replace
from unittest.mock import Mock, patch


def _client():
    from main import app

    client = app.test_client()
    client.testing = True
    return client


def _read_only_config(main):
    return replace(main.APP_CONFIG, read_only=True)


def test_write_gate_blocks_writes_but_allows_reads():
    from mcbe_editor.server_status import write_gate

    import main

    config = replace(_read_only_config(main), require_server_offline=False)
    gate = write_gate(config, status={"status": "offline"})
    assert gate["allowed"] is False
    assert gate["read_only"] is True
    assert gate["read_allowed"] is True
    assert "Read-Only" in gate["reason"]


def test_public_gate_config_exposes_read_only():
    from mcbe_editor.server_status import write_gate

    import main

    for read_only in (False, True):
        config = replace(main.APP_CONFIG, read_only=read_only)
        gate = write_gate(config, status={"status": "offline"})
        assert gate["config"]["read_only"] is read_only


def test_write_gate_read_only_allows_reads_while_server_online():
    from mcbe_editor.server_status import write_gate

    import main

    config = replace(
        _read_only_config(main),
        require_server_offline=True,
        allow_edit_while_online=False,
    )
    gate = write_gate(config, status={"status": "online"})
    assert gate["allowed"] is False
    assert gate["read_allowed"] is True
    assert gate["read_only"] is True
    assert "Schreibaktionen bleiben blockiert" in gate["reason"]


def test_write_gate_read_only_allows_reads_when_server_status_unknown():
    from mcbe_editor.server_status import write_gate

    import main

    config = replace(
        _read_only_config(main),
        require_server_offline=True,
        allow_edit_while_online=False,
    )
    gate = write_gate(config, status={"status": "unknown"})
    assert gate["allowed"] is False
    assert gate["read_allowed"] is True
    assert gate["read_only"] is True


def test_write_gate_read_only_beats_online_override():
    from mcbe_editor.server_status import write_gate

    import main

    config = replace(
        _read_only_config(main),
        require_server_offline=True,
        allow_edit_while_online=True,
    )
    gate = write_gate(config, status={"status": "online"})
    assert gate["allowed"] is False
    assert gate["read_allowed"] is True


@patch("main.CSRF_TOKEN", "ro-token")
def test_mutating_endpoint_returns_403_in_read_only_mode():
    import main

    previous_config = main.APP_CONFIG
    main.APP_CONFIG = _read_only_config(main)
    try:
        with patch.object(main.editor_service, "save_player", Mock()) as save_player:
            resp = _client().post(
                "/api/player/save",
                json={"world_path": "C:/world", "player_key": "local_player"},
                headers={"X-CSRF-Token": "ro-token"},
            )
    finally:
        main.APP_CONFIG = previous_config

    assert resp.status_code == 403
    data = resp.get_json()
    assert data["success"] is False
    assert data["read_only"] is True
    assert "Read-Only" in data["error"]
    save_player.assert_not_called()


@patch("main.CSRF_TOKEN", "ro-token")
def test_restore_endpoint_returns_403_in_read_only_mode():
    import main

    previous_config = main.APP_CONFIG
    main.APP_CONFIG = _read_only_config(main)
    try:
        resp = _client().post(
            "/api/restore_backup",
            json={"world_path": "C:/world", "backup_file": "x.zip"},
            headers={"X-CSRF-Token": "ro-token"},
        )
    finally:
        main.APP_CONFIG = previous_config

    assert resp.status_code == 403
    assert resp.get_json()["read_only"] is True


@patch("main.CSRF_TOKEN", "ro-token")
def test_read_endpoint_stays_available_in_read_only_mode():
    import main

    previous_config = main.APP_CONFIG
    main.APP_CONFIG = replace(_read_only_config(main), require_server_offline=False)
    try:
        with patch.object(
            main.editor_service,
            "list_players",
            Mock(return_value={"success": True, "players": [], "world_name": "w", "capabilities": {}, "compatibility": {}}),
        ) as list_players:
            resp = _client().post(
                "/api/players",
                json={"world_path": "C:/world"},
                headers={"X-CSRF-Token": "ro-token"},
            )
    finally:
        main.APP_CONFIG = previous_config

    assert resp.status_code == 200
    assert resp.get_json()["success"] is True
    list_players.assert_called_once()


@patch("main.CSRF_TOKEN", "ro-token")
def test_read_endpoint_stays_available_in_read_only_mode_with_online_server():
    import main

    previous_config = main.APP_CONFIG
    main.APP_CONFIG = replace(_read_only_config(main), require_server_offline=True, allow_edit_while_online=False)
    viewer_gate = {
        "allowed": False,
        "reason": "Read-Only-Modus aktiv (MCBE_READ_ONLY). Welten können angesehen werden; Schreibaktionen bleiben blockiert.",
        "override_active": False,
        "read_allowed": True,
        "read_only": True,
        "server_status": {"status": "online"},
        "config": {"read_only": True},
    }
    try:
        with (
            patch("main.write_gate", Mock(return_value=viewer_gate)) as write_gate_mock,
            patch.object(
                main.editor_service,
                "list_players",
                Mock(return_value={"success": True, "players": [], "world_name": "w", "capabilities": {}, "compatibility": {}}),
            ) as list_players,
        ):
            resp = _client().post(
                "/api/players",
                json={"world_path": "C:/world"},
                headers={"X-CSRF-Token": "ro-token"},
            )
    finally:
        main.APP_CONFIG = previous_config

    assert resp.status_code == 200
    assert resp.get_json()["success"] is True
    write_gate_mock.assert_called()
    list_players.assert_called_once()


def test_public_app_config_exposes_read_only_flag():
    import main

    previous_config = main.APP_CONFIG
    main.APP_CONFIG = _read_only_config(main)
    try:
        config = main.public_app_config()
    finally:
        main.APP_CONFIG = previous_config

    assert config["read_only"] is True


@patch("main.CSRF_TOKEN", "ro-token")
def test_icon_scan_returns_403_in_read_only_mode():
    import main

    previous_config = main.APP_CONFIG
    main.APP_CONFIG = _read_only_config(main)
    try:
        with patch.object(main.icon_api_routes, "icons_scan", Mock()) as icons_scan:
            resp = _client().post(
                "/api/icons/scan",
                json={"world_path": "C:/world"},
                headers={"X-CSRF-Token": "ro-token"},
            )
    finally:
        main.APP_CONFIG = previous_config

    assert resp.status_code == 403
    data = resp.get_json()
    assert data["read_only"] is True
    assert data["category"] == "app_write"
    icons_scan.assert_not_called()


def test_icon_status_does_not_rebuild_cache_in_read_only_mode():
    import main

    previous_config = main.APP_CONFIG
    previous_index = main.ICON_INDEX
    main.APP_CONFIG = _read_only_config(main)
    main.ICON_INDEX = {"success": True, "enabled": True, "icons": {}, "_by_token": {}, "count": 0}
    try:
        with (
            patch("mcbe_editor.icon_api_routes.load_cached_icon_index", return_value=None),
            patch("mcbe_editor.icon_api_routes.scan_icons", Mock(side_effect=AssertionError("scan must not run"))) as scan_icons,
        ):
            resp = _client().get("/api/icons/status")
    finally:
        main.APP_CONFIG = previous_config
        main.ICON_INDEX = previous_index

    assert resp.status_code == 200
    assert resp.get_json()["count"] == 0
    scan_icons.assert_not_called()


@patch("main.CSRF_TOKEN", "ro-token")
def test_import_preview_stays_available_in_read_only_mode():
    import main

    previous_config = main.APP_CONFIG
    main.APP_CONFIG = _read_only_config(main)
    try:
        with patch.object(main.editor_service, "preview_player_export", Mock(return_value={"success": True, "importable": True})) as preview:
            resp = _client().post(
                "/api/player/import_preview",
                json={"export_zip": "C:/exports/player.mcbe-player.zip", "world_path": "C:/world"},
                headers={"X-CSRF-Token": "ro-token"},
            )
    finally:
        main.APP_CONFIG = previous_config

    assert resp.status_code == 200
    assert resp.get_json()["success"] is True
    preview.assert_called_once_with("C:/exports/player.mcbe-player.zip", "C:/world")


@patch("main.CSRF_TOKEN", "ro-token")
def test_import_preview_in_docker_rejects_paths_outside_world_export_dir(monkeypatch, tmp_path):
    import main

    world_path = tmp_path / "world"
    (world_path / "db").mkdir(parents=True)
    outside_export = tmp_path / "outside.mcbe-player.zip"
    monkeypatch.setenv("MCBE_EDITOR_MODE", "docker")
    monkeypatch.setenv("MCBE_WORLDS_ROOT", str(tmp_path))

    previous_config = main.APP_CONFIG
    main.APP_CONFIG = replace(main.APP_CONFIG, mode="docker", worlds_root=str(tmp_path), read_only=False)
    try:
        with (
            patch("main.first_run_setup_required", Mock(return_value=False)),
            patch.object(main.editor_service, "preview_player_export", Mock()) as preview,
        ):
            resp = _client().post(
                "/api/player/import_preview",
                json={"export_zip": str(outside_export), "world_path": str(world_path)},
                headers={"X-CSRF-Token": "ro-token"},
            )
    finally:
        main.APP_CONFIG = previous_config

    assert resp.status_code == 400
    assert "Exportordner" in resp.get_json()["error"]
    preview.assert_not_called()


@patch("main.CSRF_TOKEN", "ro-token")
def test_read_only_block_emits_audit_event():
    import main

    previous_config = main.APP_CONFIG
    main.APP_CONFIG = _read_only_config(main)
    try:
        with patch("main.audit_event", Mock()) as audit_event:
            resp = _client().post(
                "/api/player/save",
                json={"world_path": "C:/world", "player_key": "local_player"},
                headers={"X-CSRF-Token": "ro-token"},
            )
    finally:
        main.APP_CONFIG = previous_config

    assert resp.status_code == 403
    audit_event.assert_called_once()
    assert audit_event.call_args.args[:2] == ("readonly.blocked", "blocked")


def test_mutating_rate_limited_routes_have_explicit_read_only_policy():
    import main

    missing = []
    for rule in main.app.url_map.iter_rules():
        view = main.app.view_functions[rule.endpoint]
        if getattr(view, "_rate_limit_group", None) == "mutate" and not getattr(view, "_readonly_block_category", None):
            missing.append(rule.rule)

    assert missing == []


# Vollständige Readonly-Policy-Tabelle: Jede Route mit schreibfähiger HTTP-Methode
# (POST/PUT/DELETE/PATCH) muss hier klassifiziert sein. Kategorien:
#   world_write / app_write / local_file -> Route muss @block_when_read_only(<kategorie>) tragen.
#   read       -> liest nur; im Read-Only-Modus erlaubt.
#   read_gated -> liest nur, wird aber im Handler selbst für Read-Only gesperrt
#                 (eigener Test deckt die Sperre ab).
#   presence   -> Kollaborations-Heartbeat/Presence; kein Weltzugriff.
#   auth       -> Setup/Login/Logout; muss auch im Read-Only-Modus funktionieren.
# Ein neuer schreibender Endpunkt ohne Tabelleneintrag lässt diese Tests fehlschlagen.
MUTATING_METHODS = {"POST", "PUT", "DELETE", "PATCH"}
BLOCKED_CATEGORIES = {"world_write", "app_write", "local_file"}
ROUTE_READONLY_POLICY = {
    "/api/backup/create": "app_write",
    "/api/backup/delete": "app_write",
    "/api/backup/restore_preview": "read",
    "/api/backups": "read",
    "/api/heartbeat": "presence",
    "/api/icons/pick_folder": "local_file",
    "/api/icons/pick_pack": "local_file",
    "/api/icons/scan": "app_write",
    "/api/icons/sources/add": "app_write",
    "/api/icons/sources/move": "app_write",
    "/api/icons/sources/remove": "app_write",
    "/api/icons/sources/set_enabled": "app_write",
    "/api/icons/vanilla/update": "app_write",
    "/api/mount/preview": "read",
    "/api/mount/create": "world_write",
    "/api/open_backup_folder": "local_file",
    "/api/open_folder": "local_file",
    "/api/open_player_export_folder": "local_file",
    "/api/pick_folder": "local_file",
    "/api/pick_player_export": "local_file",
    "/api/player/export": "app_write",
    "/api/player/import": "world_write",
    "/api/player/import_preview": "read",
    "/api/player/load": "read",
    "/api/player/save": "world_write",
    "/api/player/state_transfer": "world_write",
    "/api/player/state_transfer_preview": "read",
    "/api/workspace/save": "world_write",
    "/api/players": "read",
    "/api/restore_backup": "world_write",
    "/api/scan_paths/add": "app_write",
    "/api/scan_paths/remove": "app_write",
    "/api/scan_paths/set_enabled": "app_write",
    "/api/update_db": "app_write",
    "/api/world/compatibility": "read",
    "/api/world/presence": "presence",
    "/api/world/presence/leave": "presence",
    "/login": "auth",
    "/logout": "auth",
    "/setup": "auth",
}


def _mutating_rules(main):
    for rule in main.app.url_map.iter_rules():
        if rule.methods & MUTATING_METHODS:
            yield rule


def test_every_mutating_route_is_classified_in_readonly_policy_table():
    import main

    actual = {rule.rule for rule in _mutating_rules(main)}
    unclassified = sorted(actual - set(ROUTE_READONLY_POLICY))
    stale = sorted(set(ROUTE_READONLY_POLICY) - actual)
    assert unclassified == [], f"Neue schreibfähige Routen ohne Readonly-Klassifizierung: {unclassified}"
    assert stale == [], f"Policy-Tabelle enthält nicht mehr existierende Routen: {stale}"


def test_readonly_policy_table_matches_route_decorators():
    import main

    mismatches = []
    for rule in _mutating_rules(main):
        view = main.app.view_functions[rule.endpoint]
        expected = ROUTE_READONLY_POLICY[rule.rule]
        actual = getattr(view, "_readonly_block_category", None)
        if expected in BLOCKED_CATEGORIES:
            if actual != expected:
                mismatches.append(f"{rule.rule}: erwartet block_when_read_only({expected!r}), gefunden {actual!r}")
        elif actual is not None:
            mismatches.append(f"{rule.rule}: als {expected!r} klassifiziert, trägt aber block_when_read_only({actual!r})")

    assert mismatches == []
