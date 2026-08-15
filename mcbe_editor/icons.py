from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import threading
import time
import zipfile
from collections.abc import Iterable
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .i18n import t
from .icon_cache import recover_icon_cache
from .world_locks import locked_operation

_ALLOWED_EXTENSIONS = {".png", ".webp"}
_TEXTURE_PARTS = {"textures"}
_ITEM_DIR_HINTS = {"items", "item", "blocks", "block"}
_DISPLAY_DIR_HINTS = {"display"}
_MAX_FILE_BYTES = 2_000_000
_MAX_SCAN_FILES = 12000
_MAX_ARCHIVE_MEMBERS = 20000
_SOURCE_FILE_VERSION = 2
_INDEX_FILE_VERSION = 5
_ICON_SOURCES_LOCK = threading.RLock()
_LOGGER = logging.getLogger(__name__)
_POTION_DAMAGE_TEXTURE_SUFFIXES = {
    0: "empty",
    5: "nightvision",
    6: "nightvision",
    7: "invisibility",
    8: "invisibility",
    9: "jump",
    10: "jump",
    11: "jump",
    12: "fireresistance",
    13: "fireresistance",
    14: "movespeed",
    15: "movespeed",
    16: "movespeed",
    17: "moveslowdown",
    18: "moveslowdown",
    19: "waterbreathing",
    20: "waterbreathing",
    21: "heal",
    22: "heal",
    23: "harm",
    24: "harm",
    25: "poison",
    26: "poison",
    27: "poison",
    28: "regeneration",
    29: "regeneration",
    30: "regeneration",
    31: "damageboost",
    32: "damageboost",
    33: "damageboost",
    34: "weakness",
    35: "weakness",
    36: "wither",
    37: "turtlemaster",
    38: "turtlemaster",
    39: "turtlemaster",
    40: "slowfall",
    41: "slowfall",
    42: "moveslowdown",
    43: "windcharged",
    44: "weaving",
    45: "oozing",
    46: "infested",
}
_TIPPED_ARROW_DAMAGE_TEXTURE_SUFFIXES = {
    5: "nightvision",
    6: "nightvision",
    7: "invisibility",
    8: "invisibility",
    9: "leaping",
    10: "leaping",
    11: "leaping",
    12: "fireres",
    13: "fireres",
    14: "swift",
    15: "swift",
    16: "swift",
    17: "slow",
    18: "slow",
    19: "waterbreathing",
    20: "waterbreathing",
    21: "healing",
    22: "healing",
    23: "harm",
    24: "harm",
    25: "poison",
    26: "poison",
    27: "poison",
    28: "regen",
    29: "regen",
    30: "regen",
    31: "strength",
    32: "strength",
    33: "strength",
    34: "weakness",
    35: "weakness",
    36: "wither",
    37: "turtlemaster",
    38: "turtlemaster",
    39: "turtlemaster",
    40: "slowfalling",
    41: "slowfalling",
    42: "slow",
    43: "windcharged",
    44: "weaving",
    45: "oozing",
    46: "infested",
}


