"""Corruption tests for the independent trade oracle; these are not BDS runs."""

from copy import deepcopy
import hashlib
import json
import zipfile

import pytest

from mcbe_editor import nbt
from scripts.engine_checks.extended import ENCHANTMENT_IDS
from scripts.engine_checks.protocol import ProbeError
from scripts.engine_checks.villager_trade_tables import load_run_trade_tables, load_trade_tables, stage_samples, trade_enchantment_items, validate_offers


def stack(name, count=1, damage=0, metadata=None):
    result = nbt.CompoundTag({"Name": nbt.StringTag("minecraft:" + name), "Count": nbt.ByteTag(count), "Damage": nbt.ShortTag(damage)})
    if metadata is not None:
        result["tag"] = metadata
    return result


def trade(item, count=1):
    return {
        "wants": [{"item": "minecraft:emerald", "quantity": 1}],
        "gives": [{"item": "minecraft:" + item, "quantity": count}],
        "max_uses": 12,
        "trader_exp": 1,
        "reward_exp": True,
    }


@pytest.fixture
def reference():
    # Deliberately small schema fixture, not a purported copy of Vanilla offers.
    items = ("bread", "apple", "cookie", "cake", "golden_carrot")
    thresholds = (0, 10, 70, 150, 250)
    tiers = [{"total_exp_required": xp, "groups": [{"num_to_select": 1, "trades": [trade(item)]}]} for xp, item in zip(thresholds, items, strict=True)]
    table = {"tiers": tiers, "variant": 1, "path": "trading/economy_trades/farmer_trades.json"}
    recipes = [
        nbt.CompoundTag(
            {
                "tier": nbt.IntTag(tier),
                "buyA": stack("emerald"),
                "sell": stack(item),
                "uses": nbt.IntTag(0),
                "maxUses": nbt.IntTag(12),
                "traderExp": nbt.IntTag(1),
            }
        )
        for tier, item in enumerate(items)
    ]
    root = nbt.CompoundTag(
        {
            "Variant": nbt.IntTag(1),
            "MarkVariant": nbt.IntTag(0),
            "TradeTablePath": nbt.StringTag(table["path"]),
            "TradeTier": nbt.IntTag(0),
            "TradeExperience": nbt.IntTag(0),
            "Offers": nbt.CompoundTag(
                {
                    "Recipes": nbt.ListTag(recipes),
                    "TierExpRequirements": nbt.ListTag([nbt.CompoundTag({str(index): nbt.IntTag(xp)}) for index, xp in enumerate(thresholds)]),
                }
            ),
        }
    )
    return root, {"farmer": table}


def run(reference, **kwargs):
    return validate_offers(*reference[:1], "farmer", reference[1], **kwargs)


def first(reference):
    root, tables = reference
    return root["Offers"]["Recipes"][0], tables["farmer"]["tiers"][0]["groups"][0]["trades"][0]


def test_oracle_checks_all_tiers_and_order_independent_critical_identity(reference):
    before = run(reference)
    assert before["status"] == "pass" and before["recipes"] == 5 and before["tiers"] == 5
    assert before["recipe_structure"] == "pass" and before["metadata"] == "partial"
    assert len(before["critical_signature"]) == 64 and len(before["limitations"]) == 3
    root = reference[0]
    root["Offers"]["Recipes"] = nbt.ListTag(list(reversed(root["Offers"]["Recipes"])))
    assert run(reference)["critical_signature"] == before["critical_signature"]


@pytest.mark.parametrize("native_default", ["wanted_aux", "durability", "banner_type"])
def test_critical_signature_preserves_native_default_equivalence_without_mutation(reference, native_default):
    recipe, template = first(reference)
    if native_default == "wanted_aux":
        recipe["buyA"]["Damage"] = nbt.ShortTag(32767)
    else:
        item = "shears" if native_default == "durability" else "banner"
        template["gives"] = [{"item": "minecraft:" + item}]
        recipe["sell"] = stack(item)
    before = run(reference)["critical_signature"]
    if native_default == "wanted_aux":
        recipe["buyA"]["Damage"] = nbt.ShortTag(0)
    else:
        recipe["sell"]["tag"] = nbt.CompoundTag({"Damage" if native_default == "durability" else "Type": nbt.IntTag(0)})
    encoded = reference[0].save_to()
    assert run(reference)["critical_signature"] == before
    assert reference[0].save_to() == encoded


