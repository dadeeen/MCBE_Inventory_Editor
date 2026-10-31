"""Read jobs survive HTTP retries without weakening world or session guards."""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import time
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from mcbe_editor import read_operation
from mcbe_editor.world_read_jobs import ReadJobError, WorldReadJobs

IDENTIFIER = "a" * 32
OWNER = "synthetic-session-token"


def _finished(jobs, identifier=IDENTIFIER, owner=OWNER):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        result, status = jobs.poll(identifier, owner)
        if status != 202:
            return result, status
        time.sleep(0.01)
    pytest.fail("Read job did not finish")


def test_progress_retries_and_cross_manager_polling_share_one_job(tmp_path):
    jobs = WorldReadJobs(tmp_path)
    other_worker = WorldReadJobs(tmp_path)
    entered, release, closed = Event(), Event(), Event()
    calls = []

    def work():
        calls.append(1)
        try:
            read_operation.checkpoint("scanning", current=512)
            entered.set()
            assert release.wait(5)
            return {"success": True, "players": [{"label": "Synthetic"}]}, 200
        finally:
            closed.set()

    try:
        first, status = jobs.start(IDENTIFIER, OWNER, "/synthetic/world", work)
        assert status == 202 and first["pending"]
        assert entered.wait(5)
        progress, status = other_worker.start(IDENTIFIER, OWNER, "/synthetic/world", work)
        assert status == 202
        assert progress["progress"]["phase"] == "scanning"
        assert progress["progress"]["current"] == 512
        assert calls == [1]
        stored = (tmp_path / f"{IDENTIFIER}.json").read_text()
        assert OWNER not in stored and "/synthetic/world" not in stored
        if os.name != "nt":
            assert (tmp_path / f"{IDENTIFIER}.json").stat().st_mode & 0o777 == 0o600
    finally:
        release.set()
        assert closed.wait(5)
    result, status = _finished(other_worker)
    assert status == 200 and result["players"][0]["label"] == "Synthetic"
    assert jobs.start(IDENTIFIER, OWNER, "/synthetic/world", work) == (result, status)
    assert calls == [1]


@pytest.mark.parametrize(
    "identifier",
    [
        "",
        "../" + IDENTIFIER,
        "..\\" + IDENTIFIER,
        "C:\\synthetic\\" + IDENTIFIER,
        IDENTIFIER + ".json",
        "A" * 32,
        "ａ" * 32,
        "a" * 31 + "\0",
        IDENTIFIER + "\n",
        "a" * 31,
        "a" * 33,
        "g" * 32,
    ],
    ids=["empty", "parent-posix", "parent-windows", "absolute", "suffix", "uppercase", "unicode", "nul", "newline", "short", "long", "nonhex"],
)
def test_invalid_identifiers_are_rejected_before_filesystem_work(tmp_path, monkeypatch, identifier):
    from mcbe_editor import world_read_jobs

    directory = tmp_path / "reads"
    jobs = WorldReadJobs(directory)

    def unexpected(*_args, **_kwargs):
        pytest.fail("Invalid read identifier reached filesystem or worker")

    with monkeypatch.context() as filesystem:
        filesystem.setattr(world_read_jobs, "ensure_private_directory", unexpected)
        filesystem.setattr(jobs, "_lock", unexpected)
        filesystem.setattr(Path, "stat", unexpected)
        filesystem.setattr(Path, "open", unexpected)
        for action in (
            lambda: jobs.start(identifier, OWNER, "read", unexpected),
            lambda: jobs.poll(identifier, OWNER),
            lambda: jobs.poll(identifier, OWNER, cancel=True),
        ):
            with pytest.raises(ReadJobError) as error:
                action()
            assert (error.value.status, error.value.code) == (400, "invalid_read_id")
    assert not directory.exists()


