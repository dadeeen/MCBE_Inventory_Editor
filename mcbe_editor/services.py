import contextlib
import hashlib
import logging
import os

import amulet_nbt as nbt

from mcbe_editor.item_availability import item_availability_client_payload
from mcbe_editor.item_data import (
    ADDABLE_ITEM_IDS,
    BLOCK_ITEM_IDS,
    BLOCK_ONLY_ITEM_IDS,
    COMPAT_ITEM_ALIASES,
    DEFAULT_MAX_STACK,
    DURABILITY,
    EFFECTS,
    ENCHANTMENT_COMPATIBILITY,
    ITEM_COMPONENTS,
    MAX_DATA_VALUE,
    STACK_LIMITS,
)

from .backup import (
    BACKUP_KIND_MANUAL,
    BACKUP_KIND_PRE_RESTORE,
    RETENTION_RECOVERY,
    create_backup,
    delete_backup,
    get_backups_dir,
    prune_backups,
    remove_backup_after_aborted_write,
    resolve_backup_path,
    snapshot_backup_for_restore,
)
from .backup import list_backups as scan_backups
from .backup import preview_backup as preview_world_backup
from .backup import restore_backup as restore_world_backup
from .bedrock_nbt import load_player_nbt, save_player_nbt
from .compatibility import analyze_player_compatibility, analyze_world_structure, assert_serialized_player_roundtrip
from .config import load_config
from .db import LevelDbAdapter, close_db_preserving_active_exception
from .i18n import t
from .inventory import (
    _item_source_matches,
    apply_abilities,
    apply_effects,
    apply_player_stats,
    build_ender_chest_nbt,
    build_inventory_nbt,
    count_hidden_unknown_slots,
    extract_player_stats,
    items_by_slot_for_origin,
    nbt_to_json,
    parse_abilities,
    parse_effects,
    parse_ender_chest,
    protected_player_nbt_flags,
)
from .leveldb_readonly import ReadonlyLevelDbAdapter
from .player_state_transfer import (
    PLAYER_STATE_TRANSFER_SCHEMA_VERSION,
    build_player_state_transfer_plan,
    merge_player_state,
    transfer_policy_id,
    validate_player_state_transfer,
)
from .players import (
    PlayerScanner,
    classify_player_record,
    create_player_export,
    decode_player_key,
    encode_player_key,
    evaluate_player_import_preview,
    player_preview_from_bytes,
    read_player_export,
    snapshot_player_export_for_import,
)
from .root_equipment import (
    apply_root_equipment_writes,
    filter_read_only_root_equipment_payload,
    filter_root_equipment_presence_flags,
    merge_root_equipment_fallbacks,
    merge_root_equipment_protected_slots,
    reject_root_equipment_fallback_slot_writes,
    root_equipment_original_items_by_slot,
    split_root_equipment_writes,
)
from .service_errors import (
    PlayerImportPreviewStaleError,
    PlayerImportRecordRollbackError,
    PlayerImportRolledBackError,
    PlayerStateTransferPreviewStaleError,
    PlayerStateTransferRollbackError,
    PlayerStateTransferRolledBackError,
    denied_write_actor,
    denied_write_permission_hint,
)
from .world import LOCAL_PLAYER_KEY, detect_capabilities, ensure_valid_world_path, get_world_name
from .world_locks import get_world_lock, lock_key, locked_world

LOGGER = logging.getLogger(__name__)


