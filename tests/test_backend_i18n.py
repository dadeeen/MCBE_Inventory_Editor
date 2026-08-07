"""Backend message translation: request-locale resolution and response funnels.

The pytest suite pins the Flask test client to German (see conftest), so these
tests opt in to English explicitly via Accept-Language or the locale cookie.
"""

from __future__ import annotations

from mcbe_editor import i18n


def test_translate_uses_catalog_for_english():
    assert i18n.translate("Seite nicht gefunden.", "en") == "Page not found."
    assert i18n.translate("Seite nicht gefunden.", "de") == "Seite nicht gefunden."


def test_translate_substitutes_params_after_lookup():
    text = i18n.translate("Ungültiger Slot: {slot}", "en", {"slot": 7})
    assert text == "Invalid slot: 7"


def test_t_outside_request_context_falls_back_to_german():
    assert i18n.t("Seite nicht gefunden.") == "Seite nicht gefunden."


def test_t_unknown_text_passes_through_unchanged():
    assert i18n.t("Völlig unbekannter Text 12345") == "Völlig unbekannter Text 12345"


def test_request_locale_prefers_cookie_over_accept_language():
    import main

    with main.app.test_request_context("/", headers={"Accept-Language": "en"}, environ_base={"HTTP_COOKIE": f"{i18n.LOCALE_COOKIE_NAME}=de"}):
        assert i18n.request_locale() == "de"
    with main.app.test_request_context("/", headers={"Accept-Language": "de-DE,de;q=0.9"}):
        assert i18n.request_locale() == "de"
    with main.app.test_request_context("/"):
        assert i18n.request_locale() == i18n.DEFAULT_LOCALE


def test_resolve_locale_honors_accept_language_quality_and_rejections():
    assert i18n.resolve_locale(None, "de;q=0.2, en-US;q=0.9") == "en"
    assert i18n.resolve_locale(None, "fr-FR, de;q=0, en;q=0.8") == "en"
    assert i18n.resolve_locale(None, "fr-FR, *;q=0.5") == i18n.DEFAULT_LOCALE
    assert i18n.resolve_locale(None, "en;q=broken, de;q=0.4") == "de"
    assert i18n.resolve_locale(None, "*;q=0.9, en;q=0") == "de"
    assert i18n.resolve_locale(None, "*;q=0.9, de;q=0.5, en;q=0") == "de"
    assert i18n.resolve_locale("de", "en;q=1") == "de"


def test_api_404_message_is_translated_per_request_locale():
    import main

    with main.app.test_client() as client:
        german = client.get("/api/definitely-missing").get_json()
        english = client.get("/api/definitely-missing", headers={"Accept-Language": "en"}).get_json()

    assert german["error"] == "Seite nicht gefunden."
    assert english["error"] == "Page not found."
    assert german["code"] == english["code"] == "not_found"
    assert english["message_key"] == "Seite nicht gefunden."
    assert english["params"] == {}


def test_server_status_payload_is_translated_per_request_locale():
    from unittest.mock import patch

    import main

    status = {"status": "online", "message": "Server erreichbar.", "server_name": "Bedrock"}
    gate = {
        "allowed": False,
        "read_allowed": True,
        "reason": "Server läuft noch. Bitte Server stoppen.",
        "server_status": status,
    }
    with (
        patch("main.check_server_status", return_value=status),
        patch("main.write_gate", return_value=gate),
        main.app.test_client() as client,
    ):
        english = client.get("/api/server_status", headers={"Accept-Language": "en"}).get_json()

    assert english["server_status"]["message"] == "Server reachable."
    assert english["write_gate"]["reason"] == "The server is still running. Please stop the server."


def test_structured_server_probe_error_is_translated_per_request_locale():
    from unittest.mock import patch

    import main

    status = {
        "status": "unknown",
        "message": "Serverstatus unbekannt: Serveradresse konnte nicht aufgelöst werden.",
        "message_key": "Serverstatus unbekannt: Serveradresse konnte nicht aufgelöst werden.",
        "message_params": {},
        "technical_error": "Der angegebene Host ist unbekannt.",
        "server_status_revision": 41,
    }
    gate = {
        "allowed": False,
        "read_allowed": True,
        "reason": "Serverstatus unbekannt. Bitte bestätige vor dem Schreiben ausdrücklich, dass der Server gestoppt ist.",
        "server_status": status,
    }
    with (
        patch("main.check_server_status", return_value=status),
        patch("main.write_gate", return_value=gate),
        main.app.test_client() as client,
    ):
        english = client.get("/api/server_status", headers={"Accept-Language": "en"}).get_json()

    assert english["server_status"]["message"] == "Server status unknown: server address could not be resolved."
    assert english["server_status"]["message_key"] == status["message_key"]
    assert english["server_status"]["message_params"] == {}
    assert english["server_status"]["technical_error"] == "Der angegebene Host ist unbekannt."
    assert english["server_status_revision"] == 41


def test_write_block_response_localizes_nested_server_status() -> None:
    import main

    status = {
        "status": "unknown",
        "message": "Kein Minecraft-Server konfiguriert.",
        "message_key": "Kein Minecraft-Server konfiguriert.",
        "message_params": {},
    }
    gate = {
        "allowed": False,
        "read_allowed": True,
        "reason": "Serverstatus unbekannt. Bitte bestätige vor dem Schreiben ausdrücklich, dass der Server gestoppt ist.",
        "requires_unknown_server_confirmation": True,
        "server_status": status,
    }

    with main.app.test_request_context("/", headers={"Accept-Language": "en"}):
        response, response_status = main.write_block_response(gate)
        payload = response.get_json()

    assert response_status == 409
    assert payload["write_gate"]["reason"] == "Server status unknown. Please explicitly confirm before writing that the server is stopped."
    assert payload["write_gate"]["server_status"]["message"] == "No Minecraft server configured."
    assert payload["write_gate"]["server_status"]["message_key"] == status["message_key"]


def test_test_client_defaults_to_german_source_language():
    import main

    with main.app.test_client() as client:
        payload = client.get("/api/definitely-missing").get_json()
    assert payload["error"] == "Seite nicht gefunden."


def test_localized_responses_vary_by_locale_but_static_assets_do_not():
    import main

    with main.app.test_client() as client:
        html_response = client.get("/")
        json_response = client.get("/api/definitely-missing")
        static_response = client.get("/static/i18n.js")

    assert html_response.headers.get("Vary") == "Accept-Language, Cookie"
    assert json_response.headers.get("Vary") == "Accept-Language, Cookie"
    assert "Accept-Language" not in static_response.headers.get("Vary", "")
    assert "Cookie" not in static_response.headers.get("Vary", "")