@pytest.mark.parametrize("identifier", ["0" * 32, "0" * 31 + "1", "f" * 32], ids=["zero", "leading-zeroes", "maximum"])
def test_boundary_identifiers_resume_existing_files_without_changing_read_ids(tmp_path, identifier):
    jobs = WorldReadJobs(tmp_path)
    now = time.time()
    stored = {
        "owner": jobs._owner(OWNER),
        "identity": hashlib.sha256(b"read").hexdigest(),
        "generation": "synthetic-existing-worker",
        "state": "running",
        "created": now,
        "observed": now,
        "updated": now,
        "phase": "scanning",
        "current": 512,
    }
    # Use the established filename directly, independently of the path builder.
    path = tmp_path / f"{identifier}.json"
    path.write_text(json.dumps(stored), encoding="utf-8")
    pending, status = jobs.start(identifier, OWNER, "read", lambda: pytest.fail("existing scan started again"))
    assert status == 202 and pending["read_id"] == identifier
    assert jobs.poll(identifier, OWNER)[0]["read_id"] == identifier
    assert set(tmp_path.glob("*.json")) == {path}

    result = {"success": True, "players": [{"label": "Synthetic existing result"}]}
    stored.update(state="done", finished=time.time(), result=result, status=200)
    path.write_text(json.dumps(stored), encoding="utf-8")
    before = path.read_bytes()
    restarted = WorldReadJobs(tmp_path)
    assert restarted.start(identifier, OWNER, "read", lambda: pytest.fail("completed scan started again")) == (result, 200)
    assert restarted.poll(identifier, OWNER) == (result, 200)
    assert path.read_bytes() == before


def test_session_scope_and_capacity(tmp_path):
    jobs = WorldReadJobs(tmp_path, limit=1)
    release = Event()

    def work():
        assert release.wait(5)
        return {"success": True}, 200

    try:
        jobs.start(IDENTIFIER, OWNER, "read", work)
        for action in [lambda: jobs.poll(IDENTIFIER, "foreign"), lambda: jobs.poll(IDENTIFIER, "foreign", cancel=True)]:
            with pytest.raises(ReadJobError) as error:
                action()
            assert error.value.status == 404
        with pytest.raises(ReadJobError) as error:
            jobs.start(IDENTIFIER, OWNER, "different-world", work)
        assert error.value.status == 409
        with pytest.raises(ReadJobError) as error:
            jobs.start("b" * 32, OWNER, "read", work)
        assert error.value.status == 429
    finally:
        release.set()
    assert _finished(jobs)[1] == 200


@pytest.mark.parametrize("stop", ["cancel", "lease", "timeout"])
def test_stopped_read_closes_resources_and_releases_capacity(tmp_path, stop):
    jobs = WorldReadJobs(tmp_path, limit=1, timeout=0.15 if stop == "timeout" else 10, lease=0.15 if stop == "lease" else 10)
    closed, entered = Event(), Event()

    def work():
        try:
            entered.set()
            while True:
                read_operation.checkpoint("scanning")
                time.sleep(0.01)
        finally:
            closed.set()

    jobs.start(IDENTIFIER, OWNER, "read", work)
    assert entered.wait(5)
    if stop == "cancel":
        assert jobs.poll(IDENTIFIER, OWNER, cancel=True)[1] == 408
    assert closed.wait(5)
    result, status = _finished(jobs)
    assert status == 408
    assert result["code"] == ("read_timeout" if stop == "timeout" else "read_cancelled")
    # The worker's finally follows the callback's finally.
    deadline = time.monotonic() + 5
    while True:
        try:
            jobs.start("b" * 32, OWNER, "next", lambda: ({"success": True}, 200))
            break
        except ReadJobError:
            assert time.monotonic() < deadline
            time.sleep(0.01)
    assert _finished(jobs, "b" * 32)[1] == 200


def test_completed_results_expire_and_errors_do_not_expose_exceptions(tmp_path):
    jobs = WorldReadJobs(tmp_path)

    def fail():
        raise RuntimeError("/private/synthetic-path")

    jobs.start(IDENTIFIER, OWNER, "read", fail)
    result, status = _finished(jobs)
    assert status == 500 and result == {"success": False, "code": "read_job_failed"}
    path = tmp_path / f"{IDENTIFIER}.json"
    data = json.loads(path.read_text())
    data["finished"] -= 120
    path.write_text(json.dumps(data))
    with pytest.raises(ReadJobError) as error:
        jobs.poll(IDENTIFIER, OWNER)
    assert error.value.status == 404 and not path.exists()