@pytest.mark.parametrize("change", ["count", "variant", "color"])
def test_critical_signature_detects_other_valid_random_trade_choices(reference, change):
    recipe, template = first(reference)
    if change == "count":
        template["gives"] = [{"item": "minecraft:bread", "quantity": {"min": 1, "max": 2}}]
    elif change == "variant":
        template["gives"] = [{"item": "minecraft:banner", "functions": [{"function": "random_aux_value", "values": {"min": 0, "max": 15}}]}]
        recipe["sell"] = stack("banner", damage=4)
    else:
        template["gives"] = [{"item": "minecraft:leather_chestplate", "functions": [{"function": "random_dye"}]}]
        recipe["sell"] = stack("leather_chestplate", metadata=nbt.CompoundTag({"customColor": nbt.IntTag(0x112233)}))
    before = run(reference)["critical_signature"]
    if change == "count":
        recipe["sell"]["Count"] = nbt.ByteTag(2)
    elif change == "variant":
        recipe["sell"]["Damage"] = nbt.ShortTag(5)
    else:
        recipe["sell"]["tag"]["customColor"] = nbt.IntTag(0x223344)
    assert run(reference)["critical_signature"] != before


@pytest.mark.parametrize(
    "fault",
    [
        "wrong_item",
        "wrong_amount",
        "swap_sides",
        "missing_buy",
        "missing_sell",
        "extra_buy",
        "wrong_tier",
        "missing_recipe",
        "duplicate_recipe",
        "threshold",
        "variant",
        "table",
        "uses",
        "max_uses",
        "xp",
        "item_type",
    ],
)
def test_oracle_rejects_wrong_native_recipe_contents(reference, fault):
    root, _tables = reference
    recipe, _trade = first(reference)
    if fault == "wrong_item":
        recipe["sell"] = stack("diamond_sword")
    elif fault == "wrong_amount":
        recipe["sell"]["Count"] = nbt.ByteTag(64)
    elif fault == "swap_sides":
        recipe["buyA"], recipe["sell"] = recipe["sell"], recipe["buyA"]
    elif fault == "missing_buy":
        del recipe["buyA"]
    elif fault == "missing_sell":
        del recipe["sell"]
    elif fault == "extra_buy":
        recipe["buyB"] = stack("diamond")
    elif fault == "wrong_tier":
        recipe["tier"] = nbt.IntTag(4)
    elif fault == "missing_recipe":
        root["Offers"]["Recipes"].pop()
    elif fault == "duplicate_recipe":
        root["Offers"]["Recipes"].append(deepcopy(recipe))
    elif fault == "threshold":
        root["Offers"]["TierExpRequirements"][2]["2"] = nbt.IntTag(71)
    elif fault == "variant":
        root["Variant"] = nbt.IntTag(4)
    elif fault == "table":
        root["TradeTablePath"] = nbt.StringTag("trading/economy_trades/fletcher_trades.json")
    elif fault == "uses":
        recipe["uses"] = nbt.IntTag(13)
    elif fault == "max_uses":
        recipe["maxUses"] = nbt.IntTag(16)
    elif fault == "xp":
        recipe["traderExp"] = nbt.IntTag(9)
    elif fault == "item_type":
        recipe["sell"]["Count"] = nbt.IntTag(1)
    with pytest.raises(ProbeError):
        run(reference)


