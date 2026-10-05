"""Read Bedrock pack activation and metadata without modifying game files.

Pack lists and manifests select sources; texture interpretation lives in
icon_pack_resolution. All file access shares the icon reader's path boundaries.
"""

from __future__ import annotations

import json
import os
import re
import zipfile
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from uuid import UUID

from .archive_errors import ZIP_READ_ERRORS
from .i18n import t
from .icon_diagnostics import IconSourceError, error_record, warning_record
from .path_safety import is_linklike

MAX_METADATA_BYTES = 2 * 1024 * 1024
MAX_PACKS = 256
MAX_PACK_FILES = 20000


def strip_json_comments(text: str) -> str:
    """Remove JSONC comments while preserving strings and token boundaries."""
    pattern = r'"(?:\\.|[^"\\])*"|//[^\r\n]*|/\*[\s\S]*?\*/'
    return re.sub(pattern, lambda match: match[0] if match[0].startswith('"') else " ", text)


def parse_json(raw: bytes):
    if len(raw) > MAX_METADATA_BYTES:
        raise IconSourceError("Pack-Metadaten überschreiten das Größenlimit.")
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise IconSourceError("Pack-Metadaten enthalten einen mehrfach belegten Schlüssel: {key}", key=key)
            result[key] = value
        return result

    return json.loads(strip_json_comments(raw.decode("utf-8-sig")), object_pairs_hook=unique_object)


def read_json_file(path: Path, root: Path):
    from .icons import _open_source_file

    with _open_source_file(path, root) as stream:
        return parse_json(stream.read(MAX_METADATA_BYTES + 1))


def _read_archive_json(zf: zipfile.ZipFile, entry: zipfile.ZipInfo):
    if entry.file_size > MAX_METADATA_BYTES:
        raise IconSourceError("Pack-Metadaten überschreiten das Größenlimit.")
    try:
        with zf.open(entry) as stream:
            raw = stream.read(MAX_METADATA_BYTES + 1)
    except ZIP_READ_ERRORS as exc:
        # ZIP decoders expose different exception types for corrupt/encrypted
        # streams. Contain failures at this read boundary, before parsing JSON.
        raise IconSourceError("Pack-Metadaten können nicht entpackt werden: {path}", path=entry.filename) from exc
    return parse_json(raw)


def relative_name(value: str) -> str:
    name = value.replace("\\", "/")
    if not name or "\x00" in name or ":" in name or name.startswith("/") or any(part in {"", ".", ".."} for part in name.split("/")):
        raise IconSourceError("Ungültiger relativer Pfad in Pack-Metadaten.")
    return name


class PackReader:
    """A bounded, read-only view of one folder or archive, with one subpack."""

    def __init__(self, source: dict):
        self.path = Path(source["path"])
        self.prefix = source.get("pack_prefix", "")
        self.subpack = source.get("subpack", "")
        self.files: dict[str, Path | zipfile.ZipInfo] = {}
        self.stack = ExitStack()
        self.archive = None
        self.archive_stat = None
        self.zf = None

    def __enter__(self):
        from .icons import _directory_files, _open_source_file

        try:
            entries = {}
            if self.path.is_dir():
                def failed(error):
                    raise error

                def linked(path):
                    raise IconSourceError("Pack enthält einen Symlink oder Reparse-Point: {path}", path=path)

                for path in _directory_files(self.path, onerror=failed, onlink=linked):
                    entries[path.relative_to(self.path).as_posix()] = path
                    if len(entries) > MAX_PACK_FILES:
                        raise IconSourceError("Pack überschreitet das Dateilimit.")
            else:
                self.archive = self.stack.enter_context(_open_source_file(self.path, self.path.parent))
                self.archive_stat = os.fstat(self.archive.fileno())
                self.zf = self.stack.enter_context(zipfile.ZipFile(self.archive))
                infos = self.zf.infolist()
                if len(infos) > MAX_PACK_FILES:
                    raise IconSourceError("Pack überschreitet das Dateilimit.")
                for info in infos:
                    if info.is_dir():
                        continue
                    name = relative_name(info.filename)
                    if self.prefix:
                        if not name.startswith(self.prefix):
                            continue
                        name = name[len(self.prefix):]
                    if name in entries:
                        raise IconSourceError("Pack enthält einen mehrfach belegten Dateipfad: {path}", path=name)
                    entries[name] = info
            self.files = {name: entry for name, entry in entries.items() if not name.startswith("subpacks/")}
            if self.subpack:
                prefix = f"subpacks/{relative_name(self.subpack)}/"
                if not any(name.startswith(prefix) for name in entries):
                    raise IconSourceError("Ausgewähltes Subpack fehlt im Pack.")
                self.files.update({name[len(prefix):]: entry for name, entry in entries.items() if name.startswith(prefix)})
            return self
        except BaseException:
            self.stack.close()
            raise

    def __exit__(self, *args):
        try:
            if self.archive_stat is not None:
                from .icons import _checked_source_path

                current = _checked_source_path(self.path, self.path.parent)
                if not os.path.samestat(self.archive_stat, current) or (
                    self.archive_stat.st_size, self.archive_stat.st_mtime_ns
                ) != (current.st_size, current.st_mtime_ns):
                    raise IconSourceError("Pack wurde während des Einlesens verändert.")
        finally:
            self.stack.close()

    def json(self, name: str, default=None):
        entry = self.files.get(relative_name(name))
        if entry is None:
            return default
        if isinstance(entry, Path):
            return read_json_file(entry, self.path)
        return _read_archive_json(self.zf, entry)