def test_stalled_worker_times_out_even_while_client_keeps_polling(tmp_path):
    jobs = WorldReadJobs(tmp_path)
    entered, release = Event(), Event()

    def work():
        entered.set()
        release.wait(5)
        return {"success": True}, 200

    try:
        jobs.start(IDENTIFIER, OWNER, "read", work)
        assert entered.wait(5)
        path = tmp_path / f"{IDENTIFIER}.json"
        with jobs._lock():
            data = json.loads(path.read_text())
            data["updated"] -= 46
            jobs._write(path, data)
        result, status = jobs.poll(IDENTIFIER, OWNER)
        assert status == 408 and result["code"] == "read_timeout"
    finally:
        release.set()


def test_expired_worker_cannot_publish_over_reused_identifier(tmp_path):
    jobs = WorldReadJobs(tmp_path)
    entered, release_old, release_new, old_returned = Event(), Event(), Event(), Event()

    def old_work():
        entered.set()
        release_old.wait(5)
        old_returned.set()
        return {"success": True, "generation": "old"}, 200

    def new_work():
        release_new.wait(5)
        return {"success": True, "generation": "new"}, 200

    try:
        jobs.start(IDENTIFIER, OWNER, "read", old_work)
        assert entered.wait(5)
        jobs.poll(IDENTIFIER, OWNER, cancel=True)
        path = tmp_path / f"{IDENTIFIER}.json"
        with jobs._lock():
            data = json.loads(path.read_text())
            data["finished"] -= 120
            data["cancel_until"] = time.time() - 1
            jobs._write(path, data)
        with pytest.raises(ReadJobError):
            jobs.poll(IDENTIFIER, OWNER)
        assert jobs.start(IDENTIFIER, OWNER, "read", new_work)[1] == 202
        release_old.set()
        assert old_returned.wait(5)
        time.sleep(0.05)
        assert jobs.poll(IDENTIFIER, OWNER)[1] == 202
    finally:
        release_old.set()
        release_new.set()
    assert _finished(jobs) == ({"success": True, "generation": "new"}, 200)


def _process_read(directory, started, release, finished):
    jobs = WorldReadJobs(directory)

    def work():
        started.set()
        release.wait(10)
        return {"success": True, "source": "first-process"}, 200

    jobs.start(IDENTIFIER, OWNER, "read", work)
    while jobs.poll(IDENTIFIER, OWNER)[1] == 202:
        time.sleep(0.01)
    finished.set()


def test_another_process_can_resume_and_collect_the_same_read(tmp_path):
    context = multiprocessing.get_context("spawn")
    started, release, finished = context.Event(), context.Event(), context.Event()
    process = context.Process(target=_process_read, args=(tmp_path, started, release, finished))
    process.start()
    try:
        assert started.wait(10)
        jobs = WorldReadJobs(tmp_path)
        assert jobs.start(IDENTIFIER, OWNER, "read", lambda: pytest.fail("duplicate scan"))[1] == 202
        release.set()
        assert finished.wait(10)
        assert _finished(jobs) == ({"success": True, "source": "first-process"}, 200)
    finally:
        release.set()
        process.join(10)
        if process.is_alive():
            process.terminate()
            process.join(5)
    assert process.exitcode == 0


@pytest.fixture
def job_api(tmp_path, monkeypatch):
    import main

    jobs = WorldReadJobs(tmp_path / "reads")
    monkeypatch.setattr(main, "WORLD_READ_JOBS", jobs)
    monkeypatch.setattr(main, "CSRF_TOKEN", OWNER)
    monkeypatch.setattr(main, "auth_enabled", lambda: False)
    return main, jobs, main.app.test_client()


