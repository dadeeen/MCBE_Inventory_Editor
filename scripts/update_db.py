#!/usr/bin/env python3
"""Aktualisiert item_db.json aus Mojang-Daten und lokal geprüften Vanilla-Fakten."""

import contextlib
import hashlib
import hmac
import html
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.parse
import urllib.request
import zipfile
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_runtime_dependencies():
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from mcbe_editor import item_db_transaction, item_db_verification, item_localization, update_source_quality
    from mcbe_editor.item_name_policy import (
        DOCUMENTED_ENGLISH_ITEM_IDS,
        EDITORIAL_ITEM_IDS_BY_LOCALE,
        EXPECTED_ITEM_NAME_DIFFERENCES,
        REPLACEABLE_CATALOG_ITEM_IDS,
        confirmed_item_label_pair,
        is_expected_item_name_difference,
        item_label_reference,
        reviewed_item_label_repairs,
        reviewed_variant_name_overrides,
    )
    from mcbe_editor.item_registry_policy import is_non_item_lang_key_id, is_technical_block_only_item_id
    from mcbe_editor.numeric_catalog_policy import canonical_numeric_name, reconcile_numeric_catalog
    from mcbe_editor.runtime_data import BUNDLED_ITEM_DB_JSON, atomic_seed_file
    from mcbe_editor.update_http_errors import report_http_errors
    from mcbe_editor.update_output_i18n import output_t
    from mcbe_editor.update_progress import report_progress

    return (
        BUNDLED_ITEM_DB_JSON,
        atomic_seed_file,
        item_db_verification,
        item_db_transaction,
        is_non_item_lang_key_id,
        is_technical_block_only_item_id,
        output_t,
        report_progress,
        reviewed_item_label_repairs,
        canonical_numeric_name,
        reconcile_numeric_catalog,
        report_http_errors,
        update_source_quality,
        item_localization,
        is_expected_item_name_difference,
        EDITORIAL_ITEM_IDS_BY_LOCALE,
        REPLACEABLE_CATALOG_ITEM_IDS,
        DOCUMENTED_ENGLISH_ITEM_IDS,
        EXPECTED_ITEM_NAME_DIFFERENCES,
        reviewed_variant_name_overrides,
        item_label_reference,
        confirmed_item_label_pair,
    )


(
    BUNDLED_ITEM_DB_JSON,
    atomic_seed_file,
    item_db_verification,
    item_db_transaction,
    is_non_item_lang_key_id,
    is_technical_block_only_item_id,
    tr,
    report_progress,
    reviewed_item_label_repairs,
    canonical_numeric_name,
    reconcile_numeric_catalog,
    report_http_errors,
    update_source_quality,
    item_localization,
    is_expected_item_name_difference,
    EDITORIAL_ITEM_IDS_BY_LOCALE,
    REPLACEABLE_CATALOG_ITEM_IDS,
    DOCUMENTED_ENGLISH_ITEM_IDS,
    EXPECTED_ITEM_NAME_DIFFERENCES,
    reviewed_variant_name_overrides,
    item_label_reference,
    confirmed_item_label_pair,
) = _load_runtime_dependencies()
DEFAULT_ITEM_DB_PATH = BUNDLED_ITEM_DB_JSON
DEFAULT_DATA_ROOT = REPO_ROOT / "data"
ENCHANTMENT_MAX_LEVELS_PATH = REPO_ROOT / "mcbe_editor" / "resources" / "enchantment_max_levels.json"


def _env_path(name: str, default: Path) -> Path:
    value = os.environ.get(name, "").strip()
    return Path(value).expanduser() if value else default


ITEM_DB_PATH = _env_path("MCBE_ITEM_DB_PATH", DEFAULT_ITEM_DB_PATH)
if ITEM_DB_PATH.suffix.lower() == ".py":
    ITEM_DB_PATH = ITEM_DB_PATH.with_suffix(".json")
DATA_ROOT = _env_path("MCBE_DATA_ROOT", DEFAULT_DATA_ROOT)
CACHE_DIR = _env_path("MCBE_UPDATE_CACHE_DIR", DATA_ROOT / "cache" / "item_update")
RELEASE_METADATA_PATH = CACHE_DIR / "release_metadata.json"
ITEM_LISTING_CACHE_PATH = CACHE_DIR / item_db_verification.ITEM_LISTING_CACHE_FILENAME
SOURCE_VERSION_JSON = _env_path("MCBE_SOURCE_VERSION_PATH", DATA_ROOT / "source_version.json")
SOURCE_VERSION_HISTORY = _env_path("MCBE_SOURCE_VERSION_HISTORY_PATH", DATA_ROOT / "source_version_history.json")
# Writers and the recovery journal must address the same canonical targets,
# including when a direct CLI invocation configures relative paths or symlinks.
ITEM_DB_PATH, SOURCE_VERSION_JSON, SOURCE_VERSION_HISTORY = item_db_transaction.configured_targets(ITEM_DB_PATH, SOURCE_VERSION_JSON, SOURCE_VERSION_HISTORY)

RP_OWNER = "Mojang"
RP_REPO = "bedrock-samples"
RP_LATEST_API = f"https://api.github.com/repos/{RP_OWNER}/{RP_REPO}/releases/latest"
WIKI_ENCHANTMENTS_URL = "https://minecraft.wiki/w/Enchantment"
MICROSOFT_ITEM_LISTINGS_URL = (
    "https://learn.microsoft.com/en-us/minecraft/creator/reference/content/vanillalistingsreference/items?view=minecraft-bedrock-stable"
)

MAX_RESOURCE_PACK_BYTES = 200 * 1024 * 1024
MAX_RESOURCE_PACK_MEMBERS = 100_000
MAX_RESOURCE_PACK_MEMBER_BYTES = 128 * 1024 * 1024
MAX_RESOURCE_PACK_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024
MAX_WIKI_BYTES = 8 * 1024 * 1024
MAX_MICROSOFT_LEARN_BYTES = 8 * 1024 * 1024
ALLOWED_GITHUB_API_HOSTS = {"api.github.com"}
ALLOWED_RESOURCE_PACK_HOSTS = {"github.com", "objects.githubusercontent.com", "github-releases.githubusercontent.com", "release-assets.githubusercontent.com"}
ALLOWED_WIKI_HOSTS = {"minecraft.wiki", "www.minecraft.wiki"}
ALLOWED_MICROSOFT_LEARN_HOSTS = {"learn.microsoft.com"}

# Einige Vanilla-Items sind weiterhin fest in der Bedrock-Engine definiert und
# fehlen deshalb in behavior_pack/items. Komponenten aus Mojangs Archiv haben
# beim Zusammenführen Vorrang, sobald ein Item dort datengetrieben vorliegt.
# Der Haltbarkeitswert entspricht dem maximal gespeicherten tag.Damage-Wert.
CURATED_ENGINE_STACK_LIMITS = {
    "minecraft:brush": 1,
    "minecraft:copper_axe": 1,
    "minecraft:copper_boots": 1,
    "minecraft:copper_chestplate": 1,
    "minecraft:copper_helmet": 1,
    "minecraft:copper_hoe": 1,
    "minecraft:copper_leggings": 1,
    "minecraft:copper_pickaxe": 1,
    "minecraft:copper_shovel": 1,
    "minecraft:copper_sword": 1,
    "minecraft:iron_hoe": 1,
    "minecraft:leather_boots": 1,
    "minecraft:leather_chestplate": 1,
    "minecraft:leather_helmet": 1,
    "minecraft:leather_leggings": 1,
    "minecraft:mace": 1,
    "minecraft:turtle_helmet": 1,
    "minecraft:wolf_armor": 1,
}

CURATED_ENGINE_DURABILITY = {
    "minecraft:brush": 64,
    "minecraft:copper_axe": 190,
    "minecraft:copper_boots": 143,
    "minecraft:copper_chestplate": 176,
    "minecraft:copper_helmet": 121,
    "minecraft:copper_hoe": 190,
    "minecraft:copper_leggings": 165,
    "minecraft:copper_pickaxe": 190,
    "minecraft:copper_shovel": 190,
    "minecraft:copper_sword": 190,
    "minecraft:crossbow": 464,
    "minecraft:mace": 500,
    "minecraft:turtle_helmet": 275,
    "minecraft:wolf_armor": 64,
}

# Include explicit 64s from the reviewed snapshot as well. Registry membership
# or an item name never proves a stack size. Do not retain data-driven values
# here: a later Mojang release may remove those components again.
_bundled_limits = json.loads(BUNDLED_ITEM_DB_JSON.read_text(encoding="utf-8"))
_bundled_component_ids = set(_bundled_limits.get("behavior_item_source", {}).get("stack_limit_items", []))
CURATED_ENGINE_STACK_LIMITS = {
    **CURATED_ENGINE_STACK_LIMITS,
    **{item_id: limit for item_id, limit in _bundled_limits.get("stack_limits", {}).items() if item_id not in _bundled_component_ids},
}

# The engine suite also verifies every durability component. Keep those reviewed
# facts when updating an older persistent database; current explicit components
# still take precedence in merge_item_limits.
_bundled_durability_ids = set(_bundled_limits.get("behavior_item_source", {}).get("durability_items", []))
CURATED_ENGINE_DURABILITY = {
    **CURATED_ENGINE_DURABILITY,
    **{item_id: limit for item_id, limit in _bundled_limits.get("durability", {}).items() if item_id not in _bundled_durability_ids},
}

# Nur Komponenten, die im Editor tatsächlich eine Entscheidung treffen:
# ``enchantable`` bestimmt die Verzauberungs-Kompatibilität, ``wearable`` die
# Rüstungsslots und ``allow_off_hand`` die Nebenhand. Weitere Komponenten werden nicht extrahiert;
# unbenutzte Daten mit fail-closed-Validierung können nur schaden.
TRACKED_ITEM_COMPONENTS = (
    "enchantable",
    "wearable",
    "allow_off_hand",
)
KNOWN_ENCHANTABLE_SLOTS = {
    "all",
    "armor_feet",
    "armor_head",
    "armor_legs",
    "armor_torso",
    "axe",
    "bow",
    "brush",
    "carrot_stick",
    "compass",
    "cosmetic_head",
    "crossbow",
    "elytra",
    "fishing_rod",
    "flintsteel",
    "g_armor",
    "g_digging",
    "g_tool",
    "hoe",
    "mace",
    "melee_spear",
    "none",
    "pickaxe",
    "shears",
    "shield",
    "shovel",
    "spear",
    "sword",
}
KNOWN_WEARABLE_SLOTS = {
    "slot.armor.body",
    "slot.armor.chest",
    "slot.armor.feet",
    "slot.armor.head",
    "slot.armor.legs",
    "slot.weapon.mainhand",
    "slot.weapon.offhand",
}


# .lang → JSON name mapping for effects (where they differ)
EFFECT_LANG_TO_JSON = {
    "badOmen": "bad_omen",
    "confusion": "nausea",
    "customNautilus": "breath_of_the_nautilus",
    "damageBoost": "strength",
    "digSlowDown": "mining_fatigue",
    "digSpeed": "haste",
    "fatalPoison": "fatal_poison",
    "fireResistance": "fire_resistance",
    "harm": "instant_damage",
    "heal": "instant_health",
    "healthBoost": "health_boost",
    "instantDamage": "instant_damage",
    "instantHealth": "instant_health",
    "jump": "jump_boost",
    "jumpBoost": "jump_boost",
    "miningFatigue": "mining_fatigue",
    "moveSlowdown": "slowness",
    "moveSpeed": "speed",
    "nightVision": "night_vision",
    "waterBreathing": "water_breathing",
    "slowFalling": "slow_falling",
    "villageHero": "village_hero",
    "trialOmen": "trial_omen",
    "raidOmen": "raid_omen",
    "windCharged": "wind_charged",
    "conduitPower": "conduit_power",
}

# .lang → JSON name mapping for enchantments (where they differ)
ENCH_LANG_TO_JSON = {
    "aquaAffinity": "aqua_affinity",
    "arrowDamage": "power",
    "arrowFire": "flame",
    "arrowInfinite": "infinity",
    "arrowKnockback": "punch",
    "baneOfArthropods": "bane_of_arthropods",
    "blastProtection": "blast_protection",
    "crossbowMultishot": "multishot",
    "crossbowPiercing": "piercing",
    "crossbowQuickCharge": "quick_charge",
    "curse.binding": "binding_curse",
    "curse.vanishing": "vanishing_curse",
    "damage.all": "sharpness",
    "damage.arthropods": "bane_of_arthropods",
    "damage.undead": "smite",
    "depthStrider": "depth_strider",
    "digging": "efficiency",
    "durability": "unbreaking",
    "featherFalling": "feather_falling",
    "fire": "fire_aspect",
    "fireAspect": "fire_aspect",
    "fireProtection": "fire_protection",
    "fishingSpeed": "lure",
    "frostwalker": "frost_walker",
    "frostWalker": "frost_walker",
    "heavy_weapon.breach": "breach",
    "heavy_weapon.density": "density",
    "heavy_weapon.windburst": "wind_burst",
    "lootBonus": "looting",
    "lootBonusDigger": "fortune",
    "lootBonusFishing": "luck_of_the_sea",
    "luckOfTheSea": "luck_of_the_sea",
    "oxygen": "respiration",
    "projectileProtection": "projectile_protection",
    "protect.all": "protection",
    "protect.explosion": "blast_protection",
    "protect.fall": "feather_falling",
    "protect.fire": "fire_protection",
    "protect.projectile": "projectile_protection",
    "quickCharge": "quick_charge",
    "respiration": "respiration",
    "silkTouch": "silk_touch",
    "soulSpeed": "soul_speed",
    "swiftSneak": "swift_sneak",
    "tridentChanneling": "channeling",
    "tridentImpaling": "impaling",
    "tridentLoyalty": "loyalty",
    "tridentRiptide": "riptide",
    "untouching": "silk_touch",
    "waterWalker": "depth_strider",
    "waterWorker": "aqua_affinity",
    "windBurst": "wind_burst",
}

# Mojang's JSON identifiers, .lang keys and the legacy names in item_db.py do not
# always use the same canonical name. Without these aliases the updater creates
# duplicate numeric IDs, which is unsafe because the UI writes these IDs back into
# player NBT data.
NON_ITEM_LANG_IDENTIFIER_PREFIXES = (
    "axolotlcolor",
    "tropicalcolor",
    "tropicalschool",
    # tile.glazedTerracotta*.name sind reine Lokalisierungsschluessel; die echten
    # Bedrock-IDs heissen <farbe>_glazed_terracotta (mojang-items.json).
    "glazedterracotta",
)


def _validate_https_url(url: str, allowed_hosts: set[str], *, label: str) -> str:
    try:
        parsed = urllib.parse.urlparse(url)
        host = (parsed.hostname or "").lower()
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise RuntimeError(tr("Unsichere {label}-URL: {url}", label=label, url=repr(url))) from exc
    if parsed.scheme.lower() != "https" or host not in allowed_hosts or port not in (None, 443) or parsed.username is not None or parsed.password is not None:
        raise RuntimeError(tr("Unsichere {label}-URL: {url}", label=label, url=repr(url)))
    return url


