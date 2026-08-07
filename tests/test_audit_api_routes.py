import json
from types import SimpleNamespace
from unittest.mock import Mock

from mcbe_editor import audit_api_routes


def _jsonify(payload):
    return ("json", payload)


def _response(body, mimetype="", headers=None):
    return ("response", body, mimetype, headers or {})


def _api_error(message, status=400, **_kwargs):
    return ("error", str(message), status)


def _deps(**overrides):
    audit_log = overrides.pop(
        "audit_log",
        SimpleNamespace(
            enabled=True,
            status=Mock(return_value={"enabled": True}),
            tail=Mock(return_value=[{"id": 1}]),
            read_events=Mock(
                return_value={
                    "events": [{"id": 1}],
                    "available_events": 1,
                    "truncated": False,
                    "invalid_lines": 0,
                    "read_errors": 0,
                    "files_read": 1,
                }
            ),
        ),
    )
    deps = audit_api_routes.AuditRouteDeps(
        audit_log=audit_log,
        jsonify=_jsonify,
        response=_response,
        api_error=_api_error,
        auth_enabled=overrides.pop("auth_enabled", Mock(return_value=False)),
        is_authenticated=overrides.pop("is_authenticated", Mock(return_value=False)),
        auth_required_response=overrides.pop("auth_required_response", Mock(return_value=("auth", 401))),
        wide_reachable=overrides.pop("wide_reachable", Mock(return_value=False)),
    )
    assert not overrides
    return deps


def test_audit_events_block_wide_reachable_without_auth():
    audit_log = SimpleNamespace(enabled=True, status=Mock(), tail=Mock())
    deps = _deps(audit_log=audit_log, wide_reachable=Mock(return_value=True))

    result = audit_api_routes.audit_events({"limit": "10"}, deps)

    assert result == ("error", "Audit-Ereignisse sind im Docker/LAN-Modus nur mit aktivierter Auth abrufbar.", 403)
    audit_log.tail.assert_not_called()


def test_audit_events_requires_login_when_auth_enabled():
    audit_log = SimpleNamespace(enabled=True, status=Mock(), tail=Mock())
    auth_required_response = Mock(return_value=("auth-required", 401))
    deps = _deps(
        audit_log=audit_log,
        auth_enabled=Mock(return_value=True),
        is_authenticated=Mock(return_value=False),
        auth_required_response=auth_required_response,
    )

    result = audit_api_routes.audit_events({}, deps)

    assert result == ("auth-required", 401)
    auth_required_response.assert_called_once()
    audit_log.tail.assert_not_called()


def test_audit_export_clamps_limit_and_returns_attachment_json():
    audit_log = SimpleNamespace(
        enabled=True,
        status=Mock(return_value={"enabled": True, "path": r"C:\Users\private\events.jsonl"}),
        tail=Mock(return_value=[{"id": 1}]),
        read_events=Mock(
            return_value={
                "events": [{"id": 1}],
                "available_events": 2,
                "truncated": True,
                "invalid_lines": 0,
                "read_errors": 0,
                "files_read": 2,
            }
        ),
    )
    deps = _deps(audit_log=audit_log)

    result = audit_api_routes.audit_export({"limit": "999999"}, deps)

    assert result[0] == "response"
    payload = json.loads(result[1])
    assert payload["success"] is True
    assert "path" not in payload["audit_log"]
    assert payload["events"] == [{"id": 1}]
    assert payload["export"]["available_events"] == 2
    assert payload["export"]["truncated"] is True
    assert result[2] == "application/json; charset=utf-8"
    assert result[3]["Content-Disposition"] == "attachment; filename=mcbe-audit-events.json"
    audit_log.read_events.assert_called_once_with(5000, max_limit=5000)


def test_audit_events_uses_default_limit_for_invalid_query_value():
    audit_log = SimpleNamespace(enabled=False, status=Mock(return_value={"enabled": False}), tail=Mock(return_value=[]))
    deps = _deps(audit_log=audit_log)

    result = audit_api_routes.audit_events({"limit": "not-a-number"}, deps)

    assert result == ("json", {"success": True, "audit_log": {"enabled": False}, "events": []})
    audit_log.tail.assert_called_once_with(100)
