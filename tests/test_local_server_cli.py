from __future__ import annotations

import ast
from pathlib import Path


def test_embedded_make_server_call_uses_supported_keywords() -> None:
    tree = ast.parse(Path("main.py").read_text(encoding="utf-8"))
    make_server_calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "make_server"]
    assert make_server_calls, "main.py should create the local embedded server with make_server()"
    forbidden = {"use_debugger", "use_reloader"}
    for call in make_server_calls:
        used_keywords = {keyword.arg for keyword in call.keywords if keyword.arg}
        assert not (used_keywords & forbidden)


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
