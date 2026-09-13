"""Differential check of the editor write path against the Amulet-NBT backend.

Opt-in like ``tests/test_nbt_reference.py``: it runs only where the independent
reference lock is installed (Python 3.12) and is skipped elsewhere. Disposable
copies of one world receive the identical player edit through the real service
layer in separate processes, once with the project codec and once with
Amulet-NBT installed as ``mcbe_editor.nbt``, the module binding the editor used
before the standard-library codec. Both results must be byte-identical, and
only the edited player records may differ from the untouched original.

No private data lives in this file. The always-on case builds a synthetic
world. The private-world case reads the git-ignored ``fixtures/private``
directory only with the same environment flags as the other private-world
tests, and writes exclusively to temporary copies.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

import mcbe_editor.db as db_module
from mcbe_editor import nbt
from mcbe_editor.db import LevelDbAdapter
from mcbe_editor.players import decode_player_key, encode_player_key
from mcbe_editor.world import LOCAL_PLAYER_KEY, scan_minecraft_worlds

reference = pytest.importorskip("amulet_nbt", reason="Independent NBT oracle runs on Python 3.12")

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_WORLD_ROOT = ROOT / "fixtures" / "private"
SERVER_PLAYER_KEY = b"player_server_11111111-2222-3333-4444-555555555555"
TRUE_VALUES = {"1", "true", "yes", "ja", "on"}
DEFAULT_MAX_WORLDS = 3


@pytest.fixture
def _offline_world_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the web write guard out of explicit offline writes to disposable worlds."""
    monkeypatch.setattr(db_module, "_runtime_app_modules", lambda: ())
    monkeypatch.setattr(db_module, "_registered_write_guard", None)


def _item(slot: int, name: str, count: int = 1, damage: int = 0, tag=None):
    item = nbt.CompoundTag(
        {
            "Slot": nbt.ByteTag(slot),
            "Name": nbt.StringTag(name),
            "Count": nbt.ByteTag(count),
            "Damage": nbt.ShortTag(damage),
            "WasPickedUp": nbt.ByteTag(0),
        }
    )
    if tag is not None:
        item["tag"] = tag
    return item


def _synthetic_player(*, ender_chest: bool) -> bytes:
    pickaxe_tag = nbt.CompoundTag(
        {
            "Damage": nbt.IntTag(3),
            "RepairCost": nbt.IntTag(2),
            "ench": nbt.ListTag([nbt.CompoundTag({"id": nbt.ShortTag(15), "lvl": nbt.ShortTag(2)})]),
            "display": nbt.CompoundTag({"Name": nbt.StringTag("§bSpitzhacke"), "Lore": nbt.ListTag([nbt.StringTag("Grüße 世界")])}),
            # Unknown item NBT that a save must carry through untouched.
            "FutureComponent": nbt.CompoundTag(
                {
                    "long": nbt.LongTag(-5),
                    "ints": nbt.IntArrayTag([1, -2, 3]),
                    "negative_zero": nbt.FloatTag(-0.0),
                    "raw": nbt.StringTag("a␛xffb"),
                }
            ),
        }
    )
    effect = nbt.CompoundTag(
        {
            "Id": nbt.ByteTag(1),
            "Amplifier": nbt.ByteTag(0),
            "Duration": nbt.IntTag(600),
            "DurationEasy": nbt.IntTag(600),
            "DurationNormal": nbt.IntTag(600),
            "DurationHard": nbt.IntTag(600),
            "Ambient": nbt.ByteTag(0),
            "ShowParticles": nbt.ByteTag(1),
            "ShowIcon": nbt.ByteTag(1),
        }
    )
    player = nbt.CompoundTag(
        {
            "Inventory": nbt.ListTag(
                [
                    _item(0, "minecraft:stone", 64),
                    _item(1, "minecraft:bow", 1, 12),
                    _item(2, "minecraft:diamond_pickaxe", 1, 3, pickaxe_tag),
                    _item(9, "minecraft:apple", 5),
                    _item(35, "minecraft:torch", 3),
                ]
            ),
            "Armor": nbt.ListTag(
                [
                    _item(0, "minecraft:leather_helmet"),
                    _item(1, "minecraft:iron_chestplate"),
                    _item(2, "minecraft:leather_leggings"),
                    _item(3, "minecraft:leather_boots"),
                ]
            ),
            "Offhand": nbt.ListTag([_item(0, "minecraft:shield")]),
            "ActiveEffects": nbt.ListTag([effect]),
            "abilities": nbt.CompoundTag(
                {
                    "mayfly": nbt.ByteTag(0),
                    "flying": nbt.ByteTag(0),
                    "invulnerable": nbt.ByteTag(0),
                    "maybuild": nbt.ByteTag(1),
                    "instabuild": nbt.ByteTag(0),
                    "fly_speed": nbt.FloatTag(0.05),
                    "walk_speed": nbt.FloatTag(0.1),
                    "attackmobs": nbt.ByteTag(1),
                }
            ),
            "Pos": nbt.ListTag([nbt.DoubleTag(12.5), nbt.DoubleTag(64.0), nbt.DoubleTag(-7.25)]),
            "Rotation": nbt.ListTag([nbt.FloatTag(90.0), nbt.FloatTag(-12.5)]),
            "Health": nbt.FloatTag(17.5),
            "PlayerGameType": nbt.IntTag(0),
            "XPLevel": nbt.IntTag(7),
            "XPProgress": nbt.FloatTag(0.4),
            "foodLevel": nbt.IntTag(18),
            "foodSaturationLevel": nbt.FloatTag(4.5),
            "DimensionId": nbt.IntTag(0),
            "UniqueID": nbt.LongTag(-4294967296),
            # Unknown top-level data: must survive the save byte for byte.
            "FutureSection": nbt.CompoundTag({"longs": nbt.LongArrayTag([2**62, -1]), "bytes": nbt.ByteArrayTag([1, 2, 3])}),
        }
    )
    if ender_chest:
        player["EnderChestInventory"] = nbt.ListTag([_item(0, "minecraft:gold_ingot", 12), _item(26, "minecraft:emerald", 2)])
    return nbt.NamedTag(player).save_to(compressed=False, little_endian=True)


