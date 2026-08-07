from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

nbt = pytest.importorskip("amulet_nbt")

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_diagnostic_module():
    spec = importlib.util.spec_from_file_location("horse_diagnostic", PROJECT_ROOT / "scripts" / "horse_diagnostic.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("horse_diagnostic", module)
    spec.loader.exec_module(module)
    return module


diag = _load_diagnostic_module()


def _record(
    identifier: str,
    *,
    indexed: bool = True,
    definitions=None,
    attribute_names=None,
    attribute_details=None,
    tag_keys=None,
    raw_length: int = 2822,
    suffix: str = "0000000200000001",
    chunk=None,
    position=None,
):
    return {
        "identifier": identifier,
        "digp_contains_actor_suffix": indexed,
        "definitions": definitions or [f"+{identifier}", f"+{identifier}_adult"],
        "attribute_names": attribute_names or ["minecraft:health", "minecraft:movement"],
        "attribute_details": attribute_details or [],
        "tag_keys": tag_keys or ["UniqueID", "Pos", "definitions"],
        "raw_length": raw_length,
        "actor_suffix_hex": suffix,
        "chunk": chunk or {"x": 0, "z": 0},
        "position": position or {"x": 0.0, "y": 64.0, "z": 0.0},
    }


def test_mount_identifiers_cover_all_ui_types() -> None:
    assert set(diag.MOUNT_IDENTIFIERS) == {
        "minecraft:horse",
        "minecraft:donkey",
        "minecraft:mule",
        "minecraft:skeleton_horse",
        "minecraft:camel",
    }
    assert diag.DEFAULT_IDENTIFIERS == ("minecraft:horse",)


def test_writer_evidence_aggregates_only_indexed_records_per_identifier() -> None:
    records = [
        _record(
            "minecraft:donkey",
            definitions=["+minecraft:donkey", "+minecraft:donkey_adult", "+minecraft:donkey_wild"],
            attribute_details=[{"Name": "minecraft:movement", "Base": 0.175}, {"Name": "minecraft:health", "Base": 22.0}],
            tag_keys=["UniqueID", "Pos", "definitions", "Chested"],
            raw_length=2700,
        ),
        _record(
            "minecraft:donkey",
            definitions=["+minecraft:donkey", "+minecraft:donkey_adult", "+minecraft:donkey_wild"],
            attribute_details=[{"Name": "minecraft:movement", "Base": 0.175}],
            tag_keys=["UniqueID", "Pos", "definitions"],
            raw_length=2810,
            suffix="0000000200000002",
        ),
        _record("minecraft:horse", raw_length=2822, suffix="0000000200000003"),
        _record("minecraft:camel", indexed=False, suffix="0000000200000004"),
    ]

    evidence = diag.build_writer_evidence(records)

    assert set(evidence) == {"minecraft:donkey", "minecraft:horse"}
    donkey = evidence["minecraft:donkey"]
    assert donkey["observed_records"] == 2
    assert donkey["definitions_variants"] == [["+minecraft:donkey", "+minecraft:donkey_adult", "+minecraft:donkey_wild"]]
    assert donkey["key_attribute_bases"]["minecraft:movement"] == [0.175]
    assert donkey["tag_keys_always_present"] == ["Pos", "UniqueID", "definitions"]
    assert "Chested" in donkey["tag_keys_union"]
    assert donkey["raw_length_min"] == 2700
    assert donkey["raw_length_max"] == 2810


def test_nearest_reference_prefers_same_identifier() -> None:
    problem = _record("minecraft:donkey", indexed=False, position={"x": 0.0, "y": 64.0, "z": 0.0})
    horse_close = _record("minecraft:horse", position={"x": 1.0, "y": 64.0, "z": 0.0}, suffix="0000000200000005")
    donkey_far = _record("minecraft:donkey", position={"x": 50.0, "y": 64.0, "z": 0.0}, suffix="0000000200000006", chunk={"x": 3, "z": 0})

    reference = diag.nearest_reference(problem, [horse_close, donkey_far])

    assert reference is not None
    assert reference["identifier"] == "minecraft:donkey"


def test_gui_scans_all_mount_identifiers() -> None:
    gui_source = (PROJECT_ROOT / "scripts" / "horse_diagnostic_gui.py").read_text(encoding="utf-8")

    assert "MOUNT_IDENTIFIERS" in gui_source
    assert "identifiers=MOUNT_IDENTIFIERS" in gui_source
    assert "Mounts gefunden" in gui_source
    assert "writer_evidence" in gui_source


def test_gui_always_dumps_raw_nbt_for_all_mount_types() -> None:
    gui_source = (PROJECT_ROOT / "scripts" / "horse_diagnostic_gui.py").read_text(encoding="utf-8")

    assert "RAW_DUMP_IDENTIFIERS = MOUNT_IDENTIFIERS" in gui_source
    assert "dump_identifiers=RAW_DUMP_IDENTIFIERS" in gui_source
    assert "raw_nbt_dumps" in gui_source


def test_gui_keeps_sensitive_reports_outside_the_project_tree() -> None:
    gui_source = (PROJECT_ROOT / "scripts" / "horse_diagnostic_gui.py").read_text(encoding="utf-8")

    assert 'ROOT / "diagnostics"' not in gui_source
    assert "MCBE_HORSE_DIAGNOSTIC_DIR" in gui_source
    assert "atomic_write_private_text" in gui_source


def test_typed_nbt_preserves_tag_types() -> None:
    tag = nbt.CompoundTag(
        {
            "IsTamed": nbt.ByteTag(1),
            "Variant": nbt.IntTag(2),
            "BreedCooldown": nbt.IntTag(0),
            "Scale": nbt.FloatTag(1.0),
            "identifier": nbt.StringTag("minecraft:camel"),
            "Pos": nbt.ListTag([nbt.FloatTag(1.5), nbt.FloatTag(64.0), nbt.FloatTag(-2.5)]),
            "ChestItems": nbt.ListTag([nbt.CompoundTag({"Slot": nbt.ByteTag(0)})]),
        }
    )

    typed = diag.typed_nbt(tag)

    assert typed["type"] == "Compound"
    values = typed["value"]
    assert values["IsTamed"] == {"type": "Byte", "value": 1}
    assert values["Variant"] == {"type": "Int", "value": 2}
    assert values["Scale"]["type"] == "Float"
    assert values["identifier"] == {"type": "String", "value": "minecraft:camel"}
    assert values["Pos"]["type"] == "List"
    assert values["Pos"]["value"][0] == {"type": "Float", "value": 1.5}
    assert values["ChestItems"]["value"][0]["value"]["Slot"] == {"type": "Byte", "value": 0}


def test_find_horses_dumps_typed_nbt_only_for_requested_identifiers(monkeypatch, tmp_path) -> None:
    from contextlib import contextmanager

    from mcbe_editor.bedrock_nbt import SAVE_KWARGS

    def _actor_raw(identifier: str, x: float) -> bytes:
        tag = nbt.CompoundTag(
            {
                "identifier": nbt.StringTag(identifier),
                "Pos": nbt.ListTag([nbt.FloatTag(x), nbt.FloatTag(64.0), nbt.FloatTag(0.0)]),
                "IsTamed": nbt.ByteTag(0),
                "Variant": nbt.IntTag(0),
            }
        )
        return nbt.NamedTag(tag).save_to(**SAVE_KWARGS)

    def _actor_key(local_id: int) -> bytes:
        return b"actorprefix" + (2).to_bytes(4, "big") + local_id.to_bytes(4, "big")

    camel_raw = _actor_raw("minecraft:camel", 1.0)
    horse_raw = _actor_raw("minecraft:horse", 2.0)

    class FakeDb:
        def __init__(self, items):
            self.store = dict(items)

        def get(self, key):
            if key not in self.store:
                raise KeyError(key)
            return self.store[key]

        def iter_items(self):
            return list(self.store.items())

    db = FakeDb({_actor_key(1): camel_raw, _actor_key(2): horse_raw})

    @contextmanager
    def fake_open_db(world_path):
        yield db

    monkeypatch.setattr(diag, "open_db", fake_open_db)
    monkeypatch.setattr(diag, "get_world_name", lambda world_path: "FakeWorld")

    result = diag.find_horses(
        str(tmp_path),
        identifiers=("minecraft:horse", "minecraft:camel"),
        dump_identifiers=("minecraft:camel",),
    )

    assert result["dumped_identifiers"] == ["minecraft:camel"]
    assert result["counts"]["raw_nbt_dumps"] == 1
    by_identifier = {record["identifier"]: record for record in result["records"]}
    camel = by_identifier["minecraft:camel"]
    horse = by_identifier["minecraft:horse"]
    assert camel["raw_hex"] == camel_raw.hex()
    assert camel["nbt_typed"]["type"] == "Compound"
    assert camel["nbt_typed"]["value"]["IsTamed"] == {"type": "Byte", "value": 0}
    assert camel["nbt_typed"]["value"]["Pos"]["value"][1] == {"type": "Float", "value": 64.0}
    assert "nbt_typed" not in horse
    assert "raw_hex" not in horse
