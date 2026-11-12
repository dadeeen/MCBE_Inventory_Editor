"""Corruption checks of the trade harness; these are not evidence of a BDS run."""

from __future__ import annotations

import hashlib
import json
import struct
from copy import deepcopy

import pytest

from mcbe_editor import nbt
from mcbe_editor.bedrock_nbt import load_player_nbt, save_player_nbt
from scripts.engine_checks import runner, villager_trade_worker as worker
from scripts.engine_checks.extended import ENCHANTMENT_NAMES
from scripts.engine_checks.protocol import ProbeError
from scripts.engine_checks.villager_trade_profile import PROFESSIONS, make_trade_cases, validate_trade_events, validate_trade_plan
from tests import test_engine_villager_trade_tables as table_tests
from tests.test_engine_villagers import synthetic_records

table_reference = table_tests.reference


def test_public_summary_keeps_reference_provenance_without_local_paths():
    report = {
        "status": "partial",
        "suite": "villager_trades",
        "engine": {},
        "editor": {},
        "catalog_sha256": "a" * 64,
        "phases": {},
        "not_covered": [],
        "trade_reference": {"version": "v1.26.60.5", "sha256": "b" * 64, "archive": "C:/private/samples.zip"},
        "trade_tables_sha256": "c" * 64,
        "trade_enchantments_sha256": "d" * 64,
    }
    result = runner.public_summary(report)
    assert result["trade_reference"] == {"version": "v1.26.60.5", "sha256": "b" * 64}
    assert result["trade_tables_sha256"] == "c" * 64
    assert result["trade_enchantments_sha256"] == "d" * 64
    assert "private" not in json.dumps(result)


def _events(cases, stage):
    return [
        {
            "kind": "case",
            "case_id": case["case_id"],
            "snapshot": {
                "type": "minecraft:villager_v2",
                **{key: deepcopy(case[stage][key]) for key in ("name", "current", "maximum", "items")},
            },
        }
        for case in cases
    ]


def test_complete_independent_plan_covers_all_jobs_up_and_down_and_control():
    cases = make_trade_cases()
    assert len(cases) == 19
    assert {case["edited"]["profession"] for case in cases if case["case_id"].startswith("profession_")} == set(PROFESSIONS)
    assert {case["edited"]["tier"] for case in cases} == set(range(5))
    assert [case["revised"]["experience"] for case in cases if case["case_id"].startswith("tier_")] == [1] * 4
    assert sum(case["edit"] is None for case in cases) == 1
    assert all(case["edited"] != case["revised"] for case in cases if case["edit"] is not None)
    validate_trade_plan(cases)
    cases.pop()
    with pytest.raises(ProbeError, match="complete plan"):
        validate_trade_plan(cases)


@pytest.mark.parametrize("fault", ["missing", "duplicate", "wrong_type", "changed_supplies", "wrong_name", "extra_field"])
def test_live_probe_cannot_omit_or_replace_control_observations(fault):
    cases = make_trade_cases()
    events = _events(cases, "seed")
    if fault == "missing":
        events.pop(0)
    elif fault == "duplicate":
        events.append(deepcopy(events[0]))
    elif fault == "wrong_type":
        events[0]["snapshot"]["type"] = "minecraft:wandering_trader"
    elif fault == "changed_supplies":
        events[0]["snapshot"]["items"][0] = {"name": "minecraft:diamond", "count": 1}
    elif fault == "wrong_name":
        events[0]["snapshot"]["name"] = "Different actor"
    else:
        events[0]["snapshot"]["offers_verified"] = True
    with pytest.raises(ProbeError):
        validate_trade_events(events, cases, stage="seed")


