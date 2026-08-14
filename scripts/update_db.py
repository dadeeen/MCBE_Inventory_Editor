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
    from mcbe_editor import item_db_verification
    from mcbe_editor.runtime_data import BUNDLED_ITEM_DB_JSON, atomic_seed_file

    return BUNDLED_ITEM_DB_JSON, atomic_seed_file, item_db_verification


BUNDLED_ITEM_DB_JSON, atomic_seed_file, item_db_verification = _load_runtime_dependencies()
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

# Nur Komponenten, die im Editor tatsächlich eine Entscheidung treffen:
# ``enchantable`` bestimmt die Verzauberungs-Kompatibilität, ``wearable`` die
# Rüstungsslots. Weitere Mojang-Komponenten werden bewusst nicht extrahiert;
# unbenutzte Daten mit fail-closed-Validierung können nur schaden.
TRACKED_ITEM_COMPONENTS = (
    "enchantable",
    "wearable",
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
    "customNautilus": "breath_of_the_nautilus",
    "fatalPoison": "fatal_poison",
    "fireResistance": "fire_resistance",
    "healthBoost": "health_boost",
    "instantDamage": "instant_damage",
    "instantHealth": "instant_health",
    "jumpBoost": "jump_boost",
    "miningFatigue": "mining_fatigue",
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
    "baneOfArthropods": "bane_of_arthropods",
    "blastProtection": "blast_protection",
    "depthStrider": "depth_strider",
    "featherFalling": "feather_falling",
    "fireAspect": "fire_aspect",
    "fireProtection": "fire_protection",
    "frostWalker": "frost_walker",
    "luckOfTheSea": "luck_of_the_sea",
    "projectileProtection": "projectile_protection",
    "quickCharge": "quick_charge",
    "respiration": "respiration",
    "silkTouch": "silk_touch",
    "soulSpeed": "soul_speed",
    "swiftSneak": "swift_sneak",
    "windBurst": "wind_burst",
}

# Mojang's JSON identifiers, .lang keys and the legacy names in item_db.py do not
# always use the same canonical name. Without these aliases the updater creates
# duplicate numeric IDs, which is unsafe because the UI writes these IDs back into
# player NBT data.
EFFECT_IDENTIFIER_ALIASES = {
    "village_hero": "hero_of_the_village",
}

ENCHANTMENT_IDENTIFIER_ALIASES = {
    "binding": "binding_curse",
    "curse_of_binding": "binding_curse",
    "bow_infinity": "infinity",
    "vanishing": "vanishing_curse",
    "curse_of_vanishing": "vanishing_curse",
}

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
        raise RuntimeError(f"Unsichere {label}-URL: {url!r}") from exc
    if parsed.scheme.lower() != "https" or host not in allowed_hosts or port not in (None, 443) or parsed.username is not None or parsed.password is not None:
        raise RuntimeError(f"Unsichere {label}-URL: {url!r}")
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
    identifier = _normalize_identifier(value)
    return EFFECT_IDENTIFIER_ALIASES.get(identifier, identifier)


def _canonical_enchantment_identifier(value: str) -> str:
    identifier = _normalize_identifier(value)
    return ENCHANTMENT_IDENTIFIER_ALIASES.get(identifier, identifier)


def _is_non_item_lang_identifier(identifier: str) -> bool:
    return any(identifier.startswith(prefix) for prefix in NON_ITEM_LANG_IDENTIFIER_PREFIXES)


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
                raise RuntimeError("GitHub-API-Antwort ist unerwartet gross.")
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise RuntimeError("GitHub-API-Antwort hat ein unerwartetes JSON-Format.")
            return data
    except (OSError, TimeoutError) as exc:
        raise RuntimeError(f"Fehler beim Laden von {url}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Ungültige JSON-Antwort von {url}: {exc}") from exc


def get_latest_release_info() -> dict:
    log("  Looking up latest release...", Colors.YELLOW)
    data = fetch_github_json(RP_LATEST_API)
    tag = data.get("tag_name", "unknown")
    log(f"  Found: {Colors.CYAN}{tag}{Colors.END} (official Mojang/bedrock-samples)")
    assets = data.get("assets")
    if not isinstance(assets, list):
        raise RuntimeError("GitHub-API-Antwort enthält keine gültige Asset-Liste.")
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        asset_name = str(asset.get("name", ""))
        asset_size = _safe_int(asset.get("size"), 0)
        if asset_name.endswith("-min.zip"):
            if asset_size <= 0 or asset_size > MAX_RESOURCE_PACK_BYTES:
                raise RuntimeError(f"Resource-Pack-Asset hat eine unerwartete Größe: {asset_size} Bytes")
            download_url = _validate_https_url(str(asset.get("browser_download_url", "")), ALLOWED_RESOURCE_PACK_HOSTS, label="Resource-Pack")
            info = {
                "resource_pack_release": tag,
                "resource_pack_asset": asset_name,
                "resource_pack_asset_size": asset_size,
                "resource_pack_fetched_at": utc_now(),
                "resource_pack_url": download_url,
            }
            log(f"  Asset: {Colors.GREEN}{asset_name}{Colors.END} ({asset_size // 1024 // 1024} MB)")
            return info
    raise RuntimeError(f"No min asset found in release {tag}")


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
    expected_size = _safe_int(cached_info.get("resource_pack_asset_size"), 0)
    try:
        if dest.stat().st_size != expected_size:
            return {}
        _validate_downloaded_zip(dest)
    except (OSError, RuntimeError):
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
    log(f"  {Colors.YELLOW}Lade MaxLevel-Tabelle aus der Minecraft Wiki...{Colors.END}")
    _validate_https_url(url, ALLOWED_WIKI_HOSTS, label="Minecraft-Wiki")
    opener = _build_validating_opener(ALLOWED_WIKI_HOSTS, label="Minecraft-Wiki")
    opener.addheaders = [("User-Agent", "MCBE-Inventory-Editor-Updater/1.0")]
    try:
        with opener.open(url, timeout=30) as resp:
            _validate_final_response_url(resp, ALLOWED_WIKI_HOSTS, label="Minecraft-Wiki")
            raw = resp.read(MAX_WIKI_BYTES + 1)
            if len(raw) > MAX_WIKI_BYTES:
                raise RuntimeError("Minecraft-Wiki-Antwort ist unerwartet gross.")
            content = raw.decode("utf-8", errors="replace")
    except (OSError, TimeoutError) as exc:
        message = f"Fehler beim Laden der Minecraft Wiki MaxLevel-Tabelle: {exc}"
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
        raise RuntimeError(f"Lokale Verzauberungs-Maximalstufen fehlen: {path}") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise RuntimeError(f"Lokale Verzauberungs-Maximalstufen sind nicht lesbar: {path}: {exc}") from exc

    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise RuntimeError("Lokale Verzauberungs-Maximalstufen haben eine unbekannte Schema-Version")
    raw_levels = data.get("max_levels")
    if not isinstance(raw_levels, dict) or not raw_levels:
        raise RuntimeError("Lokale Verzauberungs-Maximalstufen enthalten keine Einträge")

    levels: dict[str, int] = {}
    for raw_identifier, raw_level in raw_levels.items():
        if not isinstance(raw_identifier, str):
            raise RuntimeError("Lokale Verzauberungs-Maximalstufen enthalten einen ungültigen Identifier")
        identifier = _canonical_enchantment_identifier(raw_identifier)
        if identifier != raw_identifier or not re.fullmatch(r"[a-z0-9_]+", identifier):
            raise RuntimeError(f"Lokale Verzauberungs-Maximalstufen enthalten keinen kanonischen Identifier: {raw_identifier!r}")
        if isinstance(raw_level, bool) or not isinstance(raw_level, int) or not 1 <= raw_level <= 255:
            raise RuntimeError(f"Ungültige lokale Maximalstufe für {identifier}: {raw_level!r}")
        levels[identifier] = raw_level
    return dict(sorted(levels.items()))


