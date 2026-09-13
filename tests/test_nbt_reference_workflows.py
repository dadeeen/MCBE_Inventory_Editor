"""Byte-level service comparisons with the independent pre-migration NBT backend.

Synthetic fixtures exercise actual native LevelDB writes. Expectations also
check the original database and reviewed fixture fields, so equal failures or
common data loss cannot pass merely because both backends agree.
"""

from __future__ import annotations

import hashlib
import json
import os
import struct
import subprocess
import sys
import tempfile
import zipfile
from copy import deepcopy
from pathlib import Path

import pytest

from mcbe_editor.db import LevelDbAdapter
from mcbe_editor.leveldb_readonly import ReadonlyLevelDbAdapter
from mcbe_editor.players import decode_player_key, encode_player_key
from mcbe_editor.world import LOCAL_PLAYER_KEY
from tests.test_nbt_reference_write_path import (
    ROOT,
    SERVER_PLAYER_KEY,
    _build_synthetic_world,
    _copy_world,
    _offline_world_writes as _offline_world_writes,
    _private_world_paths,
)

reference = pytest.importorskip("amulet_nbt", reason="Independent NBT oracle runs on Python 3.12")
BACKENDS = ("project", "amulet")
pytestmark = pytest.mark.usefixtures("_offline_world_writes")


def _load(raw):
    return reference.load(raw, compressed=False, little_endian=True, string_decoder=reference.utf8_escape_decoder).tag


def _bytes(tag):
    return reference.NamedTag(tag).save_to(compressed=False, little_endian=True, string_encoder=reference.utf8_escape_encoder)


def _equal(actual, expected, message):
    # Keep private payloads out of pytest's assertion diffs when reusing helpers.
    if actual != expected:
        raise AssertionError(message)


def _snapshot(world, selected=()):
    """Hash every untouched key/value, retaining bytes only for selected records."""
    selected = set(selected)
    records = {key: None for key in selected}
    digest = hashlib.sha256()
    count = 0
    db = ReadonlyLevelDbAdapter(str(world / "db"))
    try:
        for key, value in db.iter_items():
            if key in selected:
                records[key] = value
            else:
                digest.update(len(key).to_bytes(4, "little") + key + hashlib.sha256(value).digest())
                count += 1
    finally:
        db.close()
    return (count, digest.hexdigest()), records


def _assert_delta(original, changed, keys):
    before_digest, before = _snapshot(original, keys)
    after_digest, after = _snapshot(changed, keys)
    _equal(after_digest, before_digest, "Unrelated database records changed")
    assert all(after[key] is not None and after[key] != before[key] for key in keys), "Expected write missing or no-op"
    return before, after


def _write_records(world, records):
    db = LevelDbAdapter(str(world / "db"))
    try:
        db.put_batch(records)
    finally:
        db.close()


def _worker(backend, world, output, request):
    output.parent.mkdir(parents=True, exist_ok=True)
    request_file = output.with_suffix(".request.json")
    request_file.write_text(json.dumps(request), encoding="utf-8")
    runtime = output.parent / (output.stem + "-runtime")
    env = {**os.environ, "MCBE_DATA_ROOT": str(runtime), "MCBE_BACKUP_ROOT": str(runtime / "backups"), "PYTHONIOENCODING": "utf-8"}
    completed = subprocess.run(
        [sys.executable, "-m", "tests.nbt_workflow_worker", "--backend", backend,
         "--world", str(world), "--request", str(request_file), "--output", str(output)],
        cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900,
    )
    assert completed.returncode == 0, f"{backend} {request['operation']} worker failed:\n{completed.stderr}"
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report.pop("nbt_module") == ("amulet_nbt" if backend == "amulet" else "mcbe_editor.nbt")
    return report


def _pair(original, work, request):
    worlds, reports = {}, {}
    for backend in BACKENDS:
        worlds[backend] = work / backend
        _copy_world(original, worlds[backend])
        reports[backend] = _worker(backend, worlds[backend], work / f"{backend}.json", request)
    _equal(reports["project"], reports["amulet"], "Service previews, results or reread views differ between backends")
    return worlds, reports["project"]


