"""Villager failures retain actionable, safe diagnostics at the HTTP boundary."""

from __future__ import annotations

import errno
import json
from unittest.mock import Mock

import pytest

from mcbe_editor import villager_service
from mcbe_editor.service_errors import LevelDbPermissionError
from tests.test_villager_workflow import (
    _preview_request,
    _records,
    villager_client as villager_client,
    villager_world as villager_world,
)


def test_refused_villager_save_retains_the_permission_explanation(villager_client, villager_world, monkeypatch):
    import main

    world, original = villager_world
    preview, _ = _preview_request(villager_client, world)
    error = LevelDbPermissionError(operation="Öffnen", db_path=f"{world}/db")
    monkeypatch.setattr(main.editor_service, "_open_db", Mock(side_effect=error))

    response = villager_client.post("/api/villagers/save", json={"world_path": world, "preview_token": preview["preview_token"]})

    data = response.get_json()
    assert response.status_code == 500
    assert data["code"] == "villager_request_failed"
    assert data["details"] == str(error)
    assert data["request_id"] == response.headers["X-Request-ID"]
    assert _records(world) == original


@pytest.mark.parametrize("system_error", [False, True], ids=["unexpected", "disk_full"])
def test_villager_failure_details_hide_internal_paths_and_name_the_request(villager_client, monkeypatch, system_error):
    private_path = "/private/unexpected-location/secret-db/000023.log"
    error = OSError(errno.ENOSPC, "No space left on device", private_path) if system_error else RuntimeError(private_path)
    monkeypatch.setattr(villager_service, "scan", Mock(side_effect=error))

    response = villager_client.post("/api/villagers/scan", json={"world_path": "world"})

    data = response.get_json()
    assert response.status_code == 500
    assert data["request_id"] == response.headers["X-Request-ID"]
    assert data["request_id"] in data["details"]
    assert private_path not in json.dumps(data, ensure_ascii=False)
    if system_error:
        assert "No space left on device" in data["details"]
    else:
        assert "interner Fehler" in data["details"]