@pytest.mark.parametrize(
    "method,endpoint,manager_method",
    [
        ("POST", "/api/players", "start"),
        ("POST", "/api/player/load", "start"),
        ("GET", f"/api/world_reads/{IDENTIFIER}", "poll"),
        ("DELETE", f"/api/world_reads/{IDENTIFIER}", "poll"),
    ],
    ids=["players", "player-load", "poll", "cancel"],
)
@pytest.mark.parametrize(
    "code,expected_code,status,german,english",
    [
        ("invalid_read_id", "invalid_read_id", 400, "Ungültige Lade-ID.", "Invalid load ID."),
        (
            "read_job_expired",
            "read_job_expired",
            404,
            "Der Ladevorgang ist abgelaufen. Lade die Welt erneut.",
            "The load operation has expired. Load the world again.",
        ),
        (
            "read_id_conflict",
            "read_id_conflict",
            409,
            "Diese Lade-ID gehört zu einer anderen Anfrage.",
            "This load ID belongs to a different request.",
        ),
        (
            "read_jobs_busy",
            "read_jobs_busy",
            429,
            "Die Kapazität für Leseaufträge ist belegt. Versuche es gleich erneut.",
            "Read operation capacity is full. Try again shortly.",
        ),
        (
            "synthetic_private_code",
            "read_job_failed",
            500,
            "Der Lesevorgang konnte nicht abgeschlossen werden. Lade die Welt erneut.",
            "The read operation could not be completed. Load the world again.",
        ),
    ],
    ids=["invalid", "expired", "conflict", "busy", "unknown"],
)
def test_read_job_http_errors_expose_only_the_localized_public_contract(
    job_api, monkeypatch, method, endpoint, manager_method, code, expected_code, status, german, english
):
    _main, jobs, client = job_api

    def fail(*_args, **_kwargs):
        raise ReadJobError("Sensitive synthetic exception at /private/synthetic/read.json", 599, code) from RuntimeError(
            "Sensitive synthetic cause at C:\\private\\synthetic\\read.json"
        )

    monkeypatch.setattr(jobs, manager_method, fail)
    for locale, message in (("de", german), ("en", english)):
        headers = {"X-CSRF-Token": OWNER, "X-MCBE-Read-ID": IDENTIFIER, "Accept-Language": locale}
        body = {"world_path": "synthetic", "player_key": "synthetic-player"} if method == "POST" else None
        response = client.open(endpoint, method=method, json=body, headers=headers)
        assert response.status_code == status
        assert response.headers["Cache-Control"] == "no-store"
        assert response.json["success"] is False
        assert response.json["code"] == expected_code
        assert response.json["message_key"] == german
        assert response.json["message"] == response.json["error"] == message
        assert response.json["hints"]
        serialized = response.get_data(as_text=True)
        assert "Sensitive synthetic" not in serialized
        assert "private" not in serialized
        assert "read.json" not in serialized


def test_async_api_keeps_csrf_and_authentication_and_translates_errors(job_api, monkeypatch):
    main, jobs, client = job_api
    headers = {"X-CSRF-Token": OWNER, "X-MCBE-Read-ID": IDENTIFIER, "Accept-Language": "en"}
    assert client.post("/api/players", json={"world_path": "w"}).status_code == 403
    assert client.get(f"/api/world_reads/{IDENTIFIER}").status_code == 403
    expired = client.get(f"/api/world_reads/{IDENTIFIER}", headers=headers)
    assert expired.status_code == 404
    assert expired.json["code"] == "read_job_expired" and expired.json["hints"]
    assert expired.headers["Cache-Control"] == "no-store"
    monkeypatch.setattr(main, "auth_enabled", lambda: True)
    assert client.get(f"/api/world_reads/{IDENTIFIER}", headers=headers).status_code == 401
    monkeypatch.setattr(main, "auth_enabled", lambda: False)
    monkeypatch.setattr(main, "require_world_db_access_allowed", lambda: None)
    monkeypatch.setattr(
        main.editor_service,
        "list_players",
        lambda _path: (_ for _ in ()).throw(ValueError("Symlinks und Reparse-Points werden als Weltpfade nicht unterstützt.")),
    )
    assert client.post("/api/players", json={"world_path": "w"}, headers=headers).status_code == 202
    _finished(jobs)
    response = client.get(f"/api/world_reads/{IDENTIFIER}", headers=headers)
    assert response.status_code == 400
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json["message"] == "Symlinks and reparse points are not supported as world paths."


