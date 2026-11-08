"""Interactive village checks require every real-client and disk observation."""

from __future__ import annotations

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from scripts.engine_checks import runner
from scripts.engine_checks.protocol import ProbeError
from scripts.engine_checks.village_profile import make_village_plan
from tests.test_engine_village import village_events


def _run(tmp_path, monkeypatch, *, missing=None, failure=None, worker_mutation=None):
    report = {"phases": {}, "not_covered": []}
    config = {}
    sequence = []
    observed_configs = []
    worker_results = []
    active_phase = None

    def phase(name):
        nonlocal active_phase
        active_phase = name
        sequence.append(name)
        observed_configs.append(deepcopy(config))
        if worker_results:
            assert config["village_expected"] == worker_results[-1]["expected"]
            assert config["village_expected"] is not worker_results[-1]["expected"]
            assert config["village_expected"]["farmer"] is not worker_results[-1]["expected"]["farmer"]
        report["phases"][name] = "observed"
        if failure == name:
            raise ProbeError("Real client did not complete this phase")
        events = village_events(name)
        if missing and missing[0] == name:
            events = [event for event in events if event.get("case_id") != missing[1]]
        return events

    def worker(directory, action, *, module):
        assert directory == tmp_path
        assert module == "scripts.engine_checks.village_worker"
        assert action == ("edit" if active_phase == "seed" else "verify")
        sequence.append("worker:" + action)
        published = json.loads((directory / "run.json").read_text(encoding="utf-8"))
        assert published["phases"][active_phase] == "pass"
        evidence = json.loads((directory / f"{active_phase}.village.json").read_text(encoding="utf-8"))
        assert evidence["phase"] == active_phase and evidence["status"] == "pass"
        expected = deepcopy(evidence["observations"]["chunk_reload"]["actors"])
        result = {"status": "pass", "native_trades": 1, "expected": expected}
        if action == "edit":
            result["backed_up_saves"] = 2
            expected["injured"].update(current=40, maximum=40)
            expected["farmer"]["items"] = [{"name": "minecraft:carrot", "count": 4}] + [None] * 7
        else:
            result["verified_reloads"] = 1 if active_phase == "reload1" else 2
        if worker_mutation and worker_mutation[0] == active_phase:
            field, value = worker_mutation[1:]
            if value == "omit":
                result.pop(field)
            else:
                result[field] = value
        worker_results.append(result)
        return result

    monkeypatch.setattr(runner, "nbt_worker", worker)
    runner.run_village_checks(tmp_path, report, config, phase)
    return report, sequence, observed_configs


def test_village_requires_three_interactions_and_two_independent_reload_checks(tmp_path, monkeypatch):
    report, sequence, configs = _run(tmp_path, monkeypatch)
    assert sequence == ["seed", "worker:edit", "reload1", "worker:verify", "reload2", "worker:verify"]
    assert all(config["village_profile"] == make_village_plan() for config in configs)
    expected = {
        "status": "pass",
        "required_connections": 3,
        "completed_connections": 3,
        "backed_up_saves": 2,
        "trades": 3,
        "pickups": 3,
        "chunk_reloads": 3,
        "reload_cycles": 2,
    }
    assert {field: report["village"][field] for field in expected} == expected
    assert all(status == "pass" for status in report["phases"].values())
    assert report["roundtrip"]["reload_cycles"] == 2
    assert (tmp_path / "village-plan.json").is_file()
    assert report["village_plan_sha256"] == runner.sha256(tmp_path / "village-plan.json")


@pytest.mark.parametrize("phase", ["seed", "reload1", "reload2"])
@pytest.mark.parametrize("case", ["before", "trade", "pickup", "after", "chunk_reload"])
def test_missing_gameplay_evidence_in_any_join_fails(tmp_path, monkeypatch, phase, case):
    with pytest.raises(ProbeError, match="evidence"):
        _run(tmp_path, monkeypatch, missing=(phase, case))


def test_missing_natural_generation_provenance_fails(tmp_path, monkeypatch):
    with pytest.raises(ProbeError, match="evidence"):
        _run(tmp_path, monkeypatch, missing=("seed", "origin"))


