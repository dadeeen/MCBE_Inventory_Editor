from __future__ import annotations

import json
from copy import deepcopy

import pytest

from scripts.engine_checks.cases import make_cases
from scripts.engine_checks.client_profile import CONTROL_NAME, CONTROL_SLOTS, find_client_player_key, player_items, verify_player_items
from scripts.engine_checks.protocol import ProbeError, catalog_result
from scripts.engine_checks.runner import configure_server, container_arguments, public_summary
from scripts.engine_checks.service_profile import assignments


def synthetic_player(cases):
    from mcbe_editor import nbt

    containers = {field: [] for field in CONTROL_SLOTS}
    for field, slot in CONTROL_SLOTS.items():
        containers[field].append(nbt.CompoundTag({
            "Slot": nbt.ByteTag(slot), "Name": nbt.StringTag("minecraft:stone"), "Count": nbt.ByteTag(1), "Damage": nbt.ShortTag(0),
            "tag": nbt.CompoundTag({"display": nbt.CompoundTag({"Name": nbt.StringTag(CONTROL_NAME)})}),
        }))
    locations = assignments(cases)
    for case in cases:
        if case["mode"] == "create":
            continue
        field, slot = locations[case["case_id"]]
        containers[field].append(nbt.CompoundTag({"Slot": nbt.ByteTag(slot), "Name": nbt.StringTag(case["id"]),
                                                "Count": nbt.ByteTag(case["amount"]), "Damage": nbt.ShortTag(0)}))
    return nbt.NamedTag(nbt.CompoundTag({**{field: nbt.ListTag(items) for field, items in containers.items()},
                                       "Opaque": nbt.LongArrayTag([2**50, -1])}))


def test_durability_measurements_detect_wrong_values_missing_components_and_unreviewed_items():
    events = [{"kind": "registry", "ids": ["minecraft:fishing_rod"]},
              {"kind": "item", "id": "minecraft:fishing_rod", "max_amount": 1, "max_durability": 384, "components": []}]
    limits = {"minecraft:fishing_rod": 1}
    assert catalog_result(events, list(limits), limits, {"minecraft:fishing_rod": 384})["status"] == "pass"
    assert catalog_result(events, list(limits), limits, {"minecraft:fishing_rod": 64})["status"] == "fail"
    assert catalog_result(events, list(limits), limits, {})["status"] == "partial"
    events[1]["max_durability"] = None
    assert catalog_result(events, list(limits), limits, {"minecraft:fishing_rod": 384})["status"] == "fail"


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "extra", "count", "control", "slot-type", "container"])
def test_real_player_disk_observer_rejects_corruption(mutation):
    from mcbe_editor import nbt
    from mcbe_editor.bedrock_nbt import save_player_nbt

    cases = make_cases(["minecraft:stone"], {"minecraft:stone": {"max_amount": 64}}, {"minecraft:stone": 64})
    player = synthetic_player(cases)
    assert verify_player_items(save_player_nbt(player), cases, seed=True)["status"] == "pass"
    items = player.tag["EnderChestInventory"]
    if mutation == "missing":
        items.pop()
    elif mutation == "duplicate":
        items.append(deepcopy(items[-1]))
    elif mutation == "extra":
        extra = deepcopy(items[-1])
        extra["Slot"] = nbt.ByteTag(24)
        items.append(extra)
    elif mutation == "count":
        items[-1]["Count"] = nbt.ByteTag(1)
    elif mutation == "control":
        items[0]["tag"]["display"]["Name"] = nbt.StringTag("corrupted")
    elif mutation == "slot-type":
        items[-1]["Slot"] = nbt.IntTag(0)
    else:
        del player.tag["EnderChestInventory"]
    with pytest.raises(ProbeError):
        verify_player_items(save_player_nbt(player), cases, seed=True)


def test_client_transport_is_explicit_ipv4_loopback_only(tmp_path):
    isolated = container_arguments(tmp_path, "test", "sha256:" + "a" * 64)
    assert isolated[isolated.index("--network") + 1] == "none" and "--publish" not in isolated
    connected = container_arguments(tmp_path, "test", "sha256:" + "a" * 64, client_port=19134)
    assert [connected[index + 1] for index, value in enumerate(connected) if value == "--publish"] == [
        "127.0.0.1:19134:19132/tcp", "127.0.0.1:19134:19132/udp",
    ]
    configure_server(tmp_path, client_port=19134)
    properties = dict(line.split("=", 1) for line in (tmp_path / "server.properties").read_text().splitlines())
    assert properties["transport"] == "nethernet"
    assert properties["server-udp-ports"] == "127.0.0.1:19134:19132"
    assert properties["enable-lan-visibility"] == "false" and properties["online-mode"] == "false"
    for invalid in (True, 0, 80, 65536, "19134", "0.0.0.0:19134"):
        with pytest.raises(ProbeError):
            container_arguments(tmp_path, "test", "image", client_port=invalid)


