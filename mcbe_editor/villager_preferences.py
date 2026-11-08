"""World-scoped editor aliases and regions, stored outside the Minecraft world."""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

from .i18n import t
from .runtime_data import atomic_write_private_text
from .world_locks import lock_key, locked_operation

MAX_REGIONS = 256
MAX_ALIASES = 10000
MAX_PREFERENCES_BYTES = 2 * 1024 * 1024
_ID = re.compile(r"[A-Za-z0-9:_=.-]{1,512}\Z")
_REGION_ID = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")


class VillagerPreferencesStaleError(ValueError):
    pass


def _text(value: Any, *, empty: bool = False) -> str:
    if not isinstance(value, str) or len(value) > 80 or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError(t("Name und Alias dürfen höchstens 80 Zeichen und keine Steuerzeichen enthalten."))
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError(t("Name und Alias müssen gültigen Unicode-Text enthalten.")) from exc
    result = value.strip()
    if not result and not empty:
        raise ValueError(t("Eine Region benötigt einen Namen."))
    return result


def _coordinate(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or abs(value) > 2**35 or not math.isfinite(value):
        raise ValueError(t("Regionskoordinaten müssen endliche Zahlen innerhalb des Weltbereichs sein."))
    return float(value)


def normalize_preferences(aliases: Any, regions: Any) -> dict[str, Any]:
    if not isinstance(aliases, dict) or len(aliases) > MAX_ALIASES:
        raise ValueError(t("Die Aliasliste ist ungültig oder zu groß."))
    normalized_aliases = {}
    for identifier, value in aliases.items():
        if not isinstance(identifier, str) or not _ID.fullmatch(identifier) or identifier in {"__proto__", "constructor", "prototype"}:
            raise ValueError(t("Ungültige Dorfbewohner-ID in der Aliasliste."))
        label = _text(value, empty=True)
        if label:
            normalized_aliases[identifier] = label
    if not isinstance(regions, list) or len(regions) > MAX_REGIONS:
        raise ValueError(t("Die Regionenliste ist ungültig oder zu groß."))
    normalized_regions = []
    seen = set()
    allowed = {"id", "name", "dimension", "min_x", "max_x", "min_z", "max_z", "min_y", "max_y"}
    for region in regions:
        if not isinstance(region, dict) or set(region) - allowed:
            raise ValueError(t("Die Region enthält unbekannte oder ungültige Felder."))
        identifier = region.get("id")
        if not isinstance(identifier, str) or not _REGION_ID.fullmatch(identifier) or identifier in seen:
            raise ValueError(t("Regions-IDs müssen eindeutig sein."))
        dimension = region.get("dimension")
        if isinstance(dimension, bool) or not isinstance(dimension, int) or not -(2**31) <= dimension < 2**31:
            raise ValueError(t("Eine Region benötigt eine gültige Dimension."))
        normalized = {"id": identifier, "name": _text(region.get("name")), "dimension": dimension}
        for axis in ("x", "z", "y"):
            low, high = region.get(f"min_{axis}"), region.get(f"max_{axis}")
            if axis == "y" and low is None and high is None:
                continue
            low, high = _coordinate(low), _coordinate(high)
            if low > high:
                raise ValueError(t("Die untere Regionsgrenze darf nicht über der oberen Grenze liegen."))
            normalized[f"min_{axis}"], normalized[f"max_{axis}"] = low, high
        seen.add(identifier)
        normalized_regions.append(normalized)
    return {"version": 1, "aliases": normalized_aliases, "regions": normalized_regions}


def _encoded(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _public(data: dict[str, Any]) -> dict[str, Any]:
    return {**data, "revision": hashlib.sha256(_encoded(data).encode("utf-8")).hexdigest()}


class VillagerPreferences:
    def __init__(self, directory: Path):
        self.directory = directory

    def _path(self, world_path: str) -> Path:
        digest = hashlib.sha256(lock_key(world_path).encode("utf-8", "surrogatepass")).hexdigest()
        return self.directory / f"{digest}.json"

    def _read(self, path: Path) -> dict[str, Any]:
        try:
            with path.open("rb") as handle:
                raw = handle.read(MAX_PREFERENCES_BYTES + 1)
        except FileNotFoundError:
            return _public(normalize_preferences({}, []))
        if len(raw) > MAX_PREFERENCES_BYTES:
            raise ValueError(t("Die gespeicherten Dorfbewohner-Einstellungen sind zu groß."))
        try:
            data = json.loads(raw)
            if not isinstance(data, dict) or data.get("version") != 1:
                raise ValueError()
            return _public(normalize_preferences(data.get("aliases"), data.get("regions")))
        except (ValueError, TypeError, UnicodeError) as exc:
            raise ValueError(t("Die gespeicherten Dorfbewohner-Einstellungen sind beschädigt und wurden nicht überschrieben.")) from exc

    def read(self, world_path: str) -> dict[str, Any]:
        # Replacements are atomic; an unlocked read sees either complete version.
        return self._read(self._path(world_path))

    def save(self, world_path: str, *, revision: Any, aliases: Any, regions: Any) -> dict[str, Any]:
        data = normalize_preferences(aliases, regions)
        encoded = _encoded(data)
        if len(encoded.encode("utf-8")) > MAX_PREFERENCES_BYTES:
            raise ValueError(t("Die Dorfbewohner-Einstellungen sind zu groß."))
        path = self._path(world_path)
        with locked_operation(f"villager-preferences:{path.stem}", root=self.directory):
            current = self._read(path)
            if not isinstance(revision, str) or revision != current["revision"]:
                raise VillagerPreferencesStaleError(t("Aliase oder Regionen wurden zwischenzeitlich geändert. Bitte Dorfbewohner neu laden."))
            atomic_write_private_text(path, encoded)
        return _public(data)
