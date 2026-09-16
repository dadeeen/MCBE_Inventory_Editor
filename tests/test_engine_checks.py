from __future__ import annotations

import hashlib
import io
import json
import stat
import zipfile
from copy import deepcopy

import pytest

from scripts.engine_checks.cases import CARRIER_PREFIX, CONTROL_NAME, expected_snapshot, make_cases, validate_case_events
from scripts.engine_checks.nbt_roundtrip import build_item_writes, verify_saved_items
from scripts.engine_checks.protocol import PREFIX, ProbeError, Transcript, catalog_result
from scripts.engine_checks.runner import container_arguments, extract_server


def wire(kind, seq, **extra):
    return "[INFO] " + PREFIX + json.dumps({"run_id": "test-run", "phase": "catalog", "seq": seq, "kind": kind, **extra})


def transcript():
    result = Transcript("test-run", "catalog", "1.26.50.5")
    result.feed("[INFO] Version: 1.26.50.5")
    result.feed(wire("begin", 0))
    return result


def catalog_events():
    return [
        {"kind": "registry", "ids": ["minecraft:stone", "minecraft:future_item"]},
        {"kind": "item", "id": "minecraft:stone", "max_amount": 64, "components": [], "max_durability": None},
        {"kind": "error", "id": "minecraft:future_item", "message": "Unavailable in this profile"},
    ]


def test_transcript_requires_exact_version_and_complete_counts():
    probe = transcript()
    with pytest.raises(ProbeError, match="complete"):
        probe.finish()
    probe.feed(wire("item", 1, id="minecraft:stone"))
    probe.feed(wire("done", 2, items=1, cases=0, errors=0))
    assert len(probe.finish()) == 3
    with pytest.raises(ProbeError, match="trailing"):
        probe.feed(wire("done", 3))
    with pytest.raises(ProbeError, match="version mismatch"):
        transcript().feed("Version: 1.26.51.1")


@pytest.mark.parametrize("line", [
    wire("item", 2), wire("begin", 1), wire("surprise", 1), wire("item", 1, run_id="stale-run"),
    wire("item", 1, phase="reload1"), "[INFO] " + PREFIX + "{broken", wire("item", True),
])
def test_transcript_rejects_missing_stale_duplicate_and_malformed_events(line):
    with pytest.raises(ProbeError):
        transcript().feed(line)


def test_transcript_rejects_truncated_event_counts_and_missing_version():
    probe = transcript()
    probe.feed(wire("done", 1, items=1, cases=0, errors=0))
    with pytest.raises(ProbeError, match="count"):
        probe.finish()
    probe = Transcript("test-run", "catalog", "1.26.50.5")
    probe.feed(wire("begin", 0))
    probe.feed(wire("done", 1, items=0, cases=0, errors=0))
    with pytest.raises(ProbeError):
        probe.finish()


def test_unavailable_engine_items_are_partial_never_implicit_one_or_64():
    report = catalog_result(catalog_events(), ["minecraft:stone", "minecraft:future_item"], {"minecraft:stone": 64})
    assert report["status"] == "partial"
    assert report["missing"] == ["minecraft:future_item"]
    assert "minecraft:future_item" not in report["new_limit_candidates"]


def test_registry_additions_require_review_even_when_old_items_pass():
    events = catalog_events()
    events[2] = {"kind": "item", "id": "minecraft:future_item", "max_amount": 16, "components": [], "max_durability": None}
    report = catalog_result(events, ["minecraft:stone"], {"minecraft:stone": 64})
    assert report["status"] == "partial"
    assert report["registry_extra"] == ["minecraft:future_item"]
    assert report["new_limit_candidates"] == {"minecraft:future_item": 16}


def test_catalog_boolean_cannot_pass_as_a_matching_amount_one():
    events = [
        {"kind": "registry", "ids": ["minecraft:bow"]},
        {"kind": "item", "id": "minecraft:bow", "max_amount": 1, "components": [], "max_durability": 384},
    ]
    with pytest.raises(ProbeError, match="recorded catalog"):
        catalog_result(events, ["minecraft:bow"], {"minecraft:bow": True})


@pytest.mark.parametrize("limit", [True, "64", 0, -1, 1.5, 256, None])
def test_invalid_engine_measurements_fail_instead_of_becoming_defaults(limit):
    events = catalog_events()
    events[1]["max_amount"] = limit
    with pytest.raises(ProbeError, match="stack limit"):
        catalog_result(events, ["minecraft:stone"], {})


