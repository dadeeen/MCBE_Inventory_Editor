import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

from mcbe_editor import update_progress
from mcbe_editor.setup_state import FirstRunSetup


def test_child_process_progress_is_visible_before_process_exits_and_removed_afterward(tmp_path):
    progress_id = "a" * 32
    with update_progress.track_progress(tmp_path, progress_id) as path:
        env = {**os.environ, update_progress.PROGRESS_ENV: str(path)}
        script = (
            "from mcbe_editor.update_progress import report_progress; "
            "report_progress('downloading', current=250, total=1000, unit='bytes'); "
            "print('ready', flush=True); input()"
        )
        with subprocess.Popen(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ) as child:
            try:
                assert child.stdout.readline().strip() == "ready"
                assert child.poll() is None
                assert update_progress.read_progress(tmp_path, progress_id) == {
                    "phase": "downloading",
                    "current": 250,
                    "total": 1000,
                    "unit": "bytes",
                }
                child.communicate("\n", timeout=10)
                assert child.returncode == 0
            finally:
                if child.poll() is None:
                    child.kill()
    assert update_progress.read_progress(tmp_path, progress_id) is None


def test_progress_is_exclusive_and_failure_cleans_up_only_its_own_snapshot(tmp_path):
    first_id, second_id = "a" * 32, "b" * 32
    with update_progress.track_progress(tmp_path, first_id):
        with pytest.raises(ValueError, match="bereits"), update_progress.track_progress(tmp_path, first_id):
            pytest.fail("Duplicate tracker must not start")
        with pytest.raises(RuntimeError, match="update failed"), update_progress.track_progress(tmp_path, second_id):
            raise RuntimeError("update failed")
        assert update_progress.read_progress(tmp_path, first_id) == {"phase": "waiting"}
        assert update_progress.read_progress(tmp_path, second_id) is None


def test_progress_file_name_is_the_validated_id(tmp_path):
    for progress_id in ("0" * 31 + "1", "f" * 32):
        assert update_progress.progress_path(tmp_path, progress_id) == tmp_path / f"{progress_id}.json"
    # int() alone would accept upper case, underscores and whitespace; the ID check must reject them first.
    for invalid in ("A" * 32, "a" * 30 + "_1", " " + "a" * 31, "../" + "a" * 29, "a" * 31, "a" * 33):
        with pytest.raises(ValueError, match="Ungültige"):
            update_progress.progress_path(tmp_path, invalid)


def test_progress_storage_errors_do_not_abort_updates(tmp_path, monkeypatch):
    monkeypatch.setattr(update_progress, "ensure_private_directory", lambda _path: (_ for _ in ()).throw(OSError("disk unavailable")))
    with update_progress.track_progress(tmp_path, "a" * 32) as path:
        assert path is None
    monkeypatch.setenv(update_progress.PROGRESS_ENV, str(tmp_path / "snapshot.json"))
    monkeypatch.setattr(update_progress, "atomic_write_private_text", lambda *_args: (_ for _ in ()).throw(OSError("disk full")))
    update_progress.report_progress("checking")


@pytest.fixture
def progress_app(monkeypatch, tmp_path):
    import main

    monkeypatch.setattr(
        main,
        "APP_CONFIG",
        replace(
            main.APP_CONFIG,
            mode="local",
            host="127.0.0.1",
            data_root=str(tmp_path),
            auth_required=False,
            auth_password=None,
            auth_password_hash=None,
            read_only=False,
        ),
    )
    monkeypatch.setattr(main, "RUNTIME_BIND_HOST", "127.0.0.1")
    monkeypatch.setattr(main, "SETUP_STATE", FirstRunSetup(tmp_path / "setup.json"))
    monkeypatch.setattr(main, "CSRF_TOKEN", "progress-test-token")
    return main


@pytest.mark.parametrize(
    "endpoint,module_name,handler_name",
    [
        ("/api/update_db", "item_db_api_routes", "update_db"),
        ("/api/icons/vanilla/update", "icon_api_routes", "icons_vanilla_update"),
    ],
)
def test_progress_can_be_polled_while_post_runs_and_keeps_failed_result(progress_app, monkeypatch, endpoint, module_name, handler_name):
    main = progress_app
    started, release = threading.Event(), threading.Event()
    progress_id = "c" * 32

    def update(_data, _deps):
        update_progress.write_progress(main.g.update_progress_path, "validating")
        started.set()
        assert release.wait(10)
        return main.jsonify({"success": False, "error": "Broken archive"}), 500

    monkeypatch.setattr(getattr(main, module_name), handler_name, update)

    def post():
        with main.app.test_client() as client:
            return client.post(endpoint, json={}, headers={"X-CSRF-Token": main.CSRF_TOKEN, update_progress.PROGRESS_HEADER: progress_id})

    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(post)
        try:
            assert started.wait(10)
            response = main.app.test_client().get(f"/api/update_progress/{progress_id}")
            assert response.status_code == 200
            assert response.headers["Cache-Control"] == "no-store"
            assert response.get_json()["progress"] == {"phase": "validating"}
            assert not result.done()
        finally:
            release.set()
        assert result.result(timeout=10).status_code == 500
    assert main.app.test_client().get(f"/api/update_progress/{progress_id}").get_json()["progress"] is None


def test_progress_routes_keep_auth_csrf_and_read_only_guards(progress_app, monkeypatch):
    main = progress_app
    headers = {"X-CSRF-Token": main.CSRF_TOKEN, update_progress.PROGRESS_HEADER: "d" * 32}
    client = main.app.test_client()
    assert client.get("/api/update_progress/invalid").status_code == 400
    for endpoint in ("/api/update_db", "/api/icons/vanilla/update"):
        assert client.post(endpoint, json={}, headers={update_progress.PROGRESS_HEADER: "d" * 32}).status_code == 403
        invalid = {**headers, update_progress.PROGRESS_HEADER: "../outside"}
        assert client.post(endpoint, json={}, headers=invalid).status_code == 400
    monkeypatch.setattr(main, "APP_CONFIG", replace(main.APP_CONFIG, read_only=True))
    for endpoint in ("/api/update_db", "/api/icons/vanilla/update"):
        assert client.post(endpoint, json={}, headers=headers).status_code == 403
    monkeypatch.setattr(main, "APP_CONFIG", replace(main.APP_CONFIG, auth_required=True, auth_password="configured-password"))
    assert client.get("/api/update_progress/" + "d" * 32).status_code == 401
    assert not list(main._update_progress_directory().glob("*.json"))
