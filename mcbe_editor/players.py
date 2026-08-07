import base64
import contextlib
import errno
import hashlib
import json
import logging
import os
import re
import secrets
import shutil
import stat
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import PurePosixPath

import amulet_nbt as nbt

from .bedrock_nbt import load_player_nbt
from .i18n import t
from .inventory import extract_player_stats, nbt_to_json, protected_player_nbt_flags
from .service_errors import PlayerImportPreviewStaleError
from .world import LOCAL_PLAYER_KEY, get_world_name

MAX_EXPORT_UNCOMPRESSED_MB = 50
MAX_EXPORT_MEMBERS = 100
MAX_PLAYER_LABEL_LENGTH = 128

EXPORT_FORMAT = "mcbe-player-export"
EXPORT_VERSION = 1
PLAYER_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+$")
PLAYER_LIKE_KEY_PREFIXES = (b"player_",)
LOCAL_PLAYER_KEY_ALIASES = {LOCAL_PLAYER_KEY, b"local_player"}
PLAYER_HINT_TAGS = {
    "Inventory",
    "EnderChestInventory",
    "Armor",
    "Offhand",
    "Mainhand",
    "SelectedInventorySlot",
    "Pos",
    "Rotation",
    "Motion",
    "Health",
    "PlayerGameMode",
    "PlayerGameType",
    "DimensionId",
    "Level",
    "abilities",
    "Attributes",
    "ActiveEffects",
    "PlayerLevel",
    "PlayerLevelProgress",
    "XPLevel",
    "XPProgress",
    "foodLevel",
    "foodSaturationLevel",
}
UNKNOWN_KEY_STRONG_PLAYER_HINTS = {
    "SelectedInventorySlot",
    "PlayerGameMode",
    "PlayerGameType",
    "abilities",
    "PlayerLevel",
    "PlayerLevelProgress",
    "XPLevel",
    "XPProgress",
    "foodLevel",
    "foodSaturationLevel",
}
UNKNOWN_KEY_STRONG_PLAYER_HINT_BYTES = tuple(name.encode("ascii") for name in sorted(UNKNOWN_KEY_STRONG_PLAYER_HINTS))
FALLBACK_PLAYER_SCAN_LIMIT = 750
MAX_PLAYER_NBT_CANDIDATE_BYTES = 2 * 1024 * 1024
PLAYER_IMPORT_TOKEN_VERSION = 1

LOGGER = logging.getLogger(__name__)


def encode_player_key(key: bytes) -> str:
    return base64.urlsafe_b64encode(key).decode("ascii").rstrip("=")


def decode_player_key(encoded: str) -> bytes:
    if not encoded or not isinstance(encoded, str):
        raise ValueError("Kein Spieler-Key angegeben.")
    if len(encoded) > 512 or not PLAYER_KEY_RE.fullmatch(encoded):
        raise ValueError("Ungültiger Spieler-Key.")
    padding = "=" * (-len(encoded) % 4)
    try:
        decoded = base64.urlsafe_b64decode((encoded + padding).encode("ascii"))
    except Exception as exc:
        raise ValueError("Ungültiger Spieler-Key.") from exc
    if not decoded:
        raise ValueError("Ungültiger Spieler-Key.")
    return decoded


def _truncate_label(label: str) -> str:
    if len(label) <= MAX_PLAYER_LABEL_LENGTH:
        return label
    return f"{label[: MAX_PLAYER_LABEL_LENGTH - 1]}…"


def _safe_key_label(key: bytes) -> str:
    if key in LOCAL_PLAYER_KEY_ALIASES:
        return t("Lokaler Spieler")
    try:
        decoded = key.decode("utf-8")
        if decoded.isprintable():
            return _truncate_label(decoded)
    except UnicodeDecodeError:
        pass
    return _truncate_label(key.hex())


def _tag_type_name(value) -> str:
    return type(value).__name__


