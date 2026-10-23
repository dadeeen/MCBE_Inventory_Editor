"""Harness regressions with synthetic records, never an actual BDS invocation."""

from copy import deepcopy
import json

import pytest

from mcbe_editor import nbt
from mcbe_editor.bedrock_nbt import save_player_nbt
from scripts.engine_checks.cases import expected_snapshot, validate_case_events
from scripts.engine_checks.nbt_roundtrip import build_item_writes, carriers, indexed_items, verify_saved_items
from scripts.engine_checks.protocol import ProbeError
from scripts.engine_checks.special import make_special_cases, revision_cases, verify_special_rejections
from tests.test_engine_checks import server_zip, synthetic_carriers


@pytest.fixture
def special_inputs():
    from scripts.engine_checks.runner import ROOT

    catalog = json.loads((ROOT / "mcbe_editor/resources/item_db.json").read_text(encoding="utf-8"))
    # These are test doubles for measurements, not evidence of engine behavior.
    observations = {item: {"max_amount": limit, "max_durability": catalog["durability"].get(item)} for item, limit in catalog["stack_limits"].items()}
    return observations, catalog["stack_limits"]


@pytest.fixture
def special_cases(special_inputs):
    return make_special_cases(*special_inputs)


def test_profile_covers_all_special_kinds_and_revises_only_selected_cases(special_cases):
    assert {case["special_edit"]["kind"] for case in special_cases} == {"bundle", "shulker", "book", "banner", "fireworks", "firework_star"}
    assert len(special_cases) == 18
    assert len({(case["carrier"], case["slot"]) for case in special_cases}) == len(special_cases)
    assert all(case["slot"] != 26 for case in special_cases)
    original = deepcopy(special_cases)
    revised = revision_cases(special_cases)
    assert special_cases == original
    assert sum(case["mode"] == "decorate" for case in revised) == 14
    assert sum(case["mode"] == "preserve" for case in revised) == 4


@pytest.mark.parametrize("fault", ["missing", "uncurated", "changed", "boolean", "curated_boolean", "durability", "null_durability"])
def test_profile_fails_closed_when_required_measurements_are_unavailable(special_inputs, fault):
    observations, limits = deepcopy(special_inputs)
    if fault == "missing":
        del observations["minecraft:bundle"]
    elif fault == "uncurated":
        del limits["minecraft:ender_pearl"]
    elif fault == "changed":
        observations["minecraft:diamond"]["max_amount"] = 32
    elif fault == "boolean":
        observations["minecraft:bundle"]["max_amount"] = True
    elif fault == "curated_boolean":
        limits["minecraft:bundle"] = True
    elif fault == "durability":
        observations["minecraft:diamond_sword"]["max_durability"] = 0
    elif fault == "null_durability":
        observations["minecraft:diamond_sword"]["max_durability"] = None
    with pytest.raises(ProbeError):
        make_special_cases(observations, limits)


def test_signed_book_reference_uses_engine_signing_and_checks_identity(special_cases):
    from tests.node_runner import run_node

    case = next(case for case in special_cases if case["profile"] == "book_signed")
    run_node(
        "const test = "
        + json.dumps(case)
        + ";\n"
        + r"""
        const assert = require('node:assert/strict');
        const fs = require('node:fs');
        const source = fs.readFileSync('scripts/engine_checks/pack/scripts/items.js', 'utf8')
            .replace(/^import .*;\s*/m, '').replaceAll('export function ', 'function ');
        let available = true, changesIdentity = true;
        class ItemStack {
            constructor(id, amount) {
                assert.equal(id, 'minecraft:writable_book');
                this.typeId = id; this.amount = amount;
            }
            getComponent(id) {
                assert.equal(id, 'minecraft:book');
                if (!available) return null;
                return {
                    setContents: pages => assert.deepEqual(pages, test.seed_book.pages),
                    signBook: (title, author) => {
                        assert.equal(title, test.seed_book.title);
                        assert.equal(author, test.seed_book.author);
                        if (changesIdentity) this.typeId = 'minecraft:written_book';
                    },
                };
            }
        }
        const referenceItem = new Function('ItemStack', 'Potions', 'EnchantmentTypes', source + '; return referenceItem;')(ItemStack, {}, {});
        assert.equal(referenceItem(test, true).typeId, test.id);
        changesIdentity = false;
        assert.throws(() => referenceItem(test, true), /identity/);
        available = false;
        assert.throws(() => referenceItem(test, true), /component missing/);
    """
    )