@pytest.fixture
def workflow_world(tmp_path):
    world = tmp_path / "source"
    _build_synthetic_world(world)
    # The oracle builds two distinct identities and gameplay states, with
    # unknown source/target roots and nested data, not just a self-transfer.
    _, records = _snapshot(world, (LOCAL_PLAYER_KEY, SERVER_PLAYER_KEY))
    for index, key in enumerate((LOCAL_PLAYER_KEY, SERVER_PLAYER_KEY)):
        tag = _load(records[key])
        tag["UniqueID"] = reference.LongTag(-4294967296 + index)
        tag["ServerId"] = reference.StringTag(f"synthetic-identity-{index}")
        tag[f"OnlyOnPlayer{index}"] = reference.StringTag("must stay with its owner")
        tag["FutureSection"]["signed_zero"] = reference.DoubleTag(-0.0 if index else 0.0)
        tag["XPLevel"] = reference.IntTag(7 + 20 * index)
        tag["Pos"][0] = reference.DoubleTag(12.5 + index)
        tag["Inventory"][0]["Count"] = reference.ByteTag(32 + index)
        tag["abilities"]["mayfly"] = reference.ByteTag(index)
        tag["abilities"]["FutureAbility"] = reference.ByteArrayTag([index, -128, 127])
        tag["Attributes"] = reference.ListTag([
            reference.CompoundTag({"Name": reference.StringTag("minecraft:health"), "Current": reference.FloatTag(14 + index),
                                   "Max": reference.FloatTag(20), "FutureStat": reference.IntArrayTag([index, -2])}),
            reference.CompoundTag({"Name": reference.StringTag(f"addon:identity_{index}"), "Current": reference.FloatTag(-0.0)}),
        ])
        tag["recipe_unlocking"] = reference.CompoundTag({
            "unlocked_recipes": reference.ListTag([reference.StringTag(f"synthetic:recipe_{index}"), reference.StringTag("synthetic:shared")]),
            "used_contexts": reference.IntTag(1 << index), "FutureRecipe": reference.LongArrayTag([index, 2**62]),
        })
        tag["TimeSinceRest"] = reference.IntTag(42 + index)
        tag["HasDiedBefore"] = reference.ByteTag(index)
        if index:
            for field, value in (("DeathDimension", 0), ("DeathPositionX", -12), ("DeathPositionY", 70), ("DeathPositionZ", 24)):
                tag[field] = reference.IntTag(value)
        records[key] = _bytes(tag)
    _write_records(world, records)
    return world


def _mount_cases():
    # All random non-horse stats receive explicit user overrides. Horse random
    # mode has a public seed, so no production randomness needs monkeypatching.
    cases = [{"mount_type": "minecraft:horse", "create_mode": "auto", "horse_profile": {"mode": "random_like_game", "seed": 917}}]
    for mount_type, stats, tamed_values in (
        ("horse", None, (False,)),
        ("donkey", {"health": 30, "temper": 0}, (False, True)),
        ("mule", {"health": 15, "temper": 99}, (False, True)),
        ("skeleton_horse", {"jump_strength": 0.4}, (False,)),
        ("camel", {}, (False,)),
    ):
        for tamed in tamed_values:
            cases.append({"mount_type": f"minecraft:{mount_type}", "create_mode": "synthetic_full", "mount_stats": stats,
                          "tamed": tamed, "horse_profile": {"mode": "custom", "color": 6, "mark_variant": 4,
                                                            "health": 30, "movement": 0.3375, "jump_strength": 1, "temper": 99}})
    for index, case in enumerate(cases):
        # Exercise both appending to an existing digp and a negative/new chunk.
        case["position"] = {"x": 1.5, "y": 65.0, "z": 1.5} if index % 2 == 0 else {"x": -17.5, "y": 70.0, "z": 32.5}
    return cases


