"""Request-input boundaries reject malformed values without bypassing guards."""

import logging
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from mcbe_editor.api_errors import error_payload


@pytest.fixture
def application(monkeypatch):
    import main

    monkeypatch.setattr(main, "url_for", lambda _endpoint: "/")
    return main


@pytest.mark.parametrize("level", ["BASIC_FORMAT", "_STYLES", "_HANDLERS", "not-a-level"])
def test_recent_logs_unknown_levels_fall_back_to_info(application, level):
    handler = application.RecentLogHandler()
    for name in ("DEBUG", "INFO", "WARNING", "ERROR"):
        handler.emit(logging.LogRecord("test", getattr(logging, name), __file__, 1, name, (), None))

    assert [entry["message"] for entry in handler.tail(min_level=level)] == ["INFO", "WARNING", "ERROR"]


@pytest.mark.parametrize(
    ("level", "expected"),
    [("error", ["ERROR"]), ("WARN", ["WARNING", "ERROR"]), ("DEBUG", ["DEBUG", "INFO", "WARNING", "ERROR"])],
)
def test_recent_logs_keep_valid_level_filters(application, level, expected):
    handler = application.RecentLogHandler()
    for name in ("DEBUG", "INFO", "WARNING", "ERROR"):
        handler.emit(logging.LogRecord("test", getattr(logging, name), __file__, 1, name, (), None))

    assert [entry["message"] for entry in handler.tail(min_level=level)] == expected


@pytest.mark.parametrize(
    "target",
    ["/\t/[invalid", "/\r/[invalid", "/versions\nother", "/versions\r\nX-Test: injected", "/ver\x00sions", "/ver\x1fsions", "/ver\x7fsions"],
)
def test_login_redirect_rejects_control_characters(application, target):
    assert application._safe_redirect_target(target) == "/"


@pytest.mark.parametrize("target", ["/versions?from=login", "/?name=München", "/?name=two%20words"])
def test_login_redirect_keeps_ordinary_local_targets(application, target):
    assert application._safe_redirect_target(target) == target


@pytest.fixture
def guarded_application(application, monkeypatch):
    current = {"server_guard_epoch": 4, "server_guard_token": "valid-current-token"}
    gate = {"allowed": True, "read_allowed": True, "server_status": {"status": "offline"}, **current}
    monkeypatch.setattr(application, "APP_CONFIG", SimpleNamespace(require_server_offline=True))
    monkeypatch.setattr(application, "server_guard_snapshot", Mock(return_value=current))
    monkeypatch.setattr(application, "_request_write_gate", Mock(return_value=gate))
    monkeypatch.setattr(application, "with_server_guard_epoch", lambda value: value)
    monkeypatch.setattr(application, "_localized_public_write_gate", lambda value: value)
    monkeypatch.setattr(application, "has_request_context", lambda: True)
    monkeypatch.setattr(application, "g", SimpleNamespace())
    monkeypatch.setattr(application, "_remote_addr", lambda: "127.0.0.1")

    def api_error(message, status=400, *, extra=None, **kwargs):
        return {**error_payload(message, **kwargs), **(extra or {})}, status

    monkeypatch.setattr(application, "api_error", api_error)
    return application


@pytest.mark.parametrize("token", ["ä", "😀", "\ud800", "old-token", ""])
def test_server_guard_invalid_tokens_are_conflicts_not_internal_errors(guarded_application, token):
    app = guarded_application
    payload, status = app.require_server_guard_current({"server_guard_epoch": 4, "server_guard_token": token})

    assert status == 409
    assert payload["code"] == "server_guard_stale"
    assert payload["write_gate"]["allowed"] is False
    assert payload["write_gate"]["server_guard_token"] == "valid-current-token"
    assert not hasattr(app.g, "expected_server_guard_token")


@pytest.mark.parametrize("token", [[], {}, 1])
def test_server_guard_wrong_token_types_are_bad_requests(guarded_application, token):
    app = guarded_application
    payload, status = app.require_server_guard_current({"server_guard_epoch": 4, "server_guard_token": token})

    assert status == 400
    assert payload["success"] is False
    assert not hasattr(app.g, "expected_server_guard_token")


def test_server_guard_valid_token_is_retained_for_the_final_write_check(guarded_application):
    app = guarded_application
    assert app.require_server_guard_current({"server_guard_epoch": 4, "server_guard_token": "valid-current-token"}) is None
    assert app.g.expected_server_guard_token == "valid-current-token"


def test_disabled_server_guard_does_not_inspect_client_token(guarded_application):
    app = guarded_application
    app.APP_CONFIG.require_server_offline = False
    assert app.require_server_guard_current({"server_guard_token": "ä"}) is None
    app.server_guard_snapshot.assert_not_called()
