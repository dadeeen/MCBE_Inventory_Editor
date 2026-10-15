"""Scan route contracts: payloads, validation, audit ordering, and failures."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from mcbe_editor import scan_api_routes as routes
from mcbe_editor.api_errors import error_payload


@pytest.fixture
def deps():
    return SimpleNamespace(
        settings_path="settings.json",
        data_root="private-data",
        jsonify=lambda payload: payload,
        api_error=lambda message, status=400: (error_payload(message), status),
        log_api_exception=Mock(),
        json_string=lambda data, key: data.get(key, ""),
        json_bool=lambda data, key, default: data.get(key, default),
        audit_event=Mock(),
    )


def test_scan_retains_worlds_and_traversal_metadata(monkeypatch, deps):
    result = {"worlds": [{"name": "World"}], "truncated": True, "visited_dirs": 500}
    scan = Mock(return_value=result)
    monkeypatch.setattr(routes, "scan_minecraft_worlds_with_meta", scan)
    assert routes.scan_worlds(deps) == {"success": True, **result}
    scan.assert_called_once_with()


def test_scan_failure_is_not_an_empty_successful_list(monkeypatch, deps):
    monkeypatch.setattr(routes, "scan_minecraft_worlds_with_meta", Mock(side_effect=OSError("no access")))
    payload, status = routes.scan_worlds(deps)
    assert status == 500
    assert payload["success"] is False
    deps.log_api_exception.assert_called_once()


@pytest.mark.parametrize("default", [None, Path("default-worlds")])
def test_scan_path_listing_keeps_disabled_roots_but_excludes_them_from_active_paths(monkeypatch, deps, default):
    roots = [
        {"path": "default", "removable": False},
        {"path": "extra", "enabled": True, "removable": True},
        {"path": "disabled", "enabled": False, "removable": True},
    ]
    get_roots = Mock(return_value=roots)
    monkeypatch.setattr(routes, "get_configured_scan_roots", get_roots)
    monkeypatch.setattr(routes, "get_minecraft_saves_dir", Mock(return_value=default))
    monkeypatch.setattr(routes, "get_minecraft_saves_candidates", Mock(return_value=[Path(str(index)) for index in range(9)]))
    result = routes.get_scan_paths(deps)
    assert result["scan_roots"] == roots
    assert result["all_paths"] == ["default", "extra"]
    assert result["extra_paths"] == ["extra", "disabled"]
    assert result["default_path"] == (str(default) if default is not None else None)
    assert result["default_candidates"] == [str(index) for index in range(6)]
    assert result["settings_path"] == "settings.json"
    assert result["data_root"] == "private-data"
    get_roots.assert_called_once_with(include_disabled=True)


OPERATIONS = [
    (routes.add_scan_path_route, "add_scan_path", "scan_path.add"),
    (routes.remove_scan_path_route, "remove_scan_path", "scan_path.remove"),
    (routes.set_scan_path_enabled_route, "set_scan_path_enabled", "scan_path.disable"),
]


@pytest.mark.parametrize(("handler", "operation", "action"), OPERATIONS)
def test_mutation_audits_only_after_service_success(monkeypatch, deps, handler, operation, action):
    def change(*args):
        deps.audit_event.assert_not_called()

    change_mock = Mock(side_effect=change)
    monkeypatch.setattr(routes, operation, change_mock)
    result = handler({"path": "Worlds/München", "enabled": False}, deps)
    assert result == {"success": True}
    expected_args = ("Worlds/München", False) if operation == "set_scan_path_enabled" else ("Worlds/München",)
    change_mock.assert_called_once_with(*expected_args)
    deps.audit_event.assert_called_once_with(action, "success", details={"path": "Worlds/München"})


@pytest.mark.parametrize(("handler", "operation", "action"), OPERATIONS)
def test_empty_scan_path_does_not_call_service_or_audit(monkeypatch, deps, handler, operation, action):
    change = Mock()
    monkeypatch.setattr(routes, operation, change)
    payload, status = handler({}, deps)
    assert status == 400
    assert payload["success"] is False
    change.assert_not_called()
    deps.audit_event.assert_not_called()


@pytest.mark.parametrize(("handler", "operation", "action"), OPERATIONS)
@pytest.mark.parametrize(("exception", "status"), [(ValueError("invalid path"), 400), (OSError("cannot write"), 500)])
def test_service_failure_cannot_emit_successful_audit(monkeypatch, deps, handler, operation, action, exception, status):
    monkeypatch.setattr(routes, operation, Mock(side_effect=exception))
    payload, actual_status = handler({"path": "worlds", "enabled": False}, deps)
    assert actual_status == status
    assert payload["success"] is False
    deps.audit_event.assert_not_called()
    assert deps.log_api_exception.call_count == int(status == 500)


def test_enable_defaults_to_true_and_uses_matching_audit_action(monkeypatch, deps):
    change = Mock()
    monkeypatch.setattr(routes, "set_scan_path_enabled", change)
    assert routes.set_scan_path_enabled_route({"path": "worlds"}, deps) == {"success": True}
    change.assert_called_once_with("worlds", True)
    deps.audit_event.assert_called_once_with("scan_path.enable", "success", details={"path": "worlds"})


def test_invalid_enabled_value_stops_before_mutation(monkeypatch, deps):
    change = Mock()
    monkeypatch.setattr(routes, "set_scan_path_enabled", change)
    deps.json_bool = Mock(side_effect=ValueError("invalid boolean"))
    payload, status = routes.set_scan_path_enabled_route({"path": "worlds", "enabled": []}, deps)
    assert status == 400
    assert payload["success"] is False
    change.assert_not_called()
    deps.audit_event.assert_not_called()
