"""Malformed CSRF tokens must produce ordinary HTTP rejection responses."""
from dataclasses import replace

import pytest


@pytest.mark.parametrize("path", ["setup", "login", "api_header", "api_form"])
@pytest.mark.parametrize("submitted", ["ä", "", "wrong-token", "valid"])
def test_csrf_tokens_through_real_http_routes(monkeypatch, path, submitted):
    import main

    monkeypatch.setattr(main, "first_run_setup_required", lambda: path == "setup")
    monkeypatch.setattr(main, "auth_enabled", lambda: path == "login")
    monkeypatch.setattr(main, "APP_CONFIG", replace(main.APP_CONFIG, auth_required=path == "login", auth_username="admin", auth_password="secret"))
    monkeypatch.setattr(main, "CSRF_TOKEN", "expected-token")
    client = main.app.test_client()
    expected = "expected-token"
    if path in {"setup", "login"}:
        assert client.get("/" + path).status_code == 200
        with client.session_transaction() as session:
            expected = session["setup_csrf_token" if path == "setup" else "csrf_token"]
    token = expected if submitted == "valid" else submitted
    if path == "setup":
        response = client.post("/setup", data={"_setup_token": token})
        assert response.status_code == 200
        assert ("Ungültiges Setup-Token" in response.get_data(as_text=True)) is (submitted != "valid")
    elif path == "login":
        response = client.post("/login", data={"_csrf_token": token, "username": "admin", "password": "secret"})
        assert response.status_code == (302 if submitted == "valid" else 200)
        if submitted != "valid":
            assert "Ungültiges Login-Token" in response.get_data(as_text=True)
    else:
        kwargs = {"headers": {"X-CSRF-Token": token}, "json": {}} if path == "api_header" else {"data": {"_csrf_token": token}}
        response = client.post("/api/player/load", **kwargs)
        if submitted == "valid":
            assert response.status_code < 500 and response.status_code != 403
        else:
            assert response.status_code == 403
            assert response.get_json()["code"] == "invalid_csrf_token"
