"""Handlers for audit trail API routes."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AuditRouteDeps:
    audit_log: Any
    jsonify: Callable[..., Any]
    response: Callable[..., Any]
    api_error: Callable[..., Any]
    auth_enabled: Callable[[], bool]
    is_authenticated: Callable[[], bool]
    auth_required_response: Callable[[], Any]
    wide_reachable: Callable[[], bool]


def _int_arg(args: Any, key: str, default: int) -> int:
    try:
        return int(args.get(key, str(default)))
    except ValueError:
        return default


def _audit_read_blocked_message(deps: AuditRouteDeps, action: str) -> Any | None:
    if deps.audit_log.enabled and not deps.auth_enabled() and deps.wide_reachable():
        if action == "export":
            return deps.api_error("Audit-Export ist im Docker/LAN-Modus nur mit aktivierter Auth erlaubt.", 403)
        return deps.api_error("Audit-Ereignisse sind im Docker/LAN-Modus nur mit aktivierter Auth abrufbar.", 403)
    if deps.audit_log.enabled and deps.auth_enabled() and not deps.is_authenticated():
        return deps.auth_required_response()
    return None


def _public_audit_status(deps: AuditRouteDeps) -> dict[str, Any]:
    status = dict(deps.audit_log.status() or {})
    status.pop("path", None)
    return status


def audit_events(args: Any, deps: AuditRouteDeps):
    blocked = _audit_read_blocked_message(deps, "events")
    if blocked:
        return blocked
    limit = _int_arg(args, "limit", 100)
    return deps.jsonify({"success": True, "audit_log": _public_audit_status(deps), "events": deps.audit_log.tail(limit)})


def audit_export(args: Any, deps: AuditRouteDeps):
    blocked = _audit_read_blocked_message(deps, "export")
    if blocked:
        return blocked
    limit = max(1, min(_int_arg(args, "limit", 1000), 5000))
    # Der Export darf mehr Zeilen liefern als das UI-Tail (Standardcap 500),
    # sonst schneidet ein "limit=5000"-Export still bei 500 Events ab.
    export = deps.audit_log.read_events(limit, max_limit=5000)
    payload = {
        "success": True,
        "audit_log": _public_audit_status(deps),
        "events": export.pop("events"),
        "export": export,
    }
    body = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    return deps.response(
        body,
        mimetype="application/json; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=mcbe-audit-events.json"},
    )