def _orchestration(tmp_path, monkeypatch, fault=None, shared_report=None):
    from scripts.engine_checks import villager_trade_tables

    cases, config, sequence = make_trade_cases(), {}, []
    report = {"phases": {}, "not_covered": []} if shared_report is None else shared_report
    monkeypatch.setattr(villager_trade_tables, "load_trade_tables", lambda _server: {"independent_test_source": True})
    monkeypatch.setattr(villager_trade_tables, "trade_enchantment_items", lambda _tables: ["minecraft:iron_axe"])

    def phase(name):
        sequence.append(name)
        report["phases"][name] = "observed"
        stage = "revised" if name in {"reload3", "reload4"} else "edited" if name in {"reload1", "reload2"} else "seed"
        events = _events(cases, stage)
        if name == "seed":
            events.append(
                {"kind": "matrix_registry", "enchantments": dict.fromkeys(ENCHANTMENT_NAMES, 5), "enchantability": {"minecraft:iron_axe": ["efficiency"]}}
            )
            if fault == "registry":
                events.pop()
            elif fault == "compatibility":
                events[-1]["enchantability"] = {}
        if fault == name:
            events.pop(0)
        return events

    def offline(directory, action, *, module):
        assert directory == tmp_path and module == "scripts.engine_checks.villager_trade_worker"
        persisted = json.loads((directory / "run.json").read_bytes())
        assert persisted["phases"]["seed"] == "pass"
        assert (directory / "trade-enchantments.json").is_file()
        sequence.append("worker:" + action)
        if fault == "worker:" + action:
            raise ProbeError("independent trade oracle rejected articles")
        result = {"status": "pass", "cases": 19, "limitations": ["map targets require separate world verification"]}
        if action in {"edit", "revise"}:
            result.update(backed_up_saves=18, no_op_checks=18, stale_revision_rejections=18)
            if fault in {"backed_up_saves", "no_op_checks", "stale_revision_rejections"}:
                result[fault] = 17
        return result

    monkeypatch.setattr(runner, "nbt_worker", offline)
    runner.run_villager_trade_checks(tmp_path, report, config, phase)
    return report, sequence, config


def test_orchestration_requires_two_reload_pairs_and_independent_worker_after_each(tmp_path, monkeypatch):
    report, sequence, config = _orchestration(tmp_path, monkeypatch)
    assert sequence == [
        "seed",
        "worker:seed",
        "warmup1",
        "worker:warmup1",
        "warmup2",
        "worker:warmup2",
        "worker:edit",
        "reload1",
        "worker:reload1",
        "reload2",
        "worker:reload2",
        "worker:revise",
        "reload3",
        "worker:reload3",
        "reload4",
        "worker:reload4",
    ]
    assert report["villager_trades"]["status"] == "partial"
    assert report["villager_trades"]["recipe_structure"] == "pass" and report["villager_trades"]["metadata"] == "partial"
    assert report["villager_trades"]["backed_up_saves"] == 36
    assert report["villager_trades"]["warmup_cycles"] == 2 and report["villager_trades"]["reload_cycles"] == 4
    assert report["villager_trades"]["limitations"] == ["map targets require separate world verification"]
    assert config["villager_profile"] and config["villager_trade_profile"]


@pytest.mark.parametrize(
    "fault",
    [
        "seed",
        "warmup1",
        "warmup2",
        "reload1",
        "reload2",
        "reload3",
        "reload4",
        "registry",
        "compatibility",
        "worker:reload1",
        "worker:reload2",
        "worker:reload3",
        "worker:reload4",
        "backed_up_saves",
        "no_op_checks",
        "stale_revision_rejections",
    ],
)
def test_incomplete_live_disk_or_save_coverage_cannot_report_engine_pass(tmp_path, monkeypatch, fault):
    with pytest.raises(ProbeError):
        _orchestration(tmp_path, monkeypatch, fault)


@pytest.mark.parametrize("fault,warmups,reloads", [("seed", 0, 0), ("warmup1", 0, 0), ("warmup2", 1, 0), ("worker:reload2", 2, 1)])
def test_failed_report_counts_only_completed_live_and_disk_cycles(tmp_path, monkeypatch, fault, warmups, reloads):
    report = {"phases": {}, "not_covered": []}
    with pytest.raises(ProbeError):
        _orchestration(tmp_path, monkeypatch, fault, report)
    assert report["villager_trades"]["status"] == "incomplete"
    assert report["villager_trades"]["warmup_cycles"] == warmups
    assert report["villager_trades"]["reload_cycles"] == reloads


def _pack(tmp_path):
    cases = make_trade_cases()
    run_id = "1" * 32
    runner.write_json(tmp_path / "run.json", {"run_id": run_id})
    runner.prepare_pack(tmp_path / "server", {"run_id": run_id, "villager_profile": True, "villager_trade_profile": True, "cases": cases})
    return tmp_path / "server" / "worlds" / runner.WORLD_NAME