def test_signed_book_seed_expects_engine_title_and_reload_expects_edited_name(special_cases):
    case = next(case for case in special_cases if case["profile"] == "book_signed")
    snapshot = {"id": "minecraft:written_book", "amount": 1, "name": "Seed book", "lore": [], "damage": 0, "enchantments": []}
    events = [{"kind": "case", "case_id": case["case_id"], "snapshot": snapshot}]
    validate_case_events(events, [case], seed=True)
    assert expected_snapshot(case)["name"] == "§bProbe · book_signed"
    with pytest.raises(ProbeError, match="semantics"):
        validate_case_events(events, [case])
    snapshot["name"] = ""
    with pytest.raises(ProbeError, match="semantics"):
        validate_case_events(events, [case], seed=True)


def test_special_requests_use_production_builder_and_independent_oracle(special_cases):
    records = synthetic_carriers(special_cases)
    records.update(build_item_writes(records, special_cases))
    assert verify_saved_items(records, special_cases)["cases"] == 18
    before = deepcopy(records)
    revised = revision_cases(special_cases)
    records.update(build_item_writes(records, revised))
    assert verify_saved_items(records, revised)["cases"] == 18
    assert records[b"unrelated"] == before[b"unrelated"]
    assert verify_special_rejections() == 15
    # Checking against the old manifest must not bless the revised contents.
    with pytest.raises(ProbeError):
        verify_saved_items(records, special_cases)


@pytest.mark.parametrize(
    "profile,path,replacement",
    [
        ("bundle_diamond", ("tag", "bundle_weight"), nbt.IntTag(4)),
        ("bundle_diamond", ("tag", "bundle_weight"), nbt.ShortTag(68)),
        ("bundle_diamond", ("tag", "storage_item_component_content", 63, "Count"), nbt.ByteTag(63)),
        ("bundle_diamond", ("tag", "storage_item_component_content", 63, "Name"), nbt.StringTag("minecraft:stone")),
        ("bundle_diamond", ("tag", "storage_item_component_content", 1, "Slot"), nbt.ByteTag(0)),
        ("bundle_diamond", ("tag", "storage_item_component_content", 0, "tag"), nbt.CompoundTag({"lost": nbt.IntTag(1)})),
        ("bundle_nested_64", ("tag", "storage_item_component_content", 63, "tag", "bundle_weight"), nbt.IntTag(4)),
        ("bundle_diamond_sword", ("tag", "storage_item_component_content", 63, "tag", "Damage"), nbt.IntTag(0)),
        ("bundle_diamond_sword", ("tag", "storage_item_component_content", 63, "tag", "display", "Name"), nbt.StringTag("lost")),
        ("bundle_diamond_sword", ("tag", "storage_item_component_content", 63, "tag", "ench"), nbt.ListTag([], 10)),
        ("shulker_full", ("tag", "Items"), nbt.ListTag([], 10)),
        ("shulker_nested", ("tag", "Items", 1, "tag", "storage_item_component_content", 63, "tag", "pages", 0, "text"), nbt.StringTag("lost")),
        ("book_pages", ("tag", "pages", 0, "text"), nbt.IntTag(0)),
        ("book_pages", ("tag", "pages", 2, "text"), nbt.StringTag("x" * 255)),
        ("book_signed", ("tag", "author"), nbt.StringTag("lost")),
        ("book_signed", ("tag", "generation"), nbt.ByteTag(0)),
        ("banner_patterns", ("tag", "Patterns", 0, "Color"), nbt.ByteTag(0)),
        ("banner_patterns", ("tag", "Patterns", 0, "Pattern"), nbt.StringTag("ts")),
        ("banner_patterns", ("Damage",), nbt.ShortTag(0)),
        ("banner_ominous", ("tag", "Type"), nbt.IntTag(0)),
        ("rocket_effects", ("tag", "Fireworks", "Flight"), nbt.ByteTag(1)),
        ("rocket_effects", ("tag", "Fireworks", "Explosions", 1, "FireworkFade"), nbt.ByteArrayTag([])),
        ("rocket_effects", ("tag", "Fireworks", "Explosions", 1, "FireworkTrail"), nbt.ByteTag(0)),
        ("star_effect", ("tag", "customColor"), nbt.IntTag(0)),
    ],
)
def test_disk_oracle_rejects_special_corruption_even_if_script_snapshot_passes(special_cases, profile, path, replacement):
    records = synthetic_carriers(special_cases)
    records.update(build_item_writes(records, special_cases))
    # First prove this fixture passes. Otherwise an unrelated malformed item
    # could satisfy every negative assertion and hide a broken observer.
    assert verify_saved_items(records, special_cases)["cases"] == len(special_cases)
    case = next(case for case in special_cases if case["profile"] == profile)
    key, actor, field = carriers(records, {case["carrier"]})[case["carrier"]]
    target = indexed_items(actor.tag[field])[case["slot"]]
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = deepcopy(replacement)
    records[key] = save_player_nbt(actor)
    validate_case_events([{"kind": "case", "case_id": case["case_id"], "snapshot": expected_snapshot(case)} for case in special_cases], special_cases)
    with pytest.raises(ProbeError):
        verify_saved_items(records, special_cases)


