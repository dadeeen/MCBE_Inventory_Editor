"""Resolve static inventory sprites from an ordered, explicitly selected pack stack."""

from __future__ import annotations

import re
import zipfile
from dataclasses import replace
from pathlib import Path, PurePosixPath

from .icon_diagnostics import IconSourceError, error_record, warning_record
from .icon_resolution import inventory_sprite_keys, item_icon_key
from .resource_packs import PackReader, _pack_key, read_json_file, relative_name

_MISSING_ICON = object()


def _identifier(value) -> str | None:
    if not isinstance(value, str):
        return None
    value = value if ":" in value else "minecraft:" + value
    return value if re.fullmatch(r"[a-z0-9_.-]+:[a-z0-9_./-]+", value) else None


def _atlas_key(value: str) -> str:
    return value.removeprefix("minecraft:")


def _texture_paths(value) -> list[str]:
    if isinstance(value, dict):
        if value.keys() - {"textures", "path"}:
            raise IconSourceError("Textur benötigt zusätzliche Darstellungsregeln.")
        value = value.get("textures", value.get("path"))
    if isinstance(value, str):
        name = relative_name(value)
        if not name.startswith("textures/"):
            raise IconSourceError("Deklarierte Icon-Textur liegt nicht im textures-Ordner.")
        suffix = PurePosixPath(name).suffix.lower()
        if suffix in {".png", ".webp"}:
            name = name[: -len(suffix)]
        return [name]
    if isinstance(value, list):
        paths = []
        for entry in value:
            resolved = _texture_paths(entry)
            if not resolved:
                return []
            paths.extend(resolved)
        return list(dict.fromkeys(paths))
    return []


def _candidate(pack: PackReader, name: str, source: dict):
    from .icons import _MAX_FILE_BYTES, IconCandidate, _token_for, _token_for_text

    entry = pack.files[name]
    if isinstance(entry, Path):
        if not 0 < entry.stat().st_size <= _MAX_FILE_BYTES:
            return None
        return IconCandidate("", entry, source["label"], _token_for(entry), source_root=pack.path, declared=True)
    if not 0 < entry.file_size <= _MAX_FILE_BYTES:
        return None
    revision = f"{pack.archive_stat.st_size}:{pack.archive_stat.st_mtime_ns}:{entry.CRC}:{entry.file_size}"
    token = _token_for_text(f"{pack.path.resolve()}::{entry.filename}::{revision}")
    return IconCandidate(
        "", None, source["label"], token, archive_path=pack.path, archive_member=entry.filename.replace("\\", "/"), source_root=pack.path.parent, declared=True
    )


