"""Placement refinement and safety policy for staged mounts.

This module owns candidate scanning, footprint probing, and the public safety
summary. HTTP request handling and write orchestration remain in
``mount_api_routes``.
"""

from __future__ import annotations

import math
from typing import Any

from .i18n import t
from .mount_block_probe import (
    CHUNK_FINALIZED_DONE,
    annotate_preview_candidates_with_chunk_probe,
    is_confirmed_full_support_surface,
    probe_candidate_chunk,
    support_surface_requires_shape_data,
    support_surface_shape_is_state_dependent,
)
from .mounts import MIN_PLACEMENT_RADIUS, horizontal_block_offset, mount_collision_height, mount_collision_width

PASSABLE_PLACEMENT_SPACE_BLOCKS = frozenset(
    {
        "minecraft:air",
        "minecraft:cave_air",
        "minecraft:void_air",
        "minecraft:short_grass",
        "minecraft:tall_grass",
        "minecraft:fern",
        "minecraft:large_fern",
        "minecraft:deadbush",
        "minecraft:dandelion",
        "minecraft:poppy",
        "minecraft:blue_orchid",
        "minecraft:allium",
        "minecraft:azure_bluet",
        "minecraft:red_tulip",
        "minecraft:orange_tulip",
        "minecraft:white_tulip",
        "minecraft:pink_tulip",
        "minecraft:oxeye_daisy",
        "minecraft:cornflower",
        "minecraft:lily_of_the_valley",
        "minecraft:wither_rose",
        "minecraft:torchflower",
        "minecraft:seagrass",
        "minecraft:tall_seagrass",
        "minecraft:vine",
        "minecraft:glow_lichen",
    }
)
LIQUID_PLACEMENT_BLOCKS = frozenset({"minecraft:water", "minecraft:flowing_water", "minecraft:lava", "minecraft:flowing_lava"})
VERTICAL_PLACEMENT_Y_OFFSETS = (0, -1, 1, -2, 2, -3, 3)
HORSE_FOOTPRINT_HALF_WIDTH_BLOCKS = 0.75


def _finite_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result or result in (float("inf"), float("-inf")):
        return None
    return result


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _block_names_from_probe(candidate: dict[str, Any]) -> dict[str, str | None]:
    placement_check = candidate.get("chunk_probe", {}).get("placement_check")
    if not isinstance(placement_check, dict):
        return {}
    names = placement_check.get("block_names")
    if not isinstance(names, dict):
        return {}
    return {role: value if isinstance(value, str) else None for role, value in names.items()}