@pytest.mark.parametrize("empty", [None, nbt.CompoundTag(), stack("air", 0), stack("", 0)])
def test_absent_or_native_empty_second_slot_is_allowed(reference, empty):
    recipe, _trade = first(reference)
    if empty is not None:
        if empty.get("Name") is not None and empty["Name"].py_data == "minecraft:":
            empty["Name"] = nbt.StringTag("")
        recipe["buyB"] = empty
    assert run(reference)["status"] == "pass"


def test_two_inputs_remain_distinct_from_the_output(reference):
    recipe, template = first(reference)
    template["wants"].append({"item": "minecraft:book", "quantity": 1})
    recipe["buyB"] = stack("book")
    assert run(reference)["status"] == "pass"
    recipe["buyB"] = stack("paper")
    with pytest.raises(ProbeError):
        run(reference)


def test_group_cardinality_and_selection_without_replacement(reference):
    root, tables = reference
    recipe, template = first(reference)
    group = tables["farmer"]["tiers"][0]["groups"][0]
    group["trades"].append(trade("diamond"))
    group["num_to_select"] = 2
    root["Offers"]["Recipes"].append(deepcopy(recipe))
    with pytest.raises(ProbeError, match="duplicate a choice"):
        run(reference)
    root["Offers"]["Recipes"][-1]["sell"] = stack("diamond")
    assert run(reference)["recipes"] == 6


@pytest.mark.parametrize("selection", [-1, 0, None])
def test_all_selection_and_missing_selection_preserve_all_native_candidates(reference, selection):
    root, tables = reference
    recipe, _template = first(reference)
    group = tables["farmer"]["tiers"][0]["groups"][0]
    group["trades"].append(trade("diamond"))
    if selection is None:
        del group["num_to_select"]
    else:
        group["num_to_select"] = selection
    with pytest.raises(ProbeError, match="recipe count"):
        run(reference)
    duplicate = deepcopy(recipe)
    duplicate["sell"] = stack("diamond")
    root["Offers"]["Recipes"].append(duplicate)
    assert run(reference)["recipes"] == 6


@pytest.mark.parametrize("field", ["functions", "filters", "unknown"])
def test_unsupported_unchosen_source_branches_fail_closed(reference, field):
    _root, tables = reference
    extra = trade("diamond")
    extra["gives"][0][field] = (
        [{"function": "invent_magic"}]
        if field == "functions"
        else {"test": "unknown", "subject": "self", "value": True, "operator": "="}
        if field == "filters"
        else True
    )
    tables["farmer"]["tiers"][0]["groups"][0]["trades"].append(extra)
    with pytest.raises(ProbeError):
        run(reference)


def test_biome_filters_reject_a_different_biome_boat(reference):
    recipe, template = first(reference)
    template["gives"] = [
        {
            "choice": [
                {"item": "minecraft:oak_boat", "quantity": 1, "filters": {"test": "is_mark_variant", "subject": "self", "operator": "=", "value": 0}},
                {"item": "minecraft:spruce_boat", "quantity": 1, "filters": {"test": "is_mark_variant", "subject": "self", "operator": "=", "value": 4}},
            ]
        }
    ]
    recipe["sell"] = stack("oak_boat")
    assert run(reference)["status"] == "pass"
    recipe["sell"] = stack("spruce_boat")
    with pytest.raises(ProbeError):
        run(reference)
    reference[0]["MarkVariant"] = nbt.IntTag(4)
    assert run(reference)["status"] == "pass"


def test_dimension_filter_does_not_allow_overworld_only_recipe_in_nether(reference):
    recipe, template = first(reference)
    template["gives"][0]["filters"] = {"test": "in_overworld", "subject": "self", "operator": "=", "value": True}
    assert run(reference)["status"] == "pass"
    with pytest.raises(ProbeError):
        run(reference, dimension=1)


