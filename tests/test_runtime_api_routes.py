"""Exercise the runtime handlers independently from Flask's transport layer."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from mcbe_editor import runtime_api_routes as routes
from mcbe_editor.api_errors import error_payload


def _error(message, status=400, **kwargs):
    return error_payload(message, **kwargs), status


def _deps(**overrides):
    status = {"status": "offline", "message": "offline", "server_status_revision": 9}
    deps = SimpleNamespace(
        app_config=SimpleNamespace(
            is_docker=False,
            mode="local",
            data_root="private-data",
            world_scan_depth=5,
            world_scan_max_dirs=500,
            backup_root="backups",
            max_backups_per_world=10,
            max_pre_restore_backups_per_world=3,
            server_host="127.0.0.1",
            server_port=19132,
            require_server_offline=True,
            allow_edit_while_online=False,
        ),
        service=SimpleNamespace(
            stored_player_revision=Mock(return_value="revision-2"),
            compatibility_report=Mock(return_value={"success": True}),
        ),
        world_presence=SimpleNamespace(touch=Mock(return_value={"success": True}), leave=Mock(return_value={"success": True})),
        recent_log_handler=SimpleNamespace(tail=Mock(return_value=[{"message": "private diagnostic"}])),
        jsonify=lambda payload: payload,
        api_error=_error,
        log_api_exception=Mock(),
        json_string=lambda data, key: data.get(key, ""),
        json_bool=lambda data, key, default=False: data.get(key, default),
        ensure_valid_world_path=Mock(),
        check_server_status=Mock(return_value=status),
        note_server_status=Mock(return_value={"server_guard_epoch": 4, "server_guard_token": "guard"}),
        write_gate=Mock(return_value={"allowed": True, "reason": "", "server_status": status}),
        auth_enabled=Mock(return_value=False),
        is_authenticated=Mock(return_value=False),
        wide_reachable=Mock(return_value=False),
        require_world_db_access_allowed=Mock(return_value=None),
        note_heartbeat=Mock(),
        write_gate_setup_status=Mock(return_value={"ready": True}),
        worlds_root_status=Mock(return_value={"accessible": True}),
        data_root_snapshot=Mock(return_value={"writable": True}),
        distribution_snapshot=Mock(return_value={"kind": "source"}),
        world_fingerprint=Mock(return_value="world-2"),
    )
    for key, value in overrides.items():
        setattr(deps, key, value)
    return deps


@pytest.mark.parametrize(
    ("docker", "wide", "auth", "authenticated", "status"),
    [
        (False, False, False, False, 200),
        (False, True, False, False, 403),
        (False, True, False, True, 403),
        (True, True, False, False, 403),
        (False, True, True, False, 401),
        (True, True, True, False, 401),
        (False, True, True, True, 200),
        (True, True, True, True, 200),
    ],
)
def test_log_access_uses_effective_reachability_not_only_docker_mode(docker, wide, auth, authenticated, status):
    deps = _deps(
        app_config=SimpleNamespace(is_docker=docker),
        wide_reachable=Mock(return_value=wide),
        auth_enabled=Mock(return_value=auth),
        is_authenticated=Mock(return_value=authenticated),
    )
    result = routes.recent_logs({}, deps)
    if status == 200:
        assert result["logs"] == [{"message": "private diagnostic"}]
        deps.recent_log_handler.tail.assert_called_once()
    else:
        assert result[1] == status
        deps.recent_log_handler.tail.assert_not_called()


@pytest.mark.parametrize(("limit", "expected"), [("12", 12), ("broken", 80), ("9" * 5000, 80)])
def test_log_limit_parser_falls_back_without_crashing(limit, expected):
    deps = _deps()
    assert routes.recent_logs({"limit": limit, "level": "WARNING"}, deps)["success"] is True
    deps.recent_log_handler.tail.assert_called_once_with(expected, min_level="WARNING")


@pytest.mark.parametrize("observation", [7, {"server_guard_epoch": 7, "server_guard_token": "token"}])
def test_server_status_preserves_the_same_guard_observation(observation):
    deps = _deps(note_server_status=Mock(return_value=observation))
    result = routes.server_status(deps)
    assert result["success"] is True
    assert result["server_guard_epoch"] == result["write_gate"]["server_guard_epoch"] == 7
    assert result["server_guard_token"] == ("token" if isinstance(observation, dict) else "")
    assert result["server_status_revision"] == 9
    deps.note_server_status.assert_called_once_with(deps.check_server_status.return_value)
    deps.write_gate.assert_called_once_with(deps.app_config, deps.check_server_status.return_value)


def test_heartbeat_records_receipt():
    deps = _deps()
    assert routes.heartbeat(deps) == {"status": "alive"}
    deps.note_heartbeat.assert_called_once_with()


@pytest.mark.parametrize("baseline", [None, [], ""])
def test_presence_without_valid_player_baseline_never_reads_database(baseline):
    deps = _deps()
    result = routes.world_presence({"world_path": "world", "session_id": "session", "fingerprint_baseline": baseline, "player_key": "player"}, deps)
    assert result["success"] is True
    deps.ensure_valid_world_path.assert_called_once_with("world")
    deps.world_fingerprint.assert_not_called()
    deps.service.stored_player_revision.assert_not_called()


@pytest.mark.parametrize(
    ("baseline", "seen", "blocked", "reads"),
    [("world-2", "world-2", False, False), ("world-1", "world-1", False, False), ("world-1", "world-2", True, False), ("world-1", "world-2", False, True)],
)
def test_presence_only_checks_a_stable_changed_world_after_read_gate(baseline, seen, blocked, reads):
    deps = _deps(require_world_db_access_allowed=Mock(return_value=({"error": "online"}, 409) if blocked else None))
    result = routes.world_presence(
        {"world_path": "world", "session_id": "session", "player_key": "player", "fingerprint_baseline": baseline, "fingerprint_seen": seen}, deps
    )
    assert result["world_fingerprint"] == "world-2"
    assert ("player_revision" in result) is reads
    assert deps.service.stored_player_revision.call_count == int(reads)


@pytest.mark.parametrize("stage", ["fingerprint", "revision"])
def test_presence_tolerates_a_world_changing_during_poll(stage):
    deps = _deps()
    if stage == "fingerprint":
        deps.world_fingerprint.side_effect = OSError("temporarily unavailable")
    else:
        deps.service.stored_player_revision.side_effect = OSError("changed while reading")
    result = routes.world_presence(
        {"world_path": "world", "session_id": "session", "player_key": "player", "fingerprint_baseline": "world-1", "fingerprint_seen": "world-2"}, deps
    )
    assert result["success"] is True
    assert "player_revision" not in result


@pytest.mark.parametrize(("operation", "method"), [(routes.world_presence, "touch"), (routes.world_presence_leave, "leave")])
@pytest.mark.parametrize(("exception", "status"), [(ValueError("invalid session"), 400), (OSError("internal fault"), 500)])
def test_presence_errors_remain_structured(operation, method, exception, status):
    deps = _deps()
    getattr(deps.world_presence, method).side_effect = exception
    payload, actual_status = operation({"world_path": "world", "session_id": "session"}, deps)
    assert actual_status == status
    assert payload["success"] is False
    assert deps.log_api_exception.call_count == int(status == 500)


def test_leave_delegates_session_id():
    deps = _deps()
    assert routes.world_presence_leave({"session_id": "session"}, deps)["success"] is True
    deps.world_presence.leave.assert_called_once_with("session")


@pytest.mark.parametrize("player", [None, "player"])
def test_compatibility_only_reads_player_after_gate(player):
    deps = _deps(require_world_db_access_allowed=Mock(return_value=({"error": "online"}, 409)))
    result = routes.world_compatibility({"world_path": "world", "player_key": player}, deps)
    if player:
        assert result[1] == 409
        deps.service.compatibility_report.assert_not_called()
    else:
        assert result["success"] is True
        deps.require_world_db_access_allowed.assert_not_called()
        deps.service.compatibility_report.assert_called_once_with("world", None)


@pytest.mark.parametrize("read_only", [None, False, True])
def test_diagnostics_preserves_effective_configuration_and_snapshots(read_only):
    deps = _deps()
    if read_only is not None:
        deps.app_config.read_only = read_only
    result = routes.diagnostics_status(deps)
    assert result["success"] is True
    assert result["config"]["read_only"] is bool(read_only)
    assert result["config"]["server_port"] == 19132
    assert result["worlds_root"] == {"accessible": True}
    assert result["write_gate_setup"] == {"ready": True}
    assert result["data_root"] == {"writable": True}
    assert result["distribution"] == {"kind": "source"}
    deps.data_root_snapshot.assert_called_once_with("private-data")
    deps.log_api_exception.assert_not_called()


@pytest.mark.parametrize("stage", ["write_gate_setup_status", "worlds_root_status", "write_gate", "data_root_snapshot", "distribution_snapshot"])
def test_diagnostics_failure_returns_structured_error(stage):
    deps = _deps()
    getattr(deps, stage).side_effect = OSError("unavailable")
    payload, status = routes.diagnostics_status(deps)
    assert status == 500
    assert payload["success"] is False
    deps.log_api_exception.assert_called_once()


@pytest.mark.parametrize(("exception", "status"), [(ValueError("bad world"), 400), (OSError("unavailable"), 500)])
def test_compatibility_service_errors_are_not_reported_as_success(exception, status):
    deps = _deps()
    deps.service.compatibility_report.side_effect = exception
    payload, actual_status = routes.world_compatibility({"world_path": "world"}, deps)
    assert actual_status == status
    assert payload["success"] is False
    assert deps.log_api_exception.call_count == int(status == 500)