def _record_debug(key: bytes, raw_bytes: bytes, *, player_tag=None, parse_error: Exception | None = None) -> dict:
    debug = {
        "key_label": _safe_key_label(key),
        "key_b64": encode_player_key(key),
        "key_hex": key.hex(),
        "raw_length": len(raw_bytes or b""),
        "first_bytes_hex": (raw_bytes or b"")[:24].hex(),
        "starts_like_named_compound": bool(raw_bytes) and raw_bytes[:1] == b"\x0a",
    }
    if parse_error is not None:
        debug["parse_error"] = f"{parse_error.__class__.__name__}: {parse_error}"
    if player_tag is not None and hasattr(player_tag, "keys"):
        try:
            tag_names = sorted(str(name) for name in player_tag)
        except Exception:
            tag_names = []
        debug["tag_count"] = len(tag_names)
        debug["tag_names"] = tag_names[:80]
        tag_types = {}
        for name in tag_names[:80]:
            try:
                tag_types[name] = _tag_type_name(player_tag.get(name))
            except Exception:
                tag_types[name] = "<unlesbar>"
        debug["tag_types"] = tag_types
    return debug


def _load_player_tag(raw_bytes):
    named_tag = load_player_nbt(raw_bytes)
    return named_tag, named_tag.tag


def _looks_like_player_key(key: bytes) -> bool:
    lower_key = key.lower()
    return key in LOCAL_PLAYER_KEY_ALIASES or lower_key.startswith(PLAYER_LIKE_KEY_PREFIXES) or b"player" in lower_key


def _looks_like_nbt_candidate(raw_bytes: bytes) -> bool:
    # Bedrock player records are usually uncompressed little-endian NBT with a
    # Compound root.  Chunk data and most LevelDB metadata do not start this way,
    # so this keeps the fallback scan cheap and avoids trying to parse the world.
    return bool(raw_bytes) and raw_bytes[0] == 10 and len(raw_bytes) <= MAX_PLAYER_NBT_CANDIDATE_BYTES


def _looks_like_unknown_player_candidate(raw_bytes: bytes) -> bool:
    """Cheaply reject ordinary actor NBT before the bounded fallback parser."""

    if not _looks_like_nbt_candidate(raw_bytes):
        return False
    if b"EnderChestInventory" in raw_bytes:
        return True
    return b"Inventory" in raw_bytes and any(marker in raw_bytes for marker in UNKNOWN_KEY_STRONG_PLAYER_HINT_BYTES)