def _reassess_candidate_space(candidate: dict[str, Any]) -> dict[str, Any]:
    names = _block_names_from_probe(candidate)
    if not names:
        return candidate
    floor = names.get("floor")
    feet = names.get("feet")
    head = names.get("head")
    if not floor or not feet or not head:
        return candidate

    chunk_probe = _dict_or_empty(candidate.get("chunk_probe"))
    if feet not in PASSABLE_PLACEMENT_SPACE_BLOCKS:
        safe_to_place = False
        status = "unsafe"
        message = t("Fußraum ist blockiert durch {feet}; Pferd kann hier nicht sicher platziert werden.", feet=feet)
    elif head not in PASSABLE_PLACEMENT_SPACE_BLOCKS:
        safe_to_place = False
        status = "unsafe"
        message = t("Kopfraum ist blockiert durch {head}; Pferd kann hier nicht sicher platziert werden.", head=head)
    elif floor in PASSABLE_PLACEMENT_SPACE_BLOCKS:
        safe_to_place = False
        status = "unsafe"
        message = t("Bodenblock ist {floor}; Pferd hätte keinen tragfähigen Boden.", floor=floor)
    elif floor in LIQUID_PLACEMENT_BLOCKS:
        safe_to_place = False
        status = "unsafe"
        message = t("Bodenblock ist Flüssigkeit ({floor}); Pferd kann hier nicht sicher platziert werden.", floor=floor)
    elif support_surface_requires_shape_data(floor):
        safe_to_place = False
        status = "unsafe"
        message = t("Bodenblock {floor} hat keine bestätigte Vollblock-Oberfläche; die exakte Standhöhe ist nicht sicher bestimmbar.", floor=floor)
    elif support_surface_shape_is_state_dependent(floor):
        safe_to_place = None
        status = "unchecked"
        message = t(
            "Bodenblock {floor} kann je nach Blockzustand tragen oder nicht; der Zustand wird nicht gelesen. Bitte Platzierung prüfen.", floor=floor
        )
    elif not is_confirmed_full_support_surface(floor):
        safe_to_place = None
        status = "unchecked"
        message = t("Bodenblock {floor} ist kein bestätigter Vollblock; die Tragfähigkeit ist nicht sicher bestätigt. Bitte Platzierung prüfen.", floor=floor)
    else:
        safe_to_place = True
        status = "safe"
        message = t("Boden/Fuß-/Kopfraum geprüft: Boden {floor}, Fußraum {feet}, Kopfraum {head}.", floor=floor, feet=feet, head=head)

    if safe_to_place is True and chunk_probe.get("chunk_finalized") != CHUNK_FINALIZED_DONE:
        safe_to_place = None
        status = "unchecked"
        message = t("Chunk-Generierung ist nicht abgeschlossen oder nicht sicher nachweisbar; Position bleibt ungeprüft.")

    placement_check = _dict_or_empty(chunk_probe.get("placement_check"))
    updated_placement_check = {
        **placement_check,
        "status": status,
        "safe_to_place": safe_to_place,
        "block_names": names,
        "message": message,
    }
    return {
        **candidate,
        "safe_to_place": safe_to_place,
        "warning": message,
        "chunk_probe": {
            **chunk_probe,
            "safe_to_place": safe_to_place,
            "warning": message,
            "placement_check": updated_placement_check,
        },
    }


def _candidate_with_vertical_offset(candidate: dict[str, Any], y_offset: int) -> dict[str, Any]:
    if y_offset == 0:
        return dict(candidate)
    adjusted = dict(candidate)
    adjusted["y"] = round(float(candidate.get("y", 0.0)) + y_offset, 3)
    offset = dict(candidate.get("offset") or {})
    offset["y"] = round(float(offset.get("y", 0.0)) + y_offset, 3)
    adjusted["offset"] = offset
    adjusted["vertical_adjustment"] = y_offset
    return adjusted


def _candidate_snapped_to_block_surface(candidate: dict[str, Any]) -> dict[str, Any]:
    y = _finite_float(candidate.get("y"))
    if y is None:
        return dict(candidate)
    snapped_y = float(math.floor(y))
    adjustment = round(snapped_y - y, 3)
    adjusted = {**candidate, "y": snapped_y}
    if adjustment:
        adjusted["surface_snap_adjustment"] = adjustment
    return adjusted


def _placement_safety_rank(candidate: dict[str, Any] | None) -> int:
    if not isinstance(candidate, dict):
        return 0
    if candidate.get("safe_to_place") is True:
        return 3
    if candidate.get("safe_to_place") is None:
        return 2
    if candidate.get("safe_to_place") is False:
        return 1
    return 0


def _placement_safety_status(candidate: dict[str, Any] | None) -> str:
    if not isinstance(candidate, dict):
        return "unchecked"
    if candidate.get("safe_to_place") is True:
        return "safe"
    if candidate.get("safe_to_place") is False:
        return "unsafe"
    return "unchecked"


def _better_placement_fallback(current: dict[str, Any] | None, candidate: dict[str, Any]) -> dict[str, Any]:
    if current is None:
        return candidate
    current_rank = _placement_safety_rank(current)
    candidate_rank = _placement_safety_rank(candidate)
    if candidate_rank > current_rank:
        return candidate
    return current