class _AllowlistedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject redirects before urllib contacts a non-allowlisted target."""

    def __init__(self, allowed_hosts: set[str], *, label: str):
        super().__init__()
        self._allowed_hosts = frozenset(allowed_hosts)
        self._label = label

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        resolved_url = urllib.parse.urljoin(req.full_url, newurl)
        _validate_https_url(resolved_url, self._allowed_hosts, label=self._label)
        return super().redirect_request(req, fp, code, msg, headers, resolved_url)


def _build_validating_opener(allowed_hosts: set[str], *, label: str):
    return urllib.request.build_opener(_AllowlistedRedirectHandler(allowed_hosts, label=label))


def _validate_final_response_url(resp, allowed_hosts: set[str], *, label: str) -> None:
    final_url = getattr(resp, "url", None) or resp.geturl()
    _validate_https_url(final_url, allowed_hosts, label=label)


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_identifier(value: str) -> str:
    normalized = str(value).replace("minecraft:", "", 1).strip().lower()
    normalized = normalized.replace(" ", "_").replace("-", "_")
    return re.sub(r"_+", "_", normalized)


def _canonical_effect_identifier(value: str) -> str:
    return canonical_numeric_name(value)


def _canonical_enchantment_identifier(value: str) -> str:
    return canonical_numeric_name(value)


def _is_non_item_lang_identifier(identifier: str) -> bool:
    # Tooltip keys such as item.canBreak= match the legacy item key pattern.
    return any(identifier.startswith(prefix) for prefix in NON_ITEM_LANG_IDENTIFIER_PREFIXES) or is_non_item_lang_key_id(identifier)


_COLOR_OUTPUT_ENABLED = bool(getattr(sys.stdout, "isatty", lambda: False)()) and "NO_COLOR" not in os.environ


class Colors:
    GREEN = "\033[92m" if _COLOR_OUTPUT_ENABLED else ""
    YELLOW = "\033[93m" if _COLOR_OUTPUT_ENABLED else ""
    RED = "\033[91m" if _COLOR_OUTPUT_ENABLED else ""
    CYAN = "\033[96m" if _COLOR_OUTPUT_ENABLED else ""
    BOLD = "\033[1m" if _COLOR_OUTPUT_ENABLED else ""
    DIM = "\033[2m" if _COLOR_OUTPUT_ENABLED else ""
    END = "\033[0m" if _COLOR_OUTPUT_ENABLED else ""


def log(msg: str, color: str = "") -> None:
    suffix = Colors.END if Colors.END and (color or "\033[" in msg) and not msg.endswith(Colors.END) else ""
    try:
        print(f"{color}{msg}{suffix}")
    except UnicodeEncodeError:
        safe = msg.encode("utf-8", errors="replace").decode("utf-8")
        print(f"{color}{safe}{suffix}")


def step(msg: str) -> None:
    print(f"\n{Colors.BOLD}{Colors.CYAN}--- {msg} ---{Colors.END}")


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def sha256_text(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.remove(tmp_name)
        raise


def fetch_github_json(url: str) -> dict:
    _validate_https_url(url, ALLOWED_GITHUB_API_HOSTS, label="GitHub-API")
    opener = _build_validating_opener(ALLOWED_GITHUB_API_HOSTS, label="GitHub-API")
    opener.addheaders = [("User-Agent", "MCBE-Inventory-Editor-Updater/1.0")]
    try:
        with opener.open(url, timeout=30) as resp:
            _validate_final_response_url(resp, ALLOWED_GITHUB_API_HOSTS, label="GitHub-API")
            raw = resp.read(5 * 1024 * 1024 + 1)
            if len(raw) > 5 * 1024 * 1024:
                raise RuntimeError(tr("GitHub-API-Antwort ist unerwartet groß."))
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise RuntimeError(tr("GitHub-API-Antwort hat ein unerwartetes JSON-Format."))
            return data
    except (OSError, TimeoutError) as exc:
        raise RuntimeError(tr("Fehler beim Laden von {url}: {error}", url=url, error=exc)) from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(tr("Ungültige JSON-Antwort von {url}: {error}", url=url, error=exc)) from exc


def get_latest_release_info() -> dict:
    log(f"  {tr('Suche nach dem neuesten Release...')}", Colors.YELLOW)
    data = fetch_github_json(RP_LATEST_API)
    tag = data.get("tag_name", "unknown")
    log(f"  {tr('Gefunden:')} {Colors.CYAN}{tag}{Colors.END} ({tr('offizielles Mojang/bedrock-samples-Release')})")
    assets = data.get("assets")
    if not isinstance(assets, list):
        raise RuntimeError(tr("GitHub-API-Antwort enthält keine gültige Asset-Liste."))
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        asset_name = str(asset.get("name", ""))
        asset_size = _safe_int(asset.get("size"), 0)
        if asset_name.endswith("-min.zip"):
            if asset_size <= 0 or asset_size > MAX_RESOURCE_PACK_BYTES:
                raise RuntimeError(tr("Resource-Pack-Asset hat eine unerwartete Größe: {size} Bytes", size=asset_size))
            download_url = _validate_https_url(str(asset.get("browser_download_url", "")), ALLOWED_RESOURCE_PACK_HOSTS, label="Resource-Pack")
            info = {
                "resource_pack_release": tag,
                "resource_pack_asset": asset_name,
                "resource_pack_asset_size": asset_size,
                "resource_pack_fetched_at": utc_now(),
                "resource_pack_url": download_url,
            }
            log(f"  {tr('Asset:')} {Colors.GREEN}{asset_name}{Colors.END} ({asset_size // 1024 // 1024} MB)")
            return info
    raise RuntimeError(tr("Kein Min-Asset im Release {release} gefunden.", release=tag))


def write_release_metadata(info: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    atomic_write_text(RELEASE_METADATA_PATH, json.dumps(info, indent=2, sort_keys=True) + "\n")


def _valid_release_metadata(data: object) -> bool:
    if not isinstance(data, dict):
        return False
    if not all(
        isinstance(data.get(field), str) and data.get(field)
        for field in (
            "resource_pack_release",
            "resource_pack_asset",
            "resource_pack_url",
        )
    ):
        return False
    size = _safe_int(data.get("resource_pack_asset_size"), 0)
    if size <= 0 or size > MAX_RESOURCE_PACK_BYTES:
        return False
    try:
        _validate_https_url(str(data["resource_pack_url"]), ALLOWED_RESOURCE_PACK_HOSTS, label="Resource-Pack")
    except RuntimeError:
        return False
    return True


def read_release_metadata() -> dict:
    try:
        data = json.loads(RELEASE_METADATA_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        return {}
    return data if _valid_release_metadata(data) else {}


def _same_resource_pack_release(first: dict, second: dict) -> bool:
    fields = (
        "resource_pack_release",
        "resource_pack_asset",
        "resource_pack_asset_size",
        "resource_pack_url",
    )
    return bool(first) and bool(second) and all(first.get(field) == second.get(field) for field in fields)


def _matching_cached_release(dest: Path, latest_info: dict) -> dict:
    cached_info = read_release_metadata()
    if not _same_resource_pack_release(cached_info, latest_info) or not dest.is_file():
        return {}
    try:
        item_db_verification.validate_resource_pack_archive(dest, cached_info)
        report_progress("cached")
        _validate_downloaded_zip(dest)
    except (OSError, RuntimeError, item_db_verification.UpdateReviewError):
        return {}
    return cached_info


def ensure_data_paths() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    ITEM_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    SOURCE_VERSION_JSON.parent.mkdir(parents=True, exist_ok=True)
    SOURCE_VERSION_HISTORY.parent.mkdir(parents=True, exist_ok=True)
    if ITEM_DB_PATH != DEFAULT_ITEM_DB_PATH and not ITEM_DB_PATH.exists():
        atomic_seed_file(DEFAULT_ITEM_DB_PATH, ITEM_DB_PATH)


def get_latest_release_url() -> str:
    return get_latest_release_info()["resource_pack_url"]


class WikiTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._table_stack: list[dict] = []
        self._cell_stack: list[dict] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag == "table":
            self._table_stack.append({"rows": [], "row": None})
        elif tag == "tr" and self._table_stack:
            self._table_stack[-1]["row"] = {"cells": []}
        elif tag in ("td", "th") and self._table_stack and self._table_stack[-1]["row"] is not None:
            attrs_dict = dict(attrs)
            colspan = _parse_positive_int(attrs_dict.get("colspan"), 1)
            self._cell_stack.append({"text": [], "colspan": colspan})
        elif tag == "br":
            self._append_text("\n")
        elif tag == "img":
            alt = dict(attrs).get("alt")
            if alt:
                self._append_text(f" {alt} ")

    def handle_data(self, data: str) -> None:
        self._append_text(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in ("td", "th"):
            if not self._cell_stack or not self._table_stack:
                return
            cell = self._cell_stack.pop()
            row = self._table_stack[-1]["row"]
            if row is None:
                return
            text = _normalize_cell_text("".join(cell["text"]))
            for _ in range(cell["colspan"]):
                row["cells"].append(text)
        elif tag == "tr" and self._table_stack:
            row = self._table_stack[-1].pop("row", None)
            if row is not None:
                self._table_stack[-1]["rows"].append(row["cells"])
        elif tag == "table" and self._table_stack:
            self.tables.append(self._table_stack.pop()["rows"])

    def _append_text(self, text: str) -> None:
        if self._cell_stack:
            self._cell_stack[-1]["text"].append(text)


def _parse_positive_int(value: str | None, default: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _normalize_cell_text(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def fetch_wiki_enchantment_max_levels(url: str = WIKI_ENCHANTMENTS_URL) -> dict[str, int]:
    levels, _ = fetch_wiki_enchantment_snapshot(url)
    return levels


def fetch_wiki_enchantment_snapshot(url: str = WIKI_ENCHANTMENTS_URL) -> tuple[dict[str, int], dict]:
    log(f"  {Colors.YELLOW}{tr('Lade MaxLevel-Tabelle aus der Minecraft Wiki...')}{Colors.END}")
    _validate_https_url(url, ALLOWED_WIKI_HOSTS, label="Minecraft-Wiki")
    opener = _build_validating_opener(ALLOWED_WIKI_HOSTS, label="Minecraft-Wiki")
    opener.addheaders = [("User-Agent", "MCBE-Inventory-Editor-Updater/1.0")]
    try:
        with opener.open(url, timeout=30) as resp:
            _validate_final_response_url(resp, ALLOWED_WIKI_HOSTS, label="Minecraft-Wiki")
            raw = resp.read(MAX_WIKI_BYTES + 1)
            if len(raw) > MAX_WIKI_BYTES:
                raise RuntimeError(tr("Minecraft-Wiki-Antwort ist unerwartet groß."))
            content = raw.decode("utf-8", errors="replace")
    except (OSError, TimeoutError) as exc:
        message = tr("Fehler beim Laden der Minecraft Wiki MaxLevel-Tabelle: {error}", error=exc)
        log(f"  {Colors.RED}{message}{Colors.END}")
        raise RuntimeError(message) from exc
    return parse_wiki_enchantment_max_levels(content), {
        "wiki_url": url,
        "wiki_fetched_at": utc_now(),
        "wiki_revision_id": _extract_wiki_revision_id(content),
        "wiki_content_hash": sha256_text(content),
    }


def load_local_enchantment_max_levels(path: Path = ENCHANTMENT_MAX_LEVELS_PATH) -> dict[str, int]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(tr("Lokale Verzauberungs-Maximalstufen fehlen: {path}", path=path)) from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise RuntimeError(tr("Lokale Verzauberungs-Maximalstufen sind nicht lesbar: {path}: {error}", path=path, error=exc)) from exc

    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise RuntimeError(tr("Lokale Verzauberungs-Maximalstufen haben eine unbekannte Schema-Version"))
    raw_levels = data.get("max_levels")
    if not isinstance(raw_levels, dict) or not raw_levels:
        raise RuntimeError(tr("Lokale Verzauberungs-Maximalstufen enthalten keine Einträge"))

    levels: dict[str, int] = {}
    for raw_identifier, raw_level in raw_levels.items():
        if not isinstance(raw_identifier, str):
            raise RuntimeError(tr("Lokale Verzauberungs-Maximalstufen enthalten einen ungültigen Identifier"))
        identifier = _canonical_enchantment_identifier(raw_identifier)
        if identifier != raw_identifier or not re.fullmatch(r"[a-z0-9_]+", identifier):
            raise RuntimeError(tr("Lokale Verzauberungs-Maximalstufen enthalten keinen kanonischen Identifier: {identifier}", identifier=repr(raw_identifier)))
        if isinstance(raw_level, bool) or not isinstance(raw_level, int) or not 1 <= raw_level <= 255:
            raise RuntimeError(tr("Ungültige lokale Maximalstufe für {identifier}: {level}", identifier=identifier, level=repr(raw_level)))
        levels[identifier] = raw_level
    return dict(sorted(levels.items()))


def load_local_enchantment_numeric_ids(path: Path = ENCHANTMENT_MAX_LEVELS_PATH) -> dict[str, int]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(tr("Lokale numerische Verzauberungs-IDs fehlen: {path}", path=path)) from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise RuntimeError(tr("Lokale numerische Verzauberungs-IDs sind nicht lesbar: {path}: {error}", path=path, error=exc)) from exc

    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise RuntimeError(tr("Lokale numerische Verzauberungs-IDs haben eine unbekannte Schema-Version"))
    raw_ids = data.get("numeric_ids")
    if not isinstance(raw_ids, dict) or not raw_ids:
        raise RuntimeError(tr("Lokale numerische Verzauberungs-IDs enthalten keine Einträge"))

    numeric_ids: dict[str, int] = {}
    used_ids: dict[int, str] = {}
    for raw_identifier, raw_id in raw_ids.items():
        if not isinstance(raw_identifier, str):
            raise RuntimeError(tr("Lokale numerische Verzauberungs-IDs enthalten einen ungültigen Identifier"))
        identifier = _canonical_enchantment_identifier(raw_identifier)
        if identifier != raw_identifier or not re.fullmatch(r"[a-z0-9_]+", identifier):
            raise RuntimeError(tr("Lokale numerische Verzauberungs-IDs enthalten keinen kanonischen Identifier: {identifier}", identifier=repr(raw_identifier)))
        if isinstance(raw_id, bool) or not isinstance(raw_id, int) or not 0 <= raw_id <= 32767:
            raise RuntimeError(tr("Ungültige lokale numerische ID für {identifier}: {numeric_id}", identifier=identifier, numeric_id=repr(raw_id)))
        duplicate = used_ids.get(raw_id)
        if duplicate is not None:
            raise RuntimeError(
                tr(
                    "Numerische Verzauberungs-ID {numeric_id} ist doppelt vergeben: {first}, {second}",
                    numeric_id=raw_id,
                    first=duplicate,
                    second=identifier,
                )
            )
        numeric_ids[identifier] = raw_id
        used_ids[raw_id] = identifier
    return dict(sorted(numeric_ids.items()))


def load_local_effect_numeric_ids(path: Path = BUNDLED_ITEM_DB_JSON) -> dict[str, int]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(tr("Lokale numerische Effekt-IDs fehlen: {path}", path=path)) from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise RuntimeError(tr("Lokale numerische Effekt-IDs sind nicht lesbar: {path}: {error}", path=path, error=exc)) from exc

    raw_effects = data.get("effects") if isinstance(data, dict) else None
    if not isinstance(raw_effects, dict) or not raw_effects:
        raise RuntimeError(tr("Lokale numerische Effekt-IDs enthalten keine Einträge"))

    numeric_ids: dict[str, int] = {}
    used_ids: dict[int, str] = {}
    for raw_id, values in raw_effects.items():
        if not isinstance(values, (list, tuple)) or len(values) < 2:
            raise RuntimeError(tr("Ungültiger lokaler Effekt-Eintrag für ID {numeric_id}", numeric_id=repr(raw_id)))
        try:
            numeric_id = int(raw_id)
        except (TypeError, ValueError):
            raise RuntimeError(tr("Ungültige lokale numerische Effekt-ID: {numeric_id}", numeric_id=repr(raw_id))) from None
        if not 0 <= numeric_id <= 255:
            raise RuntimeError(tr("Lokale numerische Effekt-ID außerhalb des gültigen Bereichs: {numeric_id}", numeric_id=numeric_id))
        identifier = _canonical_effect_identifier(values[1] or values[0])
        if not re.fullmatch(r"[a-z0-9_]+", identifier):
            raise RuntimeError(tr("Lokaler Effekt hat keinen kanonischen Identifier: {identifier}", identifier=repr(values[1] or values[0])))
        duplicate_id = used_ids.get(numeric_id)
        if duplicate_id is not None:
            raise RuntimeError(
                tr(
                    "Numerische Effekt-ID {numeric_id} ist doppelt vergeben: {first}, {second}",
                    numeric_id=numeric_id,
                    first=duplicate_id,
                    second=identifier,
                )
            )
        duplicate_identifier = numeric_ids.get(identifier)
        if duplicate_identifier is not None:
            raise RuntimeError(
                tr(
                    "Effekt-Identifier {identifier} ist doppelt vergeben: {first}, {second}",
                    identifier=identifier,
                    first=duplicate_identifier,
                    second=numeric_id,
                )
            )
        numeric_ids[identifier] = numeric_id
        used_ids[numeric_id] = identifier
    return dict(sorted(numeric_ids.items()))


def diff_enchantment_max_levels(expected: dict[str, int], observed: dict[str, int]) -> dict[str, object]:
    expected_ids = set(expected)
    observed_ids = set(observed)
    return {
        "different": {
            identifier: {"local": expected[identifier], "wiki": observed[identifier]}
            for identifier in sorted(expected_ids & observed_ids)
            if expected[identifier] != observed[identifier]
        },
        "missing_in_wiki": sorted(expected_ids - observed_ids),
        "wiki_only": sorted(observed_ids - expected_ids),
    }


def optional_wiki_enchantment_check(enabled: bool, local_levels: dict[str, int]) -> dict | None:
    if not enabled:
        return None
    try:
        wiki_levels, snapshot = fetch_wiki_enchantment_snapshot()
    except RuntimeError as exc:
        log(f"  {Colors.YELLOW}{tr('Optionale Wiki-Prüfung nicht verfügbar: {error}', error=exc)}{Colors.END}")
        return None

    differences = diff_enchantment_max_levels(local_levels, wiki_levels)
    different = differences["different"]
    missing = differences["missing_in_wiki"]
    wiki_only = differences["wiki_only"]
    if not different and not missing and not wiki_only:
        log(f"  {Colors.GREEN}{tr('Wiki-Prüfung: lokale Maximalstufen stimmen überein')}{Colors.END}")
        return snapshot

    log(f"  {Colors.YELLOW}{tr('Wiki-Prüfung meldet Abweichungen; lokale Werte bleiben unverändert.')}{Colors.END}")
    for identifier, values in different.items():
        log(tr("    ~ {identifier}: lokal {local}, Wiki {wiki}", identifier=identifier, local=values["local"], wiki=values["wiki"]), Colors.YELLOW)
    if missing:
        log(tr("    - In der Wiki nicht gefunden: {identifiers}", identifiers=", ".join(missing)), Colors.YELLOW)
    if wiki_only:
        log(tr("    + Nur in der Wiki gefunden: {identifiers}", identifiers=", ".join(wiki_only)), Colors.YELLOW)
    return snapshot


def _extract_wiki_revision_id(content: str) -> int | None:
    match = re.search(r'"wgRevisionId"\s*:\s*(\d+)', content)
    return int(match.group(1)) if match else None


def parse_wiki_enchantment_max_levels(content: str) -> dict[str, int]:
    parser = WikiTableParser()
    parser.feed(content)
    parser.close()

    result: dict[str, int] = {}
    found_table = False
    skipped_rows: list[str] = []
    for table in parser.tables:
        if not table:
            continue
        header = [_normalize_cell_text(cell).lower() for cell in table[0]]
        if "identifier" not in header or "max level" not in header:
            continue
        found_table = True
        identifier_index = header.index("identifier")
        max_level_index = header.index("max level")
        for row in table[1:]:
            if len(row) <= max(identifier_index, max_level_index):
                continue
            identifier = _extract_wiki_identifier(row[identifier_index])
            max_level = _parse_roman_max_level(row[max_level_index])
            if identifier and max_level:
                result[identifier] = max_level
            elif identifier and max_level is None:
                skipped_rows.append(f"{identifier}: {row[max_level_index]!r}")
    if not found_table:
        message = tr("MaxLevel-Tabelle nicht in der Minecraft Wiki gefunden")
        log(f"  {Colors.RED}{message}{Colors.END}")
        raise RuntimeError(message)
    if not result:
        message = tr("Keine MaxLevel-Einträge aus der Minecraft Wiki geparst")
        log(f"  {Colors.RED}{message}{Colors.END}")
        raise RuntimeError(message)
    if skipped_rows:
        shown = ", ".join(skipped_rows[:5])
        message = tr(
            "Wiki-MaxLevel-Parser ignoriert {count} Zeilen ohne lesbares MaxLevel: {rows}",
            count=len(skipped_rows),
            rows=shown,
        )
        log(f"  {Colors.YELLOW}{message}{Colors.END}")
    return result


def _extract_wiki_identifier(text: str) -> str:
    lowered = text.lower()
    tokens = re.findall(r"[a-z0-9_]+", lowered)
    for index, token in enumerate(tokens):
        if token not in {"je", "be", "only", "combat", "tests"} and index + 1 < len(tokens) and tokens[index + 1] == "be":
            return token
    for token in tokens:
        if token not in {"je", "be", "only", "combat", "tests"}:
            return token
    return ""


def _parse_roman_max_level(text: str) -> int | None:
    value = re.sub(r"\s+", "", text)
    if not re.fullmatch(r"[IVXLCDM]+", value):
        return None
    values = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total = 0
    previous = 0
    for char in reversed(value):
        current = values[char]
        if current < previous:
            total -= current
        else:
            total += current
        previous = current
    return total


def _validate_downloaded_zip(path: Path) -> None:
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if len(members) > MAX_RESOURCE_PACK_MEMBERS:
                raise RuntimeError(tr("Resource-Pack-Download enthält unerwartet viele ZIP-Einträge."))
            total_uncompressed = 0
            for member in members:
                if member.file_size < 0 or member.file_size > MAX_RESOURCE_PACK_MEMBER_BYTES:
                    raise RuntimeError(tr("Resource-Pack-Download enthält einen unerwartet großen ZIP-Eintrag: {member}", member=member.filename))
                total_uncompressed += member.file_size
                if total_uncompressed > MAX_RESOURCE_PACK_UNCOMPRESSED_BYTES:
                    raise RuntimeError(tr("Resource-Pack-Download ist entpackt unerwartet groß."))
            damaged_member = archive.testzip()
    except (OSError, zipfile.BadZipFile) as exc:
        raise RuntimeError(tr("Resource-Pack-Download ist keine gültige ZIP-Datei.")) from exc
    if damaged_member:
        raise RuntimeError(tr("Resource-Pack-Download enthält einen beschädigten ZIP-Eintrag: {member}", member=damaged_member))


def download_with_progress(url: str, dest: Path, *, expected_size: int | None = None) -> None:
    log(f"  {tr('Wird heruntergeladen...')}", Colors.YELLOW)
    _validate_https_url(url, ALLOWED_RESOURCE_PACK_HOSTS, label="Resource-Pack")

    def report(downloaded: int, totalsize: int) -> None:
        report_progress("downloading", current=downloaded, total=expected_size or totalsize, unit="bytes")
        if totalsize > 0:
            pct = min(100, downloaded * 100 // totalsize)
            sys.stdout.write(f"\r  {tr('Wird heruntergeladen...')} {pct}%")
            sys.stdout.flush()

    opener = _build_validating_opener(ALLOWED_RESOURCE_PACK_HOSTS, label="Resource-Pack")
    opener.addheaders = [("User-Agent", "MCBE-Inventory-Editor-Updater/1.0")]
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{dest.name}.", suffix=".part", dir=dest.parent)
    temp_path = Path(temp_name)

    try:
        report_progress("downloading", current=0, total=expected_size, unit="bytes")
        with opener.open(url, timeout=60) as resp, os.fdopen(fd, "wb") as out:
            fd = -1
            _validate_final_response_url(resp, ALLOWED_RESOURCE_PACK_HOSTS, label="Resource-Pack")
            total = _safe_int(resp.headers.get("Content-Length"), 0)
            if total > MAX_RESOURCE_PACK_BYTES:
                raise RuntimeError(tr("Resource-Pack-Download ist unerwartet groß: {size} Bytes", size=total))
            downloaded = 0
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                downloaded += len(chunk)
                if downloaded > MAX_RESOURCE_PACK_BYTES:
                    raise RuntimeError(tr("Resource-Pack-Download überschreitet das Sicherheitslimit."))
                out.write(chunk)
                report(downloaded, total)
            out.flush()
            os.fsync(out.fileno())
        if expected_size and downloaded != expected_size:
            raise RuntimeError(
                tr(
                    "Resource-Pack-Download ist unvollständig: erwartet {expected} Bytes, erhalten {actual} Bytes",
                    expected=expected_size,
                    actual=downloaded,
                )
            )
        report_progress("validating")
        _validate_downloaded_zip(temp_path)
        os.replace(temp_path, dest)
        print(f"\r  {Colors.GREEN}{tr('Heruntergeladen')}{Colors.END} ({dest.name}){' ' * 20}")
    except Exception as exc:
        if fd >= 0:
            with contextlib.suppress(OSError):
                os.close(fd)
        with contextlib.suppress(OSError):
            temp_path.unlink()
        raise RuntimeError(tr("Download fehlgeschlagen: {error}", error=exc)) from exc


def download_latest_rp(dest: Path, *, release_info: dict | None = None) -> dict:
    info = release_info or get_latest_release_info()
    dest.parent.mkdir(parents=True, exist_ok=True)
    nonce = os.urandom(8).hex()
    candidate = dest.with_name(f".{dest.name}.{nonce}.candidate")
    rollback = dest.with_name(f".{dest.name}.{nonce}.rollback")
    old_moved = False
    published = False
    try:
        download_with_progress(
            info["resource_pack_url"],
            candidate,
            expected_size=_safe_int(info.get("resource_pack_asset_size"), 0) or None,
        )
        info = {**info, "resource_pack_archive_sha256": item_db_verification.file_sha256(candidate)}
        # Until both replacements finish, even equal-size archives must not be
        # paired with metadata from an interrupted older generation.
        pending = item_db_verification.resource_pack_pending_path(dest)
        atomic_write_text(pending, "pending\n")
        if dest.exists():
            os.replace(dest, rollback)
            old_moved = True
        os.replace(candidate, dest)
        published = True
        write_release_metadata(info)
        pending.unlink()
        if old_moved:
            with contextlib.suppress(OSError):
                rollback.unlink()
        return info
    except Exception as exc:
        restore_failure = None
        try:
            if old_moved and rollback.exists():
                # Replace the published candidate directly. Removing it first
                # would leave the cache path empty if the rollback rename then
                # failed; os.replace keeps either the new or the old complete
                # archive visible.
                os.replace(rollback, dest)
            elif published:
                with contextlib.suppress(FileNotFoundError):
                    dest.unlink()
        except OSError as rollback_exc:
            restore_failure = rollback_exc
        with contextlib.suppress(OSError):
            candidate.unlink()
        if restore_failure is not None:
            raise RuntimeError(
                tr(
                    "Resource-Pack-Cache konnte nach einem Metadatenfehler nicht wiederhergestellt werden: {error}",
                    error=restore_failure,
                )
            ) from exc
        raise
    finally:
        with contextlib.suppress(OSError):
            candidate.unlink()


def resolve_latest_rp(dest: Path) -> dict:
    """Resolve the latest release and reuse only a matching validated cache."""

    latest_info = get_latest_release_info()
    cached_info = _matching_cached_release(dest, latest_info)
    if cached_info:
        message = tr(
            "Cache ist aktuell: {release} ({asset})",
            release=cached_info["resource_pack_release"],
            asset=cached_info["resource_pack_asset"],
        )
        log(f"  {Colors.GREEN}{message}{Colors.END}")
        return cached_info
    if dest.exists():
        log(f"  {Colors.YELLOW}{tr('Cache ist veraltet oder ungültig; aktuelles Release wird geladen')}{Colors.END}")
    return download_latest_rp(dest, release_info=latest_info)


def open_zip(zip_path: Path) -> zipfile.ZipFile:
    """Open the min zip and return the ZipFile object."""
    try:
        return zipfile.ZipFile(zip_path, "r")
    except zipfile.BadZipFile:
        raise RuntimeError(tr("Beschädigte ZIP-Datei: {path}", path=zip_path)) from None


def read_utf8(zf: zipfile.ZipFile, path: str) -> str:
    """Read a text file from zip as UTF-8, stripping BOM."""
    return zf.read(path).decode("utf-8-sig")


# ─── ITEMS ─────────────────────────────────────────────────────────────────


def _strip_json_comments(text: str) -> str:
    """Remove JSONC comments without altering comment markers inside strings."""

    result: list[str] = []
    in_string = False
    escaped = False
    index = 0
    while index < len(text):
        char = text[index]
        nxt = text[index + 1] if index + 1 < len(text) else ""
        if in_string:
            result.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            result.append(char)
            index += 1
            continue
        if char == "/" and nxt == "/":
            index += 2
            while index < len(text) and text[index] not in "\r\n":
                index += 1
            continue
        if char == "/" and nxt == "*":
            index += 2
            while index + 1 < len(text) and not (text[index] == "*" and text[index + 1] == "/"):
                index += 1
            index = min(index + 2, len(text))
            continue
        result.append(char)
        index += 1
    return "".join(result)


def _component_error(member: str, component: str, detail: str) -> RuntimeError:
    return RuntimeError(
        tr(
            "Mojang-Itemkomponente {component} ist ungültig: {member}: {detail}",
            component=component,
            member=member,
            detail=detail,
        )
    )


def _normalize_enchantable_component(value, *, member: str) -> dict:
    component = "minecraft:enchantable"
    if not isinstance(value, dict):
        raise _component_error(member, component, tr("erwartet ein Objekt"))
    slot = str(value.get("slot", "")).strip()
    if slot not in KNOWN_ENCHANTABLE_SLOTS:
        raise _component_error(member, component, tr("unbekannter Slot {slot}", slot=repr(slot)))
    enchantability = value.get("value")
    if type(enchantability) is not int or not 0 <= enchantability <= 32767:
        raise _component_error(member, component, tr("value muss eine Ganzzahl zwischen 0 und 32767 sein"))
    return {"slot": slot, "value": enchantability}


def _normalize_allow_off_hand_component(value, *, member: str) -> dict:
    if isinstance(value, dict):
        value = value.get("value")
    if type(value) is not bool:
        raise _component_error(member, "minecraft:allow_off_hand", tr("value muss true oder false sein"))
    return {"value": value}


def _normalize_wearable_component(value, *, member: str) -> dict:
    component = "minecraft:wearable"
    if not isinstance(value, dict):
        raise _component_error(member, component, tr("erwartet ein Objekt"))
    slot = str(value.get("slot", "")).strip()
    if slot not in KNOWN_WEARABLE_SLOTS:
        raise _component_error(member, component, tr("unbekannter Slot {slot}", slot=repr(slot)))
    result: dict = {"slot": slot}
    for key in ("hides_player_location", "dispensable"):
        if key in value:
            if type(value[key]) is not bool:
                raise _component_error(member, component, tr("{key} muss ein Boolean sein", key=key))
            result[key] = value[key]
    if "protection" in value:
        protection = value["protection"]
        if type(protection) is not int or not 0 <= protection <= 32767:
            raise _component_error(member, component, tr("protection muss eine Ganzzahl zwischen 0 und 32767 sein"))
        result["protection"] = protection
    return result


def parse_json_item_components(zf: zipfile.ZipFile) -> tuple[dict[str, int], dict[str, int], dict[str, dict[str, dict]]]:
    """Read supported official components from Mojang behavior items.

    The min release archive contains data-driven vanilla item definitions under
    ``behavior_pack/items``. These component values are authoritative for new
    items such as spears and supplement the curated limits for engine-defined
    legacy items that do not have a behavior JSON file.
    """

    stack_limits: dict[str, int] = {}
    seen_components: dict[str, dict] = {}
    durability: dict[str, int] = {}
    tracked: dict[str, dict[str, dict]] = {component: {} for component in TRACKED_ITEM_COMPONENTS}
    for info in sorted(zf.infolist(), key=lambda entry: entry.filename.replace("\\", "/").lower()):
        member = info.filename.replace("\\", "/")
        if info.is_dir() or not member.startswith("behavior_pack/items/") or not member.endswith(".json"):
            continue
        try:
            payload = json.loads(_strip_json_comments(zf.read(info).decode("utf-8-sig")))
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
            raise RuntimeError(tr("Mojang-Itemdefinition ist ungültig: {member}: {error}", member=member, error=exc)) from exc
        item = payload.get("minecraft:item") if isinstance(payload, dict) else None
        if not isinstance(item, dict):
            raise _component_error(member, "minecraft:item", tr("erwartet ein Objekt"))
        description = item.get("description")
        if not isinstance(description, dict):
            raise _component_error(member, "minecraft:item.description", tr("erwartet ein Objekt"))
        identifier = description.get("identifier")
        if not isinstance(identifier, str):
            raise _component_error(member, "minecraft:item.description.identifier", tr("erwartet eine gültige Vanilla-Item-ID"))
        identifier = identifier.strip().lower()
        if identifier and not identifier.startswith("minecraft:"):
            identifier = f"minecraft:{identifier}"
        if not re.fullmatch(r"minecraft:[a-z0-9_.-]+", identifier):
            raise _component_error(member, "minecraft:item.description.identifier", tr("erwartet eine gültige Vanilla-Item-ID"))
        # Vanilla definitions such as honeycomb legitimately omit components.
        # A present, malformed value is damage, not evidence of their removal.
        components = item.get("components", {})
        if not isinstance(components, dict):
            raise _component_error(member, "minecraft:item.components", tr("erwartet ein Objekt"))

        normalized = {}
        if "minecraft:max_stack_size" in components:
            raw_stack = components["minecraft:max_stack_size"]
            # Both forms are documented by Mojang. An explicitly present empty
            # object uses the component's documented value default, unlike an
            # absent component on an engine-defined Vanilla item.
            if isinstance(raw_stack, dict):
                if set(raw_stack) - {"value"}:
                    raise _component_error(member, "max_stack_size", tr("unbekannte Felder"))
                raw_stack = raw_stack.get("value", 64)
            if type(raw_stack) is not int or not 1 <= raw_stack <= 127:
                raise _component_error(member, "max_stack_size", tr("value muss eine Ganzzahl zwischen 1 und 127 sein"))
            normalized["max_stack_size"] = raw_stack

        if "minecraft:durability" in components:
            durability_component = components["minecraft:durability"]
            if not isinstance(durability_component, dict):
                raise _component_error(member, "minecraft:durability", tr("erwartet ein Objekt"))
            raw_durability = durability_component.get("max_durability")
            if type(raw_durability) is not int or not 0 <= raw_durability <= 32767:
                raise _component_error(member, "minecraft:durability", tr("max_durability muss eine Ganzzahl zwischen 0 und 32767 sein"))
            normalized["durability"] = raw_durability

        normalizers = {
            "enchantable": _normalize_enchantable_component,
            "wearable": _normalize_wearable_component,
            "allow_off_hand": _normalize_allow_off_hand_component,
        }
        for component_name, normalizer in normalizers.items():
            namespaced_name = f"minecraft:{component_name}"
            if namespaced_name in components:
                normalized[component_name] = normalizer(components[namespaced_name], member=member)

        # A repeated identity must agree on every consumed fact, including its
        # presence. Unknown components do not participate in this comparison.
        if identifier in seen_components and seen_components[identifier] != normalized:
            raise _component_error(member, "minecraft:item", tr("widersprüchliche Itemkomponenten für {id}", id=identifier))
        seen_components[identifier] = normalized
        for component_name, destination in {"max_stack_size": stack_limits, "durability": durability, **tracked}.items():
            if component_name in normalized:
                destination[identifier] = normalized[component_name]

    return (
        dict(sorted(stack_limits.items())),
        dict(sorted(durability.items())),
        {name: dict(sorted(values.items())) for name, values in tracked.items()},
    )


def parse_json_item_component_limits(zf: zipfile.ZipFile) -> tuple[dict[str, int], dict[str, int]]:
    """Backward-compatible limit-only view of :func:`parse_json_item_components`."""

    stack_limits, durability, _components = parse_json_item_components(zf)
    return stack_limits, durability


def merge_item_limits(
    existing_stack_limits: dict[str, int],
    existing_durability: dict[str, int],
    component_stack_limits: dict[str, int],
    component_durability: dict[str, int],
    *,
    previous_component_stack_items: set[str] | frozenset[str] = frozenset(),
    previous_component_durability_items: set[str] | frozenset[str] = frozenset(),
) -> tuple[dict[str, int], dict[str, int]]:
    """Combine retained, curated and current data-driven Vanilla limits."""

    retained_stack_limits = {item_id: value for item_id, value in existing_stack_limits.items() if item_id not in previous_component_stack_items}
    retained_durability = {item_id: value for item_id, value in existing_durability.items() if item_id not in previous_component_durability_items}
    stack_limits = {**retained_stack_limits, **CURATED_ENGINE_STACK_LIMITS, **component_stack_limits}
    durability = {**retained_durability, **CURATED_ENGINE_DURABILITY, **component_durability}
    return dict(sorted(stack_limits.items())), dict(sorted(durability.items()))


class MicrosoftLearnItemParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows: list[list[str]] = []
        self._in_tr = False
        self._in_cell = False
        self._cell_parts: list[str] = []
        self._row: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._in_tr = True
            self._row = []
        elif self._in_tr and tag in {"td", "th"}:
            self._in_cell = True
            self._cell_parts = []

    def handle_data(self, data):
        if self._in_cell:
            self._cell_parts.append(data)

    def handle_endtag(self, tag):
        if tag in {"td", "th"} and self._in_cell:
            text = " ".join("".join(self._cell_parts).split())
            self._row.append(html.unescape(text))
            self._in_cell = False
        elif tag == "tr" and self._in_tr:
            if self._row:
                self.rows.append(self._row)
            self._in_tr = False
            self._row = []


def _friendly_name_from_identifier(identifier: str) -> str:
    return identifier.replace("_", " ").title()


SINGLE_WORD_MICROSOFT_ITEM_IDS = {
    "air",
    "apple",
    "beef",
    "bow",
    "bread",
    "brick",
    "camera",
    "clay",
    "clock",
    "coal",
    "cod",
    "compass",
    "cornflower",
    "dandelion",
    "egg",
    "elytra",
    "emerald",
    "feather",
    "flint",
    "glass",
    "glowstone",
    "gold",
    "gravel",
    "honeycomb",
    "ice",
    "kelp",
    "ladder",
    "lava",
    "leather",
    "melon",
    "milk",
    "mutton",
    "paper",
    "poppy",
    "porkchop",
    "potato",
    "potion",
    "quartz",
    "salmon",
    "sand",
    "shears",
    "shield",
    "stick",
    "string",
    "sugar",
    "tnt",
    "torch",
    "water",
    "wheat",
}


def parse_microsoft_item_listing(content: str) -> dict[str, str]:
    parser = MicrosoftLearnItemParser()
    parser.feed(content)
    result: dict[str, str] = {}
    for row in parser.rows:
        if len(row) < 2:
            continue
        identifier = row[0].strip().lower()
        runtime_id = row[1].strip()
        if not re.fullmatch(r"[a-z][a-z0-9_]*", identifier):
            continue
        if not re.fullmatch(r"-?\d+", runtime_id):
            continue
        if "_" not in identifier and identifier not in SINGLE_WORD_MICROSOFT_ITEM_IDS:
            continue
        result[identifier] = _friendly_name_from_identifier(identifier)
    return result


def fetch_microsoft_item_listing_snapshot(url: str = MICROSOFT_ITEM_LISTINGS_URL) -> tuple[dict[str, str], dict]:
    _validate_https_url(url, ALLOWED_MICROSOFT_LEARN_HOSTS, label="Microsoft-Learn-Itemliste")
    opener = _build_validating_opener(ALLOWED_MICROSOFT_LEARN_HOSTS, label="Microsoft-Learn-Itemliste")
    opener.addheaders = [("User-Agent", "MCBE-Inventory-Editor-Updater/1.0")]
    log(f"  {tr('Lade offizielle Microsoft-Learn-Itemliste...')}", Colors.YELLOW)
    try:
        with opener.open(url, timeout=30) as resp:
            _validate_final_response_url(resp, ALLOWED_MICROSOFT_LEARN_HOSTS, label="Microsoft-Learn-Itemliste")
            raw = resp.read(MAX_MICROSOFT_LEARN_BYTES + 1)
            if len(raw) > MAX_MICROSOFT_LEARN_BYTES:
                raise RuntimeError(tr("Microsoft-Learn-Itemliste ist unerwartet groß."))
            content = raw.decode("utf-8", errors="replace")
            items = parse_microsoft_item_listing(content)
            if len(items) < 1000:
                raise RuntimeError(tr("Microsoft-Learn-Itemliste enthält unerwartet wenige Einträge: {count}", count=len(items)))
            snapshot = {
                "microsoft_item_listing_url": url,
                "microsoft_item_listing_fetched_at": utc_now(),
                "microsoft_item_listing_content_hash": sha256_text(content),
                "microsoft_item_listing_items_hash": item_db_verification.item_listing_sha256(items),
                "microsoft_item_listing_count": len(items),
            }
            return items, snapshot
    except (OSError, TimeoutError) as exc:
        raise RuntimeError(tr("Fehler beim Laden der Microsoft-Learn-Itemliste: {error}", error=exc)) from exc


def write_microsoft_item_listing_cache(items: dict[str, str], snapshot: dict) -> None:
    try:
        payload = item_db_verification.build_item_listing_cache_payload(items, snapshot)
    except item_db_verification.UpdateReviewError as exc:
        raise RuntimeError(tr("Microsoft-Itemlisten-Snapshot ist ungültig: {error}", error=exc)) from exc
    atomic_write_text(ITEM_LISTING_CACHE_PATH, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def read_microsoft_item_listing_cache() -> tuple[dict[str, str], dict]:
    try:
        items, snapshot = item_db_verification.read_item_listing_cache(ITEM_LISTING_CACHE_PATH)
    except item_db_verification.UpdateReviewError as exc:
        raise RuntimeError(tr("Kein gültiger Microsoft-Itemlisten-Snapshot aus dem Dry-Run vorhanden: {error}", error=exc)) from exc
    source_url = str(snapshot["microsoft_item_listing_url"])
    _validate_https_url(source_url, ALLOWED_MICROSOFT_LEARN_HOSTS, label="Microsoft-Learn-Itemliste")
    if source_url != MICROSOFT_ITEM_LISTINGS_URL:
        raise RuntimeError(tr("Der Microsoft-Itemlisten-Snapshot gehört nicht zur aktuellen offiziellen Quelle."))
    return items, snapshot


def resolve_microsoft_item_listing_snapshot(*, reuse_cached: bool) -> tuple[dict[str, str], dict]:
    """Fetch the current listing or replay the exact normalized dry-run input."""

    if reuse_cached:
        items, snapshot = read_microsoft_item_listing_cache()
        log(f"  {Colors.YELLOW}{tr('Verwende im Dry-Run geprüfte Microsoft-Learn-Itemliste ({count} Einträge)', count=len(items))}{Colors.END}")
        return items, snapshot
    items, snapshot = fetch_microsoft_item_listing_snapshot()
    write_microsoft_item_listing_cache(items, snapshot)
    return items, snapshot


def _normalize_item_key(value: object) -> str:
    item_id = str(value or "").strip().lower()
    if item_id.startswith("minecraft:"):
        item_id = item_id.split(":", 1)[1]
    return item_id if re.fullmatch(r"[a-z0-9_]+", item_id) and not _is_non_item_lang_identifier(item_id) else ""


def _serialization_lang_key(value: object) -> str:
    key = str(value or "").strip().lower()
    if not key:
        return ""
    if key.startswith("minecraft:"):
        key = key.split(":", 1)[1]
    for prefix in ("item.", "tile."):
        if key.startswith(prefix):
            key = key[len(prefix) :]
            break
    if key.startswith("minecraft."):
        key = key.split(".", 1)[1]
    if key.endswith(".name"):
        key = key[:-5]
    key = key.strip(".")
    base = key.split(".", 1)[0]
    return key if _normalize_item_key(base) and re.fullmatch(r"[a-z0-9_]+(?:\.[a-z0-9_]+)*", key) else ""


def validate_update_sources(zf: zipfile.ZipFile, scope: str | None, *, allow_partial: bool = False) -> dict[str, str]:
    """Validate shared language files and each requested structural registry.

    Missing category labels are display-quality information, not evidence of
    invalid identifiers. Shared missing/unreadable language files still reject
    the snapshot. Invalid registries block only the section that consumes them.
    """
    from mcbe_editor.item_registry_policy import is_vanilla_registry_id

    modules = {"items": ("items", "blocks"), "effects": ("effects",), "enchants": ("enchantments",)}
    registry_keys = {
        "items": ("command_name", "name", "serialization_name"),
        "blocks": ("command_name", "name", "serialization_name"),
        "effects": ("name",),
        "enchantments": ("value", "name"),
    }
    members = zf.namelist()

    for locale in ("en_US", "de_DE"):
        member = f"resource_pack/texts/{locale}.lang"
        valid = False
        try:
            if members.count(member) == 1:
                content = read_utf8(zf, member)
                # A general language entry is enough: a valid Mojang language
                # file can have no labels at all for the requested category.
                entries = [line.strip() for line in content.splitlines() if line.strip() and not line.lstrip().startswith("#")]
                valid = (
                    "\0" not in content
                    and all(re.fullmatch(r"[A-Za-z0-9_.:/-]+\s*=.*", line) for line in entries)
                    and any(re.fullmatch(r"[A-Za-z0-9_.:/-]+\s*=\s*\S.*", line) for line in entries)
                )
        except (KeyError, UnicodeDecodeError, zipfile.BadZipFile):
            pass
        if not valid:
            raise RuntimeError(tr("Mojang-Quellen sind unvollständig oder ungültig: {member}.", member=member))

    blocked = {}
    for section in (scope,) if scope else modules:
        for module in modules[section]:
            member = f"metadata/vanilladata_modules/mojang-{module}.json"
            valid = False
            try:
                if members.count(member) == 1:
                    content = read_utf8(zf, member)
                    payload = json.loads(content)
                    entries = payload.get("data_items") if isinstance(payload, dict) else None
                    keys = registry_keys[module]
                    valid = (
                        isinstance(entries, list)
                        and bool(entries)
                        and all(
                            isinstance(entry, dict)
                            and any(entry.get(key) for key in keys)
                            and all(is_vanilla_registry_id(entry[key]) for key in keys if key in entry)
                            for entry in entries
                        )
                    )
            except (KeyError, UnicodeDecodeError, json.JSONDecodeError, RecursionError, zipfile.BadZipFile):
                pass
            if not valid:
                if not allow_partial:
                    raise RuntimeError(tr("Mojang-Quellen sind unvollständig oder ungültig: {member}.", member=member))
                blocked[section] = tr("Mojang-Quellen sind unvollständig oder ungültig: {member}.", member=member)
                break
    return blocked


def _vanilla_registry_ids(zf: zipfile.ZipFile, module: str) -> set[str]:
    try:
        obj = json.loads(read_utf8(zf, f"metadata/vanilladata_modules/{module}"))
    except KeyError:
        return set()
    result: set[str] = set()
    for entry in obj.get("data_items", []):
        if not isinstance(entry, dict):
            continue
        for key in ("command_name", "name", "serialization_name"):
            value = str(entry.get(key, "")).strip().lower()
            if value:
                result.add(value if value.startswith("minecraft:") else f"minecraft:{value}")
    return result


# Technische Blockformen, die unabhängig von ihrer vorübergehenden Präsenz in
# Mojangs Item-Registry nicht als neue Inventaritems angeboten werden dürfen.
# Dazu gehören auch Legacy-IDs aus der Vor-Flattening-Ära
# (double_stone_slab*, double_wooden_slab) und experimentelle Holzarten.
def compute_block_only_item_ids(zf: zipfile.ZipFile, items: dict[str, tuple[str, str]]) -> list[str]:
    """Katalog-IDs, die nur als technische Blockzustände nutzbar sind.

    Solche IDs (z. B. *_double_slab, *_standing_sign, candle_cake) ergeben im
    Inventar keine brauchbaren Items; die UI blendet sie aus den Vorschlägen aus.
    """
    item_ids = _vanilla_registry_ids(zf, "mojang-items.json")
    block_ids = _vanilla_registry_ids(zf, "mojang-blocks.json")
    if not item_ids or not block_ids:
        return []
    technical_registry_ids = {item_id for item_id in item_ids if is_technical_block_only_item_id(item_id)}
    return sorted(technical_registry_ids | {key for key in items if is_technical_block_only_item_id(key) or (key not in item_ids and key in block_ids)})


def compute_addable_item_ids(zf: zipfile.ZipFile, items: dict[str, tuple[str, str]]) -> list[str]:
    """Nichttechnische IDs aus Mojangs positiver Item-Registry.

    Der vollständige Katalog enthält absichtlich auch Legacy-Serialisierungen,
    Sprachschlüssel und reine Blockformen, damit vorhandene Welten lesbar und
    verlustfrei speicherbar bleiben. Für neu erzeugte Items ist dagegen die
    positive Item-Registry die belastbare Quelle.
    """
    item_ids = _vanilla_registry_ids(zf, "mojang-items.json")
    if not item_ids:
        return []
    # ``items`` bleibt Teil der Signatur, damit der Updater denselben
    # Datenkontext wie die übrigen Registry-Ableitungen übergibt. Moderne IDs
    # dürfen technische Aliasse auf Legacy-Serialisierungen behalten, benötigen
    # im Anzeigekatalog aber eigene Namen.
    del items
    return sorted(item_id for item_id in item_ids if not is_technical_block_only_item_id(item_id))


def complete_registry_names(items: dict, registry_ids: list[str], reviewed_items: dict) -> dict:
    """Fill missing names only for current registry IDs with reviewed exact-ID facts."""
    result = dict(items)
    for item_id in registry_ids:
        names = reviewed_items.get(item_id)
        if item_id not in result and isinstance(names, (list, tuple)) and len(names) == 2 and all(isinstance(name, str) and name.strip() for name in names):
            result[item_id] = tuple(names)
    return result


def compute_block_item_ids(zf: zipfile.ZipFile, items: dict[str, tuple[str, str]] | None = None) -> list[str]:
    """Als Blockitem geeignete IDs aus Mojangs Item-/Block-Registries.

    Diese Metadaten ergänzen die semantischen Browser-Kategorien. Dadurch
    erscheinen beispielsweise Hopper und Shulker-Kisten zusätzlich unter
    „Blöcke“, ohne zukünftige Blockfamilien über Namenssuffixe erraten zu müssen.
    """
    # Diese Inventaritems teilen zwar ihre ID mit einem Crop-Block, platzieren
    # ihn aber nicht. Die pflanzbaren Items sind beetroot_seeds/wheat_seeds.
    non_placeable_registry_collisions = {"minecraft:beetroot", "minecraft:wheat"}
    item_ids = _vanilla_registry_ids(zf, "mojang-items.json")
    block_ids = _vanilla_registry_ids(zf, "mojang-blocks.json")
    del items  # Anzeigenamen können einer gültigen Registry-ID noch fehlen.
    return sorted(key for key in (item_ids & block_ids) - non_placeable_registry_collisions if not is_technical_block_only_item_id(key))


def parse_json_item_serialization_aliases(zf: zipfile.ZipFile) -> dict[str, str]:
    """Map canonical Mojang item IDs to legacy .lang serialization keys.

    Bedrock can expose a modern command/name ID while keeping a legacy
    serialization_id for the display name, e.g. leather_horse_armor ->
    horsearmorleather. The updater needs this bridge to avoid English fallbacks.
    """
    try:
        obj = json.loads(read_utf8(zf, "metadata/vanilladata_modules/mojang-items.json"))
    except KeyError:
        return {}
    result: dict[str, str] = {}
    for item in obj.get("data_items", []):
        if not isinstance(item, dict):
            continue
        item_id = _normalize_item_key(item.get("command_name") or item.get("name") or item.get("serialization_name"))
        serialization_key = _serialization_lang_key(item.get("serialization_id"))
        if item_id and serialization_key and item_id != serialization_key:
            result[item_id] = serialization_key
    return result


def _parse_lang_item_entries(lang_path: Path | None) -> dict[str, str]:
    if not lang_path:
        return {}
    try:
        return _parse_lang_item_content(lang_path.read_text(encoding="utf-8-sig"))
    except OSError:
        return {}


def _parse_lang_item_content(content: str) -> dict[str, str]:
    """Parse safe item/tile name entries while preserving dotted localization keys.

    Dotted keys such as ``boat.acacia`` are localization identifiers, not valid
    Bedrock item IDs. Keeping them in a separate catalog lets the updater bridge
    them later without ever adding pseudo item IDs to the writable database.
    """
    named_pattern = re.compile(
        r"^(?:item|tile)\.(?:minecraft[:. ]\s*)?([a-z0-9_]+(?:[./-][a-z0-9_]+)*)\.name=(.+)$",
        re.IGNORECASE,
    )
    legacy_pattern = re.compile(
        r"^(?:item|tile)\.(?:minecraft[:. ]\s*)?([a-z0-9_]+(?:[/-][a-z0-9_]+)*)=(.+)$",
        re.IGNORECASE,
    )
    seen: dict[str, str] = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        match = named_pattern.match(line) or legacy_pattern.match(line)
        if not match:
            continue
        raw_id = match.group(1).strip().lower().strip(".")
        if not raw_id or raw_id in ("persona", "camera") or raw_id.startswith("persona_"):
            continue
        if raw_id == "minecraft":
            continue
        if raw_id not in seen:
            seen[raw_id] = match.group(2).strip()
    return seen


def parse_lang_item_localizations(en_path: Path, de_path: Path | None) -> dict[str, tuple[str, str]]:
    """Return full localization-key -> (German, English) pairs.

    Each language is independent. Missing values stay empty so exact-key
    resolution can use the available locale without inventing source coverage.
    Cross-key label matching applies its own stricter ambiguity checks.
    """
    en_entries = _parse_lang_item_entries(en_path)
    de_entries = _parse_lang_item_entries(de_path)
    return {key: (de_entries.get(key, ""), en_entries.get(key, "")) for key in sorted(en_entries.keys() | de_entries.keys())}


def parse_lang_items(en_path: Path, de_path: Path | None) -> tuple[dict[str, str], dict[str, str]]:
    """Parse direct item-ID localization keys. Returns (en_items, de_items)."""
    localizations = parse_lang_item_localizations(en_path, de_path)
    en_items: dict[str, str] = {}
    de_items: dict[str, str] = {}
    direct_identifier = re.compile(r"[a-z0-9_]+(?:[/-][a-z0-9_]+)*", re.IGNORECASE)
    for raw_id, (de_name, en_name) in localizations.items():
        if not direct_identifier.fullmatch(raw_id) or _is_non_item_lang_identifier(raw_id):
            continue
        en_name = update_source_quality.usable_source_name(en_name)
        de_name = update_source_quality.usable_source_name(de_name)
        if en_name:
            en_items[raw_id] = en_name
        if de_name:
            de_items[raw_id] = de_name
    return en_items, de_items


def _normalized_display_label(value: str) -> str:
    return " ".join(str(value or "").casefold().split())


def build_item_localization_label_index(
    localizations: dict[str, tuple[str, str]],
) -> dict[str, tuple[str, str]]:
    """Build a conservative English-label -> localized-name bridge.

    A label is accepted when it has one localization key or when all matching
    keys agree on the German name. Ambiguous translations are deliberately
    omitted instead of guessing which variant belongs to a canonical item ID.
    """
    grouped: dict[str, list[tuple[str, str, str]]] = {}
    for key, (de_name, en_name) in localizations.items():
        english = update_source_quality.usable_source_name(en_name)
        label = _normalized_display_label(english)
        if not label:
            continue
        # An untranslated competing key cannot establish that all uses of this
        # English label have the same German meaning. Keep it as an ambiguity.
        german = update_source_quality.usable_source_name(de_name)
        grouped.setdefault(label, []).append((key, german, english))

    index: dict[str, tuple[str, str]] = {}
    for label, candidates in grouped.items():
        german_names = {_normalized_display_label(candidate[1]) for candidate in candidates}
        if "" not in german_names and len(german_names) == 1:
            _key, de_name, en_name = sorted(candidates, key=lambda candidate: candidate[0])[0]
            index[label] = (de_name, en_name)
    return index


def _derived_item_localization_keys(item_id: str) -> list[str]:
    """Return deterministic localization keys for known Bedrock key families.

    These rules describe Mojang's key schema, not individual item translations.
    A derived key is only used when it exists in the parsed language catalog.
    """
    return [key.removeprefix("item.").removesuffix(".name") for key in item_localization.variant_language_keys(item_id)]


def _localized_names_for_item_key(
    item_id: str,
    localizations: dict[str, tuple[str, str]],
) -> tuple[str, str] | None:
    for key in _derived_item_localization_keys(item_id):
        names = localizations.get(key)
        if names:
            de_name, en_name = names
            usable = (update_source_quality.usable_source_name(de_name), update_source_quality.usable_source_name(en_name))
            if any(usable):
                return usable
    return None


def _base_name_for_variant_label(
    item_id: str,
    current: tuple[str, str],
    localizations: dict[str, tuple[str, str]],
) -> tuple[str, str] | None:
    """Return Mojang's base name when ``current`` names one of several variants.

    Legacy IDs such as ``sandstone`` or ``wool`` cover several variants whose
    names live under ``tile.<id>.<variant>.name``; the data value selects the
    variant. Earlier generators copied one of those variant names, so
    ``minecraft:sandstone`` was labelled "Chiseled Sandstone". When Mojang also
    ships ``tile.<id>.name``, that base name is the only label valid for the ID
    itself. IDs with an explicit derived key (``bed``) keep their reviewed
    default variant, and a single variant (``yellow_flower``) is not ambiguous.
    """
    if _derived_item_localization_keys(item_id):
        return None
    base = localizations.get(item_id)
    if not base or not all(update_source_quality.usable_source_name(name) for name in base):
        return None
    if current == base:
        return None
    base_en = _normalized_display_label(base[1])
    prefix = f"{item_id}."
    variants = [
        (de, en)
        for key, (de, en) in localizations.items()
        if key.startswith(prefix)
        and update_source_quality.usable_source_name(de)
        and update_source_quality.usable_source_name(en)
        and _normalized_display_label(en) != base_en
    ]
    if len({_normalized_display_label(en) for _de, en in variants}) < 2:
        return None
    if not any(current == (de, en) or current == (en, en) for de, en in variants):
        return None
    return base[0] or base[1], base[1] or item_id


def _candidate_item_keys(item_id: str, serialization_aliases: dict[str, str]) -> list[str]:
    keys = [item_id]
    alias = serialization_aliases.get(item_id, "")
    if alias and alias not in keys:
        keys.append(alias)
    return keys


def _first_name(mapping: dict[str, str], keys: list[str]) -> str:
    for key in keys:
        value = update_source_quality.usable_source_name(mapping.get(key))
        if value:
            return value
    return ""


def _old_name_for_keys(old: dict[str, tuple[str, str]], keys: list[str]) -> tuple[str, str] | None:
    for key in keys:
        value = old.get(f"minecraft:{key}")
        if value and len(value) >= 2 and (value[0] or value[1]):
            return value
    return None


def _looks_like_fallback_name(de_name: str, en_name: str) -> bool:
    return not str(de_name or "").strip() or str(de_name or "").strip() == str(en_name or "").strip()


def _resolved_item_names(
    item_id: str,
    old: dict[str, tuple[str, str]],
    en_items: dict[str, str],
    de_items: dict[str, str],
    microsoft_items: dict[str, str],
    serialization_aliases: dict[str, str],
    item_localizations: dict[str, tuple[str, str]],
    localization_label_index: dict[str, tuple[str, str]],
    source_labels: dict | None = None,
) -> tuple[tuple[str, str], dict[str, str], tuple[str, str]]:
    """Resolve names and their provenance together for merging and reporting."""
    keys = _candidate_item_keys(item_id, serialization_aliases)
    has_source = item_id in (source_labels or {})
    full_id = f"minecraft:{item_id}"
    curated = _bundled_limits.get("items", {}).get(full_id, ("", ""))
    previous = old.get(full_id, ("", ""))
    localized_names = _localized_names_for_item_key(item_id, item_localizations)

    direct_en_name = _first_name(en_items, [item_id])
    old_alias_name = _old_name_for_keys(old, keys[1:])
    alias_en_name = _first_name(en_items, keys[1:])
    if not alias_en_name and old_alias_name:
        alias_en_name = old_alias_name[1]
    canonical_en_name = direct_en_name or _first_name(microsoft_items, [item_id])
    alias_matches_canonical = not canonical_en_name or (
        bool(alias_en_name) and _normalized_display_label(alias_en_name) == _normalized_display_label(canonical_en_name)
    )

    official = {"de": _first_name(de_items, [item_id]), "en": direct_en_name}
    existing = list(previous)
    if alias_matches_canonical and not has_source:
        for index, (locale, mapping) in enumerate((("de", de_items), ("en", en_items))):
            official[locale] = official[locale] or _first_name(mapping, keys[1:])
            if not existing[index] and old_alias_name:
                existing[index] = old_alias_name[index]
    secondary = {
        "en": _first_name(microsoft_items, [item_id]) or (_first_name(microsoft_items, keys[1:]) if alias_matches_canonical and not has_source else "")
    }
    source = (source_labels or {}).get(item_id, {})
    # A complete reference from the exact registry identity is stronger than
    # display-label matching against the independently maintained Learn list.
    if has_source:
        official = {"de": "", "en": "", **source.get("official", {})}
        localized_names = None
    else:
        official.update(source.get("official", {}))
    for locale in source.get("reasons", {}):
        official[locale] = ""
    # A cross-key label bridge needs a current English source for this identity.
    # Display fallbacks (including custom/curated names) are not identity evidence.
    source_en_name = "" if source.get("reasons", {}).get("en") == "ambiguous" else official["en"] or secondary["en"]
    if not has_source:
        localized_names = localized_names or localization_label_index.get(_normalized_display_label(source_en_name))
    if localized_names:
        for index, locale in enumerate(("de", "en")):
            official[locale] = official[locale] or localized_names[index]
        if item_id == "bed":
            # The canonical bed is the white data-value-zero variant. Resolve
            # its two locales through the same fallback policy as other items;
            # an absent counterpart is not an official source translation.
            official = dict(zip(("de", "en"), localized_names, strict=True))
    for locale, reason in source.get("reasons", {}).items():
        if reason == "ambiguous":
            official[locale] = ""
    names, sources = update_source_quality.resolve_names(full_id, official, curated, existing, secondary, composed=source.get("composed"))
    variant_names = reviewed_variant_name_overrides(full_id, _bundled_limits["items"], official)
    names = tuple(variant_names.get(locale, names[index]) for index, locale in enumerate(("de", "en")))
    sources = tuple("curated" if locale in variant_names else sources[index] for index, locale in enumerate(("de", "en")))
    # Preserve the existing exact shipped-label migration even when a reviewed
    # German fallback means the intermediate pair is no longer English-only.
    if not official["de"] and not (has_source and official["en"]):
        repaired = reviewed_item_label_repairs({full_id: (names[1], names[1])}, _bundled_limits.get("items", {})).get(full_id)
        if repaired:
            names = repaired
            sources = ("curated", "curated")
    return names, official, sources


def merge_items(
    old: dict[str, tuple[str, str]],
    en_items: dict[str, str],
    de_items: dict[str, str],
    microsoft_items: dict[str, str] | None = None,
    serialization_aliases: dict[str, str] | None = None,
    item_localizations: dict[str, tuple[str, str]] | None = None,
    registry_ids: list[str] | None = None,
    source_labels: dict | None = None,
    *,
    label_records: dict | None = None,
    previous_confirmed: dict | None = None,
    has_explicit_registry: bool = False,
    registry_label_ids: set[str] | None = None,
) -> dict[str, tuple[str, str]]:
    """Merge existing items + official item IDs.

    Known shipped obsolete labels use the same exact-match repairs as the runtime.
    Other existing localized entries stay untouched. Existing English fallbacks may be
    corrected when Mojang's mojang-items.json points the canonical ID at a
    legacy serialization/localization key. A label that names one variant of a
    multi-variant ID is replaced by Mojang's base name for that ID. Tooltip
    keys that older catalogs took for items are dropped.
    """
    merged = {item_id: names for item_id, names in old.items() if not is_non_item_lang_key_id(item_id)}
    # Repair exact shipped pairs before a fallback changes only one language.
    catalog = _bundled_limits.get("items", {})
    previous_confirmed = previous_confirmed or {}
    microsoft_items = microsoft_items or {}
    if label_records is None:
        label_records = {}
    label_records.update({key: value for key, value in previous_confirmed.items() if key in merged})
    repairs = reviewed_item_label_repairs(merged, catalog)
    merged.update({key: names for key, names in repairs.items() if key not in previous_confirmed})
    serialization_aliases = serialization_aliases or {}
    item_localizations = item_localizations or {}
    localization_label_index = build_item_localization_label_index(item_localizations)
    # Standalone callers can supply already identified label maps. The worker
    # reads raw language keys, where a future tooltip may resemble an item ID.
    language_ids = en_items.keys() | de_items.keys()
    if registry_ids is not None or registry_label_ids is not None:
        known_label_ids = merged.keys() | catalog.keys() | (registry_label_ids or set())
        language_ids = {key for key in language_ids if f"minecraft:{key}" in known_label_ids}
    all_ids = language_ids | set(microsoft_items) | set(serialization_aliases) | {identifier.removeprefix("minecraft:") for identifier in registry_ids or ()}
    for item_id in sorted(all_ids):
        if is_non_item_lang_key_id(item_id):
            continue
        full_id = f"minecraft:{item_id}"
        (de_name, en_name), _official, _sources = _resolved_item_names(
            item_id,
            old,
            en_items,
            de_items,
            microsoft_items,
            serialization_aliases,
            item_localizations,
            localization_label_index,
            source_labels,
        )
        # A validated identity is not a display name. New entries without any
        # usable name keep the runtime fallback; existing entries stay intact.
        if full_id not in merged and _sources == ("identifier", "identifier"):
            continue
        current = old.get(full_id)
        previous = previous_confirmed.get(full_id)
        record = previous
        if source_labels is None or item_id in source_labels or item_id in microsoft_items:
            record = item_label_reference(
                full_id, current, previous, catalog, _official, (source_labels or {}).get(item_id, {}).get("composed"), microsoft_items.get(item_id)
            )
        if record:
            label_records[full_id] = record
            candidate = confirmed_item_label_pair(record)
            if previous:
                prior = confirmed_item_label_pair(previous)
                merged[full_id] = tuple(new if local == last else local for local, last, new in zip(current, prior, candidate, strict=True))
                continue
            if current == tuple(candidate):
                # A current source can legitimately use a historical spelling.
                merged[full_id] = current
                continue
        existing = merged.get(full_id)
        if existing:
            # Fill generated ID placeholders before reconciling the pair. This
            # lets the same comparison repair any newly recognizable fallback.
            if full_id in existing:
                old_de, old_en = existing
                existing = merged[full_id] = (de_name if old_de == full_id else old_de, en_name if old_en == full_id else old_en)
            if is_expected_item_name_difference(full_id, existing, {locale: {full_id: value} for locale, value in _official.items()}):
                continue
            reviewed_pair = catalog.get(full_id)
            replaceable = full_id in REPLACEABLE_CATALOG_ITEM_IDS
            if reviewed_pair and ((item_id in (source_labels or {}) and full_id not in EXPECTED_ITEM_NAME_DIFFERENCES) or replaceable):
                # Each unchanged reviewed locale can receive its own translation.
                inherited = tuple(
                    value if (replaceable or _official.get(locale)) and existing[index] in (reviewed_pair[index], _official.get(locale)) else existing[index]
                    for index, (locale, value) in enumerate((("de", de_name), ("en", en_name)))
                )
                if inherited != existing or replaceable:
                    merged[full_id] = inherited
                    continue
            old_de, old_en = existing
            has_authoritative_derived_name = (
                item_id == "bed"
                and not (source_labels or {}).get(item_id, {}).get("reasons")
                and _localized_names_for_item_key(item_id, item_localizations) is not None
                and any(
                    (old_de, old_en) == pair or old_de == old_en == pair[1]
                    for key, pair in item_localizations.items()
                    if key == "bed" or key.startswith("bed.")
                )
            )
            base_name = _base_name_for_variant_label(item_id, existing, item_localizations)
            if item_id in (source_labels or {}) and base_name != tuple(_official.get(locale, "") for locale in ("de", "en")):
                base_name = None
            if has_authoritative_derived_name and (old_de, old_en) != (de_name, en_name):
                merged[full_id] = (de_name, en_name)
            elif base_name is not None:
                merged[full_id] = base_name
            elif (
                not has_explicit_registry
                and _looks_like_fallback_name(old_de, old_en)
                and old_en in (en_name, microsoft_items.get(item_id))
                and not _looks_like_fallback_name(de_name, en_name)
            ):
                merged[full_id] = (de_name, old_en or en_name)
            elif not has_explicit_registry and old_de == old_en == de_name and de_name != en_name:
                merged[full_id] = (old_de, en_name)
            continue
        merged[full_id] = (de_name, en_name)
    # Run after localization fallback resolution as well: a formerly English-only
    # pair can acquire its German half during this merge (e.g. poplar signs).
    repairs = reviewed_item_label_repairs(merged, catalog, label_records)
    merged.update({key: names for key, names in repairs.items() if key not in previous_confirmed})
    return merged


# ─── EFFECTS ────────────────────────────────────────────────────────────────


def parse_json_effects(zf: zipfile.ZipFile) -> list[str]:
    obj = json.loads(read_utf8(zf, "metadata/vanilladata_modules/mojang-effects.json"))
    return sorted(_canonical_effect_identifier(item["name"]) for item in obj.get("data_items", []) if item.get("name"))


def parse_lang_effects(content: str) -> dict[str, str]:
    """Read Bedrock effect labels from effect.* and base potion.* keys."""
    result: dict[str, str] = {}
    for line in content.splitlines():
        line = line.strip()
        if not line.startswith(("effect.", "potion.")) or "=" not in line:
            continue
        key, val = line.split("=", 1)
        lang_name = key.partition(".")[2].strip()
        # Potion item names, durations and potency labels are not effect names.
        # Turtle Master has two UI labels for its combined effects, not an ID.
        if "." in lang_name or lang_name in {"empty", "turtleMaster", "turtleMaster2"}:
            continue
        json_name = EFFECT_LANG_TO_JSON.get(lang_name, lang_name)
        json_name = _canonical_effect_identifier(json_name)
        name = update_source_quality.usable_source_name(val)
        if re.fullmatch(r"[a-z0-9_]+", json_name) and name and json_name not in result:
            result[json_name] = name
    return result


def _numeric_label_inputs(identifier, numeric_id, old, bundled, numeric_ids, en_names, de_names):
    facts = bundled.get(str(numeric_id), ())
    curated = facts[:2] if len(facts) >= 2 and canonical_numeric_name(facts[1]) == identifier else ()
    matches = [values[:2] for values in old.values() if any(canonical_numeric_name(name) == identifier for name in values[:2])]
    existing = matches[0] if len(matches) == 1 else ()
    if not existing and numeric_id in old:
        candidate = old[numeric_id][:2]
        # A custom label at the correct reviewed ID is safe to retain; a name
        # identifying a different reviewed ID is not a fallback for this one.
        recognized = {numeric_ids[key] for name in candidate if (key := canonical_numeric_name(name)) in numeric_ids}
        if not recognized or recognized == {numeric_id}:
            existing = candidate
    official = {"de": _first_name(de_names, [identifier]), "en": _first_name(en_names, [identifier])}
    return official, curated, existing


def numeric_label_quality(old, merged, identifiers, numeric_ids, en_names, de_names, *, kind):
    bundled = json.loads(BUNDLED_ITEM_DB_JSON.read_text(encoding="utf-8"))[kind]
    canonical = _canonical_effect_identifier if kind == "effects" else _canonical_enchantment_identifier
    records = []
    for identifier in sorted({canonical(value) for value in identifiers}):
        numeric_id = numeric_ids[identifier]
        official, curated, existing = _numeric_label_inputs(identifier, numeric_id, old, bundled, numeric_ids, en_names, de_names)
        names, sources = update_source_quality.resolve_names(f"minecraft:{identifier}", official, curated, existing)
        actual = merged.get(numeric_id, names)
        actual_sources = update_source_quality.display_name_sources(actual, official, curated)
        sources = tuple(
            actual_sources[index] if actual[index] != names[index] or actual_sources[index] == "official" else source for index, source in enumerate(sources)
        )
        records.append((f"minecraft:{identifier}", official, sources))
    return update_source_quality.coverage(records)


def item_label_quality(
    registry_ids, items, old, en_names, de_names, serialization_aliases, localizations, microsoft_items=None, source_labels=None, *, label_records=None
):
    records = []
    label_index = build_item_localization_label_index(localizations)
    for full_id in sorted(set(registry_ids)):
        identifier = full_id.removeprefix("minecraft:")
        names, official, sources = _resolved_item_names(
            identifier, old, en_names, de_names, microsoft_items or {}, serialization_aliases, localizations, label_index, source_labels
        )
        actual = items.get(full_id)
        if actual:
            curated = _bundled_limits["items"].get(full_id, (None, None))
            actual_sources = update_source_quality.display_name_sources(actual, official, curated, (source_labels or {}).get(identifier, {}).get("composed"))
            sources = tuple(
                actual_sources[index] if actual[index] != names[index] or actual_sources[index] == "official" else source
                for index, source in enumerate(sources)
            )
            record = (label_records or {}).get(full_id)
            if record:
                reference = confirmed_item_label_pair(record)
                sources = list(sources)
                for index, locale in enumerate(("de", "en")):
                    if actual[index] != reference[index]:
                        sources[index] = "existing"
                    elif not official[locale] and actual_sources[index] == "existing":
                        if isinstance(record, dict) and record["borrowed"] == locale:
                            sources[index] = "other_language"
                        elif sources[index] == "other_language":
                            sources[index] = "existing"
        records.append((full_id, official, sources))
    quality = update_source_quality.coverage(records)
    for index, (locale, coverage) in enumerate(quality.items()):
        for fallback in [*coverage["fallbacks"], *coverage.get("retained", [])]:
            identifier = fallback["id"].removeprefix("minecraft:")
            source = (source_labels or {}).get(identifier, {})
            if reason := source.get("reasons", {}).get(locale):
                fallback["reason"] = reason
            elif fallback["source"] == "curated" and fallback["id"] in EDITORIAL_ITEM_IDS_BY_LOCALE.get(locale, ()):
                fallback["reason"] = "editorial"
            elif locale == "en" and fallback["source"] == "curated" and fallback["id"] in DOCUMENTED_ENGLISH_ITEM_IDS:
                fallback["reason"] = "documented"
            elif source.get("composed", {}).get(locale):
                fallback["reason"] = "composed"
            elif (
                identifier in item_localization.CATEGORY_ITEM_NAMES
                and items.get(fallback["id"], ("", ""))[index] == _bundled_limits["items"].get(fallback["id"], (None, None))[index]
            ):
                fallback["reason"] = "category"
    return quality


def merge_effects(
    old: dict[int, tuple[str, str, str, str]],
    json_ids: list[str],
    en_names: dict[str, str],
    de_names: dict[str, str],
    local_numeric_ids: dict[str, int],
) -> dict[int, tuple[str, str, str, str]]:
    """Merge Mojang labels while retaining all bundled reviewed effect facts."""
    identifiers = {_canonical_effect_identifier(value) for value in json_ids}
    missing = sorted(identifiers - set(local_numeric_ids))
    if missing:
        raise RuntimeError(tr("Lokale numerische IDs fehlen für neue Mojang-Effekte: {identifiers}", identifiers=", ".join(missing)))
    _validate_numeric_targets(identifiers, local_numeric_ids)
    bundled = json.loads(BUNDLED_ITEM_DB_JSON.read_text(encoding="utf-8"))["effects"]
    # Engine-reviewed effects can precede the stable samples registry. Seed the
    # same curated facts used by runtime loading, then prefer Mojang labels for
    # identifiers actually present in this release. This does not change source
    # metadata or present a curated label as a translation from that release.
    reviewed = {int(numeric_id): tuple(values) for numeric_id, values in bundled.items()}
    for json_id in json_ids:
        identifier = _canonical_effect_identifier(json_id)
        numeric_id = local_numeric_ids[identifier]
        official, curated, existing = _numeric_label_inputs(identifier, numeric_id, old, bundled, local_numeric_ids, en_names, de_names)
        names, _sources = update_source_quality.resolve_names(f"minecraft:{identifier}", official, curated, existing)
        facts = bundled.get(str(numeric_id))
        descriptions = facts[2:] if facts and canonical_numeric_name(facts[1]) == identifier else ("", "")
        reviewed[numeric_id] = (*names, *descriptions)
    return _reconcile_numeric(old, reviewed, identifiers, local_numeric_ids, kind="effects")


def _validate_numeric_targets(identifiers: set[str], numeric_ids: dict[str, int]) -> None:
    targets = [numeric_ids[identifier] for identifier in identifiers]
    if len(targets) != len(set(targets)):
        raise RuntimeError(tr("Numerische IDs sind im geprüften Katalog doppelt vergeben."))


def _reconcile_numeric(old, reviewed, identifiers, numeric_ids, *, kind):
    try:
        return reconcile_numeric_catalog(old, reviewed, kind=kind, identifiers={name: numeric_ids[name] for name in identifiers})
    except ValueError as exc:
        raise RuntimeError(tr(str(exc))) from exc


# ─── ENCHANTMENTS ───────────────────────────────────────────────────────────


def parse_json_enchantments(zf: zipfile.ZipFile) -> list[tuple[str, int]]:
    """Parse mojang-enchantments.json, return list of (canonical_name, max_level)."""
    obj = json.loads(read_utf8(zf, "metadata/vanilladata_modules/mojang-enchantments.json"))
    items = obj.get("data_items", [])
    result = []
    for item in items:
        raw_name = item.get("value") or item.get("name")
        if not raw_name:
            continue
        name = _canonical_enchantment_identifier(raw_name)
        # The tuple keeps the existing merge API; actual max levels come from the
        # locally reviewed Vanilla table.
        result.append((name, 1))
    return result


def parse_lang_enchantments(content: str) -> dict[str, str]:
    """Read Bedrock enchantment.* labels and supported legacy enchant.* keys."""
    result: dict[str, str] = {}
    for line in content.splitlines():
        line = line.strip()
        if not line.startswith(("enchant.", "enchantment.")) or "=" not in line:
            continue
        key, val = line.split("=", 1)
        lang_name = key.partition(".")[2].strip()
        if lang_name in {"desc", "prefix", "level"}:
            continue
        json_name = ENCH_LANG_TO_JSON.get(lang_name, lang_name)
        json_name = _canonical_enchantment_identifier(json_name)
        # Known dotted name aliases are mapped above; remaining dotted keys
        # contain levels, descriptions or other UI text, not registry IDs.
        name = update_source_quality.usable_source_name(val)
        if re.fullmatch(r"[a-z0-9_]+", json_name) and name and json_name not in result:
            result[json_name] = name
    return result


def merge_enchantments(
    old: dict[int, tuple[str, str, int, str]],
    json_list: list[tuple[str, int]],
    en_names: dict[str, str],
    de_names: dict[str, str],
    local_max_levels: dict[str, int],
    local_numeric_ids: dict[str, int],
) -> dict[int, tuple[str, str, int, str]]:
    """Merge Mojang identifiers/names with reviewed Bedrock IDs and max levels."""
    mojang_identifiers = {_canonical_enchantment_identifier(name) for name, _ in json_list}
    missing_levels = sorted(mojang_identifiers - set(local_max_levels))
    if missing_levels:
        raise RuntimeError(tr("Lokale Maximalstufen fehlen für neue Mojang-Verzauberungen: {identifiers}", identifiers=", ".join(missing_levels)))
    missing_numeric_ids = sorted(mojang_identifiers - set(local_numeric_ids))
    if missing_numeric_ids:
        raise RuntimeError(tr("Lokale numerische IDs fehlen für neue Mojang-Verzauberungen: {identifiers}", identifiers=", ".join(missing_numeric_ids)))

    _validate_numeric_targets(mojang_identifiers, local_numeric_ids)
    bundled = json.loads(BUNDLED_ITEM_DB_JSON.read_text(encoding="utf-8"))["enchantments"]
    reviewed = {}
    for json_name, _ in json_list:
        identifier = _canonical_enchantment_identifier(json_name)
        numeric_id = local_numeric_ids[identifier]
        official, curated, existing = _numeric_label_inputs(identifier, numeric_id, old, bundled, local_numeric_ids, en_names, de_names)
        names, _sources = update_source_quality.resolve_names(f"minecraft:{identifier}", official, curated, existing)
        reviewed[numeric_id] = (*names, local_max_levels[identifier], "")
    return _reconcile_numeric(old, reviewed, mojang_identifiers, local_numeric_ids, kind="enchantments")


# ─── HELPERS ────────────────────────────────────────────────────────────────


def _cap(s: str) -> str:
    """Capitalize first letter."""
    return s[0].upper() + s[1:] if s else s


# ─── JSON DATABASE READING/WRITING ──────────────────────────────────────────


def _load_item_db_json() -> dict:
    try:
        data = json.loads(ITEM_DB_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(tr("Item-DB JSON nicht gefunden: {path}", path=ITEM_DB_PATH)) from exc
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise RuntimeError(tr("Item-DB JSON ist ungültig: {path}", path=ITEM_DB_PATH)) from exc
    if not isinstance(data, dict):
        raise RuntimeError(tr("Item-DB JSON muss ein Objekt sein."))
    return data


def _read_str_pair_map(data: dict, key: str) -> dict[str, tuple[str, str]]:
    raw = data.get(key, {})
    if not isinstance(raw, dict):
        return {}
    result: dict[str, tuple[str, str]] = {}
    for item_id, value in raw.items():
        if isinstance(value, (list, tuple)) and len(value) >= 2:
            result[str(item_id)] = (str(value[0] or ""), str(value[1] or ""))
    return result


def _read_effect_map(data: dict) -> dict[int, tuple[str, str, str, str]]:
    raw = data.get("effects", {})
    if not isinstance(raw, dict):
        return {}
    result: dict[int, tuple[str, str, str, str]] = {}
    for key, value in raw.items():
        if not isinstance(value, (list, tuple)) or len(value) < 3:
            continue
        try:
            numeric_key = int(key)
        except (TypeError, ValueError):
            continue
        if len(value) >= 4:
            description_de = str(value[2] or "")
            description_en = str(value[3] or "")
        else:
            description_de = ""
            description_en = str(value[2] or "")
        result[numeric_key] = (str(value[0] or ""), str(value[1] or ""), description_de, description_en)
    return result


def _read_enchantment_map(data: dict) -> dict[int, tuple[str, str, int, str]]:
    raw = data.get("enchantments", {})
    if not isinstance(raw, dict):
        return {}
    result: dict[int, tuple[str, str, int, str]] = {}
    for key, value in raw.items():
        if not isinstance(value, (list, tuple)) or len(value) < 3:
            continue
        try:
            numeric_key = int(key)
            max_level = int(value[2])
        except (TypeError, ValueError):
            continue
        desc = str(value[3] or "") if len(value) >= 4 else ""
        result[numeric_key] = (str(value[0] or ""), str(value[1] or ""), max_level, desc)
    return result


def read_all_dicts() -> tuple[
    dict[str, tuple[str, str]],
    dict[int, tuple[str, str, str, str]],
    dict[int, tuple[str, str, int, str]],
]:
    """Read ITEMS, EFFECTS, ENCHANTMENTS from item_db.json."""
    data = _load_item_db_json()
    return _read_str_pair_map(data, "items"), _read_effect_map(data), _read_enchantment_map(data)


def read_block_only_item_ids() -> list[str]:
    raw = _load_item_db_json().get("block_only_items", [])
    if not isinstance(raw, list):
        return []
    return sorted({str(entry).strip().lower() for entry in raw if str(entry).strip()})


def read_block_item_ids() -> list[str]:
    raw = _load_item_db_json().get("block_items", [])
    if not isinstance(raw, list):
        return []
    return sorted({str(entry).strip().lower() for entry in raw if str(entry).strip()})


def read_addable_item_ids() -> list[str]:
    raw = _load_item_db_json().get("addable_items", [])
    if not isinstance(raw, list):
        return []
    return sorted({str(entry).strip().lower() for entry in raw if str(entry).strip()})


def _read_positive_int_map(key: str, *, allow_zero: bool = False) -> dict[str, int]:
    raw = _load_item_db_json().get(key, {})
    if not isinstance(raw, dict):
        return {}
    minimum = 0 if allow_zero else 1
    result: dict[str, int] = {}
    for item_id, value in raw.items():
        if type(value) is int and minimum <= value <= 32767:
            result[str(item_id).strip().lower()] = value
    return dict(sorted(result.items()))


def read_stack_limits() -> dict[str, int]:
    return _read_positive_int_map("stack_limits")


def read_durability() -> dict[str, int]:
    return _read_positive_int_map("durability", allow_zero=True)


def read_item_components() -> dict[str, dict[str, dict]]:
    raw = _load_item_db_json().get("item_components", {})
    if not isinstance(raw, dict):
        return {component: {} for component in TRACKED_ITEM_COMPONENTS}
    result: dict[str, dict[str, dict]] = {}
    for component in TRACKED_ITEM_COMPONENTS:
        values = raw.get(component, {})
        if not isinstance(values, dict):
            result[component] = {}
            continue
        result[component] = {
            str(item_id).strip().lower(): value
            for item_id, value in sorted(values.items())
            if re.fullmatch(r"[a-z0-9_.-]+:[a-z0-9_./-]+", str(item_id).strip().lower()) and isinstance(value, dict)
        }
    return result


def normalize_behavior_item_source(raw: object) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    result = {
        "resource_pack_release": str(raw.get("resource_pack_release", "") or "").strip(),
    }
    for field in ("stack_limit_items", "durability_items"):
        values = raw.get(field, [])
        if not isinstance(values, list):
            values = []
        result[field] = sorted(
            {
                item_id
                for value in values
                if isinstance(value, str)
                and re.fullmatch(
                    r"[a-z0-9_.-]+:[a-z0-9_./-]+",
                    item_id := value.strip().lower(),
                )
            }
        )
    return result


def read_behavior_item_source() -> dict:
    return normalize_behavior_item_source(_load_item_db_json().get("behavior_item_source", {}))


def build_behavior_item_source(
    release_info: dict,
    component_stack_limits: dict[str, int],
    component_durability: dict[str, int],
) -> dict:
    return {
        "resource_pack_release": str(release_info.get("resource_pack_release", "") or "").strip(),
        "stack_limit_items": sorted(component_stack_limits),
        "durability_items": sorted(component_durability),
    }


def write_all_dicts(
    items: dict[str, tuple[str, str]],
    effects: dict[int, tuple[str, str, str, str]],
    enchants: dict[int, tuple[str, str, int, str]],
    block_only_items: list[str] | None = None,
    block_items: list[str] | None = None,
    addable_items: list[str] | None = None,
    stack_limits: dict[str, int] | None = None,
    durability: dict[str, int] | None = None,
    item_components: dict[str, dict[str, dict]] | None = None,
    behavior_item_source: dict | None = None,
    updated_sections: set[str] | None = None,
    confirmed_item_labels: dict | None = None,
) -> None:
    data = _load_item_db_json()
    selected = {"items", "effects", "enchants"} if updated_sections is None else updated_sections
    data["schema_version"] = 3
    # Preserve unselected and blocked sections directly from the old payload.
    # Even normalizing their optional fields would publish an unreviewed change.
    if "items" in selected:
        data.setdefault("defaults", {"max_damage": 1561, "max_data_value": 32767})["max_stack"] = 1
        data.setdefault("stack_limits", {})
        data.setdefault("durability", {})
        data.setdefault("item_components", {component: {} for component in TRACKED_ITEM_COMPONENTS})
        data["items"] = {key: [de, en] for key, (de, en) in sorted(items.items())}
        if confirmed_item_labels is not None:
            if confirmed_item_labels:
                data["confirmed_item_labels"] = confirmed_item_labels
            else:
                data.pop("confirmed_item_labels", None)
        if block_only_items is not None:
            data["block_only_items"] = sorted(block_only_items)
        if block_items is not None:
            data["block_items"] = sorted(block_items)
        if addable_items is not None:
            data["addable_items"] = sorted(addable_items)
        if stack_limits is not None:
            data["stack_limits"] = dict(sorted(stack_limits.items()))
        if durability is not None:
            data["durability"] = dict(sorted(durability.items()))
        if item_components is not None:
            data["item_components"] = {component: dict(sorted((item_components.get(component) or {}).items())) for component in TRACKED_ITEM_COMPONENTS}
        if behavior_item_source is not None:
            data["behavior_item_source"] = normalize_behavior_item_source(behavior_item_source)
    if "effects" in selected:
        data["effects"] = {str(key): [de, en, desc_de, desc_en] for key, (de, en, desc_de, desc_en) in sorted(effects.items())}
    if "enchants" in selected:
        data["enchantments"] = {str(key): [de, en, int(level), desc] for key, (de, en, level, desc) in sorted(enchants.items())}
    atomic_write_text(ITEM_DB_PATH, json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def format_items(items: dict[str, tuple[str, str]]) -> dict[str, tuple[str, str]]:
    return dict(sorted(items.items()))


def format_effects(effects: dict[int, tuple[str, str, str, str]]) -> dict[int, tuple[str, str, str, str]]:
    return dict(sorted(effects.items()))


def format_enchantments(enchants: dict[int, tuple[str, str, int, str]]) -> dict[int, tuple[str, str, int, str]]:
    return dict(sorted(enchants.items()))


_SOURCE_RESOURCE_PACK_FIELDS = item_db_verification.RESOURCE_PACK_SOURCE_FIELDS
_SOURCE_ITEM_LISTING_FIELDS = item_db_verification.ITEM_LISTING_SOURCE_FIELDS
_SOURCE_WIKI_FIELDS = item_db_verification.WIKI_SOURCE_FIELDS
_SOURCE_IDENTITY_DEFAULTS = item_db_verification.SOURCE_IDENTITY_DEFAULTS
source_identity_from_metadata = item_db_verification.source_identity_from_metadata
_SOURCE_STRING_FIELDS = {
    "resource_pack_release",
    "resource_pack_asset",
    "resource_pack_url",
    "resource_pack_fetched_at",
    "microsoft_item_listing_url",
    "microsoft_item_listing_content_hash",
    "microsoft_item_listing_items_hash",
    "microsoft_item_listing_fetched_at",
    "wiki_url",
    "wiki_content_hash",
    "wiki_fetched_at",
    "generated_at",
}
_SOURCE_NONNEGATIVE_INT_FIELDS = {
    "resource_pack_asset_size",
    "microsoft_item_listing_count",
}


def _valid_source_metadata(data: object) -> bool:
    if not isinstance(data, dict):
        return False
    for field in _SOURCE_STRING_FIELDS:
        if field in data and not isinstance(data[field], str):
            return False
    for field in _SOURCE_NONNEGATIVE_INT_FIELDS:
        if field in data:
            value = data[field]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                return False
    if "wiki_revision_id" in data:
        revision = data["wiki_revision_id"]
        if revision is not None and (isinstance(revision, bool) or not isinstance(revision, int) or revision < 0):
            return False
    return "microsoft_item_listing_items_hash" not in data or bool(re.fullmatch(r"[0-9a-f]{64}", data["microsoft_item_listing_items_hash"]))


def build_source_identity(release_info: dict, wiki_snapshot: dict, item_listing_snapshot: dict | None = None) -> dict:
    return source_identity_from_metadata({**release_info, **wiki_snapshot, **(item_listing_snapshot or {})})


def merge_source_metadata(
    previous: dict,
    *,
    release_info: dict | None = None,
    wiki_snapshot: dict | None = None,
    item_listing_snapshot: dict | None = None,
) -> dict:
    """Merge only sources fetched by this update into existing metadata."""

    metadata = dict(previous)
    if release_info is not None:
        for field in _SOURCE_RESOURCE_PACK_FIELDS:
            metadata[field] = release_info.get(field, _SOURCE_IDENTITY_DEFAULTS[field])
        metadata["resource_pack_fetched_at"] = release_info.get("resource_pack_fetched_at", "")
    if item_listing_snapshot is not None:
        for field in _SOURCE_ITEM_LISTING_FIELDS:
            metadata[field] = item_listing_snapshot.get(field, _SOURCE_IDENTITY_DEFAULTS[field])
        metadata["microsoft_item_listing_fetched_at"] = item_listing_snapshot.get("microsoft_item_listing_fetched_at", "")
        if "microsoft_item_listing_items_hash" in item_listing_snapshot:
            metadata["microsoft_item_listing_items_hash"] = item_listing_snapshot["microsoft_item_listing_items_hash"]
        else:
            metadata.pop("microsoft_item_listing_items_hash", None)
    if wiki_snapshot is not None:
        for field in _SOURCE_WIKI_FIELDS:
            metadata[field] = wiki_snapshot.get(field, _SOURCE_IDENTITY_DEFAULTS[field])
        metadata["wiki_fetched_at"] = wiki_snapshot.get("wiki_fetched_at", "")
    else:
        # The wiki stamp is valid only for the run that performed --check-wiki.
        # It records a comparison, not data used to build the database.
        for field in (*_SOURCE_WIKI_FIELDS, "wiki_fetched_at"):
            metadata.pop(field, None)
    metadata["generated_at"] = utc_now()
    return metadata


def build_source_metadata(release_info: dict, wiki_snapshot: dict, item_listing_snapshot: dict | None = None) -> dict:
    return merge_source_metadata(
        {},
        release_info=release_info or None,
        wiki_snapshot=wiki_snapshot,
        item_listing_snapshot=item_listing_snapshot or {},
    )


def read_source_version() -> dict:
    if not SOURCE_VERSION_JSON.exists():
        return {}
    try:
        data = json.loads(SOURCE_VERSION_JSON.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, OSError, RecursionError):
        return {}
    return data if _valid_source_metadata(data) else {}


def write_source_version(metadata: dict) -> None:
    SOURCE_VERSION_JSON.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(SOURCE_VERSION_JSON, json.dumps(metadata, indent=2, sort_keys=True) + "\n")


def append_source_version_history(entry: dict) -> None:
    SOURCE_VERSION_HISTORY.parent.mkdir(parents=True, exist_ok=True)
    history: list[dict] = []
    if SOURCE_VERSION_HISTORY.exists():
        try:
            data = json.loads(SOURCE_VERSION_HISTORY.read_text(encoding="utf-8"))
            if isinstance(data, list):
                history = [item for item in data if _valid_source_metadata(item)]
        except (UnicodeDecodeError, json.JSONDecodeError, OSError, RecursionError):
            pass
    history.append(entry)
    atomic_write_text(SOURCE_VERSION_HISTORY, json.dumps(history, indent=2, ensure_ascii=False) + "\n")


def commit_update_files(
    items: dict[str, tuple[str, str]],
    effects: dict[int, tuple[str, str, str, str]],
    enchants: dict[int, tuple[str, str, int, str]],
    *,
    block_only_items: list[str] | None,
    block_items: list[str] | None,
    addable_items: list[str] | None,
    write_item_db: bool,
    source_metadata: dict | None,
    append_source_history: bool = True,
    verify_item_db: bool = False,
    stack_limits: dict[str, int] | None = None,
    durability: dict[str, int] | None = None,
    item_components: dict[str, dict[str, dict]] | None = None,
    behavior_item_source: dict | None = None,
    updated_sections: set[str] | None = None,
    confirmed_item_labels: dict | None = None,
) -> None:
    """Commit item data and matching source metadata as one recoverable unit."""

    if verify_item_db and source_metadata is None:
        raise ValueError(tr("Ein Item-DB-Prüfbeleg benötigt Quellenmetadaten."))
    targets = item_db_transaction.configured_targets(ITEM_DB_PATH, SOURCE_VERSION_JSON, SOURCE_VERSION_HISTORY)
    with item_db_transaction.item_db_transaction(targets):
        if write_item_db:
            write_all_dicts(
                items,
                effects,
                enchants,
                block_only_items=block_only_items,
                block_items=block_items,
                addable_items=addable_items,
                stack_limits=stack_limits,
                durability=durability,
                item_components=item_components,
                behavior_item_source=behavior_item_source,
                updated_sections=updated_sections,
                confirmed_item_labels=confirmed_item_labels,
            )
        if source_metadata is not None:
            committed_metadata = source_metadata
            if verify_item_db:
                committed_metadata = item_db_verification.attach_item_db_verification(
                    source_metadata,
                    ITEM_DB_PATH,
                    verified_at=utc_now(),
                )
            write_source_version(committed_metadata)
            if append_source_history:
                append_source_version_history(committed_metadata)


# ─── DIFF ───────────────────────────────────────────────────────────────────


def show_diff(label: str, old: dict, new: dict) -> bool:
    """Generic diff. Returns True if changes exist."""
    old_keys = set(old.keys())
    new_keys = set(new.keys())
    added = new_keys - old_keys
    removed = old_keys - new_keys
    common = old_keys & new_keys
    changed = {k for k in common if old[k] != new[k]}

    if not added and not removed and not changed:
        log(f"  {Colors.GREEN}{tr('{label}: aktuell ({count} Einträge)', label=label, count=len(old))}{Colors.END}")
        return False

    log(f"\n  {Colors.BOLD}{'-' * 50}{Colors.END}")
    log(f"  {Colors.BOLD}{label}{Colors.END}")
    log(f"  {Colors.BOLD}{'-' * 50}{Colors.END}")

    if added:
        log(f"\n  {Colors.GREEN}{tr('Neu (+{count}):', count=len(added))}{Colors.END}")
        for k in sorted(added):
            log(f"    + {k}: {new[k]}", color=Colors.GREEN)

    if removed:
        log(f"\n  {Colors.RED}{tr('Entfernt (-{count}):', count=len(removed))}{Colors.END}")
        for k in sorted(removed):
            log(f"    - {k}: {old[k]}", color=Colors.RED)

    if changed:
        log(f"\n  {Colors.YELLOW}{tr('Geändert (~{count}):', count=len(changed))}{Colors.END}")
        for k in sorted(changed):
            log(f"    ~ {k}: {old[k]} -> {new[k]}", color=Colors.YELLOW)

    log(
        tr(
            "\n  Statistik: {old_count} -> {new_count} (+{added_count} / -{removed_count} / ~{changed_count})",
            old_count=len(old),
            new_count=len(new),
            added_count=len(added),
            removed_count=len(removed),
            changed_count=len(changed),
        )
    )
    return True


# ─── MAIN ───────────────────────────────────────────────────────────────────


def report_blocked_sections(blocked_sections: list[tuple[str, str]]) -> int:
    """Log skipped sections and return the process exit code.

    Ein Abschnitt, dem geprüfte lokale Daten fehlen (z. B. eine numerische ID
    für einen neuen Mojang-Effekt), wird bewusst nicht geraten. Er darf aber
    auch nicht den gesamten Lauf mitreißen: die übrigen Abschnitte sind
    voneinander unabhängig und werden regulär geschrieben. Der Exit-Code stellt
    sicher, dass der übersprungene Abschnitt in Skripten nicht untergeht.
    """

    if not blocked_sections:
        return 0
    log(f"\n  {Colors.BOLD}{Colors.RED}{tr('Übersprungene Abschnitte ({count}):', count=len(blocked_sections))}{Colors.END}")
    for section_name, reason in blocked_sections:
        log(f"    {Colors.RED}{section_name}: {reason}{Colors.END}")
    log(f"  {Colors.YELLOW}{tr('Alle übrigen Abschnitte wurden regulär verarbeitet. Fehlende Werte kuratieren und erneut ausführen.')}{Colors.END}")
    return 1


@report_http_errors
def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description=tr("Aktualisiert item_db.json aus Mojang/bedrock-samples und lokal geprüften Vanilla-Fakten."),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--dry-run", action="store_true", help=tr("Nur anzeigen, nicht schreiben"))
    parser.add_argument("--json-summary", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--force", action="store_true", help=tr("Ohne Nachfrage schreiben"))
    parser.add_argument(
        "--cache",
        "--reuse-cached-release",
        dest="cache",
        action="store_true",
        help=tr("Im Dry-Run geprüfte Quellen ohne erneuten Online-Abruf verarbeiten"),
    )
    parser.add_argument(
        "--expected-review-token",
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--only", choices=["items", "effects", "enchants"], help=tr("Nur bestimmte Daten aktualisieren"))
    parser.add_argument(
        "--check-wiki",
        action="store_true",
        help=tr("Maximalstufen optional mit der Minecraft Wiki vergleichen; Abweichungen werden nicht übernommen"),
    )
    args = parser.parse_args()
    if args.expected_review_token:
        if not args.cache:
            raise RuntimeError(tr("Ein Dry-Run-Prüfbeleg kann nur mit dem internen Cache-Replay verwendet werden."))
        if not re.fullmatch(r"[0-9a-f]{64}", args.expected_review_token):
            raise RuntimeError(tr("Der Dry-Run-Prüfbeleg ist ungültig."))

    targets = item_db_transaction.configured_targets(ITEM_DB_PATH, SOURCE_VERSION_JSON, SOURCE_VERSION_HISTORY)
    with item_db_transaction.item_db_update_operation(targets, allow_parent_lock=True):
        return _run_update(args)


def _previous_item_label_records(stored, items, locales, metadata):
    """Read exact automatic baselines, including reconstructible older Learn fallbacks."""
    records = {}
    borrowed = update_source_quality.borrowed_item_locales(locales)
    for key, record in stored.items() if isinstance(stored, dict) else ():
        pair = confirmed_item_label_pair(record)
        if key in items and pair:
            if not isinstance(record, dict) and pair[0] == pair[1] and borrowed.get(key):
                record = {"names": pair, "borrowed": borrowed[key]}
            records[key] = record
    for entry in locales.get("en", {}).get("fallbacks", []):
        key = entry["id"]
        if entry["source"] == "microsoft" and key in items and key not in records:
            # Learn publishes the identifier. Its rendered title is reproducible
            # even when the next release no longer lists it.
            title = _friendly_name_from_identifier(key.removeprefix("minecraft:"))
            reviewed = _bundled_limits["items"].get(key, (None, None))
            records[key] = {"names": [title, title], "borrowed": "de"} if borrowed.get(key) == "de" else [reviewed[0], title]
    # Older quality reports identify the borrowed locale but omit the actual
    # wording. Recover it only from the exact file the report verified.
    official = {
        locale: items.keys() - {row["id"] for row in section["fallbacks"] + section.get("retained", [])}
        for locale, section in locales.items()
        if len(section["fallbacks"]) == section["total"] - section["official"]
    }
    candidates = {
        key: locale
        for key, locale in borrowed.items()
        if locale and key not in records and key in items and items[key][0] == items[key][1] and key in official.get("de" if locale == "en" else "en", ())
    }
    if candidates and item_db_verification.item_db_verification_snapshot(metadata, ITEM_DB_PATH, require_current_contract=False)["verified"]:
        for key, locale in candidates.items():
            records[key] = {"names": list(items[key]), "borrowed": locale}
    return records


def _prepare_item_update(
    zf,
    en_lang,
    de_lang,
    *,
    release_info,
    reuse_cached,
    old_items,
    old_stack_limits,
    old_durability,
    old_item_components,
    old_behavior_item_source,
    previous_item_locales,
    previous_metadata,
):
    """Prepare one complete item section without changing the publishable state."""
    from mcbe_editor.update_db_report import audit_items

    final_items = old_items
    final_stack_limits = old_stack_limits
    final_durability = old_durability
    final_item_components = old_item_components
    final_behavior_item_source = old_behavior_item_source
    final_block_only = final_block_items = final_addable_items = None
    changes = []
    sections = {}
    step(tr("3/4 · Items verarbeiten"))
    component_stack_limits, component_durability, new_item_components = parse_json_item_components(zf)
    en_item_names, de_item_names = parse_lang_items(en_lang, de_lang) if en_lang else ({}, {})
    item_localizations = parse_lang_item_localizations(en_lang, de_lang) if en_lang else {}
    item_serialization_aliases = parse_json_item_serialization_aliases(zf)
    microsoft_items, item_listing_snapshot = resolve_microsoft_item_listing_snapshot(reuse_cached=reuse_cached)
    log(f"  {Colors.GREEN}{tr('Microsoft-Learn-Item-IDs: {count}', count=len(microsoft_items))}{Colors.END}")
    log(f"  {Colors.GREEN}{tr('Vollständige Item-Lokalisierungen: {count}', count=len(item_localizations))}{Colors.END}")
    if item_serialization_aliases:
        log(f"  {Colors.GREEN}{tr('Mojang-Serialization-Aliasse: {count}', count=len(item_serialization_aliases))}{Colors.END}")
    new_addable_items = compute_addable_item_ids(zf, old_items)
    source_labels = item_localization.registry_item_labels(
        new_addable_items,
        json.loads(read_utf8(zf, "metadata/vanilladata_modules/mojang-items.json")),
        json.loads(read_utf8(zf, "metadata/vanilladata_modules/mojang-blocks.json")),
        {
            "en": item_localization.parse_source_labels(en_lang.read_text(encoding="utf-8-sig")),
            "de": item_localization.parse_source_labels(de_lang.read_text(encoding="utf-8-sig")) if de_lang else {},
        },
        microsoft_items,
    )
    raw_db = _load_item_db_json()
    old_confirmed = raw_db.get("confirmed_item_labels", {})
    previous_confirmed = _previous_item_label_records(old_confirmed, old_items, previous_item_locales, previous_metadata)
    confirmed_labels = {}
    new_items = merge_items(
        old_items,
        en_item_names,
        de_item_names,
        microsoft_items,
        item_serialization_aliases,
        item_localizations,
        new_addable_items,
        source_labels,
        label_records=confirmed_labels,
        previous_confirmed=previous_confirmed,
        has_explicit_registry=isinstance(raw_db.get("addable_items"), list),
        registry_label_ids=_vanilla_registry_ids(zf, "mojang-items.json") | _vanilla_registry_ids(zf, "mojang-blocks.json"),
    )
    new_items = complete_registry_names(new_items, new_addable_items, _bundled_limits.get("items", {}))
    confirmed_labels = {key: record for key, record in confirmed_labels.items() if key in new_items}
    if show_diff("ITEMS", old_items, new_items):
        changes.append("ITEMS")
        final_items = format_items(new_items)
    log(f"  {Colors.GREEN}{tr('Items: {old_count} -> {new_count}', old_count=len(old_items), new_count=len(new_items))}{Colors.END}")

    new_block_only = compute_block_only_item_ids(zf, new_items)
    old_block_only = read_block_only_item_ids()
    if new_block_only and new_block_only != old_block_only:
        show_diff("BLOCK_ONLY_ITEMS", dict.fromkeys(old_block_only, True), dict.fromkeys(new_block_only, True))
        changes.append("BLOCK_ONLY_ITEMS")
        final_block_only = new_block_only
    message = tr(
        "Block-only-IDs: {old_count} -> {new_count}",
        old_count=len(old_block_only),
        new_count=len(new_block_only),
    )
    log(f"  {Colors.GREEN}{message}{Colors.END}")

    old_addable_items = read_addable_item_ids()
    if new_addable_items and new_addable_items != old_addable_items:
        show_diff("ADDABLE_ITEMS", dict.fromkeys(old_addable_items, True), dict.fromkeys(new_addable_items, True))
        changes.append("ADDABLE_ITEMS")
        final_addable_items = new_addable_items
    message = tr(
        "Neu hinzufügbar: {old_count} -> {new_count}",
        old_count=len(old_addable_items),
        new_count=len(new_addable_items),
    )
    log(f"  {Colors.GREEN}{message}{Colors.END}")

    new_behavior_item_source = build_behavior_item_source(
        release_info,
        component_stack_limits,
        component_durability,
    )
    new_stack_limits, new_durability = merge_item_limits(
        old_stack_limits,
        old_durability,
        component_stack_limits,
        component_durability,
        previous_component_stack_items=set(old_behavior_item_source["stack_limit_items"]),
        previous_component_durability_items=set(old_behavior_item_source["durability_items"]),
    )
    if new_stack_limits != old_stack_limits:
        show_diff("STACK_LIMITS", old_stack_limits, new_stack_limits)
        changes.append("STACK_LIMITS")
        final_stack_limits = new_stack_limits
    unverified_stack_count = len(set(new_addable_items) - set(new_stack_limits))
    if unverified_stack_count:
        log(
            tr(
                "Ungeprüfte Stacklimits: {count}. Neue Stapel dieser Items bleiben auf Menge 1 begrenzt.",
                count=unverified_stack_count,
            )
        )
    message = tr(
        "Stack-Limits: {old_count} -> {new_count}",
        old_count=len(old_stack_limits),
        new_count=len(new_stack_limits),
    )
    log(f"  {Colors.GREEN}{message}{Colors.END}")

    if new_durability != old_durability:
        show_diff("DURABILITY", old_durability, new_durability)
        changes.append("DURABILITY")
        final_durability = new_durability
    message = tr(
        "Haltbarkeitswerte: {old_count} -> {new_count}",
        old_count=len(old_durability),
        new_count=len(new_durability),
    )
    log(f"  {Colors.GREEN}{message}{Colors.END}")

    if new_item_components != old_item_components:
        for component_name in TRACKED_ITEM_COMPONENTS:
            old_values = old_item_components.get(component_name, {})
            new_values = new_item_components.get(component_name, {})
            if old_values != new_values:
                show_diff(f"ITEM_COMPONENTS.{component_name}", old_values, new_values)
        changes.append("ITEM_COMPONENTS")
        final_item_components = new_item_components
    component_counts = ", ".join(f"{component}={len(new_item_components.get(component, {}))}" for component in TRACKED_ITEM_COMPONENTS)
    log(f"  {Colors.GREEN}{tr('Offizielle Item-Komponenten: {component_counts}', component_counts=component_counts)}{Colors.END}")
    if new_behavior_item_source != old_behavior_item_source:
        show_diff(
            "BEHAVIOR_ITEM_SOURCE",
            old_behavior_item_source,
            new_behavior_item_source,
        )
        changes.append("BEHAVIOR_ITEM_SOURCE")
        final_behavior_item_source = new_behavior_item_source

    new_block_items = compute_block_item_ids(zf)
    old_block_items = read_block_item_ids()
    if new_block_items != old_block_items:
        show_diff("BLOCK_ITEMS", dict.fromkeys(old_block_items, True), dict.fromkeys(new_block_items, True))
        changes.append("BLOCK_ITEMS")
        final_block_items = new_block_items
    message = tr(
        "Block-Item-IDs: {old_count} -> {new_count}",
        old_count=len(old_block_items),
        new_count=len(new_block_items),
    )
    log(f"  {Colors.GREEN}{message}{Colors.END}")

    quality = item_label_quality(
        new_addable_items,
        final_items,
        old_items,
        en_item_names,
        de_item_names,
        item_serialization_aliases,
        item_localizations,
        microsoft_items,
        source_labels,
        label_records=confirmed_labels,
    )
    if old_confirmed != confirmed_labels:
        sections["confirmed_item_labels"] = (old_confirmed if isinstance(old_confirmed, dict) else {}, confirmed_labels)
        changes.append("CONFIRMED_ITEM_LABELS")
    sections.update(
        {
            "items": (old_items, final_items),
            "stack_limits": (old_stack_limits, final_stack_limits),
            "durability": (old_durability, final_durability),
            "addable_items": (
                dict.fromkeys(old_addable_items),
                dict.fromkeys(final_addable_items if final_addable_items is not None else old_addable_items),
            ),
            "block_only_items": (
                dict.fromkeys(old_block_only),
                dict.fromkeys(final_block_only if final_block_only is not None else old_block_only),
            ),
            "block_items": (dict.fromkeys(old_block_items), dict.fromkeys(final_block_items if final_block_items is not None else old_block_items)),
        }
    )
    for component in TRACKED_ITEM_COMPONENTS:
        sections[component] = (old_item_components.get(component, {}), final_item_components.get(component, {}))
    label_index = build_item_localization_label_index(item_localizations)
    audit_names = {"de": {}, "en": {}}
    for full_id in new_addable_items:
        _names, official, _sources = _resolved_item_names(
            full_id.removeprefix("minecraft:"),
            old_items,
            en_item_names,
            de_item_names,
            microsoft_items,
            item_serialization_aliases,
            item_localizations,
            label_index,
            source_labels,
        )
        for locale, value in official.items():
            if value:
                audit_names[locale][full_id] = value
    audit = audit_items(
        final_items,
        new_addable_items,
        final_stack_limits,
        final_durability,
        audit_names,
        {"stack_limits": component_stack_limits, "durability": component_durability},
        {"stack_limits": CURATED_ENGINE_STACK_LIMITS, "durability": CURATED_ENGINE_DURABILITY},
    )
    log(tr("Automatischer Abgleich: {count} Katalogeinträge geprüft.", count=audit["checked_items"]))
    for issue in audit["issues"]:
        log(f"  {issue['code']} ({issue['count']}): {', '.join(issue['items'])}")
    return {
        "items": final_items,
        "stack_limits": final_stack_limits,
        "durability": final_durability,
        "item_components": final_item_components,
        "behavior_item_source": final_behavior_item_source,
        "block_only_items": final_block_only,
        "block_items": final_block_items,
        "addable_items": final_addable_items,
        "listing": item_listing_snapshot,
        "confirmed_item_labels": confirmed_labels,
        "quality": quality,
        "audit": audit,
        "sections": sections,
        "changes": changes,
    }


def _run_update(args) -> int:
    from mcbe_editor.update_db_report import REPORT_PREFIX, build_report, snapshot_update_quality

    # Recover the complete generation before reading any of its base state.
    item_db_transaction.recover_item_db(item_db_transaction.configured_targets(ITEM_DB_PATH, SOURCE_VERSION_JSON, SOURCE_VERSION_HISTORY))
    ensure_data_paths()
    review_paths = {
        "update_cache_dir": CACHE_DIR,
        "item_db_path": ITEM_DB_PATH,
        "source_version_path": SOURCE_VERSION_JSON,
        "source_version_history_path": SOURCE_VERSION_HISTORY,
        "scope": args.only,
    }
    if args.dry_run:
        # A failed or interrupted preview must never reuse an earlier plan.
        (CACHE_DIR / item_db_verification.UPDATE_REVIEW_PLAN_FILENAME).unlink(missing_ok=True)
    reviewed_blocks = {}
    old_version = read_source_version()
    previous_quality = snapshot_update_quality(old_version.get("update_quality"))
    requested = (args.only,) if args.only else ("items", "effects", "enchants")
    section_labels = {"items": "ITEMS", "effects": "EFFECTS", "enchants": "ENCHANTMENTS"}

    def reject_source(reason: str, release: str | None = None) -> int:
        blocked = [(section_labels[section], reason) for section in requested]
        quality = update_source_quality.merge_quality(previous_quality, release, requested, {}, dict.fromkeys(requested, reason))
        report = build_report(
            scope=args.only,
            release=release,
            previous_release=old_version.get("resource_pack_release"),
            sections={},
            metadata_changed=False,
            audit=None,
            blocked=blocked,
            quality=quality,
        )
        if args.json_summary:
            print(REPORT_PREFIX + json.dumps(report, ensure_ascii=True))
        log(reason)
        return 1

    log(f"{Colors.BOLD}{Colors.CYAN}{'=' * 60}{Colors.END}")
    log(f"{Colors.BOLD}  {tr('Minecraft Bedrock Item-DB-Updater (Items + Effekte + Verzauberungen)')}{Colors.END}")
    log(f"{Colors.BOLD}{Colors.CYAN}{'=' * 60}{Colors.END}")

    report_progress("checking")
    log(f"  Item-DB: {ITEM_DB_PATH}", Colors.DIM)
    log(f"  Cache:   {CACHE_DIR}", Colors.DIM)

    if args.expected_review_token:
        try:
            current_review = item_db_verification.update_review_snapshot(**review_paths)
        except item_db_verification.UpdateReviewError as exc:
            raise RuntimeError(tr("Der Dry-Run-Prüfbeleg kann nicht validiert werden: {error}", error=exc)) from exc
        if not hmac.compare_digest(args.expected_review_token, current_review["token"]):
            raise RuntimeError(tr("Die geprüften Dry-Run-Eingaben haben sich geändert. Bitte den Dry-Run erneut ausführen."))
        reviewed_blocks = current_review["blocked_sections"]
        log(f"  {Colors.GREEN}{tr('Dry-Run-Prüfbeleg validiert ({scope})', scope=current_review['scope'])}{Colors.END}")

    step(tr("1/4  Resource Pack herunterladen"))
    rp_zip = CACHE_DIR / "bedrock_resource_pack.zip"
    release_info: dict = {}
    if args.cache:
        if not rp_zip.exists():
            raise RuntimeError(tr("Kein gecachtes Resource-Pack für die erneute Verarbeitung vorhanden."))
        report_progress("cached")
        release_info = read_release_metadata()
        if not release_info:
            raise RuntimeError(tr("Die Metadaten des gecachten Resource-Packs fehlen oder sind ungültig."))
        try:
            item_db_verification.validate_resource_pack_archive(rp_zip, release_info)
            _validate_downloaded_zip(rp_zip)
        except (RuntimeError, item_db_verification.UpdateReviewError) as exc:
            return reject_source(str(exc), release_info.get("resource_pack_release"))
        message = tr(
            "Verwende gecachtes Release ohne Online-Versionsprüfung: {release}",
            release=release_info["resource_pack_release"],
        )
        log(f"  {Colors.YELLOW}{message}{Colors.END}")
    else:
        release_info = resolve_latest_rp(rp_zip)

    try:
        with open_zip(rp_zip) as source:
            source_blocks = validate_update_sources(source, args.only, allow_partial=True)
        # Replaying a preview cannot promote a blocked section merely because
        # an unused older cache happens to be readable during this apply.
        source_blocks.update(reviewed_blocks)
    except RuntimeError as exc:
        return reject_source(str(exc), release_info.get("resource_pack_release"))
    except (OSError, zipfile.BadZipFile):
        return reject_source(tr("Resource-Pack-Download ist keine gültige ZIP-Datei."), release_info.get("resource_pack_release"))

    step(tr("2/4  Daten extrahieren und parsen"))
    report_progress("processing")
    old_items, old_effects, old_enchants = read_all_dicts()
    old_stack_limits = read_stack_limits()
    old_durability = read_durability()
    old_item_components = read_item_components()
    old_behavior_item_source = read_behavior_item_source()
    final_items = old_items
    final_effects = old_effects
    final_enchants = old_enchants
    final_stack_limits = old_stack_limits
    final_durability = old_durability
    final_item_components = old_item_components
    final_behavior_item_source = old_behavior_item_source
    final_block_only: list[str] | None = None
    final_block_items: list[str] | None = None
    final_addable_items: list[str] | None = None
    final_confirmed_item_labels = None
    changes: list[str] = []
    blocked_sections: list[tuple[str, str]] = [(section_labels[section], reason) for section, reason in source_blocks.items()]
    checked_quality: dict = {}
    pending_source_version: dict | None = None
    audit = None
    sections = {}

    en_content = de_content = ""
    en_lang = de_lang = None
    item_listing_snapshot: dict | None = None
    wiki_snapshot: dict | None = None

    with open_zip(rp_zip) as zf:
        # Extract .lang files to temp
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for locale in ("en_US", "de_DE"):
                dest = tmp_path / f"{locale}.lang"
                with zf.open(f"resource_pack/texts/{locale}.lang") as src, open(dest, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                if locale == "en_US":
                    en_lang = dest
                else:
                    de_lang = dest

            en_content = en_lang.read_text(encoding="utf-8-sig") if en_lang else ""
            de_content = de_lang.read_text(encoding="utf-8-sig") if de_lang else ""

            # A section becomes publishable only after every part validates.
            if "items" in requested and "items" not in source_blocks:
                try:
                    prepared = _prepare_item_update(
                        zf,
                        en_lang,
                        de_lang,
                        release_info=release_info,
                        reuse_cached=args.cache,
                        old_items=old_items,
                        old_stack_limits=old_stack_limits,
                        old_durability=old_durability,
                        old_item_components=old_item_components,
                        old_behavior_item_source=old_behavior_item_source,
                        previous_item_locales=previous_quality.get("sections", {}).get("items", {}).get("locales", {}),
                        previous_metadata=old_version,
                    )
                    audit = prepared["audit"]
                    if any(issue["severity"] == "error" for issue in audit["issues"]):
                        raise RuntimeError(tr("Der Item-Abgleich enthält ungültige Daten. Der Item-Bereich bleibt unverändert."))
                except RuntimeError as exc:
                    source_blocks["items"] = str(exc)
                    blocked_sections.append(("ITEMS", str(exc)))
                    log(f"  {Colors.RED}{tr('ITEMS übersprungen: {error}', error=exc)}{Colors.END}")
                else:
                    final_items = prepared["items"]
                    final_stack_limits = prepared["stack_limits"]
                    final_durability = prepared["durability"]
                    final_item_components = prepared["item_components"]
                    final_behavior_item_source = prepared["behavior_item_source"]
                    final_block_only = prepared["block_only_items"]
                    final_block_items = prepared["block_items"]
                    final_addable_items = prepared["addable_items"]
                    item_listing_snapshot = prepared["listing"]
                    final_confirmed_item_labels = prepared["confirmed_item_labels"]
                    checked_quality["items"] = prepared["quality"]
                    sections.update(prepared["sections"])
                    changes.extend(prepared["changes"])

            if "effects" in requested and "effects" not in source_blocks:
                step(tr("3/4 · Effekte verarbeiten"))
                # Fehlen geprüfte numerische IDs, bleibt der Abschnitt bewusst
                # ungeschrieben — geraten wird hier nicht. Items, Blocklisten und
                # Verzauberungen sind davon unabhängig und laufen weiter.
                try:
                    json_effects = parse_json_effects(zf)
                    en_eff_names = parse_lang_effects(en_content)
                    de_eff_names = parse_lang_effects(de_content)
                    local_effect_numeric_ids = load_local_effect_numeric_ids()
                    log(f"  {Colors.GREEN}{tr('Lokale numerische Effekt-IDs: {count}', count=len(local_effect_numeric_ids))}{Colors.END}")
                    new_effects = merge_effects(
                        old_effects,
                        json_effects,
                        en_eff_names,
                        de_eff_names,
                        local_effect_numeric_ids,
                    )
                except RuntimeError as exc:
                    blocked_sections.append(("EFFECTS", str(exc)))
                    log(f"  {Colors.RED}{tr('EFFECTS übersprungen: {error}', error=exc)}{Colors.END}")
                else:
                    checked_quality["effects"] = numeric_label_quality(
                        old_effects, new_effects, json_effects, local_effect_numeric_ids, en_eff_names, de_eff_names, kind="effects"
                    )
                    if show_diff("EFFECTS", old_effects, new_effects):
                        changes.append("EFFECTS")
                        final_effects = format_effects(new_effects)
                    log(f"  {Colors.GREEN}{tr('Effekte: {old_count} -> {new_count}', old_count=len(old_effects), new_count=len(new_effects))}{Colors.END}")

        # ── ENCHANTMENTS ── (zip still open, tmp dir closed — content strings remain)
        if "enchants" in requested and "enchants" not in source_blocks:
            step(tr("3/4 · Verzauberungen verarbeiten"))
            # Gleiche Begründung wie bei den Effekten: fehlende geprüfte IDs
            # blockieren nur diesen Abschnitt, nicht den gesamten Lauf.
            try:
                json_enchants = parse_json_enchantments(zf)
                en_ench_names = parse_lang_enchantments(en_content)
                de_ench_names = parse_lang_enchantments(de_content)
                local_max_levels = load_local_enchantment_max_levels()
                local_numeric_ids = load_local_enchantment_numeric_ids()
                message = tr(
                    "Lokale Verzauberungsdaten: {level_count} Maximalstufen, {id_count} numerische IDs",
                    level_count=len(local_max_levels),
                    id_count=len(local_numeric_ids),
                )
                log(f"  {Colors.GREEN}{message}{Colors.END}")
                new_enchants = merge_enchantments(
                    old_enchants,
                    json_enchants,
                    en_ench_names,
                    de_ench_names,
                    local_max_levels,
                    local_numeric_ids,
                )
                wiki_snapshot = optional_wiki_enchantment_check(args.check_wiki, local_max_levels)
            except RuntimeError as exc:
                blocked_sections.append(("ENCHANTMENTS", str(exc)))
                log(f"  {Colors.RED}{tr('ENCHANTMENTS übersprungen: {error}', error=exc)}{Colors.END}")
            else:
                checked_quality["enchants"] = numeric_label_quality(
                    old_enchants, new_enchants, [name for name, _level in json_enchants], local_numeric_ids, en_ench_names, de_ench_names, kind="enchantments"
                )
                if show_diff("ENCHANTMENTS", old_enchants, new_enchants):
                    changes.append("ENCHANTMENTS")
                    final_enchants = format_enchantments(new_enchants)
                log(f"  {Colors.GREEN}{tr('Verzauberungen: {old_count} -> {new_count}', old_count=len(old_enchants), new_count=len(new_enchants))}{Colors.END}")

    if "items" in source_blocks:
        sections["items"] = (old_items, old_items)
    if not args.only or args.only == "effects":
        sections["effects"] = (old_effects, final_effects)
    if not args.only or args.only == "enchants":
        sections["enchants"] = (old_enchants, final_enchants)
    new_version = merge_source_metadata(
        old_version,
        release_info=release_info or None,
        wiki_snapshot=wiki_snapshot,
        item_listing_snapshot=item_listing_snapshot,
    )
    blocked_by_section = {section: reason for label, reason in blocked_sections for section in requested if section_labels[section] == label}
    quality = update_source_quality.merge_quality(previous_quality, release_info.get("resource_pack_release"), requested, checked_quality, blocked_by_section)
    new_version["update_quality"] = quality
    quality_changed = old_version.get("update_quality") != quality
    verification_eligible = args.only is None and not blocked_sections
    old_identity = source_identity_from_metadata(old_version)
    new_identity = source_identity_from_metadata(new_version)
    source_identity_changed = old_identity != new_identity
    receipt_removed = (
        not verification_eligible
        and item_db_verification.VERIFICATION_FIELD in old_version
        and (bool(changes) or source_identity_changed or quality_changed or bool(blocked_sections))
    )
    report = build_report(
        scope=args.only,
        release=release_info.get("resource_pack_release"),
        previous_release=old_version.get("resource_pack_release"),
        sections=sections,
        metadata_changed=source_identity_changed or quality_changed or receipt_removed or old_behavior_item_source != final_behavior_item_source,
        audit=audit,
        blocked=blocked_sections,
        quality=quality,
    )
    if blocked_sections:
        # Recording a failure alone also commits metadata. Only data or source
        # changes in a successfully checked section make this a partial update.
        old_sections = previous_quality.get("sections", {})
        checked_source_fields = set(_SOURCE_RESOURCE_PACK_FIELDS) if checked_quality else set()
        if "items" in checked_quality:
            checked_source_fields.update((*_SOURCE_ITEM_LISTING_FIELDS, "microsoft_item_listing_items_hash"))
        if "enchants" in checked_quality and wiki_snapshot is not None:
            checked_source_fields.update(_SOURCE_WIKI_FIELDS)
        report["checked_sections_changed"] = (
            bool(changes)
            or any(quality["sections"][section] != old_sections.get(section) for section in checked_quality)
            or any(old_identity.get(field) != new_identity.get(field) for field in checked_source_fields)
        )
    if args.json_summary:
        print(REPORT_PREFIX + json.dumps(report, ensure_ascii=True))
    if source_identity_changed:
        show_diff("SOURCE_VERSION", old_version, new_version)
    if source_identity_changed or quality_changed or receipt_removed or verification_eligible:
        pending_source_version = dict(new_version)
        if not verification_eligible:
            pending_source_version.pop(item_db_verification.VERIFICATION_FIELD, None)

    if args.dry_run and checked_quality:
        try:
            item_db_verification.record_update_review_plan(blocked=blocked_by_section, **review_paths)
        except (OSError, item_db_verification.UpdateReviewError) as exc:
            raise RuntimeError(tr("Der Dry-Run-Prüfplan konnte nicht sicher gespeichert werden. Bitte die Prüfung erneut ausführen.")) from exc

    step(tr("4/4  Prüfung abschließen") if args.dry_run else tr("4/4  Änderungen schreiben"))
    report_progress("finalizing")
    if not changes and not source_identity_changed and not quality_changed and not receipt_removed:
        log(f"  {Colors.GREEN}{tr('Alles aktuell, keine Änderungen.')}{Colors.END}")
        if args.dry_run or not verification_eligible:
            return report_blocked_sections(blocked_sections)

    if args.dry_run:
        log(f"\n  {Colors.YELLOW}{tr('Dry-Run: Keine Änderungen geschrieben.')}{Colors.END}")
        return report_blocked_sections(blocked_sections)

    if not args.force:
        try:
            answer = input(f"\n  {Colors.BOLD}{tr('Schreiben? (j/N):')} {Colors.END}").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"
        if answer not in ("j", "ja", "y", "yes"):
            log(f"  {Colors.YELLOW}{tr('Abgebrochen.')}{Colors.END}")
            return report_blocked_sections(blocked_sections)

    commit_update_files(
        final_items,
        final_effects,
        final_enchants,
        block_only_items=final_block_only,
        block_items=final_block_items,
        addable_items=final_addable_items,
        write_item_db=bool(changes),
        source_metadata=pending_source_version,
        append_source_history=source_identity_changed,
        verify_item_db=verification_eligible,
        stack_limits=final_stack_limits,
        durability=final_durability,
        item_components=final_item_components,
        behavior_item_source=final_behavior_item_source,
        updated_sections=set(checked_quality),
        confirmed_item_labels=final_confirmed_item_labels,
    )
    # Publish the confirmed outcome after the atomic write, including partial
    # updates whose skipped sections still produce a nonzero exit code.
    report["applied"] = True
    if args.json_summary:
        print(REPORT_PREFIX + json.dumps(report, ensure_ascii=True))
    for block_name in changes:
        log(f"  {Colors.GREEN}{tr('{block_name} aktualisiert', block_name=block_name)}{Colors.END}")
    if source_identity_changed:
        log(f"  {Colors.GREEN}{tr('SOURCE_VERSION aktualisiert')}{Colors.END}")
    if verification_eligible:
        log(f"  {Colors.GREEN}{tr('ITEM_DB_PRÜFBELEG aktualisiert')}{Colors.END}")
    log(f"\n  {Colors.BOLD}{Colors.GREEN}{tr('Fertig! Update-Dateien konsistent aktualisiert.')}{Colors.END}")
    return report_blocked_sections(blocked_sections)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        log(f"\n  {Colors.RED}{exc}{Colors.END}")
        raise SystemExit(1) from exc
