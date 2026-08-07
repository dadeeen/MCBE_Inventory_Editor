from __future__ import annotations

from pathlib import Path

from mcbe_editor import api_errors


def test_error_payload_has_stable_structure_and_legacy_alias() -> None:
    payload = api_errors.error_payload(
        "Ungültiger Slot: {slot}",
        code="invalid-slot",
        params={"slot": 7},
        details="Zusatzinfo",
    )

    assert payload == {
        "success": False,
        "code": "invalid_slot",
        "params": {"slot": 7},
        "message_key": "Ungültiger Slot: {slot}",
        "message": "Ungültiger Slot: 7",
        "error": "Ungültiger Slot: 7",
        "details": "Zusatzinfo",
    }


def test_error_payload_is_localized_for_request_but_keeps_source_key() -> None:
    import main

    with main.app.test_request_context("/", headers={"Accept-Language": "en"}):
        payload = api_errors.error_payload(
            "Ungültiger Slot: {slot}",
            code="invalid_slot",
            params={"slot": 4},
        )

    assert payload["message_key"] == "Ungültiger Slot: {slot}"
    assert payload["message"] == "Invalid slot: 4"
    assert payload["error"] == payload["message"]


def test_status_codes_have_stable_fallback_error_codes() -> None:
    assert api_errors.error_code_for_status(400) == "invalid_request"
    assert api_errors.error_code_for_status("409") == "conflict"
    assert api_errors.error_code_for_status(500) == "internal_server_error"
    assert api_errors.error_code_for_status("broken") == "request_failed"


def test_api_route_modules_do_not_build_legacy_only_error_payloads() -> None:
    root = Path(__file__).resolve().parents[1]
    paths = [root / "main.py", *sorted((root / "mcbe_editor").glob("*_api_routes.py"))]
    offenders = [path.name for path in paths if '"success": False, "error"' in path.read_text(encoding="utf-8")]
    assert not offenders, f"Use api_errors.error_payload or api_error in: {offenders}"
