"""Malformed persisted auth modes must remain recoverable and fail closed."""

import json

import pytest

from mcbe_editor.setup_state import FirstRunSetup


@pytest.mark.parametrize("value", [[], {}, ["password"], {"value": "open"}, None, True, 42, "unknown"])
def test_invalid_persisted_mode_stays_pending_until_explicit_setup(tmp_path, value):
    path = tmp_path / "setup.json"
    path.write_text(json.dumps({"auth_mode": value, "risk_acknowledged": True}), encoding="utf-8")
    original = path.read_bytes()
    setup = FirstRunSetup(path)

    summary = setup.summary()

    assert summary.mode == "pending"
    assert summary.completed is False
    assert setup.open_acknowledged() is False
    assert setup.password_hash() is None
    assert path.read_bytes() == original

    # A malformed mode is not an acknowledged decision, but an explicit new
    # setup decision can replace it through the normal locked write path.
    setup.save_open()
    recovered = FirstRunSetup(path)
    assert recovered.summary().mode == "open"
    assert recovered.completed() is True
    assert recovered.open_acknowledged() is True


@pytest.mark.parametrize("mode", ["password", "open"])
def test_recognized_mode_alone_does_not_mark_setup_completed(tmp_path, mode):
    path = tmp_path / "setup.json"
    path.write_text(json.dumps({"auth_mode": mode}), encoding="utf-8")
    setup = FirstRunSetup(path)

    summary = setup.summary()

    assert summary.mode == mode
    assert summary.completed is False
    assert setup.open_acknowledged() is False
    assert setup.password_hash() is None
