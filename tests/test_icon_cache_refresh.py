"""Offline cache migration uses synthetic art and never touches game data."""

import json
import shutil
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from mcbe_editor import icon_api_routes, icon_cache, icon_cache_refresh, icons
from mcbe_editor.banner_patterns import BANNER_TEXTURES, crop_banner_texture
from mcbe_editor.block_icon_renderer import decode_png, encode_rgba_png
from scripts import update_icons

APPLE = encode_rgba_png(16, 16, bytes((90, 10, 20, 255)) * 256)
ATLAS = encode_rgba_png(64, 64, bytes((40, 50, 60, 120)) * 4096)
FACE = crop_banner_texture(ATLAS)


def snapshot(root):
    return {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}


@pytest.fixture
def cache_case(monkeypatch, tmp_path):
    target = tmp_path / "data" / "icons" / "vanilla"
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    archive = downloads / "bedrock-samples-fixture-full.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("resource_pack/textures/items/apple.png", APPLE)
        for code, texture in BANNER_TEXTURES.items():
            if code == "illager":
                header = bytearray(18)
                header[2] = 2
                header[12], header[14], header[16], header[17] = 64, 64, 32, 0x28
                zf.writestr(f"resource_pack/textures/{texture}.tga", bytes(header) + bytes((60, 50, 40, 120)) * 4096)
            zf.writestr(f"resource_pack/textures/{texture}.png", APPLE if code == "illager" else ATLAS)
        for texture in update_icons.AXOLOTL_DISPLAY_ASSETS.values():
            zf.writestr(f"resource_pack/textures/items/{texture}.png", APPLE)
    release = {
        "resource_pack_release": "fixture",
        "resource_pack_asset": archive.name,
        "resource_pack_asset_size": archive.stat().st_size,
        "resource_pack_url": f"https://github.com/Mojang/bedrock-samples/releases/download/fixture/{archive.name}",
    }
    manifest = update_icons.build_icon_cache(archive, ["apple"], target, release, block_item_ids=set())
    assert len(manifest["display_assets"]) == 54
    manifest_path = target / "manifest.json"

    def omit(asset_ids, *, keep_declared=False):
        current = json.loads(manifest_path.read_text(encoding="utf-8"))
        for asset_id in asset_ids:
            (target / "textures" / "display" / f"{asset_id.removeprefix('mcbe:')}.png").unlink(missing_ok=True)
            if not keep_declared:
                current["display_assets"].pop(asset_id, None)
        current["mapped_display_assets"] = len(current["display_assets"])
        manifest_path.write_text(json.dumps(current), encoding="utf-8")

    omit(["mcbe:banner_illager"])
    settings = target.parents[1] / "icon_sources.json"
    stored = {}
    deps = SimpleNamespace(
        read_only=False,
        data_root=str(settings.parent),
        settings_path=str(settings),
        get_icon_index=lambda: stored,
        set_icon_index=lambda value: (stored.clear(), stored.update(value)),
        jsonify=lambda value: value,
        log_api_exception=lambda _name, exc: pytest.fail(str(exc)),
    )
    monkeypatch.setenv("MCBE_DATA_ROOT", str(settings.parent))
    monkeypatch.setenv("MCBE_UPDATE_CACHE_DIR", str(downloads))
    monkeypatch.delenv("MCBE_ICON_CACHE_ROOT", raising=False)
    monkeypatch.delenv("MCBE_ICON_ROOTS", raising=False)
    monkeypatch.setattr(update_icons, "_build_validating_opener", lambda *_a, **_kw: pytest.fail("Automatic refresh must stay offline"))
    icon_cache_refresh._ATTEMPTS.clear()
    return SimpleNamespace(target=target, downloads=downloads, archive=archive, manifest=manifest_path, omit=omit, deps=deps, stored=stored)


def refresh(case, **kwargs):
    return icon_cache_refresh.refresh_cached_display_assets(case.target, case.downloads, **kwargs)


def test_status_repairs_legacy_cache_before_index_lookup_and_serves_the_face(cache_case, monkeypatch):
    case = cache_case
    # Simulate an already persisted index from the previous editor version.
    archive_bytes = case.archive.read_bytes()
    case.archive.unlink()
    old = icon_api_routes.icons_status(case.deps)
    assert old["missing_banner_patterns"] == ["illager"]
    case.archive.write_bytes(archive_bytes)
    before = snapshot(case.target)
    validations = []
    validate = update_icons._validate_downloaded_zip

    def track(path):
        validations.append(path)
        validate(path)

    monkeypatch.setattr(update_icons, "_validate_downloaded_zip", track)
    result = icon_api_routes.icons_status(case.deps)
    assert result["missing_banner_patterns"] == []
    assert result["count"] == old["count"]
    entry = result["banner_patterns"]["illager"]
    assert "?context=" in entry["url"]
    assert case.stored["_by_token"][entry["token"]].read_bytes() == FACE
    for path, content in before.items():
        if path != Path("manifest.json"):
            assert (case.target / path).read_bytes() == content
    after = json.loads(case.manifest.read_text())
    original = json.loads(before[Path("manifest.json")])
    assert after["release"] == original["release"]
    assert after["items"] == original["items"]
    assert after["mapped_display_assets"] == after["display_asset_targets"] == 54
    assert icon_api_routes.icons_status(case.deps)["cache"]["state"] == "hit"
    assert icon_api_routes.icons_status(case.deps)["missing_banner_patterns"] == []
    assert len(validations) == 1


