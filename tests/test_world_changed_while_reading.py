"""A world that a running server changes during loading gets its own message."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from mcbe_editor.leveldb_readonly import WorldChangedWhileReadingError


@pytest.mark.parametrize(
    ("endpoint", "service_method", "payload"),
    [
        ("/api/players", "list_players", {"world_path": "world"}),
        ("/api/player/load", "load_player", {"world_path": "world", "player_key": "~local_player"}),
    ],
    ids=["list", "load"],
)
def test_loading_a_world_the_server_changes_asks_to_load_again(monkeypatch, endpoint, service_method, payload) -> None:
    import main

    error = WorldChangedWhileReadingError("/worlds/Test/db/921247.ldb")
    logged = []
    deps = replace(
        main.player_route_deps(),
        service=SimpleNamespace(**{service_method: Mock(side_effect=error)}),
        require_world_db_access_allowed=lambda: None,
        world_db_access_gate=lambda: {"read_allowed": True},
        log_api_exception=lambda *args: logged.append(args),
    )
    monkeypatch.setattr(main, "player_route_deps", lambda: deps)
    response = main.app.test_client().post(endpoint, json=payload, headers={"X-CSRF-Token": main.CSRF_TOKEN})

    assert response.status_code == 409
    result = response.get_json()
    assert result["code"] == "world_changed_while_reading"
    assert result["error"] == str(error)
    assert "Lade die Welt erneut" in str(error)
    # Hints about the world path would send the user looking in the wrong place.
    assert result["hints"] == [
        "Lade die Welt erneut; der nächste Versuch liest den aktuellen Stand.",
        "Tritt der Fehler wiederholt auf, stoppe den Server kurz und lade die Welt dann.",
    ]
    assert logged == []


def test_a_change_while_opening_the_reader_is_not_reported_as_a_broken_world(tmp_path, monkeypatch) -> None:
    from mcbe_editor.services import BedrockEditorService

    error = WorldChangedWhileReadingError(str(tmp_path / "db" / "000005.ldb"))

    def reader_factory(_path):
        raise error

    service = BedrockEditorService({}, {}, readonly_db_factory=reader_factory)
    monkeypatch.setattr("mcbe_editor.services.ensure_valid_world_path", lambda path: str(path))
    # Other failures while opening become a generic RuntimeError; a change by
    # a running server keeps its own type and message.
    with pytest.raises(WorldChangedWhileReadingError) as raised:
        service._open_db_readonly(str(tmp_path))
    assert raised.value is error