def test_async_real_service_remains_readonly_online_and_returns_stale_write_guard(job_api, tmp_path, monkeypatch):
    from mcbe_editor.item_data import ENCHANTMENTS, ITEMS
    from mcbe_editor.players import encode_player_key
    from mcbe_editor.services import BedrockEditorService
    from tests.browser.disk_fixture import create_world

    main, jobs, client = job_api
    world = tmp_path / "synthetic-world"
    create_world(world)
    before = {p.name: p.read_bytes() for p in (world / "db").iterdir()}
    monkeypatch.setattr(main, "editor_service", BedrockEditorService(ITEMS, ENCHANTMENTS))
    gate = {
        "allowed": False,
        "read_allowed": True,
        "server_status": {"status": "online"},
        "config": {"require_server_offline": True},
        "server_guard_epoch": 3,
        "server_guard_token": "current",
        "_server_guard_previous_token": "old",
    }
    monkeypatch.setattr(main, "world_db_access_gate", lambda: gate)
    monkeypatch.setattr(main, "require_world_db_access_allowed", lambda: None)
    for identifier, endpoint, extra in [
        (IDENTIFIER, "/api/players", {}),
        ("b" * 32, "/api/player/load", {"player_key": encode_player_key(b"~local_player")}),
    ]:
        headers = {"X-CSRF-Token": OWNER, "X-MCBE-Read-ID": identifier}
        response = client.post(endpoint, json={"world_path": str(world), **extra}, headers=headers)
        assert response.status_code == 202
        result, status = _finished(jobs, identifier)
        assert status == 200 and result["success"]
    assert result["server_guard_stale"] is True
    assert result["player_server_guard_token"] == "old"
    assert result["write_gate"]["allowed"] is False
    assert {p.name: p.read_bytes() for p in (world / "db").iterdir()} == before


def test_cancel_while_waiting_for_world_lock_does_not_open_database(job_api, tmp_path, monkeypatch):
    from mcbe_editor.services import BedrockEditorService
    from mcbe_editor.world_locks import locked_world

    main, jobs, client = job_api
    service = BedrockEditorService({}, {})
    monkeypatch.setattr(main, "editor_service", service)
    monkeypatch.setattr(main, "require_world_db_access_allowed", lambda: None)
    opened = []
    monkeypatch.setattr(service, "_open_db_readonly", lambda _path: opened.append(True))
    headers = {"X-CSRF-Token": OWNER, "X-MCBE-Read-ID": IDENTIFIER}
    with locked_world(str(tmp_path)):
        assert client.post("/api/players", json={"world_path": str(tmp_path)}, headers=headers).status_code == 202
        response = client.delete(f"/api/world_reads/{IDENTIFIER}", headers=headers)
        assert response.status_code == 408 and response.json["code"] == "read_cancelled"
        assert _finished(jobs)[1] == 408
    # The checkpoint runs before acquisition and again before opening.
    time.sleep(0.1)
    assert opened == []


def test_progress_has_a_bounded_quota_separate_from_normal_reads(job_api, monkeypatch):
    main, jobs, client = job_api
    monkeypatch.setitem(main._RATE_CONFIG, "read", (1, 60.0))
    monkeypatch.setitem(main._RATE_CONFIG, "read_progress", (3, 60.0))
    monkeypatch.setattr(jobs, "poll", lambda *_args, **_kwargs: ({"success": True, "pending": True}, 202))
    monkeypatch.setattr(main, "require_world_db_access_allowed", lambda: None)
    monkeypatch.setattr(main.editor_service, "list_players", lambda _path: {"success": True, "players": []})
    headers = {"X-CSRF-Token": OWNER}
    for _ in range(3):
        assert client.get(f"/api/world_reads/{IDENTIFIER}", headers=headers).status_code == 202
    assert client.get(f"/api/world_reads/{IDENTIFIER}", headers=headers).status_code == 429
    assert client.post("/api/players", json={"world_path": "w"}, headers=headers).status_code == 200
    assert client.post("/api/players", json={"world_path": "w"}, headers=headers).status_code == 429