def test_only_owned_script_pack_is_deregistered_and_original_bytes_restore_on_failure(tmp_path):
    world = _pack(tmp_path)
    path = world / "world_behavior_packs.json"
    before = path.read_bytes()
    with pytest.raises(RuntimeError, match="planned failure"), worker.vanilla_offline_window(world, tmp_path):
        assert json.loads(path.read_bytes()) == []
        raise RuntimeError("planned failure")
    assert path.read_bytes() == before


@pytest.mark.parametrize("fault", ["extra_pack", "extra_file", "data_module", "changed_script", "wrong_run", "missing_case"])
def test_trade_window_never_disables_unverified_behavior_pack(tmp_path, fault):
    world = _pack(tmp_path)
    pack = tmp_path / "server/behavior_packs/mcbe_engine_probe"
    if fault == "extra_pack":
        path = world / "world_behavior_packs.json"
        registry = json.loads(path.read_bytes())
        registry.append({"pack_id": "unowned", "version": [1, 0, 0]})
        runner.write_json(path, registry)
    elif fault == "extra_file":
        (pack / "entities").mkdir()
        (pack / "entities/villager_v2.json").write_text("{}")
    elif fault == "data_module":
        manifest = json.loads((pack / "manifest.json").read_bytes())
        manifest["modules"].append({"type": "data", "uuid": "unowned"})
        runner.write_json(pack / "manifest.json", manifest)
    elif fault == "changed_script":
        (pack / "scripts/main.js").write_text("// not the audited source")
    else:
        path = pack / "scripts/config.js"
        config = json.loads(path.read_text()[len("export const config = ") : -2])
        if fault == "wrong_run":
            config["run_id"] = "2" * 32
        else:
            config["cases"].pop()
        path.write_text("export const config = " + json.dumps(config) + ";\n")
    registry_path = world / "world_behavior_packs.json"
    before = registry_path.read_bytes()
    with pytest.raises(ProbeError), worker.vanilla_offline_window(world, tmp_path):
        pytest.fail("Unverified pack was deregistered")
    assert registry_path.read_bytes() == before


def _native_shape(monkeypatch):
    from scripts.engine_checks import villager_trade_tables

    cases = make_trade_cases()
    records = synthetic_records(cases)
    tables = {name: {"variant": index + 1, "path": "trading/test/" + name + ".json"} for index, name in enumerate(PROFESSIONS)}
    for case, (key, root) in zip(cases, worker.find_actors(records, cases, tagged=True).values(), strict=True):
        root["Variant"] = nbt.IntTag(tables[case["seed"]["profession"]]["variant"])
        root["TradeTablePath"] = nbt.StringTag(tables[case["seed"]["profession"]]["path"])
        root["PreferredProfession"] = nbt.StringTag(case["seed"]["profession"])
        records[key] = save_player_nbt(nbt.NamedTag(root))

    # Here the table validator is independently tested in its own module. This
    # double isolates preservation/phase-control faults from table semantics.
    monkeypatch.setattr(
        villager_trade_tables,
        "validate_offers",
        lambda root, *_a, **_k: {
            "status": "pass",
            "critical_signature": hashlib.sha256(root["Offers"].save_to()).hexdigest(),
            "limitations": [],
        },
    )
    return cases, records, tables


@pytest.mark.parametrize("fault", ["control_offers", "wrong_tier", "wrong_experience", "wrong_table", "wrong_variant", "identity"])
def test_saved_trade_observer_rejects_corruption_without_learning_it_as_expected(monkeypatch, fault):
    cases, records, tables = _native_shape(monkeypatch)
    baseline = worker.verify_records(records, cases, tables, "seed")
    key = worker.find_actors(records, cases, tagged=True)[cases[0]["name"]][0]
    named = load_player_nbt(records[key])
    root = named.tag
    if fault == "control_offers":
        root["Offers"]["foreign"] = nbt.StringTag("new articles")
    elif fault == "wrong_tier":
        root["TradeTier"] = nbt.IntTag(4)
    elif fault == "wrong_experience":
        root["TradeExperience"] = nbt.IntTag(250)
    elif fault == "wrong_table":
        root["TradeTablePath"] = nbt.StringTag("trading/custom.json")
    elif fault == "wrong_variant":
        root["Variant"] = nbt.IntTag(4)
    else:
        root["UniqueID"] = nbt.LongTag(17)
    records[key] = save_player_nbt(named)
    with pytest.raises(ProbeError):
        worker.verify_records(records, cases, tables, "seed", previous=baseline)


