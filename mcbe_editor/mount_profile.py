"""Horse profile helpers for experimental mount creation.

The first create path used fixed values copied from a working synthetic horse.
This module keeps the next step isolated: validated, vanilla-like horse values
that can later be wired into the write path and UI without spreading magic
numbers across the route/controller code.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

PROFILE_MODE_RANDOM_LIKE_GAME = "random_like_game"
PROFILE_MODE_CUSTOM = "custom"
PROFILE_MODES = frozenset({PROFILE_MODE_RANDOM_LIKE_GAME, PROFILE_MODE_CUSTOM})

# Conservative vanilla-like ranges for adult Minecraft horses.  Keep these as
# gameplay-facing boundaries, not NBT technical maxima.  The NBT attributes still
# use very large DefaultMax/Max values where Bedrock does, but user-editable
# values should stay inside normal in-game ranges.
HORSE_HEALTH_MIN = 15.0
HORSE_HEALTH_MAX = 30.0
HORSE_MOVEMENT_MIN = 0.1125
HORSE_MOVEMENT_MAX = 0.3375
HORSE_JUMP_STRENGTH_MIN = 0.4
HORSE_JUMP_STRENGTH_MAX = 1.0
HORSE_COLOR_MIN = 0
HORSE_COLOR_MAX = 6
HORSE_MARK_VARIANT_MIN = 0
HORSE_MARK_VARIANT_MAX = 4
# Taming progress. Minecraft rolls this per specimen: 41 scanned horse, donkey
# and mule records spread over 0..98 with no repeated pattern.
HORSE_TEMPER_MIN = 0
HORSE_TEMPER_MAX = 99

DEFAULT_HORSE_HEALTH = 25.0
DEFAULT_HORSE_MOVEMENT = 0.17499999701976776
DEFAULT_HORSE_JUMP_STRENGTH = 0.5
DEFAULT_HORSE_COLOR = 0
DEFAULT_HORSE_MARK_VARIANT = 1
DEFAULT_HORSE_TEMPER = 62


@dataclass(frozen=True)
class HorseProfile:
    mode: str
    health: float
    movement: float
    jump_strength: float
    color: int
    mark_variant: int
    temper: int


def _float_between(value: Any, *, field_name: str, default: float, minimum: float, maximum: float) -> float:
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        raise ValueError(f"{field_name} muss eine Zahl sein.")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} muss eine Zahl sein.") from exc
    if result != result or result in (float("inf"), float("-inf")):
        raise ValueError(f"{field_name} muss endlich sein.")
    if not minimum <= result <= maximum:
        raise ValueError(f"{field_name} muss zwischen {minimum:g} und {maximum:g} liegen.")
    return float(result)


def _int_between(value: Any, *, field_name: str, default: int, minimum: int, maximum: int) -> int:
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        raise ValueError(f"{field_name} muss eine Ganzzahl sein.")
    if isinstance(value, float) and not value.is_integer():
        raise ValueError(f"{field_name} muss eine Ganzzahl sein.")
    try:
        result = int(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} muss eine Ganzzahl sein.") from exc
    if not minimum <= result <= maximum:
        raise ValueError(f"{field_name} muss zwischen {minimum} und {maximum} liegen.")
    return result


def default_horse_profile() -> HorseProfile:
    return HorseProfile(
        mode=PROFILE_MODE_RANDOM_LIKE_GAME,
        health=DEFAULT_HORSE_HEALTH,
        movement=DEFAULT_HORSE_MOVEMENT,
        jump_strength=DEFAULT_HORSE_JUMP_STRENGTH,
        color=DEFAULT_HORSE_COLOR,
        mark_variant=DEFAULT_HORSE_MARK_VARIANT,
        temper=DEFAULT_HORSE_TEMPER,
    )


def random_like_game_horse_profile(seed: Any = None) -> HorseProfile:
    rng = random.Random(seed)
    return HorseProfile(
        mode=PROFILE_MODE_RANDOM_LIKE_GAME,
        health=float(rng.randint(int(HORSE_HEALTH_MIN), int(HORSE_HEALTH_MAX))),
        movement=rng.uniform(HORSE_MOVEMENT_MIN, HORSE_MOVEMENT_MAX),
        jump_strength=rng.uniform(HORSE_JUMP_STRENGTH_MIN, HORSE_JUMP_STRENGTH_MAX),
        color=rng.randint(HORSE_COLOR_MIN, HORSE_COLOR_MAX),
        mark_variant=rng.randint(HORSE_MARK_VARIANT_MIN, HORSE_MARK_VARIANT_MAX),
        # Drawn from the same seeded rng as everything else, so one seed still
        # reproduces the whole record.
        temper=rng.randint(HORSE_TEMPER_MIN, HORSE_TEMPER_MAX),
    )


def normalize_horse_profile(value: Any = None) -> HorseProfile:
    if value in (None, ""):
        return default_horse_profile()
    if isinstance(value, HorseProfile):
        return value
    if not isinstance(value, dict):
        raise ValueError("horse_profile muss ein Objekt sein.")
    mode = str(value.get("mode") or PROFILE_MODE_RANDOM_LIKE_GAME).strip() or PROFILE_MODE_RANDOM_LIKE_GAME
    if mode not in PROFILE_MODES:
        raise ValueError(f"Ungültiger Horse-Profilmodus: {mode}")
    if mode == PROFILE_MODE_RANDOM_LIKE_GAME:
        seed = value.get("seed")
        return random_like_game_horse_profile(seed=seed) if seed not in (None, "") else default_horse_profile()
    return HorseProfile(
        mode=PROFILE_MODE_CUSTOM,
        health=_float_between(value.get("health"), field_name="Leben", default=DEFAULT_HORSE_HEALTH, minimum=HORSE_HEALTH_MIN, maximum=HORSE_HEALTH_MAX),
        movement=_float_between(
            value.get("movement"), field_name="Bewegungsgeschwindigkeit", default=DEFAULT_HORSE_MOVEMENT, minimum=HORSE_MOVEMENT_MIN, maximum=HORSE_MOVEMENT_MAX
        ),
        jump_strength=_float_between(
            value.get("jump_strength"),
            field_name="Sprungstärke",
            default=DEFAULT_HORSE_JUMP_STRENGTH,
            minimum=HORSE_JUMP_STRENGTH_MIN,
            maximum=HORSE_JUMP_STRENGTH_MAX,
        ),
        color=_int_between(value.get("color"), field_name="Farbe", default=DEFAULT_HORSE_COLOR, minimum=HORSE_COLOR_MIN, maximum=HORSE_COLOR_MAX),
        mark_variant=_int_between(
            value.get("mark_variant"),
            field_name="Markierung",
            default=DEFAULT_HORSE_MARK_VARIANT,
            minimum=HORSE_MARK_VARIANT_MIN,
            maximum=HORSE_MARK_VARIANT_MAX,
        ),
        temper=_int_between(
            value.get("temper"),
            field_name="Zähmfortschritt",
            default=DEFAULT_HORSE_TEMPER,
            minimum=HORSE_TEMPER_MIN,
            maximum=HORSE_TEMPER_MAX,
        ),
    )


def horse_profile_attribute_values(profile: HorseProfile) -> dict[str, float]:
    return {
        "minecraft:health": float(profile.health),
        "minecraft:movement": float(profile.movement),
        "minecraft:horse.jump_strength": float(profile.jump_strength),
    }


def horse_profile_summary(profile: HorseProfile) -> dict[str, Any]:
    return {
        "mode": profile.mode,
        "health": profile.health,
        "movement": profile.movement,
        "jump_strength": profile.jump_strength,
        "color": profile.color,
        "mark_variant": profile.mark_variant,
        "temper": profile.temper,
    }