@pytest.mark.parametrize("phase", ["seed", "reload1", "reload2"])
def test_missing_real_client_join_fails(tmp_path, monkeypatch, phase):
    with pytest.raises(ProbeError, match="Real client"):
        _run(tmp_path, monkeypatch, failure=phase)


@pytest.mark.parametrize("phase", ["seed", "reload1", "reload2"])
@pytest.mark.parametrize("value", ["omit", 0, True, 1.0, 2])
def test_each_join_requires_one_independently_verified_native_trade(tmp_path, monkeypatch, phase, value):
    with pytest.raises(ProbeError):
        _run(tmp_path, monkeypatch, worker_mutation=(phase, "native_trades", value))


@pytest.mark.parametrize("value", ["omit", 0, 1, True, 2.0, 3])
def test_every_planned_backed_up_save_is_required(tmp_path, monkeypatch, value):
    with pytest.raises(ProbeError):
        _run(tmp_path, monkeypatch, worker_mutation=("seed", "backed_up_saves", value))


@pytest.mark.parametrize("phase", ["reload1", "reload2"])
@pytest.mark.parametrize("value", ["omit", 0, True, 1.0, 3])
def test_each_disk_reload_must_report_its_exact_cycle(tmp_path, monkeypatch, phase, value):
    with pytest.raises(ProbeError):
        _run(tmp_path, monkeypatch, worker_mutation=(phase, "verified_reloads", value))


@pytest.mark.parametrize("phase", ["seed", "reload1", "reload2"])
def test_normal_worker_exit_cannot_hide_failed_checks(tmp_path, monkeypatch, phase):
    with pytest.raises(ProbeError):
        _run(tmp_path, monkeypatch, worker_mutation=(phase, "status", "fail"))


@pytest.mark.parametrize("phase", ["seed", "reload1", "reload2"])
@pytest.mark.parametrize("value", ["omit", None, [], {}])
def test_complete_expected_state_must_survive_each_worker(tmp_path, monkeypatch, phase, value):
    with pytest.raises(ProbeError):
        _run(tmp_path, monkeypatch, worker_mutation=(phase, "expected", value))


def _cli(monkeypatch, tmp_path, *extra):
    from scripts.engine_checks import __main__ as entry

    calls = []

    def run(*args, **kwargs):
        calls.append((args, kwargs))
        return tmp_path, {"status": "pass"}

    monkeypatch.setattr(entry, "run_probe", run)
    monkeypatch.setattr(
        "sys.argv",
        ["engine-checks", "--archive", "server.zip", "--sha256", "a" * 64, "--server-version", "1.26.61.1", *extra],
    )
    return entry, calls


def test_village_cli_is_explicit_and_reuses_loopback_port(tmp_path, monkeypatch):
    entry, calls = _cli(monkeypatch, tmp_path, "--suite", "village", "--client-port", "19135")
    assert entry.main() == 0
    assert len(calls) == 1 and calls[0][0][5] == "village"
    assert calls[0][1] == {"client_port": 19135, "client_reloads": 2}


def test_unattended_all_and_workflow_exclude_interactive_village(tmp_path, monkeypatch):
    entry, calls = _cli(monkeypatch, tmp_path, "--suite", "all")
    assert entry.main() == 0
    suites = [args[5] for args, _ in calls]
    assert suites and "village" not in suites and "client" not in suites
    workflow = (runner.ROOT / ".github/workflows/engine-checks.yml").read_text(encoding="utf-8")
    options = next(line.split("[", 1)[1].split("]", 1)[0] for line in workflow.splitlines() if "options:" in line)
    assert "village" not in {option.strip() for option in options.split(",")}


@pytest.mark.parametrize("reloads", ["1", "2"])
def test_client_reload_override_is_not_accepted_for_village(tmp_path, monkeypatch, reloads):
    entry, calls = _cli(monkeypatch, tmp_path, "--suite", "village", "--client-reloads", reloads)
    with pytest.raises(SystemExit) as result:
        entry.main()
    assert result.value.code == 2 and calls == []