def classify_player_record(key: bytes, raw_bytes: bytes, *, allow_unknown_key: bool = False) -> dict | None:
    is_local = key in LOCAL_PLAYER_KEY_ALIASES
    key_is_player_like = _looks_like_player_key(key)

    if not key_is_player_like and not allow_unknown_key:
        return None

    try:
        _named_tag, player_tag = _load_player_tag(raw_bytes)
    except Exception as exc:
        if key_is_player_like:
            return {
                "player_key": encode_player_key(key),
                "raw_key_preview": _safe_key_label(key),
                "label": _safe_key_label(key),
                "kind": "local" if is_local else "unknown",
                "confidence": "low",
                "editable": False,
                "exportable": False,
                "reason_code": "nbt_unreadable",
                "reason": (
                    "Key wirkt spielerartig, aber der Player-NBT-Datensatz konnte nicht sicher gelesen werden. "
                    "Bearbeitung ist blockiert, damit keine Daten normalisiert oder gelöscht werden."
                ),
                "debug": _record_debug(key, raw_bytes, parse_error=exc),
            }
        return None

    if not hasattr(player_tag, "keys") or not hasattr(player_tag, "get"):
        if key_is_player_like:
            return {
                "player_key": encode_player_key(key),
                "raw_key_preview": _safe_key_label(key),
                "label": _safe_key_label(key),
                "kind": "local" if is_local else "unknown",
                "confidence": "low",
                "editable": False,
                "exportable": False,
                "reason_code": "non_compound_root",
                "reason": "Key wirkt spielerartig, Player-NBT hat aber keinen Compound-Root-Tag.",
                "debug": _record_debug(key, raw_bytes, player_tag=player_tag),
            }
        return None

    tag_names = set(player_tag.keys())
    has_inventory_tag = "Inventory" in tag_names
    has_inventory_list = has_inventory_tag and isinstance(player_tag.get("Inventory"), nbt.ListTag)
    inventory_opaque = has_inventory_tag and not has_inventory_list
    has_ender_chest_tag = "EnderChestInventory" in tag_names
    has_ender_chest_list = has_ender_chest_tag and isinstance(player_tag.get("EnderChestInventory"), nbt.ListTag)
    ender_chest_opaque = has_ender_chest_tag and not has_ender_chest_list
    has_player_hints = bool(tag_names & (PLAYER_HINT_TAGS - {"Inventory", "EnderChestInventory"}))

    if allow_unknown_key and not key_is_player_like:
        # Unknown keys are scanned even when a normal local/remote player exists.
        # Pos/Health/Inventory alone also occur on ordinary actors, so require an
        # EnderChestInventory tag or Inventory plus a player-specific state tag.
        has_safe_unknown_shape = has_ender_chest_tag or (has_inventory_tag and bool(tag_names & UNKNOWN_KEY_STRONG_PLAYER_HINTS))
        if not has_safe_unknown_shape:
            return None

    if not (has_inventory_tag or has_ender_chest_tag or has_player_hints or is_local):
        return None

    kind = "local" if is_local else ("remote" if key_is_player_like else "unknown")

    # Important safety distinction:
    # - missing Inventory can be loaded only when other player-shaped NBT hints
    #   are present. A normal save must preserve that absence unless the user
    #   explicitly chooses to create a new Inventory tag and actually writes items.
    # - opaque/future Inventory or EnderChest tags make the whole player read-only
    #   for now. The current UI posts both visible containers on save, so allowing
    #   partial edits would risk replacing unknown data with empty standard lists.
    has_safe_player_shape = has_inventory_list or has_ender_chest_list or has_player_hints
    editable = has_safe_player_shape and not inventory_opaque and not ender_chest_opaque
    inventory_create_requires_confirmation = editable and not has_inventory_tag
    if editable and has_inventory_list and (is_local or "Pos" in tag_names or "PlayerGameType" in tag_names):
        confidence = "high"
    elif editable or has_inventory_tag or has_ender_chest_tag or has_player_hints:
        confidence = "medium"
    else:
        confidence = "low"

    if inventory_opaque:
        reason_code = "inventory_opaque"
        reason = "Inventory-Tag hat einen unbekannten NBT-Typ. Bearbeitung ist blockiert, damit das Inventar nicht ersetzt oder gelöscht wird."
    elif ender_chest_opaque:
        reason_code = "ender_chest_opaque"
        reason = "EnderChestInventory hat einen unbekannten NBT-Typ. Bearbeitung ist blockiert, damit Enderchest-Daten nicht ersetzt oder gelöscht werden."
    elif has_inventory_list or has_ender_chest_list:
        reason_code = "ok"
        reason = "Sicher erkannt."
    elif inventory_create_requires_confirmation:
        reason_code = "missing_inventory_safe_shape"
        reason = (
            "Inventory-Tag fehlt. Der Spieler kann geladen werden; ein neues Inventar wird nur nach ausdrücklicher "
            "Bestätigung und nur bei echten Inventar-Änderungen angelegt."
        )
    else:
        reason_code = "insufficient_player_shape"
        reason = "Datensatz ist nicht ausreichend als sicher bearbeitbarer Player-NBT erkennbar; read-only."

    return {
        "player_key": encode_player_key(key),
        "raw_key_preview": _safe_key_label(key),
        "label": _safe_key_label(key),
        "kind": kind,
        "confidence": confidence,
        "editable": editable,
        "exportable": True,
        "reason_code": reason_code,
        "reason": reason,
        "debug": _record_debug(key, raw_bytes, player_tag=player_tag),
        "has_inventory": has_inventory_list,
        "has_inventory_tag": has_inventory_tag,
        "inventory_opaque": inventory_opaque,
        "inventory_create_requires_confirmation": inventory_create_requires_confirmation,
        "inventory_will_be_created": False,
        "has_ender_chest": has_ender_chest_list,
        "has_ender_chest_tag": has_ender_chest_tag,
        "ender_chest_opaque": ender_chest_opaque,
    }


