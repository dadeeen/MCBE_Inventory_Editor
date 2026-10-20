from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
from flask import Response

from mcbe_editor import browser_launch
from tests.test_local_server_cli import running_server, server_app


@pytest.mark.parametrize("host", ["192.0.2.1", "example.invalid", "fe80::1"])
def test_existing_editor_probe_never_connects_to_non_loopback(host, monkeypatch):
    connection = Mock()
    monkeypatch.setattr(browser_launch, "HTTPConnection", connection)
    assert browser_launch.existing_editor_url(host, 5000) is None
    connection.assert_not_called()


@pytest.mark.parametrize("status,marker", [(200, None), (200, "different"), (302, "1"), (500, "1")])
def test_existing_editor_probe_rejects_foreign_services_and_redirects(status, marker):
    app = server_app()

    @app.get("/healthz")
    def health():
        headers = {"Location": "http://example.invalid/"}
        if marker:
            headers["X-MCBE-Editor"] = marker
        return Response("ok", status=status, headers=headers)

    with running_server(app) as (_, port, _thread):
        assert browser_launch.existing_editor_url("127.0.0.1", port) is None


def test_existing_editor_probe_is_bounded_and_closes_failed_connections(monkeypatch):
    connection = Mock()
    connection.request.side_effect = TimeoutError("busy")
    factory = Mock(return_value=connection)
    monkeypatch.setattr(browser_launch, "HTTPConnection", factory)
    assert browser_launch.existing_editor_url("127.0.0.1", 5000) is None
    factory.assert_called_once_with("127.0.0.1", 5000, timeout=2)
    connection.close.assert_called_once()


def test_existing_editor_probe_ignores_proxies(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    app = server_app()
    app.add_url_rule("/healthz", view_func=lambda: Response("ok", headers={"X-MCBE-Editor": "1"}))
    with running_server(app) as (_, port, _thread):
        assert browser_launch.existing_editor_url("0.0.0.0", port) == f"http://127.0.0.1:{port}/?already_running=1"


@pytest.mark.parametrize("host,expected", [("::", "[::1]"), ("::1", "[::1]"), ("0.0.0.0", "127.0.0.1")])
def test_browser_url_preserves_ipv6_and_maps_wildcards(host, expected):
    assert browser_launch.browser_url(host, 5010) == f"http://{expected}:5010/"


def test_health_check_identifies_editor_without_exposing_runtime_details():
    import main

    with main.app.test_client() as client:
        response = client.get("/healthz")
    assert response.headers["X-MCBE-Editor"] == "1"
    assert response.json == {"success": True, "status": "ok"}


@pytest.mark.parametrize("editor,exit_code", [(True, 0), (False, 1)])
def test_cli_second_start_reuses_only_an_identified_editor(tmp_path, editor, exit_code):
    app = server_app()
    headers = {"X-MCBE-Editor": "1"} if editor else {}
    app.add_url_rule("/healthz", view_func=lambda: Response("ok", headers=headers))
    app_root = Path(__file__).resolve().parents[1]
    env = {key: value for key, value in os.environ.items() if not key.startswith("MCBE_")}
    env.update(
        {
            "MCBE_EDITOR_MODE": "local",
            "MCBE_DATA_ROOT": str(tmp_path / "data"),
            "MCBE_BACKUP_ROOT": str(tmp_path / "backups"),
            "MCBE_WORLDS_ROOT": str(tmp_path / "no-worlds"),
            "MCBE_READ_ONLY": "true",
            "MCBE_STARTUP_SECURITY_REPORT": "false",
        }
    )
    with running_server(app) as (_, port, _thread):
        result = subprocess.run(
            [sys.executable, "-X", "utf8", "main.py", "--host=127.0.0.1", f"--port={port}", "--no-browser"],
            cwd=app_root,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=20,
            check=False,
        )
        assert result.returncode == exit_code, result.stderr
        assert ("Der Editor läuft bereits" in result.stdout) is editor
        assert "beende" in result.stdout
        assert "Traceback" not in result.stderr
        # The duplicate start leaves the original server running.
        assert bool(browser_launch.existing_editor_url("127.0.0.1", port)) is editor
