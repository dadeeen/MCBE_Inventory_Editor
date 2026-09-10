"""Resolve inventory visuals without confusing item IDs and atlas keys.

This module only follows declared references. Geometry and legacy compatibility
guesses belong to the caller and must retain their own provenance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class IconResolution:
    basis: str
    atlas: str
    path: str | None = None
    faces: dict[str, str] = field(default_factory=dict)
    issue: str | None = None

    def metadata(self) -> dict[str, Any]:
        return {"basis": self.basis, "atlas": self.atlas, "texture": self.path, "faces": self.faces, "issue": self.issue}


def item_icon_key(value: Any) -> str | None:
    """Read current and historical minecraft:icon component representations."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        textures = value.get("textures")
        key = textures.get("default") if isinstance(textures, dict) else value.get("texture")
        return key if isinstance(key, str) else None
    return None


def _path(key: str, atlas: dict[str, list[str]], available: set[str]) -> tuple[str | None, str | None]:
    paths = list(dict.fromkeys(atlas.get(key, [])))
    # Array order encodes states/variants, not preference or availability.
    if len(paths) > 1:
        return None, "variant_selection_required"
    if not paths:
        return None, "unknown_texture_key"
    path = paths[0]
    if path.startswith("entity/"):
        return None, "model_required"
    if path not in available:
        return None, "missing_texture"
    return path, None


def _face_keys(value: Any) -> dict[str, str]:
    if isinstance(value, str):
        return dict.fromkeys(("side", "top", "front"), value)
    if not isinstance(value, dict):
        return {}
    result = {}
    # The preview exposes the east and north faces. "side" and "*" are
    # documented defaults; arbitrary other faces must not be substituted.
    for face, candidates in {"side": ("east", "side", "*"), "top": ("up", "*"), "front": ("north", "side", "*")}.items():
        for candidate in candidates:
            if isinstance(value.get(candidate), str):
                result[face] = value[candidate]
                break
    # Orient simple previews towards an explicitly named front material. This
    # preserves the identifying face of e.g. trapped chests and furnaces.
    fronts = {key for key in value.values() if isinstance(key, str) and "front" in key}
    if len(fronts) == 1:
        result["front"] = fronts.pop()
    return result


def inventory_sprite_keys(item_id: str) -> list[str]:
    """Identity-preserving Bedrock sprite spellings for placeable items.

    These never remove a block shape to obtain a crafting ingredient. Most
    Vanilla item definitions are not published; these spellings bridge that gap.
    """
    keys = [item_id]
    if item_id.startswith("waxed_") and item_id.endswith("_door"):
        keys.append(item_id.removeprefix("waxed_"))
    if item_id.endswith("_door"):
        wood = item_id.removesuffix("_door")
        keys.append("door_" + {"wooden": "wood"}.get(wood, wood))
    if item_id.endswith("_sign"):
        keys.append("sign_" + item_id.removesuffix("_sign"))
        keys.extend({"oak_sign": ["sign"], "dark_oak_sign": ["sign_darkoak"]}.get(item_id, []))
    keys.extend({
        "frame": ["item_frame"], "glow_frame": ["glow_item_frame"],
        "redstone_wire": ["redstone_dust"], "sugar_cane": ["reeds"], "iron_chain": ["chain"],
    }.get(item_id, []))
    return keys


def resolve_icon_definition(
    item_id: str,
    *,
    is_block: bool,
    item_icons: dict[str, Any],
    blocks: dict[str, Any],
    item_atlas: dict[str, list[str]],
    terrain_atlas: dict[str, list[str]],
    available: set[str],
) -> IconResolution | None:
    """Return a declared binding (including failures), or no known definition.

    Missing declared assets must not silently fall through to a similarly named
    material. Unresolved state arrays may use a separately labelled legacy path.
    """
    if item_id in item_icons:
        key = item_icon_key(item_icons[item_id])
        path, issue = _path(key, item_atlas, available) if key else (None, "unsupported_item_icon")
        return IconResolution("item_definition", "items", path, issue=issue)

    block = blocks.get(item_id, {}) if is_block else {}
    if not isinstance(block, dict):
        block = {}
    # An explicit inventory binding takes precedence over world materials.
    carried = block.get("carried_textures")
    if carried is None:
        for key in inventory_sprite_keys(item_id):
            paths = item_atlas.get(key, [])
            if paths and all(path.startswith("items/") for path in paths):
                path, issue = _path(key, item_atlas, available)
                return IconResolution("item_atlas", "items", path, issue=issue)
            direct = "items/" + key
            if direct in available:
                return IconResolution("inventory_sprite", "items", direct)
    if not block:
        return None
    basis = "block_carried" if carried is not None else "block_definition"
    keys = _face_keys(block.get("textures"))
    # Some Vanilla blocks only override selected faces for the carried form.
    if carried is not None:
        keys.update(_face_keys(carried))
    if not keys:
        return None
    faces = {}
    for face, key in keys.items():
        path, issue = _path(key, terrain_atlas, available)
        if issue:
            return IconResolution(basis, "terrain", issue=issue)
        faces[face] = path
    path = faces.get("side") or faces.get("front") or faces.get("top")
    return IconResolution(basis, "terrain", path, faces)
