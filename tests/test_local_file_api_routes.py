from types import SimpleNamespace
from unittest.mock import Mock

from mcbe_editor import local_file_api_routes


class DummyLock:
    def __init__(self, *, acquire_result: bool = True):
        self.acquire_result = acquire_result
        self.acquired = 0
        self.released = 0

    def acquire(self, *, blocking: bool = True) -> bool:
        assert blocking is False
        self.acquired += 1
        return self.acquire_result

    def release(self) -> None:
        self.released += 1


def _jsonify(payload):
    return ("json", payload)


def _api_error(message, status=400, **_kwargs):
    return ("error", str(message), status)


def _json_string(data, key, default=""):
    value = data.get(key, default)
    if value is None:
        return default
    return str(value).strip()


def _deps(tmp_path, **overrides):
    lock = overrides.pop("gui_picker_lock", DummyLock())
    config = SimpleNamespace(
        is_docker=overrides.pop("is_docker", False),
        worlds_root=overrides.pop("worlds_root", str(tmp_path / "worlds")),
    )
    service = SimpleNamespace(
        list_backups=overrides.pop("list_backups", Mock(return_value={"backup_dir": str(tmp_path / "backups")})),
    )
    deps = local_file_api_routes.LocalFileRouteDeps(
        app_config=config,
        service=service,
        jsonify=_jsonify,
        api_error=_api_error,
        log_api_exception=Mock(),
        json_string=_json_string,
        audit_event=Mock(),
        ensure_valid_world_path=overrides.pop("ensure_valid_world_path", Mock(side_effect=ValueError("keine Welt"))),
        get_configured_scan_roots=overrides.pop("get_configured_scan_roots", Mock(return_value=[])),
        get_minecraft_saves_dir=overrides.pop("get_minecraft_saves_dir", Mock(return_value=tmp_path / "saves")),
        player_export_dir_for_world=overrides.pop("player_export_dir_for_world", Mock(return_value=str(tmp_path / "exports"))),
        gui_picker_lock=lock,
        select_folder=overrides.pop("select_folder", Mock(return_value=str(tmp_path / "world"))),
        select_player_export=overrides.pop("select_player_export", Mock(return_value=str(tmp_path / "player.mcbe-player.zip"))),
    )
    assert not overrides
    return deps


def test_open_folder_rejects_unconfigured_local_directory(tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(local_file_api_routes, "_open_folder_in_file_manager", opened.append)
    folder = tmp_path / "unconfigured"
    folder.mkdir()

    result = local_file_api_routes.open_folder({"path": str(folder)}, _deps(tmp_path))

    assert result[0] == "error"
    assert result[2] == 400
    assert "bekannter Suchbereich" in result[1]
    assert opened == []


def test_open_folder_allows_configured_scan_root(tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(local_file_api_routes, "_open_folder_in_file_manager", opened.append)
    folder = tmp_path / "scan-root"
    folder.mkdir()
    deps = _deps(
        tmp_path,
        get_configured_scan_roots=Mock(return_value=[{"path": str(folder), "enabled": True, "removable": True}]),
    )

    result = local_file_api_routes.open_folder({"path": str(folder)}, deps)

    assert result == ("json", {"success": True})
    assert opened == [str(folder.resolve())]
    deps.audit_event.assert_called_once()


def test_pick_folder_blocks_in_docker_without_acquiring_lock(tmp_path):
    lock = DummyLock()
    deps = _deps(tmp_path, is_docker=True, gui_picker_lock=lock)

    result = local_file_api_routes.pick_folder(deps)

    assert result[0] == "error"
    assert result[2] == 400
    assert lock.acquired == 0
    assert lock.released == 0


def test_pick_player_export_uses_world_export_dir_and_releases_lock(tmp_path):
    lock = DummyLock()
    export_dir = tmp_path / "exports"
    select_player_export = Mock(return_value=str(tmp_path / "player.mcbe-player.zip"))
    deps = _deps(
        tmp_path,
        gui_picker_lock=lock,
        ensure_valid_world_path=Mock(return_value=tmp_path / "world"),
        player_export_dir_for_world=Mock(return_value=str(export_dir)),
        select_player_export=select_player_export,
    )

    result = local_file_api_routes.pick_player_export({"world_path": str(tmp_path / "world")}, deps)

    assert result == ("json", {"success": True, "path": str(tmp_path / "player.mcbe-player.zip")})
    assert export_dir.is_dir()
    select_player_export.assert_called_once_with(initial_dir=str(export_dir))
    assert lock.acquired == 1
    assert lock.released == 1


def test_pick_player_export_reports_invalid_world_as_client_error(tmp_path):
    lock = DummyLock()
    deps = _deps(
        tmp_path,
        gui_picker_lock=lock,
        ensure_valid_world_path=Mock(side_effect=ValueError("ungültige Welt")),
    )

    result = local_file_api_routes.pick_player_export({"world_path": str(tmp_path / "missing")}, deps)

    assert result == ("error", "ungültige Welt", 400)
    deps.log_api_exception.assert_not_called()
    assert lock.released == 1