def test_tier_writer_must_preserve_offers_and_all_other_database_records(monkeypatch):
    cases, before, _tables = _native_shape(monkeypatch)
    chosen = next(case for case in cases if case["case_id"] == "tier_1")
    key = worker.find_actors(before, cases, tagged=True)[chosen["name"]][0]
    named = load_player_nbt(before[key])
    named.tag["TradeTier"] = nbt.IntTag(1)
    named.tag["TradeExperience"] = nbt.IntTag(10)
    after = {**before, key: save_player_nbt(named)}
    worker.verify_write(before, after, cases, chosen, switched=False)
    named.tag["Offers"]["unexpected"] = nbt.ByteTag(1)
    after[key] = save_player_nbt(named)
    with pytest.raises(ProbeError, match="unrelated actor"):
        worker.verify_write(before, after, cases, chosen, switched=False)


def test_offline_tier_write_does_not_invent_preferred_profession_but_reload_checks_binding(monkeypatch):
    _cases, records, tables = _native_shape(monkeypatch)
    root = load_player_nbt(next(raw for key, raw in records.items() if key.startswith(b"actorprefix"))).tag
    root["TradeTier"], root["TradeExperience"] = nbt.IntTag(1), nbt.IntTag(10)
    root["PreferredProfession"] = nbt.StringTag("")
    expected = {"profession": "farmer", "tier": 1, "experience": 10}
    worker._career(root, expected, tables)
    with pytest.raises(ProbeError, match="preferred binding"):
        worker._career(root, expected, tables, require_binding=True)


@pytest.mark.parametrize("variant", [None, nbt.IntTag(0), nbt.IntTag(1), nbt.ByteTag(0)])
def test_unemployed_native_variant_defaults_only_to_zero(variant):
    root = nbt.CompoundTag({"TradeTier": nbt.IntTag(0), "TradeExperience": nbt.IntTag(0)})
    if variant is not None:
        root["Variant"] = variant
    expected = {"profession": "unemployed", "tier": 0, "experience": 0}
    if variant is None or isinstance(variant, nbt.IntTag) and variant.py_data == 0:
        assert worker._career(root, expected, {})["recipes"] == 0
    else:
        with pytest.raises(ProbeError, match="Variant"):
            worker._career(root, expected, {})
    with pytest.raises(ProbeError, match="Variant"):
        worker._career(nbt.CompoundTag(), {**expected, "profession": "farmer"}, {"farmer": {"variant": 1}})