def test_public_village_summary_excludes_account_and_world_data():
    report = {
        "status": "pass",
        "suite": "village",
        "engine": {},
        "editor": {},
        "catalog_sha256": "a" * 64,
        "phases": {},
        "not_covered": [],
        "village": {
            "status": "pass",
            "required_connections": 3,
            "completed_connections": 3,
            "backed_up_saves": 2,
            "trades": 3,
            "pickups": 3,
            "chunk_reloads": 3,
            "reload_cycles": 2,
            "identities": "PRIVATE_ACTORS",
            "client_key": "PRIVATE_KEY",
            "player_name": "PRIVATE_NAME",
            "raw_nbt": "PRIVATE_NBT",
            "backup": "PRIVATE_PATH",
        },
        "village_results": {"edit": {"log": "PRIVATE_LOG"}},
    }
    summary = runner.public_summary(report)
    assert summary["village"]["trades"] == 3
    assert summary["village"]["completed_connections"] == 3
    assert "PRIVATE_" not in json.dumps(summary)


def test_village_worker_discards_real_world_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("MCBE_READ_ONLY", "true")
    monkeypatch.setenv("MCBE_WORLDS_ROOT", "PRIVATE_REAL_WORLD")
    result = {"status": "pass", "backed_up_saves": 2, "native_trades": 1, "expected": {"farmer": {}}}

    def subprocess_run(command, **kwargs):
        assert command[2] == "scripts.engine_checks.village_worker"
        assert "MCBE_READ_ONLY" not in kwargs["env"] and "MCBE_WORLDS_ROOT" not in kwargs["env"]
        assert kwargs["env"]["MCBE_DATA_ROOT"] == str(tmp_path / "app-data")
        assert kwargs["env"]["MCBE_BACKUP_ROOT"] == str(tmp_path / "backups")
        assert kwargs["env"]["MCBE_ITEM_DB_PATH"] == str(tmp_path / "catalog.json")
        return SimpleNamespace(returncode=0, stdout=json.dumps(result), stderr="")

    monkeypatch.setattr(runner.subprocess, "run", subprocess_run)
    assert runner.nbt_worker(tmp_path, "edit", module="scripts.engine_checks.village_worker") == result


@pytest.mark.parametrize(
    ("stage", "instruction"),
    [
        ("client_connected", "natural village"),
        ("trade_required", "Buy bread once"),
        ("pickup_required", "drop one selected carrot"),
        ("chunk_reload", "chunk unload and reload"),
    ],
)
def test_village_progress_requests_real_actions_and_keeps_status_private(tmp_path, capsys, stage, instruction):
    runner.client_progress(tmp_path, "reload1", stage, 19135, 3, profile="village")
    message = capsys.readouterr().out
    assert instruction in message and "do not change items" not in message
    state = json.loads((tmp_path / "client-status.json").read_text(encoding="utf-8"))
    assert state == {"phase": "reload1", "status": stage, "connection": 2, "required_connections": 3, "address": "127.0.0.1", "port": 19135}


@pytest.mark.parametrize("port", [True, 0, 1023, 65536, "19134"])
def test_village_rejects_invalid_ports_before_starting_docker(tmp_path, monkeypatch, port):
    monkeypatch.setattr(runner, "docker_command", lambda *args, **kwargs: pytest.fail("Docker must not start for an invalid client port"))
    with pytest.raises(ProbeError, match="Client port"):
        runner.run_probe(tmp_path / "server.zip", "a" * 64, "1.26.61.1", "image", tmp_path, "village", 300, client_port=port)


def test_village_pack_uses_stable_client_api_without_vanilla_overrides(tmp_path):
    runner.prepare_pack(tmp_path, {"run_id": "test", "phase": "seed", "village_profile": make_village_plan()})
    pack = tmp_path / "behavior_packs" / "mcbe_engine_probe"
    manifest = json.loads((pack / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["dependencies"] == [{"module_name": "@minecraft/server", "version": "2.11.0"}]
    assert [module["type"] for module in manifest["modules"]] == ["script"]
    assert not (pack / "entities").exists() and not (pack / "trading").exists()
