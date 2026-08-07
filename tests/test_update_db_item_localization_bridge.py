from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import update_db


def test_full_lang_catalog_preserves_dotted_keys_without_creating_item_ids(tmp_path: Path) -> None:
    en_lang = tmp_path / "en_US.lang"
    de_lang = tmp_path / "de_DE.lang"
    en_lang.write_text(
        "\n".join(
            [
                "item.boat.acacia.name=Acacia Boat",
                "item.spawn_egg.entity.allay.name=Allay Spawn Egg",
                "item.apple.name=Apple",
                "item.apple.desc=Must not be parsed",
            ]
        ),
        encoding="utf-8",
    )
    de_lang.write_text(
        "\n".join(
            [
                "item.boat.acacia.name=Akazienboot",
                "item.spawn_egg.entity.allay.name=Hilfsgeist-Spawn-Ei",
                "item.apple.name=Apfel",
                "item.apple.desc=Darf nicht geparst werden",
            ]
        ),
        encoding="utf-8",
    )

    localizations = update_db.parse_lang_item_localizations(en_lang, de_lang)
    en_items, de_items = update_db.parse_lang_items(en_lang, de_lang)

    assert localizations["boat.acacia"] == ("Akazienboot", "Acacia Boat")
    assert localizations["spawn_egg.entity.allay"] == ("Hilfsgeist-Spawn-Ei", "Allay Spawn Egg")
    assert "apple.desc" not in localizations
    assert en_items == {"apple": "Apple"}
    assert de_items == {"apple": "Apfel"}


def test_label_bridge_localizes_canonical_boat_spawn_egg_and_slab_ids() -> None:
    old = {
        "minecraft:acacia_boat": ("Acacia Boat", "Acacia Boat"),
        "minecraft:allay_spawn_egg": ("Allay Spawn Egg", "Allay Spawn Egg"),
        "minecraft:oak_slab": ("Oak Slab", "Oak Slab"),
    }
    microsoft_items = {
        "acacia_boat": "Acacia Boat",
        "allay_spawn_egg": "Allay Spawn Egg",
        "oak_slab": "Oak Slab",
    }
    localizations = {
        "boat.acacia": ("Akazienboot", "Acacia Boat"),
        "spawn_egg.entity.allay": ("Hilfsgeist-Spawn-Ei", "Allay Spawn Egg"),
        "wooden_slab.oak": ("Eichenstufe", "Oak Slab"),
    }

    merged = update_db.merge_items(
        old,
        en_items={},
        de_items={},
        microsoft_items=microsoft_items,
        item_localizations=localizations,
    )

    assert merged["minecraft:acacia_boat"] == ("Akazienboot", "Acacia Boat")
    assert merged["minecraft:allay_spawn_egg"] == ("Hilfsgeist-Spawn-Ei", "Allay Spawn Egg")
    assert merged["minecraft:oak_slab"] == ("Eichenstufe", "Oak Slab")
    assert "minecraft:boat.acacia" not in merged
    assert "minecraft:spawn_egg.entity.allay" not in merged


def test_structural_bridge_handles_different_chest_boat_wording_and_legacy_variant_key() -> None:
    old = {
        "minecraft:acacia_chest_boat": ("Acacia Chest Boat", "Acacia Chest Boat"),
        "minecraft:dark_oak_chest_boat": ("Dark Oak Chest Boat", "Dark Oak Chest Boat"),
        "minecraft:bamboo_chest_raft": ("Bamboo Chest Raft", "Bamboo Chest Raft"),
    }
    localizations = {
        "chest_boat.acacia": ("Akazienholztruhenboot", "Acacia Boat with Chest"),
        "chest_boat.big_oak": ("Schwarzeichenholztruhenboot", "Dark Oak Boat with Chest"),
        "chest_boat.bamboo": ("Bambusfloß mit Truhe", "Bamboo Raft with Chest"),
    }

    merged = update_db.merge_items(
        old,
        en_items={},
        de_items={},
        microsoft_items={item_id.removeprefix("minecraft:"): names[1] for item_id, names in old.items()},
        item_localizations=localizations,
    )

    assert merged["minecraft:acacia_chest_boat"] == ("Akazienholztruhenboot", "Acacia Chest Boat")
    assert merged["minecraft:dark_oak_chest_boat"] == ("Schwarzeichenholztruhenboot", "Dark Oak Chest Boat")
    assert merged["minecraft:bamboo_chest_raft"] == ("Bambusfloß mit Truhe", "Bamboo Chest Raft")


def test_structural_bridge_maps_renamed_spawn_egg_by_entity_id() -> None:
    merged = update_db.merge_items(
        {"minecraft:zombie_pigman_spawn_egg": ("Zombie Pigman Spawn Egg", "Zombie Pigman Spawn Egg")},
        en_items={},
        de_items={},
        microsoft_items={"zombie_pigman_spawn_egg": "Zombie Pigman Spawn Egg"},
        item_localizations={"spawn_egg.entity.zombie_pigman": ("Zombifizierter-Piglin-Spawn-Ei", "Zombified Piglin Spawn Egg")},
    )

    assert merged["minecraft:zombie_pigman_spawn_egg"] == (
        "Zombifizierter-Piglin-Spawn-Ei",
        "Zombie Pigman Spawn Egg",
    )


def test_label_bridge_accepts_duplicate_keys_only_when_translations_agree() -> None:
    localizations = {
        "leaves.acacia": ("Akazienlaub", "Acacia Leaves"),
        "leaves2.acacia": ("Akazienlaub", "Acacia Leaves"),
        "stone_slab.smoothstonebrick": ("Steinziegelstufe", "Stone Brick Slab"),
        "double_stone_slab.smoothstonebrick": ("Steinziegel-Stufe", "Stone Brick Slab"),
    }

    index = update_db.build_item_localization_label_index(localizations)

    assert index["acacia leaves"] == ("Akazienlaub", "Acacia Leaves")
    assert "stone brick slab" not in index


def test_label_bridge_never_overwrites_existing_localized_name() -> None:
    merged = update_db.merge_items(
        {"minecraft:acacia_boat": ("Eigenes Akazienboot", "Acacia Boat")},
        en_items={},
        de_items={},
        microsoft_items={"acacia_boat": "Acacia Boat"},
        item_localizations={"boat.acacia": ("Akazienboot", "Acacia Boat")},
    )

    assert merged["minecraft:acacia_boat"] == ("Eigenes Akazienboot", "Acacia Boat")


def test_bed_uses_white_data_value_zero_name_and_repairs_old_black_base_label() -> None:
    merged = update_db.merge_items(
        {"minecraft:bed": ("Schwarzes Bett", "Black Bed")},
        en_items={},
        de_items={},
        microsoft_items={"bed": "Black Bed"},
        item_localizations={
            "bed.white": ("Weißes Bett", "White Bed"),
            "bed.black": ("Schwarzes Bett", "Black Bed"),
        },
    )

    assert merged["minecraft:bed"] == ("Weißes Bett", "White Bed")


def test_label_bridge_skips_missing_or_placeholder_german_names() -> None:
    index = update_db.build_item_localization_label_index(
        {
            "boat.acacia": ("", "Acacia Boat"),
            "spawn_egg.entity.allay": ("%entity.allay.name Spawn Egg", "Allay Spawn Egg"),
        }
    )

    assert index == {}