@pytest.mark.parametrize(
    "item,function,good_damage,bad_damage",
    [
        ("banner", {"function": "random_aux_value", "values": {"min": 0, "max": 15}}, 4, 16),
        ("suspicious_stew:0", {"function": "random_aux_value", "values": {"min": 0, "max": 5}}, 2, 6),
        ("arrow", {"function": "set_potion", "id": "nightvision"}, 6, 5),
    ],
)
def test_known_random_aux_and_potion_variants_are_bounded(reference, item, function, good_damage, bad_damage):
    recipe, template = first(reference)
    template["gives"] = [{"item": "minecraft:" + item, "quantity": 1, "functions": [function]}]
    recipe["sell"] = stack(item.split(":")[0], damage=good_damage)
    assert run(reference)["status"] == "pass"
    recipe["sell"]["Damage"] = nbt.ShortTag(bad_damage)
    with pytest.raises(ProbeError):
        run(reference)


@pytest.mark.parametrize("fault", [None, "missing_registry", "overlevel", "duplicate", "wrong_type", "plain_book"])
def test_enchanted_book_requires_native_registry_and_bounded_typed_enchantment(reference, fault):
    recipe, template = first(reference)
    template["gives"] = [
        {
            "item": "minecraft:book",
            "quantity": 1,
            "functions": [{"function": "enchant_book_for_trading", "base_cost": 2, "base_random_cost": 5, "per_level_random_cost": 10, "per_level_cost": 3}],
        }
    ]
    enchantment = nbt.CompoundTag({"id": nbt.ShortTag(26), "lvl": nbt.ShortTag(1)})
    recipe["sell"] = stack("enchanted_book", metadata=nbt.CompoundTag({"ench": nbt.ListTag([enchantment])}))
    recipe["buyA"]["Count"] = nbt.ByteTag(8)
    limits = {"mending": 1}
    if fault == "missing_registry":
        limits = None
    elif fault == "overlevel":
        enchantment["lvl"] = nbt.ShortTag(2)
    elif fault == "duplicate":
        recipe["sell"]["tag"]["ench"].append(deepcopy(enchantment))
    elif fault == "wrong_type":
        enchantment["id"] = nbt.IntTag(26)
    elif fault == "plain_book":
        recipe["sell"]["Name"] = nbt.StringTag("minecraft:book")
    if fault is None:
        assert run(reference, enchantment_limits=limits)["status"] == "pass"
    else:
        with pytest.raises(ProbeError):
            run(reference, enchantment_limits=limits)


def test_unenchanted_offer_cannot_silently_gain_enchantments(reference):
    recipe, _template = first(reference)
    recipe["sell"]["tag"] = nbt.CompoundTag({"ench": nbt.ListTag([nbt.CompoundTag({"id": nbt.ShortTag(26), "lvl": nbt.ShortTag(1)})])})
    with pytest.raises(ProbeError):
        run(reference, enchantment_limits={"mending": 1})


@pytest.mark.parametrize("price,accepted", [(5, False), (6, True), (20, True), (21, False)])
def test_native_gear_price_uses_only_the_matched_outputs_level_range(reference, price, accepted):
    recipe, template = first(reference)
    enchanted = {"item": "minecraft:diamond_chestplate", "functions": [{"function": "enchant_with_levels", "treasure": False, "levels": {"min": 5, "max": 19}}]}
    template["gives"] = [{"choice": [enchanted, {"item": "minecraft:bread"}]}]
    recipe["buyA"]["Count"] = nbt.ByteTag(price)
    recipe["sell"] = stack(
        "diamond_chestplate", metadata=nbt.CompoundTag({"ench": nbt.ListTag([nbt.CompoundTag({"id": nbt.ShortTag(0), "lvl": nbt.ShortTag(1)})])})
    )
    options = {"enchantment_limits": {"protection": 4}, "enchantment_compatibility": {"minecraft:diamond_chestplate": ["protection"]}}
    if accepted:
        assert run(reference, **options)["status"] == "pass"
    else:
        with pytest.raises(ProbeError):
            run(reference, **options)
    # The plain alternative cannot inherit another option's enchantment price.
    recipe["sell"] = stack("bread")
    with pytest.raises(ProbeError):
        run(reference, **options)
    recipe["buyA"]["Count"] = nbt.ByteTag(1)
    assert run(reference, **options)["status"] == "pass"


