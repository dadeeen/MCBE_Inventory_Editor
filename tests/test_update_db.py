import contextlib
import hashlib
import io
import json
import sys
import tempfile
import unittest
import zipfile

import pytest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def load_update_db():
    import update_db

    return update_db


update_db = load_update_db()


SAMPLE_WIKI_HTML = """
<table>
  <tr>
    <th>Name</th>
    <th>Identifier</th>
    <th>Summary</th>
    <th>Incompatible<br />With</th>
    <th>Max<br />Level</th>
    <th>Primary<br />Items</th>
  </tr>
  <tr>
    <td>Aqua Affinity</td>
    <td><code>aqua_affinity</code></td>
    <td>Removes mining speed reduction underwater.</td>
    <td></td>
    <td data-sort-value="1">I</td>
    <td></td>
  </tr>
  <tr>
    <td>Bane of Arthropods</td>
    <td><code>bane_of_arthropods</code></td>
    <td>Applies Slowness IV to arthropods.</td>
    <td>Smite, Sharpness</td>
    <td data-sort-value="5">V</td>
    <td></td>
  </tr>
  <tr>
    <td>Curse of Binding</td>
    <td><code>binding_curse</code> JE only<br /><code>binding</code> BE only</td>
    <td>Items cannot be removed from armor slots.</td>
    <td></td>
    <td data-sort-value="1">I</td>
    <td></td>
  </tr>
  <tr>
    <td>Broken Level</td>
    <td><code>broken_level</code></td>
    <td>Summary with no roman max level.</td>
    <td></td>
    <td>3</td>
    <td></td>
  </tr>
</table>
"""


class FakeOpener:
    def __init__(self):
        self.addheaders = None

    def open(self, url, timeout=None):
        raise OSError("offline")


class TestUrlValidation(unittest.TestCase):
    def test_allows_current_github_release_asset_redirect_host(self):
        url = "https://release-assets.githubusercontent.com/github-production-release-asset/540129950/example?response-content-type=application%2Foctet-stream"

        self.assertEqual(
            update_db._validate_https_url(url, update_db.ALLOWED_RESOURCE_PACK_HOSTS, label="Resource-Pack"),
            url,
        )

    def test_rejects_untrusted_resource_pack_host(self):
        with self.assertRaisesRegex(RuntimeError, "Unsichere Resource-Pack-URL"):
            update_db._validate_https_url(
                "https://example.invalid/bedrock-samples.zip",
                update_db.ALLOWED_RESOURCE_PACK_HOSTS,
                label="Resource-Pack",
            )

    def test_rejects_credentials_nonstandard_port_and_malformed_authority(self):
        for url in (
            "https://user:secret@github.com/asset.zip",
            "https://github.com:8443/asset.zip",
            "https://[github.com/asset.zip",
        ):
            with self.subTest(url=url), self.assertRaisesRegex(RuntimeError, "Unsichere Resource-Pack-URL"):
                update_db._validate_https_url(
                    url,
                    update_db.ALLOWED_RESOURCE_PACK_HOSTS,
                    label="Resource-Pack",
                )

    def test_rejects_untrusted_redirect_before_following_it(self):
        handler = update_db._AllowlistedRedirectHandler(
            update_db.ALLOWED_RESOURCE_PACK_HOSTS,
            label="Resource-Pack",
        )
        request = update_db.urllib.request.Request("https://github.com/Mojang/bedrock-samples/releases/download/v1/asset.zip")

        with self.assertRaisesRegex(RuntimeError, "Unsichere Resource-Pack-URL"):
            handler.redirect_request(
                request,
                None,
                302,
                "Found",
                {},
                "http://127.0.0.1:8080/internal",
            )


