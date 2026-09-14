from __future__ import annotations

import socket
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from http.client import HTTPConnection
from threading import Event, Thread, enumerate as enumerate_threads

import pytest
from flask import Flask, Response, request
from werkzeug.middleware.proxy_fix import ProxyFix

from mcbe_editor.local_server import LocalServer


@contextmanager
def running_server(app, port=0):
    server = LocalServer(app, "127.0.0.1", port)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, int(server._server.effective_port), thread
    finally:
        server.shutdown()
        thread.join(timeout=10)
        assert not thread.is_alive(), "local server did not shut down"
        assert not server._sockets
        assert not server._dispatcher.threads


def server_app():
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 1024
    return app


def fetch(port, path="/"):
    with closing(HTTPConnection("127.0.0.1", port, timeout=10)) as connection:
        connection.request("GET", path)
        response = connection.getresponse()
        return response.status, response.read()


def test_local_server_reuses_http_connection_and_closes_idle_connections():
    app = server_app()
    app.add_url_rule("/", view_func=lambda: "ok")
    with running_server(app) as (server, port, _thread), closing(HTTPConnection("127.0.0.1", port, timeout=5)) as connection:
        connection.request("GET", "/")
        assert connection.getresponse().read() == b"ok"
        first_socket = connection.sock
        assert first_socket is not None
        connection.request("GET", "/")
        assert connection.getresponse().read() == b"ok"
        assert connection.sock is first_socket
        server.shutdown()
        _thread.join(timeout=5)
        assert not _thread.is_alive()


def test_local_server_handles_parallel_requests():
    app = server_app()
    entered, release = Event(), Event()

    @app.get("/slow")
    def slow():
        entered.set()
        assert release.wait(5)
        return "done"

    app.add_url_rule("/", view_func=lambda: "ready")
    with running_server(app) as (_server, port, _thread), ThreadPoolExecutor(1) as pool:
        pending = pool.submit(fetch, port, "/slow")
        try:
            assert entered.wait(5)
            assert fetch(port) == (200, b"ready")
        finally:
            release.set()
        assert pending.result(timeout=5) == (200, b"done")


def test_local_shutdown_finishes_active_handler_and_large_response(monkeypatch):
    monkeypatch.setattr("mcbe_editor.local_server.SHUTDOWN_FLUSH_TIMEOUT", 0.05)
    app = server_app()
    entered, release = Event(), Event()
    payload = b"x" * (2 * 1024 * 1024)

    @app.get("/")
    def active_request():
        entered.set()
        assert release.wait(5)
        return payload

    with running_server(app) as (server, port, thread), ThreadPoolExecutor(1) as pool:
        pending = pool.submit(fetch, port)
        try:
            assert entered.wait(5)
            server.shutdown()
            thread.join(timeout=0.2)
            assert thread.is_alive(), "shutdown abandoned an active handler"
        finally:
            release.set()
        assert pending.result(timeout=5) == (200, payload)