def _assert_mounts(original, worlds, report, cases):
    results = report["results"]
    assert len(results) == len(cases)
    actor_keys = [bytes.fromhex(result["actor_key_hex"]) for result in results]
    assert len(set(actor_keys)) == len(cases), "Duplicate mount actor key"
    digp_keys = {bytes.fromhex(result["digp_key_hex"]) for result in results}
    keys = {*actor_keys, *digp_keys}
    expected = None
    for world in worlds.values():
        before, after = _assert_delta(original, world, keys)
        if expected is not None:
            _equal(after, expected, "Mount actor NBT or digp bytes differ between backends")
        expected = after
        expected_digp = {key: before[key] or b"" for key in digp_keys}
        for case, result, key in zip(cases, results, actor_keys, strict=True):
            assert before[key] is None, "Existing actor overwritten"
            assert result["success"] is True and result["write_committed"] is True
            assert result["post_create_validation"]["ok"] is True
            tag = _load(after[key])
            suffix = key[len(b"actorprefix"):]
            assert len(suffix) == 8
            uid = -(int.from_bytes(suffix[:4], "big") << 32) + int.from_bytes(suffix[4:], "big")
            assert tag["UniqueID"].py_data == uid == result["unique_id"]
            assert tag["identifier"].py_data == case["mount_type"]
            _equal([value.py_data for value in tag["Pos"]], [case["position"][axis] for axis in ("x", "y", "z")], "Mount position differs")
            storage = tag["internalComponents"]["EntityStorageKeyComponent"]["StorageKey"].py_data
            assert reference.utf8_escape_encoder(storage) == suffix
            if case.get("tamed"):
                owner = _load(_snapshot(original, (LOCAL_PLAYER_KEY,))[1][LOCAL_PLAYER_KEY])["UniqueID"].py_data
                assert tag["OwnerNew"].py_data == owner and tag["IsTamed"].py_data == 1
            position = case["position"]
            digp = b"digp" + struct.pack("<ii", int(position["x"] // 16), int(position["z"] // 16))
            assert bytes.fromhex(result["digp_key_hex"]) == digp
            assert suffix not in [expected_digp[digp][offset:offset + 8] for offset in range(0, len(expected_digp[digp]), 8)]
            expected_digp[digp] += suffix
        _equal({key: after[key] for key in digp_keys}, expected_digp, "Existing digp entries changed or new actor reference missing")


def test_mount_creation_matches_amulet_through_native_service(workflow_world, tmp_path):
    from mcbe_editor.mount_write import SYNTHETIC_CREATABLE_MOUNT_TYPES, TAMEABLE_MOUNT_TYPES

    cases = _mount_cases()
    assert {case["mount_type"] for case in cases} == set(SYNTHETIC_CREATABLE_MOUNT_TYPES)
    assert {case["mount_type"] for case in cases if case.get("tamed")} == set(TAMEABLE_MOUNT_TYPES)
    worlds, report = _pair(workflow_world, tmp_path / "mounts", {"operation": "mounts", "player_key": encode_player_key(LOCAL_PLAYER_KEY), "cases": cases})
    assert all(result["create_mode_effective"] == "synthetic_full" for result in report["results"])
    _assert_mounts(workflow_world, worlds, report, cases)


@pytest.mark.parametrize("mode,active_template", [("auto", False), ("template_clone", False), ("auto", True)])
def test_mount_template_clone_matches_amulet(workflow_world, tmp_path, mode, active_template):
    template = _load(bytes.fromhex((ROOT / "tests/data/mule_tamed_actor_record.hex").read_text(encoding="utf-8")))
    # Derive an idle, unowned template; active owners/tame state now exclude
    # cloning. The reviewed game record itself remains unchanged on disk.
    if not active_template:
        template["IsTamed"] = reference.ByteTag(0)
        template["OwnerNew"] = reference.LongTag(-1)
        template["definitions"] = reference.ListTag([reference.StringTag(value) for value in (
            "+minecraft:mule", "+minecraft:mule_adult", "+minecraft:mule_wild", "+minecraft:mule_unchested",
        )])
    marker = reference.CompoundTag({"zero": reference.FloatTag(-0.0), "array": reference.LongArrayTag([2**62, -1]),
                                    "raw": reference.StringTag("a␛xffb")})
    template["FutureTemplateData"] = marker
    suffix = struct.pack(">II", 2, 400)
    template["UniqueID"] = reference.LongTag(-(2 << 32) + 400)
    template["internalComponents"]["EntityStorageKeyComponent"]["StorageKey"] = reference.StringTag(reference.utf8_escape_decoder(suffix))
    x, _y, z = (value.py_data for value in template["Pos"])
    digp_key = b"digp" + struct.pack("<ii", int(x // 16), int(z // 16))
    previous_digp = _snapshot(workflow_world, (digp_key,))[1][digp_key] or b""
    _write_records(workflow_world, {b"actorprefix" + suffix: _bytes(template), digp_key: previous_digp + suffix})
    cases = [{"mount_type": "minecraft:horse", "create_mode": mode, "position": {"x": -0.5, "y": 65.0, "z": 0.5},
              "horse_profile": {"mode": "random_like_game", "seed": 617}}]
    worlds, report = _pair(workflow_world, tmp_path / mode, {"operation": "mounts", "player_key": encode_player_key(LOCAL_PLAYER_KEY), "cases": cases})
    result = report["results"][0]
    assert result["create_mode_effective"] == ("synthetic_full" if active_template else "template_clone")
    assert result["template_identifier"] == (None if active_template else "minecraft:mule")
    _assert_mounts(workflow_world, worlds, report, cases)
    for world in worlds.values():
        key = bytes.fromhex(result["actor_key_hex"])
        tag = _load(_snapshot(world, (key,))[1][key])
        if active_template:
            assert "FutureTemplateData" not in tag
        else:
            _equal(_bytes(tag["FutureTemplateData"]), _bytes(marker), "Unknown template data lost")


def _assert_transfer_contract(source_raw, target_raw, after_raw):
    source, target, after = map(_load, (source_raw, target_raw, after_raw))
    # Independent fixture contract; do not call the production merge/validator
    # or derive expectations from its allowlists.
    copied = {"Inventory", "EnderChestInventory", "Armor", "Offhand", "Pos", "Rotation", "DimensionId", "Health", "PlayerGameType",
              "XPLevel", "XPProgress", "foodLevel", "foodSaturationLevel", "ActiveEffects", "TimeSinceRest", "HasDiedBefore",
              "DeathDimension", "DeathPositionX", "DeathPositionY", "DeathPositionZ"}
    expected = deepcopy(target)
    for field in copied:
        if field in source:
            expected[field] = source[field]
        elif field in expected:
            del expected[field]
    for field in ("mayfly", "flying", "invulnerable", "maybuild", "instabuild"):
        expected["abilities"][field] = source["abilities"][field]
    expected["Attributes"][0] = source["Attributes"][0]
    target_recipes = expected["recipe_unlocking"]
    recipe_ids = [entry.py_data for entry in target_recipes["unlocked_recipes"]]
    for entry in source["recipe_unlocking"]["unlocked_recipes"]:
        if entry.py_data not in recipe_ids:
            target_recipes["unlocked_recipes"].append(entry)
    target_recipes["used_contexts"] = reference.IntTag(3)
    _equal({key: _bytes(value) for key, value in after.items()}, {key: _bytes(value) for key, value in expected.items()},
           "Transferred gameplay or preserved identity/unknown NBT violates fixture contract")


@pytest.mark.parametrize(
    "source_key,target_key", [(LOCAL_PLAYER_KEY, SERVER_PLAYER_KEY), (SERVER_PLAYER_KEY, LOCAL_PLAYER_KEY)],
    ids=["local-to-server", "server-to-local"],
)
def test_player_transfer_matches_amulet(workflow_world, tmp_path, source_key, target_key):
    _compare_transfer(workflow_world, tmp_path / "transfer", source_key, target_key, fixture_contract=True)


def _compare_transfer(original, work, source_key, target_key, *, fixture_contract=False):
    request = {"operation": "transfer", "source": encode_player_key(source_key), "target": encode_player_key(target_key)}
    worlds, report = _pair(original, work, request)
    assert report["result"]["source_deleted"] is False and report["result"]["world_changed"] is True
    assert report["before"]["player_revision"] != report["after"]["player_revision"]
    source = _snapshot(original, (source_key,))[1][source_key]
    expected = None
    for world in worlds.values():
        before, after = _assert_delta(original, world, (target_key,))
        if fixture_contract:
            _assert_transfer_contract(source, before[target_key], after[target_key])
        else:
            # Real source NBT has additional gameplay fields. The destination
            # is still our reviewed synthetic player with these sentinels.
            target, written = _load(before[target_key]), _load(after[target_key])
            for field in ("UniqueID", "ServerId", "FutureSection"):
                _equal(_bytes(written[field]), _bytes(target[field]), "Private transfer lost target identity/unknown data")
            _equal(_bytes(written["abilities"]["FutureAbility"]), _bytes(target["abilities"]["FutureAbility"]), "Unknown ability lost")
            _equal(_bytes(written["Inventory"]), _bytes(_load(source)["Inventory"]), "Private source inventory was not transferred")
        if expected is not None:
            _equal(after, expected, "Transferred player NBT differs between backends")
        expected = after


def _archive_payload(path):
    with zipfile.ZipFile(path) as archive:
        assert sorted(archive.namelist()) == ["manifest.json", "player.nbt", "preview.json"]
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest.pop("created_at"), "Export timestamp missing"
        return {"manifest": manifest, "preview": archive.read("preview.json"), "nbt": archive.read("player.nbt")}


@pytest.mark.parametrize("source_key", [LOCAL_PLAYER_KEY, SERVER_PLAYER_KEY], ids=["local", "server"])
@pytest.mark.parametrize("new_player", [False, True], ids=["overwrite", "create"])
def test_exports_and_cross_backend_imports_match_original(workflow_world, tmp_path, source_key, new_player):
    _compare_exports_imports(workflow_world, tmp_path, source_key, new_player)


def _compare_exports_imports(workflow_world, tmp_path, source_key, new_player, target_key=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    source_raw = _snapshot(workflow_world, (source_key,))[1][source_key]
    archives, export_reports = {}, {}
    original_digest = _snapshot(workflow_world)
    for backend in BACKENDS:
        with tempfile.TemporaryDirectory(prefix=f"export-{backend}-", dir=tmp_path) as directory:
            source_copy = Path(directory) / "world"
            _copy_world(workflow_world, source_copy)
            output = tmp_path / f"export-{backend}.json"
            export_reports[backend] = _worker(backend, source_copy, output, {"operation": "export", "player_key": encode_player_key(source_key)})
            archives[backend] = output.with_suffix(".zip")
            payload = _archive_payload(archives[backend])
            _equal(payload["nbt"], source_raw, "Export NBT differs from original database bytes")
            assert payload["manifest"]["nbt"]["byte_length"] == len(source_raw)
            _equal(_snapshot(source_copy), original_digest, "Export changed source database")
    _equal(export_reports["project"], export_reports["amulet"], "Export service views differ")
    _equal(_archive_payload(archives["project"]), _archive_payload(archives["amulet"]), "Export archive payloads differ")

    target_key = target_key or (source_key if new_player else (SERVER_PLAYER_KEY if source_key == LOCAL_PLAYER_KEY else LOCAL_PLAYER_KEY))
    baseline = tmp_path / "import-baseline"
    _copy_world(workflow_world, baseline)
    if new_player:
        _write_records(baseline, {target_key: None})
    expected = None
    for exporter in BACKENDS:
        for importer in BACKENDS:
            with tempfile.TemporaryDirectory(prefix=f"import-{exporter}-{importer}-", dir=tmp_path) as directory:
                destination = Path(directory) / "world"
                _copy_world(baseline, destination)
                report = _worker(importer, destination, destination.with_suffix(".json"), {
                    "operation": "import", "archive": str(archives[exporter]), "target": encode_player_key(target_key), "new_player": new_player,
                })
                assert report["result"]["created_new_player"] is new_player
                _, after = _assert_delta(baseline, destination, (target_key,))
                _equal(after[target_key], source_raw, "Imported NBT differs from original export source")
                if expected is not None:
                    _equal(report, expected, "Cross-backend import preview, result or reread view differs")
                expected = report


@pytest.mark.parametrize("fault", ["unknown-data", "signed-zero"])
def test_transfer_comparison_rejects_common_corruption(workflow_world, tmp_path, fault):
    source, target = LOCAL_PLAYER_KEY, SERVER_PLAYER_KEY
    worlds, _report = _pair(workflow_world, tmp_path / "fault", {
        "operation": "transfer", "source": encode_player_key(source), "target": encode_player_key(target),
    })
    originals = _snapshot(workflow_world, (source, target))[1]
    for world in worlds.values():
        corrupted = _load(_snapshot(world, (target,))[1][target])
        if fault == "unknown-data":
            del corrupted["FutureSection"]["bytes"]
        else:
            corrupted["FutureSection"]["signed_zero"] = reference.DoubleTag(0.0)
        with pytest.raises(AssertionError, match="fixture contract"):
            _assert_transfer_contract(originals[source], originals[target], _bytes(corrupted))


@pytest.mark.parametrize("fault", ["digp-loss", "unrelated-record", "no-op"])
def test_mount_comparison_rejects_common_corruption(workflow_world, tmp_path, fault):
    cases = _mount_cases()[:1]
    worlds, report = _pair(workflow_world, tmp_path / "fault", {
        "operation": "mounts", "player_key": encode_player_key(LOCAL_PLAYER_KEY), "cases": cases,
    })
    for world in worlds.values():
        if fault == "digp-loss":
            key = bytes.fromhex(report["results"][0]["digp_key_hex"])
            _write_records(world, {key: _snapshot(world, (key,))[1][key][8:]})
        elif fault == "unrelated-record":
            _write_records(world, {b"BiomeData": b"unexpected common corruption"})
    if fault == "no-op":
        worlds = {backend: workflow_world for backend in BACKENDS}
    with pytest.raises(AssertionError, match="digp|Unrelated|write missing"):
        _assert_mounts(workflow_world, worlds, report, cases)


@pytest.mark.private_world
@pytest.mark.destructive
@pytest.mark.slow
def test_private_world_workflows_match_amulet_on_temporary_copies(workflow_world, tmp_path):
    from mcbe_editor.item_data import ENCHANTMENTS, ITEMS
    from mcbe_editor.services import BedrockEditorService

    service = BedrockEditorService(ITEMS, ENCHANTMENTS)
    compared = 0
    for index, private_world in enumerate(_private_world_paths()):
        # All writes, backups, exports and imported records are confined to
        # this disposable directory; originals are only copied, never opened.
        with tempfile.TemporaryDirectory(prefix=f"private-{index}-", dir=tmp_path) as directory:
            work = Path(directory)
            baseline = work / "baseline"
            _copy_world(private_world, baseline)
            players = service.list_players(str(baseline))["players"]
            editable = [player for player in players if player.get("editable") and player.get("player_key")]
            if not editable:
                continue
            player = next((entry for entry in editable if entry["kind"] == "local"), editable[0])
            source_key = decode_player_key(player["player_key"])
            target_key = SERVER_PLAYER_KEY if player["kind"] == "local" else LOCAL_PLAYER_KEY
            target_raw = _snapshot(workflow_world, (target_key,))[1][target_key]
            _write_records(baseline, {target_key: target_raw})
            with tempfile.TemporaryDirectory(prefix="transfer-", dir=work) as stage:
                _compare_transfer(baseline, Path(stage), source_key, target_key)
            with tempfile.TemporaryDirectory(prefix="exchange-", dir=work) as stage:
                _compare_exports_imports(baseline, Path(stage), source_key, False, target_key)
            case = {"mount_type": "minecraft:horse", "create_mode": "synthetic_full",
                    "position": {"x": -17.5, "y": 70.0, "z": 32.5}, "horse_profile": {"mode": "random_like_game", "seed": 917}}
            worlds, report = _pair(baseline, work / "mount", {"operation": "mounts", "player_key": player["player_key"], "cases": [case]})
            _assert_mounts(baseline, worlds, report, [case])
            compared += 1
            print(f"Private world #{index + 1}: transfer, cross-backend import/export and mount bytes verified", flush=True)
    if not compared:
        pytest.skip("No editable players in the selected private fixtures")
