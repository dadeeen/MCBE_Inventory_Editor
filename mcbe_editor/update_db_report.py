"""Language-independent updater results and conservative catalog checks."""

from __future__ import annotations

import json
import re

from .item_name_policy import is_expected_item_name_difference
from .item_registry_policy import is_non_item_lang_key_id

REPORT_PREFIX = "MCBE_UPDATE_REPORT_V1:"


def diff_counts(old: dict, new: dict) -> dict:
    return {
        "added": len(new.keys() - old.keys()),
        "removed": len(old.keys() - new.keys()),
        "changed": sum(old[key] != new[key] for key in old.keys() & new.keys()),
    }


def audit_items(items, addable, stack_limits, durability, source_names, component_limits, reviewed_limits):
    """Check structure and available source facts, without claiming engine equivalence."""
    issues = []
    expected_differences = []

    def issue(code, ids, severity="warning"):
        ids = sorted(set(ids))
        if ids:
            issues.append({"code": code, "severity": severity, "count": len(ids), "items": ids})

    issue("invalid_ids", [key for key in set(items) | set(addable) if not re.fullmatch(r"[a-z0-9_.-]+:[a-z0-9_./-]+", key)], "error")
    issue("missing_names", [key for key, names in items.items() if len(names) != 2 or any(not isinstance(n, str) or not n.strip() for n in names)], "error")
    # Official registry additions may precede both public localization sources.
    # The runtime supplies display-only fallback names for these exact IDs;
    # missing translations must not prevent their registry from being updated.
    issue("missing_entries", set(addable) - items.keys())
    issue("invalid_stack_limits", [key for key, value in stack_limits.items() if type(value) is not int or not 1 <= value <= 127], "error")
    issue("invalid_durability", [key for key, value in durability.items() if type(value) is not int or value <= 0], "error")
    issue("unverified_stack_limits", set(addable) - stack_limits.keys())
    for locale, index in (("de", 0), ("en", 1)):
        source = source_names.get(locale, {})
        differences = [key for key, names in items.items() if len(names) == 2 and key in source and str(names[index]).strip() != source[key].strip()]
        expected = [key for key in differences if is_expected_item_name_difference(key, items[key], source_names)]
        expected_differences.extend({"id": key, "locale": locale, "catalog": items[key][index], "source": source[key]} for key in sorted(expected))
        differences = [key for key in differences if key not in expected]
        issue(
            f"name_differences_{locale}",
            differences,
            "info",
        )
        if differences:
            issues[-1]["comparisons"] = [{"id": key, "catalog": items[key][index], "source": source[key]} for key in sorted(differences)]
    for kind in ("stack_limits", "durability"):
        official = component_limits.get(kind, {})
        reviewed = reviewed_limits.get(kind, {})
        issue(f"source_conflicts_{kind}", [key for key in official.keys() & reviewed.keys() if official[key] != reviewed[key]])
    return {"checked_items": len(items), "issues": issues, "expected_name_differences": expected_differences}


def describe_changes(sections):
    """Explain actual field changes without interpreting localized log output."""
    details = {}
    old_items, new_items = sections.get("items", ({}, {}))
    if "items" in sections:
        details["items"] = {"removed_non_items": sorted(key for key in old_items.keys() - new_items.keys() if is_non_item_lang_key_id(key))}
    if "stack_limits" in sections:
        old, new = sections["stack_limits"]
        details["stack_limits"] = {
            "before_count": len(old),
            "after_count": len(new),
            "added_existing_items": len((new.keys() - old.keys()) & old_items.keys()),
        }
    if "effects" in sections:
        old, new = sections["effects"]
        changed = [key for key in old.keys() & new.keys() if old[key] != new[key]]
        descriptions_only = sum(len(old[key]) == len(new[key]) == 4 and old[key][:2] == new[key][:2] for key in changed)
        details["effects"] = {"descriptions_only": descriptions_only, "other_changes": len(changed) - descriptions_only}
    if "durability" in sections:
        old, new = sections["durability"]
        details["durability"] = {
            "changes": [{"id": key, "before": old[key], "after": new[key]} for key in sorted(old.keys() & new.keys()) if old[key] != new[key]]
        }
    return details


def build_report(*, scope, release, sections, metadata_changed, audit, blocked, previous_release=None):
    counts = {name: diff_counts(old, new) for name, (old, new) in sections.items()}
    changed = any(any(values.values()) for values in counts.values())
    incomplete = bool(blocked) or any(issue["severity"] == "error" for issue in (audit or {}).get("issues", []))
    return {
        "schema": 1,
        "applied": False,
        "scope": scope or "all",
        "release": release,
        "previous_release": previous_release,
        "status": "incomplete" if incomplete else "available" if changed else "metadata_only" if metadata_changed else "current",
        "sections": counts,
        "change_details": describe_changes(sections),
        "audit": audit,
        "blocked": [{"section": section, "reason": reason} for section, reason in blocked],
    }


def extract_report(output: str):
    """Read the explicit JSON record, never infer a result from localized log prose."""
    lines = output.splitlines(keepends=True)
    report = None
    visible = []
    for line in lines:
        if line.startswith(REPORT_PREFIX):
            try:
                candidate = json.loads(line[len(REPORT_PREFIX) :])
                if isinstance(candidate, dict) and candidate.get("schema") == 1:
                    report = candidate
            except (ValueError, TypeError):
                pass
        else:
            visible.append(line)
    return "".join(visible), report
