from __future__ import annotations

import io
import json
import sys
from copy import deepcopy

import pytest

from scripts.engine_checks.cases import expected_snapshot, make_cases
from scripts.engine_checks.equipment import make_equipment_cases
from scripts.engine_checks.protocol import ProbeError
from scripts.engine_checks.runner import ROOT
from scripts.engine_checks.service_profile import assignments
from tests.node_runner import run_node


@pytest.mark.parametrize("reloads,expected", [(None, 2), ("1", 1), ("2", 2)])
def test_client_cli_chooses_reload_count(tmp_path, monkeypatch, reloads, expected):
    from scripts.engine_checks import __main__ as cli

    calls = []

    def run(*args, **kwargs):
        calls.append((args[5], kwargs["client_reloads"]))
        return tmp_path, {"status": "pass"}

    argv = ["engine-checks", "--archive", "server.zip", "--sha256", "a" * 64, "--server-version", "1.26.52.3", "--suite", "client"]
    if reloads is not None:
        argv.extend(["--client-reloads", reloads])
    monkeypatch.setattr(cli, "run_probe", run)
    monkeypatch.setattr(sys, "argv", argv)
    assert cli.main() == 0
    assert calls == [("client", expected)]


@pytest.mark.parametrize("suite,reloads", [("all", "1"), ("service", "2"), ("client", "0"), ("client", "3")])
def test_client_reload_option_rejects_invalid_scope_before_start(monkeypatch, suite, reloads):
    from scripts.engine_checks import __main__ as cli

    monkeypatch.setattr(cli, "run_probe", lambda *_args, **_kwargs: pytest.fail("Invalid options started a server"))
    monkeypatch.setattr(
        sys,
        "argv",
        ["engine-checks", "--archive", "server.zip", "--sha256", "a" * 64, "--server-version", "1.26.52.3", "--suite", suite, "--client-reloads", reloads],
    )
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2


@pytest.mark.parametrize("suite,reloads", [("client", True), ("client", "1"), ("client", 0), ("client", 3), ("service", 1)])
def test_runner_rejects_invalid_reload_count_before_docker(tmp_path, monkeypatch, suite, reloads):
    from scripts.engine_checks import runner

    monkeypatch.setattr(runner, "docker_command", lambda *_args, **_kwargs: pytest.fail("Invalid options reached Docker"))
    with pytest.raises(ProbeError, match="Client reloads"):
        runner.run_probe(tmp_path / "server.zip", "a" * 64, "1.26.52.3", "unused", tmp_path / "runs", suite, 30, client_reloads=reloads)


@pytest.mark.parametrize("phase,connections,ordinal", [("seed", 2, 1), ("reload2", 3, 3)])
def test_client_progress_follows_observed_events_and_intentional_shutdown(tmp_path, monkeypatch, capsys, phase, connections, ordinal):
    from scripts.engine_checks import runner

    events = [
        {"kind": "begin"},
        {"kind": "checkpoint", "stage": "waiting_for_client"},
        {"kind": "checkpoint", "stage": "client_connected"},
        {"kind": "done", "items": 0, "cases": 0, "errors": 0},
    ]
    lines = ["Version: 1.26.52.3", "Private client log: PRIVATE_ACCOUNT"]
    lines.extend("[MCBE_ENGINE] " + json.dumps({**event, "run_id": "test-run", "phase": phase, "seq": index}) for index, event in enumerate(events))
    commands = []

    class Input:
        def write(self, value):
            commands.append(value)

        def flush(self):
            pass

        def close(self):
            pass

    class Process:
        stdin = Input()
        stdout = io.StringIO("\n".join(lines) + "\n")

        def wait(self, **_kwargs):
            return 0

        def poll(self):
            return 0

    def docker(args, **_kwargs):
        return "b" * 64 if args[0] == "create" else json.dumps({"Running": False, "ExitCode": 0, "OOMKilled": False})

    statuses = []
    real_write = runner.write_json

    def write(path, value):
        if path.name == "client-status.json":
            statuses.append(deepcopy(value))
        real_write(path, value)

    monkeypatch.setattr(runner, "write_json", write)
    monkeypatch.setattr(runner, "docker_command", docker)
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *_args, **_kwargs: Process())
    observed = runner.run_phase(tmp_path, tmp_path, phase, "test-run", "1.26.52.3", "sha256:" + "a" * 64, 10, client_port=19134, client_connections=connections)
    assert observed[-1]["kind"] == "done"
    assert commands == ["stop\n"]
    assert [status["status"] for status in statuses] == ["starting", "waiting_for_client", "client_connected", "saving", "stopped"]
    assert all(status["required_connections"] == connections and status["connection"] == ordinal for status in statuses)
    output = capsys.readouterr().out
    assert f"Join {ordinal}/{connections} ready: connect to 127.0.0.1:19134" in output
    assert "disconnect you intentionally" in output
    assert "PRIVATE_ACCOUNT" not in output + json.dumps(statuses)


def test_clear_snapshot_preserves_explicit_seed_item_and_plain_controls():
    original = {"id": "minecraft:diamond_leggings", "amount": 1, "name": "Original", "lore": [], "damage": 4, "enchantments": []}
    case = {**original, "mode": "clear", "seed_item": original}
    assert expected_snapshot(case, seed=True) == original
    assert expected_snapshot(case) is None
    assert expected_snapshot(original) == original


