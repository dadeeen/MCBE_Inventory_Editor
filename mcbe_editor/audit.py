from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import threading
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mcbe_editor.runtime_data import append_private_text, restrict_private_file

_SAFE_DETAIL_TYPES = (str, int, float, bool, type(None))
_QUOTED_PATH_RE = re.compile(r"""(?P<quote>["'])(?P<path>(?:[a-zA-Z]:[\\/]|/)[^"'\r\n]+)(?P=quote)""")
_WINDOWS_PATH_RE = re.compile(r"(?i)\b[a-z]:[\\/][^\s\"']+")
_POSIX_PATH_RE = re.compile(r"(?<!\w)/(?:[^\s\"']+/)+[^\s\"']+")
_MAX_EVENT_BYTES = 64_000
LOGGER = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _json_line(value: dict[str, Any]) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    return text.encode("utf-8", errors="replace").decode("utf-8")


def stable_hash(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    if not text:
        return None
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def _safe_basename(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return Path(text.replace("\\", "/")).name[:160]


def summarize_world_path(world_path: Any) -> dict[str, str] | None:
    if world_path is None:
        return None
    text = str(world_path).strip()
    if not text:
        return None
    try:
        normalized = os.path.normcase(os.path.realpath(os.path.abspath(os.path.normpath(text))))
    except OSError:
        normalized = text
    return {
        "name": Path(text.replace("\\", "/")).name[:160],
        "path_sha256": stable_hash(normalized) or "",
    }


def summarize_player_key(player_key: Any) -> dict[str, str] | None:
    if player_key is None:
        return None
    text = str(player_key).strip()
    if not text:
        return None
    return {
        "preview": text[:24],
        "sha256": stable_hash(text) or "",
    }


def sanitize_error(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None

    def replace_path(match: re.Match[str]) -> str:
        raw_path = match.groupdict().get("path") or match.group(0)
        return _safe_basename(raw_path.rstrip(".,;:")) or "<path>"

    text = _QUOTED_PATH_RE.sub(replace_path, text)
    text = _WINDOWS_PATH_RE.sub(replace_path, text)
    text = _POSIX_PATH_RE.sub(replace_path, text)
    return text[:500]


def sanitize_detail(value: Any, *, depth: int = 0) -> Any:
    if depth > 3:
        return "<max-depth>"
    if isinstance(value, _SAFE_DETAIL_TYPES):
        if isinstance(value, str):
            return value[:500]
        if isinstance(value, float) and not math.isfinite(value):
            return str(value)
        return value
    if isinstance(value, Path):
        return _safe_basename(value)
    if isinstance(value, (list, tuple)):
        return [sanitize_detail(item, depth=depth + 1) for item in value[:50]]
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in list(value.items())[:50]:
            key_text = str(key)[:80]
            lowered = key_text.lower()
            if any(secret in lowered for secret in ("password", "token", "secret", "csrf", "session")):
                sanitized[key_text] = "<redacted>"
            elif (
                lowered.endswith("path")
                or lowered in {"world_path", "export_zip"}
                or lowered.endswith("file")
                or lowered.endswith("filename")
                or lowered == "backup_file"
            ):
                sanitized[key_text] = _safe_basename(item)
            elif lowered.endswith("key") or lowered == "player_key":
                sanitized[key_text] = summarize_player_key(item)
            else:
                sanitized[key_text] = sanitize_detail(item, depth=depth + 1)
        return sanitized
    return str(value)[:500]


class AuditLogger:
    """Small append-only JSONL audit trail for admin-visible operations.

    The audit log is intentionally separate from application logs. Application
    logs are for operators watching Docker; the audit log is a compact history of
    who changed what, when, and whether the action succeeded. Sensitive values are
    redacted or hashed before writing.
    """

    def __init__(self, path: str | os.PathLike | None, *, enabled: bool = False, max_bytes: int = 5_000_000):
        self.path = Path(path).expanduser() if path else None
        self.enabled = bool(enabled and self.path)
        self.max_bytes = max(100_000, int(max_bytes or 5_000_000))
        self._lock = threading.RLock()
        self._last_error: str | None = None
        self._last_error_at: str | None = None
        self._dropped_events = 0
        if self.enabled and self.path and self.path.exists():
            try:
                restrict_private_file(self.path)
            except OSError:
                self.enabled = False
                self._last_error = "file_permissions_failed"
                self._last_error_at = _utc_now_iso()
                LOGGER.error("audit_log unavailable reason=file_permissions_failed")

    def status(self) -> dict[str, Any]:
        current_size = None
        status_error = None
        if self.enabled and self.path:
            try:
                current_size = self.path.stat().st_size
            except FileNotFoundError:
                current_size = 0
            except OSError:
                status_error = "stat_failed"
        return {
            "enabled": self.enabled,
            "healthy": False if self._last_error or status_error else (True if self.enabled else None),
            "max_bytes": self.max_bytes,
            "current_bytes": current_size,
            "last_error": self._last_error or status_error,
            "last_error_at": self._last_error_at,
            "dropped_events": self._dropped_events,
            "format": "jsonl",
        }

    def _mark_failure(self, reason: str) -> None:
        first_failure = self._last_error is None
        self._last_error = reason
        self._last_error_at = _utc_now_iso()
        self._dropped_events += 1
        if first_failure:
            LOGGER.error("audit_log unavailable reason=%s", reason)

    def _mark_success(self) -> None:
        if self._last_error is not None:
            LOGGER.info("audit_log recovered")
        self._last_error = None
        self._last_error_at = None

    def _rotate_if_needed(self, incoming_bytes: int = 0) -> None:
        if not self.path or not self.path.exists():
            return
        if self.path.stat().st_size + max(0, incoming_bytes) <= self.max_bytes:
            return
        rotated = self.path.with_suffix(self.path.suffix + ".1")
        # Path.replace/os.replace replaces an existing target atomically.
        # Deleting it first would lose the previous archive when the
        # subsequent rotation fails (for example because the current log
        # is transiently locked on Windows).
        self.path.replace(rotated)

    def record(
        self,
        action: str,
        *,
        outcome: str,
        remote: str | None = None,
        username: str | None = None,
        request_id: str | None = None,
        world_path: str | None = None,
        player_key: str | None = None,
        details: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> bool:
        if not self.enabled or not self.path:
            return False
        event: dict[str, Any] = {
            "ts": _utc_now_iso(),
            "action": str(action)[:120],
            "outcome": str(outcome)[:40],
        }
        if request_id:
            event["request_id"] = str(request_id)[:80]
        if remote:
            event["remote"] = str(remote)[:120]
        if username:
            event["username"] = str(username)[:120]
        world = summarize_world_path(world_path)
        if world:
            event["world"] = world
        player = summarize_player_key(player_key)
        if player:
            event["player"] = player
        if details:
            event["details"] = sanitize_detail(details)
        sanitized_error = sanitize_error(error)
        if sanitized_error:
            event["error"] = sanitized_error

        line = _json_line(event)
        encoded_size = len(line.encode("utf-8"))
        if encoded_size > _MAX_EVENT_BYTES and "details" in event:
            event["details"] = {"omitted": "event_too_large"}
            line = _json_line(event)
            encoded_size = len(line.encode("utf-8"))
        with self._lock:
            try:
                self._rotate_if_needed(encoded_size)
                append_private_text(self.path, line)
                self._mark_success()
                return True
            except OSError:
                # Avoid breaking the editor because audit storage is temporarily
                # unavailable. The health status and application log expose it.
                self._mark_failure("write_or_rotation_failed")
                return False

    def read_events(
        self,
        limit: int = 100,
        *,
        max_limit: int = 500,
        include_rotated: bool = True,
    ) -> dict[str, Any]:
        limit = max(1, min(int(limit or 100), max(1, int(max_limit))))
        entries: deque[dict[str, Any]] = deque(maxlen=limit)
        available_events = 0
        invalid_lines = 0
        read_errors = 0
        files_read = 0
        if not self.enabled or not self.path:
            return {
                "events": [],
                "available_events": 0,
                "truncated": False,
                "invalid_lines": 0,
                "read_errors": 0,
                "files_read": 0,
            }

        paths = []
        if include_rotated:
            paths.append(self.path.with_suffix(self.path.suffix + ".1"))
        paths.append(self.path)
        with self._lock:
            for path in paths:
                if not path.exists():
                    continue
                try:
                    with path.open("r", encoding="utf-8", errors="replace") as handle:
                        files_read += 1
                        for line in handle:
                            try:
                                value = json.loads(line)
                            except (json.JSONDecodeError, RecursionError):
                                invalid_lines += 1
                                continue
                            if isinstance(value, dict):
                                available_events += 1
                                entries.append(value)
                            else:
                                invalid_lines += 1
                except OSError:
                    read_errors += 1

        events = list(entries)
        return {
            "events": events,
            "available_events": available_events,
            "truncated": available_events > len(events),
            "invalid_lines": invalid_lines,
            "read_errors": read_errors,
            "files_read": files_read,
        }

    def tail(self, limit: int = 100, *, max_limit: int = 500) -> list[dict[str, Any]]:
        return self.read_events(limit, max_limit=max_limit)["events"]