def _texture_item_aliases() -> dict[str, tuple[str, ...]]:
    aliases: dict[str, tuple[str, ...]] = {
        "minecraft:potion": ("minecraft:potion_bottle_drinkable",),
        "minecraft:splash_potion": ("minecraft:potion_bottle_splash",),
        "minecraft:lingering_potion": ("minecraft:potion_bottle_lingering",),
        # Legacy-Item-IDs für Pferderüstung nutzen die modernen Sprites.
        "minecraft:horsearmorleather": ("minecraft:leather_horse_armor",),
        "minecraft:horsearmoriron": ("minecraft:iron_horse_armor",),
        "minecraft:horsearmorgold": ("minecraft:golden_horse_armor",),
        "minecraft:horsearmordiamond": ("minecraft:diamond_horse_armor",),
        "minecraft:cocoa_beans": ("minecraft:cocoa",),
        # Mob-Köpfe haben in Bedrock nur ein generisches Skull-Item-Sprite;
        # die Item-Form wird im Spiel 3D gerendert. Besser als leere Fläche.
        "minecraft:skeleton_skull": ("minecraft:skull",),
        "minecraft:wither_skeleton_skull": ("minecraft:skull",),
        "minecraft:creeper_head": ("minecraft:skull",),
        "minecraft:dragon_head": ("minecraft:skull",),
        "minecraft:piglin_head": ("minecraft:skull",),
        "minecraft:player_head": ("minecraft:skull",),
        "minecraft:zombie_head": ("minecraft:skull",),
        # Das offizielle Bedrock-Resource-Pack führt für diese Varianten nur
        # den gemeinsamen Sprite ``tuff_bricks``.
        "minecraft:tuff_brick_stairs": ("minecraft:tuff_bricks",),
        "minecraft:tuff_brick_slab": ("minecraft:tuff_bricks",),
        "minecraft:tuff_brick_wall": ("minecraft:tuff_bricks",),
        # Explizite Bedrock-Texture-Aliasse für IDs ohne gleichnamigen
        # Inventar-Key. Die Ziele sind die jeweiligen Vanilla-PNG-Dateien.
        "minecraft:allow": ("minecraft:build_allow",),
        "minecraft:deny": ("minecraft:build_deny",),
        "minecraft:brown_mushroom_block": ("minecraft:mushroom_block_skin_brown",),
        # Die berindeten Varianten der neueren Hölzer haben keinen gleichnamigen
        # Texture-Key; ohne Alias bliebe nur das Emoji-Fallback.
        "minecraft:cherry_wood": ("minecraft:cherry_log_side",),
        "minecraft:mangrove_wood": ("minecraft:mangrove_log_side",),
        "minecraft:pale_oak_wood": ("minecraft:pale_oak_log_side",),
        "minecraft:cinnabar_brick_slab": ("minecraft:cinnabar_bricks",),
        "minecraft:cinnabar_brick_stairs": ("minecraft:cinnabar_bricks",),
        "minecraft:cinnabar_brick_wall": ("minecraft:cinnabar_bricks",),
        "minecraft:crimson_fence": ("minecraft:crimson_planks",),
        "minecraft:crimson_fence_gate": ("minecraft:crimson_planks",),
        "minecraft:crimson_hyphae": ("minecraft:crimson_log_side",),
        "minecraft:crimson_pressure_plate": ("minecraft:crimson_planks",),
        "minecraft:crimson_slab": ("minecraft:crimson_planks",),
        "minecraft:crimson_stairs": ("minecraft:crimson_planks",),
        "minecraft:crimson_stem": ("minecraft:crimson_log_side",),
        "minecraft:deepslate_brick_slab": ("minecraft:deepslate_bricks",),
        "minecraft:deepslate_brick_stairs": ("minecraft:deepslate_bricks",),
        "minecraft:deepslate_brick_wall": ("minecraft:deepslate_bricks",),
        "minecraft:deepslate_tile_slab": ("minecraft:deepslate_tiles",),
        "minecraft:deepslate_tile_stairs": ("minecraft:deepslate_tiles",),
        "minecraft:deepslate_tile_wall": ("minecraft:deepslate_tiles",),
        "minecraft:end_brick_stairs": ("minecraft:end_bricks",),
        "minecraft:end_portal_frame": ("minecraft:endframe_top",),
        "minecraft:fence_gate": ("minecraft:planks_oak",),
        "minecraft:glow_frame": ("minecraft:glow_item_frame",),
        "minecraft:heavy_weighted_pressure_plate": ("minecraft:iron_block",),
        "minecraft:honey_block": ("minecraft:honey_side",),
        "minecraft:infested_deepslate": ("minecraft:deepslate",),
        "minecraft:iron_chain": ("minecraft:chain",),
        "minecraft:light_gray_carpet": ("minecraft:wool_colored_silver",),
        "minecraft:light_gray_wool": ("minecraft:wool_colored_silver",),
        "minecraft:light_weighted_pressure_plate": ("minecraft:gold_block",),
        "minecraft:lit_pumpkin": ("minecraft:pumpkin_face_on",),
        "minecraft:melon_block": ("minecraft:melon_side",),
        "minecraft:moss_carpet": ("minecraft:moss_block",),
        "minecraft:mossy_cobblestone": ("minecraft:cobblestone_mossy",),
        "minecraft:mossy_cobblestone_stairs": ("minecraft:cobblestone_mossy",),
        "minecraft:mud_brick_slab": ("minecraft:mud_bricks",),
        "minecraft:mud_brick_stairs": ("minecraft:mud_bricks",),
        "minecraft:mud_brick_wall": ("minecraft:mud_bricks",),
        "minecraft:normal_stone_stairs": ("minecraft:stone",),
        "minecraft:packed_ice": ("minecraft:ice_packed",),
        "minecraft:pointed_dripstone": ("minecraft:pointed_dripstone_up_tip",),
        "minecraft:polished_blackstone_brick_slab": ("minecraft:polished_blackstone_bricks",),
        "minecraft:polished_blackstone_brick_stairs": ("minecraft:polished_blackstone_bricks",),
        "minecraft:polished_blackstone_brick_wall": ("minecraft:polished_blackstone_bricks",),
        "minecraft:rail": ("minecraft:rail_normal",),
        "minecraft:red_mushroom_block": ("minecraft:mushroom_block_skin_red",),
        "minecraft:small_dripleaf_block": ("minecraft:small_dripleaf_top",),
        "minecraft:snow_layer": ("minecraft:snow",),
        "minecraft:sticky_piston": ("minecraft:piston_top_sticky",),
        # Der historische Bedrock-Key lautet ``stonebrick``.
        "minecraft:stone_brick_stairs": ("minecraft:stonebrick",),
        "minecraft:stripped_cherry_wood": ("minecraft:stripped_cherry_log_side",),
        "minecraft:stripped_crimson_hyphae": ("minecraft:stripped_crimson_stem_side",),
        "minecraft:stripped_mangrove_wood": ("minecraft:stripped_mangrove_log_side",),
        "minecraft:stripped_pale_oak_wood": ("minecraft:stripped_pale_oak_log_side",),
        "minecraft:stripped_warped_hyphae": ("minecraft:stripped_warped_stem_side",),
        "minecraft:sulfur_brick_slab": ("minecraft:sulfur_bricks",),
        "minecraft:sulfur_brick_stairs": ("minecraft:sulfur_bricks",),
        "minecraft:sulfur_brick_wall": ("minecraft:sulfur_bricks",),
        "minecraft:sulfur_spike": ("minecraft:sulfur_spike_up_tip",),
        "minecraft:warped_fence": ("minecraft:warped_planks",),
        "minecraft:warped_fence_gate": ("minecraft:warped_planks",),
        "minecraft:warped_hyphae": ("minecraft:warped_stem_side",),
        "minecraft:warped_pressure_plate": ("minecraft:warped_planks",),
        "minecraft:warped_slab": ("minecraft:warped_planks",),
        "minecraft:warped_stairs": ("minecraft:warped_planks",),
        "minecraft:waxed_copper": ("minecraft:copper_block",),
        "minecraft:waxed_copper_chest": ("minecraft:copper_chest_inventory_front",),
        "minecraft:waxed_exposed_copper_chest": ("minecraft:exposed_copper_chest_inventory_front",),
        "minecraft:waxed_oxidized_copper_chest": ("minecraft:oxidized_copper_chest_inventory_front",),
        "minecraft:waxed_weathered_copper_chest": ("minecraft:weathered_copper_chest_inventory_front",),
        "minecraft:wooden_pressure_plate": ("minecraft:planks_oak",),
        # Banner sind entity-gerendert und haben kein Item-Sprite; sie fallen
        # bewusst auf das Emoji-Fallback zurück (siehe EMOJI_MAP im Frontend).
    }
    for damage, suffix in _POTION_DAMAGE_TEXTURE_SUFFIXES.items():
        aliases[f"minecraft:potion#{damage}"] = (f"minecraft:potion_bottle_{suffix}",)
        aliases[f"minecraft:splash_potion#{damage}"] = (f"minecraft:potion_bottle_splash_{suffix}",)
        aliases[f"minecraft:lingering_potion#{damage}"] = (f"minecraft:potion_bottle_lingering_{suffix}",)
    # Mojang liefert für die wirkungslosen Wurftränke 0–4 nur die gemeinsame
    # blaue Basistextur. Diese Aliasse sind bewusst explizit, damit die korrekte
    # Darstellung nicht bloß vom allgemeinen Basis-Fallback abhängt.
    for damage in range(5):
        aliases[f"minecraft:splash_potion#{damage}"] = ("minecraft:potion_bottle_splash",)
    for damage, suffix in _TIPPED_ARROW_DAMAGE_TEXTURE_SUFFIXES.items():
        aliases[f"minecraft:tipped_arrow#{damage}"] = (f"minecraft:tipped_arrow_{suffix}",)
    return aliases