def load_local_enchantment_numeric_ids(path: Path = ENCHANTMENT_MAX_LEVELS_PATH) -> dict[str, int]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"Lokale numerische Verzauberungs-IDs fehlen: {path}") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise RuntimeError(f"Lokale numerische Verzauberungs-IDs sind nicht lesbar: {path}: {exc}") from exc

    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise RuntimeError("Lokale numerische Verzauberungs-IDs haben eine unbekannte Schema-Version")
    raw_ids = data.get("numeric_ids")
    if not isinstance(raw_ids, dict) or not raw_ids:
        raise RuntimeError("Lokale numerische Verzauberungs-IDs enthalten keine Einträge")

    numeric_ids: dict[str, int] = {}
    used_ids: dict[int, str] = {}
    for raw_identifier, raw_id in raw_ids.items():
        if not isinstance(raw_identifier, str):
            raise RuntimeError("Lokale numerische Verzauberungs-IDs enthalten einen ungültigen Identifier")
        identifier = _canonical_enchantment_identifier(raw_identifier)
        if identifier != raw_identifier or not re.fullmatch(r"[a-z0-9_]+", identifier):
            raise RuntimeError(f"Lokale numerische Verzauberungs-IDs enthalten keinen kanonischen Identifier: {raw_identifier!r}")
        if isinstance(raw_id, bool) or not isinstance(raw_id, int) or not 0 <= raw_id <= 32767:
            raise RuntimeError(f"Ungültige lokale numerische ID für {identifier}: {raw_id!r}")
        duplicate = used_ids.get(raw_id)
        if duplicate is not None:
            raise RuntimeError(f"Numerische Verzauberungs-ID {raw_id} ist doppelt vergeben: {duplicate}, {identifier}")
        numeric_ids[identifier] = raw_id
        used_ids[raw_id] = identifier
    return dict(sorted(numeric_ids.items()))


def load_local_effect_numeric_ids(path: Path = BUNDLED_ITEM_DB_JSON) -> dict[str, int]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"Lokale numerische Effekt-IDs fehlen: {path}") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise RuntimeError(f"Lokale numerische Effekt-IDs sind nicht lesbar: {path}: {exc}") from exc

    raw_effects = data.get("effects") if isinstance(data, dict) else None
    if not isinstance(raw_effects, dict) or not raw_effects:
        raise RuntimeError("Lokale numerische Effekt-IDs enthalten keine Einträge")

    numeric_ids: dict[str, int] = {}
    used_ids: dict[int, str] = {}
    for raw_id, values in raw_effects.items():
        if not isinstance(values, (list, tuple)) or len(values) < 2:
            raise RuntimeError(f"Ungültiger lokaler Effekt-Eintrag für ID {raw_id!r}")
        try:
            numeric_id = int(raw_id)
        except (TypeError, ValueError):
            raise RuntimeError(f"Ungültige lokale numerische Effekt-ID: {raw_id!r}") from None
        if not 0 <= numeric_id <= 255:
            raise RuntimeError(f"Lokale numerische Effekt-ID außerhalb des gültigen Bereichs: {numeric_id}")
        identifier = _canonical_effect_identifier(values[1] or values[0])
        if not re.fullmatch(r"[a-z0-9_]+", identifier):
            raise RuntimeError(f"Lokaler Effekt hat keinen kanonischen Identifier: {values[1] or values[0]!r}")
        duplicate_id = used_ids.get(numeric_id)
        if duplicate_id is not None:
            raise RuntimeError(f"Numerische Effekt-ID {numeric_id} ist doppelt vergeben: {duplicate_id}, {identifier}")
        duplicate_identifier = numeric_ids.get(identifier)
        if duplicate_identifier is not None:
            raise RuntimeError(f"Effekt-Identifier {identifier} ist doppelt vergeben: {duplicate_identifier}, {numeric_id}")
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
        log(f"  {Colors.YELLOW}Optionale Wiki-Prüfung nicht verfügbar: {exc}{Colors.END}")
        return None

    differences = diff_enchantment_max_levels(local_levels, wiki_levels)
    different = differences["different"]
    missing = differences["missing_in_wiki"]
    wiki_only = differences["wiki_only"]
    if not different and not missing and not wiki_only:
        log(f"  {Colors.GREEN}Wiki-Prüfung: lokale Maximalstufen stimmen überein{Colors.END}")
        return snapshot

    log(f"  {Colors.YELLOW}Wiki-Prüfung meldet Abweichungen; lokale Werte bleiben unverändert.{Colors.END}")
    for identifier, values in different.items():
        log(f"    ~ {identifier}: lokal {values['local']}, Wiki {values['wiki']}", Colors.YELLOW)
    if missing:
        log(f"    - In der Wiki nicht gefunden: {', '.join(missing)}", Colors.YELLOW)
    if wiki_only:
        log(f"    + Nur in der Wiki gefunden: {', '.join(wiki_only)}", Colors.YELLOW)
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
        message = "MaxLevel-Tabelle nicht in der Minecraft Wiki gefunden"
        log(f"  {Colors.RED}{message}{Colors.END}")
        raise RuntimeError(message)
    if not result:
        message = "Keine MaxLevel-Einträge aus der Minecraft Wiki geparst"
        log(f"  {Colors.RED}{message}{Colors.END}")
        raise RuntimeError(message)
    if skipped_rows:
        shown = ", ".join(skipped_rows[:5])
        log(f"  {Colors.YELLOW}Wiki-MaxLevel-Parser ignoriert {len(skipped_rows)} Zeilen ohne lesbares MaxLevel: {shown}{Colors.END}")
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
                raise RuntimeError("Resource-Pack-Download enthält unerwartet viele ZIP-Einträge.")
            total_uncompressed = 0
            for member in members:
                if member.file_size < 0 or member.file_size > MAX_RESOURCE_PACK_MEMBER_BYTES:
                    raise RuntimeError(f"Resource-Pack-Download enthält einen unerwartet großen ZIP-Eintrag: {member.filename}")
                total_uncompressed += member.file_size
                if total_uncompressed > MAX_RESOURCE_PACK_UNCOMPRESSED_BYTES:
                    raise RuntimeError("Resource-Pack-Download ist entpackt unerwartet groß.")
            damaged_member = archive.testzip()
    except (OSError, zipfile.BadZipFile) as exc:
        raise RuntimeError("Resource-Pack-Download ist keine gültige ZIP-Datei.") from exc
    if damaged_member:
        raise RuntimeError(f"Resource-Pack-Download enthält einen beschädigten ZIP-Eintrag: {damaged_member}")


