import json

import pytest

from mcbe_editor.update_db_report import REPORT_PREFIX, audit_items, build_report, extract_report
from mcbe_editor.item_name_policy import EXPECTED_ITEM_NAME_DIFFERENCES
from scripts.update_db import complete_registry_names


def test_missing_registry_names_use_exact_reviewed_names_without_replacing_existing_names():
    assert complete_registry_names(
        {"minecraft:old": ("Alt", "Old")},
        ["minecraft:old", "minecraft:new", "minecraft:future"],
        {"minecraft:old": ["Anders", "Different"], "minecraft:new": ["Neu", "New"], "minecraft:removed": ["Weg", "Gone"]},
    ) == {
        "minecraft:old": ("Alt", "Old"),
        "minecraft:new": ("Neu", "New"),
    }


@pytest.mark.parametrize(
    "changed,metadata,blocked,state",
    [
        (False, False, [], "current"),
        (False, True, [], "metadata_only"),
        (True, True, [], "available"),
        (True, False, [("effects", "missing IDs")], "incomplete"),
    ],
)
def test_report_classifies_content_metadata_and_partial_failures(changed, metadata, blocked, state):
    report = build_report(
        scope="items", release="v1", sections={"items": ({"a": 1}, {"a": 2} if changed else {"a": 1})}, metadata_changed=metadata, audit=None, blocked=blocked
    )
    assert report["status"] == state
    assert report["scope"] == "items"
    assert report["sections"]["items"] == {"added": 0, "removed": 0, "changed": int(changed)}


def test_audit_does_not_confuse_same_language_names_with_missing_translations():
    audit = audit_items(
        {"minecraft:test": ("Test", "Test")},
        ["minecraft:test"],
        {"minecraft:test": 64},
        {},
        {"de": {"minecraft:test": "Test"}, "en": {"minecraft:test": "Test"}},
        {},
        {},
    )
    assert audit == {"checked_items": 1, "issues": [], "expected_name_differences": []}


def test_audit_separates_errors_source_conflicts_and_preserved_names():
    audit = audit_items(
        {"bad ID": ("", "Name"), "minecraft:test": ("Erhaltener Name", "Test")},
        ["minecraft:missing", "minecraft:test"],
        {"minecraft:test": True},
        {"minecraft:test": 0},
        {"de": {"minecraft:test": "Offizieller Name"}},
        {"stack_limits": {"minecraft:test": 16}},
        {"stack_limits": {"minecraft:test": 64}},
    )
    issues = {issue["code"]: issue for issue in audit["issues"]}
    assert issues["invalid_ids"]["items"] == ["bad ID"]
    assert issues["missing_names"]["severity"] == "error"
    assert issues["missing_entries"]["items"] == ["minecraft:missing"]
    assert issues["invalid_stack_limits"]["severity"] == "error"
    assert issues["invalid_durability"]["severity"] == "error"
    assert issues["source_conflicts_stack_limits"]["severity"] == "warning"
    assert issues["name_differences_de"]["severity"] == "info"
    report = build_report(scope=None, release="v1", sections={}, metadata_changed=False, audit=audit, blocked=[])
    assert report["status"] == "incomplete"


def test_report_protocol_never_interprets_human_log_messages():
    report = {"schema": 1, "status": "metadata_only"}
    log = "Everything current\nAlles aktuell\n" + REPORT_PREFIX + json.dumps(report) + "\nDone\n"
    assert extract_report(log) == ("Everything current\nAlles aktuell\nDone\n", report)
    assert extract_report("Alles aktuell") == ("Alles aktuell", None)
    assert extract_report(REPORT_PREFIX + "bad JSON") == ("", None)


def test_expected_names_are_reported_separately_from_findings():
    items = {key: value[0] for key, value in EXPECTED_ITEM_NAME_DIFFERENCES.items()}
    source = {locale: {key: value[1][index] for key, value in EXPECTED_ITEM_NAME_DIFFERENCES.items()} for index, locale in enumerate(("de", "en"))}
    audit = audit_items(items, [], {}, {}, source, {}, {})
    assert audit["issues"] == []
    assert len(audit["expected_name_differences"]) == 6
    assert {entry["id"] for entry in audit["expected_name_differences"]} == set(items)
    assert {entry["locale"] for entry in audit["expected_name_differences"]} == {"de", "en"}


@pytest.mark.parametrize("item_id", EXPECTED_ITEM_NAME_DIFFERENCES)
@pytest.mark.parametrize("change", ["catalog_de", "catalog_en", "source_de", "source_en", "missing_source", "different_id"])
def test_expected_name_classification_never_masks_new_differences(item_id, change):
    catalog_pair, source_pair = EXPECTED_ITEM_NAME_DIFFERENCES[item_id]
    names = list(catalog_pair)
    source = {"de": {item_id: source_pair[0]}, "en": {item_id: source_pair[1]}}
    if change.startswith("catalog_"):
        names[0 if change.endswith("de") else 1] += " changed"
    elif change.startswith("source_"):
        source[change[-2:]][item_id] += " changed"
    elif change == "missing_source":
        source["de"].clear()
    else:
        item_id = "minecraft:different"
        source = {"de": {item_id: source_pair[0]}, "en": {item_id: source_pair[1]}}
    audit = audit_items({item_id: names}, [], {}, {}, source, {}, {})
    assert audit["expected_name_differences"] == []
    assert any(issue["code"].startswith("name_differences_") for issue in audit["issues"])