_TEXTURE_ITEM_ALIASES = _texture_item_aliases()
_COMMON_PREVIEW_IDS = [
    "minecraft:diamond_sword",
    "minecraft:diamond_pickaxe",
    "minecraft:apple",
    "minecraft:stone",
    "minecraft:iron_chestplate",
    "minecraft:bow",
    "minecraft:torch",
    "minecraft:oak_planks",
]
_WOOL_COLOR_BY_DAMAGE = [
    "white",
    "orange",
    "magenta",
    "light_blue",
    "yellow",
    "lime",
    "pink",
    "gray",
    "light_gray",
    "cyan",
    "purple",
    "blue",
    "brown",
    "green",
    "red",
    "black",
]
_DYE_COLOR_BY_DAMAGE = [
    "black",
    "red",
    "green",
    "brown",
    "blue",
    "purple",
    "cyan",
    "light_gray",
    "gray",
    "pink",
    "lime",
    "yellow",
    "light_blue",
    "magenta",
    "orange",
    "white",
]
_RED_FLOWER_BY_DAMAGE = {
    0: "poppy",
    1: "blue_orchid",
    2: "allium",
    3: "azure_bluet",
    4: "red_tulip",
    5: "orange_tulip",
    6: "white_tulip",
    7: "pink_tulip",
    8: "oxeye_daisy",
    9: "cornflower",
    10: "lily_of_the_valley",
}
_DOUBLE_PLANT_BY_DAMAGE = {
    0: "sunflower",
    1: "lilac",
    2: "tallgrass",
    3: "large_fern",
    4: "rose_bush",
    5: "peony",
}
_DOUBLE_STONE_SLAB_BY_DAMAGE = {
    0: "stone_slab",
    1: "sandstone_slab",
    2: "wooden_slab",
    3: "cobblestone_slab",
    4: "brick_slab",
    5: "stone_brick_slab",
    6: "quartz_slab",
    7: "nether_brick_slab",
}
_STONE_BLOCK_SLAB_BY_DAMAGE = {
    0: "smooth_stone_slab",
    1: "sandstone_slab",
    2: "petrified_oak_slab",
    3: "cobblestone_slab",
    4: "brick_slab",
    5: "stone_brick_slab",
    6: "quartz_slab",
    7: "nether_brick_slab",
}


def _data_root() -> Path:
    raw = os.environ.get("MCBE_DATA_ROOT")
    if raw:
        return Path(raw).expanduser()
    return Path(__file__).resolve().parents[1] / "data"


def _vanilla_icon_roots() -> list[Path]:
    roots: list[Path] = []
    configured = os.environ.get("MCBE_ICON_CACHE_ROOT")
    if configured:
        roots.append(Path(configured).expanduser())
    roots.append(_data_root() / "icons" / "vanilla")
    for root in roots:
        try:
            recover_icon_cache(root, warn=lambda message: _LOGGER.warning("%s", message))
        except OSError:
            _LOGGER.exception("Unterbrochener Vanilla-Icon-Cache konnte nicht wiederhergestellt werden: %s", root)
    return roots


def _read_limited_binary(stream) -> bytes:
    data = stream.read(_MAX_FILE_BYTES + 1)
    if len(data) > _MAX_FILE_BYTES:
        raise ValueError("Icon-Quelle ist zu groß oder wurde seit dem Scan verändert.")
    return data


@dataclass(frozen=True)
class IconCandidate:
    item_id: str
    path: Path | None
    source: str
    token: str
    archive_path: Path | None = None
    archive_member: str | None = None

    @property
    def suffix(self) -> str:
        if self.archive_member:
            return PurePosixPath(self.archive_member).suffix.lower()
        if self.path:
            return self.path.suffix.lower()
        return ""

    def read_bytes(self) -> bytes:
        if self.archive_path and self.archive_member:
            with zipfile.ZipFile(self.archive_path) as zf:
                matches = [info for info in zf.infolist() if info.filename.replace("\\", "/") == self.archive_member]
                if len(matches) != 1 or not _archive_member_looks_like_icon(matches[0]):
                    raise ValueError("Icon-Archiv wurde seit dem Scan verändert. Bitte Icons neu scannen.")
                with zf.open(matches[0]) as src:
                    return _read_limited_binary(src)
        if self.path:
            if not _looks_like_icon(self.path):
                raise ValueError("Icon-Datei ist zu groß oder wurde seit dem Scan verändert. Bitte Icons neu scannen.")
            with self.path.open("rb") as src:
                return _read_limited_binary(src)
        raise FileNotFoundError("Icon-Quelle fehlt.")

    def to_cache_entry(self) -> dict:
        return {
            "item_id": self.item_id,
            "path": str(self.path) if self.path else None,
            "source": self.source,
            "token": self.token,
            "archive_path": str(self.archive_path) if self.archive_path else None,
            "archive_member": self.archive_member,
        }

    @classmethod
    def from_cache_entry(cls, entry: dict) -> IconCandidate | None:
        try:
            item_id = str(entry.get("item_id") or "").strip().lower()
            token = str(entry.get("token") or "").strip()
            source = str(entry.get("source") or "Icon-Quelle")
            path_raw = entry.get("path")
            archive_raw = entry.get("archive_path")
            archive_member = entry.get("archive_member")
            if not item_id or not token:
                return None
            path = Path(path_raw) if path_raw else None
            archive_path = Path(archive_raw) if archive_raw else None
            if archive_path and archive_member:
                return cls(item_id=item_id, path=None, source=source, token=token, archive_path=archive_path, archive_member=str(archive_member))
            if path:
                return cls(item_id=item_id, path=path, source=source, token=token)
        except (TypeError, ValueError):
            return None
        return None


def _safe_stat(path: Path):
    try:
        return path.stat()
    except OSError:
        return None


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _token_for_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()[:24]


def _token_for(path: Path) -> str:
    stat = _safe_stat(path)
    revision = f"{getattr(stat, 'st_size', 0)}:{getattr(stat, 'st_mtime_ns', 0)}"
    return _token_for_text(f"{path.resolve()}::{revision}")


def _normalize_item_id(stem: str) -> str:
    stem = stem.strip().lower().replace(" ", "_")
    if not stem:
        return ""
    if stem.startswith("minecraft_"):
        stem = stem.removeprefix("minecraft_")
    return stem if ":" in stem else f"minecraft:{stem}"


def _normalize_display_asset_id(stem: str) -> str:
    stem = stem.strip().lower().replace(" ", "_")
    if not stem:
        return ""
    if stem.startswith("mcbe_"):
        stem = stem.removeprefix("mcbe_")
    return stem if ":" in stem else f"mcbe:{stem}"


