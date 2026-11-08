"""Offline editor writes and native saved-trade evidence for natural villages."""

from __future__ import annotations

import json
import re
import sys
import zipfile
from copy import deepcopy
from pathlib import Path

from .village_profile import CASE_IDS, ROLES, _carrots, require, same_persisted_actor, validate_village_events, validate_village_plan
from .villager_worker import find_actors, health_snapshot, inventory_snapshot, verify_write_preservation


def _inputs(run_dir: Path) -> tuple[Path, dict, dict]:
    from .runner import WORLD_NAME, sha256, source_hashes

    require(not run_dir.is_symlink() and not run_dir.is_junction(), "Village run directory may not be a link")
    run_dir = run_dir.resolve(strict=True)
    report = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    require(report.get("format") == "mcbe-engine-check-v1" and report.get("suite") == "village", "Worker requires a natural village run")
    require(isinstance(report.get("run_id"), str) and bool(re.fullmatch(r"[a-f0-9]{32}", report["run_id"])), "Missing natural village run identity")
    require(report.get("phases", {}).get("seed") == "pass", "Live natural village seed phase must complete")
    require(all(report.get("editor", {}).get(key) == value for key, value in source_hashes().items()), "Village probe/editor sources changed")
    require(sha256(run_dir / "village-plan.json") == report.get("village_plan_sha256"), "Natural village plan changed")
    require(sha256(run_dir / "catalog.json") == report.get("catalog_sha256"), "Natural village catalog changed")
    plan = json.loads((run_dir / "village-plan.json").read_text(encoding="utf-8"))
    validate_village_plan(plan)
    world = run_dir / "server" / "worlds" / WORLD_NAME
    for path in (run_dir / "server", run_dir / "server/worlds", world, world / "db"):
        require(
            path.resolve(strict=True).is_relative_to(run_dir) and not path.is_symlink() and not path.is_junction(), "Natural village escaped its disposable run"
        )
    return world, report, plan


def _evidence(run_dir: Path, plan: dict, phase: str) -> dict:
    raw = json.loads((run_dir / f"{phase}.village.json").read_text(encoding="utf-8"))
    require(raw.get("status") == "pass" and raw.get("phase") == phase and isinstance(raw.get("observations"), dict), "Missing verified village live evidence")
    order = (("origin",) if phase == "seed" else ()) + CASE_IDS
    require(set(raw["observations"]) == set(order), "Incomplete village live evidence")
    events = [{"kind": "case", "case_id": key, "snapshot": raw["observations"][key]} for key in order]
    return validate_village_events(events, plan, phase=phase)["observations"]


def trade_snapshot(root) -> dict:
    """Native offer usage and experience independently corroborate client trades."""
    from mcbe_editor import nbt

    require(isinstance(root.get("Variant"), nbt.IntTag) and root["Variant"].py_data == 1, "Saved natural trader is not a farmer")
    experience = root.get("TradeExperience")
    require(isinstance(experience, nbt.IntTag) and experience.py_data >= 0, "Malformed native trade experience")
    offers = root.get("Offers")
    recipes = offers.get("Recipes") if isinstance(offers, nbt.CompoundTag) else None
    require(isinstance(recipes, nbt.ListTag), "Natural farmer did not persist offers")
    bread = []
    for recipe in recipes:
        require(isinstance(recipe, nbt.CompoundTag), "Malformed native offer")
        buy, sell = recipe.get("buyA"), recipe.get("sell")
        if not isinstance(buy, nbt.CompoundTag) or not isinstance(sell, nbt.CompoundTag):
            continue
        if not all(isinstance(item.get("Name"), nbt.StringTag) for item in (buy, sell)):
            continue
        if buy["Name"].py_data != "minecraft:emerald" or sell["Name"].py_data != "minecraft:bread":
            continue
        uses = recipe.get("uses")
        require(isinstance(uses, nbt.IntTag) and uses.py_data >= 0, "Malformed native bread offer usage")
        per_trade_experience = recipe.get("traderExp")
        require(
            isinstance(per_trade_experience, nbt.IntTag) and per_trade_experience.py_data > 0,
            "Malformed native bread offer experience",
        )
        require(isinstance(sell.get("Count"), nbt.ByteTag) and sell["Count"].py_data > 0, "Malformed native bread output")
        require(isinstance(buy.get("Count"), nbt.ByteTag) and buy["Count"].py_data == 1, "Unexpected native bread recipe cost")
        bread.append({"uses": uses.py_data, "count": sell["Count"].py_data, "per_trade_experience": per_trade_experience.py_data})
    require(len(bread) == 1, "Natural farmer needs one unambiguous emerald-for-bread offer")
    return {"experience": experience.py_data, **bread[0]}


