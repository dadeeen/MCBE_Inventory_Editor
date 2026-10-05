"""Source-bound icon warnings, stored independently of the request language."""

from pathlib import Path

from .i18n import localize_message_record, request_locale, translate


def warning_record(message_key: str, *, sources=(), **params) -> dict:
    return {
        "message_key": message_key,
        "message_params": {key: str(value) if isinstance(value, Path) else value for key, value in params.items()},
        "source_indices": list(sources),
    }


def warning_text(record: dict | str, *, locale: str | None = None, _depth: int = 0) -> str:
    if isinstance(record, str):
        return translate(record, locale or request_locale())
    if not isinstance(record, dict) or _depth > 8:
        return ""
    raw_params = record.get("message_params", {})
    params = {
        key: warning_text(value, locale=locale, _depth=_depth + 1) if isinstance(value, dict) and "message_key" in value else value
        for key, value in (raw_params.items() if isinstance(raw_params, dict) else ())
    }
    if locale is not None:
        return translate(str(record.get("message_key", "")), locale, params)
    return str(localize_message_record({**record, "message_params": params})["message"])


class IconSourceError(ValueError):
    """Retain translatable validation details when an error becomes a warning."""

    def __init__(self, message_key: str, **params):
        self.record = warning_record(message_key, **params)
        super().__init__(warning_text(self.record))


def error_record(error: Exception) -> dict:
    return error.record if isinstance(error, IconSourceError) else warning_record(str(error))
