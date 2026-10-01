"""A refused save names the action once, and file errors keep their path in the log."""

from __future__ import annotations

import errno
import json
import logging
import zipfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from mcbe_editor import backup, players
from mcbe_editor.backup_settings import BackupLimitError

SECRET = "C:/Users/someone/secret-world/backups/.mcbe_backup_x.part"
REFUSED_DURING_BACKUP = "Speichern abgelehnt: Der Spieler wurde während der Backup-Erstellung extern geändert. Bitte neu laden."
REFUSED_DURING_BACKUP_EN = "Save rejected: the player was changed externally while the backup was being created. Please reload."


def _post_save(monkeypatch, error, *, language="de"):
    import main

    deps = replace(
        main.player_route_deps(),
        service=SimpleNamespace(save_player=Mock(side_effect=error)),
        require_world_write_allowed=lambda: None,
        require_server_guard_current=lambda _data: None,
        presence_conflict_response=lambda *_args, **_kwargs: None,
        audit_event=lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(main, "player_route_deps", lambda: deps)
    return main.app.test_client().post(
        "/api/player/save",
        json={"world_path": "world", "player_key": "~local_player", "inventory": []},
        headers={"X-CSRF-Token": main.CSRF_TOKEN, "Accept-Language": language},
    )


@pytest.mark.parametrize(
    "language, expected",
    [("de", "Speichern abgelehnt: Welt-Ordner existiert nicht."), ("en", "Save rejected: World folder does not exist.")],
)
def test_a_save_refusal_that_names_only_its_reason_gets_the_action_in_front(monkeypatch, language, expected) -> None:
    response = _post_save(monkeypatch, ValueError("Welt-Ordner existiert nicht."), language=language)

    data = response.get_json()
    assert response.status_code == 400
    assert data["error"] == expected
    # The page localizes message_key with its params again.
    assert data["message_key"] == "Speichern abgelehnt: {error}"


@pytest.mark.parametrize(
    "language, raised, expected",
    [
        ("de", REFUSED_DURING_BACKUP, REFUSED_DURING_BACKUP),
        # A German source text is translated in the answer ...
        ("en", REFUSED_DURING_BACKUP, REFUSED_DURING_BACKUP_EN),
        # ... and a refusal raised through t() is already in the request language.
        ("en", REFUSED_DURING_BACKUP_EN, REFUSED_DURING_BACKUP_EN),
    ],
)
def test_a_save_refusal_that_names_its_action_keeps_one_prefix(monkeypatch, language, raised, expected) -> None:
    response = _post_save(monkeypatch, ValueError(raised), language=language)

    assert response.status_code == 409
    assert response.get_json()["error"] == expected


def test_every_english_save_refusal_starts_with_the_prefix_the_route_recognizes() -> None:
    # A refusal raised through t() is English before the route sees it; a
    # different wording would get "Save rejected:" a second time.
    catalog = json.loads((Path(__file__).resolve().parents[1] / "static" / "i18n" / "en.json").read_text(encoding="utf-8"))
    prefix = catalog["Speichern abgelehnt: {error}"].split("{", 1)[0]
    refusals = {key: value for key, value in catalog.items() if key.startswith("Speichern abgelehnt:")}

    assert len(refusals) > 1
    assert [key for key, value in refusals.items() if not value.startswith(prefix)] == []


def test_a_refused_save_over_the_backup_limit_keeps_its_code(monkeypatch) -> None:
    response = _post_save(monkeypatch, BackupLimitError("Das Backup überschreitet das Größenlimit."))

    data = response.get_json()
    assert response.status_code == 400
    assert data["code"] == "backup_limit_exceeded"
    assert data["error"] == "Speichern abgelehnt: Das Backup überschreitet das Größenlimit."


def test_a_refused_workspace_save_names_the_action_once(monkeypatch) -> None:
    import main

    deps = replace(main.mount_route_deps(), require_world_write_allowed=lambda: None, audit_event=lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main, "mount_route_deps", lambda: deps)

    response = main.app.test_client().post(
        "/api/workspace/save",
        json={"world_path": "world", "player_key": "~local_player", "mounts": "keine Liste"},
        headers={"X-CSRF-Token": main.CSRF_TOKEN, "Accept-Language": "de"},
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "Speichern abgelehnt: mounts muss eine Liste sein."


def test_an_unreadable_backup_names_the_system_error_without_its_path(tmp_path, monkeypatch, caplog) -> None:
    archive = tmp_path / "backup.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("level.dat", b"x")

    def locked(_self):
        raise PermissionError(errno.EACCES, "Permission denied", SECRET)

    monkeypatch.setattr(zipfile.ZipFile, "testzip", locked)
    with caplog.at_level(logging.ERROR, logger="mcbe_editor.service_errors"), pytest.raises(ValueError) as raised:
        backup._verify_zip_integrity(str(archive))

    assert str(raised.value) == "Backup-Datei kann nicht gelesen werden: Systemfehler „Permission denied“, Details im Server-Log"
    assert "secret-world" in caplog.text


def test_a_missing_player_export_is_a_refusal_without_a_log_entry(tmp_path, caplog) -> None:
    world = tmp_path / "world"
    (world / "db").mkdir(parents=True)

    with caplog.at_level(logging.ERROR), pytest.raises(ValueError) as raised:
        players.snapshot_player_export_for_import(str(tmp_path / "moved.zip"), str(world))

    assert str(raised.value) == "Spieler-Export existiert nicht."
    assert caplog.records == []


def test_an_unreadable_player_export_names_the_system_error_without_its_path(tmp_path, monkeypatch, caplog) -> None:
    export = tmp_path / "player.zip"
    export.write_bytes(b"PK")

    def locked(*_args, **_kwargs):
        raise PermissionError(errno.EACCES, "Permission denied", SECRET)

    monkeypatch.setattr(players.zipfile, "ZipFile", locked)
    with caplog.at_level(logging.ERROR, logger="mcbe_editor.service_errors"), pytest.raises(ValueError) as raised:
        players.read_player_export(str(export))

    assert str(raised.value) == "Spieler-Export kann nicht gelesen werden: Systemfehler „Permission denied“, Details im Server-Log"
    assert "secret-world" in caplog.text