@pytest.mark.parametrize("fault", [None, "missing_component", "duplicate_position", "missing_position", "seed_failure", "extra_item"])
def test_client_script_seeds_once_and_observes_equipment_without_repairing_reload(fault):
    catalog = json.loads((ROOT / "mcbe_editor/resources/item_db.json").read_text(encoding="utf-8"))
    observations = {item: {"max_amount": limit, "max_durability": catalog["durability"].get(item)} for item, limit in catalog["stack_limits"].items()}
    cases = make_cases(["minecraft:stone"], observations, catalog["stack_limits"])
    cases.extend(make_equipment_cases(observations, catalog["stack_limits"]))
    config = {
        "phase": "seed",
        "cases": cases,
        "client_locations": assignments(cases),
        "client_control_slots": {"Inventory": 34, "EnderChestInventory": 25},
        "client_control_name": "untouched control",
    }
    data = {
        "config": config,
        "seed": {case["case_id"]: expected_snapshot(case, seed=True) for case in cases},
        "final": {case["case_id"]: expected_snapshot(case) for case in cases},
        "fault": fault,
    }
    run_node(
        "const data = "
        + json.dumps(data)
        + r""";
        (() => {
        const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
        const clone = value => value == null ? value : JSON.parse(JSON.stringify(value));
        let allowWrites = true, writes = 0, players = [];
        const events = [];
        function writeGuard() { assert.ok(allowWrites, 'Reload attempted to repair/reseed persisted items'); writes++; }
        function container(size) {
            const items = new Map();
            return {size, items, clearAll() {writeGuard(); items.clear();},
                setItem(slot, item) {writeGuard(); items.set(slot, item);}, getItem(slot) {return items.get(slot);}};
        }
        const containers = {Inventory: container(36), EnderChestInventory: container(27)};
        const gear = new Map();
        const equipment = {getEquipment(slot) {return gear.get(slot);}, setEquipment(slot, item) {
            writeGuard(); if (data.fault === 'seed_failure') return false;
            if (item === undefined) gear.delete(slot); else gear.set(slot, item); return true;
        }};
        const player = {getComponent(id) {
            if (id === 'minecraft:inventory') return {container: containers.Inventory};
            if (id === 'minecraft:ender_inventory') return {container: containers.EnderChestInventory};
            if (id === 'minecraft:equippable') return data.fault === 'missing_component' ? undefined : equipment;
        }};
        class ItemStack {
            constructor(id, amount) {this.id = id; this.amount = amount; this.lore = []; this.damage = 0; this.enchantments = [];}
        }
        const snapshot = item => !item ? null : item instanceof ItemStack ?
            {id: item.id, amount: item.amount, name: item.nameTag, lore: [], damage: 0, enchantments: []} : clone(item);
        const context = {ItemStack, world: {getAllPlayers() {return players;}},
            EquipmentSlot: Object.fromEntries(['Head','Chest','Legs','Feet','Offhand'].map(name => [name,name])),
            snapshot, referenceItem(test) {assert.ok(allowWrites); return clone(data.seed[test.case_id]);}};
        const source = fs.readFileSync('scripts/engine_checks/pack/scripts/client.js', 'utf8')
            .replace(/^import .*;\r?\n/gm, '').replace('export function*', 'function*');
        vm.runInNewContext(source + '\nglobalThis.probe = clientRoundtrip;', context);
        if (data.fault === 'duplicate_position') data.config.cases.at(-1).equipment_slot = 'Head';
        if (data.fault === 'missing_position') data.config.cases.pop();
        const emit = (kind, value) => events.push(clone({kind, ...value}));
        function finish(task) {for (let i=0; i<200; i++) if (task.next().done) return; throw new Error('Unbounded client wait');}
        const seed = context.probe(data.config, emit);
        assert.equal(seed.next().value.wait, 5);
        assert.equal(writes, 0);
        assert.equal(events[0].stage, 'waiting_for_client');
        players = [player];
        if (['missing_component','duplicate_position','missing_position','seed_failure'].includes(data.fault)) {
            assert.throws(() => finish(seed), /equipment|Equipment/); return;
        }
        finish(seed);
        const seedEvents = Object.fromEntries(events.filter(event => event.kind === 'case').map(event => [event.case_id,event.snapshot]));
        assert.deepEqual(seedEvents, data.seed);
        assert.ok(events.some(event => event.stage === 'client_connected'));
        const seedWrites = writes;
        // Model the independent offline editor. Neither reload may rebuild data.
        for (const test of data.config.cases) {
            const value = clone(data.final[test.case_id]);
            if (test.equipment_slot) {
                if (value === null) gear.delete(test.equipment_slot); else gear.set(test.equipment_slot, value);
            } else {
                const [field, slot] = data.config.client_locations[test.case_id];
                containers[field].items.set(slot, value);
            }
        }
        allowWrites = false;
        if (data.fault === 'extra_item') containers.Inventory.items.set(24, {id:'minecraft:stone'});
        for (const phase of ['reload1','reload2']) {
            events.length = 0; data.config.phase = phase;
            if (data.fault === 'extra_item') {assert.throws(() => finish(context.probe(data.config, emit)), /extra items/); break;}
            finish(context.probe(data.config, emit));
            assert.deepEqual(Object.fromEntries(events.filter(event => event.kind === 'case').map(event => [event.case_id,event.snapshot])), data.final);
            assert.equal(writes, seedWrites);
        }
        })();
        """
    )