def _parts_look_like_icon(parts: Iterable[str], suffix: str) -> bool:
    if suffix.lower() not in _ALLOWED_EXTENSIONS:
        return False
    lowered = {p.lower() for p in parts}
    if not (_TEXTURE_PARTS & lowered):
        return False
    return bool(_ITEM_DIR_HINTS & lowered)


def _parts_look_like_display_asset(parts: Iterable[str], suffix: str) -> bool:
    if suffix.lower() not in _ALLOWED_EXTENSIONS:
        return False
    lowered = {p.lower() for p in parts}
    return bool((_TEXTURE_PARTS & lowered) and (_DISPLAY_DIR_HINTS & lowered))


def _looks_like_icon(path: Path) -> bool:
    if not _parts_look_like_icon(path.parts, path.suffix):
        return False
    st = _safe_stat(path)
    return bool(st and 0 < st.st_size <= _MAX_FILE_BYTES)


def _archive_member_looks_like_icon(info: zipfile.ZipInfo) -> bool:
    if info.is_dir() or info.file_size <= 0 or info.file_size > _MAX_FILE_BYTES:
        return False
    pp = PurePosixPath(info.filename.replace("\\", "/"))
    return _parts_look_like_icon(pp.parts, pp.suffix)


def _default_roots() -> list[Path]:
    roots: list[Path] = []
    local = os.environ.get("LOCALAPPDATA", "")
    appdata = os.environ.get("APPDATA", "")
    home = Path.home()

    candidates = []
    if local:
        base = Path(local)
        candidates.extend(
            [
                base / "Packages" / "Microsoft.MinecraftUWP_8wekyb3d8bbwe" / "LocalState" / "games" / "com.mojang",
                base / "Packages" / "Microsoft.MinecraftWindowsBeta_8wekyb3d8bbwe" / "LocalState" / "games" / "com.mojang",
                base / "Packages" / "Microsoft.MinecraftUWP_8wekyb3d8bbwe" / "LocalCache",
                base / "Packages" / "Microsoft.MinecraftWindowsBeta_8wekyb3d8bbwe" / "LocalCache",
            ]
        )
    if appdata:
        candidates.append(Path(appdata) / "Minecraft Bedrock" / "Users")
    candidates.append(home / "AppData" / "Roaming" / "Minecraft Bedrock" / "Users")

    roots.extend(candidates)
    return _dedupe_existing_roots(roots)


def world_icon_roots(world_path: str | os.PathLike | None) -> list[Path]:
    """Return local resource-pack roots that can be inferred from a world path.

    A portable/local Bedrock install may keep worlds under paths such as
    ``.../Users/<xuid>/games/com.mojang/minecraftWorlds/<world>`` while resource
    packs live in sibling folders of that same ``com.mojang`` directory.  The
    generic process environment does not always expose APPDATA/LOCALAPPDATA, so
    infer those roots from the already selected world as an additional automatic
    source.
    """

    if not world_path:
        return []
    try:
        current = Path(world_path).expanduser().resolve()
    except OSError:
        current = Path(world_path).expanduser()
    roots: list[Path] = []
    parts_lower = [part.lower() for part in current.parts]
    for idx, part in enumerate(parts_lower):
        if part == "com.mojang":
            com_mojang = Path(*current.parts[: idx + 1])
            roots.extend(
                [
                    com_mojang / "resource_packs",
                    com_mojang / "development_resource_packs",
                ]
            )
            break
    # World templates/exported worlds may also contain local packs inside or near
    # the world directory. These paths are cheap to check and harmless if absent.
    roots.extend(
        [
            current / "resource_packs",
            current / "development_resource_packs",
            current.parent / "resource_packs",
            current.parent / "development_resource_packs",
        ]
    )
    return _dedupe_existing_roots(roots)


def _coerce_extra_sources(extra_sources: Iterable[dict | str | os.PathLike] | None) -> list[dict]:
    result: list[dict] = []
    for raw in extra_sources or []:
        if isinstance(raw, dict):
            raw_path = str(raw.get("path") or "").strip()
            if not raw_path:
                continue
            result.append(
                {
                    "path": raw_path,
                    "enabled": bool(raw.get("enabled", True)),
                    "label": str(raw.get("label") or _source_label(Path(raw_path))),
                    "auto": bool(raw.get("auto", True)),
                    "world": bool(raw.get("world")),
                }
            )
        else:
            raw_path = str(raw or "").strip()
            if raw_path:
                result.append({"path": raw_path, "enabled": True, "label": _source_label(Path(raw_path)), "auto": True})
    return result