@pytest.mark.parametrize("fault", ["append_blank", "pad_to_49", "remove_blank", "move_blank"])
def test_disk_oracle_checks_blank_book_page_count_and_position(special_cases, fault):
    records = synthetic_carriers(special_cases)
    records.update(build_item_writes(records, special_cases))
    expected = special_cases
    if fault in {"append_blank", "pad_to_49"}:
        expected = revision_cases(special_cases)
        records.update(build_item_writes(records, expected))
    verify_saved_items(records, expected)
    case = next(case for case in expected if case["profile"] == "book_pages")
    key, actor, field = carriers(records, {case["carrier"]})[case["carrier"]]
    pages = indexed_items(actor.tag[field])[case["slot"]]["tag"]["pages"]
    if fault in {"append_blank", "pad_to_49"}:
        added = 1 if fault == "append_blank" else 49 - len(pages)
        for _ in range(added):
            pages.append(nbt.CompoundTag({"text": nbt.StringTag(""), "photoname": nbt.StringTag("")}))
    elif fault == "remove_blank":
        pages.pop(1)
    else:
        pages.append(pages.pop(1))
    records[key] = save_player_nbt(actor)

    # Outer item snapshots cannot detect added, removed or moved blank pages.
    validate_case_events([{"kind": "case", "case_id": case["case_id"], "snapshot": expected_snapshot(case)} for case in expected], expected)
    with pytest.raises(ProbeError, match="Special NBT changed"):
        verify_saved_items(records, expected)


def test_rejection_checks_detect_a_permissive_writer(monkeypatch):
    from mcbe_editor import inventory

    monkeypatch.setattr(inventory, "build_inventory_nbt", lambda *_: nbt.ListTag([], 10))
    with pytest.raises(ProbeError, match="accepted"):
        verify_special_rejections()


