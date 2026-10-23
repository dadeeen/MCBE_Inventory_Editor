"""Real worker deaths recover a catalog generation without playable fixtures."""

import hashlib
import json
import os
import subprocess
import sys
import time
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from mcbe_editor import item_db_transaction as transaction
from mcbe_editor import item_db_verification, update_script_runner

ROOT = Path(__file__).resolve().parents[1]
WORKER = r"""
import os
import time
from pathlib import Path
from scripts import update_db
from mcbe_editor import item_db_transaction as transaction
stage = os.environ.get("FAULT_STAGE", "")
def boundary(name):
    if stage != name:
        return
    if os.environ.get("FAULT_WAIT"):
        Path(os.environ["FAULT_WAIT"]).write_text("ready")
        while not Path(os.environ["FAULT_WAIT"] + ".continue").exists():
            time.sleep(0.02)
    elif os.environ.get("FAULT_SLEEP"):
        time.sleep(60)
    else:
        os._exit(91)
for name, point in [("write_all_dicts", "items"), ("write_source_version", "source"), ("append_source_version_history", "history")]:
    original = getattr(update_db, name)
    def wrapped(*args, _original=original, _point=point, **kwargs):
        result = _original(*args, **kwargs)
        boundary(_point)
        return result
    setattr(update_db, name, wrapped)
original_save = transaction._save_journal
def save(path, data):
    original_save(path, data)
    boundary(data["phase"])
transaction._save_journal = save
update_db.commit_update_files(
    {"minecraft:stone": ("Stein", "Stone")}, {}, {},
    block_only_items=[], block_items=[], addable_items=["minecraft:stone"],
    write_item_db=True, source_metadata={"resource_pack_release": "new"}, verify_item_db=True,
)
"""


@pytest.mark.parametrize("reserved_index", [1, 2])
def test_configuration_rejects_journal_as_a_publication_target(tmp_path, reserved_index):
    targets = [tmp_path / "item_db.json", tmp_path / "source.json", tmp_path / "history.json"]
    targets[reserved_index] = transaction.journal_path(targets)
    with pytest.raises(transaction.ItemDbRecoveryError, match="journal cannot be a publication target"):
        transaction.configured_targets(*targets)
    assert not list(tmp_path.iterdir())


@pytest.fixture
def generation(tmp_path):
    targets = transaction.configured_targets(
        tmp_path / "catalog" / "item_db.json",
        tmp_path / "provenance" / "source_version.json",
        tmp_path / "history" / "source_version_history.json",
    )
    contents = [
        {"schema_version": 3, "items": {"minecraft:dirt": ["Erde", "Dirt"]}, "effects": {}, "enchantments": {}},
        {"resource_pack_release": "old"},
        [{"resource_pack_release": "old"}],
    ]
    for path, data in zip(targets, contents, strict=True):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data) + "\n", encoding="utf-8")
    env = {key: value for key, value in os.environ.items() if not key.startswith("MCBE_")}
    env.update(
        PYTHONPATH=str(ROOT),
        MCBE_DATA_ROOT=str(tmp_path / "data"),
        MCBE_ITEM_DB_PATH=str(targets[0]),
        MCBE_SOURCE_VERSION_PATH=str(targets[1]),
        MCBE_SOURCE_VERSION_HISTORY_PATH=str(targets[2]),
    )
    return targets, env, {path: path.read_bytes() for path in targets}


def _worker(env, **kwargs):
    return subprocess.run([sys.executable, "-c", WORKER], cwd=ROOT, env=env, capture_output=True, text=True, **kwargs)


def _assert_new_generation(targets):
    catalog = json.loads(targets[0].read_text(encoding="utf-8"))
    metadata = json.loads(targets[1].read_text(encoding="utf-8"))
    history = json.loads(targets[2].read_text(encoding="utf-8"))
    assert catalog["items"] == {"minecraft:stone": ["Stein", "Stone"]}
    assert metadata["resource_pack_release"] == "new"
    assert metadata["verification"]["item_db_sha256"] == hashlib.sha256(targets[0].read_bytes()).hexdigest()
    assert metadata["verification"]["source_identity_sha256"] == item_db_verification.source_identity_sha256(metadata)
    assert history[-1] == metadata