@pytest.mark.parametrize("missing", [[f"mcbe:banner_{code}" for code in BANNER_TEXTURES], list(update_icons.AXOLOTL_DISPLAY_ASSETS)])
@pytest.mark.parametrize("keep_declared", [False, True])
def test_repairs_other_missing_faces_and_axolotl_assets(cache_case, missing, keep_declared):
    case = cache_case
    case.omit(missing, keep_declared=keep_declared)
    assert refresh(case)
    manifest = json.loads(case.manifest.read_text())
    assert len(manifest["display_assets"]) == 54
    for asset_id in missing:
        png = case.target / "textures" / "display" / f"{asset_id.removeprefix('mcbe:')}.png"
        assert png.read_bytes() == (FACE if asset_id.startswith("mcbe:banner_") else APPLE)


def test_repairs_zero_length_declared_asset(cache_case):
    case = cache_case
    path = case.target / "textures/display/banner_base.png"
    path.write_bytes(b"")
    assert refresh(case)
    assert path.read_bytes() == FACE


def test_existing_undeclared_face_is_preserved_when_manifest_is_extended(cache_case):
    case = cache_case
    path = case.target / "textures/display/banner_base.png"
    existing = encode_rgba_png(20, 40, bytes((99, 88, 77, 255)) * 800)
    path.write_bytes(existing)
    manifest = json.loads(case.manifest.read_text())
    del manifest["display_assets"]["mcbe:banner_base"]
    case.manifest.write_text(json.dumps(manifest), encoding="utf-8")
    assert refresh(case)
    assert path.read_bytes() == existing
    assert json.loads(case.manifest.read_text())["display_assets"]["mcbe:banner_base"] == BANNER_TEXTURES["base"]


@pytest.mark.parametrize("kind", ["absent", "wrong_name", "wrong_size", "unknown_schema", "unknown_source", "invalid_json", "invalid_utf8", "unsafe_asset"])
def test_missing_or_mismatched_inputs_preserve_cache(cache_case, kind):
    case = cache_case
    manifest = json.loads(case.manifest.read_text())
    if kind == "absent":
        case.archive.unlink()
    elif kind == "wrong_name":
        case.archive.rename(case.archive.with_name("bedrock-samples-other-full.zip"))
    elif kind == "wrong_size":
        manifest["release"]["resource_pack_asset_size"] += 1
    elif kind == "unknown_schema":
        manifest["schema_version"] = 999
    elif kind == "unknown_source":
        manifest["source"] = "Custom pack"
    elif kind == "unsafe_asset":
        manifest["release"]["resource_pack_asset"] = "../bedrock-samples-fixture-full.zip"
    case.manifest.write_bytes(b"{" if kind == "invalid_json" else b"\xff" if kind == "invalid_utf8" else json.dumps(manifest).encode())
    before = snapshot(case.target)
    assert not refresh(case)
    assert not refresh(case)
    assert snapshot(case.target) == before


def test_corrupt_archive_is_not_retried_until_replaced(cache_case, monkeypatch):
    case = cache_case
    original = case.archive.read_bytes()
    case.archive.write_bytes(b"x" * len(original))
    before = snapshot(case.target)
    attempts = []
    validate = update_icons._validate_downloaded_zip

    def track(path):
        attempts.append(path)
        validate(path)

    monkeypatch.setattr(update_icons, "_validate_downloaded_zip", track)
    assert not refresh(case)
    assert not refresh(case)
    assert len(attempts) == 1
    assert snapshot(case.target) == before
    case.archive.write_bytes(original)
    assert refresh(case)
    assert len(attempts) == 2


def test_archive_limits_leave_existing_icons_available(cache_case, monkeypatch):
    monkeypatch.setattr(update_icons, "MAX_RESOURCE_PACK_MEMBERS", 1)
    before = snapshot(cache_case.target)
    result = icon_api_routes.icons_status(cache_case.deps)
    assert "minecraft:apple" in result["icons"]
    assert result["missing_banner_patterns"] == ["illager"]
    assert snapshot(cache_case.target) == before


