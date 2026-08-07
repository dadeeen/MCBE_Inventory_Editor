"""Locale resolution and catalog lookup for the bilingual UI.

German is the source language: user-facing strings appear in code and
templates as German literals. ``static/i18n/en.json`` maps each exact German
source string to its English translation. A missing entry falls back to the
German source string, so untranslated strings degrade gracefully instead of
breaking the UI.
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Mapping
from pathlib import Path

SUPPORTED_LOCALES: tuple[str, ...] = ("de", "en")
DEFAULT_LOCALE = "en"
LOCALE_COOKIE_NAME = "mcbe_locale"

_CATALOG_PATH = Path(__file__).resolve().parent.parent / "static" / "i18n" / "en.json"
_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")

_catalog_lock = threading.Lock()
_catalog_cache: dict[str, str] | None = None


def _load_catalog() -> dict[str, str]:
    global _catalog_cache
    with _catalog_lock:
        if _catalog_cache is None:
            raw = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("i18n catalog must be a JSON object")
            _catalog_cache = {str(key): str(value) for key, value in raw.items()}
        return _catalog_cache


def catalog_for(locale: str) -> dict[str, str]:
    """Return the translation catalog for a locale; empty for the source language."""

    if locale == "en":
        return _load_catalog()
    return {}


def resolve_locale(cookie_value: str | None, accept_language: str | None) -> str:
    """Resolve the UI locale from the locale cookie, then Accept-Language."""

    if cookie_value in SUPPORTED_LOCALES:
        return str(cookie_value)
    explicit: dict[str, tuple[float, int]] = {}
    wildcard: tuple[float, int] | None = None
    for index, part in enumerate((accept_language or "").split(",")):
        segments = [segment.strip() for segment in part.split(";")]
        language = segments[0].lower()
        if not language:
            continue
        quality = 1.0
        for parameter in segments[1:]:
            name, separator, raw_value = parameter.partition("=")
            if separator and name.strip().lower() == "q":
                try:
                    quality = float(raw_value.strip())
                except ValueError:
                    quality = 0.0
                break
        if not 0.0 <= quality <= 1.0:
            continue
        if language == "*":
            candidate = (quality, -index)
            if wildcard is None or candidate > wildcard:
                wildcard = candidate
            continue
        primary = language.split("-", 1)[0]
        if primary in SUPPORTED_LOCALES:
            candidate = (quality, -index)
            if primary not in explicit or candidate > explicit[primary]:
                explicit[primary] = candidate

    candidates: list[tuple[float, int, str]] = []
    for locale in SUPPORTED_LOCALES:
        quality_and_order = explicit.get(locale, wildcard)
        if quality_and_order is not None and quality_and_order[0] > 0.0:
            candidates.append((*quality_and_order, locale))
    if candidates:
        return max(candidates)[2]
    return DEFAULT_LOCALE


def translate(text: str, locale: str, params: Mapping[str, object] | None = None) -> str:
    """Translate a German source string and substitute ``{name}`` placeholders."""

    result = catalog_for(locale).get(text, text)
    if params:
        values: Mapping[str, object] = params
        result = _PLACEHOLDER_RE.sub(
            lambda match: str(values[match.group(1)]) if match.group(1) in values else match.group(0),
            result,
        )
    return result


def request_locale() -> str:
    """Resolve the locale of the active Flask request; German outside a request.

    German is the source language, so code paths that run without an HTTP
    request (startup scans, CLI helpers, desktop dialogs) keep producing the
    untranslated source strings.
    """

    try:
        from flask import has_request_context, request
    except ImportError:
        return "de"
    if not has_request_context():
        return "de"
    return resolve_locale(
        request.cookies.get(LOCALE_COOKIE_NAME),
        request.headers.get("Accept-Language"),
    )


def t(text: str, **params: object) -> str:
    """Translate ``text`` for the active request's locale (see ``request_locale``)."""

    return translate(text, request_locale(), params or None)


def localize_message_record(
    record: Mapping[str, object] | None,
    *,
    value_field: str = "message",
    key_field: str = "message_key",
    params_field: str = "message_params",
) -> dict[str, object]:
    """Localize a structured API message while retaining its stable source data."""

    source = dict(record or {})
    message_key = str(source.get(key_field) or source.get(value_field) or "")
    raw_params = source.get(params_field)
    params = dict(raw_params) if isinstance(raw_params, Mapping) else {}
    return {**source, value_field: t(message_key, **params)}
