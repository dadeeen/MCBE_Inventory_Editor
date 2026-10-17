"""NetherNet detection in the server status check.

Servers with ``transport=nethernet`` ignore the RakNet ping and answer HTTP on
TCP ``server-port`` instead. These tests serve scripted answers on a loopback
port; the RakNet probe is replaced so no test depends on a real server.
"""

from __future__ import annotations

import socket
import threading
import time
from contextlib import contextmanager, suppress
from dataclasses import replace

import pytest

from mcbe_editor import i18n, server_status


@contextmanager
def _signaling_server(reply: bytes | None, *, host: str = "127.0.0.1", port: int = 0, family: int = socket.AF_INET, reply_delay: float = 0):
    """Answer every TCP connection with ``reply``; ``None`` closes silently."""

    requests: list[bytes] = []
    listener = socket.create_server((host, port), family=family)
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
                if reply is not None and not stop.wait(reply_delay):
                    # Another address may already have answered online and
                    # caused the probe to cancel this connection.
                    with suppress(OSError):
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


@pytest.mark.usefixtures("no_raknet")
@pytest.mark.parametrize("first_reply", [b"HTTP/1.1 502 Bad Gateway\r\n\r\n", None])
def test_nethernet_tries_all_resolved_addresses_after_connected_unknown(monkeypatch, first_reply):
    if not socket.has_ipv6:
        pytest.skip("IPv6 loopback is unavailable")
    try:
        listener = socket.create_server(("::1", 0), family=socket.AF_INET6)
    except OSError as exc:
        pytest.skip(f"IPv6 loopback is unavailable: {exc}")
    listener.close()

    with (
        _signaling_server(first_reply, host="::1", family=socket.AF_INET6) as (port, _first_requests),
        _signaling_server(b"HTTP/1.1 200 OK\r\n\r\n", port=port) as (_port, second_requests),
    ):
        monkeypatch.setattr(
            socket,
            "getaddrinfo",
            lambda host, target_port, family=0, type=0, proto=0, flags=0: [
                (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::1", port, 0, 0)),
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port)),
            ],
        )
        config = replace(_config(port), server_host="bedrock.example")
        status = server_status.check_server_status(config)

    assert second_requests
    assert status["status"] == "online"
    assert status["transport"] == "nethernet"
    # A running endpoint must not offer the manual unknown-status override.
    gate = server_status.write_gate(config, status, unknown_status_confirmed=True)
    assert gate["allowed"] is False
    assert gate["requires_unknown_server_confirmation"] is False


@pytest.mark.parametrize("second_online", [True, False])
def test_nethernet_reserves_time_for_later_addresses_with_one_io_budget(monkeypatch, second_online):
    reply = b"HTTP/1.1 200 OK\r\n\r\n"
    with (
        _signaling_server(reply, reply_delay=2) as (first_port, _first_requests),
        _signaling_server(reply, reply_delay=0 if second_online else 2) as (second_port, second_requests),
    ):
        monkeypatch.setattr(
            socket,
            "getaddrinfo",
            lambda *args, **kwargs: [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", first_port)),
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", second_port)),
            ],
        )
        started = time.monotonic()
        if second_online:
            assert server_status._nethernet_join_probe("bedrock.example", first_port, timeout=0.4)["status"] == "online"
        else:
            with pytest.raises(TimeoutError):
                server_status._nethernet_join_probe("bedrock.example", first_port, timeout=0.4)
        elapsed = time.monotonic() - started
    if second_online:
        assert second_requests
    assert elapsed < 0.7, "each DNS record must not multiply the total I/O timeout"


def _resolve_loopback_ports(monkeypatch, *ports):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port)) for port in ports],
    )


