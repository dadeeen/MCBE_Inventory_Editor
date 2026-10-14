"""Language-independent updater results and conservative catalog checks."""

from __future__ import annotations

import json
import re

from .item_name_policy import is_expected_item_name_difference

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

    issue("invalid_ids", [key for key in items if not re.fullmatch(r"[a-z0-9_.-]+:[a-z0-9_./-]+", key)], "error")
    issue("missing_names", [key for key, names in items.items() if len(names) != 2 or any(not isinstance(n, str) or not n.strip() for n in names)], "error")
    issue("missing_entries", set(addable) - items.keys(), "error")
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


def build_report(*, scope, release, sections, metadata_changed, audit, blocked):
    counts = {name: diff_counts(old, new) for name, (old, new) in sections.items()}
    changed = any(any(values.values()) for values in counts.values())
    incomplete = bool(blocked) or any(issue["severity"] == "error" for issue in (audit or {}).get("issues", []))
    return {
        "schema": 1,
        "scope": scope or "all",
        "release": release,
        "status": "incomplete" if incomplete else "available" if changed else "metadata_only" if metadata_changed else "current",
        "sections": counts,
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