def _dedupe_existing_roots(roots: Iterable[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for root in roots:
        try:
            expanded = root.expanduser()
            resolved = str(expanded.resolve())
        except OSError:
            expanded = root.expanduser()
            resolved = str(expanded)
        if resolved in seen:
            continue
        seen.add(resolved)
        if expanded.exists() and (expanded.is_dir() or _is_supported_archive(expanded)):
            result.append(expanded)
    return result


def _is_supported_archive(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in {".zip", ".mcpack"}


def _source_label(path: Path, root: Path | None = None, *, manual: bool = False, archive: bool = False) -> str:
    text = str(path).lower()
    if manual and archive:
        return t("Manuell gewähltes Resource Pack: {name}", name=path.name)
    if manual:
        return t("Manueller Resource-Pack-/Icon-Ordner: {path}", path=path)
    if archive:
        return f"Lokales Resource-Pack-Archiv: {path.name}"
    if "development_resource_packs" in text:
        return "Lokales Development Resource Pack"
    if "resource_packs" in text:
        return "Lokales Resource Pack"
    if "minecraft bedrock" in text:
        return "Lokale Minecraft-Bedrock-Installation"
    if "microsoft.minecraftwindowsbeta" in text:
        return "Minecraft Bedrock Preview lokal"
    if "microsoft.minecraftuwp" in text:
        return "Minecraft Bedrock lokal"
    return f"Lokaler Icon-Ordner: {root or path}"


def _settings_file(settings_path: str | None) -> Path | None:
    if not settings_path:
        return None
    return Path(settings_path).expanduser()


def _cache_file(settings_path: str | None) -> Path | None:
    settings = _settings_file(settings_path)
    if settings:
        return settings.with_name("icon_index_cache.json")
    data_root = os.environ.get("MCBE_DATA_ROOT")
    if data_root:
        return Path(data_root).expanduser() / "icon_index_cache.json"
    return None


def load_icon_sources(settings_path: str | None) -> dict:
    path = _settings_file(settings_path)
    if not path or not path.exists():
        return {"version": _SOURCE_FILE_VERSION, "sources": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        return {"version": _SOURCE_FILE_VERSION, "sources": []}
    sources = data.get("sources") if isinstance(data, dict) else []
    if not isinstance(sources, list):
        sources = []
    clean = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        raw_path = str(source.get("path") or "").strip()
        if not raw_path:
            continue
        clean.append(
            {
                "path": raw_path,
                "enabled": bool(source.get("enabled", True)),
                "label": str(source.get("label") or Path(raw_path).name or raw_path),
                "manual": True,
                "date": source.get("date"),
                "priority": _safe_int(source.get("priority"), 0),
            }
        )
    return {"version": _SOURCE_FILE_VERSION, "sources": clean}


@contextmanager
def _locked_icon_sources(settings_path: str | None):
    path = _settings_file(settings_path)
    if not path:
        raise ValueError("Kein Icon-Settings-Pfad konfiguriert.")
    digest = hashlib.sha256(str(path.expanduser().resolve()).encode("utf-8", errors="surrogatepass")).hexdigest()
    with _ICON_SOURCES_LOCK, locked_operation(f"icon-sources-{digest}", root=str(path.parent)):
        yield path


def _normalize_manual_sources(sources: list[dict]) -> list[dict]:
    normalized: list[dict] = []
    seen: set[str] = set()
    for index, source in enumerate(sources[:50]):
        if not isinstance(source, dict):
            continue
        raw_path = str(source.get("path") or "").strip()
        if not raw_path or raw_path in seen:
            continue
        seen.add(raw_path)
        normalized.append(
            {
                "path": raw_path,
                "enabled": bool(source.get("enabled", True)),
                "label": str(source.get("label") or Path(raw_path).name or raw_path),
                "manual": True,
                "date": source.get("date"),
                "priority": index,
            }
        )
    return normalized


def save_icon_sources(settings_path: str | None, sources: list[dict]) -> None:
    with _locked_icon_sources(settings_path) as path:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": _SOURCE_FILE_VERSION, "sources": _normalize_manual_sources(sources)}
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as temp_file:
                # fdopen owns and closes the descriptor from this point onward.
                # Invalidate our raw handle before any operation in the with-body can
                # fail, so cleanup can never close a descriptor number reused elsewhere.
                fd = -1
                json.dump(payload, temp_file, ensure_ascii=False, indent=2, sort_keys=True)
                temp_file.write("\n")
                temp_file.flush()
                os.fsync(temp_file.fileno())
            os.replace(temp_name, path)
        except BaseException:
            if fd >= 0:
                with suppress(OSError):
                    os.close(fd)
            with suppress(OSError):
                os.remove(temp_name)
            raise


def add_icon_source(settings_path: str | None, source_path: str) -> dict:
    raw = (source_path or "").strip().strip('"')
    if not raw:
        raise ValueError("Kein Resource-Pack-/Icon-Pfad angegeben.")
    path = Path(raw).expanduser()
    if not path.exists():
        raise ValueError(f"Pfad existiert nicht: {path}")
    if not path.is_dir() and not _is_supported_archive(path):
        raise ValueError("Bitte einen Resource-Pack-Ordner, Icon-Ordner, eine ZIP-Datei oder eine MCPACK-Datei wählen.")
    try:
        resolved = str(path.resolve())
    except OSError:
        resolved = str(path)
    with _locked_icon_sources(settings_path):
        state = load_icon_sources(settings_path)
        sources = state["sources"]
        for source in sources:
            try:
                same = str(Path(source["path"]).expanduser().resolve()) == resolved
            except OSError:
                same = source["path"] == resolved
            if same:
                source["enabled"] = True
                save_icon_sources(settings_path, sources)
                clear_icon_cache(settings_path)
                return source
        source = {"path": resolved, "enabled": True, "label": path.name or resolved, "manual": True, "priority": 0}
        sources.insert(0, source)
        save_icon_sources(settings_path, sources)
        clear_icon_cache(settings_path)
        return source


def remove_icon_source(settings_path: str | None, source_path: str) -> None:
    raw = (source_path or "").strip()
    if not raw:
        raise ValueError("Kein Pfad angegeben.")
    with _locked_icon_sources(settings_path):
        state = load_icon_sources(settings_path)
        kept = [s for s in state["sources"] if s.get("path") != raw]
        if len(kept) == len(state["sources"]):
            raise ValueError("Icon-Quelle nicht gefunden.")
        save_icon_sources(settings_path, kept)
        clear_icon_cache(settings_path)


def set_icon_source_enabled(settings_path: str | None, source_path: str, enabled: bool) -> None:
    raw = (source_path or "").strip()
    if not raw:
        raise ValueError("Kein Pfad angegeben.")
    with _locked_icon_sources(settings_path):
        state = load_icon_sources(settings_path)
        changed = False
        for source in state["sources"]:
            if source.get("path") == raw:
                source["enabled"] = bool(enabled)
                changed = True
                break
        if not changed:
            raise ValueError("Icon-Quelle nicht gefunden.")
        save_icon_sources(settings_path, state["sources"])
        clear_icon_cache(settings_path)


def move_icon_source(settings_path: str | None, source_path: str, direction: str) -> None:
    raw = (source_path or "").strip()
    if not raw:
        raise ValueError("Kein Pfad angegeben.")
    if direction not in {"up", "down"}:
        raise ValueError("Ungültige Richtung.")
    with _locked_icon_sources(settings_path):
        state = load_icon_sources(settings_path)
        sources = state["sources"]
        index = next((idx for idx, source in enumerate(sources) if source.get("path") == raw), -1)
        if index < 0:
            raise ValueError("Icon-Quelle nicht gefunden.")
        new_index = index - 1 if direction == "up" else index + 1
        if new_index < 0 or new_index >= len(sources):
            return
        sources[index], sources[new_index] = sources[new_index], sources[index]
        save_icon_sources(settings_path, sources)
        clear_icon_cache(settings_path)


def configured_icon_sources(settings_path: str | None = None, extra_sources: Iterable[dict | str | os.PathLike] | None = None) -> list[dict]:
    sources: list[dict] = []
    sources.extend(_coerce_extra_sources(extra_sources))
    raw = os.environ.get("MCBE_ICON_ROOTS", "")
    if raw.strip():
        for part in raw.split(os.pathsep):
            part = part.strip()
            if part:
                sources.append({"path": str(Path(part).expanduser()), "enabled": True, "label": "MCBE_ICON_ROOTS", "env": True})

    for source in load_icon_sources(settings_path).get("sources", []):
        sources.append({**source, "manual": True})

    for root in _vanilla_icon_roots():
        sources.append({"path": str(root), "enabled": True, "label": "Vanilla Icons aus Mojang/bedrock-samples", "auto": True, "vanilla": True})

    for root in _default_roots():
        sources.append({"path": str(root), "enabled": True, "label": _source_label(root), "auto": True})

    seen: set[str] = set()
    result: list[dict] = []
    for source in sources:
        path = Path(str(source.get("path", ""))).expanduser()
        try:
            resolved = str(path.resolve())
        except OSError:
            resolved = str(path)
        enabled = bool(source.get("enabled", True))
        key = f"{resolved}|{enabled}"
        if key in seen:
            continue
        seen.add(key)
        result.append({**source, "path": resolved, "exists": path.exists(), "archive": _is_supported_archive(path)})
    return result


def _source_signature(source: dict) -> dict:
    raw_path = str(source.get("path") or "")
    path = Path(raw_path).expanduser()
    st = _safe_stat(path)
    signature = {
        "path": raw_path,
        "enabled": bool(source.get("enabled", True)),
        "manual": bool(source.get("manual")),
        "auto": bool(source.get("auto")),
        "env": bool(source.get("env")),
        "exists": bool(st),
        "archive": _is_supported_archive(path),
        "mtime_ns": getattr(st, "st_mtime_ns", None) if st else None,
        "size": getattr(st, "st_size", None) if st else None,
    }
    # Directory mtimes do not always change for nested file changes on every file system.
    # A manual rescan remains the explicit reliable refresh path; this signature keeps
    # normal startup fast and invalidates for common pack replacement/enable operations.
    return signature


def _sources_signature(sources: list[dict]) -> str:
    payload = [_source_signature(source) for source in sources]
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _add_icon(icons: dict[str, IconCandidate], candidate: IconCandidate) -> None:
    # Quellen werden in Prioritätsreihenfolge gescannt (manuell/env vor
    # automatisch); der erste Treffer pro Item-ID gewinnt.
    icons.setdefault(candidate.item_id, candidate)


def _variant_key(item_id: str, damage: int) -> str:
    return f"{item_id}#{damage}"


def _alias_variant_icon(icons: dict[str, IconCandidate], alias_id: str, target_id: str) -> bool:
    if alias_id in icons:
        return False
    target = icons.get(target_id)
    if not target:
        return False
    icons[alias_id] = IconCandidate(
        item_id=alias_id,
        path=target.path,
        source=f"{target.source} · Variantenalias",
        token=target.token,
        archive_path=target.archive_path,
        archive_member=target.archive_member,
    )
    return True


def _add_variant_alias_icons(icons: dict[str, IconCandidate]) -> int:
    added = 0
    for alias_id, target_ids in _TEXTURE_ITEM_ALIASES.items():
        for target_id in target_ids:
            if _alias_variant_icon(icons, alias_id, target_id):
                added += 1
                break
    for damage, color in enumerate(_WOOL_COLOR_BY_DAMAGE):
        for base, suffix in [
            ("minecraft:carpet", "carpet"),
            ("minecraft:concrete_powder", "concrete_powder"),
            ("minecraft:stained_glass", "stained_glass"),
            ("minecraft:stained_glass_pane", "stained_glass_pane"),
            ("minecraft:hard_stained_glass", "stained_glass"),
            ("minecraft:hard_stained_glass_pane", "stained_glass_pane"),
        ]:
            added += int(_alias_variant_icon(icons, _variant_key(base, damage), f"minecraft:{color}_{suffix}"))
        added += int(_alias_variant_icon(icons, _variant_key("minecraft:wool", damage), f"minecraft:{color}_wool"))
    for damage, color in enumerate(_DYE_COLOR_BY_DAMAGE):
        added += int(_alias_variant_icon(icons, _variant_key("minecraft:dye", damage), f"minecraft:{color}_dye"))
    for damage, item in _RED_FLOWER_BY_DAMAGE.items():
        added += int(_alias_variant_icon(icons, _variant_key("minecraft:red_flower", damage), f"minecraft:{item}"))
    for damage, item in _DOUBLE_PLANT_BY_DAMAGE.items():
        added += int(_alias_variant_icon(icons, _variant_key("minecraft:double_plant", damage), f"minecraft:{item}"))
    for base in ["minecraft:double_stone_slab", "minecraft:double_stone_slab2", "minecraft:double_stone_slab3", "minecraft:double_stone_slab4"]:
        for damage, item in _DOUBLE_STONE_SLAB_BY_DAMAGE.items():
            added += int(_alias_variant_icon(icons, _variant_key(base, damage), f"minecraft:{item}"))
    for base in ["minecraft:stone_block_slab", "minecraft:stone_block_slab2", "minecraft:stone_block_slab3", "minecraft:stone_block_slab4"]:
        for damage, item in _STONE_BLOCK_SLAB_BY_DAMAGE.items():
            added += int(_alias_variant_icon(icons, _variant_key(base, damage), f"minecraft:{item}"))
    return added


def _scan_directory(
    root: Path,
    source_label: str,
    icons: dict[str, IconCandidate],
    display_assets: dict[str, IconCandidate],
    scanned: int,
) -> tuple[int, list[str]]:
    warnings: list[str] = []
    try:
        # pathlib's recursive glob may silently yield no entries when the root
        # itself is unreadable. Probe one directory entry first so diagnostics
        # do not report an inaccessible source as healthy and empty.
        with os.scandir(root) as entries:
            next(entries, None)
        for path in root.rglob("*"):
            if scanned >= _MAX_SCAN_FILES:
                warnings.append(t("Scan-Limit erreicht ({limit} Dateien). Weitere Icons wurden übersprungen.", limit=_MAX_SCAN_FILES))
                break
            if not path.is_file():
                continue
            scanned += 1
            is_display_asset = _parts_look_like_display_asset(path.parts, path.suffix)
            if not is_display_asset and not _looks_like_icon(path):
                continue
            if is_display_asset:
                st = _safe_stat(path)
                if not st or not 0 < st.st_size <= _MAX_FILE_BYTES:
                    continue
            asset_id = _normalize_display_asset_id(path.stem) if is_display_asset else _normalize_item_id(path.stem)
            if not asset_id:
                continue
            target = display_assets if is_display_asset else icons
            _add_icon(target, IconCandidate(item_id=asset_id, path=path, source=source_label, token=_token_for(path)))
    except OSError as exc:
        warnings.append(f"{root}: {exc.__class__.__name__}: {exc}")
    return scanned, warnings


def _scan_archive(
    path: Path,
    source_label: str,
    icons: dict[str, IconCandidate],
    display_assets: dict[str, IconCandidate],
    scanned: int,
) -> tuple[int, list[str]]:
    warnings: list[str] = []
    try:
        with zipfile.ZipFile(path) as zf:
            infos = zf.infolist()
            if len(infos) > _MAX_ARCHIVE_MEMBERS:
                warnings.append(
                    t("{name}: Archiv enthält sehr viele Dateien; nur die ersten {limit} Einträge werden geprüft.", name=path.name, limit=_MAX_ARCHIVE_MEMBERS)
                )
                infos = infos[:_MAX_ARCHIVE_MEMBERS]
            for info in infos:
                if scanned >= _MAX_SCAN_FILES:
                    warnings.append(t("Scan-Limit erreicht ({limit} Dateien). Weitere Icons wurden übersprungen.", limit=_MAX_SCAN_FILES))
                    break
                scanned += 1
                member_path = PurePosixPath(info.filename.replace("\\", "/"))
                is_display_asset = (
                    not info.is_dir() and 0 < info.file_size <= _MAX_FILE_BYTES and _parts_look_like_display_asset(member_path.parts, member_path.suffix)
                )
                if not is_display_asset and not _archive_member_looks_like_icon(info):
                    continue
                member = info.filename.replace("\\", "/")
                asset_id = _normalize_display_asset_id(member_path.stem) if is_display_asset else _normalize_item_id(member_path.stem)
                if not asset_id:
                    continue
                archive_stat = _safe_stat(path)
                revision = f"{getattr(archive_stat, 'st_size', 0)}:{getattr(archive_stat, 'st_mtime_ns', 0)}:{info.CRC}:{info.file_size}"
                token = _token_for_text(f"{path.resolve()}::{member}::{revision}")
                target = display_assets if is_display_asset else icons
                _add_icon(target, IconCandidate(item_id=asset_id, path=None, archive_path=path, archive_member=member, source=source_label, token=token))
    except (OSError, zipfile.BadZipFile) as exc:
        warnings.append(f"{path}: {exc.__class__.__name__}: {exc}")
    return scanned, warnings


def _build_health_summary(icons: dict[str, IconCandidate], sources: list[dict], warnings: list[str]) -> dict:
    enabled = [s for s in sources if s.get("enabled", True)]
    existing = [s for s in enabled if s.get("exists")]
    sample = []
    for item_id in _COMMON_PREVIEW_IDS:
        candidate = icons.get(item_id)
        sample.append(
            {
                "item_id": item_id,
                "found": bool(candidate),
                "source": candidate.source if candidate else "",
                "url": f"/api/icons/{candidate.token}" if candidate else "",
            }
        )
    return {
        "status": "ok" if icons else ("warning" if existing else "empty"),
        "enabled_sources": len(enabled),
        "existing_sources": len(existing),
        "manual_sources": sum(1 for s in sources if s.get("manual")),
        "archive_sources": sum(1 for s in sources if s.get("archive")),
        "sample_found": sum(1 for row in sample if row["found"]),
        "sample_total": len(sample),
        "sample": sample,
        "warning_count": len(warnings),
    }


def _public_result(
    icons: dict[str, IconCandidate],
    display_assets: dict[str, IconCandidate],
    public_sources: list[dict],
    scanned: int,
    warnings: list[str],
    settings_path: str | None,
    *,
    variant_aliases: int = 0,
    cache_state: str,
    cache_path: Path | None,
    source_signature: str,
) -> dict:
    by_token = {candidate.token: candidate for candidate in (*icons.values(), *display_assets.values())}
    return {
        "success": True,
        "enabled": True,
        "strategy": "local-extraction-no-bundled-assets",
        "roots": [{"path": str(source.get("path")), "exists": bool(source.get("exists"))} for source in public_sources if source.get("enabled")],
        "sources": public_sources,
        "count": len(icons),
        "display_count": len(display_assets),
        "variant_aliases": variant_aliases,
        "scanned_files": scanned,
        "warnings": warnings,
        "settings_path": settings_path,
        "cache": {
            "state": cache_state,
            "path": str(cache_path) if cache_path else "",
            "signature": source_signature,
            "generated_at": time.time() if cache_state == "rebuilt" else None,
        },
        "health": _build_health_summary(icons, public_sources, warnings),
        "icons": {
            item_id: {
                "url": f"/api/icons/{candidate.token}",
                "source": candidate.source,
                "token": candidate.token,
            }
            for item_id, candidate in sorted(icons.items())
        },
        "display_icons": {
            asset_id: {
                "url": f"/api/icons/{candidate.token}",
                "source": candidate.source,
                "token": candidate.token,
            }
            for asset_id, candidate in sorted(display_assets.items())
        },
        "_by_token": by_token,
    }


def _load_cached_result(cache_path: Path, sources_signature: str, settings_path: str | None) -> dict | None:
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        return None
    if not isinstance(data, dict) or data.get("version") != _INDEX_FILE_VERSION:
        return None
    if data.get("sources_signature") != sources_signature:
        return None
    icons_raw = data.get("icons")
    display_assets_raw = data.get("display_icons", {})
    public_sources = data.get("sources")
    if not isinstance(icons_raw, dict) or not isinstance(display_assets_raw, dict) or not isinstance(public_sources, list):
        return None
    if any(not isinstance(source, dict) for source in public_sources):
        return None
    icons: dict[str, IconCandidate] = {}
    for item_id, entry in icons_raw.items():
        if not isinstance(entry, dict):
            continue
        candidate = IconCandidate.from_cache_entry(entry)
        if candidate and candidate.item_id == str(item_id).lower():
            icons[candidate.item_id] = candidate
    display_assets: dict[str, IconCandidate] = {}
    for asset_id, entry in display_assets_raw.items():
        if not isinstance(entry, dict):
            continue
        candidate = IconCandidate.from_cache_entry(entry)
        if candidate and candidate.item_id == str(asset_id).lower():
            display_assets[candidate.item_id] = candidate
    warnings_raw = data.get("warnings")
    warnings = [str(value) for value in warnings_raw] if isinstance(warnings_raw, list) else []
    scanned = max(0, _safe_int(data.get("scanned_files"), 0))
    variant_aliases = max(0, _safe_int(data.get("variant_aliases"), 0))
    return _public_result(
        icons,
        display_assets,
        public_sources,
        scanned,
        [str(w) for w in warnings],
        settings_path,
        variant_aliases=variant_aliases,
        cache_state="hit",
        cache_path=cache_path,
        source_signature=sources_signature,
    )


def load_cached_icon_index(settings_path: str | None = None) -> dict | None:
    """Load the last published icon index without scanning or writing files."""

    cache_path = _cache_file(settings_path)
    if not cache_path or not cache_path.exists():
        return None
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        return None
    sources_signature = data.get("sources_signature") if isinstance(data, dict) else None
    if not isinstance(sources_signature, str) or not sources_signature:
        return None
    cached_sources = data.get("sources")
    if not isinstance(cached_sources, list) or any(not isinstance(source, dict) for source in cached_sources):
        return None
    # Read-only darf den veröffentlichten Index nutzen, aber keine veralteten
    # Dateiverweise übernehmen, wenn sich eine gecachte Quelle geändert hat.
    if _sources_signature(cached_sources) != sources_signature:
        return None
    return _load_cached_result(cache_path, sources_signature, settings_path)


def _write_cache(cache_path: Path | None, result: dict, sources_signature: str) -> None:
    if not cache_path:
        return
    temp_name = None
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        icons_raw = result.get("_by_token", {})
        # Store by item ID instead of token so the cache stays compact and stable.
        by_item: dict[str, dict] = {}
        for item_id, public in result.get("icons", {}).items():
            token = public.get("token") if isinstance(public, dict) else None
            candidate = icons_raw.get(token) if token else None
            if isinstance(candidate, IconCandidate):
                entry = candidate.to_cache_entry()
                # Mehrere IDs dürfen dieselbe Datei und damit denselben Token
                # teilen (z. B. blue_dye und der Legacy-Alias dye#4). Der
                # Token-Lookup liefert irgendeinen dieser Kandidaten; im
                # persistenten By-Item-Index müssen ID und sichtbare Quelle
                # jedoch zum jeweiligen Eintrag gehören.
                entry["item_id"] = item_id
                entry["source"] = str(public.get("source") or candidate.source)
                by_item[item_id] = entry
        by_display_asset: dict[str, dict] = {}
        for asset_id, public in result.get("display_icons", {}).items():
            token = public.get("token") if isinstance(public, dict) else None
            candidate = icons_raw.get(token) if token else None
            if isinstance(candidate, IconCandidate):
                entry = candidate.to_cache_entry()
                entry["item_id"] = asset_id
                entry["source"] = str(public.get("source") or candidate.source)
                by_display_asset[asset_id] = entry
        payload = {
            "version": _INDEX_FILE_VERSION,
            "sources_signature": sources_signature,
            "generated_at": time.time(),
            "sources": result.get("sources", []),
            "warnings": result.get("warnings", []),
            "scanned_files": result.get("scanned_files", 0),
            "count": result.get("count", 0),
            "variant_aliases": result.get("variant_aliases", 0),
            "icons": by_item,
            "display_icons": by_display_asset,
        }
        fd, temp_name = tempfile.mkstemp(prefix=f".{cache_path.name}.", suffix=".tmp", dir=cache_path.parent)
        with os.fdopen(fd, "w", encoding="utf-8") as temp_file:
            json.dump(payload, temp_file, ensure_ascii=False, indent=2, sort_keys=True)
            temp_file.write("\n")
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.replace(temp_name, cache_path)
    except OSError:
        # Cache is purely an optimization; never fail icon scanning because of it.
        if temp_name is not None:
            with suppress(OSError):
                os.remove(temp_name)
        return


def clear_icon_cache(settings_path: str | None) -> None:
    path = _cache_file(settings_path)
    if not path:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        return


def scan_icons(
    settings_path: str | None = None,
    *,
    force: bool = False,
    extra_sources: Iterable[dict | str | os.PathLike] | None = None,
) -> dict:
    # Der Scan folgt allein der konfigurierten Quellen-Priorität; der erste
    # Treffer je Bezeichner gewinnt. Eine Liste erwarteter IDs schränkt das
    # Ergebnis bewusst nicht ein, damit Zusatzpakete vollständig erfasst werden.
    sources = configured_icon_sources(settings_path, extra_sources=extra_sources)
    source_signature = _sources_signature(sources)
    cache_path = _cache_file(settings_path)
    if not force and cache_path and cache_path.exists():
        cached = _load_cached_result(cache_path, source_signature, settings_path)
        if cached:
            return cached

    icons: dict[str, IconCandidate] = {}
    display_assets: dict[str, IconCandidate] = {}
    scanned = 0
    warnings: list[str] = []
    public_sources: list[dict] = []

    for source in sources:
        raw_path = str(source.get("path") or "")
        path = Path(raw_path).expanduser()
        exists = path.exists()
        enabled = bool(source.get("enabled", True))
        archive = _is_supported_archive(path)
        label = str(source.get("label") or _source_label(path, manual=bool(source.get("manual")), archive=archive))
        before = len(icons) + len(display_assets)
        source_warnings: list[str] = []
        if enabled and exists:
            if archive:
                scanned, source_warnings = _scan_archive(path, label, icons, display_assets, scanned)
            elif path.is_dir():
                scanned, source_warnings = _scan_directory(path, label, icons, display_assets, scanned)
            else:
                source_warnings = [t("{path}: keine unterstützte Icon-Quelle.", path=path)]
            warnings.extend(source_warnings)
        public_sources.append(
            {
                "path": raw_path,
                "label": label,
                "enabled": enabled,
                "priority": _safe_int(source.get("priority"), 0),
                "exists": exists,
                "manual": bool(source.get("manual")),
                "auto": bool(source.get("auto")),
                "vanilla": bool(source.get("vanilla")),
                "env": bool(source.get("env")),
                "world": bool(source.get("world")),
                "archive": archive,
                "count": max(0, len(icons) + len(display_assets) - before),
                "status": "disabled" if not enabled else ("missing" if not exists else ("warning" if source_warnings else "ok")),
                "warning_count": len(source_warnings),
            }
        )

    variant_aliases = _add_variant_alias_icons(icons)
    result = _public_result(
        icons,
        display_assets,
        public_sources,
        scanned,
        warnings,
        settings_path,
        variant_aliases=variant_aliases,
        cache_state="rebuilt",
        cache_path=cache_path,
        source_signature=source_signature,
    )
    _write_cache(cache_path, result, source_signature)
    return result
