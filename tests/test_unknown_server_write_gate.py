import socket
from dataclasses import replace
from types import SimpleNamespace

import pytest


def test_unknown_server_status_requires_explicit_confirmation_before_write():
    from mcbe_editor.server_status import write_gate

    import main

    config = replace(
        main.APP_CONFIG,
        read_only=False,
        require_server_offline=True,
        allow_edit_while_online=False,
    )
    gate = write_gate(config, status={"status": "unknown"}, unknown_status_confirmed=False)
    assert gate["allowed"] is False
    assert gate["read_allowed"] is True
    assert gate["requires_unknown_server_confirmation"] is True
    assert gate["unknown_status_confirmed"] is False


def test_unknown_server_status_requires_confirmation_without_offline_lock():
    from mcbe_editor.server_status import write_gate

    import main

    config = replace(
        main.APP_CONFIG,
        read_only=False,
        require_server_offline=False,
        allow_edit_while_online=False,
    )
    gate = write_gate(config, status={"status": "unknown"}, unknown_status_confirmed=False)
    assert gate["allowed"] is False
    assert gate["read_allowed"] is True
    assert gate["requires_unknown_server_confirmation"] is True


def test_confirmed_unknown_server_status_allows_write_attempt():
    from mcbe_editor.server_status import write_gate

    import main

    config = replace(
        main.APP_CONFIG,
        read_only=False,
        require_server_offline=True,
        allow_edit_while_online=False,
    )
    gate = write_gate(config, status={"status": "unknown"}, unknown_status_confirmed=True)
    assert gate["allowed"] is True
    assert gate["read_allowed"] is True
    assert gate["requires_unknown_server_confirmation"] is False
    assert gate["unknown_status_confirmed"] is True


def test_confirmed_online_server_status_still_blocks_write():
    from mcbe_editor.server_status import write_gate

    import main

    config = replace(
        main.APP_CONFIG,
        read_only=False,
        require_server_offline=True,
        allow_edit_while_online=False,
    )
    gate = write_gate(config, status={"status": "online"}, unknown_status_confirmed=True)
    assert gate["allowed"] is False
    assert gate["read_allowed"] is True
    assert gate["requires_unknown_server_confirmation"] is False
    assert gate["unknown_status_confirmed"] is True
    assert "Server läuft noch" in gate["reason"]


def test_server_status_detects_ipv6_bedrock_pong(monkeypatch):
    from mcbe_editor.server_status import check_server_status

    import main

    calls = []
    pong = b"\x1c" + b"\x00" * 40

    class FakeSocket:
        def __init__(self, family, socktype, proto):
            self.family = family
            self.socktype = socktype
            self.proto = proto

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def settimeout(self, timeout):
            calls.append(("timeout", timeout))

        def sendto(self, packet, sockaddr):
            calls.append(("sendto", self.family, sockaddr, packet[:1]))

        def recvfrom(self, _size):
            return pong, ("::1", 19132, 0, 0)

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, type=None: [(socket.AF_INET6, socket.SOCK_DGRAM, 17, "", ("::1", port, 0, 0))],
    )
    monkeypatch.setattr(socket, "socket", FakeSocket)

    config = replace(main.APP_CONFIG, server_host="::1", server_port=19132)
    status = check_server_status(config)

    assert status["status"] == "online"
    assert any(call[0] == "sendto" and call[1] == socket.AF_INET6 for call in calls)


def test_server_status_tries_next_address_family_before_unknown(monkeypatch):
    from mcbe_editor.server_status import check_server_status

    import main

    attempts = []
    pong = b"\x1c" + b"\x00" * 40

    class FakeSocket:
        def __init__(self, family, _socktype, _proto):
            self.family = family

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def settimeout(self, _timeout):
            pass

        def sendto(self, _packet, sockaddr):
            attempts.append((self.family, sockaddr))
            if self.family == socket.AF_INET:
                raise OSError("IPv4 unreachable")

        def recvfrom(self, _size):
            return pong, ("::1", 19132, 0, 0)

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, type=None: [
            (socket.AF_INET, socket.SOCK_DGRAM, 17, "", ("192.0.2.10", port)),
            (socket.AF_INET6, socket.SOCK_DGRAM, 17, "", ("2001:db8::10", port, 0, 0)),
        ],
    )
    monkeypatch.setattr(socket, "socket", FakeSocket)

    config = replace(main.APP_CONFIG, server_host="bedrock.example", server_port=19132)
    status = check_server_status(config)

    assert status["status"] == "online"
    assert [family for family, _sockaddr in attempts] == [socket.AF_INET, socket.AF_INET6]