class TestMicrosoftItemListings(unittest.TestCase):
    def test_parses_official_item_listing_table(self):
        html = """
        <table>
          <tr><th>Identifier</th><th>Runtime ID</th></tr>
          <tr><td>cornflower</td><td>654</td></tr>
          <tr><td>dandelion</td><td>37</td></tr>
          <tr><td>potion</td><td>426</td></tr>
          <tr><td>white_wool</td><td>-561</td></tr>
          <tr><td>Max Stack Size</td><td>64</td></tr>
        </table>
        """
        items = update_db.parse_microsoft_item_listing(html)

        self.assertEqual(items["cornflower"], "Cornflower")
        self.assertEqual(items["dandelion"], "Dandelion")
        self.assertEqual(items["potion"], "Potion")
        self.assertEqual(items["white_wool"], "White Wool")
        self.assertNotIn("max_stack_size", items)

    def test_merge_items_adds_microsoft_learn_ids_without_overwriting_existing_entries(self):
        old = {"minecraft:dandelion": ("Alter Löwenzahn", "Old Dandelion")}
        merged = update_db.merge_items(old, {}, {}, {"dandelion": "Dandelion", "white_wool": "White Wool"})

        self.assertEqual(merged["minecraft:dandelion"], ("Alter Löwenzahn", "Old Dandelion"))
        self.assertEqual(merged["minecraft:white_wool"], ("White Wool", "White Wool"))

    def test_normalized_microsoft_listing_cache_roundtrip(self):
        items = {f"test_item_{index}": f"Test Item {index}" for index in range(1_000)}
        snapshot = {
            "microsoft_item_listing_url": update_db.MICROSOFT_ITEM_LISTINGS_URL,
            "microsoft_item_listing_fetched_at": "2026-08-14T12:00:00+00:00",
            "microsoft_item_listing_content_hash": hashlib.sha256(b"listing").hexdigest(),
            "microsoft_item_listing_count": len(items),
        }
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "microsoft-items.json"
            with mock.patch.object(update_db, "ITEM_LISTING_CACHE_PATH", cache_path):
                update_db.write_microsoft_item_listing_cache(items, snapshot)
                cached_items, cached_snapshot = update_db.read_microsoft_item_listing_cache()

        self.assertEqual(cached_items, items)
        self.assertEqual(cached_snapshot, snapshot)

    def test_cached_listing_replay_does_not_contact_microsoft(self):
        items = {f"test_item_{index}": f"Test Item {index}" for index in range(1_000)}
        snapshot = {
            "microsoft_item_listing_url": update_db.MICROSOFT_ITEM_LISTINGS_URL,
            "microsoft_item_listing_fetched_at": "2026-08-14T12:00:00+00:00",
            "microsoft_item_listing_content_hash": hashlib.sha256(b"listing").hexdigest(),
            "microsoft_item_listing_count": len(items),
        }
        with (
            mock.patch.object(update_db, "read_microsoft_item_listing_cache", return_value=(items, snapshot)),
            mock.patch.object(update_db, "fetch_microsoft_item_listing_snapshot") as fetch,
            mock.patch.object(update_db, "log"),
        ):
            resolved = update_db.resolve_microsoft_item_listing_snapshot(reuse_cached=True)

        self.assertEqual(resolved, (items, snapshot))
        fetch.assert_not_called()

    def test_lang_item_parser_skips_axolotl_color_variant_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            en_lang = tmp_path / "en_US.lang"
            de_lang = tmp_path / "de_DE.lang"
            en_lang.write_text(
                "\n".join(
                    [
                        "item.axolotl_bucket.name=Axolotl Bucket",
                        "item.axolotlColorBlue.name=Blue",
                        "item.tropicalColorBlue.name=Blue",
                        "item.tropicalSchoolClownfish.name=Clownfish",
                    ]
                ),
                encoding="utf-8",
            )
            de_lang.write_text(
                "\n".join(
                    [
                        "item.axolotl_bucket.name=Axolotleimer",
                        "item.axolotlColorBlue.name=Blau",
                        "item.tropicalColorBlue.name=Blau",
                        "item.tropicalSchoolClownfish.name=Clownfisch",
                    ]
                ),
                encoding="utf-8",
            )

            en_items, de_items = update_db.parse_lang_items(en_lang, de_lang)

        self.assertEqual(en_items["axolotl_bucket"], "Axolotl Bucket")
        self.assertEqual(de_items["axolotl_bucket"], "Axolotleimer")
        self.assertNotIn("axolotlcolorblue", en_items)
        self.assertNotIn("axolotlcolorblue", de_items)
        self.assertNotIn("tropicalcolorblue", en_items)
        self.assertNotIn("tropicalcolorblue", de_items)
        self.assertNotIn("tropicalschoolclownfish", en_items)
        self.assertNotIn("tropicalschoolclownfish", de_items)

    def test_lang_item_parser_skips_glazed_terracotta_localization_keys(self):
        # tile.glazedTerracotta*.name sind reine Lokalisierungsschlüssel; die
        # echten IDs (<farbe>_glazed_terracotta) kommen aus mojang-items.json.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            en_lang = tmp_path / "en_US.lang"
            en_lang.write_text(
                "\n".join(
                    [
                        "tile.glazedTerracottaBlack.name=Black Glazed Terracotta",
                        "tile.glazedTerracottaSilver.name=Light Gray Glazed Terracotta",
                        "tile.stonecutter.name=Stonecutter",
                    ]
                ),
                encoding="utf-8",
            )

            en_items, _de_items = update_db.parse_lang_items(en_lang, None)

        self.assertNotIn("glazedterracottablack", en_items)
        self.assertNotIn("glazedterracottasilver", en_items)
        self.assertEqual(en_items["stonecutter"], "Stonecutter")

    def test_compute_block_only_item_ids_uses_mojang_registries(self):
        # Block-Registry ja + Item-Registry nein => kein Inventar-Item.
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            zf.writestr(
                "metadata/vanilladata_modules/mojang-items.json",
                json.dumps({"data_items": [{"command_name": "minecraft:oak_slab"}, {"command_name": "minecraft:cake"}]}),
            )
            zf.writestr(
                "metadata/vanilladata_modules/mojang-blocks.json",
                json.dumps(
                    {
                        "data_items": [
                            {"command_name": "minecraft:oak_slab"},
                            {"command_name": "minecraft:oak_double_slab"},
                            {"command_name": "minecraft:candle_cake"},
                        ]
                    }
                ),
            )
        items = {
            "minecraft:oak_slab": ("Eichenholzstufe", "Oak Slab"),
            "minecraft:oak_double_slab": ("Oak Double Slab", "Oak Double Slab"),
            "minecraft:candle_cake": ("Kuchen mit Kerze", "Cake with Candle"),
            "minecraft:cake": ("Kuchen", "Cake"),
            "minecraft:bucketlava": ("Lavaeimer", "Lava Bucket"),
            # In keiner Registry, aber laut Suffix-Muster technische Blockformen.
            "minecraft:double_wooden_slab": ("Double Wooden Slab", "Double Wooden Slab"),
            "minecraft:poplar_double_slab": ("Pappel-Doppelstufe", "Poplar Double Slab"),
            "minecraft:poplar_wall_sign": ("Pappel-Mauerschild", "Poplar Wall Sign"),
            "minecraft:poplar_sign": ("Pappelschild", "Poplar Sign"),
        }
        with zipfile.ZipFile(io.BytesIO(buffer.getvalue())) as zf:
            block_only = update_db.compute_block_only_item_ids(zf, items)

        # Legacy-Item-Aliasse (bucketlava) und echte Items bleiben unmarkiert.
        self.assertEqual(
            block_only,
            [
                "minecraft:candle_cake",
                "minecraft:double_wooden_slab",
                "minecraft:oak_double_slab",
                "minecraft:poplar_double_slab",
                "minecraft:poplar_wall_sign",
            ],
        )

    def test_compute_block_only_item_ids_requires_both_registries(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            zf.writestr("metadata/vanilladata_modules/mojang-items.json", json.dumps({"data_items": []}))
        with zipfile.ZipFile(io.BytesIO(buffer.getvalue())) as zf:
            block_only = update_db.compute_block_only_item_ids(zf, {"minecraft:candle_cake": ("Kuchen mit Kerze", "Cake with Candle")})

        self.assertEqual(block_only, [])

    def test_compute_addable_item_ids_uses_positive_mojang_item_registry(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            zf.writestr(
                "metadata/vanilladata_modules/mojang-items.json",
                json.dumps(
                    {
                        "data_items": [
                            {"command_name": "minecraft:apple"},
                            {"name": "minecraft:allow"},
                        ]
                    }
                ),
            )
        with zipfile.ZipFile(io.BytesIO(buffer.getvalue())) as zf:
            addable = update_db.compute_addable_item_ids(
                zf,
                {
                    "minecraft:apple": ("Apfel", "Apple"),
                    "minecraft:allow": ("Erlauben", "Allow"),
                    "minecraft:element_32": ("Element 32", "Element 32"),
                    "minecraft:written_book": ("Beschriebenes Buch", "Written Book"),
                },
            )

        self.assertEqual(addable, ["minecraft:allow", "minecraft:apple"])

    def test_parse_json_item_component_limits_reads_jsonc_vanilla_values(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            zf.writestr(
                "behavior_pack/items/copper_spear.json",
                """
                {
                  // Mojang behavior item
                  "minecraft:item": {
                    "description": {
                      "identifier": "minecraft:copper_spear",
                      "documentation": "https://example.test/items/copper_spear"
                    },
                    "components": {
                      "minecraft:max_stack_size": 1,
                      /* Real durability, stored in item tag.Damage. */
                      "minecraft:durability": {"max_durability": 190}
                    }
                  }
                }
                """,
            )
            zf.writestr(
                "behavior_pack/items/not_damageable.json",
                json.dumps(
                    {
                        "minecraft:item": {
                            "description": {"identifier": "minecraft:not_damageable"},
                            "components": {"minecraft:max_stack_size": 16},
                        }
                    }
                ),
            )
            zf.writestr(
                "behavior_pack/items/invalid_limits.json",
                json.dumps(
                    {
                        "minecraft:item": {
                            "description": {"identifier": "minecraft:invalid_limits"},
                            "components": {
                                "minecraft:max_stack_size": 128,
                                "minecraft:durability": {"max_durability": True},
                            },
                        }
                    }
                ),
            )

        with zipfile.ZipFile(io.BytesIO(buffer.getvalue())) as zf:
            stack_limits, durability = update_db.parse_json_item_component_limits(zf)

        self.assertEqual(
            stack_limits,
            {
                "minecraft:copper_spear": 1,
                "minecraft:not_damageable": 16,
            },
        )
        self.assertEqual(durability, {"minecraft:copper_spear": 190})

    def test_parse_json_item_component_limits_rejects_malformed_official_item(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            zf.writestr("behavior_pack/items/broken.json", '{"minecraft:item":')

        with zipfile.ZipFile(io.BytesIO(buffer.getvalue())) as zf, self.assertRaisesRegex(RuntimeError, "broken.json"):
            update_db.parse_json_item_component_limits(zf)

    def test_parse_json_item_components_normalizes_supported_official_components(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            zf.writestr(
                "behavior_pack/items/copper_spear.json",
                json.dumps(
                    {
                        "minecraft:item": {
                            "description": {"identifier": "minecraft:copper_spear"},
                            "components": {
                                "minecraft:max_stack_size": 1,
                                "minecraft:durability": {"max_durability": 190},
                                "minecraft:enchantable": {"slot": "melee_spear", "value": 13},
                                # Nicht verfolgte Komponenten müssen folgenlos
                                # ignoriert werden, statt den Lauf zu stoppen.
                                "minecraft:repairable": {"repair_items": [{"items": ["minecraft:copper_ingot"]}]},
                                "minecraft:dyeable": {"default_color": "#A0B1C2"},
                                "minecraft:wearable": {
                                    "slot": "slot.weapon.offhand",
                                    "protection": 0,
                                    "dispensable": True,
                                },
                            },
                        }
                    }
                ),
            )

        with zipfile.ZipFile(io.BytesIO(buffer.getvalue())) as zf:
            stack_limits, durability, components = update_db.parse_json_item_components(zf)

        self.assertEqual(stack_limits, {"minecraft:copper_spear": 1})
        self.assertEqual(durability, {"minecraft:copper_spear": 190})
        self.assertEqual(
            components,
            {
                "enchantable": {
                    "minecraft:copper_spear": {"slot": "melee_spear", "value": 13},
                },
                "wearable": {
                    "minecraft:copper_spear": {
                        "slot": "slot.weapon.offhand",
                        "protection": 0,
                        "dispensable": True,
                    },
                },
            },
        )

    def test_parse_json_item_components_stops_for_unknown_future_enchantable_slot(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            zf.writestr(
                "behavior_pack/items/future_item.json",
                json.dumps(
                    {
                        "minecraft:item": {
                            "description": {"identifier": "minecraft:future_item"},
                            "components": {
                                "minecraft:enchantable": {"slot": "future_slot", "value": 1},
                            },
                        }
                    }
                ),
            )

        with zipfile.ZipFile(io.BytesIO(buffer.getvalue())) as zf, self.assertRaisesRegex(RuntimeError, "future_slot"):
            update_db.parse_json_item_components(zf)

    def test_curated_engine_limits_cover_damageable_items_missing_from_behavior_items(self):
        self.assertLessEqual(set(update_db.CURATED_ENGINE_DURABILITY) - {"minecraft:crossbow"}, set(update_db.CURATED_ENGINE_STACK_LIMITS))
        for item_id in (
            "minecraft:iron_hoe",
            "minecraft:leather_boots",
            "minecraft:leather_chestplate",
            "minecraft:leather_helmet",
            "minecraft:leather_leggings",
        ):
            self.assertEqual(update_db.CURATED_ENGINE_STACK_LIMITS[item_id], 1)
        self.assertEqual(update_db.CURATED_ENGINE_DURABILITY["minecraft:brush"], 64)
        self.assertEqual(update_db.CURATED_ENGINE_DURABILITY["minecraft:copper_sword"], 190)
        self.assertEqual(update_db.CURATED_ENGINE_DURABILITY["minecraft:mace"], 500)
        self.assertEqual(update_db.CURATED_ENGINE_DURABILITY["minecraft:turtle_helmet"], 275)
        self.assertEqual(update_db.CURATED_ENGINE_DURABILITY["minecraft:wolf_armor"], 64)
        self.assertEqual(update_db.CURATED_ENGINE_DURABILITY["minecraft:crossbow"], 464)
        stack_limits, durability = update_db.merge_item_limits(
            {"minecraft:legacy": 16},
            {"minecraft:legacy": 12},
            {"minecraft:mace": 2, "minecraft:data_driven": 8},
            {"minecraft:mace": 501, "minecraft:data_driven": 99},
        )
        self.assertEqual(stack_limits["minecraft:data_driven"], 8)
        self.assertEqual(stack_limits["minecraft:legacy"], 16)
        self.assertEqual(stack_limits["minecraft:mace"], 2)
        self.assertEqual(stack_limits["minecraft:brush"], 1)
        self.assertEqual(durability["minecraft:data_driven"], 99)
        self.assertEqual(durability["minecraft:legacy"], 12)
        self.assertEqual(durability["minecraft:mace"], 501)
        self.assertEqual(durability["minecraft:crossbow"], 464)

    def test_merge_item_limits_removes_only_previous_behavior_values(self):
        stack_limits, durability = update_db.merge_item_limits(
            {
                "minecraft:manual": 16,
                "minecraft:removed_behavior_item": 8,
            },
            {
                "minecraft:manual": 12,
                "minecraft:removed_behavior_item": 99,
            },
            {},
            {},
            previous_component_stack_items={"minecraft:removed_behavior_item"},
            previous_component_durability_items={"minecraft:removed_behavior_item"},
        )

        self.assertEqual(stack_limits["minecraft:manual"], 16)
        self.assertEqual(durability["minecraft:manual"], 12)
        self.assertNotIn("minecraft:removed_behavior_item", stack_limits)
        self.assertNotIn("minecraft:removed_behavior_item", durability)
        self.assertEqual(stack_limits["minecraft:mace"], 1)
        self.assertEqual(durability["minecraft:mace"], 500)

    def test_compute_block_item_ids_uses_registry_intersection(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            zf.writestr(
                "metadata/vanilladata_modules/mojang-items.json",
                json.dumps(
                    {
                        "data_items": [
                            {"command_name": "minecraft:hopper"},
                            {"command_name": "minecraft:diamond"},
                            {"command_name": "minecraft:wheat"},
                        ]
                    }
                ),
            )
            zf.writestr(
                "metadata/vanilladata_modules/mojang-blocks.json",
                json.dumps(
                    {
                        "data_items": [
                            {"command_name": "minecraft:hopper"},
                            {"command_name": "minecraft:candle_cake"},
                            {"command_name": "minecraft:wheat"},
                        ]
                    }
                ),
            )
        items = {
            "minecraft:hopper": ("Trichter", "Hopper"),
            "minecraft:diamond": ("Diamant", "Diamond"),
            "minecraft:candle_cake": ("Kuchen mit Kerze", "Cake with Candle"),
            "minecraft:wheat": ("Weizen", "Wheat"),
        }
        with zipfile.ZipFile(io.BytesIO(buffer.getvalue())) as zf:
            block_items = update_db.compute_block_item_ids(zf, items)

        self.assertEqual(block_items, ["minecraft:hopper"])


class TestWikiMaxLevelParser(unittest.TestCase):
    def test_parses_bedrock_identifiers_and_roman_levels(self):
        levels = update_db.parse_wiki_enchantment_max_levels(SAMPLE_WIKI_HTML)

        self.assertEqual(levels["aqua_affinity"], 1)
        self.assertEqual(levels["bane_of_arthropods"], 5)
        self.assertEqual(levels["binding"], 1)
        self.assertNotIn("broken_level", levels)

    def test_raises_when_table_is_missing(self):
        with self.assertRaisesRegex(RuntimeError, "MaxLevel-Tabelle"):
            update_db.parse_wiki_enchantment_max_levels("<p>No tables here</p>")

    def test_raises_when_no_levels_are_parsed(self):
        html = """
        <table>
          <tr><th>Name</th><th>Identifier</th><th>Max Level</th></tr>
          <tr><td>Broken</td><td>broken</td><td>3</td></tr>
        </table>
        """
        with self.assertRaisesRegex(RuntimeError, "Keine MaxLevel-Einträge"):
            update_db.parse_wiki_enchantment_max_levels(html)

    def test_fetch_reports_network_errors(self):
        def fake_build_opener(*_handlers):
            return FakeOpener()

        with (
            mock.patch.object(update_db.urllib.request, "build_opener", fake_build_opener),
            self.assertRaisesRegex(RuntimeError, "offline"),
        ):
            update_db.fetch_wiki_enchantment_max_levels(update_db.WIKI_ENCHANTMENTS_URL)

    def test_optional_check_does_not_fetch_wiki_when_disabled(self):
        with mock.patch.object(update_db, "fetch_wiki_enchantment_snapshot") as fetch:
            snapshot = update_db.optional_wiki_enchantment_check(False, {"protection": 4})

        self.assertIsNone(snapshot)
        fetch.assert_not_called()

    def test_optional_check_keeps_local_values_when_wiki_is_unavailable(self):
        with (
            mock.patch.object(update_db, "fetch_wiki_enchantment_snapshot", side_effect=RuntimeError("offline")),
            mock.patch.object(update_db, "log"),
        ):
            snapshot = update_db.optional_wiki_enchantment_check(True, {"protection": 4})

        self.assertIsNone(snapshot)

    def test_max_level_diff_reports_changes_and_coverage(self):
        differences = update_db.diff_enchantment_max_levels(
            {"aqua_affinity": 1, "protection": 4},
            {"protection": 3, "wind_burst": 3},
        )

        self.assertEqual(differences["different"], {"protection": {"local": 4, "wiki": 3}})
        self.assertEqual(differences["missing_in_wiki"], ["aqua_affinity"])
        self.assertEqual(differences["wiki_only"], ["wind_burst"])

    def test_build_source_metadata_uses_release_and_wiki_snapshot(self):
        release_info = {
            "resource_pack_release": "bedrock-1.2.3",
            "resource_pack_asset": "resource_pack-1.2.3-min.zip",
            "resource_pack_asset_size": 12345,
            "resource_pack_fetched_at": "2026-06-22T00:00:00+00:00",
            "resource_pack_url": "https://example.test/resource_pack.zip",
        }
        wiki_snapshot = {
            "wiki_url": update_db.WIKI_ENCHANTMENTS_URL,
            "wiki_fetched_at": "2026-06-22T00:01:00+00:00",
            "wiki_revision_id": 12345,
            "wiki_content_hash": "abc123",
        }
        item_listing_snapshot = {
            "microsoft_item_listing_url": update_db.MICROSOFT_ITEM_LISTINGS_URL,
            "microsoft_item_listing_fetched_at": "2026-06-22T00:01:30+00:00",
            "microsoft_item_listing_content_hash": "items123",
            "microsoft_item_listing_count": 1700,
        }

        with mock.patch.object(update_db, "utc_now", return_value="2026-06-22T00:02:00+00:00"):
            metadata = update_db.build_source_metadata(release_info, wiki_snapshot, item_listing_snapshot)

        self.assertEqual(metadata["resource_pack_release"], "bedrock-1.2.3")
        self.assertEqual(metadata["wiki_revision_id"], 12345)
        self.assertEqual(metadata["microsoft_item_listing_url"], update_db.MICROSOFT_ITEM_LISTINGS_URL)
        self.assertEqual(metadata["microsoft_item_listing_content_hash"], "items123")
        self.assertEqual(metadata["microsoft_item_listing_count"], 1700)
        self.assertEqual(metadata["generated_at"], "2026-06-22T00:02:00+00:00")

    def test_build_source_identity_matches_without_timestamps(self):
        release_info = {
            "resource_pack_release": "bedrock-1.2.3",
            "resource_pack_asset": "rp.zip",
            "resource_pack_asset_size": 100,
            "resource_pack_url": "https://example.test/rp.zip",
        }
        wiki_snapshot = {
            "wiki_url": "https://minecraft.wiki/w/Enchantment",
            "wiki_revision_id": 3639370,
            "wiki_content_hash": "def456",
        }
        identity = update_db.build_source_identity(release_info, wiki_snapshot)
        self.assertEqual(identity["resource_pack_release"], "bedrock-1.2.3")
        self.assertEqual(identity["wiki_revision_id"], 3639370)
        self.assertNotIn("generated_at", identity)
        self.assertNotIn("wiki_fetched_at", identity)
        self.assertNotIn("resource_pack_fetched_at", identity)


class TestMergeEnchantments(unittest.TestCase):
    def test_uses_local_max_level_for_new_enchantments(self):
        old = {0: ("Schutz", "Protection", 4, "")}
        json_list = [("protection", 1), ("new_enchantment", 1)]
        en_names = {"new_enchantment": "New Enchantment"}
        de_names = {}
        local_max_levels = {"protection": 4, "new_enchantment": 7}
        local_numeric_ids = {"protection": 0, "new_enchantment": 1}

        merged = update_db.merge_enchantments(
            old,
            json_list,
            en_names,
            de_names,
            local_max_levels,
            local_numeric_ids,
        )

        self.assertEqual(merged[1], ("New Enchantment", "New Enchantment", 7, ""))

    def test_local_table_corrects_existing_max_level_without_changing_numeric_id(self):
        old = {17: ("Haltbarkeit", "Unbreaking", 2, "Beschreibung")}

        merged = update_db.merge_enchantments(
            old,
            [("unbreaking", 1)],
            {},
            {},
            {"unbreaking": 3},
            {"unbreaking": 17},
        )

        self.assertEqual(merged, {17: ("Haltbarkeit", "Unbreaking", 3, "Beschreibung")})

    def test_missing_local_max_level_fails_instead_of_defaulting_to_one(self):
        with self.assertRaisesRegex(RuntimeError, "new_enchantment"):
            update_db.merge_enchantments({}, [("new_enchantment", 1)], {}, {}, {}, {"new_enchantment": 1})

    def test_missing_reviewed_numeric_id_fails_instead_of_guessing_next_id(self):
        with self.assertRaisesRegex(RuntimeError, "numerische IDs.*new_enchantment"):
            update_db.merge_enchantments(
                {0: ("Schutz", "Protection", 4, "")},
                [("protection", 1), ("new_enchantment", 1)],
                {},
                {},
                {"protection": 4, "new_enchantment": 1},
                {"protection": 0},
            )

    def test_aliases_prevent_duplicate_legacy_enchantments(self):
        old = {
            22: ("Unendlichkeit", "Infinity", 1, ""),
            27: ("Fluch der Bindung", "Binding Curse", 1, ""),
            28: ("Fluch des Verschwindens", "Vanishing Curse", 1, ""),
        }
        json_list = [("bow_infinity", 1), ("binding", 1), ("vanishing", 1)]

        local_max_levels = {"infinity": 1, "binding_curse": 1, "vanishing_curse": 1}
        local_numeric_ids = {"infinity": 22, "binding_curse": 27, "vanishing_curse": 28}
        merged = update_db.merge_enchantments(old, json_list, {}, {}, local_max_levels, local_numeric_ids)

        self.assertEqual(merged, old)

    def test_reviewed_numeric_ids_repair_shifted_modern_enchantments(self):
        old = {
            40: ("Durchbruch", "Breach", 4, ""),
            41: ("Dichte", "Density", 5, ""),
            42: ("Ausfallschritt", "Lunge", 3, ""),
            44: ("Windstoß", "Wind Burst", 3, ""),
        }
        json_list = [("wind_burst", 1), ("density", 1), ("breach", 1), ("lunge", 1)]
        local_max_levels = {"wind_burst": 3, "density": 5, "breach": 4, "lunge": 3}
        local_numeric_ids = {"wind_burst": 38, "density": 39, "breach": 40, "lunge": 41}

        merged = update_db.merge_enchantments(
            old,
            json_list,
            {},
            {},
            local_max_levels,
            local_numeric_ids,
        )

        self.assertEqual(
            merged,
            {
                38: ("Windstoß", "Wind Burst", 3, ""),
                39: ("Dichte", "Density", 5, ""),
                40: ("Durchbruch", "Breach", 4, ""),
                41: ("Ausfallschritt", "Lunge", 3, ""),
            },
        )

    def test_parse_json_enchantments_prefers_value_field(self):
        payload = {
            "data_items": [
                {"name": "bow_infinity", "value": "minecraft:infinity"},
                {"name": "minecraft:binding"},
            ]
        }
        with io.BytesIO() as buffer:
            with zipfile.ZipFile(buffer, "w") as zf:
                zf.writestr("metadata/vanilladata_modules/mojang-enchantments.json", json.dumps(payload))
            buffer.seek(0)
            with zipfile.ZipFile(buffer) as zf:
                parsed = update_db.parse_json_enchantments(zf)

        self.assertEqual(parsed, [("infinity", 1), ("binding_curse", 1)])

    def test_wiki_only_enchantments_do_not_become_available_without_mojang_data(self):
        old = {}
        json_list = [("lunge", 1), ("wind_burst", 1)]
        local_max_levels = {
            "lunge": 3,
            "wind_burst": 3,
            "sweeping_edge": 3,
            "cleaving": 3,
        }
        local_numeric_ids = {
            "lunge": 41,
            "wind_burst": 38,
            "sweeping_edge": 42,
            "cleaving": 43,
        }

        merged = update_db.merge_enchantments(old, json_list, {}, {}, local_max_levels, local_numeric_ids)
        merged_identifiers = {update_db._canonical_enchantment_identifier(values[1]) for values in merged.values()}

        self.assertEqual(merged_identifiers, {"lunge", "wind_burst"})
        self.assertNotIn("sweeping_edge", merged_identifiers)
        self.assertNotIn("cleaving", merged_identifiers)


def test_local_enchantment_max_levels_cover_bundled_enchantments():
    levels = update_db.load_local_enchantment_max_levels()
    numeric_ids = update_db.load_local_enchantment_numeric_ids()
    data = json.loads(update_db.DEFAULT_ITEM_DB_PATH.read_text(encoding="utf-8"))
    identifiers_by_id = {int(enchantment_id): update_db._canonical_enchantment_identifier(values[1]) for enchantment_id, values in data["enchantments"].items()}
    identifiers = set(identifiers_by_id.values())

    assert identifiers == set(levels)
    assert identifiers == set(numeric_ids)
    assert identifiers_by_id == {enchantment_id: identifier for identifier, enchantment_id in numeric_ids.items()}


def test_reviewed_numeric_enchantment_ids_match_vanilla_world_probe():
    probe_path = ROOT / "tests" / "fixtures" / "enchantment_id_probe_bedrock_1_26_33.json"
    probe = json.loads(probe_path.read_text(encoding="utf-8"))
    reviewed_ids = update_db.load_local_enchantment_numeric_ids()
    observed_ids = {observation["identifier"]: observation["id"] for observation in probe["observations"]}

    assert probe["source"] == "Vanilla Minecraft Bedrock world probe"
    assert probe["last_opened_with_version"] == [1, 26, 33, 1, 0]
    assert observed_ids == {
        "wind_burst": 38,
        "density": 39,
        "breach": 40,
        "lunge": 41,
    }
    assert {identifier: reviewed_ids[identifier] for identifier in observed_ids} == observed_ids
    assert all(observation["list_tag"] == "ench" for observation in probe["observations"])
    assert all(observation["id_tag_type"] == "ShortTag" for observation in probe["observations"])


def test_local_enchantment_max_levels_reject_noncanonical_alias(tmp_path):
    path = tmp_path / "levels.json"
    path.write_text(
        json.dumps({"schema_version": 1, "max_levels": {"binding": 1}}),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="kanonischen Identifier"):
        update_db.load_local_enchantment_max_levels(path)


def test_local_enchantment_numeric_ids_reject_duplicates(tmp_path):
    path = tmp_path / "levels.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "numeric_ids": {"protection": 0, "fire_protection": 0},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="doppelt vergeben"):
        update_db.load_local_enchantment_numeric_ids(path)


class TestMergeEffects(unittest.TestCase):
    def test_aliases_prevent_duplicate_hero_of_the_village(self):
        old = {29: ("Held des Dorfes", "Hero of the Village", "", "")}
        json_ids = ["speed", "village_hero"]
        en_names = {"hero_of_the_village": "Hero of the Village", "speed": "Speed"}
        de_names = {"hero_of_the_village": "Held des Dorfes", "speed": "Geschwindigkeit"}
        numeric_ids = {"hero_of_the_village": 29, "speed": 1}

        merged = update_db.merge_effects(old, json_ids, en_names, de_names, numeric_ids)

        self.assertEqual(merged[29], old[29])
        self.assertEqual(merged[1], ("Geschwindigkeit", "Speed", "", ""))
        hero_entries = [entry for entry in merged.values() if entry[1] == "Hero of the Village"]
        self.assertEqual(len(hero_entries), 1)

    def test_unknown_future_effect_requires_a_reviewed_numeric_id(self):
        with self.assertRaisesRegex(RuntimeError, "future_effect"):
            update_db.merge_effects(
                {},
                ["future_effect"],
                {"future_effect": "Future Effect"},
                {"future_effect": "Zukunftseffekt"},
                {},
            )

    def test_wrong_legacy_effect_position_is_migrated_to_reviewed_id(self):
        old = {99: ("Nautilusatem", "Breath of the Nautilus", "DE", "EN")}

        merged = update_db.merge_effects(
            old,
            ["breath_of_the_nautilus"],
            {},
            {},
            {"breath_of_the_nautilus": 37},
        )

        self.assertNotIn(99, merged)
        self.assertEqual(merged[37], old[99])


def test_bundled_effect_numeric_ids_are_loaded_from_reviewed_database():
    numeric_ids = update_db.load_local_effect_numeric_ids()

    assert numeric_ids["speed"] == 1
    assert numeric_ids["hero_of_the_village"] == 29
    assert numeric_ids["breath_of_the_nautilus"] == 37


class TestSourceVersionHistory(unittest.TestCase):
    """Tests for source version history management."""

    def setUp(self):
        self.tmp = update_db.REPO_ROOT / ".test_history_tmp.json"
        self.orig_path = update_db.SOURCE_VERSION_HISTORY
        update_db.SOURCE_VERSION_HISTORY = self.tmp

    def tearDown(self):
        update_db.SOURCE_VERSION_HISTORY = self.orig_path
        with contextlib.suppress(OSError):
            self.tmp.unlink()

    def test_appends_entry_to_new_file(self):
        entry = {"resource_pack_release": "test", "wiki_revision_id": 1, "generated_at": "now"}
        update_db.append_source_version_history(entry)
        data = json.loads(self.tmp.read_text(encoding="utf-8"))
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["resource_pack_release"], "test")

    def test_appends_second_entry(self):
        entry = {"resource_pack_release": "v1", "generated_at": "t1"}
        update_db.append_source_version_history(entry)
        entry2 = {"resource_pack_release": "v2", "generated_at": "t2"}
        update_db.append_source_version_history(entry2)
        data = json.loads(self.tmp.read_text(encoding="utf-8"))
        self.assertEqual(len(data), 2)
        self.assertEqual(data[1]["resource_pack_release"], "v2")

    def test_survives_corrupted_history_file(self):
        self.tmp.write_text("corrupted{json", encoding="utf-8")
        entry = {"resource_pack_release": "fresh", "generated_at": "now"}
        update_db.append_source_version_history(entry)
        data = json.loads(self.tmp.read_text(encoding="utf-8"))
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["resource_pack_release"], "fresh")


if __name__ == "__main__":
    unittest.main()


class TestModuleGlobals(unittest.TestCase):
    """Tests for module-level constants and helpers used by main()."""

    def test_repo_root_is_absolute(self):
        self.assertTrue(update_db.REPO_ROOT.is_absolute())

    def test_source_version_constants_defined(self):
        self.assertTrue(hasattr(update_db, "SOURCE_VERSION_JSON"))
        self.assertTrue(hasattr(update_db, "SOURCE_VERSION_HISTORY"))

    def test_wiki_url_is_valid(self):
        self.assertTrue(update_db.WIKI_ENCHANTMENTS_URL.startswith("https://"))


def test_ensure_data_paths_seeds_custom_item_db_atomically(monkeypatch, tmp_path):
    bundled = tmp_path / "bundled" / "item_db.json"
    bundled.parent.mkdir()
    bundled.write_text('{"schema_version":1,"items":{}}', encoding="utf-8")
    target = tmp_path / "data" / "item_db.json"
    source_version = tmp_path / "data" / "source_version.json"
    history = tmp_path / "data" / "source_version_history.json"
    cache = tmp_path / "data" / "cache"
    atomic_seed = mock.Mock(wraps=update_db.atomic_seed_file)

    monkeypatch.setattr(update_db, "DEFAULT_ITEM_DB_PATH", bundled)
    monkeypatch.setattr(update_db, "ITEM_DB_PATH", target)
    monkeypatch.setattr(update_db, "SOURCE_VERSION_JSON", source_version)
    monkeypatch.setattr(update_db, "SOURCE_VERSION_HISTORY", history)
    monkeypatch.setattr(update_db, "CACHE_DIR", cache)
    monkeypatch.setattr(update_db, "atomic_seed_file", atomic_seed)

    update_db.ensure_data_paths()

    atomic_seed.assert_called_once_with(bundled, target)
    assert target.read_text(encoding="utf-8") == '{"schema_version":1,"items":{}}'


def test_commit_update_files_rolls_back_item_db_and_metadata_on_metadata_failure(monkeypatch, tmp_path):
    item_db = tmp_path / "item_db.json"
    source_version = tmp_path / "source_version.json"
    history = tmp_path / "source_version_history.json"
    item_db.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "defaults": {"max_stack": 64, "max_damage": 1561, "max_data_value": 32767},
                "stack_limits": {},
                "durability": {},
                "items": {"minecraft:old": ["Alt", "Old"]},
                "effects": {},
                "enchantments": {},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    source_version.write_text('{"version":"old"}\n', encoding="utf-8")
    history.write_text('[{"version":"old"}]\n', encoding="utf-8")
    originals = {path: path.read_bytes() for path in (item_db, source_version, history)}

    monkeypatch.setattr(update_db, "ITEM_DB_PATH", item_db)
    monkeypatch.setattr(update_db, "SOURCE_VERSION_JSON", source_version)
    monkeypatch.setattr(update_db, "SOURCE_VERSION_HISTORY", history)
    monkeypatch.setattr(update_db, "append_source_version_history", mock.Mock(side_effect=OSError("history locked")))

    with pytest.raises(OSError, match="history locked"):
        update_db.commit_update_files(
            {"minecraft:new": ("Neu", "New")},
            {},
            {},
            block_only_items=[],
            block_items=[],
            addable_items=[],
            write_item_db=True,
            source_metadata={"version": "new"},
        )

    assert {path: path.read_bytes() for path in originals} == originals


def test_commit_update_files_records_no_op_verification_without_growing_history(monkeypatch, tmp_path):
    item_db = tmp_path / "item_db.json"
    source_version = tmp_path / "source_version.json"
    history = tmp_path / "source_version_history.json"
    item_db.write_text('{"schema_version":3,"items":{}}\n', encoding="utf-8")
    source_version.write_text('{}\n', encoding="utf-8")
    history.write_text('[{"resource_pack_release":"old"}]\n', encoding="utf-8")
    original_history = history.read_bytes()
    metadata = {
        "resource_pack_release": "current",
        "resource_pack_asset": "current.zip",
        "resource_pack_asset_size": 12,
        "resource_pack_url": "https://example.test/current.zip",
    }

    monkeypatch.setattr(update_db, "ITEM_DB_PATH", item_db)
    monkeypatch.setattr(update_db, "SOURCE_VERSION_JSON", source_version)
    monkeypatch.setattr(update_db, "SOURCE_VERSION_HISTORY", history)
    monkeypatch.setattr(update_db, "utc_now", lambda: "2026-08-04T12:00:00+00:00")

    update_db.commit_update_files(
        {},
        {},
        {},
        block_only_items=None,
        block_items=None,
        addable_items=None,
        write_item_db=False,
        source_metadata=metadata,
        append_source_history=False,
        verify_item_db=True,
    )

    persisted = json.loads(source_version.read_text(encoding="utf-8"))
    receipt = persisted["verification"]
    assert receipt["verified_at"] == "2026-08-04T12:00:00+00:00"
    assert receipt["item_db_sha256"] == update_db.item_db_verification.file_sha256(item_db)
    assert receipt["source_identity_sha256"] == update_db.item_db_verification.source_identity_sha256(metadata)
    assert history.read_bytes() == original_history


def test_update_main_defers_source_metadata_until_after_confirmation():
    source = Path(update_db.__file__).read_text(encoding="utf-8")
    main_source = source[source.index("def main()") :]
    prompt_index = main_source.index("answer = input")
    commit_index = main_source.index("commit_update_files(")

    assert prompt_index < commit_index
    assert "write_source_version(" not in main_source[:commit_index]
    assert "append_source_version_history(" not in main_source[:commit_index]


def test_source_identity_ignores_all_fetch_timestamps():
    old = {
        "resource_pack_release": "same",
        "resource_pack_asset": "same.zip",
        "resource_pack_asset_size": 12,
        "resource_pack_url": "https://example.test/rp.zip",
        "microsoft_item_listing_url": "https://example.test/items",
        "microsoft_item_listing_content_hash": "items-hash",
        "microsoft_item_listing_count": 10,
        "wiki_url": "https://example.test/wiki",
        "wiki_revision_id": 42,
        "wiki_content_hash": "wiki-hash",
        "generated_at": "old",
        "resource_pack_fetched_at": "old",
        "microsoft_item_listing_fetched_at": "old",
        "wiki_fetched_at": "old",
    }
    new = dict(old)
    new.update(
        {
            "generated_at": "new",
            "resource_pack_fetched_at": "new",
            "microsoft_item_listing_fetched_at": "new",
            "wiki_fetched_at": "new",
        }
    )

    assert update_db.source_identity_from_metadata(old) == update_db.source_identity_from_metadata(new)


def test_merge_source_metadata_preserves_sources_not_fetched_by_partial_update(monkeypatch):
    previous = {
        "resource_pack_release": "old-rp",
        "resource_pack_asset": "old.zip",
        "resource_pack_asset_size": 1,
        "resource_pack_url": "https://example.test/old.zip",
        "microsoft_item_listing_url": "https://example.test/items",
        "microsoft_item_listing_content_hash": "items-old",
        "microsoft_item_listing_count": 123,
        "microsoft_item_listing_fetched_at": "items-time",
        "wiki_url": "https://example.test/wiki",
        "wiki_revision_id": 99,
        "wiki_content_hash": "wiki-old",
        "wiki_fetched_at": "wiki-time",
    }
    release = {
        "resource_pack_release": "new-rp",
        "resource_pack_asset": "new.zip",
        "resource_pack_asset_size": 2,
        "resource_pack_url": "https://example.test/new.zip",
        "resource_pack_fetched_at": "new-rp-time",
    }
    monkeypatch.setattr(update_db, "utc_now", lambda: "generated")

    merged = update_db.merge_source_metadata(previous, release_info=release)

    assert merged["resource_pack_release"] == "new-rp"
    assert merged["microsoft_item_listing_content_hash"] == "items-old"
    assert merged["microsoft_item_listing_fetched_at"] == "items-time"
    assert "wiki_revision_id" not in merged
    assert "wiki_fetched_at" not in merged
    assert merged["generated_at"] == "generated"


def test_wiki_stamp_never_outlives_the_run_that_checked_the_wiki(monkeypatch):
    monkeypatch.setattr(update_db, "utc_now", lambda: "generated")
    checked = update_db.merge_source_metadata(
        {},
        wiki_snapshot={
            "wiki_url": "https://example.test/wiki",
            "wiki_revision_id": 7,
            "wiki_content_hash": "wiki-hash",
            "wiki_fetched_at": "wiki-time",
        },
    )

    assert checked["wiki_revision_id"] == 7

    unchecked = update_db.merge_source_metadata(checked)

    assert not [field for field in unchecked if field.startswith("wiki_")]
    assert update_db._valid_source_metadata(unchecked)
    assert update_db.source_identity_from_metadata(unchecked)["wiki_revision_id"] is None


def test_shipped_source_metadata_claims_no_wiki_check():
    shipped = json.loads((ROOT / "source_version.json").read_text(encoding="utf-8"))

    assert not [field for field in shipped if field.startswith("wiki_")]

    for entry in json.loads((ROOT / "source_version_history.json").read_text(encoding="utf-8")):
        assert not [field for field in entry if field.startswith("wiki_")], entry


def test_runtime_network_probe_excludes_the_maintainer_only_wiki_host():
    import main

    expected_runtime_hosts = update_db.ALLOWED_GITHUB_API_HOSTS | update_db.ALLOWED_RESOURCE_PACK_HOSTS | update_db.ALLOWED_MICROSOFT_LEARN_HOSTS

    assert set(main.OUTBOUND_UPDATE_HOSTS) == expected_runtime_hosts
    assert not (set(main.OUTBOUND_UPDATE_HOSTS) & update_db.ALLOWED_WIKI_HOSTS)


def test_effects_only_update_can_commit_new_resource_pack_metadata(monkeypatch, tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    archive = cache_dir / "bedrock_resource_pack.zip"
    with zipfile.ZipFile(archive, "w"):
        pass

    old_effects = {1: ("Tempo", "Speed", "", "")}
    old_version = {
        "resource_pack_release": "old",
        "resource_pack_asset": "old.zip",
        "resource_pack_asset_size": 1,
        "resource_pack_url": "https://example.test/old.zip",
        "wiki_url": "https://example.test/wiki",
        "wiki_revision_id": 7,
        "wiki_content_hash": "wiki",
        "microsoft_item_listing_url": "https://example.test/items",
        "microsoft_item_listing_content_hash": "items",
        "microsoft_item_listing_count": 10,
    }
    release = {
        "resource_pack_release": "new",
        "resource_pack_asset": "new.zip",
        "resource_pack_asset_size": 2,
        "resource_pack_url": "https://example.test/new.zip",
        "resource_pack_fetched_at": "now",
    }
    committed = mock.Mock()
    validate_cached_archive = mock.Mock(wraps=update_db._validate_downloaded_zip)

    monkeypatch.setattr(update_db, "CACHE_DIR", cache_dir)
    monkeypatch.setattr(update_db, "_validate_downloaded_zip", validate_cached_archive)
    monkeypatch.setattr(update_db, "ensure_data_paths", lambda: None)
    monkeypatch.setattr(update_db, "read_release_metadata", lambda: release)
    monkeypatch.setattr(update_db, "read_all_dicts", lambda: ({}, old_effects, {}))
    monkeypatch.setattr(update_db, "parse_json_effects", lambda _zf: [])
    monkeypatch.setattr(update_db, "merge_effects", lambda *_args: old_effects)
    monkeypatch.setattr(update_db, "read_source_version", lambda: old_version)
    monkeypatch.setattr(update_db, "commit_update_files", committed)
    monkeypatch.setattr(update_db, "log", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(update_db, "step", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(update_db, "show_diff", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(sys, "argv", ["update_db.py", "--only", "effects", "--cache", "--force"])

    update_db.main()

    validate_cached_archive.assert_called_once_with(archive)
    assert committed.call_count == 1
    kwargs = committed.call_args.kwargs
    assert kwargs["write_item_db"] is False
    assert kwargs["append_source_history"] is True
    assert kwargs["verify_item_db"] is False
    assert kwargs["source_metadata"]["resource_pack_release"] == "new"
    assert "wiki_revision_id" not in kwargs["source_metadata"]
    assert kwargs["source_metadata"]["microsoft_item_listing_content_hash"] == "items"


def test_main_rejects_changed_review_token_before_processing_sources(monkeypatch):
    monkeypatch.setattr(update_db, "ensure_data_paths", lambda: None)
    monkeypatch.setattr(update_db, "log", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        update_db.item_db_verification,
        "update_review_snapshot",
        lambda **_kwargs: {"token": "b" * 64, "scope": "all"},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["update_db.py", "--cache", "--expected-review-token", "a" * 64, "--force"],
    )

    with pytest.raises(RuntimeError, match="Dry-Run erneut"):
        update_db.main()


def test_full_no_op_update_commits_server_side_verification(monkeypatch, tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    archive = cache_dir / "bedrock_resource_pack.zip"
    with zipfile.ZipFile(archive, "w"):
        pass
    release = {
        "resource_pack_release": "current",
        "resource_pack_asset": "current.zip",
        "resource_pack_asset_size": archive.stat().st_size,
        "resource_pack_url": "https://example.test/current.zip",
        "resource_pack_fetched_at": "release-time",
    }
    item_listing = {
        "microsoft_item_listing_url": "https://example.test/items",
        "microsoft_item_listing_content_hash": "items-hash",
        "microsoft_item_listing_count": 0,
        "microsoft_item_listing_fetched_at": "listing-time",
    }
    old_version = {**release, **item_listing, "generated_at": "old-time"}
    item_components = {component: {} for component in update_db.TRACKED_ITEM_COMPONENTS}
    behavior_source = update_db.build_behavior_item_source(release, {}, {})
    committed = mock.Mock()

    monkeypatch.setattr(update_db, "CACHE_DIR", cache_dir)
    monkeypatch.setattr(update_db, "ensure_data_paths", lambda: None)
    monkeypatch.setattr(update_db, "read_release_metadata", lambda: release)
    monkeypatch.setattr(update_db, "read_all_dicts", lambda: ({}, {}, {}))
    monkeypatch.setattr(update_db, "read_stack_limits", lambda: {})
    monkeypatch.setattr(update_db, "read_durability", lambda: {})
    monkeypatch.setattr(update_db, "read_item_components", lambda: item_components)
    monkeypatch.setattr(update_db, "read_behavior_item_source", lambda: behavior_source)
    monkeypatch.setattr(update_db, "parse_json_item_serialization_aliases", lambda _zf: {})
    monkeypatch.setattr(
        update_db,
        "resolve_microsoft_item_listing_snapshot",
        lambda *, reuse_cached: ({}, item_listing),
    )
    monkeypatch.setattr(update_db, "merge_items", lambda *_args: {})
    monkeypatch.setattr(update_db, "compute_block_only_item_ids", lambda *_args: [])
    monkeypatch.setattr(update_db, "read_block_only_item_ids", lambda: [])
    monkeypatch.setattr(update_db, "compute_addable_item_ids", lambda *_args: [])
    monkeypatch.setattr(update_db, "read_addable_item_ids", lambda: [])
    monkeypatch.setattr(update_db, "parse_json_item_components", lambda _zf: ({}, {}, item_components))
    monkeypatch.setattr(update_db, "merge_item_limits", lambda *_args, **_kwargs: ({}, {}))
    monkeypatch.setattr(update_db, "compute_block_item_ids", lambda *_args: [])
    monkeypatch.setattr(update_db, "read_block_item_ids", lambda: [])
    monkeypatch.setattr(update_db, "parse_json_effects", lambda _zf: [])
    monkeypatch.setattr(update_db, "merge_effects", lambda *_args: {})
    monkeypatch.setattr(update_db, "parse_json_enchantments", lambda _zf: {})
    monkeypatch.setattr(update_db, "load_local_enchantment_max_levels", lambda: {})
    monkeypatch.setattr(update_db, "load_local_enchantment_numeric_ids", lambda: {})
    monkeypatch.setattr(update_db, "optional_wiki_enchantment_check", lambda *_args: {})
    monkeypatch.setattr(update_db, "merge_enchantments", lambda *_args: {})
    monkeypatch.setattr(update_db, "read_source_version", lambda: old_version)
    monkeypatch.setattr(update_db, "commit_update_files", committed)
    monkeypatch.setattr(update_db, "log", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(update_db, "step", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(update_db, "show_diff", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(sys, "argv", ["update_db.py", "--cache", "--force"])

    assert update_db.main() == 0

    committed.assert_called_once()
    kwargs = committed.call_args.kwargs
    assert kwargs["write_item_db"] is False
    assert kwargs["append_source_history"] is False
    assert kwargs["verify_item_db"] is True
    assert kwargs["source_metadata"]["resource_pack_release"] == "current"


def _zip_bytes(filename="file.txt", content=b"ok"):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(filename, content)
    return buffer.getvalue()


class _DownloadResponse:
    def __init__(self, payload, url="https://release-assets.githubusercontent.com/example.zip"):
        self._payload = io.BytesIO(payload)
        self.url = url
        self.headers = {"Content-Length": str(len(payload))}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size=-1):
        return self._payload.read(size)


class _DownloadOpener:
    def __init__(self, payload):
        self.payload = payload
        self.addheaders = []

    def open(self, _url, timeout=None):
        return _DownloadResponse(self.payload)


def test_latest_release_resolution_reuses_only_matching_valid_cache(monkeypatch, tmp_path):
    archive = tmp_path / "bedrock_resource_pack.zip"
    archive.write_bytes(_zip_bytes())
    metadata_path = tmp_path / "release_metadata.json"
    cached = {
        "resource_pack_release": "v1.26.40.5",
        "resource_pack_asset": "bedrock-samples-v1.26.40.5-min.zip",
        "resource_pack_asset_size": archive.stat().st_size,
        "resource_pack_url": "https://release-assets.githubusercontent.com/current.zip",
        "resource_pack_fetched_at": "cached-at",
    }
    metadata_path.write_text(json.dumps(cached), encoding="utf-8")
    latest = {**cached, "resource_pack_fetched_at": "checked-now"}
    download = mock.Mock()
    monkeypatch.setattr(update_db, "RELEASE_METADATA_PATH", metadata_path)
    monkeypatch.setattr(update_db, "get_latest_release_info", lambda: latest)
    monkeypatch.setattr(update_db, "download_latest_rp", download)
    monkeypatch.setattr(update_db, "log", lambda *_args, **_kwargs: None)

    resolved = update_db.resolve_latest_rp(archive)

    assert resolved == cached
    download.assert_not_called()


def test_latest_release_resolution_replaces_stale_cache(monkeypatch, tmp_path):
    archive = tmp_path / "bedrock_resource_pack.zip"
    archive.write_bytes(_zip_bytes())
    metadata_path = tmp_path / "release_metadata.json"
    old = {
        "resource_pack_release": "v1.26.30.5",
        "resource_pack_asset": "bedrock-samples-v1.26.30.5-min.zip",
        "resource_pack_asset_size": archive.stat().st_size,
        "resource_pack_url": "https://release-assets.githubusercontent.com/old.zip",
    }
    latest = {
        "resource_pack_release": "v1.26.40.5",
        "resource_pack_asset": "bedrock-samples-v1.26.40.5-min.zip",
        "resource_pack_asset_size": archive.stat().st_size + 1,
        "resource_pack_url": "https://release-assets.githubusercontent.com/new.zip",
    }
    metadata_path.write_text(json.dumps(old), encoding="utf-8")
    download = mock.Mock(return_value=latest)
    monkeypatch.setattr(update_db, "RELEASE_METADATA_PATH", metadata_path)
    monkeypatch.setattr(update_db, "get_latest_release_info", lambda: latest)
    monkeypatch.setattr(update_db, "download_latest_rp", download)
    monkeypatch.setattr(update_db, "log", lambda *_args, **_kwargs: None)

    assert update_db.resolve_latest_rp(archive) == latest
    download.assert_called_once_with(archive, release_info=latest)


def test_read_release_metadata_rejects_non_object_json(monkeypatch, tmp_path):
    metadata = tmp_path / "release.json"
    metadata.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(update_db, "RELEASE_METADATA_PATH", metadata)

    assert update_db.read_release_metadata() == {}


def test_resource_pack_zip_validation_limits_uncompressed_size(monkeypatch, tmp_path):
    archive_path = tmp_path / "oversized.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("payload.bin", b"1234")

    monkeypatch.setattr(update_db, "MAX_RESOURCE_PACK_MEMBER_BYTES", 10)
    monkeypatch.setattr(update_db, "MAX_RESOURCE_PACK_UNCOMPRESSED_BYTES", 3)

    with pytest.raises(RuntimeError, match="entpackt unerwartet groß"):
        update_db._validate_downloaded_zip(archive_path)


def test_resource_pack_download_failure_preserves_existing_cache(monkeypatch, tmp_path):
    destination = tmp_path / "bedrock_resource_pack.zip"
    old_payload = _zip_bytes("old.txt", b"old")
    new_payload = _zip_bytes("new.txt", b"new")
    destination.write_bytes(old_payload)
    monkeypatch.setattr(update_db.urllib.request, "build_opener", lambda *_handlers: _DownloadOpener(new_payload))

    with pytest.raises(RuntimeError, match="unvollständig"):
        update_db.download_with_progress(
            "https://release-assets.githubusercontent.com/example.zip",
            destination,
            expected_size=len(new_payload) + 1,
        )

    assert destination.read_bytes() == old_payload
    assert not list(tmp_path.glob(".bedrock_resource_pack.zip.*.part"))


def test_resource_pack_metadata_failure_restores_previous_cache(monkeypatch, tmp_path):
    destination = tmp_path / "bedrock_resource_pack.zip"
    old_payload = _zip_bytes("old.txt", b"old")
    new_payload = _zip_bytes("new.txt", b"new")
    destination.write_bytes(old_payload)
    info = {
        "resource_pack_release": "v2",
        "resource_pack_asset": "new.zip",
        "resource_pack_asset_size": len(new_payload),
        "resource_pack_url": "https://release-assets.githubusercontent.com/new.zip",
        "resource_pack_fetched_at": "now",
    }
    monkeypatch.setattr(update_db, "get_latest_release_info", lambda: info)
    monkeypatch.setattr(update_db, "download_with_progress", lambda _url, path, **_kwargs: path.write_bytes(new_payload))
    monkeypatch.setattr(update_db, "write_release_metadata", lambda _info: (_ for _ in ()).throw(OSError("metadata locked")))

    with pytest.raises(OSError, match="metadata locked"):
        update_db.download_latest_rp(destination)

    assert destination.read_bytes() == old_payload
    assert not list(tmp_path.glob(".bedrock_resource_pack.zip.*.candidate"))
    assert not list(tmp_path.glob(".bedrock_resource_pack.zip.*.rollback"))


def test_resource_pack_metadata_failure_removes_first_unmatched_cache(monkeypatch, tmp_path):
    destination = tmp_path / "bedrock_resource_pack.zip"
    new_payload = _zip_bytes("new.txt", b"new")
    info = {
        "resource_pack_release": "v2",
        "resource_pack_asset": "new.zip",
        "resource_pack_asset_size": len(new_payload),
        "resource_pack_url": "https://release-assets.githubusercontent.com/new.zip",
        "resource_pack_fetched_at": "now",
    }
    monkeypatch.setattr(update_db, "get_latest_release_info", lambda: info)
    monkeypatch.setattr(update_db, "download_with_progress", lambda _url, path, **_kwargs: path.write_bytes(new_payload))
    monkeypatch.setattr(update_db, "write_release_metadata", lambda _info: (_ for _ in ()).throw(OSError("metadata locked")))

    with pytest.raises(OSError, match="metadata locked"):
        update_db.download_latest_rp(destination)

    assert not destination.exists()


def test_resource_pack_rollback_failure_keeps_published_cache_visible(monkeypatch, tmp_path):
    destination = tmp_path / "bedrock_resource_pack.zip"
    old_payload = _zip_bytes("old.txt", b"old")
    new_payload = _zip_bytes("new.txt", b"new")
    destination.write_bytes(old_payload)
    info = {
        "resource_pack_release": "v2",
        "resource_pack_asset": "new.zip",
        "resource_pack_asset_size": len(new_payload),
        "resource_pack_url": "https://release-assets.githubusercontent.com/new.zip",
        "resource_pack_fetched_at": "now",
    }
    original_replace = update_db.os.replace

    def fail_rollback_replace(source, target):
        if ".rollback" in str(source) and Path(target) == destination:
            raise PermissionError("rollback locked")
        return original_replace(source, target)

    monkeypatch.setattr(update_db, "get_latest_release_info", lambda: info)
    monkeypatch.setattr(update_db, "download_with_progress", lambda _url, path, **_kwargs: path.write_bytes(new_payload))
    monkeypatch.setattr(update_db, "write_release_metadata", lambda _info: (_ for _ in ()).throw(OSError("metadata locked")))
    monkeypatch.setattr(update_db.os, "replace", fail_rollback_replace)

    with pytest.raises(RuntimeError, match="nicht wiederhergestellt"):
        update_db.download_latest_rp(destination)

    assert destination.read_bytes() == new_payload
    rollback_paths = list(tmp_path.glob(".bedrock_resource_pack.zip.*.rollback"))
    assert len(rollback_paths) == 1
    assert rollback_paths[0].read_bytes() == old_payload


def test_read_release_metadata_rejects_incomplete_object(monkeypatch, tmp_path):
    metadata = tmp_path / "release.json"
    metadata.write_text('{"resource_pack_release":"only-tag"}', encoding="utf-8")
    monkeypatch.setattr(update_db, "RELEASE_METADATA_PATH", metadata)

    assert update_db.read_release_metadata() == {}


def test_read_source_version_rejects_non_object_json(monkeypatch, tmp_path):
    source_version = tmp_path / "source_version.json"
    source_version.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(update_db, "SOURCE_VERSION_JSON", source_version)

    assert update_db.read_source_version() == {}


def test_read_source_version_rejects_wrong_known_field_types(monkeypatch, tmp_path):
    source_version = tmp_path / "source_version.json"
    source_version.write_text('{"resource_pack_asset_size":"large"}', encoding="utf-8")
    monkeypatch.setattr(update_db, "SOURCE_VERSION_JSON", source_version)

    assert update_db.read_source_version() == {}


def test_append_source_version_history_drops_structurally_invalid_entries(monkeypatch, tmp_path):
    history = tmp_path / "source_version_history.json"
    history.write_text(
        '[{"resource_pack_release":"ok"},{"resource_pack_asset_size":"broken"},42]',
        encoding="utf-8",
    )
    monkeypatch.setattr(update_db, "SOURCE_VERSION_HISTORY", history)

    update_db.append_source_version_history({"resource_pack_release": "new"})

    assert json.loads(history.read_text(encoding="utf-8")) == [
        {"resource_pack_release": "ok"},
        {"resource_pack_release": "new"},
    ]


def test_read_all_dicts_skips_invalid_numeric_effect_and_enchantment_entries(monkeypatch, tmp_path):
    item_db = tmp_path / "item_db.json"
    item_db.write_text(
        json.dumps(
            {
                "items": {},
                "effects": {
                    "1": ["Tempo", "Speed", ""],
                    "broken": ["Bad", "Bad", ""],
                },
                "enchantments": {
                    "2": ["Schutz", "Protection", 4, ""],
                    "broken": ["Bad", "Bad", 1, ""],
                    "3": ["Bad", "Bad", "not-a-level", ""],
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(update_db, "ITEM_DB_PATH", item_db)

    _items, effects, enchantments = update_db.read_all_dicts()

    assert effects == {1: ("Tempo", "Speed", "", "")}
    assert enchantments == {2: ("Schutz", "Protection", 4, "")}


def test_write_all_dicts_migrates_effect_descriptions_to_schema_two(monkeypatch, tmp_path):
    item_db = tmp_path / "item_db.json"
    item_db.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "defaults": {},
                "stack_limits": {},
                "durability": {},
                "items": {},
                "effects": {},
                "enchantments": {},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(update_db, "ITEM_DB_PATH", item_db)

    update_db.write_all_dicts(
        {},
        {1: ("Geschwindigkeit", "Speed", "Eigenständiger Text.", "Original wording.")},
        {},
    )

    payload = json.loads(item_db.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 3
    assert payload["effects"]["1"] == ["Geschwindigkeit", "Speed", "Eigenständiger Text.", "Original wording."]


def test_write_all_dicts_updates_component_limits_when_provided(monkeypatch, tmp_path):
    item_db = tmp_path / "item_db.json"
    item_db.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "defaults": {},
                "stack_limits": {"minecraft:legacy": 1},
                "durability": {"minecraft:legacy": 10},
                "items": {},
                "effects": {},
                "enchantments": {},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(update_db, "ITEM_DB_PATH", item_db)

    update_db.write_all_dicts(
        {},
        {},
        {},
        stack_limits={"minecraft:copper_spear": 1, "minecraft:legacy": 1},
        durability={"minecraft:copper_spear": 190, "minecraft:legacy": 10},
        item_components={
            "enchantable": {"minecraft:copper_spear": {"slot": "melee_spear", "value": 13}},
            "wearable": {},
        },
        behavior_item_source={
            "resource_pack_release": "v1.26.30.5",
            "stack_limit_items": ["minecraft:copper_spear"],
            "durability_items": ["minecraft:copper_spear"],
        },
    )

    payload = json.loads(item_db.read_text(encoding="utf-8"))
    assert payload["stack_limits"] == {"minecraft:copper_spear": 1, "minecraft:legacy": 1}
    assert payload["durability"] == {"minecraft:copper_spear": 190, "minecraft:legacy": 10}
    assert payload["item_components"]["enchantable"] == {"minecraft:copper_spear": {"slot": "melee_spear", "value": 13}}
    assert payload["behavior_item_source"] == {
        "resource_pack_release": "v1.26.30.5",
        "stack_limit_items": ["minecraft:copper_spear"],
        "durability_items": ["minecraft:copper_spear"],
    }


def test_get_latest_release_info_rejects_invalid_assets_shape(monkeypatch):
    monkeypatch.setattr(update_db, "fetch_github_json", lambda _url: {"tag_name": "v1", "assets": {}})
    monkeypatch.setattr(update_db, "log", lambda *_args, **_kwargs: None)

    with pytest.raises(RuntimeError, match="Asset-Liste"):
        update_db.get_latest_release_info()


def test_resource_pack_crc_failure_preserves_existing_cache(monkeypatch, tmp_path):
    destination = tmp_path / "bedrock_resource_pack.zip"
    old_payload = _zip_bytes("old.txt", b"old")
    new_payload = _zip_bytes("new.txt", b"new")
    destination.write_bytes(old_payload)
    monkeypatch.setattr(update_db.urllib.request, "build_opener", lambda *_handlers: _DownloadOpener(new_payload))
    monkeypatch.setattr(
        update_db,
        "_validate_downloaded_zip",
        lambda _path: (_ for _ in ()).throw(RuntimeError("CRC failure")),
    )

    with pytest.raises(RuntimeError, match="CRC failure"):
        update_db.download_with_progress(
            "https://release-assets.githubusercontent.com/example.zip",
            destination,
            expected_size=len(new_payload),
        )

    assert destination.read_bytes() == old_payload
    assert not list(tmp_path.glob(".bedrock_resource_pack.zip.*.part"))


def test_update_db_persistent_metadata_tolerates_invalid_utf8(monkeypatch, tmp_path):
    release_metadata = tmp_path / "release.json"
    source_version = tmp_path / "source_version.json"
    history = tmp_path / "source_version_history.json"
    for path in (release_metadata, source_version, history):
        path.write_bytes(b"\xff\xfe")

    monkeypatch.setattr(update_db, "RELEASE_METADATA_PATH", release_metadata)
    monkeypatch.setattr(update_db, "SOURCE_VERSION_JSON", source_version)
    monkeypatch.setattr(update_db, "SOURCE_VERSION_HISTORY", history)

    assert update_db.read_release_metadata() == {}
    assert update_db.read_source_version() == {}
    update_db.append_source_version_history({"resource_pack_release": "new"})
    assert json.loads(history.read_text(encoding="utf-8")) == [{"resource_pack_release": "new"}]


def test_update_db_item_database_reports_invalid_utf8(monkeypatch, tmp_path):
    item_db = tmp_path / "item_db.json"
    item_db.write_bytes(b"\xff\xfe")
    monkeypatch.setattr(update_db, "ITEM_DB_PATH", item_db)

    with pytest.raises(RuntimeError, match="Item-DB JSON ist ungültig"):
        update_db._load_item_db_json()


def test_report_blocked_sections_signals_failure_without_losing_other_sections(capsys):
    """Ein Abschnitt ohne geprüfte IDs darf den Lauf nicht komplett mitreißen.

    Effekte, Verzauberungen und Items sind voneinander unabhängige Blöcke. Wird
    einer davon übersprungen, müssen die übrigen regulär geschrieben werden --
    aber der Exit-Code muss das Überspringen sichtbar machen.
    """

    assert update_db.report_blocked_sections([]) == 0

    blocked = [("EFFECTS", "Lokale numerische IDs fehlen für neue Mojang-Effekte: glowing")]
    assert update_db.report_blocked_sections(blocked) == 1
    output = capsys.readouterr().out
    assert "EFFECTS" in output
    assert "glowing" in output