@pytest.mark.parametrize("name", ["soul_speed", "swift_sneak", "wind_burst"])
def test_native_registry_membership_does_not_allow_non_trading_book_enchantments(reference, name):
    recipe, template = first(reference)
    template["gives"] = [
        {
            "item": "minecraft:book",
            "functions": [{"function": "enchant_book_for_trading", "base_cost": 2, "base_random_cost": 5, "per_level_random_cost": 10, "per_level_cost": 3}],
        }
    ]
    recipe["sell"] = stack(
        "enchanted_book",
        metadata=nbt.CompoundTag({"ench": nbt.ListTag([nbt.CompoundTag({"id": nbt.ShortTag(ENCHANTMENT_IDS[name]), "lvl": nbt.ShortTag(1)})])}),
    )
    with pytest.raises(ProbeError):
        run(reference, enchantment_limits={name: 3})


@pytest.mark.parametrize("fault", [None, "missing_compatibility", "wrong_item_applicability", "treasure"])
def test_enchanted_gear_requires_native_item_applicability_and_non_treasure_selection(reference, fault):
    recipe, template = first(reference)
    template["gives"] = [
        {"item": "minecraft:diamond_chestplate", "functions": [{"function": "enchant_with_levels", "treasure": False, "levels": {"min": 5, "max": 19}}]}
    ]
    name = "riptide" if fault == "wrong_item_applicability" else "mending" if fault == "treasure" else "protection"
    recipe["sell"] = stack(
        "diamond_chestplate",
        metadata=nbt.CompoundTag({"ench": nbt.ListTag([nbt.CompoundTag({"id": nbt.ShortTag(ENCHANTMENT_IDS[name]), "lvl": nbt.ShortTag(1)})])}),
    )
    recipe["buyA"]["Count"] = nbt.ByteTag(6)
    assert trade_enchantment_items(reference[1]) == ["minecraft:diamond_chestplate"]
    compatibility = None if fault == "missing_compatibility" else {"minecraft:diamond_chestplate": ["protection", "mending"]}
    kwargs = {"enchantment_limits": {"protection": 4, "riptide": 3, "mending": 1}, "enchantment_compatibility": compatibility}
    if fault is None:
        assert run(reference, **kwargs)["metadata"] == "partial"
    else:
        with pytest.raises(ProbeError):
            run(reference, **kwargs)


@pytest.mark.parametrize("field", ["Patterns", "display", "ChargedProjectiles", "Items", "unknownContent"])
def test_unexplained_extra_metadata_cannot_pass_as_a_plain_trade_item(reference, field):
    recipe, template = first(reference)
    template["gives"] = [{"item": "minecraft:banner:4"}]
    recipe["sell"] = stack(
        "banner", damage=4, metadata=nbt.CompoundTag({field: nbt.ListTag([nbt.CompoundTag({"Color": nbt.IntTag(0), "Pattern": nbt.StringTag("cre")})])})
    )
    with pytest.raises(ProbeError):
        run(reference)


@pytest.mark.parametrize("banner_type", [nbt.IntTag(0), nbt.IntTag(1), nbt.ByteTag(0), nbt.StringTag("0")])
def test_native_banner_type_is_limited_to_plain_banners(reference, banner_type):
    recipe, template = first(reference)
    template["gives"] = [{"item": "minecraft:banner:4"}]
    recipe["sell"] = stack("banner", damage=4, metadata=nbt.CompoundTag({"Type": banner_type}))
    if isinstance(banner_type, nbt.IntTag) and banner_type.py_data == 0:
        assert run(reference)["status"] == "pass"
    else:
        with pytest.raises(ProbeError):
            run(reference)
    template["gives"] = [{"item": "minecraft:bread"}]
    recipe["sell"] = stack("bread", metadata=nbt.CompoundTag({"Type": banner_type}))
    with pytest.raises(ProbeError):
        run(reference)


