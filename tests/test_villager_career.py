"""Behavioral regressions for vanilla career edits and unrelated NBT retention."""

from __future__ import annotations

import copy

import pytest

from mcbe_editor import nbt
from mcbe_editor.bedrock_nbt import LOAD_KWARGS, literal_string_tag
from mcbe_editor.villager_career import CAREER_FIELDS, PROFESSIONS, TIER_EXPERIENCE, career_state, normalize_career_changes
from mcbe_editor.villagers import _active_definitions, load_villager_detail, prepare_villager_changes, scan_villagers
from tests.test_entities import EntityDb, add_actor, entity_tag
from tests.test_villagers import selection


def career_tag(profession="librarian", tier=4, experience=None):
    """Synthetic modern structure for writer/retention tests, not a trade oracle.

    The small recipe set covers the five tier envelopes. It does not claim to
    reproduce a profession's native random trade selection or actual articles.
    """
    variant = [entry[0] for entry in PROFESSIONS].index(profession)
    tag = entity_tag()
    tag["Variant"] = nbt.IntTag(variant)
    tag["IsBaby"] = nbt.ByteTag(0)
    tag["Age"] = nbt.IntTag(0)
    tag["TradeTier"] = nbt.IntTag(tier)
    tag["TradeExperience"] = nbt.IntTag(TIER_EXPERIENCE[tier] if experience is None else experience)
    tag["PreferredProfession"] = nbt.StringTag("" if profession == "unemployed" else profession)
    table = {"weaponsmith": "weapon_smith", "toolsmith": "tool_smith", "leatherworker": "leather_worker", "mason": "stone_mason"}.get(profession, profession)
    tag["TradeTablePath"] = nbt.StringTag("" if profession == "unemployed" else f"trading/economy_trades/{table}_trades.json")
    group = "unskilled" if profession == "unemployed" else profession
    schedule = {"unemployed": "basic_schedule", "farmer": "farmer_schedule", "fisherman": "fisher_schedule", "librarian": "librarian_schedule"}.get(
        profession, "work_schedule"
    )
    behavior = "behavior_peasant" if profession in {"unemployed", "farmer"} else "behavior_non_peasant"
    tag["definitions"] = nbt.ListTag(
        [
            nbt.StringTag(value)
            for value in (
                "+minecraft:villager_v2",
                "+",
                "+adult",
                "+make_and_receive_love",
                "+taiga_villager",
                "+villager_skin_3",
                f"+{group}",
                f"+{behavior}",
                f"+{schedule}",
                "+work_schedule_librarian",
                "+trade_resupply_component_group",
            )
        ]
    )
    if profession != "unemployed":
        tag["Offers"] = nbt.CompoundTag(
            {
                "Recipes": nbt.ListTag(
                    [
                        nbt.CompoundTag(
                            {
                                "tier": nbt.IntTag(index),
                                "uses": nbt.IntTag(3),
                                "maxUses": nbt.IntTag(12),
                                "traderExp": nbt.IntTag(index + 1),
                                "buyA": nbt.CompoundTag({"Name": nbt.StringTag("minecraft:emerald"), "Count": nbt.ByteTag(7)}),
                                "sell": nbt.CompoundTag({"Name": nbt.StringTag("minecraft:book"), "Count": nbt.ByteTag(1)}),
                                "priceMultiplierA": nbt.FloatTag(0.05),
                                "demand": nbt.IntTag(2),
                            }
                        )
                        for index in range(5)
                    ]
                ),
                "TierExpRequirements": nbt.ListTag(
                    [nbt.CompoundTag({str(index): nbt.IntTag(threshold)}) for index, threshold in enumerate((0, 10, 70, 150, 250))]
                ),
            }
        )
    tag["MarkVariant"] = nbt.IntTag(4)
    tag["SkinID"] = nbt.IntTag(3)
    tag["Riches"] = nbt.IntTag(123)
    tag["LowTierCuredDiscount"] = nbt.IntTag(-25)
    tag["HighTierCuredDiscount"] = nbt.IntTag(-20)
    tag["NearbyCuredDiscount"] = nbt.IntTag(-5)
    tag["Willing"] = nbt.ByteTag(1)
    tag["UnknownPassiveState"] = nbt.CompoundTag(
        {
            "Raw": literal_string_tag("␛xff"),
            "Large": nbt.LongTag(9007199254740999),
            "NotFinite": nbt.FloatTag(float("nan")),
        }
    )
    return tag