def test_full_worker_uses_real_service_on_synthetic_world_without_claiming_engine_execution(tmp_path, monkeypatch, table_reference):
    """Exercise orchestration and actual DB writes; reloaded offers are doubles.

    This makes missing restore/state/order/backup paths fail without pretending
    the test's deliberate offer fixtures were generated by Minecraft.
    """
    from mcbe_editor.bedrock_nbt import SAVE_KWARGS
    from mcbe_editor.leveldb_writer import LevelDbWriter
    from scripts.engine_checks.villager_trade_tables import load_trade_tables

    world = _pack(tmp_path)
    (world / "db").mkdir()
    raw = nbt.NamedTag(nbt.CompoundTag({"LevelName": nbt.StringTag("Synthetic trade harness only")})).save_to(**SAVE_KWARGS)
    (world / "level.dat").write_bytes(struct.pack("<II", 10, len(raw)) + raw)
    (world / "levelname.txt").write_text("Synthetic trade harness only")
    monkeypatch.setenv("MCBE_BACKUP_ROOT", str(tmp_path / "backups"))
    monkeypatch.setenv("MCBE_MAX_BACKUPS_PER_WORLD", "100")
    cases, records = make_trade_cases(), synthetic_records(make_trade_cases())
    base = tmp_path / "server/behavior_packs/vanilla"
    (base / "entities").mkdir(parents=True)
    groups = {}
    table_names = {"weaponsmith": "weapon_smith", "toolsmith": "tool_smith", "leatherworker": "leather_worker", "mason": "stone_mason"}
    for variant, profession in enumerate(PROFESSIONS, 1):
        path = "trading/economy_trades/" + table_names.get(profession, profession) + "_trades.json"
        groups[profession] = {"minecraft:variant": {"value": variant}, "minecraft:economy_trade_table": {"table": path, "persist_trades": True}}
        output = base / path
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps({"tiers": table_reference[1]["farmer"]["tiers"]}))
    (base / "entities/villager_v2.json").write_text(json.dumps({"minecraft:entity": {"component_groups": groups}}))
    tables = load_trade_tables(tmp_path / "server")
    for case in cases:
        key, root = worker.find_actors(records, cases, tagged=True)[case["name"]]
        profession = case["seed"]["profession"]
        root["Variant"] = nbt.IntTag(tables[profession]["variant"])
        root["TradeTablePath"] = nbt.StringTag(tables[profession]["path"])
        root["PreferredProfession"] = nbt.StringTag(profession)
        root["IsBaby"], root["Age"] = nbt.ByteTag(0), nbt.IntTag(0)
        root["definitions"] = nbt.ListTag([nbt.StringTag("+" + group) for group in ("villager_v2", "adult", profession)])
        root["Offers"] = deepcopy(table_reference[0]["Offers"])
        records[key] = save_player_nbt(nbt.NamedTag(root))

    def write_records(updates):
        database = LevelDbWriter(str(world / "db"))
        try:
            database.put_batch(updates)
        finally:
            database.close()

    write_records(records)
    runner.write_json(tmp_path / "cases.json", cases)
    runner.write_json(tmp_path / "catalog.json", {"synthetic_test_catalog": True})
    runner.write_json(tmp_path / "trade-enchantments.json", {"limits": dict.fromkeys(ENCHANTMENT_NAMES, 5), "compatibility": {}})
    report = {
        "format": "mcbe-engine-check-v1",
        "suite": "villager_trades",
        "run_id": "1" * 32,
        "phases": {"seed": "pass"},
        "editor": runner.source_hashes(),
        "cases_sha256": runner.sha256(tmp_path / "cases.json"),
        "catalog_sha256": runner.sha256(tmp_path / "catalog.json"),
        "trade_tables_sha256": hashlib.sha256(json.dumps(tables, sort_keys=True).encode()).hexdigest(),
        "trade_enchantments_sha256": runner.sha256(tmp_path / "trade-enchantments.json"),
    }
    runner.write_json(tmp_path / "run.json", report)
    registry = world / "world_behavior_packs.json"
    registered = registry.read_bytes()
    assert worker.run(tmp_path, "seed")["cases"] == 19
    with pytest.raises(ProbeError, match="out of order"):
        worker.run(tmp_path, "edit")
    for phase in ("warmup1", "warmup2"):
        worker.run(tmp_path, phase)
        report["phases"][phase] = "pass"
        runner.write_json(tmp_path / "run.json", report)
    for action, phases in (("edit", ("reload1", "reload2")), ("revise", ("reload3", "reload4"))):
        result = worker.run(tmp_path, action)
        assert result["backed_up_saves"] == result["no_op_checks"] == result["stale_revision_rejections"] == 18
        assert registry.read_bytes() == registered
        # Before simulated regeneration, the post-engine oracle must reject
        # the missing new offers rather than report a successful reload.
        with pytest.raises(ProbeError, match="did not generate"):
            worker.run(tmp_path, phases[0])
        current = worker._read(world)
        updates = {}
        for key, root in worker.find_actors(current, cases, tagged=True).values():
            if root["Variant"].py_data and "Offers" not in root:
                root["Offers"] = deepcopy(table_reference[0]["Offers"])
                updates[key] = save_player_nbt(nbt.NamedTag(root))
        write_records(updates)
        for phase in phases:
            worker.run(tmp_path, phase)
            report["phases"][phase] = "pass"
            runner.write_json(tmp_path / "run.json", report)
    assert len(list((tmp_path / "backups").rglob("*.zip"))) == 36