class BedrockEditorService:
    def __init__(
        self,
        items_db,
        enchantments_db,
        db_factory=LevelDbAdapter,
        readonly_db_factory=ReadonlyLevelDbAdapter,
    ):
        self.items_db = items_db
        self.enchantments_db = enchantments_db
        self.db_factory = db_factory
        self.readonly_db_factory = readonly_db_factory

    @staticmethod
    def _lock_key(world_path: str) -> str:
        return lock_key(world_path)

    @staticmethod
    def _get_world_lock(world_path: str):
        return get_world_lock(world_path)

    def _locked_world(self, world_path: str):
        return locked_world(world_path)

    def _open_db(self, world_path):
        db_path = ensure_valid_world_path(world_path)
        return self.db_factory(db_path)

    def _open_db_readonly(self, world_path):
        """Open the world database without mutating it.

        The pure-Python readonly reader never touches LOCK/MANIFEST/WAL, so
        browsing worlds leaves them byte-identical.  Tests can inject a
        readonly_db_factory, but real read paths never fall back to the
        mutating LevelDB engine.
        """

        db_path = ensure_valid_world_path(world_path)
        try:
            return self.readonly_db_factory(db_path)
        except Exception as exc:
            LOGGER.warning("Readonly-Reader konnte %s nicht öffnen.", db_path, exc_info=True)
            raise RuntimeError("Readonly-LevelDB konnte nicht geöffnet werden. Die Welt wurde nicht mit dem mutierenden LevelDB-Adapter geöffnet.") from exc

    def _read_player(self, db, player_key):
        try:
            return db.get(player_key)
        except KeyError as exc:
            raise ValueError("Der ausgewählte Spieler wurde in dieser Welt nicht gefunden.") from exc

    @staticmethod
    def _player_revision(player_bytes: bytes) -> str:
        # Content revision for optimistic concurrency.  It lets several browser
        # clients share the same Docker webservice without silent last-writer-wins
        # overwrites.  The hash is stable and does not expose the NBT content.
        return hashlib.sha256(player_bytes).hexdigest()

    @staticmethod
    def _normalize_revision(value) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("Feld 'base_revision' muss ein Textwert sein.")
        value = value.strip().lower()
        if not value:
            return None
        if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
            raise ValueError("Ungültige Player-Revision. Bitte Spieler neu laden.")
        return value

    def _assert_player_revision_current(self, player_bytes: bytes, base_revision: str | None):
        expected = self._normalize_revision(base_revision)
        if not expected:
            raise ValueError("Speichern abgelehnt: Der geladene Spielerstand fehlt. Bitte Spieler neu laden.")
        current = self._player_revision(player_bytes)
        if current != expected:
            raise ValueError(
                "Speichern abgelehnt: Dieser Spieler wurde seit dem Laden geändert "
                "oder ein Backup wurde wiederhergestellt. Bitte Spieler neu laden und Änderungen erneut prüfen."
            )

    def _assert_import_target_revision_current(self, player_bytes: bytes, base_revision: str | None) -> None:
        expected = self._normalize_revision(base_revision)
        if expected and self._player_revision(player_bytes) == expected:
            return
        raise PlayerImportPreviewStaleError(
            t("Spieler-Import abgelehnt: Der geladene Zielspielerstand fehlt oder ist veraltet. Lade den Zielspieler neu und prüfe den Import erneut."),
            target_revision_stale=True,
        )

    def _get_player_info(self, db, player_key, *, players=None):
        if players is None:
            players = PlayerScanner(db).list_players()
        encoded_key = encode_player_key(player_key)
        for player in players:
            if player["player_key"] == encoded_key:
                return player
        raise ValueError("Der ausgewählte Datensatz wurde nicht als Spieler erkannt.")

    @staticmethod
    def _capabilities_for_players(world_path, players):
        capabilities = detect_capabilities(world_path)
        editable_players = [player for player in players if player.get("editable")]
        capabilities.update(
            {
                "supports_local_player": any(player.get("kind") == "local" for player in players),
                "supports_multiple_players": len(players) > 1,
                "write_mode": "selected_player" if editable_players else "read_only",
                "player_count": len(players),
                "editable_player_count": len(editable_players),
            }
        )
        return capabilities

    def _annotate_item_origins(self, items_by_slot, encoded_player_key, container_name):
        for item in items_by_slot.values():
            item["source_player_key"] = encoded_player_key
            item["source_container"] = container_name
        return items_by_slot

    @staticmethod
    def _item_source_digests(player_tag):
        inventory_data, _original_items = nbt_to_json(player_tag)
        merge_root_equipment_fallbacks(inventory_data, player_tag)
        ender_chest_data = parse_ender_chest(player_tag)

        def digest_map(items_by_slot):
            return {str(slot): item["source_item_digest"] for slot, item in items_by_slot.items() if isinstance(item.get("source_item_digest"), str)}

        return {
            "inventory": digest_map(inventory_data),
            "ender_chest": digest_map(ender_chest_data),
        }

    def _collect_external_source_items(self, db, target_world_path, target_player_key, *item_lists):
        """Resolve explicit same-world item origins used for player-crossing paste.

        The browser only sends editable JSON fields.  When a slot was copied from
        another player in the same world, source_player_key/source_container lets
        us copy that original item CompoundTag and mutate only the controlled
        fields, preserving add-on/future NBT data. Cross-world origins are
        rejected before any same-player source maps are added; unresolved or
        stale same-world origins fail closed in the inventory write policy.
        """

        target_encoded = encode_player_key(target_player_key)
        target_world_realpath = os.path.normcase(os.path.realpath(os.path.abspath(os.path.normpath(target_world_path))))
        requested = set()
        for item_list in item_lists:
            if not isinstance(item_list, list):
                continue
            for item in item_list:
                if not isinstance(item, dict):
                    continue
                source_key = str(item.get("source_player_key") or "").strip()
                source_container = str(item.get("source_container") or "").strip()
                source_world_path = str(item.get("source_world_path") or "").strip()
                if source_world_path:
                    source_world_realpath = os.path.normcase(os.path.realpath(os.path.abspath(os.path.normpath(source_world_path))))
                    if source_world_realpath != target_world_realpath:
                        raise ValueError(
                            t("Speichern abgelehnt: Item-Herkunft verweist auf eine andere Welt. Bitte das Item in der aktuellen Welt erneut kopieren.")
                        )
                if not source_key:
                    continue
                if source_container not in {"inventory", "ender_chest"}:
                    continue
                if source_key == target_encoded:
                    # Same-player origins are resolved from the already-loaded
                    # target player tag in save_player, including cross-container
                    # moves between Inventory and EnderChestInventory.
                    continue
                requested.add((source_key, source_container))

        source_item_maps = {}
        parsed_tags = {}
        for source_key, source_container in requested:
            try:
                raw_source_key = decode_player_key(source_key)
            except ValueError:
                continue
            if raw_source_key == target_player_key:
                continue
            if source_key not in parsed_tags:
                try:
                    source_bytes = self._read_player(db, raw_source_key)
                    parsed_tags[source_key] = load_player_nbt(source_bytes).tag
                except Exception:
                    continue
            tag = parsed_tags[source_key]
            source_items = self._source_items_for_container(tag, source_container)
            if source_items is None:
                continue
            source_item_maps[(source_key, source_container)] = source_items
        return source_item_maps

    @staticmethod
    def _source_items_for_container(player_tag, source_container):
        tag_name = "EnderChestInventory" if source_container == "ender_chest" else "Inventory"
        source_list_tag = player_tag.get(tag_name)
        if not isinstance(source_list_tag, nbt.ListTag):
            return None
        source_items = items_by_slot_for_origin(source_list_tag)
        if source_container == "inventory":
            # Ausrüstung aus editierbaren Root-Listen wird in der UI unter
            # den Slots 100-103/-106 geführt; für Player-übergreifendes
            # Einfügen muss das Original-NBT dort auflösbar sein.
            source_items = {**root_equipment_original_items_by_slot(player_tag), **source_items}
        return source_items

    def _assert_external_item_sources_current(self, db, source_checks) -> None:
        if not source_checks:
            return

        parsed_tags = {}
        source_maps = {}
        stale_message = t(
            "Speichern abgelehnt: Eine verwendete Item-Herkunft wurde während der Backup-Erstellung geändert. "
            "Bitte Spieler neu laden und das Item erneut kopieren oder verschieben."
        )
        for source_key, source_container, source_slot, expected_name, expected_digest in sorted(source_checks):
            try:
                if source_key not in parsed_tags:
                    raw_source_key = decode_player_key(source_key)
                    parsed_tags[source_key] = load_player_nbt(self._read_player(db, raw_source_key)).tag
                map_key = (source_key, source_container)
                if map_key not in source_maps:
                    source_maps[map_key] = self._source_items_for_container(parsed_tags[source_key], source_container)
                source_items = source_maps[map_key]
                source_item = source_items.get(source_slot) if source_items is not None else None
            except Exception as exc:
                raise ValueError(stale_message) from exc
            if not _item_source_matches(source_item, expected_name, expected_digest):
                raise ValueError(stale_message)

    def _items_by_slot_from_tag(self, player_tag, tag_name):
        source_list_tag = player_tag.get(tag_name)
        if not isinstance(source_list_tag, nbt.ListTag):
            return {}
        return items_by_slot_for_origin(source_list_tag)

    def list_players(self, world_path):
        db = None
        with self._locked_world(world_path):
            try:
                db = self._open_db_readonly(world_path)
                players = PlayerScanner(db).list_players()
                capabilities = self._capabilities_for_players(world_path, players)
                compatibility = analyze_world_structure(world_path)
                return {
                    "success": True,
                    "world_name": get_world_name(world_path),
                    "players": players,
                    "capabilities": capabilities,
                    "compatibility": compatibility,
                }
            finally:
                close_db_preserving_active_exception(db, context="Spielerliste laden")

    def load_world(self, world_path):
        return self.load_player(world_path, encode_player_key(LOCAL_PLAYER_KEY))

    def load_player(self, world_path, encoded_player_key):
        db = None
        with self._locked_world(world_path):
            try:
                db = self._open_db_readonly(world_path)
                player_key = decode_player_key(encoded_player_key)
                players = PlayerScanner(db).list_players()
                player_info = self._get_player_info(db, player_key, players=players)
                if not player_info["editable"]:
                    raise ValueError(f"Dieser Spieler ist read-only: {player_info['reason']}")
                player_bytes = self._read_player(db, player_key)
                player_named_tag = load_player_nbt(player_bytes)
                player_tag = player_named_tag.tag
                inventory_data, _ = nbt_to_json(player_tag)
                encoded_player_key = encode_player_key(player_key)
                self._annotate_item_origins(inventory_data, encoded_player_key, "inventory")
                root_equipment_slots = merge_root_equipment_fallbacks(
                    inventory_data,
                    player_tag,
                    encoded_player_key=encoded_player_key,
                    world_path=world_path,
                )
                protected_flags = filter_root_equipment_presence_flags(player_tag, protected_player_nbt_flags(player_tag))
                has_ender_chest = "EnderChestInventory" in player_tag and not protected_flags["ender_chest_opaque"]
                ender_chest_data = parse_ender_chest(player_tag)
                self._annotate_item_origins(ender_chest_data, encoded_player_key, "ender_chest")
                hidden_unknown_slots = merge_root_equipment_protected_slots(
                    count_hidden_unknown_slots(player_tag),
                    root_equipment_slots,
                )
                selectable_items_db = dict(self.items_db)
                for item_id in ADDABLE_ITEM_IDS:
                    alias_target = COMPAT_ITEM_ALIASES.get(item_id)
                    if item_id not in selectable_items_db and alias_target in self.items_db:
                        selectable_items_db[item_id] = self.items_db[alias_target]

                return {
                    "success": True,
                    "world_name": get_world_name(world_path),
                    "player": player_info,
                    "player_revision": self._player_revision(player_bytes),
                    "inventory": inventory_data,
                    "ender_chest": ender_chest_data,
                    "has_ender_chest": has_ender_chest,
                    "stats": extract_player_stats(player_tag),
                    "effects": parse_effects(player_tag),
                    "abilities": parse_abilities(player_tag),
                    "hidden_unknown_slots": hidden_unknown_slots,
                    "protected_nbt": protected_flags,
                    "compatibility": {
                        "world": analyze_world_structure(world_path),
                        "player": analyze_player_compatibility(player_tag, serialized_before=player_bytes),
                    },
                    "capabilities": self._capabilities_for_players(world_path, players),
                    "items_db": selectable_items_db,
                    "compat_item_aliases": COMPAT_ITEM_ALIASES,
                    "addable_items": sorted(ADDABLE_ITEM_IDS),
                    "block_only_items": sorted(BLOCK_ONLY_ITEM_IDS),
                    "block_items": sorted(BLOCK_ITEM_IDS),
                    "item_availability": item_availability_client_payload(),
                    "ench_db": {k: {"name_de": v[0], "name_en": v[1], "max_lvl": v[2]} for k, v in self.enchantments_db.items()},
                    "enchantment_compatibility": ENCHANTMENT_COMPATIBILITY,
                    "item_components": ITEM_COMPONENTS,
                    "effects_db": EFFECTS,
                    "stack_limits": {**STACK_LIMITS, "__default__": DEFAULT_MAX_STACK},
                    "max_damage": {**DURABILITY, "__default__": MAX_DATA_VALUE},
                }
            finally:
                close_db_preserving_active_exception(db, context="Spieler laden")

    def save_world(self, world_path, inventory_list, stats, base_revision=None):
        return self.save_player(world_path, encode_player_key(LOCAL_PLAYER_KEY), inventory_list, stats, base_revision=base_revision)

    def save_player(
        self,
        world_path,
        encoded_player_key,
        inventory_list,
        stats,
        ender_chest_list=None,
        effects_list=None,
        abilities_dict=None,
        base_revision=None,
        allow_create_inventory=False,
        allow_create_ender_chest=False,
        allow_create_effects=False,
        allow_create_abilities=False,
        root_equipment_editable=False,
        pre_write_check=None,
        extra_batch_builder=None,
        extra_batch_validator=None,
    ):
        with self._locked_world(world_path):
            ensure_valid_world_path(world_path)
            backup_file = None
            db = None
            write_attempted = False
            try:
                # Phase 1 (read-only): read, validate and serialize entirely in
                # memory.  Opening the mutating adapter is never free -- the
                # engine acquires LOCK, replays the write-ahead log into a fresh
                # SST and rewrites CURRENT/MANIFEST on every open.  Doing that
                # here would touch the world for saves that turn out to be a
                # no-op or that get rejected during validation, and it would
                # happen before create_backup() runs.  The readonly reader never
                # writes a byte, so phase 1 leaves the world untouched.
                db = self._open_db_readonly(world_path)
                player_key = decode_player_key(encoded_player_key)
                player_info = self._get_player_info(db, player_key)
                if not player_info["editable"]:
                    raise ValueError(f"Dieser Spieler ist read-only: {player_info['reason']}")
                player_bytes = self._read_player(db, player_key)
                self._assert_player_revision_current(player_bytes, base_revision)
                player_named_tag = load_player_nbt(player_bytes)
                player_tag = player_named_tag.tag
                original_inventory_data, _ = nbt_to_json(player_tag)
                inventory_list = filter_read_only_root_equipment_payload(inventory_list)
                ender_chest_list = filter_read_only_root_equipment_payload(ender_chest_list)
                inventory_list, root_equipment_items = split_root_equipment_writes(player_tag, inventory_list, original_inventory_data.keys())
                reject_root_equipment_fallback_slot_writes(player_tag, inventory_list, original_inventory_data.keys())

                source_item_maps = self._collect_external_source_items(db, world_path, player_key, inventory_list, ender_chest_list)
                used_external_source_checks = set()
                target_encoded_key = encode_player_key(player_key)
                root_equipment_originals = root_equipment_original_items_by_slot(player_tag)
                inventory_originals = self._items_by_slot_from_tag(player_tag, "Inventory")
                source_item_maps[(target_encoded_key, "inventory")] = {**root_equipment_originals, **inventory_originals}
                source_item_maps[(target_encoded_key, "ender_chest")] = self._items_by_slot_from_tag(player_tag, "EnderChestInventory")

                if inventory_list is not None:
                    has_inventory_tag = "Inventory" in player_tag
                    if has_inventory_tag and not isinstance(player_tag.get("Inventory"), nbt.ListTag):
                        raise ValueError("Speichern abgelehnt: Inventory-Tag hat einen unbekannten NBT-Typ und wird nicht ersetzt.")
                    if has_inventory_tag:
                        player_tag["Inventory"] = build_inventory_nbt(
                            player_tag,
                            inventory_list,
                            self.enchantments_db,
                            source_item_maps=source_item_maps,
                            target_player_key=target_encoded_key,
                            extra_original_items=root_equipment_originals,
                            used_external_source_checks=used_external_source_checks,
                        )
                    elif inventory_list:
                        if not allow_create_inventory:
                            raise ValueError(
                                "Speichern abgelehnt: Dieser Spieler hat keinen Inventory-Tag. "
                                "Ein neues Inventar würde den Player-NBT-Aufbau ändern und muss ausdrücklich bestätigt werden."
                            )
                        player_tag["Inventory"] = build_inventory_nbt(
                            player_tag,
                            inventory_list,
                            self.enchantments_db,
                            source_item_maps=source_item_maps,
                            target_player_key=target_encoded_key,
                            extra_original_items=root_equipment_originals,
                            used_external_source_checks=used_external_source_checks,
                        )
                    # else: Inventory fehlt und die UI sendet eine leere Liste.
                    # Bewusst nichts schreiben, damit ein normaler Save keine
                    # neue leere Inventory-Liste erzeugt. Auch allow_create_inventory
                    # legt ohne echte Items keine leere Liste an.
                    apply_root_equipment_writes(
                        player_tag,
                        root_equipment_items,
                        self.enchantments_db,
                        source_item_maps=source_item_maps,
                        target_player_key=target_encoded_key,
                        extra_original_items=inventory_originals,
                        # Ein Payload ohne Ausrüstungs-Items bedeutet nur dann
                        # "Slots leeren", wenn der Client die editierbaren
                        # Root-Listen kennt. Stale Clients löschen so nichts.
                        allow_clears=bool(root_equipment_editable),
                        used_external_source_checks=used_external_source_checks,
                    )
                if ender_chest_list is not None:
                    has_ec = "EnderChestInventory" in player_tag
                    if has_ec and not isinstance(player_tag.get("EnderChestInventory"), nbt.ListTag):
                        raise ValueError("Speichern abgelehnt: EnderChestInventory hat einen unbekannten NBT-Typ und wird nicht ersetzt.")
                    if has_ec:
                        player_tag["EnderChestInventory"] = build_ender_chest_nbt(
                            player_tag,
                            ender_chest_list,
                            self.enchantments_db,
                            source_item_maps=source_item_maps,
                            target_player_key=target_encoded_key,
                            used_external_source_checks=used_external_source_checks,
                        )
                    elif ender_chest_list:
                        if not allow_create_ender_chest:
                            raise ValueError(
                                "Speichern abgelehnt: Dieser Spieler hat keinen EnderChestInventory-Tag. "
                                "Eine neue Enderchest-Liste würde den Player-NBT-Aufbau ändern und muss ausdrücklich bestätigt werden."
                            )
                        player_tag["EnderChestInventory"] = build_ender_chest_nbt(
                            player_tag,
                            ender_chest_list,
                            self.enchantments_db,
                            source_item_maps=source_item_maps,
                            target_player_key=target_encoded_key,
                            used_external_source_checks=used_external_source_checks,
                        )
                    # else: EnderChestInventory fehlt und die UI sendet eine leere Liste.
                    # Bewusst nichts schreiben, damit ein normaler Save keine
                    # neue leere Enderchest-Liste erzeugt.
                if effects_list is not None:
                    has_effects_tag = "ActiveEffects" in player_tag
                    if has_effects_tag and not isinstance(player_tag.get("ActiveEffects"), nbt.ListTag):
                        raise ValueError("Speichern abgelehnt: ActiveEffects hat einen unbekannten NBT-Typ und wird nicht ersetzt.")
                    if not has_effects_tag and effects_list and not allow_create_effects:
                        raise ValueError(
                            "Speichern abgelehnt: Dieser Spieler hat keinen ActiveEffects-Tag. "
                            "Eine neue Effektliste würde den Player-NBT-Aufbau ändern und muss ausdrücklich bestätigt werden."
                        )
                if abilities_dict is not None:
                    has_abilities_tag = "abilities" in player_tag
                    if has_abilities_tag and not isinstance(player_tag.get("abilities"), nbt.CompoundTag):
                        raise ValueError("Speichern abgelehnt: abilities hat einen unbekannten NBT-Typ und wird nicht ersetzt.")
                    if not has_abilities_tag and abilities_dict and not allow_create_abilities:
                        raise ValueError(
                            "Speichern abgelehnt: Dieser Spieler hat keinen abilities-Tag. "
                            "Ein neuer Fähigkeiten-Compound würde den Player-NBT-Aufbau ändern und muss ausdrücklich bestätigt werden."
                        )

                apply_effects(player_tag, effects_list)
                apply_abilities(player_tag, abilities_dict)
                apply_player_stats(player_tag, stats)

                serialized_bytes = save_player_nbt(player_named_tag)
                assert_serialized_player_roundtrip(serialized_bytes)
                item_source_digests = self._item_source_digests(load_player_nbt(serialized_bytes).tag)
                player_changed = serialized_bytes != player_bytes
                if not player_changed and extra_batch_builder is None:
                    return {
                        "success": True,
                        "message": "Keine Änderungen erkannt. Es wurde kein Backup erstellt und nichts geschrieben.",
                        "backup_file": None,
                        "player_revision": self._player_revision(player_bytes),
                        "item_source_digests": item_source_digests,
                        "no_op": True,
                    }

                # Phase 2 (write): from here on the world is modified.  The
                # read-only handle is released first so the mutating adapter can
                # take LOCK, and the backup is created before anything opens the
                # world for writing.
                if db:
                    try:
                        close_db_preserving_active_exception(db, context="Spieler-Speichern: Readonly-Phase vor Backup-Erstellung")
                    finally:
                        db = None

                try:
                    backup_file = create_backup(world_path, prune_after=False)
                except PermissionError as exc:
                    raise ValueError(
                        t(
                            "Speichern abgelehnt: {actor} verweigert Zugriff beim Erstellen des Backups. Backup-Ordner: {backup_dir}. {hint}",
                            actor=denied_write_actor(),
                            backup_dir=get_backups_dir(world_path),
                            hint=denied_write_permission_hint(),
                        )
                    ) from exc
                try:
                    # Check immediately before opening the mutating adapter so a
                    # server that became unsafe during backup creation cannot
                    # trigger LOCK/MANIFEST/CURRENT changes. The check below
                    # stays the last gate before the write batch.
                    if pre_write_check:
                        pre_write_check()
                    db = self._open_db(world_path)
                    # The readonly reader is a best-effort snapshot and can see a
                    # torn state while another process writes.  Re-reading through
                    # the real engine and comparing against phase 1 makes any such
                    # drift -- and any external change during backup creation --
                    # fail closed instead of overwriting it.
                    current_player_bytes = self._read_player(db, player_key)
                    if current_player_bytes != player_bytes:
                        raise ValueError("Speichern abgelehnt: Der Spieler wurde während der Backup-Erstellung extern geändert. Bitte neu laden.")
                    if player_changed:
                        self._assert_external_item_sources_current(db, used_external_source_checks)
                    if pre_write_check:
                        pre_write_check()
                    extra_batch = extra_batch_builder(db, player_key) if extra_batch_builder else {}
                    extra_writes = dict(extra_batch.get("writes") or {})
                    if player_changed:
                        extra_writes[player_key] = serialized_bytes
                    if extra_batch_builder:
                        if not extra_writes:
                            raise ValueError("Speichern abgelehnt: Der gemeinsame Schreibplan ist leer.")
                        write_attempted = True
                        db.put_batch(extra_writes)
                    else:
                        write_attempted = True
                        db.put(player_key, serialized_bytes)
                except PermissionError as exc:
                    raise ValueError(
                        t(
                            "Speichern abgelehnt: {actor} verweigert Zugriff beim Schreiben der Welt-Datenbank. "
                            "Weltordner: {world_path}. Minecraft/Bedrock muss komplett geschlossen sein. {hint}",
                            actor=denied_write_actor(),
                            world_path=world_path,
                            hint=denied_write_permission_hint(),
                        )
                    ) from exc

                # Ab hier ist der Batch committed. Fehler beim Validator-Wrapper,
                # beim Schließen der DB, beim Bereinigen der Backups oder beim
                # Aufbau der Antwort dürfen den Schreibstatus nicht mehr in einen
                # scheinbar wiederholbaren Fehler verwandeln; die gemeinsame
                # Post-Write-Grenze meldet jede Ausnahme strukturiert.
                try:
                    post_write_errors: list[str] = []
                    if extra_batch_builder and extra_batch_validator:
                        try:
                            extra_batch_validator(db, extra_batch)
                        except Exception as exc:
                            post_write_errors.append(f"Nachvalidierung nach dem Schreiben fehlgeschlagen: {exc}")
                    try:
                        db.close()
                    except Exception as exc:
                        post_write_errors.append(f"Datenbank konnte nach dem Schreiben nicht sauber geschlossen werden: {exc}")
                    finally:
                        db = None
                    try:
                        prune_backups(world_path, keep_paths=[backup_file])
                    except Exception as exc:
                        post_write_errors.append(f"Alte Backups konnten nach dem Schreiben nicht bereinigt werden: {exc}")

                    result = {
                        "success": not post_write_errors,
                        "message": "Erfolgreich gespeichert!" if not post_write_errors else "; ".join(post_write_errors),
                        "backup_file": os.path.basename(backup_file),
                        "player_revision": self._player_revision(serialized_bytes),
                        "item_source_digests": item_source_digests,
                        "no_op": False,
                        "workspace": extra_batch.get("result") if extra_batch_builder else None,
                    }
                    if post_write_errors:
                        result.update(
                            {
                                "write_committed": True,
                                "validation_failed": True,
                                "error": (
                                    "Änderungen wurden geschrieben, aber der Abschluss nach dem Schreiben ist fehlgeschlagen. "
                                    "Nicht erneut speichern; stelle bei Zweifeln das angegebene Backup wieder her. " + "; ".join(post_write_errors)
                                ),
                            }
                        )
                    return result
                except Exception as exc:
                    # Unerwarteter Fehler nach dem Commit (z. B. beim Aufbau der
                    # Antwort). Der Batch ist geschrieben: strukturiert als
                    # Post-Write-Fehler melden, niemals als wiederholbaren 500.
                    with contextlib.suppress(Exception):
                        if db is not None:
                            db.close()
                    db = None
                    post_write_message = (
                        "Änderungen wurden geschrieben, aber der Abschluss nach dem Schreiben ist fehlgeschlagen. "
                        "Nicht erneut speichern; stelle bei Zweifeln das angegebene Backup wieder her."
                    )
                    return {
                        "success": False,
                        "write_committed": True,
                        "validation_failed": True,
                        "error_phase": "post_write",
                        "error": post_write_message,
                        "message": post_write_message,
                        "no_op": False,
                        "backup_file": os.path.basename(backup_file) if backup_file else None,
                        "item_source_digests": item_source_digests,
                        "post_write_error_detail": f"{type(exc).__name__}: {exc}",
                    }
            except Exception as exc:
                if backup_file and not write_attempted:
                    remove_backup_after_aborted_write(backup_file, exc, operation="player.save")
                raise
            finally:
                close_db_preserving_active_exception(db, context="Spieler-Speichern vor dem Commit")

    def compatibility_report(self, world_path, encoded_player_key=None):
        db = None
        with self._locked_world(world_path):
            try:
                ensure_valid_world_path(world_path)
                report = {"success": True, "world_name": get_world_name(world_path), "world": analyze_world_structure(world_path)}
                if encoded_player_key:
                    db = self._open_db_readonly(world_path)
                    player_key = decode_player_key(encoded_player_key)
                    player_bytes = self._read_player(db, player_key)
                    player_tag = load_player_nbt(player_bytes).tag
                    report["player"] = analyze_player_compatibility(player_tag, serialized_before=player_bytes)
                return report
            finally:
                close_db_preserving_active_exception(db, context="Kompatibilitätsbericht laden")

    @staticmethod
    def _state_transfer_player_summary(player_info: dict) -> dict:
        return {
            "player_key": player_info.get("player_key"),
            "label": player_info.get("label"),
            "kind": player_info.get("kind"),
            "editable": bool(player_info.get("editable")),
            "reason": player_info.get("reason"),
        }

    def _load_state_transfer_players(self, db, encoded_source_player_key, encoded_target_player_key):
        if not encoded_source_player_key or not encoded_target_player_key:
            raise ValueError(t("Zustandsübertragung abgelehnt: Quelle und Ziel müssen gewählt werden."))
        if encoded_source_player_key == encoded_target_player_key:
            raise ValueError(t("Zustandsübertragung abgelehnt: Quelle und Ziel müssen unterschiedliche Spieler sein."))

        source_key = decode_player_key(encoded_source_player_key)
        target_key = decode_player_key(encoded_target_player_key)
        players = PlayerScanner(db).list_players()
        source_info = self._get_player_info(db, source_key, players=players)
        target_info = self._get_player_info(db, target_key, players=players)
        if not source_info.get("editable"):
            raise ValueError(t("Quellspieler ist nicht sicher übertragbar: {reason}", reason=t(source_info.get("reason") or "Unbekannter Grund")))
        if not target_info.get("editable"):
            raise ValueError(t("Zielspieler ist read-only: {reason}", reason=t(target_info.get("reason") or "Unbekannter Grund")))
        if {source_info.get("kind"), target_info.get("kind")} != {"local", "remote"}:
            raise ValueError(t("Zustandsübertragung abgelehnt: Erlaubt ist nur zwischen vorhandenem lokalem Spieler und vorhandenem Multiplayer-Spieler."))

        source_raw = self._read_player(db, source_key)
        target_raw = self._read_player(db, target_key)
        return source_key, target_key, source_info, target_info, source_raw, target_raw

    def _state_transfer_token(self, world_path, source_info, target_info, source_raw, target_raw):
        return {
            "version": PLAYER_STATE_TRANSFER_SCHEMA_VERSION,
            "policy_id": transfer_policy_id(),
            "world_id": hashlib.sha256(self._lock_key(world_path).encode("utf-8")).hexdigest(),
            "source_player_key": source_info["player_key"],
            "target_player_key": target_info["player_key"],
            "source_revision": self._player_revision(source_raw),
            "target_revision": self._player_revision(target_raw),
        }

    def _assert_state_transfer_token_current(
        self,
        token,
        world_path,
        source_info,
        target_info,
        source_raw,
        target_raw,
    ):
        if not isinstance(token, dict):
            raise PlayerStateTransferPreviewStaleError(t("Spielermigration abgelehnt: Die Vorschau fehlt oder ist veraltet. Bitte Migration erneut prüfen."))
        expected = self._state_transfer_token(world_path, source_info, target_info, source_raw, target_raw)
        if any(token.get(key) != value for key, value in expected.items()):
            raise PlayerStateTransferPreviewStaleError(
                t("Spielermigration abgelehnt: Welt, Quelle oder Ziel haben sich seit der Vorschau geändert. Bitte Migration erneut prüfen.")
            )

    def preview_player_state_transfer(self, world_path, encoded_source_player_key, encoded_target_player_key):
        db = None
        with self._locked_world(world_path):
            try:
                ensure_valid_world_path(world_path)
                db = self._open_db_readonly(world_path)
                _source_key, _target_key, source_info, target_info, source_raw, target_raw = self._load_state_transfer_players(
                    db,
                    encoded_source_player_key,
                    encoded_target_player_key,
                )
                source_tag = load_player_nbt(source_raw).tag
                target_tag = load_player_nbt(target_raw).tag
                plan = build_player_state_transfer_plan(source_tag, target_tag)
                token = self._state_transfer_token(world_path, source_info, target_info, source_raw, target_raw)
                direction = "local_to_multiplayer" if source_info.get("kind") == "local" else "multiplayer_to_local"
                return {
                    "success": True,
                    "mode": "safe_state_transfer",
                    "direction": direction,
                    "source_player": self._state_transfer_player_summary(source_info),
                    "target_player": self._state_transfer_player_summary(target_info),
                    "transfer_token": token,
                    "plan": plan,
                    "safety": {
                        "writes_selected_world": True,
                        "source_record_preserved": True,
                        "target_key_preserved": True,
                        "target_identity_fields_preserved": True,
                        "unknown_target_root_fields_preserved": True,
                        "unknown_target_ability_attribute_fields_preserved": True,
                        "recipe_unlocks_merged_without_removing_target_recipes": True,
                        "reviewed_vanilla_attributes_transferred": True,
                        "last_death_state_transferred_atomically": True,
                        "unknown_source_root_fields_skipped": True,
                        "unknown_source_ability_attribute_fields_skipped": True,
                        "external_entity_ownership_transferred": False,
                        "backup_before_write": True,
                        "post_write_validation": True,
                        "target_record_rollback_on_failure": True,
                    },
                }
            finally:
                close_db_preserving_active_exception(db, context="Spielermigration prüfen")

    def _rollback_player_state_transfer(self, world_path, target_key, target_before_raw, transferred_raw):
        failures = []
        db = None
        current_target = None
        try:
            db = self._open_db_readonly(world_path)
            current_target = self._read_player(db, target_key)
        except Exception as exc:
            failures.append((t("Aktueller Zielzustand konnte vor dem Rollback nicht gelesen werden"), exc))
        finally:
            if db:
                try:
                    db.close()
                except Exception as exc:
                    failures.append((t("Readonly-Datenbank konnte vor dem Rollback nicht geschlossen werden"), exc))
                finally:
                    db = None

        if failures:
            return failures, False
        rollback_required = current_target != target_before_raw
        if rollback_required:
            if current_target != transferred_raw:
                return (
                    [
                        (
                            t("Zielzustand wurde nach dem Migrationsschreibversuch extern verändert"),
                            ValueError(t("Automatischer Rollback würde neuere Zieldaten überschreiben.")),
                        )
                    ],
                    False,
                )
            try:
                db = self._open_db(world_path)
                db.put(target_key, target_before_raw)
            except Exception as exc:
                failures.append((t("Vorheriger Zielzustand konnte nicht zurückgeschrieben werden"), exc))
            finally:
                if db:
                    try:
                        db.close()
                    except Exception as exc:
                        failures.append((t("Datenbank konnte nach dem Rollback nicht geschlossen werden"), exc))
                    finally:
                        db = None

        try:
            db = self._open_db_readonly(world_path)
            if self._read_player(db, target_key) != target_before_raw:
                failures.append(
                    (t("Zurückgeschriebener Zielzustand stimmt nicht mit dem Zustand vor der Migration überein"), ValueError(t("Bytevergleich fehlgeschlagen")))
                )
        except Exception as exc:
            failures.append((t("Rollback konnte nicht nachvalidiert werden"), exc))
        finally:
            if db:
                try:
                    db.close()
                except Exception as exc:
                    failures.append((t("Readonly-Datenbank konnte nach dem Rollback nicht geschlossen werden"), exc))
                finally:
                    db = None
        return failures, rollback_required

    def transfer_player_state(
        self,
        world_path,
        encoded_source_player_key,
        encoded_target_player_key,
        *,
        confirm_transfer=False,
        transfer_token=None,
        write_gate_check=None,
    ):
        if not confirm_transfer:
            raise ValueError(t("Spielermigration blockiert: Die Übertragung muss ausdrücklich bestätigt werden."))

        backup_file = None
        db = None
        source_key = None
        target_key = None
        source_raw = None
        target_raw = None
        merged_raw = None
        write_attempted = False
        with self._locked_world(world_path):
            ensure_valid_world_path(world_path)
            try:
                db = self._open_db_readonly(world_path)
                source_key, target_key, source_info, target_info, source_raw, target_raw = self._load_state_transfer_players(
                    db,
                    encoded_source_player_key,
                    encoded_target_player_key,
                )
                self._assert_state_transfer_token_current(
                    transfer_token,
                    world_path,
                    source_info,
                    target_info,
                    source_raw,
                    target_raw,
                )
                preview_plan = build_player_state_transfer_plan(load_player_nbt(source_raw).tag, load_player_nbt(target_raw).tag)
            finally:
                if db:
                    try:
                        close_db_preserving_active_exception(db, context="Spielermigration vorbereiten")
                    finally:
                        db = None

            try:
                if write_gate_check is not None:
                    write_gate_check()
                backup_file = create_backup(world_path, prune_after=False)
                if write_gate_check is not None:
                    write_gate_check()

                db = self._open_db(world_path)
                current_source = self._read_player(db, source_key)
                current_target = self._read_player(db, target_key)
                if current_source != source_raw or current_target != target_raw:
                    raise PlayerStateTransferPreviewStaleError(
                        t("Spielermigration abgelehnt: Quelle oder Ziel wurden während der Backup-Erstellung geändert. Bitte Migration erneut prüfen.")
                    )
                merged_raw, applied_plan = merge_player_state(current_source, current_target)
                if applied_plan["policy_id"] != preview_plan["policy_id"]:
                    raise PlayerStateTransferPreviewStaleError(t("Spielermigration abgelehnt: Die Feldrichtlinie hat sich seit der Vorschau geändert."))
                assert_serialized_player_roundtrip(merged_raw)
                if write_gate_check is not None:
                    write_gate_check()
                write_attempted = True
                db.put(target_key, merged_raw)
                try:
                    close_db_preserving_active_exception(db, context="Spielermigration schreiben")
                finally:
                    db = None

                db = self._open_db_readonly(world_path)
                source_after = self._read_player(db, source_key)
                target_after = self._read_player(db, target_key)
                validation = validate_player_state_transfer(
                    source_raw,
                    target_raw,
                    target_after,
                    source_after_raw=source_after,
                    expected_plan=preview_plan,
                )
                resulting_info = classify_player_record(target_key, target_after)
                if not resulting_info or not resulting_info.get("editable") or resulting_info.get("kind") != target_info.get("kind"):
                    raise ValueError(t("Nachvalidierung fehlgeschlagen: Die Zielidentität ist nicht mehr sicher erkennbar."))
                try:
                    close_db_preserving_active_exception(db, context="Spielermigration nachvalidieren")
                finally:
                    db = None
            except Exception as exc:
                close_failures = []
                if db:
                    try:
                        db.close()
                    except Exception as close_exc:
                        close_failures.append((t("Datenbank konnte vor dem Migrations-Rollback nicht geschlossen werden"), close_exc))
                    finally:
                        db = None
                if write_attempted:
                    rollback_failures, rollback_performed = self._rollback_player_state_transfer(
                        world_path,
                        target_key,
                        target_raw,
                        merged_raw,
                    )
                    rollback_failures = close_failures + rollback_failures
                    if rollback_failures:
                        raise PlayerStateTransferRollbackError(
                            exc,
                            backup_file=backup_file,
                            rollback_failures=rollback_failures,
                        ) from exc
                    if rollback_performed:
                        raise PlayerStateTransferRolledBackError(exc, backup_file=backup_file) from exc
                remove_backup_after_aborted_write(backup_file, exc, operation="player.state_transfer")
                raise

            cleanup_warning = None
            try:
                prune_backups(world_path, keep_paths=[backup_file])
            except Exception as exc:
                cleanup_warning = t("Migration war erfolgreich, alte Backups konnten aber nicht bereinigt werden: {error}", error=exc)
                LOGGER.exception("Backup-Retention nach erfolgreicher Spielermigration fehlgeschlagen.")

            result = {
                "success": True,
                "write_committed": True,
                "world_path": world_path,
                "backup_file": os.path.basename(backup_file),
                "source_player": self._state_transfer_player_summary(source_info),
                "target_player": self._state_transfer_player_summary(target_info),
                "direction": "local_to_multiplayer" if source_info.get("kind") == "local" else "multiplayer_to_local",
                "plan": applied_plan,
                "validation": validation,
                "source_deleted": False,
                "world_changed": True,
            }
            if cleanup_warning:
                result["cleanup_warning"] = cleanup_warning
            return result

    def export_player(self, world_path, encoded_player_key):
        db = None
        with self._locked_world(world_path):
            try:
                db = self._open_db_readonly(world_path)
                player_key = decode_player_key(encoded_player_key)
                player_info = self._get_player_info(db, player_key)
                if not player_info["exportable"]:
                    raise ValueError(f"Dieser Spieler kann nicht exportiert werden: {player_info['reason']}")
                raw_bytes = self._read_player(db, player_key)
            finally:
                close_db_preserving_active_exception(db, context="Spieler exportieren")

        export_path = create_player_export(world_path, player_info, raw_bytes)
        return {
            "success": True,
            "export_path": export_path,
            "player": player_info,
        }

    @staticmethod
    def _read_optional_player(db, player_key):
        try:
            return db.get(player_key)
        except KeyError:
            return None

    def _rollback_player_import(self, world_path, target_key, target_before_raw, imported_raw):
        failures = []
        db = None
        current_target = None
        try:
            db = self._open_db_readonly(world_path)
            current_target = self._read_optional_player(db, target_key)
        except Exception as exc:
            failures.append((t("Aktueller Zielzustand konnte vor dem Import-Rollback nicht gelesen werden"), exc))
        finally:
            if db:
                try:
                    db.close()
                except Exception as exc:
                    failures.append((t("Readonly-Datenbank konnte vor dem Import-Rollback nicht geschlossen werden"), exc))
                finally:
                    db = None

        if failures:
            return failures, False
        rollback_required = current_target != target_before_raw
        if rollback_required:
            if current_target != imported_raw:
                return (
                    [
                        (
                            t("Zielzustand wurde nach dem Importschreibversuch extern verändert"),
                            ValueError(t("Automatischer Rollback würde neuere Zieldaten überschreiben.")),
                        )
                    ],
                    False,
                )
            try:
                db = self._open_db(world_path)
                if target_before_raw is None:
                    db.put_batch({target_key: None})
                else:
                    db.put(target_key, target_before_raw)
            except Exception as exc:
                action = (
                    t("Neu angelegter Spieler-Key konnte nicht entfernt werden")
                    if target_before_raw is None
                    else t("Vorheriger Zielzustand konnte nicht zurückgeschrieben werden")
                )
                failures.append((action, exc))
            finally:
                if db:
                    try:
                        db.close()
                    except Exception as exc:
                        failures.append((t("Datenbank konnte nach dem Import-Rollback nicht geschlossen werden"), exc))
                    finally:
                        db = None

        try:
            db = self._open_db_readonly(world_path)
            if self._read_optional_player(db, target_key) != target_before_raw:
                failures.append(
                    (t("Zielzustand stimmt nach dem Import-Rollback nicht mit dem Ausgangszustand überein"), ValueError(t("Bytevergleich fehlgeschlagen")))
                )
        except Exception as exc:
            failures.append((t("Import-Rollback konnte nicht nachvalidiert werden"), exc))
        finally:
            if db:
                try:
                    db.close()
                except Exception as exc:
                    failures.append((t("Readonly-Datenbank konnte nach dem Import-Rollback nicht geschlossen werden"), exc))
                finally:
                    db = None
        return failures, rollback_required

    def preview_player_export(self, export_zip, target_world_path):
        ensure_valid_world_path(target_world_path)
        snapshot_path, import_token = snapshot_player_export_for_import(export_zip, target_world_path)
        cleanup_warning = None
        operation_error = None
        try:
            manifest, _preview, raw_bytes = read_player_export(snapshot_path)
        except Exception as exc:
            operation_error = exc
            raise
        finally:
            try:
                os.remove(snapshot_path)
            except OSError as exc:
                warning = t("Temporärer Import-Snapshot konnte nicht entfernt werden: {path} ({error})", path=snapshot_path, error=exc)
                if operation_error is not None:
                    existing = getattr(operation_error, "cleanup_warning", None)
                    operation_error.cleanup_warning = f"{existing} {warning}" if existing else warning
                    operation_error.source_snapshot_path = snapshot_path
                else:
                    cleanup_warning = warning
                LOGGER.exception("Temporärer Spieler-Import-Snapshot konnte nach der Vorschau nicht entfernt werden: %s", snapshot_path)
        preview = player_preview_from_bytes(raw_bytes)
        import_decision = evaluate_player_import_preview(preview)
        export_player_meta = manifest.get("player") if isinstance(manifest.get("player"), dict) else {}
        exported_encoded_key = str(export_player_meta.get("player_key") or "").strip()
        player_label = str(export_player_meta.get("label") or export_player_meta.get("raw_key_preview") or "Unbekannter Spieler")
        result = {
            "success": True,
            "export_path": export_zip,
            "import_token": import_token,
            "format": manifest.get("format"),
            "version": manifest.get("version"),
            "created_at": manifest.get("created_at"),
            "source_world_name": manifest.get("source_world_name"),
            "player": {
                "player_key": exported_encoded_key,
                "label": player_label,
                "kind": export_player_meta.get("kind"),
                "editable_at_export": bool(export_player_meta.get("editable")),
                "exportable_at_export": bool(export_player_meta.get("exportable")),
                "reason": export_player_meta.get("reason"),
            },
            "preview": {
                "inventory_count": preview.get("inventory_count", 0),
                "has_inventory": bool(preview.get("has_inventory")),
                "has_inventory_tag": bool(preview.get("has_inventory_tag")),
                "has_ender_chest": bool(preview.get("has_ender_chest")),
                "has_ender_chest_tag": bool(preview.get("has_ender_chest_tag")),
                "has_player_hints": bool(preview.get("has_player_hints")),
                "inventory_will_be_created": bool(preview.get("inventory_will_be_created")),
                "inventory_opaque": import_decision["inventory_opaque"],
                "ender_chest_opaque": import_decision["ender_chest_opaque"],
                "root_tag_type": preview.get("root_tag_type"),
                "stats": preview.get("stats", {}),
            },
            "importable": import_decision["importable"],
            "import_scope": "complete_player_nbt",
            "message": import_decision["message"],
        }
        if cleanup_warning:
            result["cleanup_warning"] = cleanup_warning
        return result

    def import_player(
        self,
        export_zip,
        target_world_path,
        encoded_target_player_key,
        confirm_overwrite=False,
        import_as_exported_player=False,
        import_token=None,
        base_revision=None,
        write_gate_check=None,
    ):
        if not confirm_overwrite:
            raise ValueError("Import blockiert: Überschreiben muss ausdrücklich bestätigt werden.")
        if not isinstance(import_token, dict):
            raise PlayerImportPreviewStaleError("Spieler-Import abgelehnt: Die Import-Vorschau fehlt oder ist veraltet. Bitte Vorschau neu laden.")

        ensure_valid_world_path(target_world_path)
        source_snapshot, _actual_token = snapshot_player_export_for_import(
            export_zip,
            target_world_path,
            expected_token=import_token,
        )
        result = None
        operation_error = None
        try:
            manifest, _preview, raw_bytes = read_player_export(source_snapshot)
            preview = player_preview_from_bytes(raw_bytes)
            import_decision = evaluate_player_import_preview(preview)
            if not import_decision["importable"]:
                raise ValueError(f"Spieler-Import abgelehnt: {import_decision['message'].removeprefix('Nicht importierbar: ').strip()}")

            export_player_meta = manifest.get("player") if isinstance(manifest.get("player"), dict) else {}
            exported_encoded_key = str(export_player_meta.get("player_key") or "").strip()
            exported_player_key = decode_player_key(exported_encoded_key) if exported_encoded_key else None

            if import_as_exported_player:
                if exported_player_key is None:
                    raise ValueError("Import als neuer Spieler nicht möglich: Der Export enthält keinen Spieler-Key.")
                exported_info = classify_player_record(exported_player_key, raw_bytes)
                if not exported_info or not exported_info.get("editable"):
                    raise ValueError("Import als neuer Spieler abgelehnt: Export-Key und NBT-Daten ergeben keinen bearbeitbaren Spieler.")
                target_player_key = exported_player_key
                target_info = {**exported_info, "will_create": True}
            else:
                if not encoded_target_player_key:
                    raise ValueError("Kein Zielspieler gewählt. Wähle einen vorhandenen Spieler oder aktiviere Import als exportierter Spieler.")
                target_player_key = decode_player_key(encoded_target_player_key)
                target_info = None

            backup_file = None
            db = None
            target_before_raw = None
            write_attempted = False
            with self._locked_world(target_world_path):
                ensure_valid_world_path(target_world_path)
                try:
                    db = self._open_db_readonly(target_world_path)
                    if import_as_exported_player:
                        existing = self._read_optional_player(db, target_player_key)
                        if existing is not None:
                            existing_info = classify_player_record(target_player_key, existing)
                            label = existing_info["label"] if existing_info else encode_player_key(target_player_key)
                            raise ValueError(
                                t(
                                    "Dieser Spieler-Key existiert in der Zielwelt bereits "
                                    "({label}). Wähle den vorhandenen Spieler und importiere gezielt darauf, "
                                    "statt ihn als neuen Datensatz anzulegen.",
                                    label=label,
                                )
                            )
                        target_before_raw = None
                    else:
                        target_info = self._get_player_info(db, target_player_key)
                        if not target_info["editable"]:
                            raise ValueError(f"Zielspieler ist read-only: {target_info['reason']}")
                        target_before_raw = self._read_player(db, target_player_key)
                        self._assert_import_target_revision_current(target_before_raw, base_revision)
                finally:
                    if db:
                        try:
                            close_db_preserving_active_exception(db, context="Import-Zielspieler prüfen")
                        finally:
                            db = None

                try:
                    if write_gate_check is not None:
                        write_gate_check()
                    backup_file = create_backup(target_world_path, prune_after=False)
                    if write_gate_check is not None:
                        write_gate_check()

                    db = self._open_db(target_world_path)
                    current_target = self._read_optional_player(db, target_player_key)
                    if current_target != target_before_raw:
                        raise PlayerImportPreviewStaleError(
                            t(
                                "Spieler-Import abgelehnt: Der Zielspieler wurde während der Backup-Erstellung geändert. "
                                "Lade den Zielspieler neu und prüfe den Import erneut."
                            ),
                            target_revision_stale=True,
                        )
                    assert_serialized_player_roundtrip(raw_bytes)
                    if write_gate_check is not None:
                        write_gate_check()
                    write_attempted = True
                    db.put(target_player_key, raw_bytes)
                    try:
                        close_db_preserving_active_exception(db, context="Spieler-Import nach dem Schreiben")
                    finally:
                        db = None

                    db = self._open_db_readonly(target_world_path)
                    imported_after = self._read_optional_player(db, target_player_key)
                    if imported_after != raw_bytes:
                        raise ValueError(
                            t("Nachvalidierung fehlgeschlagen: Importierter Player-Datensatz stimmt nicht bytegenau mit der Import-Datei überein.")
                        )
                    resulting_info = classify_player_record(target_player_key, imported_after)
                    if not resulting_info or not resulting_info.get("editable"):
                        raise ValueError(t("Nachvalidierung fehlgeschlagen: Der importierte Player-Datensatz ist unter dem Ziel-Key nicht sicher bearbeitbar."))
                    try:
                        close_db_preserving_active_exception(db, context="Spieler-Import nachvalidieren")
                    finally:
                        db = None
                    cleanup_warning = None
                    try:
                        prune_backups(target_world_path, keep_paths=[backup_file])
                    except Exception as exc:
                        cleanup_warning = t("Import war erfolgreich, alte Backups konnten aber nicht bereinigt werden: {error}", error=exc)
                        LOGGER.exception("Backup-Retention nach erfolgreichem Spieler-Import fehlgeschlagen.")

                    result = {
                        "success": True,
                        "write_committed": True,
                        "world_path": target_world_path,
                        "backup_file": os.path.basename(backup_file),
                        "target_player": resulting_info,
                        "import_preview": preview,
                        "created_new_player": bool(import_as_exported_player),
                        "post_write_validated": True,
                    }
                    if cleanup_warning:
                        result["cleanup_warning"] = cleanup_warning
                except Exception as exc:
                    close_failures = []
                    if db:
                        try:
                            db.close()
                        except Exception as close_exc:
                            close_failures.append((t("Datenbank konnte vor dem Import-Rollback nicht geschlossen werden"), close_exc))
                        finally:
                            db = None
                    rollback_failures = []
                    rollback_performed = False
                    if write_attempted:
                        rollback_failures, rollback_performed = self._rollback_player_import(
                            target_world_path,
                            target_player_key,
                            target_before_raw,
                            raw_bytes,
                        )
                        rollback_failures = close_failures + rollback_failures
                        if rollback_failures:
                            raise PlayerImportRecordRollbackError(
                                exc,
                                backup_file=backup_file,
                                rollback_failures=rollback_failures,
                            ) from exc

                    if write_attempted and rollback_performed:
                        raise PlayerImportRolledBackError(exc, backup_file=backup_file) from exc
                    remove_backup_after_aborted_write(backup_file, exc, operation="player.import")
                    raise
                finally:
                    close_db_preserving_active_exception(db, context="Spieler-Import abschließen")
            return result
        except Exception as exc:
            operation_error = exc
            raise
        finally:
            try:
                os.remove(source_snapshot)
            except OSError as exc:
                warning = t("Temporärer Import-Snapshot konnte nicht entfernt werden: {path} ({error})", path=source_snapshot, error=exc)
                if result and result.get("success"):
                    existing = result.get("cleanup_warning")
                    result["cleanup_warning"] = f"{existing} {warning}" if existing else warning
                    LOGGER.exception("Temporärer Spieler-Import-Snapshot blieb nach erfolgreichem Import zurück.")
                else:
                    if operation_error is not None:
                        existing = getattr(operation_error, "cleanup_warning", None)
                        operation_error.cleanup_warning = f"{existing} {warning}" if existing else warning
                        operation_error.source_snapshot_path = source_snapshot
                    LOGGER.exception("Temporärer Spieler-Import-Snapshot konnte nach fehlgeschlagenem Import nicht entfernt werden.")

    def list_backups(self, world_path):
        with self._locked_world(world_path):
            ensure_valid_world_path(world_path)
            config = load_config()
            return {
                "success": True,
                "backup_dir": get_backups_dir(world_path),
                "max_backups_per_world": config.max_backups_per_world,
                "max_pre_restore_backups_per_world": config.max_pre_restore_backups_per_world,
                "backups": scan_backups(world_path),
            }

    def preview_backup_restore(self, world_path, backup_file):
        with self._locked_world(world_path):
            ensure_valid_world_path(world_path)
            return preview_world_backup(world_path, backup_file)

    def create_manual_backup(self, world_path):
        """Create an on-demand backup of the world.

        Manuelle Backups werden bewusst nicht automatisch rotiert. Der Benutzer
        kann sie über die Backupansicht gezielt löschen.
        """

        with self._locked_world(world_path):
            ensure_valid_world_path(world_path)
            backup_file = create_backup(
                world_path,
                prune_after=False,
                backup_kind=BACKUP_KIND_MANUAL,
            )
            return {
                "success": True,
                "backup_file": os.path.basename(backup_file),
            }

    def delete_backup(self, world_path, backup_file):
        with self._locked_world(world_path):
            ensure_valid_world_path(world_path)
            deleted = delete_backup(world_path, backup_file)
            return {
                "success": True,
                "backup_file": os.path.basename(deleted),
            }

    def restore_backup(self, world_path, backup_file, *, backup_token=None, pre_restore_check=None):
        with self._locked_world(world_path):
            ensure_valid_world_path(world_path)
            # Resolve the requested backup before creating the pre-restore
            # safety backup.  Otherwise a small retention limit could prune the
            # requested old backup before restore has a chance to open it.
            selected_backup = resolve_backup_path(world_path, backup_file)
            if not os.path.exists(selected_backup):
                raise FileNotFoundError("Backup-Datei existiert nicht.")
            restore_source_snapshot = snapshot_backup_for_restore(
                world_path,
                selected_backup,
                expected_token=backup_token,
            )
            cleanup_warnings = []
            restore_succeeded = False
            operation_error = None
            pre_restore_backup = None
            try:
                pre_restore_backup = create_backup(
                    world_path,
                    prune_after=False,
                    backup_kind=BACKUP_KIND_PRE_RESTORE,
                    restore_source=selected_backup,
                )
                cleanup_warnings.extend(
                    restore_world_backup(
                        world_path,
                        os.path.basename(selected_backup),
                        resolved_backup_path=restore_source_snapshot,
                        pre_restore_check=pre_restore_check,
                    )
                    or []
                )
                restore_succeeded = True
            except Exception as exc:
                operation_error = exc
                if pre_restore_backup:
                    exc.pre_restore_backup = os.path.basename(pre_restore_backup)
                raise
            finally:
                try:
                    os.remove(restore_source_snapshot)
                except OSError as exc:
                    warning = t(
                        "Der private Restore-Snapshot konnte nicht entfernt werden und blieb unter {path} zurück: {error}",
                        path=restore_source_snapshot,
                        error=exc,
                    )
                    if restore_succeeded:
                        cleanup_warnings.append(warning)
                        LOGGER.exception("Restore-Snapshot blieb nach erfolgreichem Restore zurück: %s", restore_source_snapshot)
                    else:
                        if operation_error is not None:
                            existing = getattr(operation_error, "cleanup_warning", None)
                            operation_error.cleanup_warning = f"{existing} {warning}" if existing else warning
                            operation_error.source_snapshot_path = restore_source_snapshot
                        LOGGER.exception("Restore-Snapshot konnte nach fehlgeschlagenem Restore nicht entfernt werden: %s", restore_source_snapshot)
                if pre_restore_backup:
                    # Recovery backups stay bounded even after a blocked or
                    # failed restore. The newest safety copy is always protected.
                    try:
                        prune_backups(
                            world_path,
                            keep_paths=[pre_restore_backup],
                            retention_classes=[RETENTION_RECOVERY],
                        )
                    except Exception as exc:
                        warning = t("Alte Vor-Wiederherstellungs-Backups konnten nicht bereinigt werden: {error}", error=exc)
                        if restore_succeeded:
                            cleanup_warnings.append(warning)
                        elif operation_error is not None:
                            existing = getattr(operation_error, "cleanup_warning", None)
                            operation_error.cleanup_warning = f"{existing} {warning}" if existing else warning
                        LOGGER.exception("Backup-Retention nach Restore-Versuch fehlgeschlagen.")
            result = {
                "success": True,
                "message": "Backup erfolgreich wiederhergestellt!",
                "pre_restore_backup": os.path.basename(pre_restore_backup),
                "restored_backup": os.path.basename(selected_backup),
            }
            if cleanup_warnings:
                result["cleanup_warning"] = " ".join(cleanup_warnings)
            return result
