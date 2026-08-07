import json
import os
from mcbe_editor.icons import _MAX_FILE_BYTES, scan_icons
import pytest


@pytest.fixture(autouse=True)
def isolate_vanilla_icon_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("MCBE_DATA_ROOT", str(tmp_path / "data_root"))
    monkeypatch.delenv("MCBE_ICON_CACHE_ROOT", raising=False)


def test_local_icon_scan_uses_configured_roots(monkeypatch, tmp_path):
    root = tmp_path / "pack" / "textures" / "items"
    root.mkdir(parents=True)
    (root / "diamond_sword.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    monkeypatch.setenv("MCBE_ICON_ROOTS", str(tmp_path / "pack"))

    result = scan_icons(["minecraft:diamond_sword"])

    assert result["success"] is True
    assert result["count"] == 1
    assert "minecraft:diamond_sword" in result["icons"]
    assert result["icons"]["minecraft:diamond_sword"]["url"].startswith("/api/icons/")


def test_directory_icon_token_changes_when_cached_png_is_replaced(monkeypatch, tmp_path):
    root = tmp_path / "pack" / "textures" / "items"
    root.mkdir(parents=True)
    icon = root / "stone.png"
    icon.write_bytes(b"first")
    monkeypatch.setenv("MCBE_ICON_ROOTS", str(tmp_path / "pack"))
    first = scan_icons(["minecraft:stone"], force=True)

    icon.write_bytes(b"second-version")
    second = scan_icons(["minecraft:stone"], force=True)

    assert first["icons"]["minecraft:stone"]["token"] != second["icons"]["minecraft:stone"]["token"]


def test_internal_display_assets_are_separate_from_item_icons(monkeypatch, tmp_path):
    item_root = tmp_path / "pack" / "textures" / "items"
    display_root = tmp_path / "pack" / "textures" / "display"
    item_root.mkdir(parents=True)
    display_root.mkdir(parents=True)
    (item_root / "apple.png").write_bytes(b"apple")
    (display_root / "axolotl_gold.png").write_bytes(b"axolotl")
    monkeypatch.setenv("MCBE_ICON_ROOTS", str(tmp_path / "pack"))

    first = scan_icons(["minecraft:apple"], force=True)
    second = scan_icons(["minecraft:apple"])

    assert first["count"] == 1
    assert first["display_count"] == 1
    assert "minecraft:entity_axolotl_gold" not in first["icons"]
    assert "mcbe:axolotl_gold" in first["display_icons"]
    assert second["cache"]["state"] == "hit"
    assert "mcbe:axolotl_gold" in second["display_icons"]


def test_local_icon_scan_ignores_non_texture_files(monkeypatch, tmp_path):
    root = tmp_path / "pack"
    root.mkdir()
    (root / "diamond_sword.png").write_bytes(b"fake")
    monkeypatch.setenv("MCBE_ICON_ROOTS", str(root))

    result = scan_icons(["minecraft:diamond_sword"])

    assert result["count"] == 0


def test_icon_scan_reports_unreadable_directory_source(monkeypatch, tmp_path):
    from pathlib import Path

    import mcbe_editor.icons as icons_module

    root = tmp_path / "pack"
    root.mkdir()
    monkeypatch.setenv("MCBE_ICON_ROOTS", str(root))
    real_scandir = icons_module.os.scandir

    def denied(path):
        # os.scandir also accepts a directory file descriptor on POSIX. Pytest's
        # temporary-directory cleanup uses that form, so preserve the full API
        # contract while rejecting only the icon source under test.
        if isinstance(path, (str, os.PathLike)) and Path(path) == root:
            raise PermissionError("denied")
        return real_scandir(path)

    monkeypatch.setattr(icons_module.os, "scandir", denied)

    result = scan_icons([], force=True)

    source = next(source for source in result["sources"] if source["path"] == str(root.resolve()))
    assert source["status"] == "warning"
    assert source["warning_count"] == 1
    assert any("PermissionError" in warning for warning in result["warnings"])


from mcbe_editor.icons import add_icon_source, load_icon_sources, remove_icon_source
import zipfile


def test_icon_source_config_persists_only_paths(tmp_path):
    pack = tmp_path / "pack" / "textures" / "items"
    pack.mkdir(parents=True)
    settings = tmp_path / "icon_sources.json"
    added = add_icon_source(str(settings), str(tmp_path / "pack"))

    assert added["path"].endswith("pack")
    state = load_icon_sources(str(settings))
    assert state["sources"][0]["path"].endswith("pack")
    assert "textures" not in settings.read_text(encoding="utf-8")

    remove_icon_source(str(settings), state["sources"][0]["path"])
    assert load_icon_sources(str(settings))["sources"] == []


def test_parallel_icon_source_additions_are_serialized(monkeypatch, tmp_path):
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path

    import mcbe_editor.icons as icons_module

    settings = tmp_path / "icon_sources.json"
    packs = [tmp_path / "pack_a", tmp_path / "pack_b"]
    for pack in packs:
        pack.mkdir()

    original_save = icons_module.save_icon_sources
    state_lock = threading.Lock()
    active = 0
    max_active = 0

    def slow_save(*args, **kwargs):
        nonlocal active, max_active
        with state_lock:
            active += 1
            max_active = max(max_active, active)
        try:
            time.sleep(0.05)
            return original_save(*args, **kwargs)
        finally:
            with state_lock:
                active -= 1

    monkeypatch.setattr(icons_module, "save_icon_sources", slow_save)
    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(lambda pack: icons_module.add_icon_source(str(settings), str(pack)), packs))

    assert max_active == 1
    assert {Path(source["path"]).name for source in load_icon_sources(str(settings))["sources"]} == {"pack_a", "pack_b"}