def _candidate_with_probe(candidate: dict[str, Any], probe: dict[str, Any]) -> dict[str, Any]:
    probed = {
        **candidate,
        "block_check": probe.get("block_check"),
        "safe_to_place": probe.get("safe_to_place"),
        "warning": probe.get("warning"),
        "chunk_probe": probe,
    }
    return _reassess_candidate_space(probed)


def _candidate_position(candidate: dict[str, Any]) -> tuple[float, float, float] | None:
    x = _finite_float(candidate.get("x"))
    y = _finite_float(candidate.get("y"))
    z = _finite_float(candidate.get("z"))
    if x is None or y is None or z is None:
        return None
    return x, y, z


def _candidate_footprint_columns(candidate: dict[str, Any], half_width: float = HORSE_FOOTPRINT_HALF_WIDTH_BLOCKS) -> list[dict[str, Any]]:
    position = _candidate_position(candidate)
    if position is None:
        return []
    x, _y, z = position
    min_x = math.floor(x - half_width)
    max_x = math.floor(x + half_width)
    min_z = math.floor(z - half_width)
    max_z = math.floor(z + half_width)
    center_x = math.floor(x)
    center_z = math.floor(z)
    return [
        {
            "block_x": block_x,
            "block_z": block_z,
            "center": block_x == center_x and block_z == center_z,
        }
        for block_x in range(min_x, max_x + 1)
        for block_z in range(min_z, max_z + 1)
    ]


def _candidate_for_footprint_column(candidate: dict[str, Any], block_x: int, block_z: int) -> dict[str, Any]:
    column_candidate = dict(candidate)
    column_candidate["x"] = block_x + 0.5
    column_candidate["z"] = block_z + 0.5
    return column_candidate


def _probe_footprint_column(
    db: Any,
    candidate: dict[str, Any],
    column: dict[str, Any],
    dimension_id: int | None,
    clearance_blocks: int = 2,
) -> dict[str, Any]:
    column_candidate = _candidate_for_footprint_column(candidate, int(column["block_x"]), int(column["block_z"]))
    probe = probe_candidate_chunk(db, column_candidate, dimension_id=dimension_id)
    probed = _candidate_with_probe(column_candidate, probe)
    names = _block_names_from_probe(probed)
    for body_offset in range(2, clearance_blocks):
        upper_candidate = {**column_candidate, "y": float(column_candidate["y"]) + body_offset - 1}
        upper_probe = probe_candidate_chunk(db, upper_candidate, dimension_id=dimension_id)
        upper_names = (upper_probe.get("placement_check") or {}).get("block_names") or {}
        names[f"body_{body_offset}"] = upper_names.get("head") if isinstance(upper_names, dict) else None
    return {
        "block_x": int(column["block_x"]),
        "block_z": int(column["block_z"]),
        "center": bool(column.get("center")),
        "block_names": names,
        "safe_to_place": probed.get("safe_to_place"),
        "block_check": probed.get("block_check"),
        "warning": probed.get("warning"),
        "chunk_probe": probed.get("chunk_probe"),
        "chunk_finalized": _dict_or_empty(probed.get("chunk_probe")).get("chunk_finalized"),
    }