def _track_probe_sockets(monkeypatch):
    """Track client sockets without counting the loopback servers' accept sockets."""

    original_socket = socket.socket
    probe_thread = threading.get_ident()
    clients = []
    peak_connections = [0]

    def tracked_socket(*args, **kwargs):
        conn = original_socket(*args, **kwargs)
        if threading.get_ident() == probe_thread:
            clients.append(conn)
            peak_connections[0] = max(peak_connections[0], sum(client.fileno() != -1 for client in clients))
        return conn

    monkeypatch.setattr(socket, "socket", tracked_socket)
    return clients, peak_connections


def test_nethernet_accepts_slow_online_address_within_the_shared_deadline(monkeypatch):
    # The successful response arrives after half the overall budget. Giving
    # each address its own slice incorrectly discards this running server.
    with (
        _signaling_server(b"HTTP/1.1 200 OK\r\n\r\n", reply_delay=0.65) as (first_port, first_requests),
        _signaling_server(b"HTTP/1.1 502 Bad Gateway\r\n\r\n") as (second_port, _second_requests),
    ):
        _resolve_loopback_ports(monkeypatch, first_port, second_port)
        status = server_status._nethernet_join_probe("bedrock.example", first_port, timeout=1)

    assert first_requests
    assert status["status"] == "online"
    gate = server_status.write_gate(_config(first_port), status, unknown_status_confirmed=True)
    assert gate["allowed"] is False
    assert gate["requires_unknown_server_confirmation"] is False


@pytest.mark.parametrize("outcome", ["online", "timeout", "closed"])
def test_nethernet_closes_all_client_sockets_before_returning(monkeypatch, outcome):
    reply = b"HTTP/1.1 200 OK\r\n\r\n" if outcome != "closed" else None
    with (
        _signaling_server(reply, reply_delay=2) as (first_port, _first_requests),
        _signaling_server(reply, reply_delay=0 if outcome == "online" else 2) as (second_port, _second_requests),
    ):
        _resolve_loopback_ports(monkeypatch, first_port, second_port)
        clients, _peak = _track_probe_sockets(monkeypatch)
        started = time.monotonic()
        if outcome == "online":
            assert server_status._nethernet_join_probe("bedrock.example", first_port, timeout=1)["status"] == "online"
            assert time.monotonic() - started < 0.7, "success must not wait for a stalled address"
        else:
            with pytest.raises(TimeoutError if outcome == "timeout" else ConnectionResetError):
                server_status._nethernet_join_probe("bedrock.example", first_port, timeout=0.2)
        assert len(clients) == 2
        assert all(conn.fileno() == -1 for conn in clients)


def test_nethernet_queues_addresses_without_exceeding_connection_limit(monkeypatch):
    with (
        _signaling_server(b"HTTP/1.1 502 Bad Gateway\r\n\r\n") as (first_port, _first_requests),
        _signaling_server(None) as (second_port, _second_requests),
        _signaling_server(b"HTTP/1.1 200 OK\r\n\r\n") as (third_port, third_requests),
    ):
        _resolve_loopback_ports(monkeypatch, first_port, second_port, third_port)
        monkeypatch.setattr(server_status, "_MAX_NETHERNET_CONNECTIONS", 2)
        clients, peak = _track_probe_sockets(monkeypatch)
        assert server_status._nethernet_join_probe("bedrock.example", first_port)["status"] == "online"
        assert len(clients) == 3
        assert peak == [2]
        assert all(conn.fileno() == -1 for conn in clients)
    assert third_requests


def test_nethernet_closes_client_sockets_if_selector_fails(monkeypatch):
    class FailedSelector(server_status.selectors.DefaultSelector):
        def select(self, timeout=None):
            raise OSError("selector failed")

    with _signaling_server(None) as (port, _requests):
        _resolve_loopback_ports(monkeypatch, port)
        clients, _peak = _track_probe_sockets(monkeypatch)
        monkeypatch.setattr(server_status.selectors, "DefaultSelector", FailedSelector)
        with pytest.raises(OSError, match="selector failed"):
            server_status._nethernet_join_probe("bedrock.example", port)
        assert len(clients) == 1
        assert clients[0].fileno() == -1
