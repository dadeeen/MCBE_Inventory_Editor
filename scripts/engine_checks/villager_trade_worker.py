"""Production career writes and independent persisted native-trade observations."""

from __future__ import annotations

import hashlib
import json
import re
import sys
import zipfile
from contextlib import contextmanager
from pathlib import Path

from .protocol import ProbeError
from .villager_trade_profile import validate_trade_plan
from .villager_worker import actor_baseline, find_actors, health_snapshot, inventory_snapshot, require

STATE_FORMAT = "mcbe-villager-trades-v1"
OWNED_FIELDS = {"Variant", "PreferredProfession", "TradeTablePath", "TradeTier", "TradeExperience", "Offers", "definitions"}
ORDER = ("seed", "warmup1", "warmup2", "edit", "reload1", "reload2", "revise", "reload3", "reload4")


def _hash(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read(world: Path) -> dict:
    from .nbt_roundtrip import read_records

    return read_records(world)


def _identity(key, root) -> dict:
    result = actor_baseline(key, root)
    for field in ("Variant", "TradeTier", "TradeExperience", "Offers"):
        result["stable"].pop(field)
    result["stable"].update({field: _hash(root[field].save_to()) if field in root else None for field in ("CustomName", "ChestItems")})
    return result


def _career(
    root,
    expected: dict,
    tables: dict,
    *,
    pending: bool = False,
    enchantment_limits: dict | None = None,
    enchantment_compatibility: dict | None = None,
    require_binding: bool = False,
) -> dict:
    from mcbe_editor import nbt

    from .villager_trade_tables import validate_offers

    profession = expected["profession"]
    variant = 0 if profession == "unemployed" else tables[profession]["variant"]
    for field, value in (("Variant", variant), ("TradeTier", expected["tier"]), ("TradeExperience", expected["experience"])):
        # BDS omits the default Variant for unskilled villagers after reload.
        stored = root.get(field, nbt.IntTag(0) if field == "Variant" and profession == "unemployed" else None)
        require(isinstance(stored, nbt.IntTag) and stored.py_data == value, "Wrong native trade state: " + field)
    preferred = root.get("PreferredProfession")
    require(preferred is None or isinstance(preferred, nbt.StringTag), "Invalid native PreferredProfession")
    if expected["experience"] > 0 and require_binding:
        require(preferred is not None and preferred.py_data == profession, "Experienced profession lost its preferred binding")
    elif preferred is not None:
        require(preferred.py_data in {"", profession}, "Wrong native preferred profession")
    table = root.get("TradeTablePath")
    path = "" if profession == "unemployed" else tables[profession]["path"]
    require((table is None and not path) or (isinstance(table, nbt.StringTag) and table.py_data == path), "Wrong native trade table")
    if pending:
        require("Offers" not in root, "Profession writer retained previous offers")
        return {"offers_sha256": None, "critical_signature": None, "recipes": 0, "limitations": []}
    offers = root.get("Offers")
    if profession == "unemployed":
        require(
            offers is None or (isinstance(offers, nbt.CompoundTag) and isinstance(offers.get("Recipes"), nbt.ListTag) and len(offers["Recipes"]) == 0),
            "Unemployed villager retained trade offers",
        )
        return {"offers_sha256": None if offers is None else _hash(offers.save_to()), "critical_signature": None, "recipes": 0, "limitations": []}
    result = validate_offers(root, profession, tables, enchantment_limits=enchantment_limits, enchantment_compatibility=enchantment_compatibility)
    require(result.get("status") == "pass" and result.get("critical_signature") is not None, "Native trade oracle omitted its article evidence")
    return {**result, "offers_sha256": _hash(root["Offers"].save_to())}


def verify_records(
    records: dict,
    cases: list[dict],
    tables: dict,
    stage: str,
    *,
    previous: dict | None = None,
    pending: set[str] | None = None,
    regenerated: set[str] | None = None,
    initialize: bool = False,
    enchantment_limits: dict | None = None,
    enchantment_compatibility: dict | None = None,
    require_binding: bool = True,
) -> dict:
    """Accept a new randomized offer baseline only after independent validation."""
    validate_trade_plan(cases)
    require(stage in {"seed", "edited", "revised"}, "Unknown native trade stage")
    found = find_actors(records, cases, tagged=True)
    pending, regenerated = pending or set(), regenerated or set()
    require(previous is None or set(previous) == set(found), "Missing native trade baselines")
    result = {}
    for case in cases:
        name, expected = case["name"], case[stage]
        key, root = found[name]
        require(health_snapshot(root) == {"current": expected["current"], "maximum": expected["maximum"]}, "Trade edit changed native health")
        require(inventory_snapshot(root) == expected["items"], "Trade edit changed native supplies")
        identity = _identity(key, root)
        try:
            career = _career(
                root,
                expected,
                tables,
                pending=name in pending,
                enchantment_limits=enchantment_limits,
                enchantment_compatibility=enchantment_compatibility,
                require_binding=require_binding,
            )
        except (ProbeError, RuntimeError) as exc:
            raise ProbeError(f"{name}: {exc}") from exc
        if previous is not None:
            require(identity == previous[name]["identity"], "Trade edit/reload changed unrelated villager identity or data")
            if name not in pending and not initialize:
                before = previous[name]["career"]
                if name in regenerated:
                    if before["critical_signature"] is not None:
                        require(career["critical_signature"] == before["critical_signature"], "Regenerated trade articles rerolled on another reload")
                else:
                    require(career["offers_sha256"] == before["offers_sha256"], "Tier edit or engine changed preserved trade offers")
        result[name] = {"identity": identity, "career": career}
    return result


def verify_write(before: dict, after: dict, cases: list[dict], chosen: dict, *, switched: bool) -> None:
    original = find_actors(before, cases, tagged=True)
    updated = find_actors(after, cases, tagged=True)
    name = chosen["name"]
    key, old = original[name]
    new_key, new = updated[name]
    require(key == new_key and set(before) == set(after), "Career writer changed actor identity or database keys")
    require(all(value == after[k] for k, value in before.items() if k != key), "Career writer changed an unrelated database record")
    fields = OWNED_FIELDS if switched else {"TradeTier", "TradeExperience"}
    require(set(old) - fields == set(new) - fields, "Career writer changed unrelated actor field names")
    require(all(old[k].save_to() == new[k].save_to() for k in old if k not in fields), "Career writer changed unrelated actor fields")
    require(before[key] != after[key], "Career case did not actually change its actor")
    if switched:
        require("Offers" not in new, "Profession change retained old trade articles")


@contextmanager
def vanilla_offline_window(world: Path, run_dir: Path):
    """Deregister only this runner's verified script-only instrumentation.

    The runner has already stopped its disposable BDS container. No product
    guard is patched: production scan/preview/save see an actual Vanilla pack
    registration. The exact registration is restored even when a write fails.
    """
    from .runner import API_VERSION, PACK, PACK_ID, SCRIPT_ID, WORLD_NAME

    require(world == run_dir / "server" / "worlds" / WORLD_NAME, "Trade window requires its own disposable world")
    registry = world / "world_behavior_packs.json"
    require(registry.is_file() and not registry.is_symlink() and not registry.is_junction(), "Missing regular probe pack registration")
    raw = registry.read_bytes()
    require(json.loads(raw) == [{"pack_id": PACK_ID, "version": [1, 0, 0]}], "Trade window refuses unknown or additional behavior packs")
    pack = run_dir / "server" / "behavior_packs" / "mcbe_engine_probe"
    require(
        all(not path.is_symlink() and not path.is_junction() for path in (pack, *pack.parents) if path.is_relative_to(run_dir)), "Probe pack may not be linked"
    )
    sources = {"scripts/" + path.name: path.read_bytes() for path in (PACK / "scripts").glob("*.js")}
    files = {path.relative_to(pack).as_posix(): path for path in pack.rglob("*") if path.is_file()}
    require(set(files) == {"manifest.json", "scripts/config.js", *sources}, "Probe pack contains unknown files or Vanilla overrides")
    require(all(not path.is_symlink() and not path.is_junction() for path in pack.rglob("*")), "Probe pack contains linked files")
    require(all(files[name].read_bytes() == content for name, content in sources.items()), "Probe scripts differ from the audited source")
    manifest = json.loads(files["manifest.json"].read_bytes())
    require(manifest.get("header", {}).get("uuid") == PACK_ID, "Probe pack has another identity")
    require(
        manifest.get("modules") == [{"type": "script", "language": "javascript", "uuid": SCRIPT_ID, "version": [1, 0, 0], "entry": "scripts/main.js"}],
        "Probe pack must contain only the owned script module",
    )
    require(manifest.get("dependencies") == [{"module_name": "@minecraft/server", "version": API_VERSION}], "Unknown probe dependency")
    config_text = files["scripts/config.js"].read_text(encoding="utf-8")
    require(config_text.startswith("export const config = ") and config_text.endswith(";\n"), "Unknown probe configuration")
    config = json.loads(config_text[len("export const config = ") : -2])
    report = json.loads((run_dir / "run.json").read_bytes())
    require(config.get("run_id") == report.get("run_id") and config.get("villager_trade_profile") is True, "Probe belongs to another run/profile")
    validate_trade_plan(config.get("cases"))
    registry.write_bytes(b"[]\n")
    try:
        yield
    finally:
        registry.write_bytes(raw)
        require(registry.read_bytes() == raw, "Failed to restore the probe pack registration")


def _inputs(run_dir: Path):
    from .runner import WORLD_NAME, sha256, source_hashes
    from .villager_trade_tables import load_run_trade_tables

    require(not run_dir.is_symlink() and not run_dir.is_junction(), "Trade run may not be linked")
    run_dir = run_dir.resolve(strict=True)
    report = json.loads((run_dir / "run.json").read_bytes())
    require(report.get("format") == "mcbe-engine-check-v1" and report.get("suite") == "villager_trades", "Worker requires its native trade run")
    require(isinstance(report.get("run_id"), str) and bool(re.fullmatch(r"[a-f0-9]{32}", report["run_id"])), "Missing native trade run identity")
    require(report.get("phases", {}).get("seed") == "pass", "Completed live trade seeding is required")
    require(all(report.get("editor", {}).get(key) == value for key, value in source_hashes().items()), "Trade probe/editor sources changed")
    require(sha256(run_dir / "cases.json") == report.get("cases_sha256"), "Native trade cases changed")
    require(sha256(run_dir / "catalog.json") == report.get("catalog_sha256"), "Native trade catalog changed")
    cases = json.loads((run_dir / "cases.json").read_bytes())
    validate_trade_plan(cases)
    world = run_dir / "server" / "worlds" / WORLD_NAME
    for path in (run_dir / "server", run_dir / "server/worlds", world, world / "db"):
        require(path.resolve(strict=True).is_relative_to(run_dir) and not path.is_symlink() and not path.is_junction(), "Native trade world escaped its run")
    tables = load_run_trade_tables(run_dir, report)
    require(_hash(json.dumps(tables, sort_keys=True).encode()) == report.get("trade_tables_sha256"), "Native Vanilla trade tables changed")
    require(sha256(run_dir / "trade-enchantments.json") == report.get("trade_enchantments_sha256"), "Native enchantment observation changed")
    enchantments = json.loads((run_dir / "trade-enchantments.json").read_bytes())
    require(isinstance(enchantments, dict) and set(enchantments) == {"limits", "compatibility"}, "Malformed native enchantment evidence")
    return run_dir, world, report, cases, tables, enchantments["limits"], enchantments["compatibility"]


def _exercise_service(
    world: Path, run_dir: Path, cases: list[dict], tables: dict, state: dict, action: str, enchantment_limits: dict, enchantment_compatibility: dict
) -> dict:
    from mcbe_editor import item_data, villager_service
    from mcbe_editor.backup import get_backups_dir
    from mcbe_editor.services import BedrockEditorService

    service = BedrockEditorService(item_data.ITEMS, item_data.ENCHANTMENTS)
    stage, before_stage = ("edited", "seed") if action == "edit" else ("revised", "edited")
    counts = {"backed_up_saves": 0, "no_op_checks": 0, "stale_revision_rejections": 0}
    pending = set()

    def prepare(case):
        scan = villager_service.scan(service, str(world))
        identity = state["actors"][case["name"]]["identity"]["unique_id"]
        matches = [row for row in scan["villagers"] if row["unique_id"] == identity]
        require(len(matches) == 1, "Production scan omitted native trade actor")
        selection = [{key: matches[0][key] for key in ("id", "revision")}]
        plan = villager_service.preview(service, str(world), scan["world_revision"], selection, case[action])
        return plan, {
            "world_revision": scan["world_revision"],
            "selection": selection,
            "changes": case[action],
            "expected_plan_digest": villager_service.plan_digest(plan),
        }

    with vanilla_offline_window(world, run_dir):
        for case in cases:
            if case[action] is None:
                continue
            switched = case[before_stage]["profession"] != case[stage]["profession"]
            before = _read(world)
            plan, arguments = prepare(case)
            require(
                _read(world) == before and plan.summary == {"selected": 1, "changed": 1, "unchanged": 0, "skipped": 0},
                "Career preview skipped or mutated a case",
            )
            result = villager_service.save(service, str(world), **arguments, pre_write_check=lambda: None)
            require(
                result.get("success") is True and result.get("write_committed") is True and result.get("validation", {}).get("ok") is True,
                "Career service did not verify a committed write",
            )
            after = _read(world)
            verify_write(before, after, cases, case, switched=switched)
            root = find_actors(after, cases, tagged=True)[case["name"]][1]
            _career(root, case[stage], tables, pending=switched, enchantment_limits=enchantment_limits, enchantment_compatibility=enchantment_compatibility)
            if switched:
                pending.add(case["name"])
            backups = Path(get_backups_dir(str(world)))
            with zipfile.ZipFile(backups / result["backup_file"]) as archive:
                require(archive.testzip() is None and any(name.endswith("level.dat") for name in archive.namelist()), "Career write omitted valid backup")
            counts["backed_up_saves"] += 1
            backup_names = set(backups.iterdir())
            try:
                villager_service.save(service, str(world), **arguments, pre_write_check=lambda: None)
            except villager_service.VillagerSnapshotStaleError:
                counts["stale_revision_rejections"] += 1
            else:
                raise RuntimeError("Career service accepted a stale native snapshot")
            noop, arguments = prepare(case)
            require(not noop.writes and noop.summary["unchanged"] == 1, "Same native career state was not a no-op")
            repeated = villager_service.save(service, str(world), **arguments, pre_write_check=lambda: None)
            require(repeated.get("success") and repeated.get("write_committed") is False, "Career no-op committed another write")
            require(_read(world) == after and set(backups.iterdir()) == backup_names, "Rejected/no-op career write changed world or backups")
            counts["no_op_checks"] += 1
        actors = verify_records(
            _read(world),
            cases,
            tables,
            stage,
            previous=state["actors"],
            pending=pending,
            enchantment_limits=enchantment_limits,
            enchantment_compatibility=enchantment_compatibility,
            require_binding=False,
        )
    return {"status": "pass", "cases": len(cases), "stage": stage, "actors": actors, "regenerated": sorted(pending), **counts}


def run(run_dir: Path, action: str) -> dict:
    from .runner import write_json

    require(action in ORDER, "Unknown native trade action")
    run_dir, world, report, cases, tables, enchantment_limits, enchantment_compatibility = _inputs(run_dir)
    state_path = run_dir / "villager-trades-state.json"
    binding = {key: report[key] for key in ("run_id", "cases_sha256", "catalog_sha256", "trade_tables_sha256", "trade_enchantments_sha256", "editor")}
    if action == "seed":
        require(not state_path.exists(), "Native trade baseline can only be seeded once")
        actors = verify_records(_read(world), cases, tables, "seed", enchantment_limits=enchantment_limits, enchantment_compatibility=enchantment_compatibility)
        state = {"format": STATE_FORMAT, **binding, "checkpoint": action, "stage": "seed", "actors": actors, "regenerated": []}
    else:
        require(state_path.is_file() and not state_path.is_symlink() and not state_path.is_junction(), "Missing native trade baseline")
        state = json.loads(state_path.read_bytes())
        require(state.get("format") == STATE_FORMAT and all(state.get(key) == value for key, value in binding.items()), "Native trade baseline inputs differ")
        require(state.get("checkpoint") == ORDER[ORDER.index(action) - 1], "Native trade phase repeated or out of order")
        if action in {"edit", "revise"}:
            required_phase = "warmup2" if action == "edit" else "reload2"
            require(report.get("phases", {}).get(required_phase) == "pass", "Native career write lacks verified prior engine phases")
            verify_records(
                _read(world),
                cases,
                tables,
                state["stage"],
                previous=state["actors"],
                enchantment_limits=enchantment_limits,
                enchantment_compatibility=enchantment_compatibility,
            )
            result = _exercise_service(world, run_dir, cases, tables, state, action, enchantment_limits, enchantment_compatibility)
            state.update(stage=result["stage"], actors=result.pop("actors"), regenerated=result.pop("regenerated"), checkpoint=action)
            write_json(state_path, state)
            return result
        state["actors"] = verify_records(
            _read(world),
            cases,
            tables,
            state["stage"],
            previous=state["actors"],
            regenerated=set(state["regenerated"]),
            initialize=action == "warmup1",
            enchantment_limits=enchantment_limits,
            enchantment_compatibility=enchantment_compatibility,
        )
        state["checkpoint"] = action
    write_json(state_path, state)
    limitations = sorted({limitation for actor in state["actors"].values() for limitation in actor["career"].get("limitations", [])})
    return {"status": "pass", "cases": len(cases), "stage": state["stage"], "limitations": limitations}


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: python -m scripts.engine_checks.villager_trade_worker RUN_DIR ACTION")
    from .nbt_roundtrip import configure_worker_catalog

    directory = Path(sys.argv[1])
    _inputs(directory)
    configure_worker_catalog(directory)
    print(json.dumps(run(directory, sys.argv[2]), sort_keys=True))
