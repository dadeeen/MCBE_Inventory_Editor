"""NetherNet detection in the server status check.

Servers with ``transport=nethernet`` ignore the RakNet ping and answer HTTP on
TCP ``server-port`` instead. These tests serve scripted answers on a loopback
port; the RakNet probe is replaced so no test depends on a real server.
"""

from __future__ import annotations

import socket
import threading
import time
from contextlib import contextmanager
from dataclasses import replace

import pytest

from mcbe_editor import i18n, server_status


@contextmanager
def _signaling_server(reply: bytes | None):
    """Answer every TCP connection with ``reply``; ``None`` closes silently."""

    requests: list[bytes] = []
    listener = socket.create_server(("127.0.0.1", 0))
    listener.settimeout(0.1)
    stop = threading.Event()

    def serve() -> None:
        while not stop.is_set():
            try:
                conn, _addr = listener.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            with conn:
                conn.settimeout(5)
                request = b""
                while b"\r\n\r\n" not in request:
                    chunk = conn.recv(1024)
                    if not chunk:
                        break
                    request += chunk
                requests.append(request)
                if reply is not None:
                    conn.sendall(reply)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        yield listener.getsockname()[1], requests
    finally:
        stop.set()
        thread.join(5)
        listener.close()


def _config(port: int):
    import main

    return replace(main.APP_CONFIG, server_host="127.0.0.1", server_port=port, require_server_offline=True)


@pytest.fixture
def no_raknet(monkeypatch):
    def silent(_host, _port):
        raise TimeoutError("Keine Antwort vom Server.")

    monkeypatch.setattr(server_status, "_bedrock_unconnected_ping", silent)


@pytest.mark.usefixtures("no_raknet")
def test_nethernet_join_answer_blocks_writes_like_a_raknet_pong():
    with _signaling_server(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n") as (port, requests):
        status = server_status.check_server_status(_config(port))

    assert status["status"] == "online"
    assert status["transport"] == "nethernet"
    assert status["message_key"] == "Server erreichbar (NetherNet)."
    assert requests[0].startswith(b"GET /v1/join HTTP/1.1\r\n")
    assert f"Host: 127.0.0.1:{port}\r\n".encode() in requests[0]
    gate = server_status.write_gate(_config(port), status)
    assert gate["allowed"] is False
    assert gate["reason"] == "Server läuft noch. Bitte Server stoppen."


@pytest.mark.usefixtures("no_raknet")
def test_reverse_proxy_error_is_not_taken_for_a_running_server():
    # A proxy in front of a stopped NetherNet server answers, but not with 2xx.
    with _signaling_server(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n") as (port, _requests):
        status = server_status.check_server_status(_config(port))

    assert status["status"] == "unknown"
    assert status["message_key"] == "Unerwartete HTTP-Antwort am Serverport (Status {status})."
    assert status["message_params"] == {"status": 502}
    assert status["message"] == "Unerwartete HTTP-Antwort am Serverport (Status 502)."
    gate = server_status.write_gate(_config(port), status)
    assert gate["allowed"] is False
    assert gate["requires_unknown_server_confirmation"] is True


@pytest.mark.usefixtures("no_raknet")
def test_non_http_answer_on_the_server_port_stays_unknown():
    with _signaling_server(b"\x00\x01not http\r\n") as (port, _requests):
        status = server_status.check_server_status(_config(port))

    assert status["status"] == "unknown"
    assert status["message_key"] == "Unerwartete Antwort am Serverport."


@pytest.mark.usefixtures("no_raknet")
def test_connection_closed_without_answer_keeps_the_raknet_result():
    # A port proxy can accept TCP and close it when nothing listens behind it.
    with _signaling_server(None) as (port, requests):
        status = server_status.check_server_status(_config(port))

    assert requests
    assert status["status"] == "unknown"
    assert status["message_key"] == "Keine Antwort vom Server."


def test_raknet_pong_does_not_wait_for_the_nethernet_probe(monkeypatch):
    nethernet_running = threading.Event()
    released = threading.Event()

    def blocked_nethernet(_host, _port):
        nethernet_running.set()
        released.wait(5)
        raise TimeoutError("timeout")

    def pong(_host, _port):
        # Answer only once the other probe runs, so it cannot simply be cancelled.
        nethernet_running.wait(5)
        return {"status": "online", "message": "Server erreichbar.", "message_key": "Server erreichbar.", "message_params": {}, "motd": "Bedrock"}

    monkeypatch.setattr(server_status, "_nethernet_join_probe", blocked_nethernet)
    monkeypatch.setattr(server_status, "_bedrock_unconnected_ping", pong)
    started = time.monotonic()
    try:
        status = server_status.check_server_status(_config(19132))
    finally:
        released.set()

    assert time.monotonic() - started < 2.5
    assert status["status"] == "online"
    assert status["transport"] == "raknet"
    assert status["motd"] == "Bedrock"


def test_nethernet_answer_does_not_wait_for_the_raknet_timeout(monkeypatch):
    released = threading.Event()

    def blocked_raknet(_host, _port):
        released.wait(5)
        raise TimeoutError("Keine Antwort vom Server.")

    monkeypatch.setattr(server_status, "_bedrock_unconnected_ping", blocked_raknet)
    with _signaling_server(b"HTTP/1.1 204 No Content\r\n\r\n") as (port, _requests):
        started = time.monotonic()
        try:
            status = server_status.check_server_status(_config(port))
        finally:
            released.set()

    assert time.monotonic() - started < 2.5
    assert status["status"] == "online"
    assert status["transport"] == "nethernet"


@pytest.mark.parametrize(
    ("host", "authority"),
    [
        ("::1", "[::1]:19132"),
        ("[::1]", "[::1]:19132"),
        ("192.0.2.10", "192.0.2.10:19132"),
        ("bedrock.example", "bedrock.example:19132"),
    ],
)
def test_http_host_header_brackets_ipv6_literals(host, authority):
    assert server_status._http_authority(host, 19132) == authority


def test_nethernet_status_messages_have_english_translations():
    assert i18n.translate("Server erreichbar (NetherNet).", "en") == "Server reachable (NetherNet)."
    assert i18n.translate("Unerwartete Antwort am Serverport.", "en") == "Unexpected response on the server port."
    assert (
        i18n.translate("Unerwartete HTTP-Antwort am Serverport (Status {status}).", "en", {"status": 502})
        == "Unexpected HTTP response on the server port (status 502)."
    )
