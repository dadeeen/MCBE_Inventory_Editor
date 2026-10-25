"""Concise HTTP failures shared by the item and icon updater workers."""

from __future__ import annotations

import contextlib
import json
import time
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from functools import wraps
from http.client import HTTPException
from urllib.error import HTTPError
from urllib.parse import urlsplit

from .i18n import t
from .update_output_i18n import output_t

ERROR_PREFIX = "MCBE_UPDATE_HTTP_ERROR:"
MAX_ERROR_BODY_BYTES = 8192
MAX_TIMESTAMP = 253402300799  # Last second representable by datetime.
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _future_timestamp(value, now: float) -> int | None:
    try:
        timestamp = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return timestamp if now < timestamp <= MAX_TIMESTAMP else None


def _retry_at(headers, *, github: bool, now: float) -> int | None:
    candidates = []
    retry = headers.get("Retry-After", "").strip()
    if retry.isascii() and retry.isdecimal():
        with contextlib.suppress(ValueError, OverflowError):
            candidates.append(_future_timestamp(int(now) + int(retry), now))
    elif retry:
        with contextlib.suppress(ValueError, TypeError, OverflowError):
            date = parsedate_to_datetime(retry)
            if date.tzinfo is not None:
                candidates.append(_future_timestamp((date - EPOCH).total_seconds(), now))
    if github and headers.get("X-RateLimit-Remaining", "").strip() == "0":
        candidates.append(_future_timestamp(headers.get("X-RateLimit-Reset"), now))
    return max((value for value in candidates if value is not None), default=None)


def http_failure(error: HTTPError) -> dict:
    """Read bounded GitHub error metadata without exposing the response body."""
    github = urlsplit(error.url).hostname == "api.github.com"
    headers = error.headers or {}
    limited = error.code == 429
    if github and error.code == 403:
        message = str(error.reason).lower()
        with contextlib.suppress(OSError, HTTPException, ValueError, UnicodeError, RecursionError):
            body = error.read(MAX_ERROR_BODY_BYTES + 1)
            if len(body) <= MAX_ERROR_BODY_BYTES:
                data = json.loads(body)
                if isinstance(data, dict) and isinstance(data.get("message"), str):
                    message += " " + data["message"].lower()
        limited = headers.get("X-RateLimit-Remaining", "").strip() == "0" or "rate limit" in message
    retry_at = _retry_at(headers, github=github, now=time.time()) if error.code in (403, 429, 503) else None
    return {
        "schema": 1,
        "category": "github-rate-limit" if github and limited else "http-error",
        "http_status": error.code,
        "retry_at": retry_at,
    }


def failure_fields(failure: dict, translate=t) -> dict:
    result = {
        "category": failure["category"],
        "http_status": failure["http_status"],
        "error": translate("GitHub-Anfragelimit erreicht. Bitte später erneut versuchen.")
        if failure["category"] == "github-rate-limit"
        else translate("Die Online-Quelle meldet einen Fehler (HTTP {status}).", status=failure["http_status"]),
    }
    retry_at = _future_timestamp(failure.get("retry_at"), time.time())
    if retry_at is not None:
        result["retry_at"] = retry_at
        result["hint"] = translate(
            "Erneuter Versuch frühestens ab {time} (UTC).",
            time=(EPOCH + timedelta(seconds=retry_at)).strftime("%Y-%m-%d %H:%M:%S"),
        )
    return result


def report_http_errors(main):
    """Handle HTTP errors, including wrapped downloads, in CLI and desktop workers."""

    @wraps(main)
    def run(*args, **kwargs):
        try:
            return main(*args, **kwargs)
        except Exception as exc:
            error = exc
            visited = set()
            while error is not None and id(error) not in visited:
                visited.add(id(error))
                if isinstance(error, HTTPError):
                    try:
                        failure = http_failure(error)
                    finally:
                        error.close()
                    # Signed download URLs can contain credentials in their query.
                    url = urlsplit(error.url)
                    source = url._replace(query="", fragment="").geturl()
                    fields = failure_fields(failure, output_t)
                    print(output_t("Fehler beim Laden von {url}: HTTP {status}", url=source, status=error.code))
                    print(fields["error"])
                    if fields.get("hint"):
                        print(fields["hint"])
                    print(ERROR_PREFIX + json.dumps(failure))
                    return 1
                error = error.__cause__ or error.__context__
            raise

    return run


def extract_http_failure(output: str) -> tuple[str, dict | None]:
    """Separate the explicit worker record from the human-readable protocol."""
    visible = []
    failure = None
    for line in output.splitlines(keepends=True):
        if line.startswith(ERROR_PREFIX):
            try:
                candidate = json.loads(line[len(ERROR_PREFIX) :])
                if (
                    isinstance(candidate, dict)
                    and candidate.get("schema") == 1
                    and candidate.get("category") in ("github-rate-limit", "http-error")
                    and type(candidate.get("http_status")) is int
                    and 400 <= candidate["http_status"] <= 599
                    and (candidate["category"] != "github-rate-limit" or candidate["http_status"] in (403, 429))
                ):
                    failure = candidate
                    continue
            except (ValueError, TypeError, RecursionError):
                pass
        visible.append(line)
    return "".join(visible), failure