def test_plain_items_allow_only_zero_native_durability_and_repair_metadata(reference):
    recipe, _template = first(reference)
    recipe["sell"]["tag"] = nbt.CompoundTag({"Damage": nbt.IntTag(0), "RepairCost": nbt.IntTag(0)})
    assert run(reference)["status"] == "pass"
    recipe["sell"]["tag"]["Damage"] = nbt.IntTag(1)
    with pytest.raises(ProbeError):
        run(reference)


def test_map_checks_uuid_type_and_reports_destination_limit(reference):
    recipe, template = first(reference)
    template["gives"] = [{"item": "minecraft:map", "quantity": 1, "functions": [{"function": "exploration_map", "destination": "monument"}]}]
    recipe["sell"] = stack("filled_map", damage=3, metadata=nbt.CompoundTag({"map_uuid": nbt.LongTag(5432101234567), "map_regenerate": nbt.ByteTag(1)}))
    result = run(reference)
    assert any("destination structures are not checked" in limitation for limitation in result["limitations"])
    recipe["sell"]["tag"]["map_uuid"] = nbt.IntTag(10)
    with pytest.raises(ProbeError):
        run(reference)


@pytest.mark.parametrize("destination,damage", [("monument", 3), ("mansion", 4), ("village_taiga", 8), ("village_savanna", 10), ("trial_chambers", 14)])
def test_map_variant_and_regeneration_flag_match_the_selected_target(reference, destination, damage):
    recipe, template = first(reference)
    template["gives"] = [{"item": "minecraft:map", "functions": [{"function": "exploration_map", "destination": destination}]}]
    recipe["sell"] = stack("filled_map", damage=damage, metadata=nbt.CompoundTag({"map_uuid": nbt.LongTag(7), "map_regenerate": nbt.ByteTag(1)}))
    assert run(reference)["status"] == "pass"
    for invalid in (nbt.ByteTag(2), nbt.IntTag(1)):
        recipe["sell"]["tag"]["map_regenerate"] = invalid
        with pytest.raises(ProbeError):
            run(reference)
    recipe["sell"]["tag"]["map_regenerate"] = nbt.ByteTag(1)
    recipe["sell"]["Damage"] = nbt.ShortTag(4 if damage == 3 else 3)
    with pytest.raises(ProbeError):
        run(reference)


def test_unknown_map_destination_fails_closed(reference):
    _recipe, template = first(reference)
    template["gives"][0]["functions"] = [{"function": "exploration_map", "destination": "invented_structure"}]
    with pytest.raises(ProbeError, match="destination"):
        run(reference)


def test_random_dye_requires_native_color_and_preserves_signature(reference):
    recipe, template = first(reference)
    template["gives"] = [{"item": "minecraft:leather_chestplate", "quantity": 1, "functions": [{"function": "random_dye"}]}]
    recipe["sell"] = stack("leather_chestplate", metadata=nbt.CompoundTag({"customColor": nbt.IntTag(-12827478)}))
    before = run(reference)
    recipe["sell"]["tag"]["customColor"] = nbt.IntTag(-1)
    assert run(reference)["critical_signature"] != before["critical_signature"]
    del recipe["sell"]["tag"]["customColor"]
    with pytest.raises(ProbeError):
        run(reference)


def write_server(tmp_path, reference):
    base = tmp_path / "behavior_packs" / "vanilla"
    (base / "entities").mkdir(parents=True)
    groups = {}
    for variant in range(1, 14):
        profession = "test_" + str(variant)
        path = f"trading/economy_trades/job_{chr(96 + variant)}_trades.json"
        groups[profession] = {"minecraft:variant": {"value": variant}, "minecraft:economy_trade_table": {"table": path, "persist_trades": True}}
        output = base / path
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps({"tiers": reference[1]["farmer"]["tiers"]}))
    (base / "entities/villager_v2.json").write_text(json.dumps({"minecraft:entity": {"component_groups": groups}}))
    return base