class PlayerScanner:
    def __init__(self, db):
        self.db = db

    def list_players(self):
        players = []
        seen_keys = set()
        fallback_candidates = []

        for local_key in LOCAL_PLAYER_KEY_ALIASES:
            try:
                local_bytes = self.db.get(local_key)
                local_player = classify_player_record(local_key, local_bytes)
                if local_player:
                    players.append(local_player)
                    seen_keys.add(local_key)
            except KeyError:
                pass

        for key, value in self.db.iter_items():
            if key in seen_keys:
                continue
            player = classify_player_record(key, value)
            if player:
                players.append(player)
                seen_keys.add(key)
                continue
            if len(fallback_candidates) < FALLBACK_PLAYER_SCAN_LIMIT and _looks_like_unknown_player_candidate(value):
                fallback_candidates.append((key, value))

        # Some Bedrock/GDK and tooling versions use less predictable LevelDB keys.
        # Scan plausible Compound-root values even when a known player exists;
        # classify_player_record applies a stricter player-only shape check to
        # unknown keys so ordinary actors are not surfaced as editable players.
        for key, value in fallback_candidates:
            if key in seen_keys:
                continue
            player = classify_player_record(key, value, allow_unknown_key=True)
            if player:
                players.append(player)
                seen_keys.add(key)

        players.sort(key=lambda item: (item["kind"] != "local", item["kind"] == "unknown", item["label"].lower()))
        return players


def player_preview_from_bytes(raw_bytes):
    named_tag, player_tag = _load_player_tag(raw_bytes)
    inventory, _original = nbt_to_json(player_tag)
    flags = protected_player_nbt_flags(player_tag)
    tag_names = set(player_tag.keys()) if hasattr(player_tag, "keys") else set()
    has_inventory_tag = "Inventory" in tag_names
    has_inventory = has_inventory_tag and isinstance(player_tag.get("Inventory"), nbt.ListTag)
    has_ender_chest_tag = "EnderChestInventory" in tag_names
    has_ender_chest = has_ender_chest_tag and isinstance(player_tag.get("EnderChestInventory"), nbt.ListTag)
    has_player_hints = bool(tag_names & (PLAYER_HINT_TAGS - {"Inventory", "EnderChestInventory"}))
    return {
        "inventory_count": len(inventory),
        "stats": extract_player_stats(player_tag),
        "root_tag_type": type(named_tag.tag).__name__,
        "has_inventory": has_inventory,
        "has_inventory_tag": has_inventory_tag,
        "has_player_hints": has_player_hints,
        "inventory_opaque": has_inventory_tag and not has_inventory,
        "inventory_create_requires_confirmation": (not has_inventory_tag) and (has_player_hints or has_ender_chest),
        "inventory_will_be_created": False,
        "has_ender_chest": has_ender_chest,
        "has_ender_chest_tag": has_ender_chest_tag,
        "ender_chest_opaque": has_ender_chest_tag and not has_ender_chest,
        "protected_nbt": flags,
    }