def _footprint_assessment(columns: list[dict[str, Any]], clearance_blocks: int = 2) -> dict[str, Any]:
    if not columns:
        return {
            "status": "unchecked",
            "safe_to_place": None,
            "message": t("Footprint konnte nicht geprüft werden; Position ist nicht sicher bestätigt."),
            "edge_overhang_count": 0,
        }

    required_roles = ["floor", "feet", "head", *(f"body_{offset}" for offset in range(2, clearance_blocks))]
    missing = [column for column in columns if not all((column.get("block_names") or {}).get(role) for role in required_roles)]
    if missing:
        return {
            "status": "unchecked",
            "safe_to_place": None,
            "message": t(
                "Footprint konnte nicht vollständig gelesen werden ({missing} von {total} Spalten); Position ist nicht sicher bestätigt.",
                missing=len(missing),
                total=len(columns),
            ),
            "edge_overhang_count": 0,
        }

    for column in columns:
        names = column["block_names"]
        for role in required_roles:
            if role == "floor":
                continue
            block_name = str(names[role])
            if block_name not in PASSABLE_PLACEMENT_SPACE_BLOCKS:
                label = t("Fußraum") if role == "feet" else t("Kopfraum") if role == "head" else t("Körperraum")
                return {
                    "status": "unsafe",
                    "safe_to_place": False,
                    "message": t(
                        "Footprint-{label} ist bei {x}/{z} durch {block} blockiert.", label=label, x=column["block_x"], z=column["block_z"], block=block_name
                    ),
                    "edge_overhang_count": 0,
                }

    center = next((column for column in columns if column.get("center")), columns[0])
    center_floor = str(center["block_names"]["floor"])
    if center_floor in PASSABLE_PLACEMENT_SPACE_BLOCKS:
        return {
            "status": "unsafe",
            "safe_to_place": False,
            "message": t("Zentraler Bodenblock ist {floor}; Pferd hätte keinen tragfähigen Standpunkt.", floor=center_floor),
            "edge_overhang_count": 0,
        }
    if center_floor in LIQUID_PLACEMENT_BLOCKS:
        return {
            "status": "unsafe",
            "safe_to_place": False,
            "message": t("Zentraler Bodenblock ist Flüssigkeit ({floor}); Pferd kann hier nicht sicher platziert werden.", floor=center_floor),
            "edge_overhang_count": 0,
        }
    if support_surface_requires_shape_data(center_floor):
        return {
            "status": "unsafe",
            "safe_to_place": False,
            "message": t(
                "Zentraler Bodenblock {floor} hat keine bestätigte Vollblock-Oberfläche; die exakte Standhöhe ist nicht sicher bestimmbar.", floor=center_floor
            ),
            "edge_overhang_count": 0,
        }
    if support_surface_shape_is_state_dependent(center_floor):
        return {
            "status": "unchecked",
            "safe_to_place": None,
            "message": t(
                "Zentraler Bodenblock {floor} kann je nach Blockzustand tragen oder nicht; der Zustand wird nicht gelesen.", floor=center_floor
            ),
            "edge_overhang_count": 0,
        }
    if not is_confirmed_full_support_surface(center_floor):
        return {
            "status": "unchecked",
            "safe_to_place": None,
            "message": t("Zentraler Bodenblock {floor} ist kein bestätigter Vollblock; die Tragfähigkeit ist nicht sicher bestätigt.", floor=center_floor),
            "edge_overhang_count": 0,
        }

    edge_overhang = 0
    for column in columns:
        if column.get("center"):
            continue
        floor = str(column["block_names"]["floor"])
        if floor in LIQUID_PLACEMENT_BLOCKS:
            return {
                "status": "unsafe",
                "safe_to_place": False,
                "message": t("Footprint-Boden enthält Flüssigkeit bei {x}/{z} ({floor}).", x=column["block_x"], z=column["block_z"], floor=floor),
                "edge_overhang_count": edge_overhang,
            }
        if support_surface_requires_shape_data(floor):
            return {
                "status": "unsafe",
                "safe_to_place": False,
                "message": t(
                    "Footprint-Boden enthält eine nicht exakt auflösbare Oberfläche bei {x}/{z} ({floor}).",
                    x=column["block_x"],
                    z=column["block_z"],
                    floor=floor,
                ),
                "edge_overhang_count": edge_overhang,
            }
        if not is_confirmed_full_support_surface(floor):
            # Rand ohne bestätigt tragfähigen Vollblock (Luft, Pflanze oder unbekannt):
            # als Überhang werten. Ränder dürfen überhängen, solange die Mitte trägt.
            edge_overhang += 1

    if edge_overhang:
        message = t(
            "Footprint geprüft: zentraler Boden {floor}, Körperraum frei; {count} Randspalten ohne tragenden Boden toleriert.",
            floor=center_floor,
            count=edge_overhang,
        )
    else:
        message = t("Footprint geprüft: zentraler Boden {floor}, Körperraum frei.", floor=center_floor)
    return {
        "status": "safe",
        "safe_to_place": True,
        "message": message,
        "edge_overhang_count": edge_overhang,
    }