def _build_synthetic_world(path: Path) -> None:
    (path / "db").mkdir(parents=True)
    (path / "levelname.txt").write_text("Differential World", encoding="utf-8")
    cow = nbt.CompoundTag(
        {
            "identifier": nbt.StringTag("minecraft:cow"),
            "Pos": nbt.ListTag([nbt.FloatTag(1.0), nbt.FloatTag(64.0), nbt.FloatTag(1.0)]),
            "UniqueID": nbt.LongTag(-(2 << 32) + 1),
        }
    )
    # Bedrock actor keys/digp use big-endian (group, local ID), not the
    # little-endian signed UniqueID stored inside the entity's NBT.
    actor_id = (2).to_bytes(4, "big") + (1).to_bytes(4, "big")
    records = {
        LOCAL_PLAYER_KEY: _synthetic_player(ender_chest=True),
        SERVER_PLAYER_KEY: _synthetic_player(ender_chest=False),
        b"actorprefix" + actor_id: nbt.NamedTag(cow).save_to(compressed=False, little_endian=True),
        b"digp" + bytes(8): actor_id,
        b"BiomeData": bytes(range(256)),
    }
    db = LevelDbAdapter(str(path / "db"))
    try:
        db.put_batch(records)
    finally:
        db.close()


def _run_worker(backend: str, world: Path, output: Path, *, edit: bool = True) -> dict:
    command = [sys.executable, "-m", "tests.nbt_backend_worker", "--backend", backend, "--world", str(world), "--output", str(output)]
    if not edit:
        command.append("--no-edit")
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
    assert completed.returncode == 0, f"{backend} worker failed:\n{completed.stdout}\n{completed.stderr}"
    return json.loads(output.read_text(encoding="utf-8"))


