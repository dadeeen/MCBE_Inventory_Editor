"""A tiny, owned conformance pack; no third-party assets or Vanilla overrides."""

from __future__ import annotations

import json
from pathlib import Path

from .cases import append_case, make_cases

ADDON_LIMITS = {"mcbe_probe:stack32": 32, "mcbe_probe:durable": 1}
ADDON_DURABILITY = 9000
DATA_MODULE_ID = "fd9a2f9e-5411-4378-98da-40447a0389a3"


def prepare_addon(pack: Path) -> None:
    directory = pack / "items"
    directory.mkdir(exist_ok=True)
    for item_id, maximum in ADDON_LIMITS.items():
        components = {"minecraft:max_stack_size": maximum, "minecraft:display_name": {"value": "MCBE synthetic conformance item"}}
        if item_id == "mcbe_probe:durable":
            components["minecraft:durability"] = {"max_durability": ADDON_DURABILITY}
        definition = {"format_version": "1.21.90", "minecraft:item": {"description": {"identifier": item_id}, "components": components}}
        (directory / (item_id.split(":")[1] + ".json")).write_text(json.dumps(definition, sort_keys=True) + "\n", encoding="utf-8")


def make_addon_cases(observations: dict) -> list[dict]:
    cases = make_cases(["minecraft:stone"], observations, {"minecraft:stone": 64})
    for item_id, maximum in ADDON_LIMITS.items():
        for mode in ("preserve", "decorate"):
            append_case(cases, observations, item_id, mode, maximum, seeded_metadata=True,
                        damage=ADDON_DURABILITY - 1 if item_id == "mcbe_probe:durable" else 0,
                        name="" if mode == "preserve" else "§bAdd-on Prüflauf 世界",
                        lore=[] if mode == "preserve" else ["Erhalten trotz unbekannter Item-ID"], coverage="controlled-addon")
    return cases