def _manifest(path: Path) -> tuple[dict, str]:
    from .icons import _open_source_file

    if path.is_dir():
        raw, prefix = read_json_file(path / "manifest.json", path), ""
    else:
        with _open_source_file(path, path.parent) as stream, zipfile.ZipFile(stream) as zf:
            infos = zf.infolist()
            if len(infos) > MAX_PACK_FILES:
                raise IconSourceError("Pack überschreitet das Dateilimit.")
            manifests = [info for info in infos if PurePosixPath(relative_name(info.filename.rstrip("/"))).name == "manifest.json" and not info.is_dir()]
            manifests = [info for info in manifests if len(PurePosixPath(info.filename).parts) <= 2]
            if not manifests:
                raise FileNotFoundError("manifest.json")
            if len(manifests) != 1 or manifests[0].file_size > MAX_METADATA_BYTES:
                raise IconSourceError("Pack-Manifest fehlt oder ist nicht eindeutig.")
            info = manifests[0]
            prefix = relative_name(info.filename).removesuffix("manifest.json")
            raw = _read_archive_json(zf, info)
    if not isinstance(raw, dict) or not isinstance(raw.get("header"), dict):
        raise IconSourceError("Ungültiges Pack-Manifest.")
    return raw, prefix


def _version(value) -> str:
    if isinstance(value, list) and len(value) == 3 and all(type(part) is int and part >= 0 for part in value):
        return ".".join(map(str, value))
    if isinstance(value, str) and re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][\w.-]+)?", value):
        return value
    raise IconSourceError("Ungültige Pack-Version.")


def _pack_key(entry: dict, id_field: str) -> tuple[str, str]:
    if not isinstance(entry, dict) or not isinstance(entry.get(id_field), str) or "version" not in entry:
        raise IconSourceError("Ungültiges Pack-Manifest.")
    return str(UUID(entry[id_field])), _version(entry["version"])


@dataclass
class PackSelection:
    sources: list[dict]
    warnings: list[str]


def _roots(world: Path, folder: str, warnings: list[str]) -> list[Path]:
    from .icons import _default_roots

    bases = [world, world.parent, world.parent.parent]
    bases.extend(parent for parent in world.parents if parent.name.lower() == "com.mojang")
    try:
        defaults = _default_roots()
    except OSError as exc:
        warnings.append(t("Pack-Suche ist unvollständig: {error}", error=str(exc)))
        defaults = []
    for candidate in defaults:
        bases.append(candidate)
        if candidate.name.lower() == "users":
            try:
                bases.extend(child / "games" / "com.mojang" for child in sorted(candidate.iterdir())[:MAX_PACKS] if child.is_dir())
            except OSError as exc:
                warnings.append(t("Pack-Suche ist unvollständig: {error}", error=str(exc)))
    result = []
    seen = set()
    for base in bases:
        for name in (folder, "development_" + folder):
            root = base / name
            if root in seen:
                continue
            seen.add(root)
            try:
                if root.is_dir() and not is_linklike(root):
                    result.append(root)
            except OSError as exc:
                warnings.append(t("Pack-Suche ist unvollständig: {error}", error=str(exc)))
    return result


