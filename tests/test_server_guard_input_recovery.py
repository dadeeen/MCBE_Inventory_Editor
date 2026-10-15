"""A damaged shared token must be replaced, not break constant-time comparisons."""

import json
import secrets

import pytest

from mcbe_editor.server_guard import ServerGuardStore


@pytest.mark.parametrize("token", ["ä", "😀", "\ud800", [], None])
@pytest.mark.parametrize("operation", ["current", "observe"])
def test_invalid_stored_token_is_replaced_and_shared(tmp_path, token, operation):
    path = tmp_path / "server_guard_state.json"
    first = ServerGuardStore(path)
    first.current()
    second = ServerGuardStore(path)
    old_token = second.current()
    # Mutate after initialization: a new worker already rotates unconditionally.
    path.write_text(json.dumps({"version": 1, "token": token}), encoding="utf-8")

    if operation == "current":
        recovered = first.current()
    else:
        observation = first.observe(online=False)
        assert observation.previous_token == observation.token
        recovered = observation.token

    assert recovered != old_token
    assert recovered and recovered.isascii()
    assert secrets.compare_digest(recovered, recovered)
    assert json.loads(path.read_text(encoding="utf-8"))["token"] == recovered
    assert second.current() == recovered
