"""Structured, localized API error payloads.

``error`` remains as a compatibility alias for existing clients. New clients
can use the stable ``code`` plus ``params`` and localize ``message_key`` at the
display boundary.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from . import i18n

_ERROR_CODE_RE = re.compile(r"[^a-z0-9_]+")
_STATUS_ERROR_CODES = {
    400: "invalid_request",
    401: "authentication_required",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    413: "request_too_large",
    428: "precondition_required",
    429: "rate_limited",
    500: "internal_server_error",
}


def normalize_error_code(value: object) -> str:
    code = _ERROR_CODE_RE.sub("_", str(value or "request_failed").strip().lower()).strip("_")
    return code or "request_failed"


def error_code_for_status(status: object) -> str:
    try:
        normalized_status = int(str(status))
    except (TypeError, ValueError):
        return "request_failed"
    return _STATUS_ERROR_CODES.get(normalized_status, "request_failed")


def error_payload(
    message_key: object,
    *,
    code: str = "request_failed",
    params: Mapping[str, object] | None = None,
    details: object | None = None,
    hints: Sequence[object] | None = None,
    request_id: str | None = None,
) -> dict[str, object]:
    source = str(message_key).strip() or "Unbekannter Fehler"
    clean_params = {str(key): value for key, value in (params or {}).items()}
    message = i18n.t(source, **clean_params)
    payload: dict[str, object] = {
        "success": False,
        "code": normalize_error_code(code),
        "params": clean_params,
        "message_key": source,
        "message": message,
        "error": message,
    }
    if details is not None and str(details).strip():
        payload["details"] = i18n.t(str(details).strip())
    if hints:
        localized_hints = [i18n.t(str(hint)) for hint in hints if str(hint).strip()]
        if localized_hints:
            payload["hints"] = localized_hints
    if request_id:
        payload["request_id"] = request_id
    return payload


def add_exception_cleanup_details(payload: dict[str, object], error: BaseException) -> dict[str, object]:
    """Expose recoverable cleanup leftovers without replacing the primary error."""

    cleanup_warning = getattr(error, "cleanup_warning", None)
    if cleanup_warning:
        payload["cleanup_warning"] = cleanup_warning
    snapshot_path = getattr(error, "source_snapshot_path", None)
    if snapshot_path:
        payload["source_snapshot_path"] = snapshot_path
    return payload