def _candidate_with_footprint_probe(
    db: Any,
    candidate: dict[str, Any],
    dimension_id: int | None,
    *,
    half_width: float = HORSE_FOOTPRINT_HALF_WIDTH_BLOCKS,
    clearance_blocks: int = 2,
) -> dict[str, Any]:
    footprint_columns = _candidate_footprint_columns(candidate, half_width)
    if not footprint_columns:
        return candidate

    columns = [_probe_footprint_column(db, candidate, column, dimension_id, clearance_blocks) for column in footprint_columns]
    assessment = _footprint_assessment(columns, clearance_blocks)
    finalized_states = [column.get("chunk_finalized") for column in columns]
    all_chunks_finalized = all(state == CHUNK_FINALIZED_DONE for state in finalized_states)
    if all_chunks_finalized:
        footprint_chunk_finalized: int | None = CHUNK_FINALIZED_DONE
    else:
        footprint_chunk_finalized = next(
            (state for state in finalized_states if isinstance(state, int) and state != CHUNK_FINALIZED_DONE),
            None,
        )
    if assessment.get("safe_to_place") is True and not all_chunks_finalized:
        assessment = {
            **assessment,
            "status": "unchecked",
            "safe_to_place": None,
            "reason": "chunk_not_finalized",
            "message": t("Chunk-Generierung ist nicht abgeschlossen oder nicht sicher nachweisbar; Position bleibt ungeprüft."),
        }
    center_column = next((column for column in columns if column.get("center")), columns[0])
    center_probe = _dict_or_empty(center_column.get("chunk_probe"))
    footprint_check = {
        "status": assessment.get("status"),
        "safe_to_place": assessment.get("safe_to_place"),
        "message": assessment.get("message"),
        "column_count": len(columns),
        "half_width": half_width,
        "clearance_blocks": clearance_blocks,
        "edge_overhang_count": assessment.get("edge_overhang_count", 0),
        "all_chunks_finalized": all_chunks_finalized,
        "columns": [
            {
                "block_x": column.get("block_x"),
                "block_z": column.get("block_z"),
                "center": column.get("center"),
                "block_names": column.get("block_names"),
                "safe_to_place": column.get("safe_to_place"),
                "chunk_finalized": column.get("chunk_finalized"),
            }
            for column in columns
        ],
    }
    return {
        **candidate,
        "block_check": "footprint_probe",
        "safe_to_place": assessment.get("safe_to_place"),
        "warning": str(assessment.get("message") or candidate.get("warning") or t("Footprint wurde geprüft.")),
        "chunk_probe": {
            **center_probe,
            "chunk_finalized": footprint_chunk_finalized,
            "safe_to_place": assessment.get("safe_to_place"),
            "warning": str(assessment.get("message") or center_probe.get("warning") or ""),
            "footprint_check": footprint_check,
        },
    }


