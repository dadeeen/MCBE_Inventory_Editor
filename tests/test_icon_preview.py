import json
import zipfile

from scripts.icon_preview import build_preview_payload, generate_preview


def test_build_preview_payload_covers_items_fallbacks_and_archive_icons(tmp_path):
    archive = tmp_path / "icons.mcpack"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("textures/items/apple.png", b"apple")
    (tmp_path / "entity.png").write_bytes(b"entity")
    item_db = {
        "items": {
            "minecraft:apple": ["Apfel", "Apple"],
            "minecraft:element_32": ["Element 32", "Element 32"],
            "minecraft:redstone": ["Redstone-Staub", "Redstone Dust"],
        },
        "compat_item_aliases": {},
        "block_only_items": ["minecraft:element_32"],
        "addable_items": ["minecraft:apple", "minecraft:redstone"],
    }
    icon_index = {
        "icons": {
            "minecraft:apple": {
                "archive_path": str(archive),
                "archive_member": "textures/items/apple.png",
                "source": "Testpack",
            },
        },
        "display_icons": {
            "mcbe:axolotl_gold": {
                "path": str(tmp_path / "entity.png"),
                "source": "Testpack",
            },
        },
        "warnings": ["Testwarnung"],
    }

    payload = build_preview_payload(item_db, icon_index)

    assert payload["item_ids"] == ["minecraft:apple", "minecraft:redstone"]
    assert payload["compatibility_ids"] == ["minecraft:element_32"]
    assert payload["extra_ids"] == []
    assert payload["display_ids"] == ["mcbe:axolotl_gold"]
    assert payload["excluded_non_addable_count"] == 1
    assert "minecraft:element_32" not in payload["item_ids"]
    assert payload["icons"]["minecraft:apple"]["url"].startswith("data:image/png;base64,")
    assert payload["display_icons"]["mcbe:axolotl_gold"]["url"].endswith("entity.png")
    assert payload["warning_count"] == 1

    embedded = build_preview_payload(item_db, icon_index, embed_files=True)
    assert embedded["display_icons"]["mcbe:axolotl_gold"]["url"].startswith("data:image/png;base64,")


def test_generate_preview_writes_ignored_dev_artifact(tmp_path):
    item_db_path = tmp_path / "item_db.json"
    index_path = tmp_path / "icon_index.json"
    output_path = tmp_path / "icon-preview.html"
    item_db_path.write_text(
        json.dumps(
            {
                "items": {"minecraft:redstone": ["Redstone-Staub", "Redstone Dust"]},
                "compat_item_aliases": {},
                "addable_items": ["minecraft:redstone"],
            }
        ),
        encoding="utf-8",
    )
    index_path.write_text(json.dumps({"icons": {}, "warnings": []}), encoding="utf-8")

    payload = generate_preview(item_db_path, index_path, output_path)
    html = output_path.read_text(encoding="utf-8")

    assert payload["item_ids"] == ["minecraft:redstone"]
    assert "MCBE Icon-Vorschau" in html
    assert "minecraft:redstone" in html
    assert "item_catalog.js" in html
    assert "app_bootstrap.js" in html
    assert "Darstellungsassets" in html
    assert "Kompatibilität/Altbestand" in html
    assert "updateSummary();\n    applyFilters();" in html