@pytest.mark.parametrize("stage", ["prepared", "items", "source", "history", "committed"])
@pytest.mark.parametrize("restart", [False, True])
def test_abrupt_worker_death_at_every_publication_boundary(generation, stage, restart):
    targets, env, originals = generation
    result = _worker(dict(env, FAULT_STAGE=stage), timeout=30)
    assert result.returncode == 91, result.stderr
    assert transaction.journal_path(targets).exists()
    if restart:
        result = subprocess.run(
            [sys.executable, "-c", "from mcbe_editor import runtime_bootstrap"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
    else:
        assert transaction.recover_item_db(targets) == ("committed" if stage == "committed" else "rolled_back")
    if stage == "committed":
        _assert_new_generation(targets)
    else:
        assert {path: path.read_bytes() for path in targets} == originals
    assert transaction.recover_item_db(targets) == "none"


@pytest.mark.parametrize("stage", ["items", "committed"])
@pytest.mark.parametrize("timeout", [False, True])
def test_parent_recovers_after_real_child_exit_or_timeout(generation, monkeypatch, stage, timeout):
    targets, env, originals = generation
    config = SimpleNamespace(
        item_db_path=str(targets[0]),
        source_version_path=str(targets[1]),
        source_version_history_path=str(targets[2]),
        data_root=env["MCBE_DATA_ROOT"],
        update_cache_dir=str(targets[0].parent / "cache"),
    )

    def run_child(cmd, **kwargs):
        child_env = dict(kwargs["env"], FAULT_STAGE=stage)
        if timeout:
            child_env["FAULT_SLEEP"] = "1"
        return _worker(child_env, timeout=3 if timeout else 30)

    monkeypatch.setattr(update_script_runner, "_run_update", run_child)
    with pytest.raises(update_script_runner.ItemDbUpdateInterruptedError) as caught:
        update_script_runner.run_update_db(ROOT, config, force=True)
    assert caught.value.timed_out is timeout
    assert caught.value.recovery == ("committed" if stage == "committed" else "rolled_back")
    if stage == "committed":
        _assert_new_generation(targets)
    else:
        assert {path: path.read_bytes() for path in targets} == originals


@pytest.mark.parametrize("tamper", ["path", "snapshot", "committed"])
def test_recovery_validates_journal_before_any_target_mutation(generation, tamper):
    targets, env, _ = generation
    result = _worker(dict(env, FAULT_STAGE="committed" if tamper == "committed" else "history"), timeout=30)
    assert result.returncode == 91, result.stderr
    journal_path = transaction.journal_path(targets)
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    if tamper == "path":
        journal["entries"][-1]["path"] = str(targets[-1].with_name("other.json"))
    elif tamper == "snapshot":
        journal["entries"][-1]["old_sha256"] = "0" * 64
    else:
        targets[0].write_bytes(b"unrelated edit")
    journal_path.write_text(json.dumps(journal), encoding="utf-8")
    before = {path: path.read_bytes() for path in targets}
    with pytest.raises(transaction.ItemDbRecoveryError):
        transaction.recover_item_db(targets)
    assert journal_path.exists()
    assert {path: path.read_bytes() for path in targets} == before


def test_completed_partial_update_keeps_its_report_after_committed_recovery(generation, monkeypatch):
    from mcbe_editor.update_db_report import REPORT_PREFIX

    targets, _env, _originals = generation
    output = REPORT_PREFIX + json.dumps({"schema": 1, "status": "incomplete", "applied": True})
    config = SimpleNamespace(
        item_db_path=str(targets[0]),
        source_version_path=str(targets[1]),
        source_version_history_path=str(targets[2]),
        update_cache_dir=str(targets[0].parent / "cache"),
    )

    def run_child(*args, **kwargs):
        result = _worker(kwargs["env"], timeout=30)
        assert result.returncode == 0, result.stderr
        return subprocess.CompletedProcess(args[0], 1, stdout=output)

    monkeypatch.setattr(update_script_runner, "_run_update", run_child)
    assert update_script_runner.run_update_db(ROOT, config, force=True) == (1, output)
    _assert_new_generation(targets)
    assert not transaction.journal_path(targets).exists()


def test_recovery_after_death_during_rollback_is_idempotent(generation):
    targets, env, originals = generation
    assert _worker(dict(env, FAULT_STAGE="history"), timeout=30).returncode == 91
    recovery = r"""
import os
from mcbe_editor import item_db_transaction as transaction
original = transaction._restore
def restore(path, content):
    original(path, content)
    os._exit(92)
transaction._restore = restore
transaction.recover_item_db(transaction.configured_targets(
    os.environ["MCBE_ITEM_DB_PATH"], os.environ["MCBE_SOURCE_VERSION_PATH"], os.environ["MCBE_SOURCE_VERSION_HISTORY_PATH"]))
"""
    result = subprocess.run([sys.executable, "-c", recovery], env=env, cwd=ROOT, timeout=30)
    assert result.returncode == 92
    assert transaction.recover_item_db(targets) == "rolled_back"
    assert {path: path.read_bytes() for path in targets} == originals


def test_recovery_removes_targets_absent_in_old_generation(generation):
    targets, env, originals = generation
    targets[1].unlink()
    targets[2].unlink()
    assert _worker(dict(env, FAULT_STAGE="history"), timeout=30).returncode == 91
    assert transaction.recover_item_db(targets) == "rolled_back"
    assert targets[0].read_bytes() == originals[targets[0]]
    assert not targets[1].exists()
    assert not targets[2].exists()


def test_cli_restart_recovers_before_reading_cached_inputs(generation):
    targets, env, originals = generation
    assert _worker(dict(env, FAULT_STAGE="source"), timeout=30).returncode == 91
    result = subprocess.run(
        [sys.executable, "-m", "scripts.update_db", "--dry-run", "--cache"],
        env=env,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    # No network or cached sources: the later input error must not prevent recovery.
    assert result.returncode != 0
    assert {path: path.read_bytes() for path in targets} == originals
    assert not transaction.journal_path(targets).exists()


def test_failed_rollback_preserves_journal_for_next_attempt(generation, monkeypatch):
    targets, env, originals = generation
    assert _worker(dict(env, FAULT_STAGE="history"), timeout=30).returncode == 91
    original_restore = transaction._restore

    def denied_restore(path, content):
        if path == targets[1]:
            raise PermissionError("locked provenance")
        original_restore(path, content)

    with monkeypatch.context() as patch:
        patch.setattr(transaction, "_restore", denied_restore)
        with pytest.raises(transaction.ItemDbRecoveryError):
            transaction.recover_item_db(targets)
    assert transaction.journal_path(targets).exists()
    assert transaction.recover_item_db(targets) == "rolled_back"
    assert {path: path.read_bytes() for path in targets} == originals


def test_recovery_waits_for_active_commit(generation, tmp_path):
    targets, env, _ = generation
    ready = tmp_path / "worker-ready"
    recovery_ready = tmp_path / "recovery-ready"
    recover = r"""
import os
from pathlib import Path
from mcbe_editor import item_db_transaction as transaction
Path(os.environ["RECOVERY_READY"]).write_text("ready")
print(transaction.recover_item_db(transaction.configured_targets(
    os.environ["MCBE_ITEM_DB_PATH"], os.environ["MCBE_SOURCE_VERSION_PATH"], os.environ["MCBE_SOURCE_VERSION_HISTORY_PATH"])))
"""
    worker = subprocess.Popen([sys.executable, "-c", WORKER], cwd=ROOT, env=dict(env, FAULT_STAGE="items", FAULT_WAIT=str(ready)))
    recovery = None
    try:
        deadline = time.monotonic() + 15
        while not ready.exists() and worker.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.exists()
        recovery = subprocess.Popen(
            [sys.executable, "-c", recover],
            cwd=ROOT,
            env=dict(env, RECOVERY_READY=str(recovery_ready)),
            stdout=subprocess.PIPE,
            text=True,
        )
        while not recovery_ready.exists() and recovery.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert recovery_ready.exists()
        time.sleep(0.1)
        assert recovery.poll() is None
        Path(str(ready) + ".continue").write_text("continue")
        assert worker.wait(timeout=15) == 0
        output, _ = recovery.communicate(timeout=15)
        assert recovery.returncode == 0
        assert output.strip() == "committed"
        _assert_new_generation(targets)
    finally:
        for process in [worker, recovery]:
            if process is not None and process.poll() is None:
                process.kill()
                process.wait(timeout=10)


@pytest.mark.parametrize("consumer", ["bootstrap", "cli"])
def test_concurrent_startup_cannot_acknowledge_a_live_parents_committed_worker(generation, tmp_path, monkeypatch, consumer):
    targets, env, _ = generation
    ready = tmp_path / "consumer-ready"
    recovered = tmp_path / "consumer-recovered"
    contender_code = r"""
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from mcbe_editor import item_db_transaction as transaction
original_lock = transaction.locked_operation
@contextmanager
def observed_lock(name, **kwargs):
    if name == "item-db-update":
        Path(os.environ["CONSUMER_READY"]).write_text("ready")
    with original_lock(name, **kwargs):
        yield
transaction.locked_operation = observed_lock
original_recovery = transaction._recover_locked
def observed_recovery(*args, **kwargs):
    result = original_recovery(*args, **kwargs)
    Path(os.environ["CONSUMER_RECOVERED"]).write_text(result)
    return result
transaction._recover_locked = observed_recovery
if os.environ["CONSUMER"] == "bootstrap":
    from mcbe_editor import runtime_bootstrap
else:
    from scripts import update_db
    sys.argv = ["update_db", "--dry-run", "--cache"]
    try:
        update_db.main()
    except RuntimeError:
        # This synthetic fixture deliberately has no cached online inputs.
        pass
"""
    config = SimpleNamespace(
        item_db_path=str(targets[0]),
        source_version_path=str(targets[1]),
        source_version_history_path=str(targets[2]),
        data_root=env["MCBE_DATA_ROOT"],
        update_cache_dir=str(tmp_path / "empty-cache"),
    )
    contenders = []

    def run_child(cmd, **kwargs):
        result = _worker(dict(kwargs["env"], FAULT_STAGE="committed"), timeout=15)
        assert result.returncode == 91, result.stderr
        assert transaction.journal_path(targets).exists()
        # This is a separate app/CLI process, not the parent's managed worker.
        contender_env = dict(env, CONSUMER=consumer, CONSUMER_READY=str(ready), CONSUMER_RECOVERED=str(recovered))
        contender = subprocess.Popen([sys.executable, "-c", contender_code], cwd=ROOT, env=contender_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        contenders.append(contender)
        deadline = time.monotonic() + 15
        while not ready.exists() and contender.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.exists()
        time.sleep(0.1)
        assert contender.poll() is None
        assert not recovered.exists()
        assert transaction.journal_path(targets).exists()
        return result

    monkeypatch.setattr(update_script_runner, "_run_update", run_child)
    try:
        with pytest.raises(update_script_runner.ItemDbUpdateInterruptedError) as caught:
            # This direct caller has no web decorator holding the outer lock.
            update_script_runner.run_update_db(ROOT, config, force=True)
        assert caught.value.recovery == "committed"
        for contender in contenders:
            output, errors = contender.communicate(timeout=15)
            assert contender.returncode == 0, (output, errors)
        assert recovered.read_text() == "none"
        _assert_new_generation(targets)
    finally:
        for contender in contenders:
            if contender.poll() is None:
                contender.kill()
                contender.wait(timeout=10)


@pytest.mark.parametrize("outer_lock", [False, True])
def test_parent_managed_cli_skips_only_its_parents_outer_lock(generation, tmp_path, monkeypatch, outer_lock):
    targets, env, _ = generation
    config = SimpleNamespace(
        item_db_path=str(targets[0]),
        source_version_path=str(targets[1]),
        source_version_history_path=str(targets[2]),
        data_root=env["MCBE_DATA_ROOT"],
        update_cache_dir=str(tmp_path / "empty-cache"),
    )

    def bounded_child(cmd, **kwargs):
        assert kwargs["env"][transaction.PARENT_LOCK_ENV] == str(targets[0])
        # A regression would deadlock against the parent's outer lock. Keep
        # that failure bounded independently of the production 180s timeout.
        return subprocess.run(cmd, **dict(kwargs, timeout=10))

    monkeypatch.setattr(update_script_runner, "_run_update", bounded_child)
    with transaction.item_db_update_operation(targets) if outer_lock else nullcontext():
        returncode, output = update_script_runner.run_update_db(ROOT, config, dry_run=True, use_cache=True)
    assert returncode == 1
    assert "Kein gecachtes Resource-Pack" in output


def test_parent_lock_marker_does_not_bypass_another_catalogs_lock(generation, monkeypatch):
    targets, _, _ = generation
    monkeypatch.setenv(transaction.PARENT_LOCK_ENV, str(targets[0].with_name("other.json")))
    calls = []

    def observed_lock(name, **kwargs):
        calls.append((name, kwargs))
        return nullcontext()

    monkeypatch.setattr(transaction, "locked_operation", observed_lock)
    with transaction.item_db_update_operation(targets, allow_parent_lock=True):
        pass
    assert calls == [("item-db-update", {"root": targets[0].parent})]
