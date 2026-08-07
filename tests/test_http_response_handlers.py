from types import SimpleNamespace

from mcbe_editor import http_response_handlers


def _jsonify(payload):
    return ("json", payload)


def test_add_security_headers_sets_defaults_without_overwriting_existing_values():
    response = SimpleNamespace(headers={"X-Frame-Options": "SAMEORIGIN"})

    result = http_response_handlers.add_security_headers(response)

    assert result is response
    assert response.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "same-origin"
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]


def test_locale_vary_headers_preserve_existing_values():
    response = SimpleNamespace(headers={"Vary": "Origin"})

    result = http_response_handlers.add_locale_vary_headers(response)

    assert result is response
    assert response.headers["Vary"] == "Accept-Language, Cookie, Origin"


def test_error_handlers_return_json_payloads_with_expected_status_codes():
    for response, status, code, message in (
        (http_response_handlers.request_too_large(_jsonify), 413, "request_too_large", "Upload/Anfrage ist zu groß."),
        (http_response_handlers.not_found(_jsonify), 404, "not_found", "Seite nicht gefunden."),
        (http_response_handlers.server_error(_jsonify), 500, "internal_server_error", "Interner Serverfehler"),
    ):
        (kind, payload), actual_status = response
        assert kind == "json"
        assert actual_status == status
        assert payload["code"] == code
        assert payload["message_key"] == message
        assert payload["message"] == message
        assert payload["error"] == message