def career_db(tag=None):
    db = EntityDb()
    key = add_actor(db, career_tag() if tag is None else tag)
    db.records[b"unrelated-world-data"] = b"\xff\x00opaque"
    return db, key


def prepare(db, changes):
    return prepare_villager_changes(db, selection(scan_villagers(db)), {"career": changes})


def test_career_capabilities_are_small_in_scan_and_complete_in_details():
    db, _key = career_db()
    result = scan_villagers(db)
    row = result["villagers"][0]
    assert row["career_editable"] and row["career"]["profession_editable"] and row["career"]["tier_editable"]
    assert "professions" not in row["career"] and "tiers" not in row["career"]
    detail = load_villager_detail(db, row["id"], row["revision"])
    assert len(detail["career"]["professions"]) == 14
    assert [option["minimum_experience"] for option in detail["career"]["tiers"]] == [0, 10, 70, 150, 250]
    assert next(option for option in detail["career"]["professions"] if option["id"] == "librarian")["job_site"] == "Lesepult"


@pytest.mark.parametrize("profession", [entry[0] for entry in PROFESSIONS])
def test_profession_override_updates_all_dependencies_and_preserves_unrelated_bytes(profession):
    db, key = career_db(career_tag("farmer" if profession == "librarian" else "librarian"))
    original_records = dict(db.records)
    source = nbt.load(db.records[key], **LOAD_KWARGS).tag
    plan = prepare(db, {"profession": profession})
    assert plan.summary == {"selected": 1, "changed": 1, "skipped": 0, "unchanged": 0}
    assert plan.rows[0]["kind"] == "career" and plan.rows[0]["warnings"]
    target = nbt.load(plan.writes[key], **LOAD_KWARGS).tag
    expected_variant = [entry[0] for entry in PROFESSIONS].index(profession)
    assert target["Variant"].py_data == expected_variant
    assert target["PreferredProfession"].py_data == ("" if profession == "unemployed" else profession)
    assert target["TradeTier"].py_data == target["TradeExperience"].py_data == 0
    assert "Offers" not in target and plan.rows[0]["after"]["trade_count"] == 0
    expected_table = {"weaponsmith": "weapon_smith", "toolsmith": "tool_smith", "leatherworker": "leather_worker", "mason": "stone_mason"}.get(
        profession, profession
    )
    assert target["TradeTablePath"].py_data == ("" if profession == "unemployed" else f"trading/economy_trades/{expected_table}_trades.json")
    active = _active_definitions(target)
    assert (set(entry[0] for entry in PROFESSIONS[1:]) | {"unskilled", "nitwit"}) & active == {"unskilled" if profession == "unemployed" else profession}
    expected_schedule = {"unemployed": "basic_schedule", "farmer": "farmer_schedule", "fisherman": "fisher_schedule", "librarian": "librarian_schedule"}.get(
        profession, "work_schedule"
    )
    assert expected_schedule in active
    assert "work_schedule_librarian" not in active and "trade_resupply_component_group" not in active
    assert "+" in [value.py_data for value in target["definitions"]]
    assert {"adult", "make_and_receive_love", "taiga_villager", "villager_skin_3"} <= active
    assert set(source) - CAREER_FIELDS == set(target) - CAREER_FIELDS
    for name in set(source) - CAREER_FIELDS:
        assert source[name].save_to() == target[name].save_to(), name
    assert db.records == original_records
    assert set(plan.writes) == {key}
    if profession == "unemployed":
        assert plan.rows[0]["after"]["trade_tier_label"] == "Keine Handelsstufe"