def _untouched_player_nbt(raw: bytes, payload: dict) -> dict:
    """Retain everything outside the worker's explicit edit, using the independent codec.

    This is the contract of edit_payload, not an invocation of the production
    writer. Whole untouched items and unknown subtrees retain their binary
    representation, including tag types, raw strings and signed floating zero.
    """
    named = reference.load(raw, compressed=False, little_endian=True, string_decoder=reference.utf8_escape_decoder)
    root = named.tag

    def serialized(tag):
        return reference.NamedTag(tag).save_to(compressed=False, little_endian=True, string_encoder=reference.utf8_escape_encoder)

    def omit(compound, keys):
        for key in keys:
            if key in compound:
                del compound[key]

    preserved = {}
    containers = {"Inventory": {0, 1}}
    if payload.get("ender_chest") is not None:
        containers["EnderChestInventory"] = {0}
    for name, replaced_slots in containers.items():
        entries = root.get(name)
        if entries is not None and not isinstance(entries, reference.ListTag):
            continue  # An opaque container is not an editable item list.
        preserved[name] = [
            serialized(item) for item in (() if entries is None else entries)
            if not (isinstance(item, reference.CompoundTag) and isinstance(item.get("Slot"), reference.ByteTag)
                    and item["Slot"].py_data in replaced_slots)
        ]
        omit(root, (name,))

    # Only these scalar fields and their matching attribute Current values are
    # changed by edit_payload. Attribute limits and unknown members stay intact.
    stat_fields = {
        "health": (("Health",), "minecraft:health"),
        "xp_level": (("PlayerLevel", "XPLevel"), "minecraft:player.level"),
        "xp_progress": (("PlayerLevelProgress", "XPProgress"), "minecraft:player.experience"),
        "food_level": (("foodLevel",), "minecraft:player.hunger"),
    }
    attributes = set()
    for field in payload.get("stats") or {}:
        names, attribute = stat_fields[field]
        omit(root, names)
        attributes.add(attribute)
    if isinstance(root.get("Attributes"), reference.ListTag):
        for entry in root["Attributes"]:
            if isinstance(entry, reference.CompoundTag) and isinstance(entry.get("Name"), reference.StringTag):
                name = entry["Name"].py_data
                if name in attributes:
                    omit(entry, ("Current",))
                    attributes.remove(name)

    if payload.get("abilities") and isinstance(root.get("abilities"), reference.CompoundTag):
        omit(root["abilities"], ("mayfly", "flySpeed"))
        if not root["abilities"]:
            del root["abilities"]
    if payload.get("effects") and isinstance(root.get("ActiveEffects"), reference.ListTag):
        changed_effect = payload["effects"][0]["id"]
        for effect in root["ActiveEffects"]:
            if (isinstance(effect, reference.CompoundTag) and isinstance(effect.get("Id"), reference.ByteTag)
                    and effect["Id"].py_data & 0xFF == changed_effect):
                omit(effect, ("Amplifier", "Duration"))
                break
    preserved["root"] = named.save_to(compressed=False, little_endian=True, string_encoder=reference.utf8_escape_encoder)
    return preserved


def _compare_backends(world: Path, work: Path, *, copy_from: Path | None = None) -> tuple[dict, dict, set[str]]:
    """Run baseline, project and Amulet workers; return both edit reports and the edited keys."""
    reports = {}
    for variant in ("baseline", "project", "amulet"):
        target = work / variant
        if copy_from is not None:
            _copy_world(copy_from, target)
        else:
            shutil.copytree(world, target)
        reports[variant] = _run_worker("project" if variant == "baseline" else variant, target, work / f"{variant}.json", edit=variant != "baseline")
    baseline, project, amulet = reports["baseline"], reports["project"], reports["amulet"]
    assert project["nbt_module"] == "mcbe_editor.nbt"
    assert amulet["nbt_module"] == "amulet_nbt"
    for report in (project, amulet):
        for entry in report["players"].values():
            if entry["save"].get("success") is not True or entry["save"].get("no_op"):
                raise AssertionError(f"{report['backend']}: every editable player must have a successful save that changes the record")
    assert set(project["players"]) == set(amulet["players"])
    assert project["players"] == amulet["players"], "payloads, views and save results must not depend on the NBT backend"
    assert project["player_records"] == amulet["player_records"], "written player records must be byte-identical"
    for report in (project, amulet):
        assert report["non_player_count"] == baseline["non_player_count"]
        assert report["non_player_digest"] == baseline["non_player_digest"], "no other database value may change"
    changed = {
        key
        for key in set(baseline["player_records"]) | set(project["player_records"])
        if baseline["player_records"].get(key) != project["player_records"].get(key)
    }
    edited = {decode_player_key(key).hex() for key in project["players"]}
    assert changed == edited, "only the successfully edited player records may differ from the original"
    for report in (project, amulet):
        for key, entry in report["players"].items():
            raw_key = decode_player_key(key).hex()
            before = _untouched_player_nbt(bytes.fromhex(baseline["player_records"][raw_key]), entry["payload"])
            after = _untouched_player_nbt(bytes.fromhex(report["player_records"][raw_key]), entry["payload"])
            if before != after:
                # Do not include private NBT values in assertion diffs.
                raise AssertionError(f"{report['backend']}: untouched player NBT differs from the original")
            assert entry["after"]["player_revision"] != entry["before"]["player_revision"]
    return project, amulet, edited


