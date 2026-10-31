"""Display-name fallbacks and persistent per-section updater provenance.

These helpers never infer numeric identities or gameplay values from labels.
The caller supplies already validated, exact identities and reviewed facts.
"""

from __future__ import annotations

from copy import deepcopy


def usable_source_name(value):
    """Return a concrete source label, not an unresolved localization template.

    The updater cannot render percent placeholders in Mojang's language files.
    This check applies to source labels, never to users' own display names.
    """
    return value.strip() if isinstance(value, str) and "%" not in value else ""


def resolve_names(identifier, official, curated=(), existing=(), secondary=None):
    """Resolve German/English labels independently from their shared identity."""
    candidates = {}
    for index, locale in enumerate(("de", "en")):
        candidates[locale] = [
            (usable_source_name(official.get(locale)), "official"),
            (curated[index] if len(curated) > index else "", "curated"),
            (existing[index] if len(existing) > index and existing[index] != identifier else "", "existing"),
            (usable_source_name((secondary or {}).get(locale)), "microsoft"),
        ]
    names, sources = [], []
    for locale, other in (("de", "en"), ("en", "de")):
        own = next(((value, source) for value, source in candidates[locale] if isinstance(value, str) and value.strip()), None)
        foreign = next((value for value, _ in candidates[other] if isinstance(value, str) and value.strip()), "")
        value, source = own or ((foreign, "other_language") if foreign else (identifier, "identifier"))
        # Reusing an unchanged generated fallback must keep its source stable.
        # Otherwise the next identical update changes only provenance to
        # "existing" and misleadingly offers another update.
        if source == "existing":
            if value == usable_source_name((secondary or {}).get(locale)):
                source = "microsoft"
            elif value == foreign:
                source = "other_language"
        names.append(value if source == "identifier" else value[0].upper() + value[1:])
        sources.append(source)
    return tuple(names), tuple(sources)


def coverage(records):
    """Describe available official labels and actual fallback choices."""
    result = {locale: {"total": len(records), "official": 0, "fallbacks": []} for locale in ("de", "en")}
    for identifier, official, sources in sorted(records):
        for index, locale in enumerate(("de", "en")):
            if usable_source_name(official.get(locale)):
                result[locale]["official"] += 1
            else:
                result[locale]["fallbacks"].append({"id": identifier, "source": sources[index]})
    return result


def merge_quality(previous, release, requested, checked, blocked):
    """Retain unselected sections and the provenance of blocked contents."""
    sections = deepcopy(previous.get("sections", {})) if isinstance(previous, dict) and previous.get("schema") == 1 else {}
    for section in requested:
        if section in blocked:
            old = sections.get(section, {})
            sections[section] = {
                "status": "blocked",
                "release": old.get("release"),
                "attempted_release": release,
                "reason": blocked[section],
                "locales": old.get("locales", {}),
            }
        else:
            sections[section] = {
                "status": "checked",
                "release": release,
                "attempted_release": release,
                "locales": checked.get(section, {}),
            }
    return {"schema": 1, "sections": sections}
