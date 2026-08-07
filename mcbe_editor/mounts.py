"""Preview helpers for experimental mount creation."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .i18n import t

MOUNT_TYPE_DEFINITIONS: dict[str, dict[str, Any]] = {
    "minecraft:horse": {
        "label": "Pferd",
        "category": "classic",
        "collision_width": 1.4,
        "collision_height": 1.6,
        "notes": ["Create ist im Spiel validiert; Farben/Markierungen folgen jetzt echten Speicher-Records (Variant/definitions)."],
        "create_available": True,
    },
    "minecraft:donkey": {
        "label": "Esel",
        "category": "classic",
        "collision_width": 1.4,
        "collision_height": 1.6,
        "notes": [
            "Create nach Record-Evidenz aktiviert (Tempo 0,175 · Sprung 0,5 · Leben zufällig, optional gezähmt); In-Game-Load-Test bestanden (2026-07-10)."
        ],
        "create_available": True,
    },
    "minecraft:mule": {
        "label": "Maultier",
        "category": "classic",
        "collision_width": 1.4,
        "collision_height": 1.6,
        "notes": [
            "Create nach Record-Evidenz aktiviert (Tempo 0,175 · Sprung 0,5 · Leben zufällig, optional gezähmt); In-Game-Load-Test bestanden (2026-07-10)."
        ],
        "create_available": True,
    },
    "minecraft:camel": {
        "label": "Kamel",
        "category": "classic",
        "collision_width": 1.7,
        "collision_height": 2.375,
        "notes": [
            "Kamel-Erzeugung mit 32 Leben, Tempo 0,09 und den erwarteten Zusatzdaten wurde im Spiel geladen und gespeichert; die Funktion bleibt experimentell."
        ],
        "create_available": True,
    },
    "minecraft:skeleton_horse": {
        "label": "Skelettpferd",
        "category": "classic",
        "collision_width": 1.4,
        "collision_height": 1.6,
        "notes": [
            "Create nach Record-Evidenz aktiviert (15 Leben · Tempo 0,2 · Sprung zufällig · zahm, ohne Temper); In-Game-Load-Test bestanden (2026-07-10)."
        ],
        "create_available": True,
    },
}
SUPPORTED_MOUNT_TYPES = frozenset(MOUNT_TYPE_DEFINITIONS)
DEFAULT_MOUNT_TYPE = "minecraft:horse"
OVERWORLD_DIMENSION_ID = 0

# Bedrock stores the player Pos around body/eye height, while entity Pos for a
# horse created by the game is the feet/bottom position.  The observed delta in
# the test world was 68.62 -> 67.00, so preview/create candidates compensate by
# this amount until real block-height probing is available.
ENTITY_FOOT_Y_FROM_PLAYER_Y = -1.62

MIN_PLACEMENT_RADIUS = 2
DEFAULT_PLACEMENT_RADIUS = 6
MAX_PLACEMENT_RADIUS = 16
MAX_PLACEMENT_CANDIDATES = 4


@dataclass(frozen=True)
class PlayerReference:
    player_key: str
    player_label: str
    position: dict[str, float]
    dimension_id: int | None
    rotation: list[float] | None = None
    yaw: float | None = None


def mount_type_options() -> list[dict[str, Any]]:
    return [
        {
            "id": mount_type,
            "label": t(str(definition["label"])),
            "category": definition.get("category", "classic"),
            "notes": [t(str(note)) for note in definition.get("notes", [])],
            "create_available": bool(definition.get("create_available")),
        }
        for mount_type, definition in MOUNT_TYPE_DEFINITIONS.items()
    ]


def normalize_mount_type(value: str | None) -> str:
    mount_type = (value or DEFAULT_MOUNT_TYPE).strip() or DEFAULT_MOUNT_TYPE
    if mount_type not in SUPPORTED_MOUNT_TYPES:
        supported = ", ".join(sorted(SUPPORTED_MOUNT_TYPES))
        raise ValueError(t("Mount-Typ '{type}' wird noch nicht unterstützt. Unterstützt: {supported}.", type=mount_type, supported=supported))
    return mount_type


def normalize_placement_radius(value: Any) -> int:
    if value in (None, ""):
        return DEFAULT_PLACEMENT_RADIUS
    if isinstance(value, bool):
        raise ValueError(t("placement_radius muss eine Zahl sein."))
    try:
        radius = int(round(float(value)))
    except (TypeError, ValueError) as exc:
        raise ValueError(t("placement_radius muss eine Zahl sein.")) from exc
    if not MIN_PLACEMENT_RADIUS <= radius <= MAX_PLACEMENT_RADIUS:
        raise ValueError(
            t(
                "placement_radius muss zwischen {min} und {max} liegen.",
                min=MIN_PLACEMENT_RADIUS,
                max=MAX_PLACEMENT_RADIUS,
            )
        )
    return radius


def mount_type_label(mount_type: str) -> str:
    return t(str(MOUNT_TYPE_DEFINITIONS[mount_type]["label"]))


def mount_type_notes(mount_type: str) -> list[str]:
    return [t(str(note)) for note in MOUNT_TYPE_DEFINITIONS[mount_type].get("notes", [])]


def mount_create_available(mount_type: str) -> bool:
    return bool(MOUNT_TYPE_DEFINITIONS[mount_type].get("create_available"))


def mount_collision_width(mount_type: str) -> float:
    return float(MOUNT_TYPE_DEFINITIONS[mount_type]["collision_width"])


def mount_collision_height(mount_type: str) -> float:
    return float(MOUNT_TYPE_DEFINITIONS[mount_type]["collision_height"])


def dimension_allows_create(dimension_id: int | None) -> bool:
    return dimension_id == OVERWORLD_DIMENSION_ID


def _float_value(value: Any, field_name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(t("{field} muss eine Zahl sein.", field=field_name))
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(t("{field} muss eine Zahl sein.", field=field_name)) from exc
    if not math.isfinite(result):
        raise ValueError(t("{field} muss endlich sein.", field=field_name))
    return result


def _position_from_stats(stats: dict[str, Any]) -> dict[str, float]:
    pos = stats.get("pos")
    if not isinstance(pos, list) or len(pos) < 3:
        raise ValueError(t("Spielerposition fehlt oder ist unvollständig. Bitte Spieler neu laden."))
    return {
        "x": _float_value(pos[0], "Position X"),
        "y": _float_value(pos[1], "Position Y"),
        "z": _float_value(pos[2], "Position Z"),
    }


def _rotation_from_stats(stats: dict[str, Any]) -> list[float] | None:
    rotation = stats.get("rotation") or stats.get("Rotation")
    if not isinstance(rotation, list) or not rotation:
        return None
    values: list[float] = []
    for index, value in enumerate(rotation[:2]):
        values.append(_float_value(value, f"Rotation {index}"))
    return values or None


def _yaw_from_rotation(rotation: list[float] | None) -> float | None:
    if not rotation:
        return None
    # Bedrock entity/player Rotation is treated as [yaw, pitch] by the current
    # diagnostics and writer.  Keep this optional: when unavailable, candidates
    # fall back to a cardinal ring around the player.
    return rotation[0]


def _dimension_from_stats(stats: dict[str, Any]) -> int | None:
    for key in ("dimension_id", "DimensionId", "dimension"):
        value = stats.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
    return None


def _player_label(snapshot: dict[str, Any], player_key: str) -> str:
    player = snapshot.get("player") if isinstance(snapshot, dict) else None
    if isinstance(player, dict):
        for key in ("label", "name", "display_name", "player_name"):
            value = player.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return player_key


def player_reference_from_snapshot(snapshot: dict[str, Any], player_key: str) -> PlayerReference:
    stats = snapshot.get("stats") if isinstance(snapshot, dict) else None
    if not isinstance(stats, dict):
        raise ValueError(t("Spieler-Stats fehlen. Bitte Spieler neu laden."))
    rotation = _rotation_from_stats(stats)
    return PlayerReference(
        player_key=player_key,
        player_label=_player_label(snapshot, player_key),
        position=_position_from_stats(stats),
        dimension_id=_dimension_from_stats(stats),
        rotation=rotation,
        yaw=_yaw_from_rotation(rotation),
    )


def _candidate_position(base: dict[str, float], dx: float, dy: float, dz: float) -> dict[str, float]:
    return {
        "x": round(base["x"] + dx, 3),
        "y": round(base["y"] + ENTITY_FOOT_Y_FROM_PLAYER_Y + dy, 3),
        "z": round(base["z"] + dz, 3),
    }


def _normalized_preferred_offset(value: Any) -> tuple[float, float, float] | None:
    if value in (None, ""):
        return None
    if not isinstance(value, dict):
        raise ValueError(t("preferred_offset muss ein Objekt mit x/y/z sein."))
    dx = _float_value(value.get("x", 0), "preferred_offset.x")
    dy = _float_value(value.get("y", 0), "preferred_offset.y")
    dz = _float_value(value.get("z", 0), "preferred_offset.z")
    if abs(dx) > MAX_PLACEMENT_RADIUS or abs(dy) > 8 or abs(dz) > MAX_PLACEMENT_RADIUS:
        raise ValueError(t("preferred_offset ist zu groß. Erlaubt sind maximal {limit} Blöcke horizontal und 8 Blöcke vertikal.", limit=MAX_PLACEMENT_RADIUS))
    return dx, dy, dz


def _ceil_away_from_zero(value: float) -> int:
    return int(math.copysign(math.ceil(abs(value)), value)) if value else 0


def horizontal_block_offset(dx: float, dz: float, distance: int, minimum: int = MIN_PLACEMENT_RADIUS) -> tuple[int, int]:
    """Snap a horizontal direction to the nearest whole blocks, never inside ``minimum``.

    Offsets are whole blocks, so a diagonal cannot hit an arbitrary distance
    exactly.  Nearest rounding keeps the candidate closest to the requested
    distance and inside the search radius the user chose -- but it also shortens
    diagonals, and at the inner end that breaks the floor: a 45° direction at
    distance 2 rounds to (1, 1), which is 1.41 blocks and closer to the player
    than MIN_PLACEMENT_RADIUS allows.

    Only in that case are the components rounded away from zero instead, which
    can only lengthen the vector.  Overshooting the requested distance is then
    unavoidable (no integer diagonal sits between 1.41 and 2.83), so it is
    confined to the one step where the alternative would violate the floor.
    """
    horizontal = math.hypot(dx, dz)
    if horizontal <= 0:
        return 0, 0
    # max(): keeps the guarantee total even if a caller ever asks for less than
    # the floor, instead of silently returning a too-close offset.
    reach = max(float(distance), float(minimum))
    exact_x = dx / horizontal * reach
    exact_z = dz / horizontal * reach
    rounded_x, rounded_z = int(round(exact_x)), int(round(exact_z))
    if math.hypot(rounded_x, rounded_z) >= minimum:
        return rounded_x, rounded_z
    return _ceil_away_from_zero(exact_x), _ceil_away_from_zero(exact_z)


def _offset_from_yaw(yaw: float, distance: int, *, yaw_delta: float = 0.0) -> tuple[float, float, float]:
    radians = math.radians(yaw + yaw_delta)
    dx, dz = horizontal_block_offset(-math.sin(radians), math.cos(radians), distance)
    if dx == 0 and dz == 0:
        dz = distance
    return float(dx), 0.0, float(dz)


def _add_candidate_offset(
    offsets: list[tuple[str, float, float, float]], seen: set[tuple[int, int, int]], candidate_id: str, dx: float, dy: float, dz: float
) -> None:
    key = (int(round(dx)), int(round(dy)), int(round(dz)))
    if key == (0, 0, 0) or key in seen:
        return
    seen.add(key)
    offsets.append((candidate_id, float(key[0]), float(key[1]), float(key[2])))


def _candidate_offsets(reference: PlayerReference, placement_radius: int) -> list[tuple[str, float, float, float]]:
    offsets: list[tuple[str, float, float, float]] = []
    seen: set[tuple[int, int, int]] = set()
    if reference.yaw is not None:
        for candidate_id, yaw_delta in (
            (f"blickrichtung_{placement_radius}", 0.0),
            (f"rechts_{placement_radius}", 90.0),
            (f"links_{placement_radius}", -90.0),
            (f"hinter_dir_{placement_radius}", 180.0),
        ):
            dx, dy, dz = _offset_from_yaw(reference.yaw, placement_radius, yaw_delta=yaw_delta)
            _add_candidate_offset(offsets, seen, candidate_id, dx, dy, dz)
        return offsets[:MAX_PLACEMENT_CANDIDATES]

    cardinal = (
        (f"east_{placement_radius}", placement_radius, 0.0, 0.0),
        (f"west_{placement_radius}", -placement_radius, 0.0, 0.0),
        (f"south_{placement_radius}", 0.0, 0.0, placement_radius),
        (f"north_{placement_radius}", 0.0, 0.0, -placement_radius),
    )
    for candidate_id, dx, dy, dz in cardinal:
        _add_candidate_offset(offsets, seen, candidate_id, dx, dy, dz)
    return offsets[:MAX_PLACEMENT_CANDIDATES]


def _candidate_warning(*, block_checked: bool = False) -> str:
    if block_checked:
        return t("Blockfreiheit geprüft.")
    return t("Sicherheitsstatus: Blockfreiheit noch nicht geprüft. Nicht als sicher platzierbar bewerten.")


def build_mount_preview(
    player_snapshot: dict[str, Any],
    player_key: str,
    *,
    mount_type: str | None = None,
    preferred_offset: Any = None,
    placement_radius: Any = None,
) -> dict[str, Any]:
    resolved_mount_type = normalize_mount_type(mount_type)
    radius = normalize_placement_radius(placement_radius)
    reference = player_reference_from_snapshot(player_snapshot, player_key)
    create_available = mount_create_available(resolved_mount_type) and dimension_allows_create(reference.dimension_id)
    warnings = [
        t(
            "Experimentell: Die Vorschau zeigt vier Richtungskandidaten. "
            "Intern wird je Richtung die Linie von Abstand {min} bis {max} geprüft, "
            "kein vollständiger Flächenscan um den Spieler.",
            min=MIN_PLACEMENT_RADIUS,
            max=radius,
        ),
        t("Die Ausgangshöhe wird aus Spielerposition minus 1,62 geschätzt und anschließend auf eine geprüfte Vollblock-Oberfläche eingerastet."),
        *mount_type_notes(resolved_mount_type),
    ]
    if reference.yaw is not None:
        warnings.append(t("Blickrichtung wurde aus Player-Rotation gelesen und für die Kandidaten-Reihenfolge bevorzugt."))
    else:
        warnings.append(t("Blickrichtung ist im aktuellen Player-Stats-Contract nicht enthalten; Kandidaten werden kardinal um den Spieler sortiert."))
    if create_available:
        warnings.append(
            t("Create schreibt actorprefix + digp, erzeugt vollständiges Mount-NBT und erstellt vorher ein Backup. Bitte zuerst nur mit Weltkopien testen.")
        )
    elif not mount_create_available(resolved_mount_type):
        warnings.append(t("Create ist für diesen Mount-Typ noch deaktiviert."))
    elif reference.dimension_id is None:
        warnings.append(
            t("DimensionId fehlt oder ist nicht sicher lesbar; Create bleibt deaktiviert, bis der Spieler mit gültiger Dimension neu geladen wurde.")
        )
    else:
        warnings.append(t("Create ist aktuell nur im Overworld-Kontext erlaubt; wechsle vor dem Erzeugen in die Overworld."))

    candidates = [
        {
            "id": candidate_id,
            **_candidate_position(reference.position, dx, dy, dz),
            "offset": {"x": dx, "y": dy, "z": dz},
            "distance": round(math.sqrt(dx * dx + dz * dz), 3),
            "block_check": "not_checked",
            "safe_to_place": None,
            "warning": _candidate_warning(),
        }
        for candidate_id, dx, dy, dz in _candidate_offsets(reference, radius)
    ]

    preferred = _normalized_preferred_offset(preferred_offset)
    selected_candidate_id = candidates[0]["id"]
    selected_position = {key: candidates[0][key] for key in ("x", "y", "z")}
    if preferred is not None:
        selected_candidate_id = "preferred_offset"
        selected_position = _candidate_position(reference.position, *preferred)
        candidates.insert(
            0,
            {
                "id": selected_candidate_id,
                **selected_position,
                "offset": {"x": preferred[0], "y": preferred[1], "z": preferred[2]},
                "distance": round(math.sqrt(preferred[0] * preferred[0] + preferred[2] * preferred[2]), 3),
                "block_check": "not_checked",
                "safe_to_place": None,
                "warning": t("Vom Client gewählter Kandidaten-Offset; serverseitig begrenzt, aber Blockfreiheit noch nicht geprüft."),
            },
        )

    return {
        "success": True,
        "mount_type": resolved_mount_type,
        "mount_label": mount_type_label(resolved_mount_type),
        "mount_options": mount_type_options(),
        "player_reference": {
            "player_key": reference.player_key,
            "player_label": reference.player_label,
        },
        "player_position": reference.position,
        "player_rotation": reference.rotation,
        "player_yaw": reference.yaw,
        "dimension_id": reference.dimension_id,
        "placement_search": {
            "radius": radius,
            "candidate_count": len(candidates),
            "prefers_view_direction": reference.yaw is not None,
            "block_check": "not_implemented",
            "search_shape": "four_direction_lines",
            "full_area_scan": False,
            "radius_scan_min_distance": MIN_PLACEMENT_RADIUS,
            "radius_scan_max_distance": radius,
        },
        "candidate_positions": candidates,
        "selected_candidate_id": selected_candidate_id,
        "selected_position": selected_position,
        "warnings": warnings,
        "can_create": create_available,
        "create_available": create_available,
    }