def test_synthetic_world_edit_is_byte_identical_across_nbt_backends(tmp_path: Path, _offline_world_writes) -> None:
    source = tmp_path / "source"
    _build_synthetic_world(source)

    project, _amulet, edited = _compare_backends(source, tmp_path / "run")

    assert edited == {LOCAL_PLAYER_KEY.hex(), SERVER_PLAYER_KEY.hex()}
    local = project["players"][encode_player_key(LOCAL_PLAYER_KEY)]
    server = project["players"][encode_player_key(SERVER_PLAYER_KEY)]
    for entry in (local, server):
        assert entry["save"] == {"success": True, "no_op": False}
        assert entry["after"]["player_revision"] != entry["before"]["player_revision"]
        after = entry["after"]
        assert after["stats"]["xp_level"] == 42
        assert after["stats"]["health"] == 19.0
        assert after["stats"]["food_level"] == 19
        assert after["inventory"]["0"]["name"] == "minecraft:diamond"
        assert after["inventory"]["0"]["count"] == 7
        assert after["inventory"]["1"]["enchantments"] == [{"id": 9, "lvl": 3}]
        assert after["inventory"]["1"]["display_name"] == "Differential"
        assert after["inventory"]["2"]["name"] == "minecraft:diamond_pickaxe"
        assert after["effects"][0]["duration"] == 1234
        assert after["abilities"]["mayfly"] is True
    assert local["after"]["ender_chest"]["0"]["count"] == 3
    assert server["after"]["has_ender_chest"] is False

    saved = nbt.load(bytes.fromhex(project["player_records"][LOCAL_PLAYER_KEY.hex()])).tag
    assert list(saved["FutureSection"]["longs"]) == [2**62, -1]
    assert saved["abilities"]["attackmobs"].py_data == 1
    pickaxe = next(item for item in saved["Inventory"] if item["Name"].py_data == "minecraft:diamond_pickaxe")
    assert pickaxe["tag"]["FutureComponent"]["raw"].py_data == "a␛xffb"
    assert list(pickaxe["tag"]["FutureComponent"]["ints"]) == [1, -2, 3]
    assert saved["Armor"][1]["Name"].py_data == "minecraft:iron_chestplate"
    assert saved["Offhand"][0]["Name"].py_data == "minecraft:shield"


