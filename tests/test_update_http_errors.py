import io
import json
import runpy
import sys
from email.message import Message
from http.client import IncompleteRead
from unittest.mock import Mock
from urllib.error import HTTPError

import pytest

from mcbe_editor import update_http_errors as errors
from scripts import update_db, update_icons

NOW = 2_000_000_000
API_URL = "https://api.github.com/repos/Mojang/bedrock-samples/releases/latest"


def http_error(status=403, headers=None, body=b"", url=API_URL, reason="Forbidden"):
    message = Message()
    for name, value in (headers or {}).items():
        message[name] = value
    return HTTPError(url, status, reason, message, io.BytesIO(body))


@pytest.mark.parametrize(
    ("status", "headers", "body", "category", "retry_at"),
    [
        (403, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(NOW + 120)}, b"", "github-rate-limit", NOW + 120),
        (403, {}, b'{"message":"API rate limit exceeded for a shared IP"}', "github-rate-limit", None),
        (403, {"Retry-After": "60"}, b'{"message":"You have exceeded a secondary rate limit"}', "github-rate-limit", NOW + 60),
        (403, {"X-RateLimit-Remaining": "30"}, b'{"message":"Resource not accessible"}', "http-error", None),
        (403, {}, b"<html>Forbidden</html>", "http-error", None),
        (429, {"Retry-After": "90"}, b"", "github-rate-limit", NOW + 90),
        (404, {"X-RateLimit-Remaining": "0"}, b"", "http-error", None),
        (500, {}, b"", "http-error", None),
        (503, {"Retry-After": "60"}, b"", "http-error", NOW + 60),
        (403, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "bad", "Retry-After": "NaN"}, b"", "github-rate-limit", None),
        (429, {"Retry-After": "-1", "X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(NOW - 1)}, b"", "github-rate-limit", None),
        (429, {"Retry-After": "99999999999999999999999999"}, b"", "github-rate-limit", None),
        (429, {"Retry-After": "Mon, 01 Jan 0001 00:00:00 GMT"}, b"", "github-rate-limit", None),
        (429, {"Retry-After": "Fri, 31 Dec 9999 23:59:59 GMT"}, b"", "github-rate-limit", errors.MAX_TIMESTAMP),
        (429, {"Retry-After": "Wed, 18 May 2033 03:35:00 GMT"}, b"", "github-rate-limit", NOW + 100),
        (429, {"Retry-After": "60", "X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(NOW + 120)}, b"", "github-rate-limit", NOW + 120),
    ],
)
def test_http_failures_distinguish_rate_limits_and_validate_retry_headers(monkeypatch, status, headers, body, category, retry_at):
    monkeypatch.setattr(errors.time, "time", lambda: NOW)
    with http_error(status, headers, body) as error:
        failure = errors.http_failure(error)
    assert failure == {"schema": 1, "category": category, "http_status": status, "retry_at": retry_at}
    fields = errors.failure_fields(failure)
    assert fields.get("retry_at") == retry_at
    assert bool(fields.get("hint")) is (retry_at is not None)
    assert ("GitHub" in fields["error"]) is (category == "github-rate-limit")


def test_other_hosts_cannot_be_mislabeled_as_github(monkeypatch):
    monkeypatch.setattr(errors.time, "time", lambda: NOW)
    with http_error(403, {"X-RateLimit-Remaining": "0"}, url="https://learn.microsoft.com/items", reason="rate limit exceeded") as error:
        assert errors.http_failure(error)["category"] == "http-error"


def test_error_body_is_bounded_and_not_exposed():
    body = Mock(wraps=io.BytesIO(b"x" * (errors.MAX_ERROR_BODY_BYTES + 2)))
    error = http_error()
    error.fp = body
    error.read = body.read
    assert errors.http_failure(error)["category"] == "http-error"
    body.read.assert_called_once_with(errors.MAX_ERROR_BODY_BYTES + 1)


@pytest.mark.parametrize("read_error", [OSError("disconnected"), IncompleteRead(b"partial")])
def test_unreadable_error_body_does_not_hide_rate_limit_headers(read_error):
    with http_error(headers={"X-RateLimit-Remaining": "0"}) as error:
        error.read = Mock(side_effect=read_error)
        assert errors.http_failure(error)["category"] == "github-rate-limit"


@pytest.mark.parametrize("script", [update_db, update_icons])
@pytest.mark.parametrize("desktop", [False, True])
@pytest.mark.parametrize("locale", ["de", "en"])
def test_both_worker_entrypoints_report_http_failure_without_traceback_or_data_changes(monkeypatch, tmp_path, capsys, script, desktop, locale):
    from mcbe_editor.desktop_worker import worker_main

    paths = {
        "ITEM_DB_PATH": tmp_path / "item_db.json",
        "SOURCE_VERSION_JSON": tmp_path / "source_version.json",
        "SOURCE_VERSION_HISTORY": tmp_path / "source_version_history.json",
        "ICON_ROOT": tmp_path / "icons/vanilla",
        "CACHE_DIR": tmp_path / "cache",
    }
    for name, path in paths.items():
        monkeypatch.setattr(script, name, path, raising=False)
    manifest = paths["ICON_ROOT"] / "manifest.json"
    manifest.parent.mkdir(parents=True)
    stored = [paths["ITEM_DB_PATH"], paths["SOURCE_VERSION_JSON"], paths["SOURCE_VERSION_HISTORY"], manifest]
    for path in stored:
        path.write_bytes(b"previous fixture data")
    for env, path in {
        "MCBE_DATA_ROOT": tmp_path,
        "MCBE_ITEM_DB_PATH": paths["ITEM_DB_PATH"],
        "MCBE_SOURCE_VERSION_PATH": paths["SOURCE_VERSION_JSON"],
        "MCBE_SOURCE_VERSION_HISTORY_PATH": paths["SOURCE_VERSION_HISTORY"],
        "MCBE_ICON_CACHE_ROOT": paths["ICON_ROOT"],
        "MCBE_UPDATE_CACHE_DIR": paths["CACHE_DIR"],
    }.items():
        monkeypatch.setenv(env, str(path))
    monkeypatch.setenv("MCBE_UPDATE_LOCALE", locale)
    monkeypatch.delenv("MCBE_UPDATE_PROGRESS_PATH", raising=False)
    error = http_error(body=b'{"message":"API rate limit exceeded for private-ip-do-not-display"}')
    open_request = Mock(side_effect=error)
    monkeypatch.setattr("urllib.request.OpenerDirector.open", open_request)
    if desktop:
        output_path = tmp_path / "worker.log"
        code = worker_main(script.__name__, output_path, ["--dry-run"])
        output = output_path.read_text(encoding="utf-8")
    else:
        monkeypatch.setattr(sys, "argv", [script.__name__, "--dry-run"])
        monkeypatch.delitem(sys.modules, script.__name__)
        with pytest.raises(SystemExit) as result:
            runpy.run_module(script.__name__, run_name="__main__")
        code = result.value.code
        captured = capsys.readouterr()
        output = captured.out + captured.err
    assert code == 1
    visible, failure = errors.extract_http_failure(output)
    assert failure["category"] == "github-rate-limit"
    assert "HTTP 403" in visible and API_URL in visible
    assert ("GitHub request limit" if locale == "en" else "GitHub-Anfragelimit") in visible
    assert "Traceback" not in visible
    assert "private-ip-do-not-display" not in visible
    assert error.fp.closed
    assert open_request.call_count == 1  # No automatic retries.
    assert all(path.read_bytes() == b"previous fixture data" for path in stored)


def test_wrapped_download_failure_redacts_query_and_keeps_retry_hint(monkeypatch, capsys):
    monkeypatch.setattr(errors.time, "time", lambda: NOW)

    @errors.report_http_errors
    def download():
        try:
            raise http_error(503, {"Retry-After": "60"}, url="https://release-assets.githubusercontent.com/pack.zip?sig=secret#fragment")
        except OSError as exc:
            raise RuntimeError("Download failed") from exc

    assert download() == 1
    output, failure = errors.extract_http_failure(capsys.readouterr().out)
    assert "pack.zip: HTTP 503" in output
    assert "secret" not in output and "Traceback" not in output
    assert failure["retry_at"] == NOW + 60
    assert "UTC" in output


def test_unexpected_errors_still_propagate():
    @errors.report_http_errors
    def broken():
        raise TypeError("unexpected program error")

    with pytest.raises(TypeError, match="unexpected program error"):
        broken()


@pytest.mark.parametrize(
    "record",
    [None, [], {"schema": 1}, {"schema": 1, "category": "github-rate-limit", "http_status": 404}, {"schema": 1, "category": "http-error", "http_status": True}],
)
def test_malformed_records_remain_visible_without_claiming_known_failure(record):
    output = errors.ERROR_PREFIX + json.dumps(record) + "\nordinary output\n"
    assert errors.extract_http_failure(output) == (output, None)


def test_expired_retry_hint_is_omitted(monkeypatch):
    monkeypatch.setattr(errors.time, "time", lambda: NOW)
    fields = errors.failure_fields({"category": "github-rate-limit", "http_status": 403, "retry_at": NOW - 1})
    assert "hint" not in fields and "retry_at" not in fields


@pytest.mark.parametrize("script", [update_db, update_icons])
def test_release_download_failure_preserves_cache_and_reports_the_download_host(monkeypatch, tmp_path, capsys, script):
    cache = tmp_path / "cache"
    cache.mkdir()
    for name, path in {
        "CACHE_DIR": cache,
        "RELEASE_METADATA_PATH": cache / "release_metadata.json",
        "ITEM_DB_PATH": tmp_path / "item_db.json",
        "SOURCE_VERSION_JSON": tmp_path / "source_version.json",
        "SOURCE_VERSION_HISTORY": tmp_path / "source_version_history.json",
    }.items():
        monkeypatch.setattr(script, name, path, raising=False)
    info = {
        "resource_pack_release": "test",
        "resource_pack_asset": "bedrock-samples-test-full.zip",
        "resource_pack_asset_size": 512,
        "resource_pack_url": "https://github.com/Mojang/bedrock-samples/releases/download/test/bedrock-samples-test-full.zip",
    }
    lookup = "get_latest_release_info" if script is update_db else "get_latest_full_release_info"
    monkeypatch.setattr(script, lookup, lambda: info)
    monkeypatch.delenv("MCBE_ICON_DOWNLOAD_TEMP_DIR", raising=False)
    monkeypatch.delenv("MCBE_UPDATE_PROGRESS_PATH", raising=False)
    metadata = cache / "release_metadata.json"
    metadata.write_bytes(b"previous fixture metadata")
    previous = cache / ("bedrock_resource_pack.zip" if script is update_db else info["resource_pack_asset"])
    previous.write_bytes(b"previous fixture download")
    error = http_error(503, {"Retry-After": "60"}, url=info["resource_pack_url"])
    monkeypatch.setattr("urllib.request.OpenerDirector.open", Mock(side_effect=error))
    monkeypatch.setattr(sys, "argv", [script.__name__, "--force"])

    assert script.main() == 1

    visible, failure = errors.extract_http_failure(capsys.readouterr().out)
    assert failure["category"] == "http-error" and failure["http_status"] == 503
    assert "github.com/Mojang" in visible and "HTTP 503" in visible
    assert "Traceback" not in visible
    assert metadata.read_bytes() == b"previous fixture metadata"
    assert previous.read_bytes() == b"previous fixture download"
    assert not list(cache.glob("*.part")) and not list(cache.glob("*.candidate"))