def verify_native_trade(current: dict, previous: dict | None, evidence: dict) -> None:
    trade = evidence["trade"]
    bread_delta = trade["after"]["bread"] - trade["before"]["bread"]
    require(bread_delta == current["count"], "Client must complete exactly one native bread trade per phase")
    old = previous or {**current, "uses": 0, "experience": 0}
    require(
        current["count"] == old["count"] and current["per_trade_experience"] == old["per_trade_experience"],
        "Native bread recipe output or experience changed",
    )
    # Vanilla restocking can reset uses between two client connections. The
    # cumulative experience must still increase by exactly this recipe's XP,
    # independently corroborating the observed one-recipe client exchange.
    require(
        current["experience"] - old["experience"] == current["per_trade_experience"] and 0 <= current["uses"] <= old["uses"] + 1,
        "No single saved native trade experience increase or invalid usage counter",
    )


def _cases(plan: dict) -> list[dict]:
    return [{"name": plan["names"][role]} for role in ROLES]


def _read(world: Path) -> dict:
    from .nbt_roundtrip import read_records

    return read_records(world)


def verify_saved(records: dict, plan: dict, evidence: dict, identities: dict | None = None) -> tuple[dict, dict]:
    from mcbe_editor import nbt

    found = find_actors(records, _cases(plan))
    actual_ids = {}
    for role in ROLES:
        key, root = found[plan["names"][role]]
        live = evidence["chunk_reload"]["actors"][role]
        require(
            health_snapshot(root) == {field: live[field] for field in ("current", "maximum")}, "Saved natural villager health differs from live observation"
        )
        items = inventory_snapshot(root)
        require(
            _carrots(items) == _carrots(live["items"]) if role == "farmer" else items == live["items"],
            "Saved natural supplies differ from the last live observation: " + role,
        )
        variant = root.get("Variant")
        require(variant is None or isinstance(variant, nbt.IntTag), "Malformed saved natural profession")
        profession = 0 if variant is None else variant.py_data
        require(0 <= profession <= 14, "Unknown saved natural profession")
        # Untraded controls can switch jobs between native observations. The
        # editor's byte-for-byte preservation check still forbids offline job edits.
        require(role != "farmer" or profession == live["variant"], "Saved natural farmer profession differs from the live observation")
        actual_ids[role] = {"key": key.hex(), "unique_id": str(root["UniqueID"].py_data), "identity": live["identity"]}
    require(identities is None or actual_ids == identities, "Original natural villagers disappeared or changed identity")
    farmer = found[plan["names"]["farmer"]][1]
    carrots = sum(item["count"] for item in inventory_snapshot(farmer) if item and item["name"] == "minecraft:carrot")
    require(carrots == evidence["pickup"]["farmer_after"], "Farmer's real food pickup was not saved")
    return actual_ids, trade_snapshot(farmer)


def _client(records: dict, evidence: dict, previous_key: str | None = None) -> str:
    from mcbe_editor.bedrock_nbt import load_player_nbt

    from .client_profile import find_client_player_key, player_items

    key = find_client_player_key(records)
    require(previous_key is None or key.hex() == previous_key, "Another client account joined the natural village")
    items = player_items(load_player_nbt(records[key]).tag, "Inventory")
    actual = {
        name: sum(item["Count"].py_data for item in items.values() if item["Name"].py_data == "minecraft:" + name) for name in ("emerald", "bread", "carrot")
    }
    require(actual == evidence["after"]["player"], "Real client's trade/drop inventory did not persist")
    return key.hex()