def _env_enabled(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in TRUE_VALUES


def _env_limit(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    try:
        return max(1, int(raw)) if raw else default
    except ValueError:
        return default


def _private_world_paths() -> list[Path]:
    if not (_env_enabled("MCBE_RUN_PRIVATE_WORLD_TESTS") and _env_enabled("MCBE_RUN_PRIVATE_WORLD_WRITE_TESTS")):
        pytest.skip("Private Weltkopien werden nur mit MCBE_RUN_PRIVATE_WORLD_TESTS=1 und MCBE_RUN_PRIVATE_WORLD_WRITE_TESTS=1 verglichen.")
    if not PRIVATE_WORLD_ROOT.is_dir():
        pytest.skip("Keine privaten Welt-Fixtures unter fixtures/private vorhanden.")
    entries = scan_minecraft_worlds(paths=[str(PRIVATE_WORLD_ROOT)])
    if not entries:
        pytest.skip("Keine direkten Bedrock-Weltordner unter fixtures/private gefunden.")
    return [Path(entry["path"]) for entry in entries[: _env_limit("MCBE_PRIVATE_WORLD_MAX_WORLDS", DEFAULT_MAX_WORLDS)]]


def _copy_world(source: Path, target: Path) -> None:
    def ignore_generated_or_linked_entries(directory: str, names: list[str]) -> list[str]:
        ignored = []
        for name in names:
            candidate = Path(directory) / name
            if candidate.is_symlink() or name.endswith("_backups") or "_rollback_" in name or "_restoring_" in name or "_player_import_" in name:
                ignored.append(name)
        return ignored

    shutil.copytree(source, target, ignore=ignore_generated_or_linked_entries)


@pytest.mark.private_world
@pytest.mark.destructive
@pytest.mark.slow
def test_private_world_copies_edit_is_byte_identical_across_nbt_backends(tmp_path: Path) -> None:
    compared = 0
    for index, source in enumerate(_private_world_paths()):
        work = tmp_path / f"world_{index}"
        try:
            project, _amulet, edited = _compare_backends(source, work, copy_from=source)
        except AssertionError as exc:
            raise AssertionError(f"Private Welt #{index + 1}: {exc}") from None
        finally:
            # Large private worlds are copied three times; free the space before the next world.
            shutil.rmtree(work, ignore_errors=True)
        if project["players"]:
            compared += 1
    if compared == 0:
        pytest.skip("Keine editierbaren Spieler in den ausgewählten privaten Welten gefunden.")


@pytest.fixture(scope="module")
def _successful_backend_reports(tmp_path_factory):
    root = tmp_path_factory.mktemp("reference-write-reports")
    source = root / "source"
    with pytest.MonkeyPatch.context() as patcher:
        patcher.setattr(db_module, "_runtime_app_modules", lambda: ())
        patcher.setattr(db_module, "_registered_write_guard", None)
        _build_synthetic_world(source)
    _compare_backends(source, root / "run")
    reports = {name: json.loads((root / "run" / f"{name}.json").read_text(encoding="utf-8")) for name in ("baseline", "project", "amulet")}
    return source, reports


def _use_backend_reports(monkeypatch, reports):
    monkeypatch.setattr(sys.modules[__name__], "_run_worker", lambda backend, world, output, *, edit=True: deepcopy(reports[backend if edit else "baseline"]))


@pytest.mark.parametrize("save_result", [{"error": "Injected save regression"}, {"success": False, "no_op": False}, {"success": True, "no_op": True}])
def test_private_comparison_rejects_common_save_failures(tmp_path, monkeypatch, _successful_backend_reports, save_result):
    source, original = _successful_backend_reports
    reports = deepcopy(original)
    for backend in ("project", "amulet"):
        reports[backend]["player_records"] = deepcopy(reports["baseline"]["player_records"])
        for entry in reports[backend]["players"].values():
            entry["save"] = save_result
            entry["after"] = deepcopy(entry["before"])
    _use_backend_reports(monkeypatch, reports)
    monkeypatch.setattr(sys.modules[__name__], "_private_world_paths", lambda: [source])
    with pytest.raises(AssertionError, match="every editable player must have a successful save"):
        test_private_world_copies_edit_is_byte_identical_across_nbt_backends(tmp_path)


@pytest.mark.parametrize("player_key", [LOCAL_PLAYER_KEY, SERVER_PLAYER_KEY])
@pytest.mark.parametrize("mutation", ["delete_array", "change_zero_sign"])
def test_comparison_rejects_common_untouched_nbt_corruption(tmp_path, monkeypatch, _successful_backend_reports, player_key, mutation):
    source, original = _successful_backend_reports
    reports = deepcopy(original)
    for backend in ("project", "amulet"):
        named = nbt.load(bytes.fromhex(reports[backend]["player_records"][player_key.hex()]))
        if mutation == "delete_array":
            del named.tag["FutureSection"]["bytes"]
        else:
            pickaxe = next(item for item in named.tag["Inventory"] if item["Name"].py_data == "minecraft:diamond_pickaxe")
            pickaxe["tag"]["FutureComponent"]["negative_zero"] = nbt.FloatTag(0.0)
        reports[backend]["player_records"][player_key.hex()] = named.save_to().hex()
    _use_backend_reports(monkeypatch, reports)
    with pytest.raises(AssertionError, match="untouched player NBT differs from the original"):
        _compare_backends(source, tmp_path / "run")


def test_private_comparison_skips_only_without_editable_players(tmp_path, monkeypatch, _successful_backend_reports):
    source, original = _successful_backend_reports
    reports = deepcopy(original)
    for backend in ("project", "amulet"):
        reports[backend]["players"] = {}
        reports[backend]["player_records"] = deepcopy(reports["baseline"]["player_records"])
    _use_backend_reports(monkeypatch, reports)
    monkeypatch.setattr(sys.modules[__name__], "_private_world_paths", lambda: [source])
    with pytest.raises(pytest.skip.Exception, match="Keine editierbaren Spieler"):
        test_private_world_copies_edit_is_byte_identical_across_nbt_backends(tmp_path)
