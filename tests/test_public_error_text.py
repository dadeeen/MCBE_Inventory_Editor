"""Error answers keep unexpected exception text in the server log."""

from __future__ import annotations

import errno
import json
import logging
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from mcbe_editor.service_errors import (
    LevelDbPermissionError,
    PlayerImportRecordRollbackError,
    UserFacingRuntimeError,
    public_error_text,
)

SECRET = "C:/Users/someone/secret-world/db/000012.log"


def test_public_error_text_shows_only_phrased_messages() -> None:
    assert public_error_text(ValueError("Slot ist ungültig.")) == "Slot ist ungültig."
    restore_failure = UserFacingRuntimeError("Die Originalwelt liegt unter C:/Welten/alt.")
    assert public_error_text(restore_failure) == "Die Originalwelt liegt unter C:/Welten/alt."
    permission = LevelDbPermissionError(operation="Schreiben", db_path="/worlds/Test/db")
    assert public_error_text(permission) == str(permission)

    assert public_error_text(KeyError(SECRET)) == "interner Fehler, Details im Server-Log"
    disk_full = OSError(errno.ENOSPC, "No space left on device", SECRET)
    assert public_error_text(disk_full) == "Systemfehler „No space left on device“, Details im Server-Log"
    assert public_error_text(OSError(SECRET)) == "interner Fehler, Details im Server-Log"


def test_public_error_text_names_the_request_id_of_the_log_entry() -> None:
    import main

    with main.app.test_request_context("/", headers={"Accept-Language": "de"}):
        main.assign_request_id()
        request_id = main._request_id()
        assert public_error_text(KeyError(SECRET)) == f"interner Fehler, Details im Server-Log (Anfrage-ID {request_id})"
    with main.app.test_request_context("/", headers={"Accept-Language": "en"}):
        main.assign_request_id()
        request_id = main._request_id()
        assert public_error_text(KeyError(SECRET)) == f"internal error, details in the server log (request ID {request_id})"


def _player_client(monkeypatch, **service_methods):
    import main

    deps = replace(
        main.player_route_deps(),
        service=SimpleNamespace(**service_methods),
        require_world_db_access_allowed=lambda: None,
        require_world_write_allowed=lambda: None,
        require_server_guard_current=lambda _data: None,
        presence_conflict_response=lambda *_args, **_kwargs: None,
        audit_event=lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(main, "player_route_deps", lambda: deps)
    return main.app.test_client(), {"X-CSRF-Token": main.CSRF_TOKEN}


def test_unexpected_load_failure_answers_with_the_request_id_instead_of_its_text(monkeypatch, caplog) -> None:
    client, headers = _player_client(monkeypatch, list_players=Mock(side_effect=KeyError(SECRET)))

    with caplog.at_level(logging.ERROR):
        response = client.post("/api/players", json={"world_path": "world"}, headers=headers)

    data = response.get_json()
    request_id = response.headers["X-Request-ID"]
    assert response.status_code == 500
    assert data["request_id"] == request_id
    assert data["message"] == "Fehler beim Erkennen der Spieler."
    assert data["details"] == f"interner Fehler, Details im Server-Log (Anfrage-ID {request_id})"
    assert data["hints"]
    assert "secret-world" not in json.dumps(data, ensure_ascii=False)
    # The log keeps the text under the same request ID.
    assert any(request_id in record.getMessage() and "secret-world" in record.getMessage() for record in caplog.records)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (KeyError(SECRET), "Fehler beim Speichern des Spielers: interner Fehler, Details im Server-Log (Anfrage-ID {request_id})"),
        (
            OSError(errno.ENOSPC, "No space left on device", SECRET),
            "Fehler beim Speichern des Spielers: Systemfehler „No space left on device“, Details im Server-Log (Anfrage-ID {request_id})",
        ),
    ],
    ids=["unexpected", "system"],
)
def test_unexpected_save_failure_keeps_its_context_without_the_exception_text(monkeypatch, error, expected) -> None:
    client, headers = _player_client(monkeypatch, save_player=Mock(side_effect=error))

    response = client.post(
        "/api/player/save",
        json={"world_path": "world", "player_key": "~local_player", "inventory": []},
        headers=headers,
    )

    data = response.get_json()
    request_id = response.headers["X-Request-ID"]
    assert response.status_code == 500
    assert data["error"] == expected.format(request_id=request_id)
    assert "secret-world" not in json.dumps(data, ensure_ascii=False)


def test_a_refused_database_permission_keeps_its_explanation(monkeypatch) -> None:
    refused = LevelDbPermissionError(operation="Schreiben", db_path="/worlds/Test/db")
    client, headers = _player_client(monkeypatch, save_player=Mock(side_effect=refused))

    response = client.post(
        "/api/player/save",
        json={"world_path": "world", "player_key": "~local_player", "inventory": []},
        headers=headers,
    )

    assert response.status_code == 500
    assert response.get_json()["error"] == f"Fehler beim Speichern des Spielers: {refused}"
    assert "verweigert Zugriff" in response.get_json()["error"]


def test_rollback_failures_reach_the_log_with_their_text(caplog) -> None:
    with caplog.at_level(logging.ERROR, logger="mcbe_editor.service_errors"):
        error = PlayerImportRecordRollbackError(
            ValueError("Nachvalidierung fehlgeschlagen"),
            rollback_failures=(("Zielzustand konnte nicht zurückgeschrieben werden", OSError(SECRET)),),
        )

    assert error.rollback_warning == (
        "Import-Rollback unvollständig: Zielzustand konnte nicht zurückgeschrieben werden: interner Fehler, Details im Server-Log"
    )
    assert "secret-world" in caplog.text