@pytest.mark.parametrize("source_tier", range(5))
@pytest.mark.parametrize("target_tier", range(5))
def test_tier_edits_preserve_offers_prices_usage_and_profession_byte_exact(source_tier, target_tier):
    original_experience = TIER_EXPERIENCE[source_tier] + 2
    db, key = career_db(career_tag(tier=source_tier, experience=original_experience))
    before = nbt.load(db.records[key], **LOAD_KWARGS).tag
    plan = prepare(db, {"trade_tier": target_tier})
    if source_tier == target_tier:
        assert not plan.writes and plan.summary["unchanged"] == 1
        return
    after = nbt.load(plan.writes[key], **LOAD_KWARGS).tag
    assert after["TradeTier"].py_data == target_tier
    assert after["TradeExperience"].py_data == (1 if target_tier == 0 else TIER_EXPERIENCE[target_tier])
    for name in set(before) - {"TradeTier", "TradeExperience"}:
        assert before[name].save_to() == after[name].save_to(), name
    assert plan.rows[0]["after"]["trade_count"] == plan.rows[0]["before"]["trade_count"] == 5


def test_combined_profession_and_master_edit_sets_coherent_new_experience():
    db, key = career_db(career_tag("unemployed", 0, 0))
    row = scan_villagers(db)["villagers"][0]
    assert row["career"]["profession_editable"] and not row["career"]["tier_editable"]
    assert row["career"]["can_set_tier_on_profession_change"]
    plan = prepare(db, {"profession": "mason", "trade_tier": 4})
    after = nbt.load(plan.writes[key], **LOAD_KWARGS).tag
    assert (after["Variant"].py_data, after["TradeTier"].py_data, after["TradeExperience"].py_data) == (13, 4, 250)
    assert "Offers" not in after


def test_unemployed_save_projects_no_trade_tier_and_keeps_wire_default_for_editing():
    db, key = career_db()
    plan = prepare(db, {"profession": "unemployed"})
    db.records.update(plan.writes)
    row = scan_villagers(db)["villagers"][0]
    assert row["profession"]["id"] == "unemployed"
    assert row["trade_tier"] is None and row["trade_tier_label"] == "Keine Handelsstufe"
    assert row["career"]["trade_tier"] == 0
    assert nbt.load(db.records[key], **LOAD_KWARGS).tag["TradeTier"].py_data == 0


def test_nitwit_projects_no_trade_tier_and_remains_protected():
    tag = career_tag("unemployed", 0, 0)
    tag["Variant"] = nbt.IntTag(14)
    tag["definitions"] = nbt.ListTag([nbt.StringTag("+minecraft:villager_v2"), nbt.StringTag("+adult"), nbt.StringTag("+nitwit")])
    db, _key = career_db(tag)
    row = scan_villagers(db)["villagers"][0]
    assert row["profession"]["id"] == "nitwit"
    assert row["trade_tier"] is None and row["trade_tier_label"] == "Keine Handelsstufe"
    assert not row["career_editable"]


@pytest.mark.parametrize("profession", ["unemployed", "farmer"])
def test_same_profession_selection_is_a_noop_even_before_offers_generate(profession):
    tag = career_tag(profession, 0, 0)
    if "Offers" in tag:
        del tag["Offers"]
    db, _key = career_db(tag)
    plan = prepare(db, {"profession": profession})
    assert not plan.writes and plan.summary["unchanged"] == 1


def test_sparse_unemployed_and_missing_adult_groups_follow_vanilla_defaults():
    tag = career_tag("unemployed", 0, 0)
    for name in ("Variant", "TradeTier", "TradeExperience", "PreferredProfession", "TradeTablePath"):
        del tag[name]
    tag["definitions"] = nbt.ListTag([nbt.StringTag(value) for value in ("+minecraft:villager_v2", "+unskilled", "+basic_schedule", "+", "-")])
    db, key = career_db(tag)
    row = scan_villagers(db)["villagers"][0]
    assert row["profession"]["id"] == "unemployed" and row["career_editable"]
    plan = prepare(db, {"profession": "farmer"})
    assert {"adult", "make_and_receive_love", "farmer", "behavior_peasant", "farmer_schedule"} <= _active_definitions(
        nbt.load(plan.writes[key], **LOAD_KWARGS).tag
    )