def test_engine_catalog_mismatch_and_unsupported_range_are_failures():
    report = catalog_result(catalog_events(), ["minecraft:stone"], {"minecraft:stone": 16})
    assert report["status"] == "fail"
    assert report["mismatches"]["minecraft:stone"] == {"catalog": 16, "engine": 64}
    events = catalog_events()
    events[1]["max_amount"] = 128
    report = catalog_result(events, ["minecraft:stone"], {})
    assert report["status"] == "fail"
    assert report["outside_editor_count_range"] == ["minecraft:stone"]


@pytest.mark.parametrize("mutation", ["omit", "duplicate", "unknown", "registry"])
def test_catalog_cannot_pass_with_missing_or_duplicate_observations(mutation):
    events = catalog_events()
    if mutation == "omit":
        events.pop()
    elif mutation == "duplicate":
        events.append(events[1])
    elif mutation == "unknown":
        events[1]["id"] = "minecraft:unrequested"
    else:
        events[0]["ids"].append("minecraft:stone")
    with pytest.raises(ProbeError):
        catalog_result(events, ["minecraft:stone"], {})


def test_cases_cover_every_item_preservation_and_known_boundaries():
    observations = {"minecraft:stone": {"max_amount": 64}, "minecraft:red_cushion": {"max_amount": 64}}
    cases = make_cases(list(observations), observations, {"minecraft:stone": 64})
    stone = [(case["mode"], case["amount"]) for case in cases if case["id"] == "minecraft:stone"]
    unknown = [(case["mode"], case["amount"]) for case in cases if case["id"] == "minecraft:red_cushion"]
    assert ("create", 64) in stone and ("create", 63) in stone and ("preserve", 64) in stone
    assert unknown == [("create", 1), ("preserve", 64)]
    assert all(case["slot"] != 26 for case in cases)


@pytest.mark.parametrize("mutation", ["missing", "clamp", "lost-name", "duplicate"])
def test_roundtrip_checks_detect_silent_engine_changes(mutation):
    cases = make_cases(["minecraft:stone"], {"minecraft:stone": {"max_amount": 64}}, {"minecraft:stone": 64})
    events = [{"kind": "case", "case_id": case["case_id"], "snapshot": expected_snapshot(case)} for case in cases]
    validate_case_events(events, cases)
    if mutation == "missing":
        events.pop()
    elif mutation == "clamp":
        events[1]["snapshot"]["amount"] = 1
    elif mutation == "lost-name":
        events[-1]["snapshot"]["name"] = ""
    else:
        events.append(events[0])
    with pytest.raises(ProbeError):
        validate_case_events(events, cases)


def server_zip(tmp_path, extra=()):
    path = tmp_path / "server.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("bedrock_server", b"\x7fELFsynthetic-test-only")
        for name, content in extra:
            archive.writestr(name, content)
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("name", ["../escape", "/absolute", "C:/escape", "a\\..\\escape", "worlds/real/db/CURRENT", "bad. /file"])
def test_archive_extraction_rejects_paths_and_preexisting_worlds(tmp_path, name):
    path, digest = server_zip(tmp_path, [(name, b"bad")])
    destination = tmp_path / "extract"
    with pytest.raises(ProbeError):
        extract_server(path, destination, digest)
    assert not destination.exists()


def test_archive_extraction_verifies_hash_symlinks_and_case_collisions(tmp_path):
    path, digest = server_zip(tmp_path)
    with pytest.raises(ProbeError, match="SHA-256"):
        extract_server(path, tmp_path / "hash", "f" * 64)
    link = zipfile.ZipInfo("link")
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(path, "a") as archive:
        archive.writestr(link, "target")
    with pytest.raises(ProbeError, match="Unsafe"):
        extract_server(path, tmp_path / "link", hashlib.sha256(path.read_bytes()).hexdigest())
    path, digest = server_zip(tmp_path, [("BEDROCK_SERVER", b"collision")])
    with pytest.raises(ProbeError, match="Duplicate"):
        extract_server(path, tmp_path / "case", digest)


def test_server_extraction_and_container_configuration(tmp_path):
    path, digest = server_zip(tmp_path, [("config/default/permissions.json", b"{}")])
    destination = tmp_path / "server"
    extract_server(path, destination, digest)
    args = container_arguments(destination, "owned", "sha256:" + "a" * 64)
    assert args[args.index("--network") + 1] == "none"
    assert "--privileged" not in args and "--publish" not in args and "-p" not in args
    assert args[args.index("--cap-drop") + 1] == "ALL"
    with pytest.raises(ProbeError, match="new directory"):
        extract_server(path, destination, digest)