@pytest.mark.parametrize("expired,code", [("observed", "read_cancelled"), ("updated", "read_timeout"), ("created", "read_timeout")])
def test_admission_expires_orphans_using_the_same_deadlines_as_polling(tmp_path, expired, code):
    jobs = WorldReadJobs(tmp_path)
    now = time.time()
    for identifier in (IDENTIFIER, "b" * 32):
        data = {
            "owner": jobs._owner(OWNER),
            "identity": "synthetic",
            "generation": "lost-worker",
            "state": "running",
            "created": now,
            "observed": now,
            "updated": now,
            "phase": "scanning",
            "current": 0,
        }
        data[expired] -= (jobs.timeout if expired == "created" else jobs.lease) + 10
        jobs._write(jobs._path(identifier), data)
    replacement = WorldReadJobs(tmp_path)
    assert replacement.start("c" * 32, OWNER, "replacement", lambda: ({"success": True}, 200))[1] == 202
    assert _finished(replacement, "c" * 32)[1] == 200
    for identifier in (IDENTIFIER, "b" * 32):
        result, status = replacement.poll(identifier, OWNER)
        assert status == 408 and result["code"] == code
        stored = json.loads(jobs._path(identifier).read_text())
        assert stored["finished"] == pytest.approx(now - 10), "retention begins at expiry, not at cleanup"


def test_worker_process_loss_does_not_block_replacement_after_lease(tmp_path):
    context = multiprocessing.get_context("spawn")
    started, release, finished = context.Event(), context.Event(), context.Event()
    process = context.Process(target=_process_read, args=(tmp_path, started, release, finished))
    process.start()
    try:
        assert started.wait(10)
    finally:
        process.terminate()
        process.join(10)
    assert not process.is_alive()
    replacement = WorldReadJobs(tmp_path, limit=1)
    path = replacement._path(IDENTIFIER)
    with replacement._lock():
        data = json.loads(path.read_text())
        for key in ("created", "observed", "updated"):
            data[key] -= 60
        replacement._write(path, data)
    assert replacement.start("b" * 32, OWNER, "replacement", lambda: ({"success": True}, 200))[1] == 202
    assert _finished(replacement, "b" * 32)[1] == 200
    assert replacement.poll(IDENTIFIER, OWNER)[1] == 408


def test_cancel_before_start_survives_other_workers_and_result_cleanup(tmp_path):
    jobs = WorldReadJobs(tmp_path)
    cancelled = ({"success": False, "code": "read_cancelled"}, 408)
    assert jobs.poll(IDENTIFIER, OWNER, cancel=True) == cancelled
    other = WorldReadJobs(tmp_path)
    path = jobs._path(IDENTIFIER)
    data = json.loads(path.read_text())
    data["finished"] -= jobs.retention + 1
    jobs._write(path, data)
    # Ordinary result eviction must not forget a still-promised cancellation.
    for index in range(66):
        completed = {
            "owner": jobs._owner(OWNER),
            "identity": "other",
            "created": time.time(),
            "state": "done",
            "finished": time.time(),
            "result": {"success": True},
            "status": 200,
        }
        jobs._write(jobs._path(f"{index:032x}"), completed)
    with jobs._lock():
        other._sweep(time.time())
    assert other.start(IDENTIFIER, OWNER, "delayed request", lambda: pytest.fail("cancelled scan started")) == cancelled
    assert other.poll(IDENTIFIER, OWNER, cancel=True) == cancelled
    for action in (
        lambda: other.poll(IDENTIFIER, "foreign", cancel=True),
        lambda: other.start(IDENTIFIER, "foreign", "read", lambda: pytest.fail("foreign scan")),
    ):
        with pytest.raises(ReadJobError) as error:
            action()
        assert error.value.status == 404
    assert json.loads(path.read_text())["cancel_until"] == data["cancel_until"], "retries must not extend retention"


