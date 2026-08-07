"""Diff the mount writer against real Minecraft-written records.

The writer's per-type constants are claims about what Minecraft produces.
``tests/fixtures/mount_reference.json`` holds the distilled evidence for those
claims, exported from a private reference world with
``scripts/export_mount_reference.py``.  These tests need no private world: the
fixture is committed, sanitized and reviewable.

Only type-invariant evidence is compared.  Values Minecraft rolls per specimen
(health, jump strength, temper, colour) sit in the fixture's ``varying_*`` lists
and are deliberately not asserted.
"""

from __future__ import annotations

import json
from pathlib import Path

import amulet_nbt as nbt
import pytest

from mcbe_editor.bedrock_nbt import LOAD_KWARGS
from mcbe_editor.mount_profile import PROFILE_MODE_CUSTOM
from mcbe_editor.mount_write import SYNTHETIC_CREATABLE_MOUNT_TYPES, build_horse_actor_nbt

REFERENCE_PATH = Path(__file__).parent / "fixtures" / "mount_reference.json"
# Tags whose value is world- or specimen-specific; presence is checked, value is not.
IDENTITY_TAGS = frozenset({"Pos", "Rotation", "UniqueID", "internalComponents", "OwnerNew", "LoveCause", "TargetID", "LeasherID"})


def _reference() -> dict:
    return json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))


def _written_tag(mount_type: str) -> nbt.CompoundTag:
    raw = build_horse_actor_nbt({"x": 0.5, "y": 64.0, "z": 0.5}, 1, b"\x00" * 8, mount_type=mount_type)
    return nbt.load(raw, **LOAD_KWARGS).tag


def _attribute_bases(tag: nbt.CompoundTag) -> dict[str, float]:
    return {str(entry["Name"].py_data): float(entry["Base"].py_data) for entry in tag["Attributes"]}


REFERENCE = _reference()
MOUNT_TYPES = sorted(REFERENCE["mounts"])


def test_reference_covers_every_type_the_writer_can_create() -> None:
    assert set(MOUNT_TYPES) == set(SYNTHETIC_CREATABLE_MOUNT_TYPES)


@pytest.mark.parametrize("mount_type", MOUNT_TYPES)
def test_writer_emits_every_tag_minecraft_writes(mount_type: str) -> None:
    tag = _written_tag(mount_type)
    missing = sorted(name for name in REFERENCE["mounts"][mount_type]["required_tags"] if name not in tag)

    assert missing == [], f"{mount_type}: Minecraft schreibt diese Tags, der Writer nicht: {missing}"


@pytest.mark.parametrize("mount_type", MOUNT_TYPES)
def test_writer_invents_no_tag_minecraft_never_writes(mount_type: str) -> None:
    reference = REFERENCE["mounts"][mount_type]
    known = set(reference["required_tags"]) | set(reference["optional_tags"])
    extra = sorted(str(name) for name in _written_tag(mount_type) if str(name) not in known)

    assert extra == [], f"{mount_type}: der Writer schreibt Tags, die in keinem Spiel-Record vorkommen: {extra}"


@pytest.mark.parametrize("mount_type", MOUNT_TYPES)
def test_writer_matches_the_type_invariant_tag_values(mount_type: str) -> None:
    tag = _written_tag(mount_type)
    mismatches = []
    for name, expected in REFERENCE["mounts"][mount_type]["invariant_tags"].items():
        if name in IDENTITY_TAGS or name not in tag:
            continue
        actual = tag[name].py_data
        if actual != expected:
            mismatches.append(f"{name}: spiel={expected!r} writer={actual!r}")

    assert mismatches == [], f"{mount_type}: {mismatches}"


@pytest.mark.parametrize("mount_type", MOUNT_TYPES)
def test_writer_matches_the_type_invariant_attribute_bases(mount_type: str) -> None:
    ours = _attribute_bases(_written_tag(mount_type))
    mismatches = []
    for name, expected in REFERENCE["mounts"][mount_type]["invariant_attributes"].items():
        if name not in ours:
            mismatches.append(f"{name}: fehlt im Writer-Record")
        elif ours[name] != expected:
            mismatches.append(f"{name}: spiel={expected!r} writer={ours[name]!r}")

    assert mismatches == [], f"{mount_type}: {mismatches}"


@pytest.mark.parametrize("mount_type", MOUNT_TYPES)
def test_writer_attribute_set_matches_the_game(mount_type: str) -> None:
    reference = REFERENCE["mounts"][mount_type]
    expected = set(reference["invariant_attributes"]) | set(reference["varying_attributes"])
    if not expected:
        pytest.skip(f"{mount_type}: keine bestaetigte Attribut-Evidenz (zu wenige Records)")

    assert set(_attribute_bases(_written_tag(mount_type))) == expected


@pytest.mark.parametrize("mount_type", MOUNT_TYPES)
def test_writer_definitions_carry_every_entry_the_game_always_emits(mount_type: str) -> None:
    ours = [item.py_data for item in _written_tag(mount_type)["definitions"]]
    missing = [entry for entry in REFERENCE["mounts"][mount_type]["common_definitions"] if entry not in ours]

    assert missing == [], f"{mount_type}: {missing} fehlt; der Writer schreibt {ours}"


@pytest.mark.parametrize("mount_type", MOUNT_TYPES)
def test_writer_definitions_match_exactly_where_the_game_shows_no_variation(mount_type: str) -> None:
    observed = REFERENCE["mounts"][mount_type]["definitions_variants"]
    if len(observed) != 1:
        pytest.skip(f"{mount_type}: das Spiel zeigt {len(observed)} Varianten (Farbe, Sitzen o. a.)")
    ours = [item.py_data for item in _written_tag(mount_type)["definitions"]]

    assert ours == observed[0]


def test_horse_colour_and_marking_tables_reproduce_the_game_definitions() -> None:
    """The writer's colour/marking lookup must emit what Minecraft emitted."""

    observed = REFERENCE["mounts"]["minecraft:horse"]["variant_definitions"]
    assert observed, "keine Farb-/Markierungs-Evidenz im Fixture"
    for entry in observed:
        raw = build_horse_actor_nbt(
            {"x": 0.5, "y": 64.0, "z": 0.5},
            1,
            b"\x00" * 8,
            horse_profile={"mode": PROFILE_MODE_CUSTOM, "color": entry["variant"], "mark_variant": entry["mark_variant"]},
            mount_type="minecraft:horse",
        )
        ours = [item.py_data for item in nbt.load(raw, **LOAD_KWARGS).tag["definitions"]]

        assert ours == entry["definitions"], f"Variant={entry['variant']} MarkVariant={entry['mark_variant']}"


def test_reference_carries_no_coordinates_or_identities() -> None:
    """The fixture is committed, so it must not leak world or player data."""

    raw = REFERENCE_PATH.read_text(encoding="utf-8")
    for mount in REFERENCE["mounts"].values():
        recorded = set(mount["invariant_tags"]) | set(mount.get("unconfirmed_single_specimen", {}).get("tags", {}))
        assert not (recorded & IDENTITY_TAGS), f"Identitaets-Tags mit Wert im Fixture: {sorted(recorded & IDENTITY_TAGS)}"
    assert "CustomName" not in raw