@pytest.mark.parametrize("layout", ["reversed", "dense", "missing"])
def test_nested_revision_origins_follow_persisted_slots_not_row_order(special_cases, layout):
    from scripts.engine_checks.special import resolve_special_edit, verify_special

    records = synthetic_carriers(special_cases)
    records.update(build_item_writes(records, special_cases))
    case = next(case for case in special_cases if case["profile"] == "shulker_nested")
    key, actor, field = carriers(records, {case["carrier"]})[case["carrier"]]
    parent = indexed_items(actor.tag[field])[case["slot"]]
    original = parent["tag"]["Items"]
    original[0]["ProbeOpaque"] = nbt.LongTag(2**50)
    if layout == "dense":
        from mcbe_editor.item_containers import empty_slot

        entries = {entry["Slot"].py_data: entry for entry in original}
        parent["tag"]["Items"] = nbt.ListTag([entries.get(slot, empty_slot(slot)) for slot in range(27)], 10)
    elif layout == "reversed":
        parent["tag"]["Items"] = nbt.ListTag(list(reversed(original)), 10)
    else:
        original.pop()
    request = case["revision"]["special_edit"]
    if layout == "missing":
        with pytest.raises(ProbeError, match="origin"):
            resolve_special_edit(request, parent)
        return
    records[key] = save_player_nbt(actor)
    records.update(build_item_writes(records, revision_cases(special_cases)))
    _key, actor, field = carriers(records, {case["carrier"]})[case["carrier"]]
    revised = indexed_items(actor.tag[field])[case["slot"]]
    verify_special(revised, request)
    moved_sword = next(entry for entry in revised["tag"]["Items"] if entry["Slot"].py_data == 7)
    assert moved_sword["ProbeOpaque"].py_data == 2**50


@pytest.mark.parametrize("standalone", [False, True])
@pytest.mark.parametrize("corrupt_before_revision", [False, True])
def test_worker_revises_only_after_verified_reload_and_preserves_unrelated_records(tmp_path, monkeypatch, special_cases, standalone, corrupt_before_revision):
    from mcbe_editor.db import LevelDbAdapter
    from scripts.engine_checks.nbt_roundtrip import read_records, run
    from scripts.engine_checks.runner import ROOT, WORLD_NAME, nbt_worker, sha256, write_json

    monkeypatch.setenv("MCBE_BACKUP_ROOT", str(tmp_path / "backups"))
    world = tmp_path / "server" / "worlds" / WORLD_NAME
    (world / "db").mkdir(parents=True)
    (world / "levelname.txt").write_text("Synthetic nonplayable fixture", encoding="utf-8")
    write_json(tmp_path / "cases.json", special_cases)
    (tmp_path / "catalog.json").write_bytes((ROOT / "mcbe_editor/resources/item_db.json").read_bytes())
    report = {
        "format": "mcbe-engine-check-v1",
        "suite": "special",
        "phases": {"seed": "pass"},
        "cases_sha256": sha256(tmp_path / "cases.json"),
        "catalog_sha256": sha256(tmp_path / "catalog.json"),
    }
    write_json(tmp_path / "run.json", report)
    records = synthetic_carriers(special_cases)
    db = LevelDbAdapter(str(world / "db"))
    try:
        db.put_batch(records)
    finally:
        db.close()
    invoke = nbt_worker if standalone else run
    assert invoke(tmp_path, "edit")["rejected_special_edits"] == 15
    assert invoke(tmp_path, "verify")["status"] == "pass"
    with pytest.raises(ProbeError, match="failed" if standalone else "first verified reload"):
        invoke(tmp_path, "revise")
    report["phases"]["reload1"] = "pass"
    write_json(tmp_path / "run.json", report)
    if corrupt_before_revision:
        current = read_records(world)
        case = next(case for case in special_cases if case["profile"] == "bundle_diamond")
        key, actor, field = carriers(current, {case["carrier"]})[case["carrier"]]
        parent = indexed_items(actor.tag[field])[case["slot"]]
        parent["tag"]["storage_item_component_content"][63]["Count"] = nbt.ByteTag(63)
        current[key] = save_player_nbt(actor)
        db = LevelDbAdapter(str(world / "db"))
        try:
            db.put_batch({key: current[key]})
        finally:
            db.close()
        # Clearing this bundle would mask the failed first reload without the
        # pre-revision check. The failed revision must leave every record intact.
        with pytest.raises(ProbeError, match="failed" if standalone else "amount"):
            invoke(tmp_path, "revise")
        assert read_records(world) == current
        return
    assert invoke(tmp_path, "revise")["backup_created"]
    report["phases"]["revision"] = "pass"
    write_json(tmp_path / "run.json", report)
    assert invoke(tmp_path, "verify")["status"] == "pass"
    assert read_records(world)[b"unrelated"] == records[b"unrelated"]
    with pytest.raises(ProbeError, match="failed" if standalone else "only once"):
        invoke(tmp_path, "revise")