def select_world_packs(world_path: str | None) -> PackSelection:
    """Resolve explicitly active packs in stack order (highest priority first)."""
    selection = PackSelection([], [])
    if not world_path:
        return selection
    if "\x00" in world_path:
        raise IconSourceError("Ungültiger Weltpfad.")
    world = Path(world_path).expanduser().absolute()
    for folder, kind in (("resource_packs", "resources"), ("behavior_packs", "data")):
        listing = world / f"world_{folder}.json"
        try:
            registrations = read_json_file(listing, world)
        except FileNotFoundError:
            continue
        except (OSError, ValueError, RecursionError) as exc:
            selection.warnings.append(t("Aktive Packs konnten nicht gelesen werden: {path} ({error})", path=listing, error=str(exc)))
            continue
        if not isinstance(registrations, list) or len(registrations) > MAX_PACKS:
            selection.warnings.append(t("Ungültige oder zu große Pack-Liste: {path}", path=listing))
            continue
        if not registrations:
            continue
        candidates: dict[tuple[str, str], list[dict]] = {}
        roots = _roots(world, folder, selection.warnings)
        inspected = 0
        for rank, root in enumerate(roots):
            # Publish one complete discovery level at a time. A failure in an
            # optional installed root cannot discard verified world-local packs.
            local_candidates = []
            try:
                paths = [root] if (root / "manifest.json").exists() else sorted(root.iterdir())
                for path in paths:
                    if is_linklike(path) or not (path.is_dir() or path.suffix.lower() in {".zip", ".mcpack"}):
                        continue
                    inspected += 1
                    if inspected > MAX_PACKS:
                        raise IconSourceError("Pack-Suche überschreitet das Paketlimit.")
                    try:
                        manifest, prefix = _manifest(path)
                        if not any(isinstance(module, dict) and module.get("type") == kind for module in manifest.get("modules", [])):
                            continue
                        key = _pack_key(manifest["header"], "uuid")
                        local_candidates.append((key, {
                            "path": str(path.resolve()), "pack_kind": kind, "pack_prefix": prefix,
                            "enabled": True, "auto": True, "world": True,
                            "label": str(manifest["header"].get("name") or path.name),
                            "_rank": rank, "_manifest": manifest,
                        }))
                    except (OSError, ValueError, KeyError, TypeError, RecursionError, zipfile.BadZipFile, RuntimeError):
                        # An unreadable/unidentified candidate cannot satisfy an
                        # activation. Report the missing registration below.
                        continue
            except (OSError, ValueError) as exc:
                selection.warnings.append(t("Pack-Suche ist unvollständig: {error}", error=str(exc)))
                if inspected > MAX_PACKS:
                    break
                continue
            for key, source in local_candidates:
                candidates.setdefault(key, []).append(source)
        activated_ids = []
        for entry in registrations:
            try:
                activated_ids.append(_pack_key(entry, "pack_id")[0])
            except ValueError:
                continue
        for entry in registrations:
            try:
                key = _pack_key(entry, "pack_id")
                if activated_ids.count(key[0]) > 1:
                    raise IconSourceError("Pack ist mehrfach aktiviert.")
                matches = candidates.get(key, [])
                if not matches:
                    raise IconSourceError("Passendes Pack mit dieser Kennung und Version fehlt oder ist nicht lesbar.")
                best = [match for match in matches if match["_rank"] == matches[0]["_rank"]]
                if len(best) != 1:
                    raise IconSourceError("Mehrere Packs haben dieselbe Kennung und Version.")
                source = dict(best[0])
                manifest = source.pop("_manifest")
                source.pop("_rank")
                source["pack_id"], source["pack_version"] = key
                source["_dependencies"] = manifest.get("dependencies", [])
                subpacks = manifest.get("subpacks", [])
                subpack = entry.get("subpack", "")
                if subpacks and not subpack:
                    raise IconSourceError("Subpack-Auswahl fehlt; eine geräteabhängige Variante wird nicht geraten.")
                if subpack:
                    if not isinstance(subpack, str) or "/" in relative_name(subpack):
                        raise IconSourceError("Ungültige Subpack-Auswahl.")
                    if not any(isinstance(value, dict) and value.get("folder_name") == subpack for value in subpacks):
                        raise IconSourceError("Ausgewähltes Subpack ist nicht im Manifest enthalten.")
                    source["subpack"] = subpack
                selection.sources.append(source)
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                identity = entry.get("pack_id", "?") if isinstance(entry, dict) else "?"
                selection.warnings.append(t("Aktives Pack {pack} kann nicht für Icons verwendet werden: {error}", pack=identity, error=str(exc)))
    selected_keys = {(source["pack_id"], source["pack_version"]) for source in selection.sources}
    for source in selection.sources:
        dependencies = source.pop("_dependencies", [])
        if not isinstance(dependencies, list):
            dependencies = [None]
        for dependency in dependencies:
            if isinstance(dependency, dict) and "module_name" in dependency:
                continue
            try:
                if _pack_key(dependency, "uuid") in selected_keys:
                    continue
            except (ValueError, TypeError, KeyError, AttributeError):
                pass
            selection.warnings.append(t("Pack {pack}: Eine Pack-Abhängigkeit ist nicht eindeutig in der aktiven Auswahl verfügbar.", pack=source["label"]))
            break
    return selection


def describe_icon_source(source: dict) -> dict:
    """Recognize an explicitly configured pack; loose icon folders stay valid."""
    path = Path(source["path"])
    if path.is_dir() and not (path / "manifest.json").exists():
        return source
    if not path.exists():
        return source
    try:
        manifest, prefix = _manifest(path)
    except FileNotFoundError:
        return source
    except (OSError, ValueError, KeyError, TypeError, RecursionError, zipfile.BadZipFile, RuntimeError) as exc:
        return {**source, "pack_kind": "invalid", "pack_error": error_record(exc)}
    modules = manifest.get("modules", [])
    if not isinstance(modules, list):
        modules = []
    kind = next((value["type"] for value in modules if isinstance(value, dict) and value.get("type") in {"resources", "data"}), None)
    if kind:
        described = {**source, "pack_kind": kind, "pack_prefix": prefix}
        if manifest.get("subpacks") and not source.get("subpack"):
            described["pack_error"] = warning_record("Subpack-Auswahl fehlt; eine geräteabhängige Variante wird nicht geraten.")
        return described
    return {**source, "pack_kind": "invalid", "pack_error": warning_record("Ungültiges Pack-Manifest.")}