def _candidate_with_horizontal_distance(candidate: dict[str, Any], distance: int) -> dict[str, Any] | None:
    offset = _dict_or_empty(candidate.get("offset"))
    dx = _finite_float(offset.get("x", 0.0))
    dy = _finite_float(offset.get("y", 0.0))
    dz = _finite_float(offset.get("z", 0.0))
    x = _finite_float(candidate.get("x"))
    y = _finite_float(candidate.get("y"))
    z = _finite_float(candidate.get("z"))
    if dx is None or dy is None or dz is None or x is None or y is None or z is None:
        return None
    if math.hypot(dx, dz) <= 0:
        return None
    # Same distance guarantee as the preview candidates: a rounded diagonal must
    # not land inside MIN_PLACEMENT_RADIUS.
    next_dx, next_dz = horizontal_block_offset(dx, dz, distance)
    if next_dx == 0 and next_dz == 0:
        return None
    base_x = x - dx
    base_z = z - dz
    adjusted = dict(candidate)
    original_id = str(candidate.get("id") or "candidate")
    prefix = original_id.rsplit("_", 1)[0] if "_" in original_id else original_id
    adjusted["id"] = f"{prefix}_{distance}"
    adjusted["x"] = round(base_x + next_dx, 3)
    adjusted["z"] = round(base_z + next_dz, 3)
    adjusted["offset"] = {"x": float(next_dx), "y": dy, "z": float(next_dz)}
    adjusted["distance"] = round(math.hypot(next_dx, next_dz), 3)
    adjusted["radius_distance"] = distance
    return adjusted


def _distance_candidates(candidate: dict[str, Any], max_radius: int) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    for distance in range(MIN_PLACEMENT_RADIUS, max_radius + 1):
        adjusted = _candidate_with_horizontal_distance(candidate, distance)
        if adjusted is None:
            continue
        offset = _dict_or_empty(adjusted.get("offset"))
        key = (int(round(float(offset.get("x", 0.0)))), int(round(float(offset.get("z", 0.0)))))
        if key == (0, 0) or key in seen:
            continue
        seen.add(key)
        result.append(adjusted)
    return result or [candidate]


def _try_safe_vertical_candidate(
    db: Any,
    candidate: dict[str, Any],
    dimension_id: int | None,
    *,
    half_width: float = HORSE_FOOTPRINT_HALF_WIDTH_BLOCKS,
    clearance_blocks: int = 2,
) -> dict[str, Any]:
    fallback = None
    for y_offset in VERTICAL_PLACEMENT_Y_OFFSETS:
        adjusted = _candidate_snapped_to_block_surface(_candidate_with_vertical_offset(candidate, y_offset))
        probed = _candidate_with_footprint_probe(
            db,
            adjusted,
            dimension_id=dimension_id,
            half_width=half_width,
            clearance_blocks=clearance_blocks,
        )
        fallback = _better_placement_fallback(fallback, probed)
        if probed.get("safe_to_place") is True:
            notes = []
            if y_offset != 0:
                notes.append(t("Höhe automatisch um {offset} Block angepasst.", offset=f"{y_offset:+d}"))
            surface_snap_adjustment = _finite_float(probed.get("surface_snap_adjustment"))
            if surface_snap_adjustment:
                notes.append(t("Standhöhe um {offset} auf die Vollblock-Oberfläche eingerastet.", offset=f"{surface_snap_adjustment:+.3f}"))
            if notes:
                probed = {
                    **probed,
                    "warning": f"{' '.join(notes)} {probed.get('warning', '')}".strip(),
                    "vertical_adjustment": y_offset,
                }
                chunk_probe = _dict_or_empty(probed.get("chunk_probe"))
                probed["chunk_probe"] = {
                    **chunk_probe,
                    "vertical_adjustment": y_offset,
                    "surface_snap_adjustment": surface_snap_adjustment or 0.0,
                }
            return probed
    return fallback or candidate