def download_with_progress(url: str, dest: Path, *, expected_size: int | None = None) -> None:
    log("  Downloading...", Colors.YELLOW)
    _validate_https_url(url, ALLOWED_RESOURCE_PACK_HOSTS, label="Resource-Pack")

    def report(downloaded: int, totalsize: int) -> None:
        if totalsize > 0:
            pct = min(100, downloaded * 100 // totalsize)
            sys.stdout.write(f"\r  Downloading... {pct}%")
            sys.stdout.flush()

    opener = _build_validating_opener(ALLOWED_RESOURCE_PACK_HOSTS, label="Resource-Pack")
    opener.addheaders = [("User-Agent", "MCBE-Inventory-Editor-Updater/1.0")]
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{dest.name}.", suffix=".part", dir=dest.parent)
    temp_path = Path(temp_name)

    try:
        with opener.open(url, timeout=60) as resp, os.fdopen(fd, "wb") as out:
            fd = -1
            _validate_final_response_url(resp, ALLOWED_RESOURCE_PACK_HOSTS, label="Resource-Pack")
            total = _safe_int(resp.headers.get("Content-Length"), 0)
            if total > MAX_RESOURCE_PACK_BYTES:
                raise RuntimeError(f"Resource-Pack-Download ist unerwartet gross: {total} Bytes")
            downloaded = 0
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                downloaded += len(chunk)
                if downloaded > MAX_RESOURCE_PACK_BYTES:
                    raise RuntimeError("Resource-Pack-Download überschreitet das Sicherheitslimit.")
                out.write(chunk)
                report(downloaded, total)
            out.flush()
            os.fsync(out.fileno())
        if expected_size and downloaded != expected_size:
            raise RuntimeError(f"Resource-Pack-Download ist unvollständig: erwartet {expected_size} Bytes, erhalten {downloaded} Bytes")
        _validate_downloaded_zip(temp_path)
        os.replace(temp_path, dest)
        print(f"\r  {Colors.GREEN}Downloaded{Colors.END} ({dest.name}){' ' * 20}")
    except Exception as exc:
        if fd >= 0:
            with contextlib.suppress(OSError):
                os.close(fd)
        with contextlib.suppress(OSError):
            temp_path.unlink()
        raise RuntimeError(f"Download failed: {exc}") from exc


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
        if dest.exists():
            os.replace(dest, rollback)
            old_moved = True
        os.replace(candidate, dest)
        published = True
        write_release_metadata(info)
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
            raise RuntimeError(f"Resource-Pack-Cache konnte nach einem Metadatenfehler nicht wiederhergestellt werden: {restore_failure}") from exc
        raise
    finally:
        with contextlib.suppress(OSError):
            candidate.unlink()


def resolve_latest_rp(dest: Path) -> dict:
    """Resolve the latest release and reuse only a matching validated cache."""

    latest_info = get_latest_release_info()
    cached_info = _matching_cached_release(dest, latest_info)
    if cached_info:
        log(
            f"  {Colors.GREEN}Cache ist aktuell: {cached_info['resource_pack_release']} "
            f"({cached_info['resource_pack_asset']}){Colors.END}"
        )
        return cached_info
    if dest.exists():
        log(f"  {Colors.YELLOW}Cache ist veraltet oder ungültig; aktuelles Release wird geladen{Colors.END}")
    return download_latest_rp(dest, release_info=latest_info)


def open_zip(zip_path: Path) -> zipfile.ZipFile:
    """Open the min zip and return the ZipFile object."""
    try:
        return zipfile.ZipFile(zip_path, "r")
    except zipfile.BadZipFile:
        raise RuntimeError(f"Corrupted zip file: {zip_path}") from None


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
    return RuntimeError(f"Mojang-Itemkomponente {component} ist ungültig: {member}: {detail}")


def _normalize_enchantable_component(value, *, member: str) -> dict:
    component = "minecraft:enchantable"
    if not isinstance(value, dict):
        raise _component_error(member, component, "erwartet ein Objekt")
    slot = str(value.get("slot", "")).strip()
    if slot not in KNOWN_ENCHANTABLE_SLOTS:
        raise _component_error(member, component, f"unbekannter Slot {slot!r}")
    enchantability = value.get("value")
    if type(enchantability) is not int or not 0 <= enchantability <= 32767:
        raise _component_error(member, component, "value muss eine Ganzzahl zwischen 0 und 32767 sein")
    return {"slot": slot, "value": enchantability}


def _normalize_wearable_component(value, *, member: str) -> dict:
    component = "minecraft:wearable"
    if not isinstance(value, dict):
        raise _component_error(member, component, "erwartet ein Objekt")
    slot = str(value.get("slot", "")).strip()
    if slot not in KNOWN_WEARABLE_SLOTS:
        raise _component_error(member, component, f"unbekannter Slot {slot!r}")
    result: dict = {"slot": slot}
    for key in ("hides_player_location", "dispensable"):
        if key in value:
            if type(value[key]) is not bool:
                raise _component_error(member, component, f"{key} muss ein Boolean sein")
            result[key] = value[key]
    if "protection" in value:
        protection = value["protection"]
        if type(protection) is not int or not 0 <= protection <= 32767:
            raise _component_error(member, component, "protection muss eine Ganzzahl zwischen 0 und 32767 sein")
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
    durability: dict[str, int] = {}
    tracked: dict[str, dict[str, dict]] = {component: {} for component in TRACKED_ITEM_COMPONENTS}
    for info in sorted(zf.infolist(), key=lambda entry: entry.filename.replace("\\", "/").lower()):
        member = info.filename.replace("\\", "/")
        if info.is_dir() or not member.startswith("behavior_pack/items/") or not member.endswith(".json"):
            continue
        try:
            payload = json.loads(_strip_json_comments(zf.read(info).decode("utf-8-sig")))
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
            raise RuntimeError(f"Mojang-Itemdefinition ist ungültig: {member}: {exc}") from exc
        item = payload.get("minecraft:item") if isinstance(payload, dict) else None
        description = item.get("description") if isinstance(item, dict) else None
        components = item.get("components") if isinstance(item, dict) else None
        identifier = str(description.get("identifier", "") if isinstance(description, dict) else "").strip().lower()
        if identifier and not identifier.startswith("minecraft:"):
            identifier = f"minecraft:{identifier}"
        if not re.fullmatch(r"minecraft:[a-z0-9_.-]+", identifier) or not isinstance(components, dict):
            continue

        raw_stack = components.get("minecraft:max_stack_size")
        if type(raw_stack) is int and 1 <= raw_stack <= 127:
            stack_limits[identifier] = raw_stack

        durability_component = components.get("minecraft:durability")
        raw_durability = durability_component.get("max_durability") if isinstance(durability_component, dict) else None
        if type(raw_durability) is int and 0 <= raw_durability <= 32767:
            durability[identifier] = raw_durability

        normalizers = {
            "enchantable": _normalize_enchantable_component,
            "wearable": _normalize_wearable_component,
        }
        for component_name, normalizer in normalizers.items():
            namespaced_name = f"minecraft:{component_name}"
            if namespaced_name in components:
                tracked[component_name][identifier] = normalizer(components[namespaced_name], member=member)

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
    log("  Lade offizielle Microsoft-Learn-Itemliste...", Colors.YELLOW)
    try:
        with opener.open(url, timeout=30) as resp:
            _validate_final_response_url(resp, ALLOWED_MICROSOFT_LEARN_HOSTS, label="Microsoft-Learn-Itemliste")
            raw = resp.read(MAX_MICROSOFT_LEARN_BYTES + 1)
            if len(raw) > MAX_MICROSOFT_LEARN_BYTES:
                raise RuntimeError("Microsoft-Learn-Itemliste ist unerwartet groß.")
            content = raw.decode("utf-8", errors="replace")
            items = parse_microsoft_item_listing(content)
            if len(items) < 1000:
                raise RuntimeError(f"Microsoft-Learn-Itemliste enthält unerwartet wenige Einträge: {len(items)}")
            snapshot = {
                "microsoft_item_listing_url": url,
                "microsoft_item_listing_fetched_at": utc_now(),
                "microsoft_item_listing_content_hash": sha256_text(content),
                "microsoft_item_listing_count": len(items),
            }
            return items, snapshot
    except (OSError, TimeoutError) as exc:
        raise RuntimeError(f"Fehler beim Laden der Microsoft-Learn-Itemliste: {exc}") from exc


def write_microsoft_item_listing_cache(items: dict[str, str], snapshot: dict) -> None:
    try:
        payload = item_db_verification.build_item_listing_cache_payload(items, snapshot)
    except item_db_verification.UpdateReviewError as exc:
        raise RuntimeError(f"Microsoft-Itemlisten-Snapshot ist ungültig: {exc}") from exc
    atomic_write_text(ITEM_LISTING_CACHE_PATH, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def read_microsoft_item_listing_cache() -> tuple[dict[str, str], dict]:
    try:
        items, snapshot = item_db_verification.read_item_listing_cache(ITEM_LISTING_CACHE_PATH)
    except item_db_verification.UpdateReviewError as exc:
        raise RuntimeError(f"Kein gültiger Microsoft-Itemlisten-Snapshot aus dem Dry-Run vorhanden: {exc}") from exc
    source_url = str(snapshot["microsoft_item_listing_url"])
    _validate_https_url(source_url, ALLOWED_MICROSOFT_LEARN_HOSTS, label="Microsoft-Learn-Itemliste")
    if source_url != MICROSOFT_ITEM_LISTINGS_URL:
        raise RuntimeError("Der Microsoft-Itemlisten-Snapshot gehört nicht zur aktuellen offiziellen Quelle.")
    return items, snapshot


def resolve_microsoft_item_listing_snapshot(*, reuse_cached: bool) -> tuple[dict[str, str], dict]:
    """Fetch the current listing or replay the exact normalized dry-run input."""

    if reuse_cached:
        items, snapshot = read_microsoft_item_listing_cache()
        log(
            f"  {Colors.YELLOW}Verwende im Dry-Run geprüfte Microsoft-Learn-Itemliste "
            f"({len(items)} Einträge){Colors.END}"
        )
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
    return _normalize_item_key(base)


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


# Technische Blockformen, die in den Mojang-Registries ausnahmslos block-only sind
# (0 Gegenbeispiele in 1.26.30.5). Das Muster greift zusätzlich für Familien, die
# (noch) in keiner Registry stehen: Legacy-IDs aus der Vor-Flattening-Ära
# (double_stone_slab*, double_wooden_slab) und experimentelle Holzarten.
TECHNICAL_BLOCK_ONLY_ID_PATTERNS = (
    re.compile(r"_double_slab$"),
    re.compile(r"^minecraft:double_(?:stone|wooden)_(?:block_)?slab\d?$"),
    re.compile(r"_standing_sign$"),
    re.compile(r"_wall_sign$"),
)


def _matches_technical_block_only_pattern(item_id: str) -> bool:
    return any(pattern.search(item_id) for pattern in TECHNICAL_BLOCK_ONLY_ID_PATTERNS)


def compute_block_only_item_ids(zf: zipfile.ZipFile, items: dict[str, tuple[str, str]]) -> list[str]:
    """Katalog-IDs, die Mojang nur als Block, nicht als Item registriert.

    Solche IDs (z. B. *_double_slab, *_standing_sign, candle_cake) ergeben im
    Inventar keine brauchbaren Items; die UI blendet sie aus den Vorschlägen aus.
    """
    item_ids = _vanilla_registry_ids(zf, "mojang-items.json")
    block_ids = _vanilla_registry_ids(zf, "mojang-blocks.json")
    if not item_ids or not block_ids:
        return []
    return sorted(key for key in items if key not in item_ids and (key in block_ids or _matches_technical_block_only_pattern(key)))


def compute_addable_item_ids(zf: zipfile.ZipFile, items: dict[str, tuple[str, str]]) -> list[str]:
    """IDs, die Mojang tatsächlich als neue Inventaritems registriert.

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
    return sorted(item_ids)


def compute_block_item_ids(zf: zipfile.ZipFile, items: dict[str, tuple[str, str]]) -> list[str]:
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
    if not item_ids or not block_ids:
        return []
    return sorted(key for key in items if key in item_ids and key in block_ids and key not in non_placeable_registry_collisions)


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
    """Parse safe item/tile name entries while preserving dotted localization keys.

    Dotted keys such as ``boat.acacia`` are localization identifiers, not valid
    Bedrock item IDs. Keeping them in a separate catalog lets the updater bridge
    them later without ever adding pseudo item IDs to the writable database.
    """
    if not lang_path:
        return {}
    named_pattern = re.compile(
        r"^(?:item|tile)\.(?:minecraft[:. ]\s*)?([a-z0-9_]+(?:[./-][a-z0-9_]+)*)\.name=(.+)$",
        re.IGNORECASE,
    )
    legacy_pattern = re.compile(
        r"^(?:item|tile)\.(?:minecraft[:. ]\s*)?([a-z0-9_]+(?:[/-][a-z0-9_]+)*)=(.+)$",
        re.IGNORECASE,
    )
    try:
        content = lang_path.read_text(encoding="utf-8-sig")
    except OSError:
        return {}

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

    Only English keys are authoritative for matching. A missing German entry is
    represented by an empty string so callers can conservatively skip it.
    """
    en_entries = _parse_lang_item_entries(en_path)
    de_entries = _parse_lang_item_entries(de_path)
    return {key: (de_entries.get(key, ""), en_name) for key, en_name in en_entries.items()}


def parse_lang_items(en_path: Path, de_path: Path | None) -> tuple[dict[str, str], dict[str, str]]:
    """Parse direct item-ID localization keys. Returns (en_items, de_items)."""
    localizations = parse_lang_item_localizations(en_path, de_path)
    en_items: dict[str, str] = {}
    de_items: dict[str, str] = {}
    direct_identifier = re.compile(r"[a-z0-9_]+(?:[/-][a-z0-9_]+)*", re.IGNORECASE)
    for raw_id, (de_name, en_name) in localizations.items():
        if not direct_identifier.fullmatch(raw_id) or _is_non_item_lang_identifier(raw_id):
            continue
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
        label = _normalized_display_label(en_name)
        if not label or not de_name or "%" in de_name or "%" in en_name:
            continue
        grouped.setdefault(label, []).append((key, de_name.strip(), en_name.strip()))

    index: dict[str, tuple[str, str]] = {}
    for label, candidates in grouped.items():
        german_names = {_normalized_display_label(candidate[1]) for candidate in candidates}
        if len(candidates) == 1 or len(german_names) == 1:
            _key, de_name, en_name = sorted(candidates, key=lambda candidate: candidate[0])[0]
            index[label] = (de_name, en_name)
    return index


def _derived_item_localization_keys(item_id: str) -> list[str]:
    """Return deterministic localization keys for known Bedrock key families.

    These rules describe Mojang's key schema, not individual item translations.
    A derived key is only used when it exists in the parsed language catalog.
    """
    # ``minecraft:bed`` ist in Bedrock weiterhin ein einzelnes Inventaritem,
    # dessen Datenwert die Farbe bestimmt. Der Standardwert 0 ist weiß; ohne
    # diese explizite kanonische Variante liefert Microsoft Learn derzeit
    # irreführend den Namen der schwarzen Variante.
    if item_id == "bed":
        return ["bed.white"]
    variant_aliases = {"dark_oak": "big_oak"}
    if item_id.endswith("_chest_boat"):
        variant = item_id.removesuffix("_chest_boat")
        return [f"chest_boat.{variant_aliases.get(variant, variant)}"]
    if item_id.endswith("_chest_raft"):
        variant = item_id.removesuffix("_chest_raft")
        return [f"chest_boat.{variant_aliases.get(variant, variant)}"]
    if item_id.endswith("_boat"):
        variant = item_id.removesuffix("_boat")
        return [f"boat.{variant_aliases.get(variant, variant)}"]
    if item_id.endswith("_raft"):
        variant = item_id.removesuffix("_raft")
        return [f"boat.{variant_aliases.get(variant, variant)}"]
    if item_id.endswith("_spawn_egg"):
        entity_id = item_id.removesuffix("_spawn_egg")
        return [f"spawn_egg.entity.{entity_id}"]
    return []


def _localized_names_for_item_key(
    item_id: str,
    localizations: dict[str, tuple[str, str]],
) -> tuple[str, str] | None:
    for key in _derived_item_localization_keys(item_id):
        names = localizations.get(key)
        if names and names[0] and "%" not in names[0] and "%" not in names[1]:
            return names
    return None


def _candidate_item_keys(item_id: str, serialization_aliases: dict[str, str]) -> list[str]:
    keys = [item_id]
    alias = serialization_aliases.get(item_id, "")
    if alias and alias not in keys:
        keys.append(alias)
    return keys


def _first_name(mapping: dict[str, str], keys: list[str]) -> str:
    for key in keys:
        value = mapping.get(key)
        if value:
            return value
    return ""


def _old_name_for_keys(old: dict[str, tuple[str, str]], keys: list[str]) -> tuple[str, str] | None:
    for key in keys:
        value = old.get(f"minecraft:{key}")
        if value and len(value) >= 2 and (value[0] or value[1]):
            return value
    return None


def _normalize_display_name(value: str, fallback: str) -> str:
    text = value or fallback
    text = text[0].upper() + text[1:] if text else fallback
    return text.replace("_", " ").replace("/", " ")


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
) -> tuple[str, str]:
    keys = _candidate_item_keys(item_id, serialization_aliases)
    localized_names = _localized_names_for_item_key(item_id, item_localizations)
    if item_id == "bed" and localized_names:
        de_name, en_name = localized_names
        return _normalize_display_name(de_name, en_name), _normalize_display_name(en_name, item_id)

    direct_en_name = _first_name(en_items, [item_id])
    old_alias_name = _old_name_for_keys(old, keys[1:])
    alias_en_name = _first_name(en_items, keys[1:])
    if not alias_en_name and old_alias_name:
        alias_en_name = old_alias_name[1]
    canonical_en_name = direct_en_name or microsoft_items.get(item_id, "")
    alias_matches_canonical = not canonical_en_name or (
        bool(alias_en_name) and _normalized_display_label(alias_en_name) == _normalized_display_label(canonical_en_name)
    )

    en_name = direct_en_name
    if not en_name and alias_matches_canonical:
        en_name = alias_en_name
    if not en_name:
        en_name = microsoft_items.get(item_id) or _first_name(microsoft_items, keys[1:]) or _friendly_name_from_identifier(item_id)

    de_name = _first_name(de_items, [item_id])
    if not de_name and alias_matches_canonical:
        de_name = _first_name(de_items, keys[1:])
        if not de_name and old_alias_name:
            de_name = old_alias_name[0]
    if not de_name:
        localized_names = _localized_names_for_item_key(item_id, item_localizations)
        if not localized_names:
            localized_names = localization_label_index.get(_normalized_display_label(en_name))
        if localized_names:
            de_name, localized_en_name = localized_names
            en_name = en_name or localized_en_name
    if not de_name:
        de_name = en_name
    return _normalize_display_name(de_name, en_name), _normalize_display_name(en_name, item_id)


def merge_items(
    old: dict[str, tuple[str, str]],
    en_items: dict[str, str],
    de_items: dict[str, str],
    microsoft_items: dict[str, str] | None = None,
    serialization_aliases: dict[str, str] | None = None,
    item_localizations: dict[str, tuple[str, str]] | None = None,
) -> dict[str, tuple[str, str]]:
    """Merge existing items + official item IDs.

    Existing localized entries stay untouched. Existing English fallbacks may be
    corrected when Mojang's mojang-items.json points the canonical ID at a
    legacy serialization/localization key.
    """
    merged = dict(old)
    microsoft_items = microsoft_items or {}
    serialization_aliases = serialization_aliases or {}
    item_localizations = item_localizations or {}
    localization_label_index = build_item_localization_label_index(item_localizations)
    all_ids = sorted(set(en_items) | set(de_items) | set(microsoft_items) | set(serialization_aliases))
    for item_id in all_ids:
        full_id = f"minecraft:{item_id}"
        de_name, en_name = _resolved_item_names(
            item_id,
            old,
            en_items,
            de_items,
            microsoft_items,
            serialization_aliases,
            item_localizations,
            localization_label_index,
        )
        if "%" in en_name or "%" in de_name:
            continue
        existing = merged.get(full_id)
        if existing:
            old_de, old_en = existing
            has_authoritative_derived_name = item_id == "bed" and _localized_names_for_item_key(item_id, item_localizations) is not None
            if has_authoritative_derived_name and (old_de, old_en) != (de_name, en_name):
                merged[full_id] = (de_name, en_name)
            elif _looks_like_fallback_name(old_de, old_en) and not _looks_like_fallback_name(de_name, en_name):
                merged[full_id] = (de_name, old_en or en_name)
            continue
        merged[full_id] = (de_name, en_name)
    return merged


# ─── EFFECTS ────────────────────────────────────────────────────────────────


def parse_json_effects(zf: zipfile.ZipFile) -> list[str]:
    obj = json.loads(read_utf8(zf, "metadata/vanilladata_modules/mojang-effects.json"))
    return sorted(_canonical_effect_identifier(item["name"]) for item in obj.get("data_items", []) if item.get("name"))


def parse_lang_effects(content: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in content.splitlines():
        line = line.strip()
        if not line.startswith("effect.") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        lang_name = key.replace("effect.", "").strip()
        json_name = EFFECT_LANG_TO_JSON.get(lang_name, lang_name)
        json_name = _canonical_effect_identifier(json_name)
        if json_name not in result:
            result[json_name] = val.strip()
    return result


def merge_effects(
    old: dict[int, tuple[str, str, str, str]],
    json_ids: list[str],
    en_names: dict[str, str],
    de_names: dict[str, str],
    local_numeric_ids: dict[str, int],
) -> dict[int, tuple[str, str, str, str]]:
    """Merge Mojang identifiers/names with locally reviewed Bedrock IDs."""
    merged = dict(old)
    name_to_id: dict[str, int] = {}
    for key, values in old.items():
        de_name, en_name, _desc_de, _desc_en = values
        for candidate in (en_name, de_name):
            if candidate:
                name_to_id.setdefault(_canonical_effect_identifier(candidate), key)

    mojang_identifiers = {_canonical_effect_identifier(json_id) for json_id in json_ids}
    missing_numeric_ids = sorted(mojang_identifiers - set(local_numeric_ids))
    if missing_numeric_ids:
        raise RuntimeError("Lokale numerische IDs fehlen für neue Mojang-Effekte: " + ", ".join(missing_numeric_ids))

    for identifier in mojang_identifiers:
        old_id = name_to_id.get(identifier)
        reviewed_id = local_numeric_ids[identifier]
        if old_id is not None and old_id != reviewed_id:
            merged.pop(old_id, None)

    for json_id in json_ids:
        canonical_json_id = _canonical_effect_identifier(json_id)
        reviewed_id = local_numeric_ids[canonical_json_id]
        existing_id = name_to_id.get(canonical_json_id)
        if existing_id is not None:
            reviewed_entry = old[existing_id]
        else:
            en_name = en_names.get(canonical_json_id, en_names.get(json_id, canonical_json_id.replace("_", " ").title()))
            de_name = de_names.get(canonical_json_id, de_names.get(json_id, en_name))
            reviewed_entry = (_cap(de_name), _cap(en_name), "", "")

        collision = merged.get(reviewed_id)
        if collision is not None:
            collision_name = _canonical_effect_identifier(collision[1] or collision[0])
            if collision_name != canonical_json_id:
                raise RuntimeError(f"Geprüfte Effekt-ID {reviewed_id} für {canonical_json_id} kollidiert mit vorhandenem Eintrag {collision_name}")
        merged[reviewed_id] = reviewed_entry

    return merged


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
    """Parse enchant.* entries from .lang content (skip .desc, .prefix). Returns JSON_name -> display_name."""
    result: dict[str, str] = {}
    for line in content.splitlines():
        line = line.strip()
        if not line.startswith("enchant.") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        lang_name = key.replace("enchant.", "").strip()
        # Skip description/prefix entries
        if ".desc" in lang_name or ".prefix" in lang_name:
            continue
        json_name = ENCH_LANG_TO_JSON.get(lang_name, lang_name)
        json_name = _canonical_enchantment_identifier(json_name)
        if json_name not in result:
            result[json_name] = val.strip()
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
    merged = dict(old)
    name_to_id: dict[str, int] = {}
    for key, values in old.items():
        de_name, en_name, _max_level, _desc = values
        for candidate in (en_name, de_name):
            if candidate:
                name_to_id.setdefault(_canonical_enchantment_identifier(candidate), key)

    mojang_identifiers = {_canonical_enchantment_identifier(name) for name, _ in json_list}
    missing_levels = sorted(mojang_identifiers - set(local_max_levels))
    if missing_levels:
        raise RuntimeError("Lokale Maximalstufen fehlen für neue Mojang-Verzauberungen: " + ", ".join(missing_levels))
    missing_numeric_ids = sorted(mojang_identifiers - set(local_numeric_ids))
    if missing_numeric_ids:
        raise RuntimeError("Lokale numerische IDs fehlen für neue Mojang-Verzauberungen: " + ", ".join(missing_numeric_ids))

    numeric_id_owners: dict[int, str] = {}
    for identifier in mojang_identifiers:
        numeric_id = local_numeric_ids[identifier]
        duplicate = numeric_id_owners.get(numeric_id)
        if duplicate is not None:
            raise RuntimeError(f"Numerische Verzauberungs-ID {numeric_id} ist doppelt vergeben: {duplicate}, {identifier}")
        numeric_id_owners[numeric_id] = identifier

    # Frühere Updater vergaben für neue Namen lediglich die nächste freie ID.
    # Entferne solche namensgleichen Altpositionen, bevor die geprüften
    # Bedrock-IDs geschrieben werden.
    for identifier in mojang_identifiers:
        old_id = name_to_id.get(identifier)
        reviewed_id = local_numeric_ids[identifier]
        if old_id is not None and old_id != reviewed_id:
            merged.pop(old_id, None)

    for json_name, _ in json_list:
        canonical_json_name = _canonical_enchantment_identifier(json_name)
        max_lvl = local_max_levels[canonical_json_name]
        reviewed_id = local_numeric_ids[canonical_json_name]
        existing_id = name_to_id.get(canonical_json_name)
        if existing_id is not None:
            de_name, en_name, _old_max_lvl, description = old[existing_id]
            reviewed_entry = (de_name, en_name, max_lvl, description)
        else:
            en_name = en_names.get(canonical_json_name, en_names.get(json_name, canonical_json_name.replace("_", " ").title()))
            de_name = de_names.get(canonical_json_name, de_names.get(json_name, en_name))
            reviewed_entry = (_cap(de_name), _cap(en_name), max_lvl, "")

        collision = merged.get(reviewed_id)
        if collision is not None:
            collision_name = _canonical_enchantment_identifier(collision[1] or collision[0])
            if collision_name != canonical_json_name:
                raise RuntimeError(f"Geprüfte Verzauberungs-ID {reviewed_id} für {canonical_json_name} kollidiert mit vorhandenem Eintrag {collision_name}")
        merged[reviewed_id] = reviewed_entry

    return merged


# ─── HELPERS ────────────────────────────────────────────────────────────────


def _cap(s: str) -> str:
    """Capitalize first letter."""
    return s[0].upper() + s[1:] if s else s


# ─── JSON DATABASE READING/WRITING ──────────────────────────────────────────


def _load_item_db_json() -> dict:
    try:
        data = json.loads(ITEM_DB_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"Item-DB JSON nicht gefunden: {ITEM_DB_PATH}") from exc
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise RuntimeError(f"Item-DB JSON ist ungültig: {ITEM_DB_PATH}") from exc
    if not isinstance(data, dict):
        raise RuntimeError("Item-DB JSON muss ein Objekt sein.")
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
) -> None:
    data = _load_item_db_json()
    data["schema_version"] = 3
    data.setdefault("defaults", {"max_stack": 64, "max_damage": 1561, "max_data_value": 32767})
    data.setdefault("stack_limits", {})
    data.setdefault("durability", {})
    data.setdefault("item_components", {component: {} for component in TRACKED_ITEM_COMPONENTS})
    data["items"] = {key: [de, en] for key, (de, en) in sorted(items.items())}
    data["effects"] = {str(key): [de, en, desc_de, desc_en] for key, (de, en, desc_de, desc_en) in sorted(effects.items())}
    data["enchantments"] = {str(key): [de, en, int(level), desc] for key, (de, en, level, desc) in sorted(enchants.items())}
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
    return True


def build_source_identity(release_info: dict, wiki_snapshot: dict, item_listing_snapshot: dict | None = None) -> dict:
    item_listing_snapshot = item_listing_snapshot or {}
    return {
        "resource_pack_release": release_info.get("resource_pack_release", ""),
        "resource_pack_asset": release_info.get("resource_pack_asset", ""),
        "resource_pack_asset_size": release_info.get("resource_pack_asset_size", 0),
        "resource_pack_url": release_info.get("resource_pack_url", ""),
        "microsoft_item_listing_url": item_listing_snapshot.get("microsoft_item_listing_url", ""),
        "microsoft_item_listing_content_hash": item_listing_snapshot.get("microsoft_item_listing_content_hash", ""),
        "microsoft_item_listing_count": item_listing_snapshot.get("microsoft_item_listing_count", 0),
        "wiki_url": wiki_snapshot.get("wiki_url", ""),
        "wiki_revision_id": wiki_snapshot.get("wiki_revision_id"),
        "wiki_content_hash": wiki_snapshot.get("wiki_content_hash", ""),
    }


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


def _file_snapshot(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def _restore_file_snapshot(path: Path, content: bytes | None) -> None:
    if content is None:
        with contextlib.suppress(FileNotFoundError):
            path.unlink()
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".rollback", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as target:
            target.write(content)
            target.flush()
            os.fsync(target.fileno())
        os.replace(tmp_name, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.remove(tmp_name)
        raise


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
) -> None:
    """Commit item data and matching source metadata as one recoverable unit."""

    if verify_item_db and source_metadata is None:
        raise ValueError("Ein Item-DB-Prüfbeleg benötigt Quellenmetadaten.")
    touched_paths = [ITEM_DB_PATH]
    if source_metadata is not None:
        touched_paths.append(SOURCE_VERSION_JSON)
        if append_source_history:
            touched_paths.append(SOURCE_VERSION_HISTORY)
    snapshots = {path: _file_snapshot(path) for path in touched_paths}
    try:
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
    except Exception as exc:
        rollback_failures = []
        for path, content in snapshots.items():
            try:
                _restore_file_snapshot(path, content)
            except Exception as rollback_exc:
                rollback_failures.append(f"{path}: {rollback_exc}")
        if rollback_failures:
            raise RuntimeError(f"Update fehlgeschlagen und konnte nicht vollständig zurückgerollt werden: {'; '.join(rollback_failures)}") from exc
        raise


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
        log(f"  {Colors.GREEN}{label}: aktuell ({len(old)} Einträge){Colors.END}")
        return False

    log(f"\n  {Colors.BOLD}{'-' * 50}{Colors.END}")
    log(f"  {Colors.BOLD}{label}{Colors.END}")
    log(f"  {Colors.BOLD}{'-' * 50}{Colors.END}")

    if added:
        log(f"\n  {Colors.GREEN}Neu (+{len(added)}):{Colors.END}")
        for k in sorted(added):
            log(f"    + {k}: {new[k]}", color=Colors.GREEN)

    if removed:
        log(f"\n  {Colors.RED}Entfernt (-{len(removed)}):{Colors.END}")
        for k in sorted(removed):
            log(f"    - {k}: {old[k]}", color=Colors.RED)

    if changed:
        log(f"\n  {Colors.YELLOW}Geändert (~{len(changed)}):{Colors.END}")
        for k in sorted(changed):
            log(f"    ~ {k}: {old[k]} -> {new[k]}", color=Colors.YELLOW)

    log(f"\n  Statistik: {len(old)} -> {len(new)} (+{len(added)} / -{len(removed)} / ~{len(changed)})")
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
    log(f"\n  {Colors.BOLD}{Colors.RED}Übersprungene Abschnitte ({len(blocked_sections)}):{Colors.END}")
    for section_name, reason in blocked_sections:
        log(f"    {Colors.RED}{section_name}: {reason}{Colors.END}")
    log(f"  {Colors.YELLOW}Alle übrigen Abschnitte wurden regulär verarbeitet. Fehlende Werte kuratieren und erneut ausführen.{Colors.END}")
    return 1


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Aktualisiert item_db.json aus Mojang/bedrock-samples und lokal geprüften Vanilla-Fakten.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--dry-run", action="store_true", help="Nur anzeigen, nicht schreiben")
    parser.add_argument("--force", action="store_true", help="Ohne Nachfrage schreiben")
    parser.add_argument(
        "--cache",
        "--reuse-cached-release",
        dest="cache",
        action="store_true",
        help="Im Dry-Run geprüfte Quellen ohne erneuten Online-Abruf verarbeiten",
    )
    parser.add_argument(
        "--expected-review-token",
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--only", choices=["items", "effects", "enchants"], help="Nur bestimmte Daten aktualisieren")
    parser.add_argument(
        "--check-wiki",
        action="store_true",
        help="Maximalstufen optional mit der Minecraft Wiki vergleichen; Abweichungen werden nicht übernommen",
    )
    args = parser.parse_args()
    if args.expected_review_token:
        if not args.cache:
            raise RuntimeError("Ein Dry-Run-Prüfbeleg kann nur mit dem internen Cache-Replay verwendet werden.")
        if not re.fullmatch(r"[0-9a-f]{64}", args.expected_review_token):
            raise RuntimeError("Der Dry-Run-Prüfbeleg ist ungültig.")

    log(f"{Colors.BOLD}{Colors.CYAN}{'=' * 60}{Colors.END}")
    log(f"{Colors.BOLD}  Minecraft Bedrock Item-DB Updater (Items + Effects + Enchantments){Colors.END}")
    log(f"{Colors.BOLD}{Colors.CYAN}{'=' * 60}{Colors.END}")

    ensure_data_paths()
    log(f"  Item-DB: {ITEM_DB_PATH}", Colors.DIM)
    log(f"  Cache:   {CACHE_DIR}", Colors.DIM)

    if args.expected_review_token:
        try:
            current_review = item_db_verification.update_review_snapshot(
                update_cache_dir=CACHE_DIR,
                item_db_path=ITEM_DB_PATH,
                source_version_path=SOURCE_VERSION_JSON,
                source_version_history_path=SOURCE_VERSION_HISTORY,
                scope=args.only,
            )
        except item_db_verification.UpdateReviewError as exc:
            raise RuntimeError(f"Der Dry-Run-Prüfbeleg kann nicht validiert werden: {exc}") from exc
        if not hmac.compare_digest(args.expected_review_token, current_review["token"]):
            raise RuntimeError("Die geprüften Dry-Run-Eingaben haben sich geändert. Bitte den Dry-Run erneut ausführen.")
        log(f"  {Colors.GREEN}Dry-Run-Prüfbeleg validiert ({current_review['scope']}){Colors.END}")

    step("1/4  Resource Pack herunterladen")
    rp_zip = CACHE_DIR / "bedrock_resource_pack.zip"
    release_info: dict = {}
    if args.cache:
        if not rp_zip.exists():
            raise RuntimeError("Kein gecachtes Resource-Pack für die erneute Verarbeitung vorhanden.")
        _validate_downloaded_zip(rp_zip)
        release_info = read_release_metadata()
        if not release_info:
            raise RuntimeError("Die Metadaten des gecachten Resource-Packs fehlen oder sind ungültig.")
        log(
            f"  {Colors.YELLOW}Verwende gecachtes Release ohne Online-Versionsprüfung: "
            f"{release_info['resource_pack_release']}{Colors.END}"
        )
    else:
        release_info = resolve_latest_rp(rp_zip)

    step("2/4  Daten extrahieren und parsen")
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
    changes: list[str] = []
    blocked_sections: list[tuple[str, str]] = []
    pending_source_version: dict | None = None

    en_content = de_content = ""
    en_lang = de_lang = None
    microsoft_items: dict[str, str] = {}
    item_listing_snapshot: dict | None = None
    wiki_snapshot: dict | None = None

    with open_zip(rp_zip) as zf:
        # Extract .lang files to temp
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for name in zf.namelist():
                if name.startswith("resource_pack/texts/") and name.endswith(".lang"):
                    fname = name.replace("\\", "/").split("/")[-1]
                    dest = tmp_path / fname
                    with zf.open(name) as src, open(dest, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    if fname == "en_US.lang":
                        en_lang = dest
                    elif fname == "de_DE.lang":
                        de_lang = dest

            en_content = en_lang.read_text(encoding="utf-8-sig") if en_lang else ""
            de_content = de_lang.read_text(encoding="utf-8-sig") if de_lang else ""

            # ── ITEMS ──
            if not args.only or args.only == "items":
                step("3/4 · Items verarbeiten")
                en_item_names, de_item_names = parse_lang_items(en_lang, de_lang) if en_lang else ({}, {})
                item_localizations = parse_lang_item_localizations(en_lang, de_lang) if en_lang else {}
                item_serialization_aliases = parse_json_item_serialization_aliases(zf)
                microsoft_items, item_listing_snapshot = resolve_microsoft_item_listing_snapshot(reuse_cached=args.cache)
                log(f"  {Colors.GREEN}Microsoft-Learn-Item-IDs: {len(microsoft_items)}{Colors.END}")
                log(f"  {Colors.GREEN}Vollständige Item-Lokalisierungen: {len(item_localizations)}{Colors.END}")
                if item_serialization_aliases:
                    log(f"  {Colors.GREEN}Mojang-Serialization-Aliasse: {len(item_serialization_aliases)}{Colors.END}")
                new_items = merge_items(
                    old_items,
                    en_item_names,
                    de_item_names,
                    microsoft_items,
                    item_serialization_aliases,
                    item_localizations,
                )
                if show_diff("ITEMS", old_items, new_items):
                    changes.append("ITEMS")
                    final_items = format_items(new_items)
                log(f"  {Colors.GREEN}Items: {len(old_items)} -> {len(new_items)}{Colors.END}")

                new_block_only = compute_block_only_item_ids(zf, new_items)
                old_block_only = read_block_only_item_ids()
                if new_block_only and new_block_only != old_block_only:
                    show_diff("BLOCK_ONLY_ITEMS", dict.fromkeys(old_block_only, True), dict.fromkeys(new_block_only, True))
                    changes.append("BLOCK_ONLY_ITEMS")
                    final_block_only = new_block_only
                log(f"  {Colors.GREEN}Block-only-IDs: {len(old_block_only)} -> {len(new_block_only)}{Colors.END}")

                new_addable_items = compute_addable_item_ids(zf, new_items)
                old_addable_items = read_addable_item_ids()
                if new_addable_items and new_addable_items != old_addable_items:
                    show_diff("ADDABLE_ITEMS", dict.fromkeys(old_addable_items, True), dict.fromkeys(new_addable_items, True))
                    changes.append("ADDABLE_ITEMS")
                    final_addable_items = new_addable_items
                log(f"  {Colors.GREEN}Neu hinzufügbar: {len(old_addable_items)} -> {len(new_addable_items)}{Colors.END}")

                component_stack_limits, component_durability, new_item_components = parse_json_item_components(zf)
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
                log(f"  {Colors.GREEN}Stack-Limits: {len(old_stack_limits)} -> {len(new_stack_limits)}{Colors.END}")

                if new_durability != old_durability:
                    show_diff("DURABILITY", old_durability, new_durability)
                    changes.append("DURABILITY")
                    final_durability = new_durability
                log(f"  {Colors.GREEN}Haltbarkeitswerte: {len(old_durability)} -> {len(new_durability)}{Colors.END}")

                if new_item_components != old_item_components:
                    for component_name in TRACKED_ITEM_COMPONENTS:
                        old_values = old_item_components.get(component_name, {})
                        new_values = new_item_components.get(component_name, {})
                        if old_values != new_values:
                            show_diff(f"ITEM_COMPONENTS.{component_name}", old_values, new_values)
                    changes.append("ITEM_COMPONENTS")
                    final_item_components = new_item_components
                component_counts = ", ".join(f"{component}={len(new_item_components.get(component, {}))}" for component in TRACKED_ITEM_COMPONENTS)
                log(f"  {Colors.GREEN}Offizielle Item-Komponenten: {component_counts}{Colors.END}")
                if new_behavior_item_source != old_behavior_item_source:
                    show_diff(
                        "BEHAVIOR_ITEM_SOURCE",
                        old_behavior_item_source,
                        new_behavior_item_source,
                    )
                    changes.append("BEHAVIOR_ITEM_SOURCE")
                    final_behavior_item_source = new_behavior_item_source

                new_block_items = compute_block_item_ids(zf, new_items)
                old_block_items = read_block_item_ids()
                if new_block_items and new_block_items != old_block_items:
                    show_diff("BLOCK_ITEMS", dict.fromkeys(old_block_items, True), dict.fromkeys(new_block_items, True))
                    changes.append("BLOCK_ITEMS")
                    final_block_items = new_block_items
                log(f"  {Colors.GREEN}Block-Item-IDs: {len(old_block_items)} -> {len(new_block_items)}{Colors.END}")

            # ── EFFECTS ──
            if not args.only or args.only == "effects":
                step("3/4 · Effekte verarbeiten")
                # Fehlen geprüfte numerische IDs, bleibt der Abschnitt bewusst
                # ungeschrieben — geraten wird hier nicht. Items, Blocklisten und
                # Verzauberungen sind davon unabhängig und laufen weiter.
                try:
                    json_effects = parse_json_effects(zf)
                    en_eff_names = parse_lang_effects(en_content)
                    de_eff_names = parse_lang_effects(de_content)
                    local_effect_numeric_ids = load_local_effect_numeric_ids()
                    log(f"  {Colors.GREEN}Lokale numerische Effekt-IDs: {len(local_effect_numeric_ids)}{Colors.END}")
                    new_effects = merge_effects(
                        old_effects,
                        json_effects,
                        en_eff_names,
                        de_eff_names,
                        local_effect_numeric_ids,
                    )
                except RuntimeError as exc:
                    blocked_sections.append(("EFFECTS", str(exc)))
                    log(f"  {Colors.RED}EFFECTS übersprungen: {exc}{Colors.END}")
                else:
                    if show_diff("EFFECTS", old_effects, new_effects):
                        changes.append("EFFECTS")
                        final_effects = format_effects(new_effects)
                    log(f"  {Colors.GREEN}Effects: {len(old_effects)} -> {len(new_effects)}{Colors.END}")

        # ── ENCHANTMENTS ── (zip still open, tmp dir closed — content strings remain)
        if not args.only or args.only == "enchants":
            step("3/4 · Verzauberungen verarbeiten")
            # Gleiche Begründung wie bei den Effekten: fehlende geprüfte IDs
            # blockieren nur diesen Abschnitt, nicht den gesamten Lauf.
            try:
                json_enchants = parse_json_enchantments(zf)
                en_ench_names = parse_lang_enchantments(en_content)
                de_ench_names = parse_lang_enchantments(de_content)
                local_max_levels = load_local_enchantment_max_levels()
                local_numeric_ids = load_local_enchantment_numeric_ids()
                log(f"  {Colors.GREEN}Lokale Verzauberungsdaten: {len(local_max_levels)} Maximalstufen, {len(local_numeric_ids)} numerische IDs{Colors.END}")
                wiki_snapshot = optional_wiki_enchantment_check(args.check_wiki, local_max_levels)
                new_enchants = merge_enchantments(
                    old_enchants,
                    json_enchants,
                    en_ench_names,
                    de_ench_names,
                    local_max_levels,
                    local_numeric_ids,
                )
            except RuntimeError as exc:
                blocked_sections.append(("ENCHANTMENTS", str(exc)))
                log(f"  {Colors.RED}ENCHANTMENTS übersprungen: {exc}{Colors.END}")
            else:
                if show_diff("ENCHANTMENTS", old_enchants, new_enchants):
                    changes.append("ENCHANTMENTS")
                    final_enchants = format_enchantments(new_enchants)
                log(f"  {Colors.GREEN}Enchantments: {len(old_enchants)} -> {len(new_enchants)}{Colors.END}")

    old_version = read_source_version()
    new_version = merge_source_metadata(
        old_version,
        release_info=release_info or None,
        wiki_snapshot=wiki_snapshot,
        item_listing_snapshot=item_listing_snapshot,
    )
    source_identity_changed = source_identity_from_metadata(old_version) != source_identity_from_metadata(new_version)
    verification_eligible = args.only is None and not blocked_sections
    if source_identity_changed:
        show_diff("SOURCE_VERSION", old_version, new_version)
    if source_identity_changed or verification_eligible:
        pending_source_version = dict(new_version)
        if not verification_eligible:
            pending_source_version.pop(item_db_verification.VERIFICATION_FIELD, None)

    step("4/4  Änderungen schreiben")
    if not changes and not source_identity_changed:
        log(f"  {Colors.GREEN}Alles aktuell, keine Änderungen.{Colors.END}")
        if args.dry_run or not verification_eligible:
            return report_blocked_sections(blocked_sections)

    if args.dry_run:
        log(f"\n  {Colors.YELLOW}Dry-Run: Keine Änderungen geschrieben.{Colors.END}")
        return report_blocked_sections(blocked_sections)

    if not args.force:
        try:
            answer = input(f"\n  {Colors.BOLD}Schreiben? (j/N): {Colors.END}").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"
        if answer not in ("j", "ja", "y", "yes"):
            log(f"  {Colors.YELLOW}Abgebrochen.{Colors.END}")
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
    )
    for block_name in changes:
        log(f"  {Colors.GREEN}{block_name} aktualisiert{Colors.END}")
    if source_identity_changed:
        log(f"  {Colors.GREEN}SOURCE_VERSION aktualisiert{Colors.END}")
    if verification_eligible:
        log(f"  {Colors.GREEN}ITEM_DB_PRÜFBELEG aktualisiert{Colors.END}")
    log(f"\n  {Colors.BOLD}{Colors.GREEN}Fertig! Update-Dateien konsistent aktualisiert.{Colors.END}")
    return report_blocked_sections(blocked_sections)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        log(f"\n  {Colors.RED}{exc}{Colors.END}")
        raise SystemExit(1) from exc