def test_server_status_keeps_timeout_unknown_after_all_addresses_timeout(monkeypatch):
    from mcbe_editor.server_status import check_server_status

    import main

    class FakeSocket:
        def __init__(self, *_args):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def settimeout(self, _timeout):
            pass

        def sendto(self, _packet, _sockaddr):
            pass

        def recvfrom(self, _size):
            raise TimeoutError("timeout")

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, type=None: [
            (socket.AF_INET, socket.SOCK_DGRAM, 17, "", ("192.0.2.10", port)),
            (socket.AF_INET6, socket.SOCK_DGRAM, 17, "", ("2001:db8::10", port, 0, 0)),
        ],
    )
    monkeypatch.setattr(socket, "socket", FakeSocket)

    config = replace(main.APP_CONFIG, server_host="bedrock.example", server_port=19132)
    status = check_server_status(config)

    assert status["status"] == "unknown"
    assert "Keine Antwort" in status["message"]


def test_server_status_exposes_structured_message_for_dns_failure(monkeypatch):
    from mcbe_editor.server_status import check_server_status

    import main

    def fail_resolution(*_args, **_kwargs):
        raise OSError("DNS lookup failed")

    monkeypatch.setattr(socket, "getaddrinfo", fail_resolution)

    config = replace(main.APP_CONFIG, server_host="missing.example", server_port=19132)
    status = check_server_status(config)

    assert status["status"] == "unknown"
    assert status["message_key"] == "Serverstatus unbekannt: Serveradresse konnte nicht aufgelöst werden."
    assert status["message_params"] == {}
    assert status["message"] == "Serverstatus unbekannt: Serveradresse konnte nicht aufgelöst werden."
    assert status["technical_error"] == "DNS lookup failed"


def test_every_server_status_observation_gets_a_new_revision(monkeypatch):
    from mcbe_editor import server_status

    import main

    monkeypatch.setattr(
        server_status,
        "_bedrock_unconnected_ping",
        lambda *_args, **_kwargs: {
            "status": "unknown",
            "message": "Leere Serverantwort.",
            "message_key": "Leere Serverantwort.",
            "message_params": {},
        },
    )
    config = replace(main.APP_CONFIG, server_host="bedrock.example", server_port=19132)

    first = server_status.check_server_status(config)
    second = server_status.check_server_status(config)

    assert second["server_status_revision"] == first["server_status_revision"] + 1


def test_leveldb_adapter_runs_runtime_final_write_guard_before_open_and_put(monkeypatch):
    import sys

    from mcbe_editor.db import LevelDbAdapter

    calls = []

    class FakeDb:
        def get(self, _key):
            raise KeyError(_key)

        def put(self, key, value):
            calls.append(("put", key, value))

        def close(self):
            calls.append(("close",))

        def items(self):
            return iter(())

    fake_db = FakeDb()
    monkeypatch.setitem(sys.modules, "leveldb", SimpleNamespace(LevelDB=lambda _path: fake_db))
    monkeypatch.setitem(
        sys.modules,
        "main",
        SimpleNamespace(require_final_world_write_allowed=lambda label: calls.append(("guard", label))),
    )

    adapter = LevelDbAdapter("/tmp/world/db")
    adapter.put(b"player", b"data")

    assert calls == [
        ("guard", "LevelDB-Öffnen"),
        ("guard", "LevelDB-Schreiben"),
        ("put", b"player", b"data"),
    ]


def test_leveldb_adapter_uses_dunder_main_runtime_guard(monkeypatch):
    import sys

    from mcbe_editor.db import LevelDbAdapter

    calls = []

    class FakeDb:
        def put(self, key, value):
            calls.append(("put", key, value))

        def get(self, _key):
            raise KeyError(_key)

        def close(self):
            pass

        def items(self):
            return iter(())

    monkeypatch.setitem(sys.modules, "leveldb", SimpleNamespace(LevelDB=lambda _path: FakeDb()))
    monkeypatch.delitem(sys.modules, "main", raising=False)
    monkeypatch.setitem(
        sys.modules,
        "__main__",
        SimpleNamespace(require_final_world_write_allowed=lambda label: calls.append(("guard", label))),
    )

    adapter = LevelDbAdapter("/tmp/world/db")
    adapter.put(b"player", b"data")

    assert calls == [
        ("guard", "LevelDB-Öffnen"),
        ("guard", "LevelDB-Schreiben"),
        ("put", b"player", b"data"),
    ]


