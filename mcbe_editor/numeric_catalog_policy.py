"""Shared reconciliation of reviewed effect/enchantment identities and fields."""

from __future__ import annotations

import re

from .i18n import t


class NumericCatalogConflictError(ValueError):
    """A readable catalog section has ambiguous identities, not a corrupt file."""

    def __init__(self, reason: str, *, section: str, ids):
        super().__init__(reason)
        self.section = section
        self.ids = sorted(set(ids))

    def details(self) -> dict:
        return {"reason": str(self), "ids": self.ids}


def numeric_catalog_conflict_messages(conflicts: dict) -> list[str]:
    """Translate diagnostics at the request boundary, not during catalog loading."""
    labels = {"effects": t("Effekte"), "enchantments": t("Verzauberungen")}
    return [
        t(
            "{section}: {reason} Betroffene IDs: {ids}. Bearbeitung gesperrt; vorhandene Daten bleiben erhalten.",
            section=labels[section],
            reason=t(details["reason"]),
            ids=", ".join(map(str, details["ids"])),
        )
        for section, details in conflicts.items()
        if section in labels
    ]


def canonical_numeric_name(value: str) -> str:
    normalized = str(value).replace("minecraft:", "", 1).strip().lower().replace(" ", "_").replace("-", "_")
    normalized = re.sub(r"_+", "_", normalized)
    return {
        "village_hero": "hero_of_the_village",
        "binding": "binding_curse",
        "curse_of_binding": "binding_curse",
        "bow_infinity": "infinity",
        "vanishing": "vanishing_curse",
        "curse_of_vanishing": "vanishing_curse",
    }.get(normalized, normalized)


def reconcile_numeric_catalog(current: dict, reviewed: dict, *, kind: str, identifiers: dict | None = None) -> dict:
    """Keep names/custom enchantment descriptions; enforce reviewed IDs and facts.

    Recognized old names can move to their reviewed ID. A custom name at an
    already-correct ID stays. Unknown entries outside the reviewed IDs stay.
    Ambiguous matches or occupied migration destinations fail without mutation.
    """
    if kind not in ("effects", "enchantments"):
        raise ValueError("Unknown numeric catalog kind")
    owners = dict(identifiers or {})
    for numeric_id, values in reviewed.items():
        for name in values[:2]:
            key = canonical_numeric_name(name)
            if not key:
                continue
            if key in owners and owners[key] != numeric_id:
                raise NumericCatalogConflictError("Mehrdeutige Namen im geprüften numerischen Katalog.", section=kind, ids=[owners[key], numeric_id])
            owners[key] = numeric_id
    identified = {}
    for numeric_id, values in current.items():
        targets = {owners[key] for name in values[:2] if (key := canonical_numeric_name(name)) in owners}
        if len(targets) > 1:
            raise NumericCatalogConflictError("Widersprüchliche Namen im numerischen Katalog.", section=kind, ids=[numeric_id, *targets])
        identified[numeric_id] = next(iter(targets)) if targets else numeric_id
    assigned = {}
    for old_id, target_id in identified.items():
        if target_id in assigned:
            raise NumericCatalogConflictError("Kollidierende Einträge im numerischen Katalog.", section=kind, ids=[assigned[target_id], old_id, target_id])
        assigned[target_id] = old_id
    result = {identified[key]: tuple(value) for key, value in current.items()}
    for numeric_id, values in reviewed.items():
        old = result.get(numeric_id)
        if old is None:
            result[numeric_id] = tuple(values)
        elif kind == "effects":
            result[numeric_id] = (*old[:2], *values[2:])
        else:
            result[numeric_id] = (*old[:2], values[2], *old[3:])
    return result