def synthetic_carriers(cases):
    from mcbe_editor import nbt
    from mcbe_editor.bedrock_nbt import save_player_nbt

    grouped = {}
    for case in cases:
        grouped.setdefault(case["carrier"], []).append(case)
    records = {b"unrelated": b"leave untouched"}
    for index, (name, entries) in enumerate(grouped.items()):
        items = [nbt.CompoundTag({
            "Slot": nbt.ByteTag(26), "Name": nbt.StringTag("minecraft:stone"), "Count": nbt.ByteTag(1), "Damage": nbt.ShortTag(0),
            "tag": nbt.CompoundTag({"display": nbt.CompoundTag({"Name": nbt.StringTag(CONTROL_NAME)})}),
        })]
        for case in entries:
            if case["mode"] == "create":
                continue
            items.append(nbt.CompoundTag({
                "Slot": nbt.ByteTag(case["slot"]), "Name": nbt.StringTag(case["id"]), "Count": nbt.ByteTag(case["amount"]), "Damage": nbt.ShortTag(0),
                "tag": nbt.CompoundTag({"future_probe": nbt.LongTag(2**50)}),
            }))
        actor = nbt.NamedTag(nbt.CompoundTag({
            "identifier": nbt.StringTag("minecraft:chest_minecart"), "CustomName": nbt.StringTag(name),
            "ChestItems": nbt.ListTag(items), "Untouched": nbt.LongArrayTag([2**50, -1]),
        }))
        records[b"actorprefix" + index.to_bytes(8, "big")] = save_player_nbt(actor)
    return records


def test_actual_nbt_builder_preserves_controls_and_unknown_existing_items(monkeypatch):
    from mcbe_editor.bedrock_nbt import load_player_nbt
    from mcbe_editor import item_data

    monkeypatch.delitem(item_data.STACK_LIMITS, "minecraft:red_cushion", raising=False)
    observations = {"minecraft:stone": {"max_amount": 64}, "minecraft:red_cushion": {"max_amount": 64}}
    cases = make_cases(list(observations), observations, {"minecraft:stone": 64})
    before = synthetic_carriers(cases)
    writes = build_item_writes(before, cases)
    assert b"unrelated" not in writes
    assert verify_saved_items({**before, **writes}, cases)["cases"] == len(cases)
    for key, raw in writes.items():
        assert load_player_nbt(raw).tag["Untouched"].save_to() == load_player_nbt(before[key]).tag["Untouched"].save_to()


def test_saved_nbt_verification_rejects_clamping():
    from mcbe_editor import nbt
    from mcbe_editor.bedrock_nbt import load_player_nbt, save_player_nbt

    cases = make_cases(["minecraft:stone"], {"minecraft:stone": {"max_amount": 64}}, {"minecraft:stone": 64})
    records = synthetic_carriers(cases)
    records.update(build_item_writes(records, cases))
    key = next(key for key in records if key.startswith(b"actorprefix"))
    actor = load_player_nbt(records[key])
    target = next(item for item in actor.tag["ChestItems"] if item["Count"].py_data == 64)
    target["Count"] = nbt.ByteTag(1)
    records[key] = save_player_nbt(actor)
    with pytest.raises(ProbeError, match="amount"):
        verify_saved_items(records, cases)


def test_native_offline_worker_writes_only_generated_carriers(tmp_path, monkeypatch):
    import mcbe_editor.db as db_module
    from mcbe_editor.db import LevelDbAdapter
    from scripts.engine_checks.nbt_roundtrip import read_records, run
    from scripts.engine_checks.runner import WORLD_NAME, sha256, write_json

    monkeypatch.setenv("MCBE_BACKUP_ROOT", str(tmp_path / "backups"))
    # pytest's app fixture registers a web-request guard; this standalone worker
    # normally runs in a fresh process which never imports the web application.
    monkeypatch.setattr(db_module, "_runtime_app_modules", lambda: ())
    monkeypatch.setattr(db_module, "_registered_write_guard", None)
    world = tmp_path / "server" / "worlds" / WORLD_NAME
    (world / "db").mkdir(parents=True)
    (world / "levelname.txt").write_text("Synthetic nonplayable fixture", encoding="utf-8")
    cases = make_cases(["minecraft:stone"], {"minecraft:stone": {"max_amount": 64}}, {"minecraft:stone": 64})
    write_json(tmp_path / "cases.json", cases)
    write_json(tmp_path / "run.json", {"format": "mcbe-engine-check-v1", "phases": {"seed": "pass"}, "cases_sha256": sha256(tmp_path / "cases.json")})
    records = synthetic_carriers(cases)
    db = LevelDbAdapter(str(world / "db"))
    try:
        db.put_batch(records)
    finally:
        db.close()
    report = run(tmp_path, "edit")
    assert report["backup_created"] is True and report["changed_records"] > 0
    assert read_records(world)[b"unrelated"] == records[b"unrelated"]
    assert run(tmp_path, "verify")["status"] == "pass"