def test_local_shutdown_unblocks_response_when_client_does_not_read(monkeypatch):
    monkeypatch.setattr("mcbe_editor.local_server.SHUTDOWN_FLUSH_TIMEOUT", 0.2)
    app = server_app()
    started, finished = Event(), Event()

    @app.get("/")
    def download():
        def body():
            started.set()
            try:
                for _ in range(32):
                    yield b"x" * (1024 * 1024)
            finally:
                finished.set()
        return Response(body(), content_type="application/octet-stream")

    with running_server(app) as (server, port, thread), socket.socket() as client:
        client.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024)
        client.settimeout(5)
        client.connect(("127.0.0.1", port))
        client.sendall(b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n")
        assert started.wait(5)
        server.shutdown()
        thread.join(timeout=3)
        assert not thread.is_alive(), "a non-reading client blocked shutdown"
        assert finished.is_set(), "response iterator was not closed"


def test_local_server_bind_failure_does_not_leak_workers():
    app = server_app()
    with running_server(app) as (_server, port, _thread):
        before = {t.ident for t in enumerate_threads() if t.name.startswith("waitress-")}
        with pytest.raises(OSError):
            LocalServer(app, "127.0.0.1", port)
        assert {t.ident for t in enumerate_threads() if t.name.startswith("waitress-")} == before


def test_local_server_can_restart_on_same_port():
    app = server_app()
    app.add_url_rule("/", view_func=lambda: "ok")
    with running_server(app) as (_server, port, _thread):
        assert fetch(port) == (200, b"ok")
    with running_server(app, port) as (_server, restarted_port, _thread):
        assert restarted_port == port
        assert fetch(port) == (200, b"ok")


def test_local_server_keyboard_interrupt_cleans_up(monkeypatch):
    server = LocalServer(server_app(), "127.0.0.1", 0)
    poll = server._poll

    def interrupt_once():
        monkeypatch.setattr(server, "_poll", poll)
        raise KeyboardInterrupt

    monkeypatch.setattr(server, "_poll", interrupt_once)
    with pytest.raises(KeyboardInterrupt):
        server.serve_forever()
    assert not server._sockets
    assert not server._dispatcher.threads


@pytest.mark.parametrize("trust_proxy", [False, True])
def test_local_server_preserves_app_proxy_policy(trust_proxy):
    app = server_app()
    if trust_proxy:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
    app.add_url_rule("/", view_func=lambda: Response(f"{request.remote_addr} {request.scheme}", mimetype="text/plain"))
    with running_server(app) as (_server, port, _thread), closing(HTTPConnection("127.0.0.1", port, timeout=5)) as connection:
        connection.request("GET", "/", headers={"X-Forwarded-For": "192.0.2.1", "X-Forwarded-Proto": "https"})
        expected = b"192.0.2.1 https" if trust_proxy else b"127.0.0.1 http"
        response = connection.getresponse()
        assert response.getheader("Content-Type") == "text/plain; charset=utf-8"
        assert response.read() == expected


def test_local_server_rejects_oversized_upload_before_app():
    app = server_app()
    called = Event()

    @app.post("/")
    def upload():
        called.set()
        return "unexpected"

    with running_server(app) as (_server, port, _thread), closing(HTTPConnection("127.0.0.1", port, timeout=5)) as connection:
        connection.request("POST", "/", headers={"Content-Length": str(128 * 1024)})
        assert connection.getresponse().status == 413
        assert not called.is_set()


@pytest.mark.parametrize("chunked", [False, True])
@pytest.mark.parametrize("limit", [1024, 10 * 1024 * 1024], ids=["small", "production"])
@pytest.mark.parametrize("offset,expected", [(-1, 200), (0, 200), (1, 413)])
def test_local_upload_boundary_matches_flask(chunked, limit, offset, expected):
    app = server_app()
    app.config["MAX_CONTENT_LENGTH"] = limit
    size = limit + offset

    @app.post("/")
    def upload():
        return str(len(request.get_data()))

    @app.errorhandler(413)
    def too_large(_error):
        return {"success": False, "code": "request_too_large"}, 413

    with running_server(app) as (_server, port, _thread), closing(HTTPConnection("127.0.0.1", port, timeout=5)) as connection:
        payload = b"x" * size
        body = (payload[i:i + 8192] for i in range(0, size, 8192)) if chunked else payload
        connection.request("POST", "/", body=body, encode_chunked=chunked)
        response = connection.getresponse()
        assert response.status == expected
        payload = response.read()
        if expected == 200:
            assert payload == str(size).encode()
        else:
            assert response.getheader("Content-Type") == "application/json"
            assert b"request_too_large" in payload


def test_interrupted_upload_does_not_run_handler_or_block_shutdown():
    app = server_app()
    called = Event()

    @app.post("/")
    def upload():
        called.set()
        return "unexpected"

    app.add_url_rule("/ready", view_func=lambda: "ok")
    with running_server(app) as (_server, port, _thread):
        with socket.create_connection(("127.0.0.1", port), timeout=5) as client:
            client.sendall(b"POST / HTTP/1.1\r\nHost: localhost\r\nContent-Length: 1024\r\n\r\nincomplete")
        assert fetch(port, "/ready") == (200, b"ok")
        assert not called.is_set()


def test_pipelined_requests_do_not_mix_responses():
    app = server_app()
    app.add_url_rule("/<value>", view_func=lambda value: Response(value, mimetype="text/plain"))
    with running_server(app) as (_server, port, _thread), socket.create_connection(("127.0.0.1", port), timeout=5) as client:
        client.sendall(
            b"GET /first HTTP/1.1\r\nHost: localhost\r\n\r\n"
            b"GET /second HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n"
        )
        chunks = []
        while chunk := client.recv(4096):
            chunks.append(chunk)
        response = b"".join(chunks)
        assert response.count(b"HTTP/1.1 200 OK\r\n") == 2
        assert response.count(b"Content-Type: text/plain; charset=utf-8\r\n") == 2
        assert b"\r\n\r\nfirstHTTP/1.1 200 OK\r\n" in response
        assert response.endswith(b"\r\n\r\nsecond")


def test_heartbeat_timeout_uses_monotonic_clock(monkeypatch) -> None:
    import main

    class ServerStub:
        shutdown_calls = 0

        def shutdown(self) -> None:
            self.shutdown_calls += 1

    sleep_calls = 0

    def fail_on_second_sleep(_seconds: float) -> None:
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls > 1:
            raise AssertionError("heartbeat loop did not terminate after shutdown")

    server = ServerStub()
    monkeypatch.setattr(main, "LAST_HEARTBEAT", 100.0)
    monkeypatch.setattr(main, "HEARTBEAT_TIMEOUT", 15.0)
    monkeypatch.setattr(main, "_SAVING_COUNTER", 0)
    monkeypatch.setattr(main, "_SERVER", server)
    monkeypatch.setattr(main.time, "sleep", fail_on_second_sleep)
    monkeypatch.setattr(main, "_heartbeat_now", lambda: 115.01)

    main.check_heartbeat()

    assert server.shutdown_calls == 1
    assert sleep_calls == 1


def test_note_heartbeat_records_monotonic_clock(monkeypatch) -> None:
    import main

    monkeypatch.setattr(main, "LAST_HEARTBEAT", 0.0)
    monkeypatch.setattr(main, "_heartbeat_now", lambda: 42.5)

    main.note_heartbeat_received()

    assert main.LAST_HEARTBEAT == 42.5
