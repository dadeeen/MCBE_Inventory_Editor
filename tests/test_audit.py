from __future__ import annotations

import json
import os
import stat
from unittest.mock import patch

from mcbe_editor.audit import AuditLogger, sanitize_detail, summarize_player_key, summarize_world_path


def test_audit_redacts_secrets_and_summarizes_paths(tmp_path):
    logger = AuditLogger(tmp_path / "events.jsonl", enabled=True, max_bytes=100_000)
    logger.record(
        "player.save",
        outcome="success",
        remote="127.0.0.1",
        username="admin",
        world_path=str(tmp_path / "World One"),
        player_key="player_server_1234567890abcdef",
        details={"password": "secret", "backup_file": "/tmp/backup.zip", "count": 2},
    )

    events = logger.tail(10)
    assert len(events) == 1
    event = events[0]
    assert event["action"] == "player.save"
    assert event["world"]["name"] == "World One"
    assert "path_sha256" in event["world"]
    assert event["player"]["preview"].startswith("player_server")
    assert event["details"]["password"] == "<redacted>"
    assert event["details"]["backup_file"] == "backup.zip"

    line = (tmp_path / "events.jsonl").read_text(encoding="utf-8").strip()
    assert json.loads(line)["outcome"] == "success"


def test_audit_uses_owner_only_file_mode_on_posix(tmp_path):
    if os.name == "nt":
        return
    path = tmp_path / "audit" / "events.jsonl"
    logger = AuditLogger(path, enabled=True, max_bytes=100_000)

    logger.record("player.save", outcome="success")

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_audit_repairs_existing_file_mode_on_posix(tmp_path):
    if os.name == "nt":
        return
    path = tmp_path / "events.jsonl"
    path.write_text("", encoding="utf-8")
    path.chmod(0o644)

    logger = AuditLogger(path, enabled=True, max_bytes=100_000)

    assert logger.enabled is True
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_audit_reports_existing_file_permission_failure(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_text("", encoding="utf-8")

    with patch("mcbe_editor.audit.restrict_private_file", side_effect=PermissionError("denied")):
        logger = AuditLogger(path, enabled=True, max_bytes=100_000)

    status = logger.status()
    assert status["enabled"] is False
    assert status["healthy"] is False
    assert status["last_error"] == "file_permissions_failed"
    assert "path" not in status


def test_audit_rotation(tmp_path):
    path = tmp_path / "events.jsonl"
    logger = AuditLogger(path, enabled=True, max_bytes=100_000)
    path.write_text("x" * 110_000, encoding="utf-8")
    logger.record("scan_path.add", outcome="success", details={"path": "/tmp/worlds"})
    assert path.exists()
    assert path.with_suffix(".jsonl.1").exists()
    assert logger.tail(1)[0]["action"] == "scan_path.add"


def test_failed_audit_rotation_preserves_previous_archive(tmp_path):
    path = tmp_path / "events.jsonl"
    rotated = path.with_suffix(".jsonl.1")
    path.write_text("x" * 110_000, encoding="utf-8")
    rotated.write_text("previous archive", encoding="utf-8")
    logger = AuditLogger(path, enabled=True, max_bytes=100_000)

    with patch.object(type(path), "replace", side_effect=PermissionError("locked")):
        assert logger.record("scan_path.add", outcome="success") is False

    assert path.exists()
    assert rotated.read_text(encoding="utf-8") == "previous archive"
    assert path.stat().st_size == 110_000
    assert logger.status()["healthy"] is False
    assert logger.status()["dropped_events"] == 1


def test_audit_rotates_before_next_event_would_exceed_limit(tmp_path):
    path = tmp_path / "events.jsonl"
    logger = AuditLogger(path, enabled=True, max_bytes=100_000)
    path.write_text("x" * 99_950, encoding="utf-8")

    assert logger.record("scan_path.add", outcome="success") is True

    assert path.stat().st_size < 100_000
    assert path.with_suffix(".jsonl.1").stat().st_size == 99_950


def test_audit_recovers_health_after_transient_write_failure(tmp_path):
    path = tmp_path / "events.jsonl"
    logger = AuditLogger(path, enabled=True, max_bytes=100_000)

    with patch("mcbe_editor.audit.append_private_text", side_effect=PermissionError("locked")):
        assert logger.record("first", outcome="failure") is False
    assert logger.record("second", outcome="success") is True

    status = logger.status()
    assert status["healthy"] is True
    assert status["last_error"] is None
    assert status["dropped_events"] == 1


def test_audit_omits_oversized_details_but_keeps_event(tmp_path):
    path = tmp_path / "events.jsonl"
    logger = AuditLogger(path, enabled=True, max_bytes=100_000)

    assert (
        logger.record(
            "large",
            outcome="success",
            details={"rows": [{f"field-{index}": "x" * 500 for index in range(50)} for _ in range(50)]},
        )
        is True
    )

    event = logger.tail(1)[0]
    assert event["action"] == "large"
    assert event["details"] == {"omitted": "event_too_large"}
    assert path.stat().st_size < 64_000


def test_audit_replaces_unpaired_unicode_without_breaking_operation(tmp_path):
    path = tmp_path / "events.jsonl"
    logger = AuditLogger(path, enabled=True, max_bytes=100_000)

    assert logger.record("unicode", outcome="success", details={"value": "\ud800"}) is True

    assert logger.tail(1)[0]["details"]["value"] == "?"


def test_audit_tail_max_limit_allows_large_exports(tmp_path):
    path = tmp_path / "events.jsonl"
    logger = AuditLogger(path, enabled=True, max_bytes=100_000_000)
    lines = [json.dumps({"ts": str(i), "action": "a", "outcome": "success"}) for i in range(600)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # UI-Tail bleibt beim Standardcap; der Export darf per max_limit darüber.
    assert len(logger.tail(5000)) == 500
    assert len(logger.tail(5000, max_limit=5000)) == 600


def test_audit_tail_and_export_include_rotated_file(tmp_path):
    path = tmp_path / "events.jsonl"
    rotated = path.with_suffix(".jsonl.1")
    logger = AuditLogger(path, enabled=True, max_bytes=100_000)
    rotated.write_text(json.dumps({"id": 1}) + "\n", encoding="utf-8")
    path.write_text(json.dumps({"id": 2}) + "\n" + json.dumps({"id": 3}) + "\n", encoding="utf-8")

    result = logger.read_events(2, max_limit=5000)

    assert result["events"] == [{"id": 2}, {"id": 3}]
    assert result["available_events"] == 3
    assert result["truncated"] is True
    assert result["invalid_lines"] == 0
    assert result["read_errors"] == 0
    assert result["files_read"] == 2


def test_sanitizers_do_not_expose_raw_world_path(tmp_path):
    world = summarize_world_path(tmp_path / "Sensitive" / "World")
    assert world == {"name": "World", "path_sha256": world["path_sha256"]}
    assert str(tmp_path) not in str(world)
    player = summarize_player_key("abcdefghijklmnopqrstuvwxyz")
    assert player["preview"] == "abcdefghijklmnopqrstuvwx"
    assert sanitize_detail({"csrf_token": "abc"})["csrf_token"] == "<redacted>"


def test_audit_tail_tolerates_invalid_utf8(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_bytes(b"\xff\xfe")
    logger = AuditLogger(path, enabled=True, max_bytes=100_000)

    assert logger.tail(10) == []


def test_audit_tail_keeps_valid_lines_next_to_invalid_utf8(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_bytes(b'\xff\n{"id": 1}\n')
    logger = AuditLogger(path, enabled=True, max_bytes=100_000)

    result = logger.read_events(10)

    assert result["events"] == [{"id": 1}]
    assert result["invalid_lines"] == 1