def test_runtime_release_excludes_engine_tools_and_generated_data():
    from pathlib import PurePosixPath

    from scripts.release_rules import is_blocked_release_dir_name
    from scripts.runtime_layout import is_runtime_relative_path

    assert is_blocked_release_dir_name(".engine-tests")
    assert not is_runtime_relative_path(PurePosixPath("scripts/engine_checks/runner.py"))


def test_public_summary_drops_raw_world_data_logs_and_failure_paths():
    from scripts.engine_checks.runner import public_summary

    report = {
        "status": "fail", "suite": "items", "engine": {"version": "1.26.50.5"}, "editor": {"commit": "abc"},
        "catalog_sha256": "a" * 64, "phases": {}, "not_covered": [],
        "failure": "PRIVATE_PATH", "world_nbt": "PRIVATE_NBT",
        "catalog": {"status": "fail", "errors": {"minecraft:stone": "PRIVATE_LOG"}, "observations": {"private": "PRIVATE_OBSERVATION"}},
    }
    summary = json.dumps(public_summary(report))
    assert "PRIVATE_" not in summary
    assert '"status": "fail"' in summary


@pytest.mark.parametrize("engine_exit", [0, 1])
def test_phase_owns_and_removes_container_and_requires_clean_exit(tmp_path, monkeypatch, engine_exit):
    from scripts.engine_checks import runner

    calls = []
    output = "Version: 1.26.50.5\n" + wire("begin", 0) + "\n" + wire("done", 1, items=0, cases=0, errors=0) + "\n"

    class Process:
        stdin = io.StringIO()
        stdout = io.StringIO(output)

        def wait(self, **_kwargs):
            return 0

        def poll(self):
            return 0

    def docker(args, **_kwargs):
        calls.append(deepcopy(args))
        return "b" * 64 if args[0] == "create" else json.dumps({"Running": False, "ExitCode": engine_exit, "OOMKilled": False})

    monkeypatch.setattr(runner, "docker_command", docker)
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *_args, **_kwargs: Process())
    if engine_exit:
        with pytest.raises(ProbeError, match="stop cleanly"):
            runner.run_phase(tmp_path, tmp_path, "catalog", "test-run", "1.26.50.5", "sha256:" + "a" * 64, 10)
    else:
        events = runner.run_phase(tmp_path, tmp_path, "catalog", "test-run", "1.26.50.5", "sha256:" + "a" * 64, 10)
        assert events[-1]["kind"] == "done"
    assert calls[-1] == ["rm", "--force", "b" * 64]


def test_carrier_names_are_synthetic_and_stable():
    cases = make_cases(["minecraft:stone"], {"minecraft:stone": {"max_amount": 64}}, {})
    assert all(case["carrier"].startswith(CARRIER_PREFIX) for case in cases)


def test_standalone_worker_uses_measured_candidate_instead_of_old_bundled_curation(tmp_path):
    import os
    import subprocess
    import sys

    from scripts.engine_checks.runner import ROOT, sha256, write_json

    catalog = json.loads((ROOT / "mcbe_editor/resources/item_db.json").read_text(encoding="utf-8"))
    # A deliberate difference ensures this remains sensitive to accidental
    # fallback to the real bundled file after its next catalog update too.
    candidate_limit = 16 if catalog["stack_limits"]["minecraft:stone"] == 64 else 64
    catalog["stack_limits"]["minecraft:stone"] = candidate_limit
    write_json(tmp_path / "catalog.json", catalog)
    write_json(tmp_path / "run.json", {"catalog_sha256": sha256(tmp_path / "catalog.json")})
    source = """
import sys
from pathlib import Path
from scripts.engine_checks.nbt_roundtrip import configure_worker_catalog
configure_worker_catalog(Path(sys.argv[1]))
from mcbe_editor import item_data
assert item_data.get_max_stack('minecraft:stone') == int(sys.argv[2])
"""
    result = subprocess.run([sys.executable, "-c", source, str(tmp_path), str(candidate_limit)], cwd=ROOT,
                            env={**os.environ, "MCBE_ITEM_DB_PATH": str(tmp_path / "catalog.json")},
                            capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 0, result.stderr