def _try_safe_distance_candidate(
    db: Any,
    candidate: dict[str, Any],
    max_radius: int,
    dimension_id: int | None,
    *,
    half_width: float = HORSE_FOOTPRINT_HALF_WIDTH_BLOCKS,
    clearance_blocks: int = 2,
) -> dict[str, Any]:
    fallback = None
    checked_count = 0
    status_counts = {"safe": 0, "unchecked": 0, "unsafe": 0}
    attempts: list[dict[str, Any]] = []
    for distance_candidate in _distance_candidates(candidate, max_radius):
        checked_count += 1
        probed = _try_safe_vertical_candidate(
            db,
            distance_candidate,
            dimension_id,
            half_width=half_width,
            clearance_blocks=clearance_blocks,
        )
        status = _placement_safety_status(probed)
        status_counts[status] += 1
        attempts.append(
            {
                "id": probed.get("id"),
                "distance": probed.get("distance"),
                "status": status,
                "safe_to_place": probed.get("safe_to_place") if probed.get("safe_to_place") in (True, False) else None,
                "warning": probed.get("warning"),
            }
        )
        fallback = _better_placement_fallback(fallback, probed)
        if probed.get("safe_to_place") is True:
            probed = {
                **probed,
                "radius_scan_checked_count": checked_count,
                "radius_scan_safe_count": status_counts["safe"],
                "radius_scan_unchecked_count": status_counts["unchecked"],
                "radius_scan_unsafe_count": status_counts["unsafe"],
                "radius_scan_attempts": attempts,
            }
            if str(probed.get("id")) != str(candidate.get("id")):
                probed["radius_scan_adjusted"] = True
                probed["warning"] = f"Abstand innerhalb des Suchradius angepasst. {probed.get('warning', '')}".strip()
            return probed
    fallback = fallback or candidate
    return {
        **fallback,
        "radius_scan_checked_count": checked_count,
        "radius_scan_safe_count": status_counts["safe"],
        "radius_scan_unchecked_count": status_counts["unchecked"],
        "radius_scan_unsafe_count": status_counts["unsafe"],
        "radius_scan_attempts": attempts,
    }


def _sync_selected_position_from_candidates(preview: dict[str, Any]) -> dict[str, Any]:
    candidates = preview.get("candidate_positions")
    selected_id = preview.get("selected_candidate_id")
    if not isinstance(candidates, list) or not selected_id:
        return preview
    selected = next((candidate for candidate in candidates if isinstance(candidate, dict) and candidate.get("id") == selected_id), None)
    if not selected:
        safe = next((candidate for candidate in candidates if isinstance(candidate, dict) and candidate.get("safe_to_place") is True), None)
        selected = safe or next((candidate for candidate in candidates if isinstance(candidate, dict) and candidate.get("safe_to_place") is not False), None)
    if not selected:
        return preview
    return {
        **preview,
        "selected_candidate_id": selected.get("id", selected_id),
        "selected_position": {"x": selected.get("x"), "y": selected.get("y"), "z": selected.get("z")},
    }


def _recount_candidate_safety(preview: dict[str, Any]) -> dict[str, Any]:
    candidates = preview.get("candidate_positions")
    if not isinstance(candidates, list):
        return preview
    safe_count = sum(1 for candidate in candidates if isinstance(candidate, dict) and candidate.get("safe_to_place") is True)
    unsafe_count = sum(1 for candidate in candidates if isinstance(candidate, dict) and candidate.get("safe_to_place") is False)
    unchecked_count = sum(1 for candidate in candidates if not isinstance(candidate, dict) or candidate.get("safe_to_place") not in (True, False))
    placement_search = _dict_or_empty(preview.get("placement_search"))
    return {
        **preview,
        "placement_search": {
            **placement_search,
            "placement_safe_count": safe_count,
            "placement_unsafe_count": unsafe_count,
            "placement_unchecked_count": unchecked_count,
        },
    }


def _reassess_passable_placement_blocks(preview: dict[str, Any]) -> dict[str, Any]:
    candidates = preview.get("candidate_positions")
    if not isinstance(candidates, list):
        return preview
    updated = [_reassess_candidate_space(candidate) if isinstance(candidate, dict) else candidate for candidate in candidates]
    return _sync_selected_position_from_candidates(_recount_candidate_safety({**preview, "candidate_positions": updated}))