@pytest.mark.parametrize(
    "changes",
    [
        None,
        {},
        {"career": None},
        {"career": {}},
        {"career": {"unexpected": 1}},
        {"career": {"profession": "nitwit"}},
        {"career": {"profession": 1}},
        {"career": {"trade_tier": True}},
        {"career": {"trade_tier": -1}},
        {"career": {"trade_tier": 5}},
        {"career": {"trade_tier": 1.0}},
        {"career": {"trade_tier": "4"}},
        {"career": {"profession": "unemployed", "trade_tier": 2}},
        {"career": {"profession": "farmer"}, "heal": True},
    ],
)
def test_invalid_requests_are_rejected_before_any_planning(changes):
    with pytest.raises(ValueError):
        normalize_career_changes(changes)


@pytest.mark.parametrize(
    "fault",
    [
        "baby",
        "age_conflict",
        "age_type",
        "unknown_age",
        "nitwit",
        "legacy",
        "orphan",
        "duplicate",
        "dead",
        "zero_health",
        "missing_definitions",
        "base_only",
        "custom_group",
        "conflicting_group",
        "child_group",
        "conversion",
        "bad_variant",
        "bad_tier",
        "bad_experience",
        "experience_mismatch",
        "custom_table",
        "missing_table",
        "bad_preference",
        "conflicting_preference",
        "bad_offers",
        "bad_recipe",
        "custom_thresholds",
        "bad_threshold_types",
    ],
)
def test_unsupported_or_ambiguous_source_stays_read_only(fault):
    tag = career_tag()
    if fault == "baby":
        tag["IsBaby"] = nbt.ByteTag(1)
    elif fault == "age_conflict":
        tag["Age"] = nbt.IntTag(-100)
    elif fault == "age_type":
        tag["Age"] = nbt.FloatTag(0)
    elif fault == "unknown_age":
        del tag["Age"]
        del tag["IsBaby"]
        tag["definitions"] = nbt.ListTag([v for v in tag["definitions"] if v.py_data != "+adult"])
    elif fault == "nitwit":
        tag["Variant"] = nbt.IntTag(14)
    elif fault == "legacy":
        tag["identifier"] = nbt.StringTag("minecraft:villager")
    elif fault == "dead":
        tag["DeathTime"] = nbt.ShortTag(1)
    elif fault == "zero_health":
        tag["Attributes"][0]["Current"] = nbt.FloatTag(0)
    elif fault == "missing_definitions":
        del tag["definitions"]
    elif fault == "base_only":
        tag["definitions"] = nbt.ListTag([nbt.StringTag("+minecraft:villager_v2")])
    elif fault in {"custom_group", "conflicting_group", "child_group", "conversion"}:
        value = {"custom_group": "+addon:custom_trader", "conflicting_group": "+farmer", "child_group": "+child_schedule", "conversion": "+become_zombie"}[
            fault
        ]
        tag["definitions"].append(nbt.StringTag(value))
    elif fault == "bad_variant":
        tag["Variant"] = nbt.ByteTag(5)
    elif fault == "bad_tier":
        tag["TradeTier"] = nbt.FloatTag(4)
    elif fault == "bad_experience":
        tag["TradeExperience"] = nbt.LongTag(250)
    elif fault == "experience_mismatch":
        tag["TradeExperience"] = nbt.IntTag(1)
    elif fault == "custom_table":
        tag["TradeTablePath"] = nbt.StringTag("trading/custom.json")
    elif fault == "missing_table":
        del tag["TradeTablePath"]
    elif fault == "bad_preference":
        tag["PreferredProfession"] = nbt.IntTag(5)
    elif fault == "conflicting_preference":
        tag["PreferredProfession"] = nbt.StringTag("farmer")
    elif fault == "bad_offers":
        tag["Offers"] = nbt.IntTag(1)
    elif fault == "bad_recipe":
        tag["Offers"]["Recipes"][0]["tier"] = nbt.StringTag("0")
    elif fault == "custom_thresholds":
        tag["Offers"]["TierExpRequirements"][1]["1"] = nbt.IntTag(20)
    elif fault == "bad_threshold_types":
        tag["Offers"]["TierExpRequirements"][1]["1"] = nbt.ShortTag(10)
    db = EntityDb()
    add_actor(db, tag, with_index=fault != "orphan")
    if fault == "duplicate":
        add_actor(db, entity_tag(identifier="minecraft:cow"), suffix=b"abcdefgh")
    source = dict(db.records)
    row = scan_villagers(db)["villagers"][0]
    assert not row["career_editable"] and row["career"]["reason"]
    for changes in ({"profession": "farmer"}, {"trade_tier": 1}):
        plan = prepare(db, changes)
        assert not plan.writes and plan.summary["skipped"] == 1
    assert source == db.records