def test_icon_scan_supports_manual_mcpack_archive(monkeypatch, tmp_path):
    monkeypatch.delenv("MCBE_ICON_ROOTS", raising=False)
    pack = tmp_path / "test.mcpack"
    with zipfile.ZipFile(pack, "w") as zf:
        zf.writestr("textures/items/apple.png", b"\x89PNG\r\n\x1a\n")
    settings = tmp_path / "icon_sources.json"
    add_icon_source(str(settings), str(pack))

    result = scan_icons(["minecraft:apple"], settings_path=str(settings))

    assert result["success"] is True
    assert result["count"] == 1
    assert "minecraft:apple" in result["icons"]
    assert result["sources"][0]["manual"] is True
    assert result["sources"][0]["archive"] is True


def test_icon_candidate_revalidates_directory_file_before_read(monkeypatch, tmp_path):
    monkeypatch.delenv("MCBE_ICON_ROOTS", raising=False)
    root = tmp_path / "pack" / "textures" / "items"
    root.mkdir(parents=True)
    icon = root / "apple.png"
    icon.write_bytes(b"\x89PNG\r\n\x1a\n")
    settings = tmp_path / "icon_sources.json"
    add_icon_source(str(settings), str(tmp_path / "pack"))
    result = scan_icons(["minecraft:apple"], settings_path=str(settings), force=True)
    token = result["icons"]["minecraft:apple"]["token"]

    icon.write_bytes(b"x" * (_MAX_FILE_BYTES + 1))

    with pytest.raises(ValueError, match="zu groß|verändert"):
        result["_by_token"][token].read_bytes()


def test_icon_candidate_revalidates_archive_member_before_read(monkeypatch, tmp_path):
    monkeypatch.delenv("MCBE_ICON_ROOTS", raising=False)
    pack = tmp_path / "test.mcpack"
    with zipfile.ZipFile(pack, "w") as zf:
        zf.writestr("textures/items/apple.png", b"\x89PNG\r\n\x1a\n")
    settings = tmp_path / "icon_sources.json"
    add_icon_source(str(settings), str(pack))
    result = scan_icons(["minecraft:apple"], settings_path=str(settings), force=True)
    token = result["icons"]["minecraft:apple"]["token"]
    with zipfile.ZipFile(pack, "w") as zf:
        zf.writestr("textures/items/apple.png", b"x" * (_MAX_FILE_BYTES + 1))

    with pytest.raises(ValueError, match="Archiv wurde seit dem Scan verändert"):
        result["_by_token"][token].read_bytes()