def _adjust_vertical_placement_candidates(db: Any, preview: dict[str, Any]) -> dict[str, Any]:
    candidates = preview.get("candidate_positions")
    if not isinstance(candidates, list):
        return preview
    dimension_id = preview.get("dimension_id") if isinstance(preview.get("dimension_id"), int) and not isinstance(preview.get("dimension_id"), bool) else None
    placement_search = _dict_or_empty(preview.get("placement_search"))
    max_radius = int(placement_search.get("radius") or MIN_PLACEMENT_RADIUS)
    mount_type = str(preview.get("mount_type") or "minecraft:horse")
    collision_width = mount_collision_width(mount_type)
    collision_height = mount_collision_height(mount_type)
    half_width = collision_width / 2
    clearance_blocks = max(1, math.ceil(collision_height))
    updated = [
        _try_safe_distance_candidate(
            db,
            candidate,
            max_radius,
            dimension_id,
            half_width=half_width,
            clearance_blocks=clearance_blocks,
        )
        if isinstance(candidate, dict)
        else candidate
        for candidate in candidates
    ]
    vertical_adjusted_count = sum(1 for candidate in updated if isinstance(candidate, dict) and candidate.get("vertical_adjustment"))
    radius_adjusted_count = sum(1 for candidate in updated if isinstance(candidate, dict) and candidate.get("radius_scan_adjusted"))
    radius_checked_count = sum(int(candidate.get("radius_scan_checked_count") or 0) for candidate in updated if isinstance(candidate, dict))
    adjusted_preview = {
        **preview,
        "candidate_positions": updated,
        "placement_search": {
            **placement_search,
            "vertical_search": "enabled",
            "vertical_offsets": list(VERTICAL_PLACEMENT_Y_OFFSETS),
            "vertical_adjusted_count": vertical_adjusted_count,
            "footprint_check": "enabled",
            "footprint_half_width": half_width,
            "collision_width": collision_width,
            "collision_height": collision_height,
            "clearance_blocks": clearance_blocks,
            "radius_scan": "enabled",
            "radius_scan_min_distance": MIN_PLACEMENT_RADIUS,
            "radius_scan_max_distance": max_radius,
            "radius_scan_adjusted_count": radius_adjusted_count,
            "radius_scan_checked_count": radius_checked_count,
        },
    }
    return _sync_selected_position_from_candidates(_recount_candidate_safety(adjusted_preview))


def refine_preview_placement(db: Any, preview: dict[str, Any]) -> dict[str, Any]:
    """Annotate, reassess, and scan mount candidates against world blocks."""

    annotated = annotate_preview_candidates_with_chunk_probe(db, preview)
    reassessed = _reassess_passable_placement_blocks(annotated)
    return _adjust_vertical_placement_candidates(db, reassessed)


def placement_safety_from_preview(preview: dict[str, Any]) -> dict[str, Any]:
    """Return the public safety summary for the selected preview candidate."""

    candidates = preview.get("candidate_positions")
    selected_id = preview.get("selected_candidate_id")
    selected = None
    if isinstance(candidates, list):
        selected = next((candidate for candidate in candidates if isinstance(candidate, dict) and candidate.get("id") == selected_id), None)
    if selected is None:
        selected = {}
    safe_to_place = selected.get("safe_to_place")
    placement_search = _dict_or_empty(preview.get("placement_search"))
    block_check = selected.get("block_check") or placement_search.get("block_check") or "not_implemented"
    if safe_to_place is True:
        status = "safe"
        message = t("Pferd kann an der gewählten Position sicher platziert werden.")
    elif safe_to_place is False:
        status = "unsafe"
        message = selected.get("warning") or t("Pferd kann an der gewählten Position nicht sicher platziert werden.")
    else:
        status = "unchecked"
        message = selected.get("warning") or t("Block-/Kollisionsprüfung ist noch nicht aktiv; Platzierung ist nicht als sicher bestätigt.")
    return {
        "status": status,
        "safe_to_place": safe_to_place if isinstance(safe_to_place, bool) else None,
        "block_check": block_check,
        "candidate_id": selected_id,
        "message": message,
    }