def test_loader_uses_exact_bds_files_hashes_and_independent_entity_mapping(tmp_path, reference):
    base = write_server(tmp_path, reference)
    tables = load_trade_tables(tmp_path)
    assert set(tables) == {"test_" + str(index) for index in range(1, 14)}
    assert tables["test_3"]["variant"] == 3
    table = tables["test_3"]
    assert table["sha256"] == hashlib.sha256((tmp_path / table["source"]).read_bytes()).hexdigest()
    assert table["entity_sha256"] == hashlib.sha256((base / "entities/villager_v2.json").read_bytes()).hexdigest()


def test_native_input_wildcard_is_limited_to_unspecified_input_variants(reference):
    recipe, template = first(reference)
    recipe["buyA"]["Damage"] = nbt.ShortTag(32767)
    assert run(reference)["status"] == "pass"
    template["wants"].append({"item": "minecraft:book", "quantity": 1})
    recipe["buyB"] = stack("book", damage=32767)
    assert run(reference)["status"] == "pass"
    template["wants"][1]["item"] = "minecraft:book:0"
    with pytest.raises(ProbeError, match="tier 1"):
        run(reference)
    template["wants"][1]["item"] = "minecraft:book"
    recipe["sell"]["Damage"] = nbt.ShortTag(32767)
    with pytest.raises(ProbeError, match="tier 1"):
        run(reference)


@pytest.mark.parametrize(
    "legacy,modern",
    [
        ("speckled_melon", "glistering_melon_slice"),
        ("fish", "cod"),
        ("cooked_fish", "cooked_cod"),
        ("clownfish", "tropical_fish"),
        ("turtle_shell_piece", "turtle_scute"),
        ("muttonraw", "mutton"),
    ],
)
def test_native_flattened_trade_aliases_keep_item_and_variant_checks(reference, legacy, modern):
    recipe, template = first(reference)
    template["gives"][0]["item"] = "minecraft:" + legacy
    recipe["sell"] = stack(modern)
    assert run(reference)["status"] == "pass"
    recipe["sell"]["Damage"] = nbt.ShortTag(1)
    with pytest.raises(ProbeError):
        run(reference)


def samples_archive(tmp_path, reference, *, fault=None):
    base = write_server(tmp_path / "input", reference)
    archive = tmp_path / "samples.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
        for path in base.rglob("*.json"):
            relative = path.relative_to(base).as_posix()
            name = "bedrock-samples/behavior_pack/" + relative
            if fault == "missing" and relative.endswith("job_a_trades.json"):
                continue
            info = zipfile.ZipInfo(name)
            if fault == "link" and relative.endswith("job_a_trades.json"):
                info.external_attr = 0o120777 << 16
            data = path.read_bytes()
            if fault == "oversized" and relative.endswith("job_a_trades.json"):
                data = b" " * (2 * 1024 * 1024 + 1)
            output.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED)
            if fault == "duplicate" and relative.endswith("job_a_trades.json"):
                with pytest.warns(UserWarning, match="Duplicate name"):
                    output.writestr(name, data)
    return archive, hashlib.sha256(archive.read_bytes()).hexdigest()


def test_packed_bds_uses_explicit_samples_and_revalidates_the_staged_archive(tmp_path, reference):
    archive, digest = samples_archive(tmp_path, reference)
    run_dir = tmp_path / "run"
    packed = run_dir / "server/behavior_packs/vanilla/__brarchive"
    packed.mkdir(parents=True)
    (packed / "entities.brarchive").write_bytes(b"packed BDS resource")
    with pytest.raises(ProbeError, match="--vanilla-samples"):
        load_trade_tables(run_dir / "server")
    report = {"trade_reference": stage_samples(run_dir, archive, digest, "v1.26.60.5")}
    tables = load_run_trade_tables(run_dir, report)
    assert len(tables) == 13
    assert tables["test_1"]["source"].startswith("samples:bedrock-samples/behavior_pack/")
    assert report["trade_reference"] == {"version": "v1.26.60.5", "sha256": digest}
    (run_dir / "vanilla-samples.zip").write_bytes(b"changed")
    with pytest.raises(ProbeError, match="SHA-256 mismatch"):
        load_run_trade_tables(run_dir, report)