def test_icon_route_reports_changed_icon_as_payload_too_large(monkeypatch):
    import main

    class ChangedIcon:
        suffix = ".png"

        def read_bytes(self):
            raise ValueError("Icon-Datei ist zu groß oder wurde seit dem Scan verändert.")

    monkeypatch.setitem(main.ICON_INDEX, "_by_token", {"changed-token": ChangedIcon()})

    response = main.app.test_client().get("/api/icons/changed-token")

    assert response.status_code == 413
    assert response.get_json()["success"] is False


def test_icon_scan_uses_cache_on_second_run(monkeypatch, tmp_path):
    monkeypatch.delenv("MCBE_ICON_ROOTS", raising=False)
    root = tmp_path / "pack" / "textures" / "items"
    root.mkdir(parents=True)
    (root / "apple.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    settings = tmp_path / "icon_sources.json"
    add_icon_source(str(settings), str(tmp_path / "pack"))

    first = scan_icons(["minecraft:apple"], settings_path=str(settings), force=True)
    second = scan_icons(["minecraft:apple"], settings_path=str(settings))

    assert first["cache"]["state"] == "rebuilt"
    assert second["cache"]["state"] == "hit"
    assert second["count"] == 1
    assert "minecraft:apple" in second["icons"]
    assert (tmp_path / "icon_index_cache.json").exists()


def test_read_only_icon_status_loads_published_cache_without_scan(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from mcbe_editor import icon_api_routes

    monkeypatch.delenv("MCBE_ICON_ROOTS", raising=False)
    root = tmp_path / "pack" / "textures" / "items"
    root.mkdir(parents=True)
    (root / "apple.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    settings = tmp_path / "icon_sources.json"
    add_icon_source(str(settings), str(tmp_path / "pack"))
    scan_icons(["minecraft:apple"], settings_path=str(settings), force=True)

    stored = {}
    deps = SimpleNamespace(
        read_only=True,
        settings_path=str(settings),
        get_icon_index=lambda: stored,
        set_icon_index=lambda value: stored.update(value),
        jsonify=lambda value: value,
        log_api_exception=lambda *_args: None,
    )
    monkeypatch.setattr(icon_api_routes, "scan_icons", lambda *_args, **_kwargs: pytest.fail("Read-only-Status darf keinen Scan starten."))

    result = icon_api_routes.icons_status(deps)

    assert result["cache"]["state"] == "hit"
    assert "minecraft:apple" in result["icons"]
    assert "_by_token" in stored


def test_public_icon_index_hides_internal_fields():
    """Interne Felder dürfen nicht über die HTTP-Schnittstelle gehen.

    ``_by_token`` ist der Server-Lookup, ``display_icons`` hat seit dem Entfernen
    des Varianten-Badges keinen Client-Konsumenten mehr. Der interne Index behält
    beide, damit Icon-Cache und Manifest-Schema unverändert gültig bleiben.
    """

    from mcbe_editor import icon_api_routes

    index = {
        "success": True,
        "icons": {"minecraft:apple": {"url": "/api/icons/abc"}},
        "display_icons": {"mcbe:axolotl_gold": {"url": "/api/icons/def"}},
        "_by_token": {"abc": object()},
        "count": 1,
    }

    public = icon_api_routes._public_icon_index(index)

    assert "display_icons" not in public
    assert "_by_token" not in public
    assert public["icons"] == {"minecraft:apple": {"url": "/api/icons/abc"}}
    assert public["count"] == 1
    # Die Quelle bleibt unangetastet, der interne Pfad also intakt.
    assert "display_icons" in index


def test_icon_scan_reports_health_preview(monkeypatch, tmp_path):
    monkeypatch.delenv("MCBE_ICON_ROOTS", raising=False)
    root = tmp_path / "pack" / "textures" / "items"
    root.mkdir(parents=True)
    (root / "diamond_sword.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    settings = tmp_path / "icon_sources.json"
    add_icon_source(str(settings), str(tmp_path / "pack"))

    result = scan_icons(["minecraft:diamond_sword"], settings_path=str(settings), force=True)

    assert result["health"]["status"] == "ok"
    assert result["health"]["sample_found"] >= 1
    assert any(row["item_id"] == "minecraft:diamond_sword" and row["found"] for row in result["health"]["sample"])


def test_icon_scan_uses_generated_vanilla_cache(monkeypatch, tmp_path):
    monkeypatch.delenv("MCBE_ICON_ROOTS", raising=False)
    monkeypatch.delenv("MCBE_ICON_CACHE_ROOT", raising=False)
    monkeypatch.setenv("MCBE_DATA_ROOT", str(tmp_path / "data"))
    root = tmp_path / "data" / "icons" / "vanilla" / "textures" / "items"
    root.mkdir(parents=True)
    (root / "apple.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    result = scan_icons(["minecraft:apple"], force=True)

    assert result["success"] is True
    assert "minecraft:apple" in result["icons"]
    assert any(source.get("vanilla") and source.get("exists") for source in result["sources"])


def test_icon_scan_adds_damage_variant_aliases(monkeypatch, tmp_path):
    monkeypatch.delenv("MCBE_ICON_ROOTS", raising=False)
    monkeypatch.delenv("MCBE_ICON_CACHE_ROOT", raising=False)
    monkeypatch.setenv("MCBE_DATA_ROOT", str(tmp_path / "data"))
    root = tmp_path / "data" / "icons" / "vanilla" / "textures" / "items"
    root.mkdir(parents=True)
    (root / "red_carpet.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    result = scan_icons(["minecraft:carpet"], force=True)

    assert result["variant_aliases"] >= 1
    assert result["icons"]["minecraft:carpet#14"]["token"] == result["icons"]["minecraft:red_carpet"]["token"]


def test_icon_cache_roundtrip_preserves_target_and_variant_alias_with_shared_token(monkeypatch, tmp_path):
    monkeypatch.delenv("MCBE_ICON_ROOTS", raising=False)
    monkeypatch.delenv("MCBE_ICON_CACHE_ROOT", raising=False)
    monkeypatch.setenv("MCBE_DATA_ROOT", str(tmp_path / "data"))
    root = tmp_path / "data" / "icons" / "vanilla" / "textures" / "items"
    root.mkdir(parents=True)
    (root / "blue_dye.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    settings = tmp_path / "data" / "icon_sources.json"

    rebuilt = scan_icons(["minecraft:blue_dye"], settings_path=str(settings), force=True)
    cached = scan_icons(["minecraft:blue_dye"], settings_path=str(settings))

    assert rebuilt["icons"]["minecraft:blue_dye"]["token"] == rebuilt["icons"]["minecraft:dye#4"]["token"]
    assert cached["cache"]["state"] == "hit"
    assert cached["icons"]["minecraft:blue_dye"]["source"] == "Vanilla Icons aus Mojang/bedrock-samples"
    assert cached["icons"]["minecraft:dye#4"]["source"].endswith("Variantenalias")
    assert cached["icons"]["minecraft:blue_dye"]["token"] == cached["icons"]["minecraft:dye#4"]["token"]


def test_icon_scan_aliases_heads_horse_armor_and_leaves_banner_to_fallback(monkeypatch, tmp_path):
    monkeypatch.delenv("MCBE_ICON_ROOTS", raising=False)
    monkeypatch.delenv("MCBE_ICON_CACHE_ROOT", raising=False)
    monkeypatch.setenv("MCBE_DATA_ROOT", str(tmp_path / "data"))
    root = tmp_path / "data" / "icons" / "vanilla" / "textures" / "items"
    root.mkdir(parents=True)
    (root / "skull.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (root / "leather_horse_armor.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (root / "leather_helmet.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (root / "shield.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (root / "barrier.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    result = scan_icons(
        [
            "minecraft:player_head",
            "minecraft:creeper_head",
            "minecraft:horsearmorleather",
            "minecraft:leather_helmet",
            "minecraft:shield",
            "minecraft:barrier",
            "minecraft:banner",
        ],
        force=True,
    )

    # Direkte Sprites für die Spezialfälle mit vorhandener Textur.
    for item_id in ("minecraft:leather_helmet", "minecraft:shield", "minecraft:barrier"):
        assert item_id in result["icons"], item_id
    # Mob-Köpfe und Legacy-Pferderüstung nutzen Alias-Sprites.
    assert result["icons"]["minecraft:player_head"]["token"] == result["icons"]["minecraft:skull"]["token"]
    assert result["icons"]["minecraft:creeper_head"]["token"] == result["icons"]["minecraft:skull"]["token"]
    assert result["icons"]["minecraft:horsearmorleather"]["token"] == result["icons"]["minecraft:leather_horse_armor"]["token"]
    # Banner haben kein Item-Sprite und fallen bewusst aufs Emoji-Fallback zurück.
    assert "minecraft:banner" not in result["icons"]


def test_icon_scan_aliases_tuff_brick_variants_to_shared_vanilla_texture(monkeypatch, tmp_path):
    monkeypatch.delenv("MCBE_ICON_ROOTS", raising=False)
    monkeypatch.delenv("MCBE_ICON_CACHE_ROOT", raising=False)
    monkeypatch.setenv("MCBE_DATA_ROOT", str(tmp_path / "data"))
    root = tmp_path / "data" / "icons" / "vanilla" / "textures" / "items"
    root.mkdir(parents=True)
    (root / "tuff_bricks.png").write_bytes(b"tuff-bricks")

    result = scan_icons(
        [
            "minecraft:tuff_bricks",
            "minecraft:tuff_brick_stairs",
            "minecraft:tuff_brick_slab",
            "minecraft:tuff_brick_wall",
        ],
        force=True,
    )

    target = result["icons"]["minecraft:tuff_bricks"]["token"]
    for item_id in ("minecraft:tuff_brick_stairs", "minecraft:tuff_brick_slab", "minecraft:tuff_brick_wall"):
        assert result["icons"][item_id]["token"] == target


def test_icon_scan_aliases_bedrock_potion_texture_names(monkeypatch, tmp_path):
    monkeypatch.delenv("MCBE_ICON_ROOTS", raising=False)
    monkeypatch.delenv("MCBE_ICON_CACHE_ROOT", raising=False)
    monkeypatch.setenv("MCBE_DATA_ROOT", str(tmp_path / "data"))
    root = tmp_path / "data" / "icons" / "vanilla" / "textures" / "items"
    root.mkdir(parents=True)
    (root / "potion_bottle_drinkable.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (root / "potion_bottle_empty.png").write_bytes(b"water")
    (root / "potion_bottle_splash.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (root / "potion_bottle_lingering.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (root / "potion_bottle_lingering_empty.png").write_bytes(b"lingering water")
    (root / "potion_bottle_fireResistance.png").write_bytes(b"fire")
    (root / "potion_bottle_splash_poison.png").write_bytes(b"poison")
    (root / "potion_bottle_lingering_nightVision.png").write_bytes(b"night")
    (root / "tipped_arrow_swift.png").write_bytes(b"swift")

    result = scan_icons(["minecraft:potion", "minecraft:splash_potion", "minecraft:lingering_potion", "minecraft:tipped_arrow"], force=True)

    assert result["variant_aliases"] >= 3
    assert result["icons"]["minecraft:potion"]["token"] == result["icons"]["minecraft:potion_bottle_drinkable"]["token"]
    assert result["icons"]["minecraft:splash_potion"]["token"] == result["icons"]["minecraft:potion_bottle_splash"]["token"]
    assert result["icons"]["minecraft:lingering_potion"]["token"] == result["icons"]["minecraft:potion_bottle_lingering"]["token"]
    assert result["icons"]["minecraft:potion#0"]["token"] == result["icons"]["minecraft:potion_bottle_empty"]["token"]
    for damage in range(5):
        assert result["icons"][f"minecraft:splash_potion#{damage}"]["token"] == result["icons"]["minecraft:potion_bottle_splash"]["token"]
    assert result["icons"]["minecraft:potion#12"]["token"] == result["icons"]["minecraft:potion_bottle_fireresistance"]["token"]
    assert result["icons"]["minecraft:splash_potion#25"]["token"] == result["icons"]["minecraft:potion_bottle_splash_poison"]["token"]
    assert result["icons"]["minecraft:lingering_potion#0"]["token"] == result["icons"]["minecraft:potion_bottle_lingering_empty"]["token"]
    assert result["icons"]["minecraft:lingering_potion#5"]["token"] == result["icons"]["minecraft:potion_bottle_lingering_nightvision"]["token"]
    assert result["icons"]["minecraft:tipped_arrow#14"]["token"] == result["icons"]["minecraft:tipped_arrow_swift"]["token"]


from mcbe_editor.icons import move_icon_source


def test_manual_icon_source_priority_can_move(monkeypatch, tmp_path):
    monkeypatch.delenv("MCBE_ICON_ROOTS", raising=False)
    pack_a = tmp_path / "pack_a" / "textures" / "items"
    pack_b = tmp_path / "pack_b" / "textures" / "items"
    pack_a.mkdir(parents=True)
    pack_b.mkdir(parents=True)
    (pack_a / "apple.png").write_bytes(b"a")
    (pack_b / "apple.png").write_bytes(b"b")
    settings = tmp_path / "icon_sources.json"
    add_icon_source(str(settings), str(tmp_path / "pack_a"))
    add_icon_source(str(settings), str(tmp_path / "pack_b"))

    state = load_icon_sources(str(settings))
    assert state["sources"][0]["path"].endswith("pack_b")

    move_icon_source(str(settings), state["sources"][1]["path"], "up")
    moved = load_icon_sources(str(settings))

    assert moved["sources"][0]["path"].endswith("pack_a")
    assert [src["priority"] for src in moved["sources"]] == [0, 1]


def test_parallel_icon_scans_are_serialized(monkeypatch, tmp_path):
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor
    from types import SimpleNamespace

    from mcbe_editor import icon_api_routes

    state_lock = threading.Lock()
    active = 0
    maximum = 0
    serial = 0

    def slow_scan(*_args, **_kwargs):
        nonlocal active, maximum, serial
        with state_lock:
            active += 1
            maximum = max(maximum, active)
            serial += 1
            current = serial
        time.sleep(0.05)
        with state_lock:
            active -= 1
        return {"success": True, "icons": {"serial": current}, "count": 1, "_by_token": {}}

    monkeypatch.setattr(icon_api_routes, "scan_icons", slow_scan)
    index = {}
    deps = SimpleNamespace(
        read_only=False,
        known_item_ids=lambda: [],
        settings_path=str(tmp_path / "settings.json"),
        set_icon_index=lambda value: index.update(value),
        jsonify=lambda value: value,
        log_api_exception=lambda *_args: None,
        api_error=lambda message, status=400: ({"error": message}, status),
        json_string=lambda data, key, default="": data.get(key, default),
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: icon_api_routes.icons_scan({}, deps), range(2)))

    assert maximum == 1
    assert len(results) == 2
    assert index["icons"]["serial"] == 2


def test_icon_file_does_not_wait_for_long_running_icon_operation(tmp_path):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from types import SimpleNamespace

    from mcbe_editor import icon_api_routes

    icon_path = tmp_path / "stone.png"
    icon_path.write_bytes(b"png")
    candidate = SimpleNamespace(suffix=".png", read_bytes=icon_path.read_bytes)
    deps = SimpleNamespace(
        read_only=False,
        get_icon_index=lambda: {"_by_token": {"stone": candidate}},
        response=lambda data, **kwargs: (data, kwargs),
        api_error=lambda message, status=400: (message, status),
        log_api_exception=lambda *_args: None,
    )
    entered = threading.Event()

    def read_icon():
        entered.set()
        return icon_api_routes.icon_file("stone", deps)

    executor = ThreadPoolExecutor(max_workers=1)
    icon_api_routes._ICON_OPERATION_LOCK.acquire()
    try:
        future = executor.submit(read_icon)
        assert entered.wait(timeout=1)
        data, response_kwargs = future.result(timeout=1)
    finally:
        icon_api_routes._ICON_OPERATION_LOCK.release()
        executor.shutdown(wait=True)

    assert data == b"png"
    assert response_kwargs["mimetype"] == "image/png"


def test_parallel_vanilla_icon_updates_are_serialized(monkeypatch, tmp_path):
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor
    from types import SimpleNamespace

    from mcbe_editor import icon_api_routes

    state_lock = threading.Lock()
    active = 0
    maximum = 0

    def slow_update(**_kwargs):
        nonlocal active, maximum
        with state_lock:
            active += 1
            maximum = max(maximum, active)
        time.sleep(0.05)
        with state_lock:
            active -= 1
        return 1, "expected test failure"

    deps = SimpleNamespace(
        data_root=str(tmp_path),
        json_bool=lambda data, key, default: data.get(key, default),
        run_update_icons=slow_update,
        looks_like_network_failure=lambda _output: False,
        audit_event=lambda *_args, **_kwargs: None,
        jsonify=lambda value: value,
        api_error=lambda message, status=400: ({"error": message}, status),
        log_api_exception=lambda *_args: None,
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: icon_api_routes.icons_vanilla_update({}, deps), range(2)))

    assert maximum == 1
    assert all(result["success"] is False for result in results)


def test_icon_sources_tolerate_invalid_priority_in_settings(tmp_path):
    settings = tmp_path / "icon_sources.json"
    settings.write_text(
        '{"version":2,"sources":[{"path":"/tmp/icons","enabled":true,"priority":"broken"}]}',
        encoding="utf-8",
    )

    state = load_icon_sources(str(settings))

    assert state["sources"][0]["priority"] == 0


def test_icon_index_cache_tolerates_invalid_numeric_counters(tmp_path):
    from mcbe_editor.icons import _load_cached_result

    cache = tmp_path / "icon_index_cache.json"
    cache.write_text(
        '{"version":5,"sources_signature":"sig","sources":[],"icons":{},"warnings":[],"scanned_files":"broken","variant_aliases":"broken"}',
        encoding="utf-8",
    )

    result = _load_cached_result(cache, "sig", None)

    assert result is not None
    assert result["scanned_files"] == 0
    assert result["variant_aliases"] == 0


def test_icon_index_cache_rejects_non_object_source_entries(tmp_path):
    from mcbe_editor.icons import _load_cached_result

    cache = tmp_path / "icon_index_cache.json"
    cache.write_text(
        json.dumps(
            {
                "version": 4,
                "sources_signature": "sig",
                "sources": ["broken"],
                "icons": {},
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )

    assert _load_cached_result(cache, "sig", None) is None


def test_vanilla_icon_update_reports_rescan_failure_after_successful_publish(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from mcbe_editor import icon_api_routes

    manifest_dir = tmp_path / "icons" / "vanilla"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "manifest.json").write_text('{"mapped_items": 1, "known_items": 1}', encoding="utf-8")
    scan_error = RuntimeError("scan failed")
    monkeypatch.setattr(icon_api_routes, "_scan_and_store_icons", lambda *_args, **_kwargs: (_ for _ in ()).throw(scan_error))
    logged = []
    audit_events = []
    deps = SimpleNamespace(
        data_root=str(tmp_path),
        json_bool=lambda data, key, default: data.get(key, default),
        run_update_icons=lambda **_kwargs: (0, "ok"),
        looks_like_network_failure=lambda _output: False,
        audit_event=lambda *args, **kwargs: audit_events.append((args, kwargs)),
        jsonify=lambda value: value,
        api_error=lambda message, status=400: ({"error": message}, status),
        log_api_exception=lambda operation, exc: logged.append((operation, exc)),
    )

    result = icon_api_routes.icons_vanilla_update({}, deps)

    assert result["success"] is True
    assert result["update_committed"] is True
    assert "erneut scannen" in result["scan_warning"]
    assert logged == [("icons.vanilla_update_rescan", scan_error)]
    assert audit_events == [
        (
            ("icons.vanilla_update", "partial"),
            {"details": {"use_cache": True, "force": False, "returncode": 0, "index_refreshed": False}},
        )
    ]


def test_icon_source_add_audits_partial_when_rescan_fails_after_settings_change(monkeypatch, tmp_path):
    import contextlib
    from types import SimpleNamespace

    from mcbe_editor import icon_api_routes

    scan_error = ValueError("scan failed")
    audit_events = []
    monkeypatch.setattr(icon_api_routes, "_icon_operation", lambda _deps: contextlib.nullcontext())
    monkeypatch.setattr(icon_api_routes, "add_icon_source", lambda _settings, path: {"path": path})
    monkeypatch.setattr(icon_api_routes, "_scan_and_store_icons", lambda *_args, **_kwargs: (_ for _ in ()).throw(scan_error))
    deps = SimpleNamespace(
        settings_path=str(tmp_path / "icon_sources.json"),
        json_string=lambda data, key: data[key],
        audit_event=lambda *args, **kwargs: audit_events.append((args, kwargs)),
        jsonify=lambda value: value,
        api_error=lambda message, status=400: ({"error": message}, status),
        log_api_exception=lambda *_args: None,
    )

    _response, status = icon_api_routes.icons_sources_add({"path": "C:/pack"}, deps)

    assert status == 400
    assert audit_events == [
        (
            ("icons.source_add", "partial"),
            {"details": {"path": "C:/pack", "settings_changed": True}, "error": "scan failed"},
        )
    ]


def test_icon_frontend_keeps_existing_index_when_post_commit_rescan_failed():
    import subprocess
    import textwrap
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            "node",
            "-e",
            textwrap.dedent(
                r"""
                const assert = require("assert");
                const fs = require("fs");
                const vm = require("vm");
                const code = fs.readFileSync("static/icon_sources_controller.js", "utf8");
                const context = { window: {}, console, fetch: async () => ({}) };
                vm.runInNewContext(code, context, { filename: "static/icon_sources_controller.js" });
                const api = context.window.MCBEIconSourcesController;
                const toasts = [];
                const statuses = [];
                const outputs = [];
                let applied = 0;
                const controller = api.createIconSourcesController({
                    elements: { updateVanillaButton: { disabled: false }, useCacheCheckbox: { checked: true, disabled: false } },
                    fetchImpl: async () => ({
                        json: async () => ({
                            success: true,
                            update_committed: true,
                            scan_warning: "Icons gespeichert, Scan fehlgeschlagen.",
                            manifest: { mapped_items: 1, known_items: 1 },
                        }),
                    }),
                    parseJsonResponse: response => response.json(),
                    withCsrf: () => ({}),
                    showToast: (...args) => toasts.push(args),
                    logStatus: (...args) => statuses.push(args),
                    appendUpdateOutput: text => outputs.push(text),
                    onIconData: () => { applied += 1; },
                    onIconDataApplied: () => { applied += 1; },
                });

                (async () => {
                    const updateResult = await controller.updateVanillaIcons();
                    assert.strictEqual(updateResult.success, false);
                    assert.strictEqual(updateResult.error, "Icons gespeichert, Scan fehlgeschlagen.");
                    assert.strictEqual(applied, 0);
                    assert.match(outputs.join("\n"), /Scan fehlgeschlagen/);
                    assert.strictEqual(statuses[0][1], "running");
                    assert.strictEqual(statuses[0][2].key, "vanilla-icons-update");
                    assert.strictEqual(statuses[0][2].active, true);
                    assert.strictEqual(toasts.at(-1)[1], "warning");
                    assert.strictEqual(statuses.at(-1)[1], "warning");
                    assert.strictEqual(statuses.at(-1)[2].key, "vanilla-icons-update");
                    assert.strictEqual(statuses.at(-1)[2].active, true);
                })().catch(error => { console.error(error); process.exit(1); });
                """
            ),
        ],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout


def test_icon_sources_tolerate_invalid_utf8(tmp_path):
    settings = tmp_path / "icon_sources.json"
    settings.write_bytes(b"\xff\xfe")

    assert load_icon_sources(str(settings)) == {"version": 2, "sources": []}


def test_icon_index_cache_tolerates_invalid_utf8(tmp_path):
    from mcbe_editor.icons import _load_cached_result, load_cached_icon_index

    cache = tmp_path / "icon_index_cache.json"
    cache.write_bytes(b"\xff\xfe")

    assert _load_cached_result(cache, "sig", None) is None
    assert load_cached_icon_index(str(tmp_path / "icon_sources.json")) is None