@pytest.mark.parametrize("expired_before_cancel", [False, True], ids=["finished", "expired"])
@pytest.mark.parametrize(
    "original_result,original_status",
    [
        ({"success": True, "players": []}, 200),
        ({"success": False, "code": "synthetic_error"}, 400),
        ({"success": False, "code": "read_timeout"}, 408),
    ],
    ids=["success", "error", "timeout"],
)
def test_cancel_terminal_result_blocks_delayed_retry_after_cleanup(tmp_path, monkeypatch, expired_before_cancel, original_result, original_status):
    from mcbe_editor import world_read_jobs

    jobs = WorldReadJobs(tmp_path)
    other_worker = WorldReadJobs(tmp_path)
    calls = []

    def work():
        calls.append("read")
        return original_result, original_status

    jobs.start(IDENTIFIER, OWNER, "read", work)
    assert _finished(jobs) == (original_result, original_status)
    path = jobs._path(IDENTIFIER)
    stored = json.loads(path.read_text())
    now = stored["finished"] + (jobs.retention + 1 if expired_before_cancel else 1)
    monkeypatch.setattr(world_read_jobs, "time", SimpleNamespace(time=lambda: now, monotonic=time.monotonic))

    # Session validation precedes expiry/cleanup, including for old results.
    before = path.read_bytes()
    with pytest.raises(ReadJobError) as error:
        other_worker.poll(IDENTIFIER, "foreign", cancel=True)
    assert error.value.status == 404
    assert path.read_bytes() == before

    cancelled = ({"success": False, "code": "read_cancelled"}, 408)
    assert other_worker.poll(IDENTIFIER, OWNER, cancel=True) == cancelled
    cancel_until = json.loads(path.read_text())["cancel_until"]

    # The lost response is still resumable in the browser when another request
    # cleans up ordinary completed results. A DELETE must survive that cleanup.
    now += jobs.retention + 1
    assert other_worker.start("b" * 32, OWNER, "unrelated", lambda: ({"success": True}, 200))[1] == 202
    assert _finished(other_worker, "b" * 32)[1] == 200
    result = jobs.start(IDENTIFIER, OWNER, "read", work)
    if result[1] == 202:
        _finished(jobs)
    assert result == cancelled
    assert calls == ["read"]
    assert jobs.poll(IDENTIFIER, OWNER, cancel=True) == cancelled
    assert json.loads(path.read_text())["cancel_until"] == cancel_until, "repeated DELETE must not renew the reservation"


def test_terminal_cancellation_obeys_capacity_and_can_retry_after_capacity_returns(tmp_path, monkeypatch):
    from mcbe_editor import world_read_jobs

    monkeypatch.setattr(world_read_jobs, "_MAX_CANCELLED_READS", 2)
    jobs = WorldReadJobs(tmp_path)
    jobs.start(IDENTIFIER, OWNER, "read", lambda: ({"success": True}, 200))
    assert _finished(jobs)[1] == 200
    for identifier in ("b" * 32, "c" * 32):
        assert jobs.poll(identifier, OWNER, cancel=True)[1] == 408

    with pytest.raises(ReadJobError) as error:
        jobs.poll(IDENTIFIER, OWNER, cancel=True)
    assert error.value.status == 429
    with jobs._lock():
        assert jobs._sweep(time.time()) == (0, 2)
        data = json.loads(jobs._path("b" * 32).read_text())
        data["cancel_until"] = time.time() - 1
        jobs._write(jobs._path("b" * 32), data)

    assert jobs.poll(IDENTIFIER, OWNER, cancel=True) == ({"success": False, "code": "read_cancelled"}, 408)
    with jobs._lock():
        assert jobs._sweep(time.time()) == (0, 2)
    assert jobs.start(IDENTIFIER, OWNER, "read", lambda: pytest.fail("cancelled retry started"))[1] == 408