def evaluate_player_import_preview(preview: dict) -> dict:
    """Return one shared importability decision for preview and import.

    A complete player export may be safely identified by either inventory
    container or by other player-shaped NBT hints.  Unknown container tag types
    make the complete record read-only because imports replace the complete
    Player-NBT payload.
    """

    protected_nbt = preview.get("protected_nbt") if isinstance(preview.get("protected_nbt"), dict) else {}
    inventory_opaque = bool(preview.get("inventory_opaque") or protected_nbt.get("inventory_opaque"))
    ender_chest_opaque = bool(preview.get("ender_chest_opaque") or protected_nbt.get("ender_chest_opaque"))
    has_inventory_tag = bool(preview.get("has_inventory_tag"))
    has_ender_chest_tag = bool(preview.get("has_ender_chest_tag"))
    has_player_hints = bool(preview.get("has_player_hints"))
    has_player_shape = has_inventory_tag or has_ender_chest_tag or has_player_hints
    importable = has_player_shape and not inventory_opaque and not ender_chest_opaque

    if inventory_opaque:
        message = "Nicht importierbar: Der Export enthält einen Inventory-Tag mit unbekanntem NBT-Typ."
        reason_code = "inventory_opaque"
    elif ender_chest_opaque:
        message = "Nicht importierbar: Der Export enthält einen EnderChestInventory-Tag mit unbekanntem NBT-Typ."
        reason_code = "ender_chest_opaque"
    elif preview.get("has_inventory"):
        message = "Importierbar: Der Export enthält einen vollständigen Inventory-Tag."
        reason_code = "inventory"
    elif preview.get("has_ender_chest"):
        message = "Importierbar: Der Export enthält einen vollständigen EnderChestInventory-Tag."
        reason_code = "ender_chest"
    elif importable:
        message = (
            "Importierbar: Der Export enthält keinen Inventory-Tag; ein neuer Inventory-Tag wird später nur "
            "nach ausdrücklicher Bestätigung und nur bei echten Inventar-Items angelegt."
        )
        reason_code = "player_hints"
    else:
        message = "Nicht importierbar: Der Export enthält keine ausreichend sicheren Player-NBT-Hinweise."
        reason_code = "insufficient_player_shape"

    return {
        "importable": importable,
        "has_player_shape": has_player_shape,
        "inventory_opaque": inventory_opaque,
        "ender_chest_opaque": ender_chest_opaque,
        "reason_code": reason_code,
        "message": message,
    }


def player_export_dir_for_world(world_path):
    return os.path.join(os.path.dirname(os.path.normpath(world_path)), "player_exports")


def _normalized_path_id(path: str | os.PathLike) -> str:
    normalized = os.path.normcase(os.path.realpath(os.path.abspath(os.path.normpath(path))))
    return hashlib.sha256(normalized.encode("utf-8", errors="surrogatepass")).hexdigest()


def _player_import_token(world_path, export_path, *, size_bytes, sha256):
    return {
        "version": PLAYER_IMPORT_TOKEN_VERSION,
        "world_id": _normalized_path_id(world_path),
        "source_id": _normalized_path_id(export_path),
        "filename": os.path.basename(export_path),
        "size_bytes": size_bytes,
        "sha256": sha256,
    }


def _validated_player_import_token(token):
    if not isinstance(token, dict):
        raise PlayerImportPreviewStaleError("Spieler-Import abgelehnt: Die Import-Vorschau fehlt oder ist veraltet. Bitte Vorschau neu laden.")
    version = token.get("version")
    world_id = token.get("world_id")
    source_id = token.get("source_id")
    filename = token.get("filename")
    size_bytes = token.get("size_bytes")
    sha256 = token.get("sha256")
    if version != PLAYER_IMPORT_TOKEN_VERSION:
        raise PlayerImportPreviewStaleError("Spieler-Import abgelehnt: Die Import-Vorschau hat ein unbekanntes Format. Bitte Vorschau neu laden.")
    for value in (world_id, source_id, sha256):
        if not isinstance(value, str) or len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
            raise PlayerImportPreviewStaleError("Spieler-Import abgelehnt: Die Import-Vorschau ist ungültig. Bitte Vorschau neu laden.")
    if not isinstance(filename, str) or not filename:
        raise PlayerImportPreviewStaleError("Spieler-Import abgelehnt: Die Import-Vorschau ist ungültig. Bitte Vorschau neu laden.")
    if isinstance(size_bytes, bool) or not isinstance(size_bytes, int) or size_bytes < 0:
        raise PlayerImportPreviewStaleError("Spieler-Import abgelehnt: Die Import-Vorschau ist ungültig. Bitte Vorschau neu laden.")
    return {
        "version": version,
        "world_id": world_id,
        "source_id": source_id,
        "filename": filename,
        "size_bytes": size_bytes,
        "sha256": sha256,
    }