@pytest.mark.parametrize("fault", ["missing", "duplicate", "link", "oversized", "digest", "not_zip"])
def test_samples_reference_rejects_invalid_or_ambiguous_sources(tmp_path, reference, fault):
    archive, digest = samples_archive(tmp_path, reference, fault=fault)
    if fault == "digest":
        digest = "0" * 64
    elif fault == "not_zip":
        archive.write_bytes(b"not a zip")
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    with pytest.raises(ProbeError):
        load_trade_tables(tmp_path / "server", samples=archive, expected_hash=digest)


def test_numbered_normal_overlay_wins_and_experimental_overlay_is_ignored(tmp_path, reference):
    base = write_server(tmp_path, reference)
    relative = "trading/economy_trades/job_a_trades.json"
    for name, count in (("vanilla_1.9.0", 2), ("vanilla_1.10.0", 3), ("vanilla_experimental", 63)):
        path = tmp_path / "behavior_packs" / name / relative
        path.parent.mkdir(parents=True)
        data = json.loads((base / relative).read_text())
        data["tiers"][0]["groups"][0]["trades"][0]["gives"][0]["quantity"] = count
        path.write_text("// Reference comments are allowed.\n" + json.dumps(data))
    table = load_trade_tables(tmp_path)["test_1"]
    assert "vanilla_1.10.0/" in table["source"]
    assert table["tiers"][0]["groups"][0]["trades"][0]["gives"][0]["quantity"] == 3


@pytest.mark.parametrize("version", ["1.18.10", "1.26.10", "9.99.99"])
def test_loader_accepts_only_supported_explicit_table_versions(tmp_path, reference, version):
    base = write_server(tmp_path, reference)
    path = base / "trading/economy_trades/job_a_trades.json"
    path.write_text(json.dumps({"format_version": version, **json.loads(path.read_text())}))
    if version == "9.99.99":
        with pytest.raises(ProbeError, match="format version"):
            load_trade_tables(tmp_path)
    else:
        assert len(load_trade_tables(tmp_path)) == 13


@pytest.mark.parametrize("fault", ["missing", "duplicate_json", "linked", "oversized", "escape", "duplicate_variant", "unknown_table_field"])
def test_loader_rejects_incomplete_ambiguous_or_unsupported_bds_sources(tmp_path, reference, fault):
    base = write_server(tmp_path, reference)
    table = base / "trading/economy_trades/job_a_trades.json"
    entity = base / "entities/villager_v2.json"
    if fault == "missing":
        table.unlink()
    elif fault == "duplicate_json":
        table.write_text('{"tiers": [], "tiers": []}')
    elif fault == "linked":
        original = table.with_suffix(".original")
        table.rename(original)
        try:
            table.symlink_to(original)
        except OSError as exc:
            if getattr(exc, "winerror", None) == 1314:
                pytest.skip("Creating symlinks requires Windows Developer Mode or the symlink privilege")
            raise
    elif fault == "oversized":
        table.write_bytes(b" " * (2 * 1024 * 1024 + 1))
    elif fault == "unknown_table_field":
        table.write_text(json.dumps({**json.loads(table.read_text()), "unknown": True}))
    else:
        data = json.loads(entity.read_text())
        group = data["minecraft:entity"]["component_groups"]["test_1"]
        if fault == "escape":
            group["minecraft:economy_trade_table"]["table"] = "../trades.json"
        else:
            group["minecraft:variant"]["value"] = 2
        entity.write_text(json.dumps(data))
    with pytest.raises(ProbeError):
        load_trade_tables(tmp_path)