def resolve_pack_icons(sources: list[dict]) -> tuple[dict, list[dict], dict[int, int]]:
    """Merge atlas entries, item components and files independently in stack order.

    A higher pack can replace only a PNG or only an atlas entry. Resolving each
    pack in isolation would miss such ordinary cross-pack references.
    """
    from .item_data import catalog_values, is_known_item_id

    assets = {}
    atlas = {}
    definitions = {}
    base_paths = {}
    base_bindings = {}
    base_atlas = {}
    warnings = []
    issues = {}
    file_counts = {}
    outdated_vanilla = []
    for priority, source in enumerate(sources):
        if not source.get("enabled", True) or not Path(source["path"]).exists():
            continue
        if source.get("vanilla"):
            try:
                root = Path(source["path"])
                manifest = read_json_file(root / "manifest.json", root)
                if not isinstance(manifest, dict):
                    continue
                if "item_texture_data" not in manifest or "item_icon_definitions" not in manifest:
                    outdated_vanilla.append(priority)
                rendered = set(manifest.get("generated_block_icons", {})) | set(manifest.get("generated_model_icons", {}))
                for item, path in manifest.get("items", {}).items():
                    if _identifier(item) and isinstance(path, str) and item not in rendered:
                        original = "textures/" + relative_name(path).removeprefix("textures/")
                        base_paths.setdefault(item, original)
                        from .icons import IconCandidate, _token_for

                        image_path = root / "textures/items" / (item.removeprefix("minecraft:") + ".png")
                        if image_path.is_file():
                            assets.setdefault(original, (IconCandidate(item, image_path, source["label"], _token_for(image_path), source_root=root), priority))
                for key, paths in manifest.get("item_texture_data", {}).items():
                    if isinstance(paths, list) and all(isinstance(path, str) for path in paths):
                        normalized = ["textures/" + relative_name(path).removeprefix("textures/") for path in paths]
                        base_atlas.setdefault(_atlas_key(key), normalized)
                        atlas.setdefault(_atlas_key(key), (normalized, priority))
                for item, component in manifest.get("item_icon_definitions", {}).items():
                    identifier = _identifier(item)
                    if identifier:
                        base_bindings.setdefault(identifier, component)
            except FileNotFoundError:
                outdated_vanilla.append(priority)
            except (OSError, ValueError, TypeError, AttributeError, RecursionError) as exc:
                warnings.append(warning_record("Vanilla-Zuordnungen konnten nicht gelesen werden: {error}", error=error_record(exc), sources=[priority]))
            continue
        if not source.get("pack_kind"):
            continue
        if source.get("pack_error"):
            warnings.append(
                warning_record(
                    "Pack {pack} konnte nicht für Icons gelesen werden: {error}", pack=source["label"], error=source["pack_error"], sources=[priority]
                )
            )
            continue
        try:
            with PackReader(source) as pack:
                file_counts[priority] = len(pack.files)
                if source.get("pack_id"):
                    manifest = pack.json("manifest.json", {})
                    if _pack_key(manifest.get("header", {}), "uuid") != (source["pack_id"], source["pack_version"]):
                        raise IconSourceError("Pack-Kennung oder Version wurde während des Einlesens verändert.")
                local_assets, local_atlas, local_definitions = {}, {}, {}
                if source["pack_kind"] == "resources":
                    for name in pack.files:
                        if name.startswith("textures/") and PurePosixPath(name).suffix.lower() in {".png", ".webp"}:
                            candidate = _candidate(pack, name, source)
                            key = name[: -len(PurePosixPath(name).suffix)]
                            if key in local_assets:
                                raise IconSourceError("Mehrere Bilddateien belegen denselben Texturpfad: {path}", path=key)
                            local_assets[key] = (candidate, priority)
                    raw = pack.json("textures/item_texture.json", {})
                    if not isinstance(raw, dict) or not isinstance(raw.get("texture_data", {}), dict):
                        raise IconSourceError("Ungültige Item-Texturzuordnung.")
                    for key, value in raw.get("texture_data", {}).items():
                        try:
                            local_atlas[_atlas_key(key)] = (_texture_paths(value), priority)
                        except ValueError:
                            local_atlas[_atlas_key(key)] = ([], priority)
                    if pack.json("blocks.json", {}) or any(name.startswith("textures/blocks/") for name in pack.files):
                        warnings.append(
                            warning_record(
                                "Pack {pack}: Eigene Blockmodelle und Blockmaterial-Vorschauen werden nicht neu gerendert; "
                                "vorhandene Standard-Icons bleiben verfügbar.",
                                pack=source["label"],
                                sources=[priority],
                            )
                        )
                else:
                    for name in pack.files:
                        if not name.startswith("items/") or not name.endswith(".json"):
                            continue
                        raw = pack.json(name)
                        item = raw.get("minecraft:item", {}) if isinstance(raw, dict) else {}
                        description = item.get("description", {}) if isinstance(item, dict) else {}
                        components = item.get("components", {}) if isinstance(item, dict) else {}
                        identifier = _identifier(description.get("identifier")) if isinstance(description, dict) else None
                        if not identifier or not isinstance(components, dict):
                            raise IconSourceError("Ungültige Item-Definition: {path}", path=name)
                        if identifier in local_definitions:
                            raise IconSourceError("Item ist im Pack mehrfach definiert: {item}", item=identifier)
                        # Whole item definitions shadow lower packs even when
                        # the higher definition omits the icon component.
                        local_definitions[identifier] = (components.get("minecraft:icon", _MISSING_ICON), priority)
                # Publish only after the reader verifies an unchanged archive.
            for key, value in local_assets.items():
                assets.setdefault(key, value)
            for key, value in local_atlas.items():
                atlas.setdefault(key, value)
            for key, value in local_definitions.items():
                definitions.setdefault(key, value)
        except (OSError, ValueError, KeyError, TypeError, AttributeError, RecursionError, zipfile.BadZipFile, RuntimeError) as exc:
            warnings.append(
                warning_record("Pack {pack} konnte nicht für Icons gelesen werden: {error}", pack=source["label"], error=error_record(exc), sources=[priority])
            )

    # Existing Vanilla manifests contain resolved paths. New publications also
    # retain the declarations, so an RP may remap a key without replacing a PNG.
    for item, path in base_paths.items():
        if item not in base_bindings:
            matches = [key for key, paths in base_atlas.items() if paths == [path]]
            if len(matches) == 1:
                base_bindings[item] = matches[0]
    targets = set(definitions) | set(base_paths) | set(base_bindings) | set(catalog_values()["ITEMS"])
    result = {}
    for item in targets:
        component, definition_priority = definitions.get(item, (base_bindings.get(item), len(sources)))
        declared_override = item in definitions and component is not _MISSING_ICON
        if component is _MISSING_ICON:
            if not item.startswith("minecraft:") or not is_known_item_id(item):
                issues[item] = ("keine unterstützte statische Icon-Definition", definition_priority)
                continue
            component = base_bindings.get(item)
            # Omitting an icon hides lower item components, but does not give
            # the base image priority over explicitly configured global icons.
            definition_priority = len(sources)
        key = item_icon_key(component)
        explicit = declared_override or item in base_bindings
        if explicit and not key:
            if item in definitions:
                issues[item] = ("keine unterstützte statische Icon-Definition", definition_priority)
            continue
        keys = [_atlas_key(key)] if key else inventory_sprite_keys(item.removeprefix("minecraft:"))
        matched = next((atlas[value] for value in keys if value in atlas), None)
        diagnostic_source = matched[1] if matched else definition_priority
        paths = matched[0] if matched else [base_paths[item]] if item in base_paths and not declared_override else []
        binding_priority = min(definition_priority, matched[1] if matched else len(sources))
        if matched is None and not paths and not explicit:
            paths = ["textures/items/" + value for value in keys if "textures/items/" + value in assets]
        if len(paths) != 1:
            if item in definitions or (matched and sources[matched[1]].get("pack_kind")):
                issues[item] = ("Textur fehlt oder benötigt eine Variantenauswahl", diagnostic_source)
            continue
        path = paths[0]
        if path.startswith("textures/entity/"):
            if item in definitions or (matched and sources[matched[1]].get("pack_kind")):
                issues[item] = ("Modelltextur benötigt eine gerenderte Vorschau", diagnostic_source)
            continue
        selected = assets.get(path)
        if selected is None:
            if item in definitions or (matched and sources[matched[1]].get("pack_kind")):
                issues[item] = ("deklarierte Bilddatei fehlt", diagnostic_source)
            continue
        candidate, asset_priority = selected
        if candidate is None:
            issues[item] = ("deklarierte Bilddatei ist leer oder zu groß", asset_priority)
            continue
        result[item] = (replace(candidate, item_id=item), min(binding_priority, asset_priority))
    if outdated_vanilla:
        warnings.append(
            warning_record(
                "Vanilla-Zuordnungsdaten fehlen. Bitte Vanilla-Icons aktualisieren, damit Pack-Verweise vollständig aufgelöst werden können.",
                sources=outdated_vanilla,
            )
        )
    for item, (reason, priority) in sorted(issues.items())[:50]:
        warnings.append(
            warning_record("Icon für {item}: {reason}. Standarddarstellung wird verwendet.", item=item, reason=warning_record(reason), sources=[priority])
        )
    if len(issues) > 50:
        remaining_sources = sorted({priority for _, (_, priority) in sorted(issues.items())[50:]})
        warnings.append(warning_record("Weitere nicht auflösbare Item-Icons: {count}.", count=len(issues) - 50, sources=remaining_sources))
    return result, warnings, file_counts
