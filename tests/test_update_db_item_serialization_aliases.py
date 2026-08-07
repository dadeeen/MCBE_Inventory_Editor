import io
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import update_db


def _zip_with_mojang_items(payload: dict) -> zipfile.ZipFile:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("metadata/vanilladata_modules/mojang-items.json", json.dumps(payload))
    buffer.seek(0)
    return zipfile.ZipFile(buffer)


def test_parse_json_item_serialization_aliases_maps_canonical_item_to_legacy_lang_key():
    payload = {
        "data_items": [
            {
                "command_name": "minecraft:leather_horse_armor",
                "name": "minecraft:leather_horse_armor",
                "raw_id": 569,
                "serialization_id": "item.horsearmorleather",
                "serialization_name": "minecraft:leather_horse_armor",
            },
            {
                "command_name": "minecraft:apple",
                "name": "minecraft:apple",
                "serialization_id": "item.apple.name",
                "serialization_name": "minecraft:apple",
            },
        ]
    }

    with _zip_with_mojang_items(payload) as zf:
        aliases = update_db.parse_json_item_serialization_aliases(zf)

    assert aliases == {"leather_horse_armor": "horsearmorleather"}


def test_lang_item_parser_accepts_legacy_keys_without_matching_descriptions(tmp_path):
    en_lang = tmp_path / "en_US.lang"
    de_lang = tmp_path / "de_DE.lang"
    en_lang.write_text(
        "\n".join(
            [
                "item.horsearmorleather=Leather Horse Armor",
                "item.apple.desc=Should not become an item name",
                "item.apple.name=Apple",
            ]
        ),
        encoding="utf-8",
    )
    de_lang.write_text(
        "\n".join(
            [
                "item.horsearmorleather=Leder-Rossharnisch",
                "item.apple.desc=Soll kein Itemname werden",
                "item.apple.name=Apfel",
            ]
        ),
        encoding="utf-8",
    )

    en_items, de_items = update_db.parse_lang_items(en_lang, de_lang)

    assert en_items["horsearmorleather"] == "Leather Horse Armor"
    assert de_items["horsearmorleather"] == "Leder-Rossharnisch"
    assert en_items["apple"] == "Apple"
    assert de_items["apple"] == "Apfel"
    assert "apple.desc" not in en_items
    assert "apple.desc" not in de_items


def test_merge_items_uses_serialization_alias_to_fix_existing_english_fallback():
    old = {
        "minecraft:horsearmorleather": ("Leder-Rossharnisch", "Leather Horse Armor"),
        "minecraft:leather_horse_armor": ("Leather Horse Armor", "Leather Horse Armor"),
    }

    merged = update_db.merge_items(
        old,
        en_items={},
        de_items={},
        microsoft_items={"leather_horse_armor": "Leather Horse Armor"},
        serialization_aliases={"leather_horse_armor": "horsearmorleather"},
    )

    assert merged["minecraft:leather_horse_armor"] == ("Leder-Rossharnisch", "Leather Horse Armor")
    assert merged["minecraft:horsearmorleather"] == ("Leder-Rossharnisch", "Leather Horse Armor")


def test_merge_items_keeps_existing_localized_canonical_name():
    old = {
        "minecraft:horsearmorleather": ("Leder-Rossharnisch", "Leather Horse Armor"),
        "minecraft:leather_horse_armor": ("Eigener Lederharnisch", "Leather Horse Armor"),
    }

    merged = update_db.merge_items(
        old,
        en_items={},
        de_items={},
        microsoft_items={"leather_horse_armor": "Leather Horse Armor"},
        serialization_aliases={"leather_horse_armor": "horsearmorleather"},
    )

    assert merged["minecraft:leather_horse_armor"] == ("Eigener Lederharnisch", "Leather Horse Armor")


def test_merge_items_adds_canonical_item_from_legacy_serialization_name():
    old = {
        "minecraft:horsearmorleather": ("Leder-Rossharnisch", "Leather Horse Armor"),
    }

    merged = update_db.merge_items(
        old,
        en_items={},
        de_items={},
        microsoft_items={},
        serialization_aliases={"leather_horse_armor": "horsearmorleather"},
    )

    assert merged["minecraft:leather_horse_armor"] == ("Leder-Rossharnisch", "Leather Horse Armor")


def test_merge_items_does_not_use_different_legacy_variant_as_display_name():
    old = {
        "minecraft:stone": ("Stein", "Stone"),
    }

    merged = update_db.merge_items(
        old,
        en_items={"stone": "Stone"},
        de_items={"stone": "Stein"},
        microsoft_items={"andesite": "Andesite"},
        serialization_aliases={"andesite": "stone"},
        item_localizations={"stone.andesite": ("Andesit", "Andesite")},
    )

    assert merged["minecraft:andesite"] == ("Andesit", "Andesite")