@pytest.mark.parametrize("failure", ["decode", "publish"])
def test_failed_repair_rolls_back_and_cleans_staging(cache_case, monkeypatch, failure):
    case = cache_case
    before = snapshot(case.target)
    if failure == "decode":

        def fail_decode(_png):
            raise ValueError("Invalid image")

        monkeypatch.setattr(icon_cache_refresh, "decode_png", fail_decode)
    else:
        replace = icon_cache.os.replace

        def fail_publish(source, destination):
            if Path(source).name.startswith(".vanilla.staging-") and Path(destination) == case.target:
                raise OSError("Simulated publication failure")
            return replace(source, destination)

        monkeypatch.setattr(icon_cache.os, "replace", fail_publish)
    assert not refresh(case)
    assert snapshot(case.target) == before
    assert not list(case.target.parent.glob(".vanilla.staging-*"))
    assert not list(case.target.parent.glob(".vanilla.rollback-*"))


@pytest.mark.parametrize("same_manifest", [False, True])
def test_concurrent_full_update_wins_over_stale_repair(cache_case, monkeypatch, same_manifest):
    case = cache_case
    publish = icon_cache.publish_icon_cache

    def concurrent_update(staging, target, **kwargs):
        newer = target.parent / ".vanilla.staging-newer"
        shutil.copytree(target, newer)
        if not same_manifest:
            manifest = json.loads((newer / "manifest.json").read_text())
            manifest["release"]["resource_pack_release"] = "newer"
            (newer / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (newer / "textures/items/apple.png").write_bytes(FACE)
        assert publish(newer, target)
        return publish(staging, target, **kwargs)

    monkeypatch.setattr(icon_cache_refresh, "publish_icon_cache", concurrent_update)
    assert not refresh(case)
    assert json.loads(case.manifest.read_text())["release"]["resource_pack_release"] == ("fixture" if same_manifest else "newer")
    assert (case.target / "textures/items/apple.png").read_bytes() == FACE
    assert not (case.target / "textures/display/banner_illager.png").exists()
    assert not list(case.target.parent.glob(".vanilla.staging-*"))


def test_read_only_status_keeps_existing_cache_and_does_not_repair(cache_case):
    case = cache_case
    archive = case.archive.read_bytes()
    case.archive.unlink()
    icon_api_routes.icons_status(case.deps)
    case.archive.write_bytes(archive)
    before = snapshot(case.target)
    case.deps.read_only = True
    result = icon_api_routes.icons_status(case.deps)
    assert result["cache"]["state"] == "hit"
    assert result["missing_banner_patterns"] == ["illager"]
    assert snapshot(case.target) == before


@pytest.mark.parametrize("source", [{"auto": False, "enabled": True}, {"auto": True, "enabled": False}])
def test_manual_or_disabled_sources_are_not_modified(cache_case, source):
    case = cache_case
    before = snapshot(case.target)
    icons.scan_icons(prepared_sources=[{"path": str(case.target), "vanilla": True, **source}])
    assert snapshot(case.target) == before


def test_manual_item_override_retains_priority_during_repair(cache_case, monkeypatch, tmp_path):
    case = cache_case
    custom = tmp_path / "custom" / "textures" / "items"
    custom.mkdir(parents=True)
    (custom / "apple.png").write_bytes(FACE)
    monkeypatch.setenv("MCBE_ICON_ROOTS", str(custom.parents[1]))
    result = icon_api_routes.icons_status(case.deps)
    token = result["icons"]["minecraft:apple"]["token"]
    assert case.stored["_by_token"][token].read_bytes() == FACE
    assert result["missing_banner_patterns"] == []
    assert (case.target / "textures/items/apple.png").read_bytes() == APPLE


def test_explicitly_removed_cache_is_not_reinstalled(cache_case):
    case = cache_case
    shutil.rmtree(case.target)
    assert not refresh(case)
    assert not case.target.exists()


def test_refresh_rejects_linked_cache_content(cache_case, tmp_path):
    from tests.test_path_safety_regressions import directory_link

    case = cache_case
    original = tmp_path / "unrelated"
    original.mkdir()
    (original / "private.png").write_bytes(APPLE)
    with directory_link(original, case.target / "linked") as link:
        assert not refresh(case)
        assert link.exists()
        assert (original / "private.png").read_bytes() == APPLE
        assert not (case.target / "textures/display/banner_illager.png").exists()


def test_repaired_ominous_texture_uses_tga_colors(cache_case):
    assert refresh(cache_case)
    texture = decode_png((cache_case.target / "textures/display/banner_illager.png").read_bytes())
    assert (texture.width, texture.height) == (20, 40)
    assert texture.rgba == bytes((40, 50, 60, 120)) * 800
