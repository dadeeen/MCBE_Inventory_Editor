"""A write condition follows the final adapter gate and cannot become a retry."""

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest

from mcbe_editor.db import LevelDbAdapter
from mcbe_editor.service_errors import WriteNotAttemptedError
from mcbe_editor.write_transaction import WritePhase, WritePlan, WriteState


def _plan(batch, check):
    return WritePlan({b"changed": b"value"}, precondition=check) if batch else WritePlan.single(b"changed", b"value", precondition=check)


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "db"
    path.mkdir()
    return path


class _PlainDb:
    """An injected/offline adapter without the optional late-condition hook."""

    def __init__(self):
        self.records = {b"original": b"kept"}
        self.writes = 0

    def put(self, key, value):
        self.put_batch({key: value})

    def put_batch(self, records):
        self.writes += 1
        self.records.update(records)

    def last_write_reached_log(self):
        return True


@pytest.mark.parametrize("batch", [False, True])
@pytest.mark.parametrize("allowed", [False, True])
def test_plain_adapter_runs_condition_and_consumes_state_once(batch, allowed):
    db = _PlainDb()
    original = dict(db.records)
    error = ValueError("world changed")
    check = Mock(side_effect=None if allowed else error)
    state = WriteState()
    plan = _plan(batch, check)
    if allowed:
        state.execute(db, plan)
        assert state.committed and db.writes == 1
        assert db.records == {**original, b"changed": b"value"}
    else:
        with pytest.raises(ValueError) as raised:
            state.execute(db, plan)
        assert raised.value is error
        assert state.phase is WritePhase.PREPARED and not state.attempted
        assert not state.outcome_unknown and not state.storage_possibly_changed
        assert db.records == original and db.writes == 0
    check.assert_called_once_with()
    with pytest.raises(RuntimeError, match="bereits versucht"):
        state.execute(db, plan)
    assert db.writes == int(allowed)


@pytest.mark.parametrize("batch", [False, True])
def test_adapter_condition_observes_its_final_gate_and_discards_old_write_evidence(db_path, batch):
    observed = []
    error = ValueError("metadata changed at the last gate")

    def gate(action):
        observed.append(action)

    def reject():
        observed.append("condition")
        raise error

    db = LevelDbAdapter(str(db_path), write_guard=gate)
    try:
        db.put(b"original", b"kept")
        assert db.last_write_reached_log()
        original = dict(db.iter_items())
        # The live writer holds an exclusive OS lock on LOCK on Windows.
        # Compare all data files; the lock's contents are not database state.
        files = {path.name: path.read_bytes() for path in db_path.iterdir() if path.name != "LOCK"}
        observed.clear()
        state = WriteState()
        with pytest.raises(ValueError) as raised:
            state.execute(db, _plan(batch, reject))
        assert raised.value is error
        assert observed == ["LevelDB-Batch-Schreiben" if batch else "LevelDB-Schreiben", "condition"]
        assert not state.attempted and not state.outcome_unknown
        assert dict(db.iter_items()) == original
        assert {path.name: path.read_bytes() for path in db_path.iterdir() if path.name != "LOCK"} == files
        with pytest.raises(RuntimeError):
            state.execute(db, _plan(batch, lambda: None))
        # Failure must leave no condition behind on this still-open adapter.
        db.put(b"later-operation", b"allowed")
        assert observed.count("condition") == 1
    finally:
        db.close()


def test_nested_adapter_conditions_restore_outer_scope_after_failure(db_path):
    outer = Mock()
    inner_error = ValueError("inner condition rejected")
    inner = Mock(side_effect=inner_error)
    db = LevelDbAdapter(str(db_path))
    try:
        with db.write_precondition(outer):
            with pytest.raises(ValueError) as raised:
                WriteState().execute(db, _plan(True, inner))
            assert raised.value is inner_error
            outer.assert_not_called()
            db.put(b"outer", b"restored")
        db.put(b"outside", b"unbound")
        inner.assert_called_once_with()
        outer.assert_called_once_with()
        assert dict(db.iter_items()) == {b"outer": b"restored", b"outside": b"unbound"}
    finally:
        db.close()


def test_adapter_condition_does_not_leak_to_another_thread(db_path):
    reject = Mock(side_effect=ValueError("condition belongs only to its operation"))
    db = LevelDbAdapter(str(db_path))
    try:
        with db.write_precondition(reject):
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(db.put, b"other-thread", b"unbound").result(timeout=5)
            reject.assert_not_called()
            with pytest.raises(ValueError):
                db.put(b"current-thread", b"blocked")
        assert dict(db.iter_items()) == {b"other-thread": b"unbound"}
    finally:
        db.close()


@pytest.mark.parametrize("batch", [False, True])
def test_successful_condition_does_not_hide_a_later_writer_failure(db_path, batch):
    error = OSError("write response lost")

    class FailingWriter(LevelDbAdapter):
        def put(self, key, value):
            super().put(key, value)
            raise error

        def put_batch(self, records):
            super().put_batch(records)
            raise error

    db = FailingWriter(str(db_path))
    try:
        state, check = WriteState(), Mock()
        with pytest.raises(OSError) as raised:
            state.execute(db, _plan(batch, check))
        assert raised.value is error
        check.assert_called_once_with()
        assert state.attempted and not state.committed and state.outcome_unknown
        assert dict(db.iter_items()) == {b"changed": b"value"}
        with pytest.raises(RuntimeError):
            state.execute(db, _plan(batch, check))
        check.assert_called_once_with()
    finally:
        db.close()


def test_adapter_gate_rejection_precedes_the_bound_condition(db_path):
    error = WriteNotAttemptedError("server restarted")

    def gate(action):
        if action == "LevelDB-Batch-Schreiben":
            raise error

    db = LevelDbAdapter(str(db_path), write_guard=gate)
    try:
        state, check = WriteState(), Mock()
        with pytest.raises(WriteNotAttemptedError) as raised:
            state.execute(db, _plan(True, check))
        assert raised.value is error
        check.assert_not_called()
        assert not state.outcome_unknown and not state.committed
        assert not dict(db.iter_items())
    finally:
        db.close()
