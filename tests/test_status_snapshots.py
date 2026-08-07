import json
from pathlib import Path
from types import SimpleNamespace

from mcbe_editor import item_db_verification, status_snapshots


def _config(tmp_path, **overrides):
    defaults = {
        "mode": "local",
        "worlds_root": str(tmp_path / "worlds"),
        "server_name": "Bedrock",
        "server_host": "127.0.0.1",
        "server_port": 19132,
        "require_server_offline": True,
        "allow_edit_while_online": False,
        "allowed_origins": ("http://localhost:5000",),
        "data_root": str(tmp_path / "data"),
        "item_db_path": str(tmp_path / "data" / "item_db.json"),
        "update_cache_dir": str(tmp_path / "cache"),
        "source_version_path": str(tmp_path / "data" / "source_version.json"),
        "source_version_history_path": str(tmp_path / "data" / "source_version_history.json"),
        "backup_root": str(tmp_path / "backups"),
        "max_backups_per_world": 5,
        "settings_path": str(tmp_path / "settings.json"),
        "presence_conflict_guard_enabled": True,
        "secret_key_configured": True,
        "session_cookie_secure": False,
        "startup_security_report": True,
        "startup_network_check": False,
        "startup_network_check_timeout": 1.5,
        "fail_on_insecure_config": False,
        "trust_proxy_headers": False,
        "setup_path": str(tmp_path / "setup.json"),
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_source_version_history_entries_filters_non_dict_entries(tmp_path):
    path = tmp_path / "history.json"
    path.write_text(json.dumps([{"id": 1}, "skip", {"id": 2}]), encoding="utf-8")

    result = status_snapshots.source_version_history_entries(str(path), tmp_path)

    assert result == [{"id": 1}, {"id": 2}]


def test_public_app_config_uses_null_username_when_auth_disabled(tmp_path):
    config = _config(tmp_path)

    result = status_snapshots.public_app_config(
        config,
        bind_host="127.0.0.1",
        bind_port=5000,
        auth_enabled=False,
        auth_username="admin",
        setup_status={"required": False},
        distribution={"kind": "source"},
        data_root_status={"status": "ok"},
    )

    assert result["auth_enabled"] is False
    assert result["auth_username"] is None
    assert result["allowed_origins"] == ["http://localhost:5000"]
    assert result["setup"] == {"required": False}


def test_item_db_status_snapshot_reports_metadata_counts_and_paths(tmp_path):
    config = _config(tmp_path)
    item_db = tmp_path / "data" / "item_db.json"
    item_db.parent.mkdir(parents=True)
    item_db.write_text("{}", encoding="utf-8")
    source_version = tmp_path / "data" / "source_version.json"
    source_version.write_text(
        json.dumps({"resource_pack_release": "1.21", "generated_at": "2026-01-01"}),
        encoding="utf-8",
    )
    history = tmp_path / "data" / "source_version_history.json"
    history.write_text(json.dumps([{"id": 1}]), encoding="utf-8")
    item_data = SimpleNamespace(
        ITEM_DB_SOURCE_PATH=str(item_db),
        ITEM_DB_SCHEMA_VERSION=1,
        ITEMS={"minecraft:stone": {}},
        COMPAT_ITEM_ALIASES={"minecraft:stone_legacy": "minecraft:stone"},
        EFFECTS={1: "Speed"},
        ENCHANTMENTS={1: "Sharpness"},
        ITEM_COMPONENTS={
            "enchantable": {"minecraft:test_spear": {"slot": "melee_spear", "value": 10}},
            "wearable": {"minecraft:test_hat": {"slot": "slot.armor.head"}},
        },
        ENCHANTMENT_COMPATIBLE_SLOTS={1: ["sword"]},
        ENCHANTMENT_COMPATIBILITY_SCHEMA_VERSION=2,
        ENCHANTMENT_COMPATIBILITY_SOURCE_PATH="compat.json",
        ENCHANTMENT_COMPATIBILITY_SOURCES=["test"],
    )

    result = status_snapshots.item_db_status_snapshot(config, item_data, tmp_path)

    assert result["status"] == "ok"
    assert result["source_version_present"] is True
    assert result["verification"]["verified"] is False
    assert result["verification"]["reason"] == "missing"
    assert result["counts"]["items"] == 1
    assert result["counts"]["enchantment_compatibility"] == 1
    assert result["counts"]["item_components"] == 2
    assert result["item_component_counts"]["enchantable"] == 1
    assert result["item_component_counts"]["wearable"] == 1
    assert result["history_count"] == 1
    assert result["is_configured_persistent"] is True
    assert result["bundled_path"] == str(tmp_path / "mcbe_editor" / "resources" / "item_db.json")


def test_item_db_status_snapshot_detects_the_initial_bundled_metadata_copy(tmp_path):
    config = _config(tmp_path)
    item_db = tmp_path / "data" / "item_db.json"
    item_db.parent.mkdir(parents=True)
    item_db.write_text("{}", encoding="utf-8")
    metadata = {"resource_pack_release": "1.21", "generated_at": "2026-01-01"}
    (tmp_path / "source_version.json").write_text(json.dumps(metadata), encoding="utf-8")
    Path(config.source_version_path).write_text(json.dumps(metadata), encoding="utf-8")
    item_data = SimpleNamespace(ITEM_DB_SOURCE_PATH=str(item_db))

    initial = status_snapshots.item_db_status_snapshot(config, item_data, tmp_path)
    assert initial["matches_bundled_snapshot"] is True
    assert initial["verification"]["verified"] is False

    Path(config.source_version_path).write_text(json.dumps({**metadata, "generated_at": "2026-02-01"}), encoding="utf-8")
    updated = status_snapshots.item_db_status_snapshot(config, item_data, tmp_path)
    assert updated["matches_bundled_snapshot"] is False


def test_item_db_status_snapshot_binds_verification_to_database_and_source(tmp_path):
    config = _config(tmp_path)
    item_db = Path(config.item_db_path)
    item_db.parent.mkdir(parents=True)
    item_db.write_text('{"items":{"minecraft:stone":["Stein","Stone"]}}', encoding="utf-8")
    metadata = {
        "resource_pack_release": "1.21",
        "resource_pack_asset": "bedrock-samples.zip",
        "resource_pack_asset_size": 123,
        "resource_pack_url": "https://example.test/bedrock-samples.zip",
        "generated_at": "2026-01-01T00:00:00+00:00",
    }
    verified = item_db_verification.attach_item_db_verification(
        metadata,
        item_db,
        verified_at="2026-01-02T00:00:00+00:00",
    )
    Path(config.source_version_path).write_text(json.dumps(verified), encoding="utf-8")
    item_data = SimpleNamespace(ITEM_DB_SOURCE_PATH=str(item_db))

    current = status_snapshots.item_db_status_snapshot(config, item_data, tmp_path)
    assert current["verification"]["verified"] is True
    assert current["verification"]["reason"] == "verified"
    assert current["verification"]["verified_at"] == "2026-01-02T00:00:00+00:00"

    item_db.write_text('{"items":{}}', encoding="utf-8")
    changed_db = status_snapshots.item_db_status_snapshot(config, item_data, tmp_path)
    assert changed_db["verification"]["verified"] is False
    assert changed_db["verification"]["reason"] == "item-db-changed"

    item_db.write_text('{"items":{"minecraft:stone":["Stein","Stone"]}}', encoding="utf-8")
    verified["resource_pack_release"] = "1.22"
    Path(config.source_version_path).write_text(json.dumps(verified), encoding="utf-8")
    changed_source = status_snapshots.item_db_status_snapshot(config, item_data, tmp_path)
    assert changed_source["verification"]["verified"] is False
    assert changed_source["verification"]["reason"] == "source-changed"


def test_runtime_status_snapshot_builds_expected_sections(tmp_path):
    config = _config(tmp_path, startup_network_check=True)

    result = status_snapshots.runtime_status_snapshot(
        config,
        version="1.2.3",
        distribution={"kind": "source"},
        bind_host="0.0.0.0",
        bind_port=5000,
        auth_enabled=True,
        auth_username="admin",
        stable_secret_key_configured=True,
        uid_label="1000",
        setup_status={"required": False},
        audit_log_status={"enabled": True},
        worlds_root_status={"status": "ok"},
        data_root_status={"status": "ok"},
        item_db_status={"status": "ok"},
        write_gate_setup_status={"status": "ok"},
        outbound_update_hosts=("github.com",),
    )

    assert result["version"] == "1.2.3"
    assert result["auth"]["username"] == "admin"
    assert result["csrf"]["mode"] == "per-session"
    assert result["runtime"]["outbound_network_check"]["hosts"] == ["github.com"]
    assert result["paths"]["worlds_root_status"] == {"status": "ok"}


def test_status_json_readers_tolerate_invalid_utf8(tmp_path):
    path = tmp_path / "broken.json"
    path.write_bytes(b"\xff\xfe")

    assert status_snapshots.read_json_dict(str(path)) == {}
    assert status_snapshots.read_json_list(str(path)) == []


def test_status_json_readers_tolerate_excessive_nesting(tmp_path):
    path = tmp_path / "deep.json"
    path.write_text('{"x":' * 10000 + "0" + "}" * 10000, encoding="utf-8")

    assert status_snapshots.read_json_dict(str(path)) == {}
    assert status_snapshots.read_json_list(str(path)) == []