def _write(world: Path, plan: dict, role: str, changes: dict) -> None:
    from mcbe_editor import item_data, villager_service
    from mcbe_editor.backup import get_backups_dir
    from mcbe_editor.services import BedrockEditorService

    service = BedrockEditorService(item_data.ITEMS, item_data.ENCHANTMENTS)
    before = _read(world)
    scan = villager_service.scan(service, str(world))
    rows = [row for row in scan["villagers"] if row["name"] == plan["names"][role]]
    require(len(rows) == 1, "Production scan omitted the natural villager")
    selection = [{key: rows[0][key] for key in ("id", "revision")}]
    preview = villager_service.preview(service, str(world), scan["world_revision"], selection, changes)
    require(preview.summary == {"selected": 1, "changed": 1, "unchanged": 0, "skipped": 0}, "Production editor skipped the natural villager edit")
    require(_read(world) == before, "Natural villager preview mutated records")
    result = villager_service.save(
        service,
        str(world),
        world_revision=scan["world_revision"],
        selection=selection,
        changes=changes,
        expected_plan_digest=villager_service.plan_digest(preview),
        pre_write_check=lambda: None,
    )
    require(
        result.get("success") is True and result.get("write_committed") is True and result.get("validation", {}).get("ok") is True,
        "Natural villager save failed",
    )
    cases = _cases(plan)
    verify_write_preservation(before, _read(world), cases, [{"name": plan["names"][role]}], changes)
    backup = Path(get_backups_dir(str(world))) / result["backup_file"]
    require(backup.is_file(), "Natural villager edit omitted its backup")
    with zipfile.ZipFile(backup) as archive:
        require(archive.testzip() is None and any(name.endswith("level.dat") for name in archive.namelist()), "Malformed natural village backup")


def run(run_dir: Path, action: str) -> dict:
    from .runner import write_json

    require(action in {"edit", "verify"}, "Unknown natural village worker action")
    world, report, plan = _inputs(run_dir)
    state_path = run_dir / "village-state.json"
    binding = {key: report[key] for key in ("run_id", "village_plan_sha256", "catalog_sha256", "editor")}
    if action == "edit":
        require(not state_path.exists(), "Natural village edit may only run once")
        evidence = _evidence(run_dir, plan, "seed")
        records = _read(world)
        identities, trade = verify_saved(records, plan, evidence)
        verify_native_trade(trade, None, evidence)
        client_key = _client(records, evidence)
        _write(world, plan, "injured", {"max_health": 40, "heal": True})
        supply_items = [{"name": "minecraft:carrot", "count": 4}] + [None] * 7
        _write(world, plan, "farmer", {"inventory": [{"slot": slot, "item": item} for slot, item in enumerate(supply_items)]})
        expected = deepcopy(evidence["chunk_reload"]["actors"])
        expected["injured"].update(current=40, maximum=40)
        expected["farmer"]["items"] = supply_items
        written = find_actors(_read(world), _cases(plan))
        for role in ROLES:
            root = written[plan["names"][role]][1]
            require(health_snapshot(root) == {field: expected[role][field] for field in ("current", "maximum")}, "Offline health result differs from plan")
        require(inventory_snapshot(written[plan["names"]["farmer"]][1]) == supply_items, "Offline supplies differ from plan")
        state = {
            "format": "mcbe-natural-village-state-v1",
            **binding,
            "checkpoint": "edit",
            "identities": identities,
            "client_key": client_key,
            "trade": trade,
            "expected": expected,
            "backed_up_saves": 2,
            "verified_reloads": 0,
        }
        write_json(state_path, state)
        return {"status": "pass", "backed_up_saves": 2, "expected": expected, "native_trades": 1}
    require(state_path.is_file() and not state_path.is_symlink() and not state_path.is_junction(), "Missing natural village baseline")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    require(
        state.get("format") == "mcbe-natural-village-state-v1" and all(state.get(key) == value for key, value in binding.items()),
        "Natural village baseline belongs to different inputs",
    )
    previous = state.get("checkpoint")
    require(previous in {"edit", "reload1"}, "Natural village verification repeated or out of order")
    phase = "reload1" if previous == "edit" else "reload2"
    require(report.get("phases", {}).get(phase) == "pass", "Completed natural village reload is required")
    evidence = _evidence(run_dir, plan, phase)
    records = _read(world)
    identities, trade = verify_saved(records, plan, evidence, state["identities"])
    verify_native_trade(trade, state["trade"], evidence)
    _client(records, evidence, state["client_key"])
    for role in ROLES:
        actual, expected = evidence["before"]["actors"][role], state["expected"][role]
        require(same_persisted_actor(actual, expected, role), "Persisted natural resident state changed before gameplay: " + role)
    state.update(checkpoint=phase, trade=trade, expected=evidence["chunk_reload"]["actors"], verified_reloads=state["verified_reloads"] + 1)
    write_json(state_path, state)
    return {"status": "pass", "expected": state["expected"], "verified_reloads": state["verified_reloads"], "native_trades": 1}


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: python -m scripts.engine_checks.village_worker RUN_DIR edit|verify")
    from .nbt_roundtrip import configure_worker_catalog

    directory = Path(sys.argv[1])
    _inputs(directory)
    configure_worker_catalog(directory)
    print(json.dumps(run(directory, sys.argv[2]), sort_keys=True))