def test_cancellation_storage_is_bounded_without_evicting_promises_or_blocking_active_cancel(tmp_path, monkeypatch):
    from mcbe_editor import world_read_jobs

    monkeypatch.setattr(world_read_jobs, "_MAX_CANCELLED_READS", 3)
    jobs = WorldReadJobs(tmp_path)
    entered, closed = Event(), Event()

    def work():
        try:
            entered.set()
            while True:
                read_operation.checkpoint("scanning")
                time.sleep(0.01)
        finally:
            closed.set()

    jobs.start(IDENTIFIER, OWNER, "active", work)
    assert entered.wait(5)
    try:
        for identifier in ("b" * 32, "c" * 32):
            assert jobs.poll(identifier, OWNER, cancel=True)[1] == 408
        with pytest.raises(ReadJobError) as error:
            jobs.poll("d" * 32, OWNER, cancel=True)
        assert error.value.status == 429
        assert not jobs._path("d" * 32).exists()
    finally:
        assert jobs.poll(IDENTIFIER, OWNER, cancel=True)[1] == 408
        assert closed.wait(5)
    with pytest.raises(ReadJobError) as error:
        jobs.start("d" * 32, OWNER, "new", lambda: pytest.fail("admitted beyond cancellation capacity"))
    assert error.value.status == 429
    for path in tmp_path.glob("*.json"):
        data = json.loads(path.read_text())
        data["cancel_until"] = time.time() - 1
        jobs._write(path, data)
    assert jobs.start("d" * 32, OWNER, "new", lambda: ({"success": True}, 200))[1] == 202
    assert _finished(jobs, "d" * 32)[1] == 200


def test_http_cancel_can_overtake_start_without_running_service(job_api, monkeypatch):
    main, jobs, client = job_api
    monkeypatch.setattr(main.editor_service, "list_players", lambda _path: pytest.fail("cancelled HTTP read started"))
    headers = {"X-CSRF-Token": OWNER, "X-MCBE-Read-ID": IDENTIFIER}
    url = f"/api/world_reads/{IDENTIFIER}"
    assert client.delete(url).status_code == 403
    assert client.delete(url, headers=headers).status_code == 408
    response = client.post("/api/players", json={"world_path": "synthetic"}, headers=headers)
    assert response.status_code == 408
    assert response.json["code"] == "read_cancelled"
    assert response.headers["Cache-Control"] == "no-store"
    assert jobs._slots.acquire(blocking=False) and jobs._slots.acquire(blocking=False)


@pytest.mark.parametrize("expired_before_cancel", [False, True], ids=["finished", "expired"])
def test_http_cancel_terminal_result_blocks_late_retry_and_allows_fresh_read(job_api, monkeypatch, expired_before_cancel):
    from mcbe_editor import world_read_jobs

    main, jobs, client = job_api
    calls = []

    def list_players(world_path):
        calls.append(world_path)
        return {"success": True, "players": []}

    monkeypatch.setattr(main, "require_world_db_access_allowed", lambda: None)
    monkeypatch.setattr(main.editor_service, "list_players", list_players)
    headers = {"X-CSRF-Token": OWNER, "X-MCBE-Read-ID": IDENTIFIER}
    body = {"world_path": "synthetic"}
    assert client.post("/api/players", json=body, headers=headers).status_code == 202
    assert _finished(jobs)[1] == 200
    stored = json.loads(jobs._path(IDENTIFIER).read_text())
    now = stored["finished"] + (jobs.retention + 1 if expired_before_cancel else 1)
    monkeypatch.setattr(world_read_jobs, "time", SimpleNamespace(time=lambda: now, monotonic=time.monotonic))

    response = client.delete(f"/api/world_reads/{IDENTIFIER}", headers=headers)
    assert response.status_code == 408
    assert response.json["code"] == "read_cancelled"
    assert response.headers["Cache-Control"] == "no-store"

    now += jobs.retention + 1
    other_worker = WorldReadJobs(jobs.directory)
    monkeypatch.setattr(main, "WORLD_READ_JOBS", other_worker)
    other_worker.start("b" * 32, OWNER, "cleanup", lambda: ({"success": True}, 200))
    assert _finished(other_worker, "b" * 32)[1] == 200
    late_response = client.post("/api/players", json=body, headers=headers)
    assert late_response.status_code == 408
    assert late_response.json["code"] == "read_cancelled"
    assert late_response.headers["Cache-Control"] == "no-store"
    assert calls == ["synthetic"]

    fresh_headers = {**headers, "X-MCBE-Read-ID": "c" * 32}
    assert client.post("/api/players", json=body, headers=fresh_headers).status_code == 202
    assert _finished(other_worker, "c" * 32)[1] == 200
    assert calls == ["synthetic", "synthetic"]
