from dataclasses import replace
from unittest.mock import Mock, patch


ALLOWED_GATE = {
    "allowed": True,
    "read_allowed": True,
    "reason": "ok",
    "server_status": {"status": "offline"},
    "config": {"read_only": False},
}


def _client():
    from main import app

    client = app.test_client()
    client.testing = True
    return client


@patch("main.CSRF_TOKEN", "import-token")
def test_import_in_docker_rejects_export_zip_outside_world_export_dir(tmp_path):
    import main

    world_path = tmp_path / "world"
    (world_path / "db").mkdir(parents=True)
    outside_export = tmp_path / "outside.mcbe-player.zip"

    previous_config = main.APP_CONFIG
    main.APP_CONFIG = replace(
        main.APP_CONFIG,
        mode="docker",
        worlds_root=str(tmp_path),
        read_only=False,
        require_server_offline=False,
    )
    try:
        with (
            patch("main.first_run_setup_required", Mock(return_value=False)),
            patch("main.write_gate", Mock(return_value=ALLOWED_GATE)),
            patch.object(main.editor_service, "import_player", Mock()) as import_player,
        ):
            resp = _client().post(
                "/api/player/import",
                json={
                    "export_zip": str(outside_export),
                    "world_path": str(world_path),
                    "target_player_key": "cGxheWVyXzE",
                    "confirm_overwrite": True,
                    "import_token": {"version": 1},
                },
                headers={"X-CSRF-Token": "import-token"},
            )
    finally:
        main.APP_CONFIG = previous_config

    assert resp.status_code == 400
    assert "Exportordner" in resp.get_json()["error"]
    import_player.assert_not_called()


@patch("main.CSRF_TOKEN", "import-token")
def test_import_in_docker_allows_export_zip_inside_world_export_dir(tmp_path):
    import main

    world_path = tmp_path / "world"
    (world_path / "db").mkdir(parents=True)
    allowed_export_dir = tmp_path / "player_exports"
    allowed_export_dir.mkdir()
    allowed_export = allowed_export_dir / "player.mcbe-player.zip"

    previous_config = main.APP_CONFIG
    main.APP_CONFIG = replace(
        main.APP_CONFIG,
        mode="docker",
        worlds_root=str(tmp_path),
        read_only=False,
        require_server_offline=False,
    )
    try:
        with (
            patch("main.first_run_setup_required", Mock(return_value=False)),
            patch("main.write_gate", Mock(return_value=ALLOWED_GATE)),
            patch.object(
                main.editor_service,
                "import_player",
                Mock(return_value={"success": True}),
            ) as import_player,
        ):
            resp = _client().post(
                "/api/player/import",
                json={
                    "export_zip": str(allowed_export),
                    "world_path": str(world_path),
                    "target_player_key": "cGxheWVyXzE",
                    "confirm_overwrite": True,
                    "import_token": {"version": 1},
                    "base_revision": "a" * 64,
                },
                headers={"X-CSRF-Token": "import-token"},
            )
    finally:
        main.APP_CONFIG = previous_config

    assert resp.status_code == 200
    assert resp.get_json()["success"] is True
    import_player.assert_called_once()
    assert import_player.call_args.args[0] == str(allowed_export.resolve())
    assert import_player.call_args.kwargs["base_revision"] == "a" * 64


@patch("main.CSRF_TOKEN", "import-token")
def test_import_without_preview_token_requires_refresh(tmp_path):
    import main

    world_path = tmp_path / "world"
    (world_path / "db").mkdir(parents=True)
    with (
        patch("main.first_run_setup_required", Mock(return_value=False)),
        patch("main.write_gate", Mock(return_value=ALLOWED_GATE)),
        patch.object(main.editor_service, "import_player", Mock()) as import_player,
    ):
        resp = _client().post(
            "/api/player/import",
            json={
                "export_zip": str(tmp_path / "player.mcbe-player.zip"),
                "world_path": str(world_path),
                "target_player_key": "cGxheWVyXzE",
                "confirm_overwrite": True,
            },
            headers={"X-CSRF-Token": "import-token"},
        )

    assert resp.status_code == 409
    assert resp.get_json()["preview_stale"] is True
    import_player.assert_not_called()


@patch("main.CSRF_TOKEN", "import-token")
def test_import_onto_existing_player_requires_loaded_target_revision(tmp_path):
    import main

    world_path = tmp_path / "world"
    (world_path / "db").mkdir(parents=True)
    with (
        patch("main.first_run_setup_required", Mock(return_value=False)),
        patch("main.write_gate", Mock(return_value=ALLOWED_GATE)),
        patch.object(main.editor_service, "import_player", Mock()) as import_player,
    ):
        resp = _client().post(
            "/api/player/import",
            json={
                "export_zip": str(tmp_path / "player.mcbe-player.zip"),
                "world_path": str(world_path),
                "target_player_key": "cGxheWVyXzE",
                "confirm_overwrite": True,
                "import_token": {"version": 1},
            },
            headers={"X-CSRF-Token": "import-token"},
        )

    data = resp.get_json()
    assert resp.status_code == 409
    assert data["target_revision_stale"] is True
    assert data["preview_stale"] is False
    import_player.assert_not_called()
