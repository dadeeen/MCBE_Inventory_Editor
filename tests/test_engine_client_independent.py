"""Independent orchestration regressions; synthetic BDS events, not a live run."""

from __future__ import annotations

from copy import deepcopy
import json
import struct

import pytest

from mcbe_editor import nbt
from scripts.engine_checks import runner
from scripts.engine_checks.cases import expected_snapshot
from scripts.engine_checks.protocol import ProbeError
from tests.test_engine_checks import server_zip


@pytest.fixture
def client_run(tmp_path, monkeypatch):
    """Keep real planning, pack preparation, validation and reporting together."""
    archive, digest = server_zip(tmp_path)
    catalog = json.loads((runner.ROOT / "mcbe_editor/resources/item_db.json").read_text(encoding="utf-8"))
    observations = {item: {"max_amount": maximum, "max_durability": catalog["durability"].get(item)} for item, maximum in catalog["stack_limits"].items()}
    monkeypatch.setattr(runner, "docker_command", lambda *_args, **_kwargs: json.dumps({"Os": "linux", "Architecture": "amd64", "Id": "sha256:" + "a" * 64}))
    config = {}
    trace = []
    selected_fault = None
    selected_reloads = 2
    catalog_status = "pass"
    bootstrapped_level = None
    prepare_pack = runner.prepare_pack

    def prepare(server, current):
        config.clear()
        config.update(deepcopy(current))
        prepare_pack(server, current)

    def phase(server, directory, name, *_args, **kwargs):
        nonlocal bootstrapped_level
        trace.append(name)
        if name == "catalog":
            # Preserve engine-created world metadata without enabling experiments.
            # No player data is fabricated here.
            payload = nbt.NamedTag(nbt.CompoundTag()).save_to(compressed=False, little_endian=True)
            bootstrapped_level = struct.pack("<II", 10, len(payload)) + payload
            (server / "worlds" / runner.WORLD_NAME / "level.dat").write_bytes(bootstrapped_level)
            assert kwargs == {}
            return []
        assert (server / "worlds" / runner.WORLD_NAME / "level.dat").read_bytes() == bootstrapped_level
        manifest = json.loads((server / "behavior_packs" / "mcbe_engine_probe" / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["dependencies"] == [{"module_name": "@minecraft/server", "version": "2.11.0"}]
        assert manifest["header"]["min_engine_version"] == [1, 26, 60]
        assert kwargs == {"client_port": 19134, "client_connections": selected_reloads + 1}
        persisted_cases = json.loads((directory / "cases.json").read_text(encoding="utf-8"))
        assert persisted_cases == config["cases"]
        assert len(config["cases"]) == 53
        assert len(config["client_locations"]) == 48
        equipment = [case for case in config["cases"] if "equipment_slot" in case]
        assert {case["equipment_slot"] for case in equipment} == {"Head", "Chest", "Legs", "Feet", "Offhand"}
        assert len({case["case_id"] for case in config["cases"]}) == 53
        if selected_fault == name + "-timeout":
            raise ProbeError("Synthetic client join timeout")
        events = [{"kind": "case", "case_id": case["case_id"], "snapshot": expected_snapshot(case, seed=name == "seed")} for case in config["cases"]]
        if selected_fault == name + "-missing-equipment":
            events = [event for event in events if event["case_id"] != equipment[0]["case_id"]]
        if selected_fault == name + "-duplicate-equipment":
            events.append(deepcopy(next(event for event in events if event["case_id"] == equipment[0]["case_id"])))
        if selected_fault == name + "-uncleared-equipment":
            cleared = next(case for case in equipment if case["mode"] == "clear")
            next(event for event in events if event["case_id"] == cleared["case_id"])["snapshot"] = expected_snapshot(cleared, seed=True)
        return events

    def worker(directory, action):
        label = config["phase"] + "-disk" if action == "verify" else action
        trace.append(label)
        report = json.loads((directory / "run.json").read_text(encoding="utf-8"))
        assert report["phases"]["seed"] == "pass"
        assert report["client"]["required_connections"] == selected_reloads + 1
        if selected_fault == label:
            raise ProbeError("Synthetic independent disk check failure")
        return {
            "status": "pass",
            "cases": 53,
            "equipment_cases": 5,
            "player_service": {"status": "pass", "special_content_cases": 3},
            "equipment": {"status": "pass", "cases": 5, "backed_up_saves": 1, "no_op_checks": 1},
        }

    monkeypatch.setattr(runner, "prepare_pack", prepare)
    monkeypatch.setattr(runner, "catalog_result", lambda *_args: {"status": catalog_status, "observations": observations})
    monkeypatch.setattr(runner, "run_phase", phase)
    monkeypatch.setattr(runner, "nbt_worker", worker)

    def run(reloads=2, fault=None, *, partial_catalog=False):
        nonlocal selected_fault, selected_reloads, catalog_status
        selected_fault, selected_reloads = fault, reloads
        catalog_status = "partial" if partial_catalog else "pass"
        directory, report = runner.run_probe(archive, digest, "1.26.60.6", "unused", tmp_path / "runs", "client", 30, client_reloads=reloads)
        summary = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
        status = json.loads((directory / "client-status.json").read_text(encoding="utf-8"))
        return report, summary, status, trace

    return run


@pytest.mark.parametrize("reloads", [1, 2])
def test_client_runner_keeps_batched_coverage_and_reports_actual_reload_scope(client_run, reloads):
    report, summary, status, trace = client_run(reloads)
    assert report["status"] == summary["status"] == status["status"] == "pass"
    assert report["engine"]["api_version"] == summary["engine"]["api_version"] == "2.11.0"
    assert report["engine"]["experiments"] is summary["engine"]["experiments"] is False
    expected = ["catalog", "seed", "edit", "reload1", "reload1-disk"]
    if reloads == 2:
        expected += ["reload2", "reload2-disk"]
    assert trace == expected
    assert report["roundtrip"]["cases"] == 53
    assert report["roundtrip"]["save_reload_cycles"] == reloads
    assert summary["roundtrip"] == report["roundtrip"]
    assert report["client"]["required_connections"] == report["client"]["completed_connections"] == reloads + 1
    assert status["required_connections"] == status["completed_connections"] == reloads + 1
    assert summary["client"] == report["client"]
    assert summary["equipment"]["cases"] == 5
    assert summary["player_service"]["special_content_cases"] == 3
    assert summary["player_service"]["client_login_verified"] is True
    assert ("reload2" in report["phases"]) is (reloads == 2)
    assert any("second real-client reload" in gap for gap in report["not_covered"]) is (reloads == 1)
    assert any("special-item gameplay" in gap for gap in report["not_covered"])
    assert "singleplayer local-player engine saves" in report["not_covered"]
    assert "UI interactions" in report["not_covered"]
    assert "stable-API-only Ender Chest observer" not in report["not_covered"]


@pytest.mark.parametrize(
    "reloads,fault,completed,last_call",
    [
        (2, "seed-missing-equipment", 0, "seed"),
        (2, "edit", 1, "edit"),
        (1, "reload1-missing-equipment", 1, "reload1"),
        (2, "reload1-duplicate-equipment", 1, "reload1"),
        (2, "reload1-uncleared-equipment", 1, "reload1"),
        (1, "reload1-timeout", 1, "reload1"),
        (1, "reload1-disk", 1, "reload1-disk"),
        (2, "reload2-missing-equipment", 2, "reload2"),
        (2, "reload2-disk", 2, "reload2-disk"),
    ],
)
def test_client_runner_never_counts_an_incomplete_phase_as_a_success(client_run, reloads, fault, completed, last_call):
    report, summary, status, trace = client_run(reloads, fault)
    assert report["status"] == summary["status"] == status["status"] == "fail"
    assert trace[-1] == last_call
    assert report["client"]["status"] != "pass"
    assert report["client"]["completed_connections"] == status["completed_connections"] == completed
    assert status["required_connections"] == reloads + 1
    assert summary["roundtrip"]["status"] != "pass"
    assert not summary["player_service"].get("client_login_verified", False)


@pytest.mark.parametrize("reloads", [1, 2])
def test_successful_client_connections_do_not_promote_partial_catalog_coverage(client_run, reloads):
    report, summary, status, _trace = client_run(reloads, partial_catalog=True)
    assert report["client"]["status"] == "pass"
    assert report["status"] == summary["status"] == status["status"] == "partial"
    assert status["completed_connections"] == reloads + 1
