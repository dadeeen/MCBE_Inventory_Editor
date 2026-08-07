"""HTTP response helpers for common headers and error payloads."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .api_errors import error_payload

JsonErrorResponse = tuple[Any, int]


def add_security_headers(response: Any) -> Any:
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "font-src 'self'; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'",
    )
    return response


def add_locale_vary_headers(response: Any) -> Any:
    vary = {value.strip() for value in response.headers.get("Vary", "").split(",") if value.strip()}
    vary.update({"Accept-Language", "Cookie"})
    response.headers["Vary"] = ", ".join(sorted(vary))
    return response


def request_too_large(jsonify: Callable[..., Any]) -> JsonErrorResponse:
    return jsonify(error_payload("Upload/Anfrage ist zu groß.", code="request_too_large")), 413


def not_found(jsonify: Callable[..., Any]) -> JsonErrorResponse:
    return jsonify(error_payload("Seite nicht gefunden.", code="not_found")), 404


def server_error(jsonify: Callable[..., Any]) -> JsonErrorResponse:
    return jsonify(error_payload("Interner Serverfehler", code="internal_server_error")), 500