def _path_is_inside_or_same(path: str | os.PathLike, root: str | os.PathLike) -> bool:
    try:
        normalized_path = os.path.normcase(os.path.realpath(os.path.abspath(os.path.normpath(path))))
        normalized_root = os.path.normcase(os.path.realpath(os.path.abspath(os.path.normpath(root))))
        return os.path.commonpath([normalized_root, normalized_path]) == normalized_root
    except (OSError, ValueError):
        return False


def snapshot_player_export_for_import(export_zip, target_world_path, *, expected_token=None):
    """Copy one validated export source to an immutable private snapshot.

    Preview and import both parse a snapshot created from one open file handle.
    The import additionally compares the copied bytes with the preview token, so
    replacing the user-visible ZIP after confirmation cannot change the data.
    """

    if not export_zip:
        raise ValueError("Spieler-Export existiert nicht.")
    source_path = os.path.abspath(os.path.normpath(export_zip))
    normalized_token = _validated_player_import_token(expected_token) if expected_token is not None else None
    if normalized_token is not None:
        if not secrets.compare_digest(normalized_token["world_id"], _normalized_path_id(target_world_path)):
            raise PlayerImportPreviewStaleError("Spieler-Import abgelehnt: Die Zielwelt wurde seit der Vorschau gewechselt. Bitte Vorschau neu laden.")
        if not secrets.compare_digest(normalized_token["source_id"], _normalized_path_id(source_path)):
            raise PlayerImportPreviewStaleError(
                "Spieler-Import abgelehnt: Die ausgewählte Exportdatei stimmt nicht mehr mit der Vorschau überein. Bitte Vorschau neu laden."
            )
        if normalized_token["filename"] != os.path.basename(source_path):
            raise PlayerImportPreviewStaleError(
                "Spieler-Import abgelehnt: Die ausgewählte Exportdatei stimmt nicht mehr mit der Vorschau überein. Bitte Vorschau neu laden."
            )

    try:
        source_stat = os.stat(source_path, follow_symlinks=False)
    except OSError as exc:
        raise ValueError(f"Spieler-Export kann nicht gelesen werden: {exc}") from exc
    if not stat.S_ISREG(source_stat.st_mode):
        raise ValueError("Spieler-Export ist keine reguläre Datei.")

    export_root = os.path.abspath(os.path.normpath(player_export_dir_for_world(target_world_path)))
    os.makedirs(export_root, exist_ok=True)
    snapshot_dir = os.path.join(export_root, ".import_sources")
    os.makedirs(snapshot_dir, exist_ok=True)
    if os.path.islink(snapshot_dir) or not _path_is_inside_or_same(snapshot_dir, export_root):
        raise ValueError("Temporärer Import-Ordner ist unsicher.")

    fd, snapshot_path = tempfile.mkstemp(prefix="player_import_source_", suffix=".zip", dir=snapshot_dir)
    try:
        with open(source_path, "rb") as source, os.fdopen(fd, "wb") as snapshot:
            # fdopen owns and closes the descriptor from this point onward.
            # Invalidate our raw handle before any operation in the with-body can
            # fail, so cleanup can never close a descriptor number reused elsewhere.
            fd = -1
            if not os.path.samestat(source_stat, os.fstat(source.fileno())):
                raise ValueError("Spieler-Export wurde während der Import-Vorbereitung ersetzt.")
            digest = hashlib.sha256()
            size_bytes = 0
            while chunk := source.read(1024 * 1024):
                snapshot.write(chunk)
                digest.update(chunk)
                size_bytes += len(chunk)
            snapshot.flush()
            os.fsync(snapshot.fileno())
        actual_token = _player_import_token(
            target_world_path,
            source_path,
            size_bytes=size_bytes,
            sha256=digest.hexdigest(),
        )
        if normalized_token is not None and (
            normalized_token["size_bytes"] != actual_token["size_bytes"] or not secrets.compare_digest(normalized_token["sha256"], actual_token["sha256"])
        ):
            raise PlayerImportPreviewStaleError("Spieler-Import abgelehnt: Die Exportdatei wurde seit der Vorschau verändert. Bitte Vorschau neu laden.")
        return snapshot_path, actual_token
    except Exception as exc:
        if fd >= 0:
            with contextlib.suppress(OSError):
                os.close(fd)
        try:
            os.remove(snapshot_path)
        except OSError as cleanup_exc:
            warning = t("Temporärer Import-Snapshot konnte nicht entfernt werden: {path} ({error})", path=snapshot_path, error=cleanup_exc)
            existing = getattr(exc, "cleanup_warning", None)
            exc.cleanup_warning = f"{existing} {warning}" if existing else warning
            exc.source_snapshot_path = snapshot_path
            LOGGER.exception("Temporärer Import-Snapshot konnte nach einem Fehler nicht entfernt werden: %s", snapshot_path)
        raise


