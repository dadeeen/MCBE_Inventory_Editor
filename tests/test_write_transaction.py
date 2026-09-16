from unittest.mock import Mock

import pytest

from mcbe_editor.write_transaction import WritePhase, WritePlan, WriteState


def test_prepared_batch_cannot_be_changed_by_its_builder():
    writes = {b"player": b"prepared", b"obsolete": None}
    plan = WritePlan(writes)
    writes[b"player"] = b"later"
    writes[b"unreviewed"] = b"unexpected"
    with pytest.raises(TypeError):
        plan.writes[b"player"] = b"changed"
    db = Mock()
    state = WriteState()
    state.execute(db, plan)
    db.put_batch.assert_called_once_with({b"player": b"prepared", b"obsolete": None})
    db.put.assert_not_called()
    assert state.committed
    with pytest.raises(RuntimeError, match="bereits versucht"):
        state.execute(db, plan)
    assert db.put_batch.call_count == 1


@pytest.mark.parametrize("batch", [False, True])
def test_failed_attempt_is_not_a_confirmed_commit_and_cannot_be_retried(batch):
    db = Mock()
    write = db.put_batch if batch else db.put
    write.side_effect = OSError("storage may already have changed")
    state = WriteState()
    plan = WritePlan({b"key": b"value"}) if batch else WritePlan.single(b"key", b"value")
    with pytest.raises(OSError):
        state.execute(db, plan)
    assert state.phase is WritePhase.ATTEMPTED
    assert state.attempted
    assert not state.committed
    with pytest.raises(RuntimeError):
        state.execute(db, plan)
    assert write.call_count == 1


@pytest.mark.parametrize("entries,mode", [({}, "batch"), ({"key": b"value"}, "batch"), ({b"key": "value"}, "batch"),
                                         ({b"key": None}, "single"), ({b"a": b"a", b"b": b"b"}, "single"), ({b"key": b"value"}, "other")])
def test_invalid_plans_fail_before_an_attempt(entries, mode):
    state = WriteState()
    with pytest.raises(ValueError):
        WritePlan(entries, mode=mode)
    assert not state.attempted


def test_single_record_success_uses_put_and_records_commit():
    db = Mock()
    state = WriteState()
    state.execute(db, WritePlan.single(b"key", b"value"))
    db.put.assert_called_once_with(b"key", b"value")
    db.put_batch.assert_not_called()
    assert state.phase is WritePhase.COMMITTED