def test_leveldb_adapter_uses_registered_runtime_guard_without_app_module(monkeypatch):
    import sys

    from mcbe_editor import db as db_module
    from mcbe_editor.db import LevelDbAdapter, register_runtime_leveldb_write_guard

    calls = []

    class FakeDb:
        def put(self, key, value):
            calls.append(("put", key, value))

        def get(self, _key):
            raise KeyError(_key)

        def close(self):
            pass

        def items(self):
            return iter(())

    monkeypatch.setitem(sys.modules, "leveldb", SimpleNamespace(LevelDB=lambda _path: FakeDb()))
    # App läuft unter fremdem Modulnamen: weder main noch __main__ tragen den Guard.
    monkeypatch.delitem(sys.modules, "main", raising=False)
    monkeypatch.setitem(sys.modules, "__main__", SimpleNamespace())
    monkeypatch.setattr(db_module, "_registered_write_guard", None)
    register_runtime_leveldb_write_guard(lambda label: calls.append(("guard", label)))

    adapter = LevelDbAdapter("/tmp/world/db")
    adapter.put(b"player", b"data")

    assert calls == [
        ("guard", "LevelDB-Öffnen"),
        ("guard", "LevelDB-Schreiben"),
        ("put", b"player", b"data"),
    ]


def test_leveldb_adapter_does_not_open_when_runtime_final_write_guard_blocks(monkeypatch):
    import sys

    import pytest

    from mcbe_editor.db import LevelDbAdapter

    calls = []

    class FakeDb:
        def __init__(self, _path):
            calls.append(("open",))

        def put(self, _key, _value):
            calls.append(("put",))

        def get(self, _key):
            raise KeyError(_key)

        def close(self):
            pass

        def items(self):
            return iter(())

    def blocked_guard(_label):
        calls.append(("guard",))
        raise ValueError("final gate blocked")

    monkeypatch.setitem(sys.modules, "leveldb", SimpleNamespace(LevelDB=FakeDb))
    monkeypatch.setitem(sys.modules, "main", SimpleNamespace(require_final_world_write_allowed=blocked_guard))

    with pytest.raises(ValueError, match="final gate blocked"):
        LevelDbAdapter("/tmp/world/db")

    assert calls == [("guard",)]


@pytest.mark.parametrize("require_server_offline", [False, True])
def test_player_save_route_honors_explicit_unknown_server_confirmation(require_server_offline):
    """Route-level: das Bestätigungsflag muss aus dem Request-JSON gelesen und
    explizit an write_gate übergeben werden (kein implizites Flask-Coupling mehr)."""

    from unittest.mock import Mock, patch

    import main

    previous_epoch = main._SERVER_ONLINE_EPOCH
    previous_config = main.APP_CONFIG
    main._SERVER_ONLINE_EPOCH = 0
    main.APP_CONFIG = replace(
        main.APP_CONFIG,
        require_server_offline=require_server_offline,
        allow_edit_while_online=False,
        read_only=False,
    )
    guard_token = main.server_guard_token()
    try:
        with (
            patch("main.CSRF_TOKEN", "gate-token"),
            patch("mcbe_editor.server_status.check_server_status", return_value={"status": "unknown", "message": "keine Antwort"}),
            patch.object(main.editor_service, "save_player", Mock(return_value={"success": True})) as save_player,
        ):
            client = main.app.test_client()
            client.testing = True

            blocked = client.post(
                "/api/player/save",
                json={
                    "world_path": "C:/world",
                    "player_key": "local_player",
                    "server_guard_epoch": 0,
                    "server_guard_token": guard_token,
                },
                headers={"X-CSRF-Token": "gate-token"},
            )
            assert blocked.status_code == 409
            blocked_data = blocked.get_json()
            assert blocked_data["success"] is False
            assert blocked_data["write_gate"]["requires_unknown_server_confirmation"] is True
            save_player.assert_not_called()

            confirmed = client.post(
                "/api/player/save",
                json={
                    "world_path": "C:/world",
                    "player_key": "local_player",
                    "server_guard_epoch": 0,
                    "server_guard_token": guard_token,
                    "confirm_unknown_server_status": True,
                },
                headers={"X-CSRF-Token": "gate-token"},
            )
            assert confirmed.status_code == 200
            assert confirmed.get_json()["success"] is True
            save_player.assert_called_once()
    finally:
        main._SERVER_ONLINE_EPOCH = previous_epoch
        main.APP_CONFIG = previous_config
