from __future__ import annotations

import struct
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

nbt = pytest.importorskip("amulet_nbt")

from mcbe_editor.bedrock_nbt import LOAD_KWARGS, SAVE_KWARGS
from mcbe_editor.mount_profile import (
    DEFAULT_HORSE_TEMPER,
    HORSE_TEMPER_MAX,
    HORSE_TEMPER_MIN,
    PROFILE_MODE_CUSTOM,
    PROFILE_MODE_RANDOM_LIKE_GAME,
    horse_profile_attribute_values,
    horse_profile_summary,
    normalize_horse_profile,
    random_like_game_horse_profile,
)
from mcbe_editor.mount_write import (
    ACTOR_PREFIX,
    DEFAULT_UNDERWATER_MOVEMENT,
    actor_key_suffix,
    build_horse_actor_nbt,
    build_horse_mount_record,
    digp_entry_for_actor_key,
    digp_key_for_position,
    digp_reference_summary,
    merge_digp_value,
    next_actor_key,
    normalize_mount_stats,
    create_horse_mount_with_service,
    unique_id_from_actor_key,
    validate_horse_mount_write,
)


def test_direct_mount_create_uses_one_atomic_batch(monkeypatch, tmp_path) -> None:
    class WriteDb:
        def __init__(self):
            self.batches = []

        def close(self):
            return None

        def put_batch(self, writes):
            self.batches.append(dict(writes))

    db = WriteDb()
    service = SimpleNamespace(
        _locked_world=lambda _path: nullcontext(),
        _open_db=lambda _path: db,
        _get_player_info=lambda _db, _key: {"editable": True},
        _read_player=lambda _db, _key: b"player",
    )
    actor_key = ACTOR_PREFIX + b"12345678"
    record = SimpleNamespace(
        actor_key=actor_key,
        actor_value=b"actor-value",
        digp_key=b"digp-key",
        digp_value=b"12345678",
        unique_id=1,
        position={"x": 1.0, "y": 64.0, "z": 1.0},
        create_mode="synthetic_full",
        template_identifier=None,
        horse_profile={},
        mount_type="minecraft:horse",
        mount_stats=None,
        tamed=False,
        owner_unique_id=None,
    )
    monkeypatch.setattr("mcbe_editor.mount_write.ensure_valid_world_path", lambda path: str(path))
    monkeypatch.setattr("mcbe_editor.mount_write.decode_player_key", lambda _key: b"player")
    monkeypatch.setattr("mcbe_editor.mount_write.create_backup", lambda *_args, **_kwargs: str(tmp_path / "backup.zip"))
    monkeypatch.setattr("mcbe_editor.mount_write.prune_backups", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("mcbe_editor.mount_write.build_horse_mount_record", lambda *_args, **_kwargs: record)
    monkeypatch.setattr("mcbe_editor.mount_write.validate_horse_mount_write", lambda *_args, **_kwargs: {"ok": True, "errors": []})

    result = create_horse_mount_with_service(
        service,
        str(tmp_path),
        "player",
        {"mount_type": "minecraft:horse", "selected_position": record.position},
        create_mode="synthetic_full",
    )

    assert result["success"] is True
    assert db.batches == [{record.actor_key: record.actor_value, record.digp_key: record.digp_value}]


def test_direct_mount_create_reports_committed_validation_failure(monkeypatch, tmp_path) -> None:
    class WriteDb:
        def close(self):
            return None

        def put_batch(self, _writes):
            return None

    db = WriteDb()
    service = SimpleNamespace(
        _locked_world=lambda _path: nullcontext(),
        _open_db=lambda _path: db,
        _get_player_info=lambda _db, _key: {"editable": True},
        _read_player=lambda _db, _key: b"player",
    )
    record = SimpleNamespace(
        actor_key=ACTOR_PREFIX + b"12345678",
        actor_value=b"actor-value",
        digp_key=b"digp-key",
        digp_value=b"12345678",
        unique_id=1,
        position={"x": 1.0, "y": 64.0, "z": 1.0},
        create_mode="synthetic_full",
        template_identifier=None,
        horse_profile={},
        mount_type="minecraft:horse",
        mount_stats=None,
        tamed=False,
        owner_unique_id=None,
    )
    monkeypatch.setattr("mcbe_editor.mount_write.ensure_valid_world_path", lambda path: str(path))
    monkeypatch.setattr("mcbe_editor.mount_write.decode_player_key", lambda _key: b"player")
    monkeypatch.setattr("mcbe_editor.mount_write.create_backup", lambda *_args, **_kwargs: str(tmp_path / "backup.zip"))
    monkeypatch.setattr("mcbe_editor.mount_write.prune_backups", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("mcbe_editor.mount_write.build_horse_mount_record", lambda *_args, **_kwargs: record)
    monkeypatch.setattr(
        "mcbe_editor.mount_write.validate_horse_mount_write",
        lambda *_args, **_kwargs: {"ok": False, "errors": ["digp hat bestehende Actor-Referenzen nicht erhalten"]},
    )

    result = create_horse_mount_with_service(
        service,
        str(tmp_path),
        "player",
        {"mount_type": "minecraft:horse", "selected_position": record.position},
        create_mode="synthetic_full",
    )

    assert result["success"] is False
    assert result["write_committed"] is True
    assert result["validation_failed"] is True
    assert "Nicht erneut erzeugen" in result["error"]

    def raise_during_validation(*_args, **_kwargs):
        raise RuntimeError("Validator abgestürzt")

    monkeypatch.setattr("mcbe_editor.mount_write.validate_horse_mount_write", raise_during_validation)
    exception_result = create_horse_mount_with_service(
        service,
        str(tmp_path),
        "player",
        {"mount_type": "minecraft:horse", "selected_position": record.position},
        create_mode="synthetic_full",
    )

    assert exception_result["success"] is False
    assert exception_result["write_committed"] is True
    assert exception_result["validation_failed"] is True
    assert exception_result["post_create_validation"]["details"]["exception_type"] == "RuntimeError"


def test_direct_mount_create_treats_post_write_close_failure_as_committed(monkeypatch, tmp_path) -> None:
    class WriteDb:
        def __init__(self):
            self.committed = False

        def put_batch(self, _writes):
            self.committed = True

        def close(self):
            # Only the close after the committed batch fails; the pre-backup close is fine.
            if self.committed:
                raise OSError("Zugriff verweigert beim Schließen der DB")

    db = WriteDb()
    service = SimpleNamespace(
        _locked_world=lambda _path: nullcontext(),
        _open_db=lambda _path: db,
        _get_player_info=lambda _db, _key: {"editable": True},
        _read_player=lambda _db, _key: b"player",
    )
    record = SimpleNamespace(
        actor_key=ACTOR_PREFIX + b"12345678",
        actor_value=b"actor-value",
        digp_key=b"digp-key",
        digp_value=b"12345678",
        unique_id=1,
        position={"x": 1.0, "y": 64.0, "z": 1.0},
        create_mode="synthetic_full",
        template_identifier=None,
        horse_profile={},
        mount_type="minecraft:horse",
        mount_stats=None,
        tamed=False,
        owner_unique_id=None,
    )
    monkeypatch.setattr("mcbe_editor.mount_write.ensure_valid_world_path", lambda path: str(path))
    monkeypatch.setattr("mcbe_editor.mount_write.decode_player_key", lambda _key: b"player")
    monkeypatch.setattr("mcbe_editor.mount_write.create_backup", lambda *_args, **_kwargs: str(tmp_path / "backup.zip"))
    monkeypatch.setattr("mcbe_editor.mount_write.prune_backups", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("mcbe_editor.mount_write.build_horse_mount_record", lambda *_args, **_kwargs: record)
    monkeypatch.setattr("mcbe_editor.mount_write.validate_horse_mount_write", lambda *_args, **_kwargs: {"ok": True, "errors": []})

    result = create_horse_mount_with_service(
        service,
        str(tmp_path),
        "player",
        {"mount_type": "minecraft:horse", "selected_position": record.position},
        create_mode="synthetic_full",
    )

    # The batch is committed; a failed close must not present as a retryable error.
    assert result["success"] is False
    assert result["write_committed"] is True
    assert result["validation_failed"] is True
    assert "geschlossen" in result["error"]
    assert result["post_create_validation"]["details"]["post_write_errors"]


def test_direct_mount_create_preserves_pre_write_error_when_close_also_fails(monkeypatch, tmp_path) -> None:
    class InitialDb:
        def close(self):
            return None

    class FailingCleanupDb:
        def close(self):
            raise OSError("close masked original")

    databases = iter([InitialDb(), FailingCleanupDb()])
    service = SimpleNamespace(
        _locked_world=lambda _path: nullcontext(),
        _open_db=lambda _path: next(databases),
        _get_player_info=lambda _db, _key: {"editable": True},
        _read_player=lambda _db, _key: b"player",
    )
    monkeypatch.setattr("mcbe_editor.mount_write.ensure_valid_world_path", lambda path: str(path))
    monkeypatch.setattr("mcbe_editor.mount_write.decode_player_key", lambda _key: b"player")
    monkeypatch.setattr("mcbe_editor.mount_write.create_backup", lambda *_args, **_kwargs: str(tmp_path / "backup.zip"))

    def fail_before_write(*_args, **_kwargs):
        raise ValueError("original build failure")

    monkeypatch.setattr("mcbe_editor.mount_write.build_horse_mount_record", fail_before_write)

    with pytest.raises(ValueError, match="original build failure"):
        create_horse_mount_with_service(
            service,
            str(tmp_path),
            "player",
            {"mount_type": "minecraft:horse", "selected_position": {"x": 1.0, "y": 64.0, "z": 1.0}},
            create_mode="synthetic_full",
        )


class FakeDb:
    def __init__(self, items=None):
        self.store = dict(items or {})

    def get(self, key):
        if key not in self.store:
            raise KeyError(key)
        return self.store[key]

    def put(self, key, value):
        self.store[key] = value

    def iter_items(self):
        return list(self.store.items())


def _actor_key(group: int, local_id: int) -> bytes:
    return ACTOR_PREFIX + group.to_bytes(4, "big") + local_id.to_bytes(4, "big")


def _typed(value):
    """Gemeinsamer NBT-zu-dict-Serialisierer für die Gold-Standard-Vergleiche."""
    if isinstance(value, nbt.CompoundTag):
        return {"type": "Compound", "value": {str(key): _typed(value[key]) for key in value}}
    if isinstance(value, nbt.ListTag):
        return {"type": "List", "value": [_typed(item) for item in value]}
    return {"type": type(value).__name__, "value": value.py_data}


def _empty_item() -> nbt.CompoundTag:
    return nbt.CompoundTag(
        {
            "Count": nbt.ByteTag(0),
            "Damage": nbt.ShortTag(0),
            "Name": nbt.StringTag(""),
            "WasPickedUp": nbt.ByteTag(0),
        }
    )


def _template_donkey_raw(unique_id: int, suffix: bytes) -> bytes:
    tag = nbt.CompoundTag(
        {
            "Air": nbt.ShortTag(300),
            "Armor": nbt.ListTag([_empty_item(), _empty_item(), _empty_item(), _empty_item(), _empty_item()]),
            "Attributes": nbt.ListTag(
                [
                    nbt.CompoundTag(
                        {
                            "Name": nbt.StringTag("minecraft:health"),
                            "Base": nbt.FloatTag(25.0),
                            "Current": nbt.FloatTag(25.0),
                            "DefaultMax": nbt.FloatTag(25.0),
                            "DefaultMin": nbt.FloatTag(0.0),
                            "Max": nbt.FloatTag(25.0),
                            "Min": nbt.FloatTag(0.0),
                        }
                    )
                ]
            ),
            "Chested": nbt.ByteTag(0),
            "Color": nbt.ByteTag(0),
            "Color2": nbt.ByteTag(0),
            "Dead": nbt.ByteTag(0),
            "DeathTime": nbt.ShortTag(0),
            "FallDistance": nbt.FloatTag(0.0),
            "HurtTime": nbt.ShortTag(0),
            "Invulnerable": nbt.ByteTag(0),
            "IsAutonomous": nbt.ByteTag(0),
            "IsBaby": nbt.ByteTag(0),
            "LeasherID": nbt.LongTag(-1),
            "Mainhand": nbt.ListTag([_empty_item()]),
            "NaturalSpawn": nbt.ByteTag(1),
            "Offhand": nbt.ListTag([_empty_item()]),
            "OnGround": nbt.ByteTag(1),
            "OwnerNew": nbt.LongTag(-1),
            "PortalCooldown": nbt.IntTag(0),
            "Pos": nbt.ListTag([nbt.FloatTag(1.0), nbt.FloatTag(2.0), nbt.FloatTag(3.0)]),
            "Rotation": nbt.ListTag([nbt.FloatTag(45.0), nbt.FloatTag(0.0)]),
            "Saddled": nbt.ByteTag(0),
            "SkinID": nbt.IntTag(0),
            "Strength": nbt.IntTag(0),
            "StrengthMax": nbt.IntTag(0),
            "Surface": nbt.ByteTag(1),
            "Tags": nbt.ListTag([]),
            "TargetID": nbt.LongTag(-1),
            "Temper": nbt.IntTag(62),
            "TradeExperience": nbt.IntTag(0),
            "TradeTier": nbt.IntTag(0),
            "UniqueID": nbt.LongTag(unique_id),
            "Variant": nbt.IntTag(0),
            "boundX": nbt.IntTag(0),
            "boundY": nbt.IntTag(0),
            "boundZ": nbt.IntTag(0),
            "definitions": nbt.ListTag([nbt.StringTag("+minecraft:donkey"), nbt.StringTag("+minecraft:donkey_adult"), nbt.StringTag("+minecraft:donkey_wild")]),
            "identifier": nbt.StringTag("minecraft:donkey"),
            "internalComponents": nbt.CompoundTag(
                {
                    "EntityStorageKeyComponent": nbt.CompoundTag(
                        {
                            "StorageKey": nbt.StringTag(nbt.utf8_escape_decoder(suffix)),
                        }
                    )
                }
            ),
        }
    )
    return nbt.NamedTag(tag).save_to(**SAVE_KWARGS)


def test_random_like_game_horse_profile_is_seeded_and_bounded() -> None:
    first = random_like_game_horse_profile(seed=1234)
    second = random_like_game_horse_profile(seed=1234)

    assert first == second
    assert first.mode == PROFILE_MODE_RANDOM_LIKE_GAME
    assert 15.0 <= first.health <= 30.0
    assert 0.1125 <= first.movement <= 0.3375
    assert 0.4 <= first.jump_strength <= 1.0
    assert 0 <= first.color <= 6
    assert 0 <= first.mark_variant <= 4


def test_normalize_horse_profile_accepts_custom_vanilla_like_values() -> None:
    profile = normalize_horse_profile(
        {
            "mode": "custom",
            "health": 28,
            "movement": 0.25,
            "jump_strength": 0.8,
            "color": 3,
            "mark_variant": 2,
        }
    )

    assert profile.mode == PROFILE_MODE_CUSTOM
    assert horse_profile_attribute_values(profile) == {
        "minecraft:health": 28.0,
        "minecraft:movement": 0.25,
        "minecraft:horse.jump_strength": 0.8,
    }
    assert horse_profile_summary(profile)["color"] == 3
    assert horse_profile_summary(profile)["mark_variant"] == 2


def test_normalize_horse_profile_rejects_out_of_range_custom_values() -> None:
    with pytest.raises(ValueError, match="Leben"):
        normalize_horse_profile({"mode": "custom", "health": 99})


def test_normalize_horse_profile_rejects_fractional_integer_fields() -> None:
    for field in ("color", "mark_variant"):
        with pytest.raises(ValueError, match="Ganzzahl"):
            normalize_horse_profile({"mode": "custom", field: 2.9})


def test_normalize_horse_profile_defaults_to_current_working_values() -> None:
    profile = normalize_horse_profile()

    assert profile.mode == PROFILE_MODE_RANDOM_LIKE_GAME
    assert profile.health == 25.0
    assert round(profile.movement, 6) == round(0.17499999701976776, 6)
    assert profile.jump_strength == 0.5
    assert profile.color == 0
    assert profile.mark_variant == 1


def test_next_actor_key_uses_next_free_highest_group_id() -> None:
    key = next_actor_key([_actor_key(1, 15), _actor_key(1, 16), _actor_key(2, 1)])

    assert key == _actor_key(2, 2)
    assert unique_id_from_actor_key(key) == -8589934590


def test_next_actor_key_starts_at_group_two_for_fresh_world() -> None:
    key = next_actor_key([])

    assert key == _actor_key(2, 1)
    assert unique_id_from_actor_key(key) == -8589934591


def test_digp_entry_uses_actor_key_suffix() -> None:
    key = _actor_key(3, 7)

    assert unique_id_from_actor_key(key) == -12884901881
    assert digp_entry_for_actor_key(key) == actor_key_suffix(key)
    assert digp_entry_for_actor_key(key).hex() == "0000000300000007"


def test_digp_key_uses_chunk_coordinates() -> None:
    key = digp_key_for_position({"x": 344.5, "y": 81.0, "z": -26.4})

    assert key.startswith(b"digp")
    assert struct.unpack("<ii", key[4:12]) == (21, -2)


@pytest.mark.parametrize(
    ("x", "expected_chunk_x"),
    [
        (15.999, 0),
        (16.0, 1),
        (-0.001, -1),
        (-16.0, -1),
        (-16.001, -2),
    ],
)
def test_digp_key_switches_exactly_at_positive_and_negative_chunk_boundaries(x: float, expected_chunk_x: int) -> None:
    key = digp_key_for_position({"x": x, "y": 65.0, "z": 0.0})

    assert struct.unpack("<ii", key[4:12]) == (expected_chunk_x, 0)


def test_merge_digp_value_appends_actor_entry_once() -> None:
    first = digp_entry_for_actor_key(_actor_key(1, 15))
    second = digp_entry_for_actor_key(_actor_key(1, 16))

    merged = merge_digp_value(first, second)

    assert merged == first + second
    assert merge_digp_value(merged, second) == merged


def test_merge_digp_value_rejects_unknown_shape() -> None:
    with pytest.raises(ValueError, match="unerwartete Länge"):
        merge_digp_value(b"abc", digp_entry_for_actor_key(_actor_key(1, 1)))


def test_digp_reference_summary_reports_actor_suffix_presence() -> None:
    actor = _actor_key(3, 7)
    first = digp_entry_for_actor_key(_actor_key(3, 6))
    second = digp_entry_for_actor_key(actor)

    summary = digp_reference_summary(first + second, second)

    assert summary == {
        "entry_count": 2,
        "contains_actor_suffix": True,
        "actor_suffix_hex": second.hex(),
        "entries_hex": [first.hex(), second.hex()],
    }


def test_build_horse_actor_nbt_contains_bedrock_horse_identity_and_state_tags() -> None:
    actor = _actor_key(2, 9)
    suffix = actor_key_suffix(actor)
    raw = build_horse_actor_nbt({"x": 12.5, "y": 64.0, "z": -20.25}, unique_id_from_actor_key(actor), suffix)
    tag = nbt.load(raw, **LOAD_KWARGS).tag

    assert tag["identifier"].py_data == "minecraft:horse"
    assert tag["UniqueID"].py_data == -8589934583
    assert [round(item.py_data, 3) for item in tag["Pos"]] == [12.5, 64.0, -20.25]
    assert [item.py_data for item in tag["definitions"]] == [
        "+minecraft:horse",
        "+minecraft:horse_adult",
        "+minecraft:horse_wild",
        "+minecraft:base_white",
        "+minecraft:markings_white_details",
    ]
    storage_key = tag["internalComponents"]["EntityStorageKeyComponent"]["StorageKey"].py_data
    assert nbt.utf8_escape_encoder(storage_key) == suffix
    assert isinstance(tag["Armor"], nbt.ListTag)
    assert isinstance(tag["Mainhand"], nbt.ListTag)
    assert isinstance(tag["Offhand"], nbt.ListTag)
    assert any(attr["Name"].py_data == "minecraft:horse.jump_strength" for attr in tag["Attributes"])
    assert "Health" not in tag
    for key in (
        "IsAngry",
        "IsEating",
        "IsGliding",
        "IsGlobal",
        "IsOutOfControl",
        "IsPregnant",
        "IsScared",
        "IsSwimming",
        "IsTrusting",
        "SkinID",
        "SkipBodySlotUpgrade",
        "boundX",
        "boundY",
        "boundZ",
        "expDropEnabled",
        "hasBoundOrigin",
    ):
        assert key in tag


def test_build_horse_actor_nbt_preserves_high_byte_storage_key_suffix() -> None:
    # Regressionsfall aus einer realen Welt: latin-1 hatte 84/f9 beim Speichern
    # zu c284/c3b9 erweitert und damit einen zweiten Actor-Key erzeugt.
    actor = _actor_key(0x84, 0x12CF9)
    suffix = actor_key_suffix(actor)
    raw = build_horse_actor_nbt({"x": 4991.683, "y": 59.0, "z": 4071.082}, unique_id_from_actor_key(actor), suffix)
    tag = nbt.load(raw, **LOAD_KWARGS).tag
    storage_key = tag["internalComponents"]["EntityStorageKeyComponent"]["StorageKey"].py_data

    assert suffix.hex() == "0000008400012cf9"
    assert nbt.utf8_escape_encoder(storage_key) == suffix
    assert storage_key != suffix.decode("latin-1")
    assert nbt.NamedTag(tag).save_to(**SAVE_KWARGS) == raw


def test_build_horse_actor_nbt_definitions_follow_profile_color_and_markings() -> None:
    actor = _actor_key(2, 9)
    suffix = actor_key_suffix(actor)
    profile = {"mode": PROFILE_MODE_CUSTOM, "health": 20, "movement": 0.2, "jump_strength": 0.6, "color": 4, "mark_variant": 4}
    raw = build_horse_actor_nbt({"x": 0.5, "y": 64.0, "z": 0.5}, unique_id_from_actor_key(actor), suffix, horse_profile=profile)
    tag = nbt.load(raw, **LOAD_KWARGS).tag

    assert [item.py_data for item in tag["definitions"]] == [
        "+minecraft:horse",
        "+minecraft:horse_adult",
        "+minecraft:horse_wild",
        "+minecraft:base_black",
        "+minecraft:markings_black_dots",
    ]
    assert tag["Variant"].py_data == 4
    assert tag["Color"].py_data == 0
    assert tag["MarkVariant"].py_data == 4


def test_validate_horse_mount_write_expects_profile_definitions() -> None:
    db = FakeDb()
    profile = {"mode": PROFILE_MODE_CUSTOM, "health": 20, "movement": 0.2, "jump_strength": 0.6, "color": 2, "mark_variant": 0}
    record = build_horse_mount_record(db, {"x": 0.5, "y": 64.0, "z": 0.5}, create_mode="synthetic_full", horse_profile=profile)
    db.put(record.actor_key, record.actor_value)
    db.put(record.digp_key, record.digp_value)

    validation = validate_horse_mount_write(db, record)

    assert validation["ok"] is True
    assert validation["checks"]["definitions_complete"] is True
    assert "+minecraft:base_chestnut" in validation["details"]["expected_definitions"]
    assert "+minecraft:markings_none" in validation["details"]["expected_definitions"]


def test_build_donkey_actor_nbt_matches_record_evidence() -> None:
    actor = _actor_key(2, 9)
    suffix = actor_key_suffix(actor)
    raw = build_horse_actor_nbt({"x": 0.5, "y": 64.0, "z": 0.5}, unique_id_from_actor_key(actor), suffix, mount_type="minecraft:donkey")
    tag = nbt.load(raw, **LOAD_KWARGS).tag

    assert tag["identifier"].py_data == "minecraft:donkey"
    assert [item.py_data for item in tag["definitions"]] == [
        "+minecraft:donkey",
        "+minecraft:donkey_adult",
        "+minecraft:donkey_wild",
    ]
    attributes = {attr["Name"].py_data: attr for attr in tag["Attributes"]}
    assert round(attributes["minecraft:movement"]["Base"].py_data, 6) == 0.175
    assert attributes["minecraft:horse.jump_strength"]["Base"].py_data == 0.5
    assert 15.0 <= attributes["minecraft:health"]["Base"].py_data <= 30.0
    assert tag["Variant"].py_data == 0
    assert tag["Color"].py_data == 0
    assert tag["MarkVariant"].py_data == 0
    assert "Temper" in tag
    assert "SkipBodySlotUpgrade" not in tag
    assert tag["IsTamed"].py_data == 0
    assert "Health" not in tag


def test_build_skeleton_horse_actor_nbt_matches_record_evidence() -> None:
    actor = _actor_key(2, 9)
    suffix = actor_key_suffix(actor)
    raw = build_horse_actor_nbt({"x": 0.5, "y": 64.0, "z": 0.5}, unique_id_from_actor_key(actor), suffix, mount_type="minecraft:skeleton_horse")
    tag = nbt.load(raw, **LOAD_KWARGS).tag

    assert tag["identifier"].py_data == "minecraft:skeleton_horse"
    assert [item.py_data for item in tag["definitions"]] == [
        "+minecraft:skeleton_horse",
        "+minecraft:skeleton_horse_adult",
    ]
    attributes = {attr["Name"].py_data: attr for attr in tag["Attributes"]}
    assert attributes["minecraft:health"]["Base"].py_data == 15.0
    assert round(attributes["minecraft:movement"]["Base"].py_data, 6) == 0.2
    assert 0.4 <= attributes["minecraft:horse.jump_strength"]["Base"].py_data <= 1.0
    # 6/6 gescannte Minecraft-Skelettpferde schwimmen mit 0.08 statt der 0.02,
    # die jeder andere reitbare Typ trägt.
    assert round(attributes["minecraft:underwater_movement"]["Base"].py_data, 6) == 0.08
    assert "Temper" not in tag
    assert "SkipBodySlotUpgrade" not in tag
    assert tag["IsTamed"].py_data == 1


def test_only_the_skeleton_horse_deviates_from_the_default_underwater_movement() -> None:
    for mount_type in ("minecraft:horse", "minecraft:donkey", "minecraft:mule", "minecraft:camel"):
        raw = build_horse_actor_nbt({"x": 0.5, "y": 64.0, "z": 0.5}, 1, b"\0" * 8, mount_type=mount_type)
        attributes = {attr["Name"].py_data: attr for attr in nbt.load(raw, **LOAD_KWARGS).tag["Attributes"]}

        assert attributes["minecraft:underwater_movement"]["Base"].py_data == DEFAULT_UNDERWATER_MOVEMENT, mount_type


def test_seeded_horse_profile_still_reproduces_the_whole_record_including_temper() -> None:
    """Randomizing Temper must not cost reproducibility: one seed, one record."""

    profile = {"mode": PROFILE_MODE_RANDOM_LIKE_GAME, "seed": "reference-seed"}
    first = build_horse_actor_nbt({"x": 0.5, "y": 64.0, "z": 0.5}, 1, b"\x00" * 8, profile, mount_type="minecraft:horse")
    second = build_horse_actor_nbt({"x": 0.5, "y": 64.0, "z": 0.5}, 1, b"\x00" * 8, profile, mount_type="minecraft:horse")

    assert first == second
    assert HORSE_TEMPER_MIN <= nbt.load(first, **LOAD_KWARGS).tag["Temper"].py_data <= HORSE_TEMPER_MAX


def test_random_horse_profiles_spread_temper_instead_of_repeating_one_value() -> None:
    tempers = {random_like_game_horse_profile(seed=f"seed-{index}").temper for index in range(60)}

    assert len(tempers) > 20, f"Temper streut zu wenig: {sorted(tempers)}"
    assert all(HORSE_TEMPER_MIN <= value <= HORSE_TEMPER_MAX for value in tempers)


def test_horse_profile_without_seed_keeps_the_deterministic_default_temper() -> None:
    raw = build_horse_actor_nbt({"x": 0.5, "y": 64.0, "z": 0.5}, 1, b"\x00" * 8, mount_type="minecraft:horse")

    assert nbt.load(raw, **LOAD_KWARGS).tag["Temper"].py_data == DEFAULT_HORSE_TEMPER


def test_custom_horse_profile_writes_the_requested_temper() -> None:
    raw = build_horse_actor_nbt(
        {"x": 0.5, "y": 64.0, "z": 0.5},
        1,
        b"\x00" * 8,
        {"mode": PROFILE_MODE_CUSTOM, "temper": 7},
        mount_type="minecraft:horse",
    )

    assert nbt.load(raw, **LOAD_KWARGS).tag["Temper"].py_data == 7

    with pytest.raises(ValueError, match="Zähmfortschritt"):
        normalize_horse_profile({"mode": PROFILE_MODE_CUSTOM, "temper": 100})


def test_donkey_and_mule_roll_temper_while_tamed_variants_have_none() -> None:
    db = FakeDb()
    for mount_type in ("minecraft:donkey", "minecraft:mule"):
        wild = build_horse_mount_record(db, {"x": 0.5, "y": 64.0, "z": 0.5}, create_mode="synthetic_full", mount_type=mount_type)
        wild_tag = nbt.load(wild.actor_value, **LOAD_KWARGS).tag

        assert HORSE_TEMPER_MIN <= wild_tag["Temper"].py_data <= HORSE_TEMPER_MAX, mount_type
        assert wild_tag["Temper"].py_data == wild.mount_stats["temper"], mount_type

        tamed = build_horse_mount_record(
            db, {"x": 0.5, "y": 64.0, "z": 0.5}, create_mode="synthetic_full", mount_type=mount_type, tamed=True, owner_unique_id=-1
        )
        assert "Temper" not in nbt.load(tamed.actor_value, **LOAD_KWARGS).tag, mount_type
        # Der Record darf keinen Zähmfortschritt melden, den er nie geschrieben hat.
        assert tamed.mount_stats["temper"] is None, mount_type


def test_donkey_and_mule_temper_is_user_editable_within_the_vanilla_range() -> None:
    db = FakeDb()
    for mount_type in ("minecraft:donkey", "minecraft:mule"):
        record = build_horse_mount_record(
            db, {"x": 0.5, "y": 64.0, "z": 0.5}, create_mode="synthetic_full", mount_type=mount_type, mount_stats={"temper": 7}
        )
        tag = nbt.load(record.actor_value, **LOAD_KWARGS).tag

        assert tag["Temper"].py_data == 7, mount_type
        assert record.mount_stats["temper"] == 7, mount_type
        # Ein gesetzter Wert darf die uebrigen Wuerfe nicht einfrieren.
        assert 15.0 <= record.mount_stats["health"] <= 30.0, mount_type

        assert normalize_mount_stats(mount_type, {"temper": HORSE_TEMPER_MIN}) == {"temper": float(HORSE_TEMPER_MIN)}
        assert normalize_mount_stats(mount_type, {"temper": HORSE_TEMPER_MAX}) == {"temper": float(HORSE_TEMPER_MAX)}
        with pytest.raises(ValueError, match="Vanilla-Bereich"):
            normalize_mount_stats(mount_type, {"temper": HORSE_TEMPER_MAX + 1})

    # Typen ohne Temper-Tag duerfen das Feld gar nicht erst anbieten.
    for mount_type in ("minecraft:skeleton_horse", "minecraft:camel"):
        with pytest.raises(ValueError, match="kein einstellbares Feld"):
            normalize_mount_stats(mount_type, {"temper": 20})


def test_a_decimal_temper_is_rejected_instead_of_silently_truncated() -> None:
    """Temper ist ein IntTag: 7.9 wuerde als 7 landen, aber als 7.9 gemeldet.

    Das Pferde-Profil weist Nachkommastellen schon lange ab; fuer Esel und Maultier
    lief der Wert dagegen durch die Float-Pruefung und wurde erst beim Schreiben
    abgeschnitten - der Record trug dann einen anderen Wert als die Rueckmeldung.
    """

    for mount_type in ("minecraft:donkey", "minecraft:mule"):
        for raw in (7.9, "7.9", 0.5, 98.5):
            with pytest.raises(ValueError, match="ganze Zahl"):
                normalize_mount_stats(mount_type, {"temper": raw})
        # Ganzzahlige Eingaben bleiben erlaubt, auch als 7.0 oder "7".
        assert normalize_mount_stats(mount_type, {"temper": 7.0}) == {"temper": 7.0}
        assert normalize_mount_stats(mount_type, {"temper": "7"}) == {"temper": 7.0}

    with pytest.raises(ValueError, match="Ganzzahl"):
        normalize_horse_profile({"mode": PROFILE_MODE_CUSTOM, "temper": 7.9})


def test_tamed_donkey_ignores_a_requested_temper_because_taming_removes_the_tag() -> None:
    db = FakeDb()
    record = build_horse_mount_record(
        db,
        {"x": 0.5, "y": 64.0, "z": 0.5},
        create_mode="synthetic_full",
        mount_type="minecraft:donkey",
        mount_stats={"temper": 42},
        tamed=True,
        owner_unique_id=-1,
    )

    assert "Temper" not in nbt.load(record.actor_value, **LOAD_KWARGS).tag
    assert record.mount_stats["temper"] is None


def test_skeleton_horse_and_camel_carry_no_temper_at_all() -> None:
    for mount_type in ("minecraft:skeleton_horse", "minecraft:camel"):
        raw = build_horse_actor_nbt({"x": 0.5, "y": 64.0, "z": 0.5}, 1, b"\x00" * 8, mount_type=mount_type)

        assert "Temper" not in nbt.load(raw, **LOAD_KWARGS).tag, mount_type


def test_horse_records_skip_the_body_slot_upgrade_like_every_scanned_game_record() -> None:
    """All 73 scanned Minecraft horse records carry SkipBodySlotUpgrade=1."""

    raw = build_horse_actor_nbt({"x": 0.5, "y": 64.0, "z": 0.5}, 1, b"\0" * 8, mount_type="minecraft:horse")
    tag = nbt.load(raw, **LOAD_KWARGS).tag

    assert tag["SkipBodySlotUpgrade"].py_data == 1


def test_build_and_validate_mule_mount_record_roundtrip() -> None:
    db = FakeDb()
    record = build_horse_mount_record(db, {"x": 0.5, "y": 64.0, "z": 0.5}, create_mode="synthetic_full", mount_type="minecraft:mule")
    db.put(record.actor_key, record.actor_value)
    db.put(record.digp_key, record.digp_value)

    validation = validate_horse_mount_write(db, record)

    assert record.mount_type == "minecraft:mule"
    assert record.horse_profile is None
    assert validation["ok"] is True
    assert validation["checks"]["identifier_matches_mount_type"] is True
    assert validation["details"]["expected_definitions"] == [
        "+minecraft:mule",
        "+minecraft:mule_adult",
        "+minecraft:mule_wild",
    ]


def test_build_camel_actor_nbt_matches_real_record_tag_for_tag() -> None:
    # Goldstandard: Die bytegenaue Referenz ist ein isolierter, von Minecraft
    # geschriebener Kamel-Record ohne Konto- oder Personendaten. Herkunft und
    # Bedeutung der weltinternen Actor-IDs sind in tests/data/README.md erklärt.
    raw_hex = (Path(__file__).parent / "data" / "camel_actor_record.hex").read_text(encoding="ascii").strip()
    real = nbt.load(bytes.fromhex(raw_hex), **LOAD_KWARGS).tag
    actor = _actor_key(2, 9)
    suffix = actor_key_suffix(actor)
    raw = build_horse_actor_nbt({"x": 0.5, "y": 64.0, "z": 0.5}, unique_id_from_actor_key(actor), suffix, mount_type="minecraft:camel")
    ours = nbt.load(raw, **LOAD_KWARGS).tag

    identity_keys = {"Pos", "Rotation", "UniqueID", "internalComponents"}
    real_keys = {str(key) for key in real}
    our_keys = {str(key) for key in ours}
    assert our_keys == real_keys
    for key in sorted(real_keys):
        if key in identity_keys:
            continue
        assert _typed(real[key]) == _typed(ours[key]), f"Tag {key} weicht vom echten Kamel-Record ab"


def test_build_and_validate_camel_mount_record_roundtrip() -> None:
    db = FakeDb()
    record = build_horse_mount_record(db, {"x": 0.5, "y": 64.0, "z": 0.5}, create_mode="synthetic_full", mount_type="minecraft:camel")
    db.put(record.actor_key, record.actor_value)
    db.put(record.digp_key, record.digp_value)

    validation = validate_horse_mount_write(db, record)

    assert record.mount_type == "minecraft:camel"
    assert record.horse_profile is None
    assert validation["ok"] is True
    assert validation["details"]["attribute_count"] == 11
    assert validation["details"]["expected_definitions"] == [
        "+minecraft:camel",
        "+minecraft:camel_adult",
        "+minecraft:camel_standing",
    ]


def test_normalize_mount_stats_enforces_vanilla_ranges_per_type() -> None:
    assert normalize_mount_stats("minecraft:donkey", None) == {}
    assert normalize_mount_stats("minecraft:donkey", {"health": 22}) == {"health": 22.0}
    assert normalize_mount_stats("minecraft:mule", {"health": "27"}) == {"health": 27.0}
    assert normalize_mount_stats("minecraft:skeleton_horse", {"jump_strength": 0.75}) == {"jump_strength": 0.75}
    assert normalize_mount_stats("minecraft:skeleton_horse", {"jump_strength": ""}) == {}

    with pytest.raises(ValueError, match="zwischen 15 und 30"):
        normalize_mount_stats("minecraft:donkey", {"health": 31})
    with pytest.raises(ValueError, match="zwischen 0.4 und 1"):
        normalize_mount_stats("minecraft:skeleton_horse", {"jump_strength": 0.2})
    with pytest.raises(ValueError, match="kein einstellbares Feld"):
        normalize_mount_stats("minecraft:donkey", {"movement": 0.3})
    with pytest.raises(ValueError, match="kein einstellbares Feld"):
        normalize_mount_stats("minecraft:camel", {"health": 20})


def test_mount_stats_override_written_attributes_and_are_reported() -> None:
    db = FakeDb()
    record = build_horse_mount_record(
        db, {"x": 0.5, "y": 64.0, "z": 0.5}, create_mode="synthetic_full", mount_type="minecraft:donkey", mount_stats={"health": 27}
    )
    tag = nbt.load(record.actor_value, **LOAD_KWARGS).tag
    attributes = {attr["Name"].py_data: attr for attr in tag["Attributes"]}

    assert attributes["minecraft:health"]["Base"].py_data == 27.0
    assert attributes["minecraft:health"]["Max"].py_data == 27.0
    assert {key: record.mount_stats[key] for key in ("health", "movement", "jump_strength")} == {
        "health": 27.0,
        "movement": 0.17499999701976776,
        "jump_strength": 0.5,
    }
    # Temper wird pro Exemplar gewuerfelt und im Record berichtet.
    assert HORSE_TEMPER_MIN <= record.mount_stats["temper"] <= HORSE_TEMPER_MAX
    assert tag["Temper"].py_data == record.mount_stats["temper"]

    skeleton = build_horse_mount_record(
        db, {"x": 0.5, "y": 64.0, "z": 0.5}, create_mode="synthetic_full", mount_type="minecraft:skeleton_horse", mount_stats={"jump_strength": 0.9}
    )
    skeleton_tag = nbt.load(skeleton.actor_value, **LOAD_KWARGS).tag
    skeleton_attrs = {attr["Name"].py_data: attr for attr in skeleton_tag["Attributes"]}

    assert round(skeleton_attrs["minecraft:horse.jump_strength"]["Base"].py_data, 6) == 0.9
    assert skeleton.mount_stats["jump_strength"] == 0.9
    assert skeleton.mount_stats["health"] == 15.0

    with pytest.raises(ValueError, match="nur für Nicht-Pferd-Mounts"):
        build_horse_mount_record(db, {"x": 0.5, "y": 64.0, "z": 0.5}, mount_stats={"health": 20})


def test_build_tamed_mule_actor_nbt_matches_real_record_tag_for_tag() -> None:
    # Referenz: isolierter, im Spiel gezähmter Maultier-Record ohne Konto- oder
    # Personendaten. OwnerNew=-4294967295 ist eine weltinterne Actor-Referenz,
    # keine XUID; Details und Prüfkriterien stehen in tests/data/README.md.
    raw_hex = (Path(__file__).parent / "data" / "mule_tamed_actor_record.hex").read_text(encoding="ascii").strip()
    real = nbt.load(bytes.fromhex(raw_hex), **LOAD_KWARGS).tag
    actor = _actor_key(2, 9)
    suffix = actor_key_suffix(actor)
    raw = build_horse_actor_nbt(
        {"x": 0.5, "y": 64.0, "z": 0.5},
        unique_id_from_actor_key(actor),
        suffix,
        mount_type="minecraft:mule",
        mount_stats={"health": 27.0, "movement": 0.17499999701976776, "jump_strength": 0.5},
        tamed=True,
        owner_unique_id=-4294967295,
    )
    ours = nbt.load(raw, **LOAD_KWARGS).tag

    identity_keys = {"Pos", "Rotation", "UniqueID", "internalComponents"}
    # canPickupItems ist in den Referenz-Records nicht deterministisch
    # (wilder Esel 1, gezähmter Esel 0, wildes Maultier 0, gezähmtes Maultier 1).
    unstable_keys = {"canPickupItems"}
    real_keys = {str(key) for key in real}
    our_keys = {str(key) for key in ours}
    assert our_keys == real_keys
    for key in sorted(real_keys):
        if key in identity_keys or key in unstable_keys:
            continue
        assert _typed(real[key]) == _typed(ours[key]), f"Tag {key} weicht vom echten gezähmten Maultier-Record ab"


def test_build_tamed_donkey_actor_nbt_matches_taming_evidence() -> None:
    actor = _actor_key(2, 9)
    suffix = actor_key_suffix(actor)
    raw = build_horse_actor_nbt(
        {"x": 0.5, "y": 64.0, "z": 0.5}, unique_id_from_actor_key(actor), suffix, mount_type="minecraft:donkey", tamed=True, owner_unique_id=-4294967295
    )
    tag = nbt.load(raw, **LOAD_KWARGS).tag

    assert [item.py_data for item in tag["definitions"]] == [
        "+minecraft:donkey",
        "+minecraft:donkey_adult",
        "-minecraft:donkey_wild",
        "+minecraft:donkey_tamed",
        "+minecraft:donkey_unchested",
    ]
    assert "Temper" not in tag
    assert tag["IsTamed"].py_data == 1
    assert tag["OwnerNew"].py_data == -4294967295
    assert len(tag["ChestItems"]) == 16
    assert [item["Slot"].py_data for item in tag["ChestItems"]] == list(range(16))
    assert tag["InventoryVersion"].py_data
    # Zuchtfähig: Esel bekommt die Breeding-Tags, das sterile Maultier nicht.
    assert "BreedCooldown" in tag and "InLove" in tag and "LoveCause" in tag

    mule_raw = build_horse_actor_nbt(
        {"x": 0.5, "y": 64.0, "z": 0.5}, unique_id_from_actor_key(actor), suffix, mount_type="minecraft:mule", tamed=True, owner_unique_id=-1
    )
    mule_tag = nbt.load(mule_raw, **LOAD_KWARGS).tag
    assert "BreedCooldown" not in mule_tag and "InLove" not in mule_tag and "LoveCause" not in mule_tag
    assert len(mule_tag["ChestItems"]) == 16


def test_tamed_create_only_supported_for_donkey_and_mule() -> None:
    db = FakeDb()

    for mount_type in ("minecraft:horse", "minecraft:skeleton_horse", "minecraft:camel"):
        with pytest.raises(ValueError, match="Gezähmt erzeugen ist nur für"):
            build_horse_mount_record(db, {"x": 0.5, "y": 64.0, "z": 0.5}, mount_type=mount_type, tamed=True)

    record = build_horse_mount_record(
        db, {"x": 0.5, "y": 64.0, "z": 0.5}, create_mode="synthetic_full", mount_type="minecraft:donkey", tamed=True, owner_unique_id=-4294967295
    )
    db.put(record.actor_key, record.actor_value)
    db.put(record.digp_key, record.digp_value)
    validation = validate_horse_mount_write(db, record)

    assert record.tamed is True
    assert record.owner_unique_id == -4294967295
    assert validation["ok"] is True
    assert "+minecraft:donkey_tamed" in validation["details"]["expected_definitions"]
    assert "-minecraft:donkey_wild" in validation["details"]["expected_definitions"]


def test_non_horse_mount_rejects_template_clone_and_unknown_types() -> None:
    db = FakeDb()

    with pytest.raises(ValueError, match="Template-Clone ist nur für Pferde"):
        build_horse_mount_record(db, {"x": 0.5, "y": 64.0, "z": 0.5}, create_mode="template_clone", mount_type="minecraft:donkey")
    with pytest.raises(ValueError, match="Create unterstützt aktuell nur"):
        build_horse_mount_record(db, {"x": 0.5, "y": 64.0, "z": 0.5}, mount_type="minecraft:pig")


def test_build_horse_mount_record_updates_actor_and_digp() -> None:
    existing_actor = _actor_key(3, 7)
    existing_entry = digp_entry_for_actor_key(existing_actor)
    digp_key = digp_key_for_position({"x": 32.0, "y": 70.0, "z": -1.0})
    db = FakeDb({existing_actor: b"old-actor", digp_key: existing_entry})

    record = build_horse_mount_record(db, {"x": 32.0, "y": 70.0, "z": -1.0})
    new_entry = digp_entry_for_actor_key(record.actor_key)
    tag = nbt.load(record.actor_value, **LOAD_KWARGS).tag

    assert record.actor_key == _actor_key(3, 8)
    assert record.digp_key == digp_key
    assert record.digp_value == existing_entry + new_entry
    assert record.unique_id == -12884901880
    storage_key = tag["internalComponents"]["EntityStorageKeyComponent"]["StorageKey"].py_data
    assert nbt.utf8_escape_encoder(storage_key) == actor_key_suffix(record.actor_key)
    assert digp_reference_summary(record.digp_value, new_entry)["contains_actor_suffix"] is True


def test_validate_horse_mount_write_reports_ok_after_puts() -> None:
    db = FakeDb()
    record = build_horse_mount_record(db, {"x": -10.0, "y": 68.0, "z": -62.0}, create_mode="synthetic_full")
    db.put(record.actor_key, record.actor_value)
    db.put(record.digp_key, record.digp_value)

    validation = validate_horse_mount_write(db, record)

    assert validation["ok"] is True
    assert validation["errors"] == []
    assert validation["checks"]["actor_record_exists"] is True
    assert validation["checks"]["actor_value_matches_write_plan"] is True
    assert validation["checks"]["digp_contains_actor_suffix"] is True
    assert validation["checks"]["digp_value_matches_write_plan"] is True
    assert validation["checks"]["digp_key_matches_position"] is True
    assert validation["checks"]["digp_preserves_previous_value"] is True
    assert validation["checks"]["identifier_matches_mount_type"] is True
    assert validation["checks"]["unique_id_matches_actor_key"] is True
    assert validation["checks"]["storage_key_matches_actor_suffix"] is True
    assert validation["details"]["actor_suffix_hex"] == actor_key_suffix(record.actor_key).hex()
    assert validation["details"]["unique_id"] == record.unique_id
    assert validation["details"]["raw_length"] >= 2700


def test_validate_horse_mount_write_rejects_values_that_differ_from_write_plan() -> None:
    db = FakeDb()
    record = build_horse_mount_record(db, {"x": -10.0, "y": 68.0, "z": -62.0}, create_mode="synthetic_full")
    unrelated_entry = digp_entry_for_actor_key(_actor_key(9, 9))
    db.put(record.actor_key, record.actor_value + b"\x00")
    db.put(record.digp_key, record.digp_value + unrelated_entry)

    validation = validate_horse_mount_write(db, record)

    assert validation["ok"] is False
    assert validation["checks"]["actor_value_matches_write_plan"] is False
    assert validation["checks"]["digp_value_matches_write_plan"] is False
    assert any("bytegenau mit dem Schreibplan" in error for error in validation["errors"])


def test_validate_horse_mount_write_accepts_final_workspace_digp_plan() -> None:
    db = FakeDb()
    record = build_horse_mount_record(db, {"x": -10.0, "y": 68.0, "z": -62.0}, create_mode="synthetic_full")
    final_digp_value = record.digp_value + digp_entry_for_actor_key(_actor_key(9, 9))
    db.put(record.actor_key, record.actor_value)
    db.put(record.digp_key, final_digp_value)

    validation = validate_horse_mount_write(db, record, expected_digp_value=final_digp_value)

    assert validation["ok"] is True
    assert validation["checks"]["digp_value_matches_write_plan"] is True


def test_validate_horse_mount_write_rejects_digp_key_for_wrong_position() -> None:
    db = FakeDb()
    record = build_horse_mount_record(db, {"x": -10.0, "y": 68.0, "z": -62.0}, create_mode="synthetic_full")
    wrong_record = replace(record, digp_key=digp_key_for_position({"x": 160.0, "y": 68.0, "z": 160.0}))
    db.put(wrong_record.actor_key, wrong_record.actor_value)
    db.put(wrong_record.digp_key, wrong_record.digp_value)

    validation = validate_horse_mount_write(db, wrong_record)

    assert validation["ok"] is False
    assert validation["checks"]["digp_key_matches_position"] is False
    assert any("finalen Mount-Position" in error for error in validation["errors"])


def test_validate_horse_mount_write_reports_missing_digp() -> None:
    db = FakeDb()
    record = build_horse_mount_record(db, {"x": -10.0, "y": 68.0, "z": -62.0}, create_mode="synthetic_full")
    db.put(record.actor_key, record.actor_value)

    validation = validate_horse_mount_write(db, record)

    assert validation["ok"] is False
    assert validation["checks"]["actor_record_exists"] is True
    assert validation["checks"]["digp_record_exists"] is False
    assert any("digp" in error for error in validation["errors"])


def test_validate_horse_mount_write_rejects_lost_existing_digp_entries() -> None:
    existing_actor = _actor_key(3, 7)
    existing_entry = digp_entry_for_actor_key(existing_actor)
    position = {"x": 32.0, "y": 70.0, "z": -1.0}
    digp_key = digp_key_for_position(position)
    db = FakeDb({existing_actor: b"old-actor", digp_key: existing_entry})
    record = build_horse_mount_record(db, position, create_mode="synthetic_full")
    db.put(record.actor_key, record.actor_value)
    db.put(record.digp_key, digp_entry_for_actor_key(record.actor_key))

    validation = validate_horse_mount_write(db, record)

    assert validation["ok"] is False
    assert validation["checks"]["digp_contains_actor_suffix"] is True
    assert validation["checks"]["digp_preserves_previous_value"] is False
    assert any("bestehende Actor-Referenzen" in error for error in validation["errors"])


def test_build_horse_mount_record_clones_existing_equine_template() -> None:
    template_actor = _actor_key(2, 5)
    template_raw = _template_donkey_raw(unique_id_from_actor_key(template_actor), actor_key_suffix(template_actor))
    db = FakeDb({template_actor: template_raw})

    record = build_horse_mount_record(db, {"x": -10.0, "y": 68.0, "z": -62.0})
    tag = nbt.load(record.actor_value, **LOAD_KWARGS).tag

    assert record.actor_key == _actor_key(2, 6)
    assert tag["identifier"].py_data == "minecraft:horse"
    assert [item.py_data for item in tag["definitions"]][:3] == ["+minecraft:horse", "+minecraft:horse_adult", "+minecraft:horse_wild"]
    assert [round(item.py_data, 3) for item in tag["Pos"]] == [-10.0, 68.0, -62.0]
    assert tag["UniqueID"].py_data == unique_id_from_actor_key(record.actor_key)
    storage_key = tag["internalComponents"]["EntityStorageKeyComponent"]["StorageKey"].py_data
    assert nbt.utf8_escape_encoder(storage_key) == actor_key_suffix(record.actor_key)
    assert isinstance(tag["Armor"], nbt.ListTag)
    assert isinstance(tag["Mainhand"], nbt.ListTag)
    assert isinstance(tag["Offhand"], nbt.ListTag)
    assert "Age" not in tag
    assert "GrowthPaused" not in tag