@pytest.mark.parametrize("fail_at", [None, "reload1_disk", "revision", "reload2_disk"])
def test_runner_requires_each_special_check_before_reporting_pass(tmp_path, monkeypatch, special_inputs, special_cases, fail_at):
    from scripts.engine_checks import runner

    archive, digest = server_zip(tmp_path)
    monkeypatch.setattr(runner, "docker_command", lambda *_args, **_kwargs: json.dumps({"Os": "linux", "Architecture": "amd64", "Id": "sha256:" + "a" * 64}))
    monkeypatch.setattr(runner, "catalog_result", lambda *_args: {"status": "pass", "observations": special_inputs[0]})
    config = {}
    calls = []

    def prepare(_server, current):
        config.clear()
        config.update(deepcopy(current))

    def phase(_server, _directory, name, *_args, **_kwargs):
        calls.append(name)
        if name == "catalog":
            return []
        expected_cases = special_cases if name != "reload2" else revision_cases(special_cases)
        assert config["cases"] == expected_cases
        return [{"kind": "case", "case_id": case["case_id"], "snapshot": expected_snapshot(case, seed=name == "seed")} for case in expected_cases]

    def worker(directory, action):
        current = json.loads((directory / "run.json").read_text(encoding="utf-8"))
        label = config["phase"] + "_disk" if action == "verify" else "revision" if action == "revise" else action
        calls.append(label)
        if label == fail_at:
            raise ProbeError("Synthetic oracle failure")
        if action == "revise":
            assert current["phases"]["reload1"] == "pass"
            assert current["phases"]["revision"] == "running"
        if label == "reload2_disk":
            assert current["phases"]["revision"] == "pass"
        return {"status": "pass", "rejected_special_edits": 15}

    monkeypatch.setattr(runner, "prepare_pack", prepare)
    monkeypatch.setattr(runner, "run_phase", phase)
    monkeypatch.setattr(runner, "nbt_worker", worker)
    directory, report = runner.run_probe(archive, digest, "1.26.52.3", "unused", tmp_path / "runs", "special", 30)
    assert report["status"] == ("fail" if fail_at else "pass")
    if fail_at:
        assert report["special"]["status"] == "incomplete"
        assert calls[-1] == fail_at
        assert report["phases"][fail_at.removesuffix("_disk")] == "fail"
    else:
        assert calls == ["catalog", "seed", "edit", "reload1", "reload1_disk", "revision", "reload2", "reload2_disk"]
        assert report["special"]["status"] == "pass"
        assert "special-editor contents persistence" not in report["not_covered"]
    assert any("gameplay" in gap for gap in report["not_covered"])
    summary = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
    assert summary["special"] == report["special"]


def test_edited_inputs_cannot_silently_mutate_the_frozen_reference(monkeypatch, special_cases):
    from mcbe_editor import inventory

    real_builder = inventory.build_inventory_nbt

    def mutating_builder(wrapper, *args, **kwargs):
        result = real_builder(wrapper, *args, **kwargs)
        book = next(item for item in wrapper["Inventory"] if item["Name"].py_data == "minecraft:written_book")
        book["unexpected"] = nbt.IntTag(1)
        return result

    monkeypatch.setattr(inventory, "build_inventory_nbt", mutating_builder)
    with pytest.raises(ProbeError, match="mutated the original"):
        build_item_writes(synthetic_carriers(special_cases), special_cases)