def _verify_player_export_archive(path: str) -> None:
    """Verify the CRCs and required members of a completed player export."""

    try:
        with zipfile.ZipFile(path, "r") as archive:
            names = set(archive.namelist())
            missing = {"manifest.json", "preview.json", "player.nbt"} - names
            if missing:
                raise ValueError("Spieler-Export ist unvollständig: " + ", ".join(sorted(missing)))
            bad_member = archive.testzip()
    except zipfile.BadZipFile as exc:
        raise ValueError("Spieler-Export konnte nicht vollständig erstellt werden.") from exc
    except OSError as exc:
        raise ValueError(t("Spieler-Export konnte nicht geprüft werden: {error}", error=exc)) from exc
    if bad_member is not None:
        raise ValueError(t("Spieler-Export ist beschädigt (CRC-Fehler): {member}", member=bad_member))


def _publish_player_export_no_clobber(temp_path: str, output_dir: str, safe_label: str, timestamp: str) -> str:
    """Publish a completed player export without overwriting another export."""

    _verify_player_export_archive(temp_path)

    unsupported = {errno.EPERM, errno.EXDEV}
    for name in ("ENOTSUP", "EOPNOTSUPP"):
        value = getattr(errno, name, None)
        if value is not None:
            unsupported.add(value)

    for _attempt in range(32):
        export_path = os.path.join(
            output_dir,
            f"{safe_label}_{timestamp}_{secrets.token_hex(8)}.mcbe-player.zip",
        )
        try:
            os.link(temp_path, export_path)
        except FileExistsError:
            continue
        except OSError as exc:
            if exc.errno not in unsupported:
                raise
            try:
                fd = os.open(export_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                continue
            try:
                with os.fdopen(fd, "wb") as target, open(temp_path, "rb") as source:
                    shutil.copyfileobj(source, target, length=1024 * 1024)
                    target.flush()
                    os.fsync(target.fileno())
                _verify_player_export_archive(export_path)
            except BaseException:
                with contextlib.suppress(OSError):
                    os.remove(export_path)
                raise
        with contextlib.suppress(OSError):
            os.remove(temp_path)
        return export_path
    raise RuntimeError("Spieler-Export konnte nicht kollisionsfrei veröffentlicht werden.")


def create_player_export(world_path, player, raw_bytes, output_dir=None):
    output_dir = output_dir or player_export_dir_for_world(world_path)
    os.makedirs(output_dir, exist_ok=True)

    now = datetime.now(UTC)
    timestamp = now.strftime("%Y-%m-%d_%H-%M-%S-%f")
    safe_label = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in player["label"])[:48].strip("_") or "player"
    preview = player_preview_from_bytes(raw_bytes)
    manifest = {
        "format": EXPORT_FORMAT,
        "version": EXPORT_VERSION,
        "created_at": now.isoformat(),
        "source_world_name": get_world_name(world_path),
        "player": player,
        "nbt": {
            "byte_length": len(raw_bytes),
            "root_tag_type": preview["root_tag_type"],
        },
    }

    fd, temp_path = tempfile.mkstemp(prefix=f".{safe_label}_", suffix=".tmp", dir=output_dir)
    os.close(fd)
    try:
        with zipfile.ZipFile(temp_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            zipf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            zipf.writestr("preview.json", json.dumps(preview, ensure_ascii=False, indent=2))
            zipf.writestr("player.nbt", raw_bytes)
        export_path = _publish_player_export_no_clobber(temp_path, output_dir, safe_label, timestamp)
    except Exception:
        with contextlib.suppress(OSError):
            os.remove(temp_path)
        raise

    return export_path


def _safe_export_member_name(name: str) -> str:
    if not name or "\0" in name or "\\" in name:
        raise ValueError(f"unsichere Pfadangabe im Spieler-Export: {name}")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise ValueError(f"unsichere Pfadangabe im Spieler-Export: {name}")
    return str(path)


def read_player_export(export_zip):
    if not export_zip or not os.path.isfile(export_zip):
        raise ValueError("Spieler-Export existiert nicht.")

    try:
        zipf_ctx = zipfile.ZipFile(export_zip, "r")
    except zipfile.BadZipFile as exc:
        raise ValueError("Spieler-Export ist keine gültige ZIP-Datei oder ist beschädigt.") from exc
    except OSError as exc:
        raise ValueError(f"Spieler-Export kann nicht gelesen werden: {exc}") from exc

    with zipf_ctx as zipf:
        infos = zipf.infolist()
        if len(infos) > MAX_EXPORT_MEMBERS:
            raise ValueError(t("Spieler-Export enthält zu viele Dateien (max {limit}).", limit=MAX_EXPORT_MEMBERS))
        all_names = [_safe_export_member_name(info.filename) for info in infos]
        normalized_names = {os.path.normcase(os.path.normpath(name)) for name in all_names}
        names_set = set(all_names)
        if len(normalized_names) != len(all_names):
            raise ValueError("Spieler-Export enthält doppelte Dateinamen.")
        if any(info.flag_bits & 0x1 for info in infos):
            raise ValueError("Verschlüsselte Spieler-Export-ZIP-Einträge werden nicht unterstützt.")
        required = {"manifest.json", "preview.json", "player.nbt"}
        missing = required - names_set
        if missing:
            raise ValueError(t("Spieler-Export ist unvollständig: {missing}", missing=", ".join(sorted(missing))))

        total_uncompressed = sum(m.file_size for m in infos)
        if total_uncompressed > MAX_EXPORT_UNCOMPRESSED_MB * 1024 * 1024:
            raise ValueError(t("Spieler-Export überschreitet maximal {limit} MB unkomprimiert.", limit=MAX_EXPORT_UNCOMPRESSED_MB))

        try:
            manifest = json.loads(zipf.read("manifest.json").decode("utf-8"))
            preview = json.loads(zipf.read("preview.json").decode("utf-8"))
            raw_bytes = zipf.read("player.nbt")
        except (KeyError, UnicodeDecodeError, json.JSONDecodeError, RecursionError, zipfile.BadZipFile) as exc:
            raise ValueError("Spieler-Export enthält ungültige oder beschädigte Daten.") from exc

    if not isinstance(manifest, dict) or not isinstance(preview, dict):
        raise ValueError("Spieler-Export enthält ungültige JSON-Metadaten.")
    if manifest.get("format") != EXPORT_FORMAT or manifest.get("version") != EXPORT_VERSION:
        raise ValueError("Spieler-Export hat ein nicht unterstütztes Format.")
    nbt_metadata = manifest.get("nbt")
    if not isinstance(nbt_metadata, dict):
        raise ValueError("Spieler-Export enthält ungültige NBT-Metadaten.")
    if nbt_metadata.get("byte_length") != len(raw_bytes):
        raise ValueError("Spieler-Export ist inkonsistent: NBT-Länge passt nicht zum Manifest.")

    try:
        player_preview_from_bytes(raw_bytes)
    except Exception as exc:
        raise ValueError("Spieler-Export enthält ungültige NBT-Spielerdaten.") from exc
    return manifest, preview, raw_bytes