@pytest.mark.parametrize("fault", ["absent", "empty", "partial", "missing_thresholds"])
def test_tier_change_requires_native_generated_offers_but_profession_reset_remains_available(fault):
    tag = career_tag(tier=0, experience=0)
    if fault == "absent":
        del tag["Offers"]
    elif fault == "empty":
        tag["Offers"]["Recipes"] = nbt.ListTag([], nbt.CompoundTag.tag_id)
    elif fault == "partial":
        tag["Offers"]["Recipes"] = nbt.ListTag([tag["Offers"]["Recipes"][0]])
    elif fault == "missing_thresholds":
        del tag["Offers"]["TierExpRequirements"]
    state = career_state(tag, is_baby=False)
    assert state["profession_editable"] and not state["tier_editable"]
    db, _key = career_db(tag)
    assert prepare(db, {"trade_tier": 4}).summary["skipped"] == 1
    assert prepare(db, {"profession": "farmer", "trade_tier": 4}).summary["changed"] == 1


@pytest.mark.parametrize("field", ["buyA", "sell", "buyB"])
@pytest.mark.parametrize("fault", ["scalar", "missing_name", "bad_name_type", "invalid_name", "missing_count", "bad_count_type", "zero_count", "air"])
def test_malformed_trade_stack_blocks_career_changes_even_with_all_five_tiers(field, fault):
    tag = career_tag()
    recipe = tag["Offers"]["Recipes"][0]
    item = nbt.CompoundTag({"Name": nbt.StringTag("minecraft:emerald"), "Count": nbt.ByteTag(1)})
    if fault == "scalar":
        item = nbt.StringTag("not an item stack")
    elif fault == "missing_name":
        del item["Name"]
    elif fault == "bad_name_type":
        item["Name"] = nbt.IntTag(1)
    elif fault == "invalid_name":
        item["Name"] = nbt.StringTag("minecraft:emerald\n")
    elif fault == "missing_count":
        del item["Count"]
    elif fault == "bad_count_type":
        item["Count"] = nbt.IntTag(1)
    elif fault == "zero_count":
        item["Count"] = nbt.ByteTag(0)
    elif fault == "air":
        item["Name"] = nbt.StringTag("minecraft:air")
    recipe[field] = item
    state = career_state(tag, is_baby=False)
    assert not state["profession_editable"] and not state["tier_editable"] and state["reason"]
    db, _key = career_db(tag)
    source = dict(db.records)
    for changes in ({"trade_tier": 1}, {"profession": "farmer"}):
        plan = prepare(db, changes)
        assert plan.summary["skipped"] == 1 and not plan.writes
    assert db.records == source


