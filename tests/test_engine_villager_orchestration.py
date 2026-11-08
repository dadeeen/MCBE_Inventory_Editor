"""The native villager profile cannot pass with missing stages or worker checks."""

from __future__ import annotations

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from scripts.engine_checks import runner
from scripts.engine_checks.protocol import ProbeError
from scripts.engine_checks.villager_profile import SUPPLY_IDS, make_villager_cases


def _run(tmp_path, monkeypatch, *, damaged_phase=None, missing_check=None, worker_failure=None):
    observations = {item: {"max_amount": 64} for item in SUPPLY_IDS}
    limits = dict.fromkeys(SUPPLY_IDS, 64)
    cases = make_villager_cases(observations, limits)
    report = {"phases": {}, "not_covered": []}
    config = {}
    sequence = []

    def phase(name):
        sequence.append(name)
        report["phases"][name] = "observed"
        stage = "revised" if name in {"reload3", "reload4"} else "edited" if name in {"reload1", "reload2"} else "seed"
        events = [{"kind": "case", "case_id": case["case_id"], "snapshot": {"type": "minecraft:villager_v2", **deepcopy(case[stage])}} for case in cases]
        if name == damaged_phase:
            events.pop()
        return events

    def worker(directory, action, *, module):
        assert directory == tmp_path and module == "scripts.engine_checks.villager_worker"
        published = json.loads((directory / "run.json").read_text(encoding="utf-8"))
        assert published["phases"]["seed"] == "pass"
        if action in {"edit", "revise"}:
            assert published["phases"]["warmup2"] == "pass"
        if action == "revise":
            assert published["phases"]["reload2"] == "pass"
        current = sequence[-1]
        sequence.append("worker:" + action)
        if current == worker_failure:
            raise ProbeError("Independent disk observer rejected changed data")
        result = {"status": "pass", "cases": len(cases)}
        if action in {"edit", "revise"}:
            result.update(
                backed_up_saves=1 if action == "revise" else 22,
                no_op_checks=22,
                stale_revision_rejections=1 if action == "revise" else 22,
                central_workspace=action == "revise",
            )
            if missing_check:
                result[missing_check] = 0
        return result

    monkeypatch.setattr(runner, "nbt_worker", worker)
    runner.run_villager_checks(tmp_path, report, config, phase, observations, limits)
    return report, sequence, config


def test_villager_orchestration_observes_four_reloads_and_two_prewrite_warmups(tmp_path, monkeypatch):
    report, sequence, config = _run(tmp_path, monkeypatch)
    assert sequence == [
        "seed",
        "worker:seed",
        "warmup1",
        "worker:warmup1",
        "warmup2",
        "worker:warmup2",
        "worker:edit",
        "reload1",
        "worker:verify",
        "reload2",
        "worker:verify",
        "worker:revise",
        "reload3",
        "worker:verify",
        "reload4",
        "worker:verify",
    ]
    assert config["villager_profile"] and len(config["cases"]) == 24
    assert report["villagers"] == {
        "status": "pass",
        "cases": 24,
        "warmup_cycles": 2,
        "reload_cycles": 4,
        "backed_up_saves": 23,
        "no_op_checks": 44,
        "stale_revision_rejections": 23,
    }
    assert all(value == "pass" for value in report["phases"].values())


@pytest.mark.parametrize("phase", ["seed", "warmup1", "warmup2", "reload1", "reload2", "reload3", "reload4"])
def test_missing_engine_actor_in_any_stage_prevents_passing(tmp_path, monkeypatch, phase):
    with pytest.raises(ProbeError, match="omitted"):
        _run(tmp_path, monkeypatch, damaged_phase=phase)


@pytest.mark.parametrize("phase", ["reload1", "reload2", "reload3", "reload4"])
def test_each_reload_requires_successful_independent_disk_verification(tmp_path, monkeypatch, phase):
    with pytest.raises(ProbeError, match="disk observer"):
        _run(tmp_path, monkeypatch, worker_failure=phase)


@pytest.mark.parametrize("field", ["backed_up_saves", "no_op_checks", "stale_revision_rejections"])
def test_normal_worker_exit_cannot_hide_missing_service_checks(tmp_path, monkeypatch, field):
    with pytest.raises(ProbeError, match="every planned service check"):
        _run(tmp_path, monkeypatch, missing_check=field)


def test_villager_worker_has_isolated_environment_and_complete_result_contract(tmp_path, monkeypatch):
    monkeypatch.setenv("MCBE_READ_ONLY", "true")
    monkeypatch.setenv("MCBE_WORLDS_ROOT", "PRIVATE_REAL_WORLD")
    runner.write_json(tmp_path / "cases.json", [{"case_id": "test"}])

    def subprocess_run(command, **kwargs):
        assert command[2] == "scripts.engine_checks.villager_worker"
        assert "MCBE_READ_ONLY" not in kwargs["env"] and "MCBE_WORLDS_ROOT" not in kwargs["env"]
        assert kwargs["env"]["MCBE_DATA_ROOT"] == str(tmp_path / "app-data")
        return SimpleNamespace(returncode=0, stdout='{"status":"pass","cases":0}', stderr="")

    monkeypatch.setattr(runner.subprocess, "run", subprocess_run)
    with pytest.raises(ProbeError, match="every planned case"):
        runner.nbt_worker(tmp_path, "seed", module="scripts.engine_checks.villager_worker")


def test_public_villager_summary_excludes_private_records_and_paths():
    report = {
        "status": "pass",
        "suite": "villagers",
        "engine": {},
        "editor": {},
        "catalog_sha256": "a" * 64,
        "phases": {},
        "not_covered": [],
        "villagers": {"status": "pass", "cases": 24, "backed_up_saves": 23, "actor_data": "PRIVATE_NBT", "backup": "PRIVATE_PATH"},
        "villager_results": {"edit": {"log": "PRIVATE_LOG"}},
    }
    summary = runner.public_summary(report)
    assert summary["villagers"] == {"status": "pass", "cases": 24, "backed_up_saves": 23}
    assert "PRIVATE_" not in json.dumps(summary)