def test_client_summary_never_contains_player_identifiers():
    report = {"status": "fail", "suite": "client", "engine": {}, "editor": {}, "catalog_sha256": "a" * 64,
              "phases": {}, "not_covered": [], "client": {"status": "fail", "key": "PRIVATE_KEY", "name": "PRIVATE_NAME"},
              "nbt_edit": {"player_service": {"status": "pass", "raw": "PRIVATE_NBT", "xuid": "PRIVATE_XUID"}}}
    assert "PRIVATE_" not in json.dumps(public_summary(report))


@pytest.mark.parametrize("mutation", [None, "only-index", "second-player", "index-type", "index-extra", "server-index", "unreadable"])
def test_client_discovery_distinguishes_account_indexes_and_rejects_ambiguity(mutation):
    from mcbe_editor import nbt
    from mcbe_editor.bedrock_nbt import save_player_nbt

    cases = make_cases(["minecraft:stone"], {"minecraft:stone": {"max_amount": 64}}, {"minecraft:stone": 64})
    index = nbt.NamedTag(nbt.CompoundTag({"MsaId": nbt.StringTag("synthetic"), "ServerId": nbt.StringTag("synthetic")}))
    player_key = b"player_server_synthetic"
    records = {player_key: save_player_nbt(synthetic_player(cases))}
    if mutation == "only-index":
        records.clear()
    elif mutation == "second-player":
        records[b"player_server_second"] = records[player_key]
    elif mutation == "index-type":
        index.tag["ServerId"] = nbt.IntTag(1)
    elif mutation == "index-extra":
        index.tag["Inventory"] = nbt.ListTag([])
    index_key = b"player_server_index" if mutation == "server-index" else b"player_synthetic"
    records[index_key] = b"invalid synthetic NBT" if mutation == "unreadable" else save_player_nbt(index)
    if mutation is None:
        assert find_client_player_key(records) == player_key
    else:
        with pytest.raises(ProbeError):
            find_client_player_key(records)


@pytest.mark.parametrize("via_client", [False, True])
def test_native_player_service_preserves_other_fields_and_records(tmp_path, monkeypatch, via_client):
    import mcbe_editor.db as db_module
    from mcbe_editor import nbt
    from mcbe_editor.bedrock_nbt import load_player_nbt, save_player_nbt
    from mcbe_editor.db import LevelDbAdapter
    from scripts.engine_checks.client_profile import client_worker
    from scripts.engine_checks.nbt_roundtrip import read_records
    from scripts.engine_checks.player_service import exercise_player_service

    monkeypatch.setenv("MCBE_BACKUP_ROOT", str(tmp_path / "backups"))
    monkeypatch.setattr(db_module, "_runtime_app_modules", lambda: ())
    monkeypatch.setattr(db_module, "_registered_write_guard", None)
    world = tmp_path / "nonplayable"
    (world / "db").mkdir(parents=True)
    (world / "levelname.txt").write_text("Synthetic nonplayable fixture", encoding="utf-8")
    cases = make_cases(["minecraft:stone"], {"minecraft:stone": {"max_amount": 64}}, {"minecraft:stone": 64})
    player = synthetic_player(cases)
    key = b"player_server_synthetic"
    index_key = b"player_synthetic"
    index = save_player_nbt(nbt.NamedTag(nbt.CompoundTag({"MsaId": nbt.StringTag("synthetic"), "ServerId": nbt.StringTag("synthetic")})))
    db = LevelDbAdapter(str(world / "db"))
    try:
        db.put_batch({key: save_player_nbt(player), index_key: index, b"unrelated": b"preserved"})
    finally:
        db.close()
    if via_client:
        checks = client_worker(tmp_path, world, read_records(world), cases, "edit")["player_service"]
        results = [load_player_nbt(read_records(world)[key]).tag]
        assert client_worker(tmp_path, world, read_records(world), cases, "verify")["status"] == "pass"
        with pytest.raises(ProbeError, match="only once"):
            client_worker(tmp_path, world, read_records(world), cases, "edit")
    else:
        results, checks = exercise_player_service(world, (key,), cases)
    assert checks["backed_up_saves"] == 5 and checks["no_op_checks"] == 1 and checks["stale_revision_rejections"] == 1
    assert results[0]["Opaque"].save_to() == player.tag["Opaque"].save_to()
    assert read_records(world)[b"unrelated"] == b"preserved"
    assert read_records(world)[index_key] == index
    assert verify_player_items(read_records(world)[key], cases)["status"] == "pass"
    assert set(player_items(results[0], "Inventory")) == {0, 1, 35, 34}


@pytest.mark.parametrize("statuses,exit_code", [(["pass", "pass", "pass"], 0), (["pass", "partial", "pass"], 2), (["fail", "partial", "pass"], 1)])
def test_all_suites_keep_failures_and_partial_results(tmp_path, monkeypatch, statuses, exit_code):
    import sys
    from scripts.engine_checks import __main__ as cli

    observed = []

    def run(*args, **kwargs):
        observed.append(args[5])
        return tmp_path, {"status": statuses[len(observed) - 1]}

    monkeypatch.setattr(cli, "run_probe", run)
    monkeypatch.setattr(sys, "argv", ["engine-checks", "--archive", str(tmp_path / "server.zip"), "--sha256", "a" * 64,
                                    "--server-version", "1.26.51.1"])
    assert cli.main() == exit_code
    assert observed == ["extended", "service", "addons"]
