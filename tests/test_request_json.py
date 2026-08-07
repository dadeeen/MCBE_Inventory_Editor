from __future__ import annotations

from unittest.mock import patch

import main


def _client():
    main.app.testing = True
    return main.app.test_client()


def test_malformed_json_does_not_start_vanilla_icon_update():
    with patch.object(main, "CSRF_TOKEN", "json-token"), patch.object(main, "run_update_icons", return_value=(0, "called")) as runner:
        response = _client().post(
            "/api/icons/vanilla/update",
            data='{"force":',
            content_type="application/json",
            headers={"X-CSRF-Token": "json-token"},
        )

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["success"] is False
    assert payload["code"] == "invalid_request"
    assert payload["message_key"] == "Der Anfragekörper muss ein gültiges JSON-Objekt sein."
    assert payload["error"] == payload["message"] == payload["message_key"]
    runner.assert_not_called()


def test_json_array_does_not_start_item_database_update():
    with patch.object(main, "CSRF_TOKEN", "json-token"), patch.object(main, "run_update_db", return_value=(0, "called")) as runner:
        response = _client().post(
            "/api/update_db",
            json=[{"dry_run": True}],
            headers={"X-CSRF-Token": "json-token"},
        )

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["success"] is False
    assert payload["code"] == "invalid_request"
    assert payload["message_key"] == "Der Anfragekörper muss ein gültiges JSON-Objekt sein."
    assert payload["error"] == payload["message"] == payload["message_key"]
    runner.assert_not_called()


def test_non_json_payload_is_rejected_before_mutating_handler_runs():
    with patch.object(main, "CSRF_TOKEN", "json-token"), patch.object(main, "run_update_icons", return_value=(0, "called")) as runner:
        response = _client().post(
            "/api/icons/vanilla/update",
            data="force=true",
            content_type="text/plain",
            headers={"X-CSRF-Token": "json-token"},
        )

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["success"] is False
    assert payload["code"] == "invalid_request"
    assert payload["message_key"] == "Der Anfragekörper muss als JSON gesendet werden."
    assert payload["error"] == payload["message"] == payload["message_key"]
    runner.assert_not_called()


def test_empty_body_remains_valid_for_defaulted_update_options():
    with patch.object(main, "CSRF_TOKEN", "json-token"), patch.object(main, "run_update_db", return_value=(0, "dry-run")) as runner:
        response = _client().post(
            "/api/update_db",
            data=b"",
            headers={"X-CSRF-Token": "json-token"},
        )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["output"] == "dry-run"
    runner.assert_called_once_with(dry_run=True, force=False, only=None, use_cache=True)


def test_invalid_vanilla_icon_update_boolean_is_a_client_error():
    with patch.object(main, "CSRF_TOKEN", "json-token"), patch.object(main, "run_update_icons", return_value=(0, "called")) as runner:
        response = _client().post(
            "/api/icons/vanilla/update",
            json={"force": {"not": "a boolean"}},
            headers={"X-CSRF-Token": "json-token"},
        )

    assert response.status_code == 400
    assert "boolescher Wert" in response.get_json()["error"]
    runner.assert_not_called()


def test_invalid_icon_scan_world_path_type_is_a_client_error():
    with patch.object(main, "CSRF_TOKEN", "json-token"), patch.object(main.icon_api_routes, "_scan_and_store_icons") as scanner:
        response = _client().post(
            "/api/icons/scan",
            json={"world_path": ["not", "a", "path"]},
            headers={"X-CSRF-Token": "json-token"},
        )

    assert response.status_code == 400
    assert "Textwert" in response.get_json()["error"]
    scanner.assert_not_called()