@pytest.mark.parametrize("field", ["buyA", "sell"])
@pytest.mark.parametrize("fault", ["absent", "empty_compound", "empty_stack"])
def test_missing_mandatory_trade_stack_is_not_a_complete_offer(field, fault):
    tag = career_tag()
    recipe = tag["Offers"]["Recipes"][0]
    if fault == "absent":
        del recipe[field]
    elif fault == "empty_compound":
        recipe[field] = nbt.CompoundTag()
    else:
        recipe[field] = nbt.CompoundTag({"Name": nbt.StringTag(""), "Count": nbt.ByteTag(0)})
    db, _key = career_db(tag)
    plan = prepare(db, {"trade_tier": 1})
    assert plan.summary["skipped"] == 1 and not plan.writes


@pytest.mark.parametrize("representation", ["absent", "empty_compound", "empty_name", "air", "minecraft:air", "item"])
def test_optional_second_trade_input_accepts_native_empty_and_populated_forms(representation):
    tag = career_tag()
    recipe = tag["Offers"]["Recipes"][0]
    if representation == "empty_compound":
        recipe["buyB"] = nbt.CompoundTag()
    elif representation != "absent":
        recipe["buyB"] = nbt.CompoundTag(
            {
                "Name": nbt.StringTag("minecraft:book" if representation == "item" else "" if representation == "empty_name" else representation),
                "Count": nbt.ByteTag(1 if representation == "item" else 0),
                "Damage": nbt.ShortTag(0),
                "WasPickedUp": nbt.ByteTag(0),
            }
        )
    db, key = career_db(tag)
    plan = prepare(db, {"trade_tier": 1})
    after = nbt.load(plan.writes[key], **LOAD_KWARGS).tag
    assert plan.summary["changed"] == 1
    assert after["Offers"].save_to() == tag["Offers"].save_to()


def test_tier_change_preserves_second_input_variants_and_generated_metadata_exactly():
    tag = career_tag()
    recipes = tag["Offers"]["Recipes"]
    recipes[0]["buyB"] = nbt.CompoundTag({"Name": nbt.StringTag("minecraft:book"), "Count": nbt.ByteTag(1), "Damage": nbt.ShortTag(0)})
    recipes[0]["sell"] = nbt.CompoundTag(
        {
            "Name": nbt.StringTag("minecraft:enchanted_book"),
            "Count": nbt.ByteTag(1),
            "Damage": nbt.ShortTag(0),
            "tag": nbt.CompoundTag({"ench": nbt.ListTag([nbt.CompoundTag({"id": nbt.ShortTag(26), "lvl": nbt.ShortTag(1)})])}),
        }
    )
    recipes[1]["sell"] = nbt.CompoundTag({"Name": nbt.StringTag("minecraft:wool"), "Count": nbt.ByteTag(1), "Damage": nbt.ShortTag(14)})
    recipes[2]["sell"] = nbt.CompoundTag(
        {
            "Name": nbt.StringTag("minecraft:filled_map"),
            "Count": nbt.ByteTag(1),
            "Damage": nbt.ShortTag(2),
            "tag": nbt.CompoundTag({"map_uuid": nbt.LongTag(9007199254740999), "map_display_players": nbt.ByteTag(1)}),
        }
    )
    recipes[3]["sell"] = nbt.CompoundTag({"Name": nbt.StringTag("minecraft:arrow"), "Count": nbt.ByteTag(5), "Damage": nbt.ShortTag(22)})
    before = tag["Offers"].save_to()
    db, key = career_db(tag)
    plan = prepare(db, {"trade_tier": 0})
    after = nbt.load(plan.writes[key], **LOAD_KWARGS).tag
    assert after["Offers"].save_to() == before
    assert after["TradeTier"].py_data == 0 and after["TradeExperience"].py_data == 1


def test_stale_selection_aborts_the_entire_career_request():
    db, _key = career_db()
    selected = selection(scan_villagers(db))
    selected[0]["revision"] = "0" * 64
    source = copy.deepcopy(db.records)
    with pytest.raises(ValueError):
        prepare_villager_changes(db, selected, {"career": {"profession": "farmer"}})
    assert db.records == source
