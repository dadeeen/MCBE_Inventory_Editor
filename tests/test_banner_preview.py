"""Synthetic banner textures exercise extraction without distributing game art."""

import json
import zipfile

import pytest

from mcbe_editor.banner_patterns import BANNER_TEXTURES, crop_banner_texture
from mcbe_editor.block_icon_renderer import decode_png, encode_rgba_png
from mcbe_editor.icon_api_routes import _public_icon_index
from mcbe_editor.icons import scan_icons
from mcbe_editor.special_items import BANNER_PATTERNS
from scripts.update_icons import build_icon_cache
from tests.node_runner import run_node


def atlas(scale=1):
    size = 64 * scale
    # Every texel encodes its coordinates; the front and back cannot be confused.
    return encode_rgba_png(size, size, bytes(value for y in range(size) for x in range(size) for value in (x, y, 173, (x + y) % 256)))


@pytest.mark.parametrize("scale", [1, 2, 4])
def test_front_face_crop_preserves_pixels_orientation_shading_and_alpha(scale):
    result = decode_png(crop_banner_texture(atlas(scale)))
    assert (result.width, result.height) == (20 * scale, 40 * scale)
    for y in range(result.height):
        for x in range(result.width):
            offset = (y * result.width + x) * 4
            assert result.rgba[offset : offset + 4] == bytes((x + scale, y + scale, 173, (x + y + 2 * scale) % 256))


@pytest.mark.parametrize("width,height", [(32, 64), (64, 128), (32, 32), (65, 65)])
def test_unreviewed_atlas_layout_is_rejected(width, height):
    with pytest.raises(ValueError, match="Bannermuster"):
        crop_banner_texture(encode_rgba_png(width, height, bytes((255, 255, 255, 255)) * (width * height)))


def test_all_editor_patterns_have_real_texture_bindings_and_are_published(monkeypatch, tmp_path):
    assert len(BANNER_PATTERNS) == 42
    assert set(BANNER_TEXTURES) == {"base", "illager", *BANNER_PATTERNS}
    assert len(set(BANNER_TEXTURES.values())) == 44
    archive = tmp_path / "reference.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for path in BANNER_TEXTURES.values():
            zf.writestr(f"resource_pack/textures/{path}.png", atlas())
    target = tmp_path / "icons"
    manifest = build_icon_cache(archive, [], target, {})
    assert manifest["mapped_display_assets"] == 44
    for code, path in BANNER_TEXTURES.items():
        assert manifest["display_assets"][f"mcbe:banner_{code}"] == path
        assert (target / f"textures/display/banner_{code}.png").read_bytes() == crop_banner_texture(atlas())
    assert not any("banner_" in key for key in manifest["items"])
    monkeypatch.setenv("MCBE_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.delenv("MCBE_ICON_ROOTS", raising=False)
    monkeypatch.setenv("MCBE_ICON_CACHE_ROOT", str(target))
    settings = str(tmp_path / "icon_sources.json")
    # Go through the real scanner, persisted index, public response and guarded
    # image reader. A manifest alone is not proof that the UI can read a face.
    for _ in range(2):
        index = scan_icons(settings_path=settings)
        assert len(_public_icon_index(index)["banner_patterns"]) == 44
        for code, entry in _public_icon_index(index)["banner_patterns"].items():
            assert index["_by_token"][entry["token"]].read_bytes() == (target / f"textures/display/banner_{code}.png").read_bytes()


@pytest.mark.parametrize("reverse", [False, True])
def test_tga_has_bedrock_priority_over_png_regardless_of_zip_order(tmp_path, reverse):
    header = bytearray(18)
    header[2] = 2  # Uncompressed truecolor BGRA, top-left origin.
    header[12], header[14], header[16], header[17] = 64, 64, 32, 0x28
    tga = bytes(header) + bytes((30, 20, 10, 120)) * (64 * 64)
    png = encode_rgba_png(64, 64, bytes((99, 99, 99, 255)) * (64 * 64))
    members = [("png", png), ("tga", tga)]
    archive = tmp_path / "reference.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for extension, data in reversed(members) if reverse else members:
            zf.writestr(f"resource_pack/textures/entity/banner/banner_skull.{extension}", data)
    target = tmp_path / "icons"
    build_icon_cache(archive, [], target, {})
    assert decode_png((target / "textures/display/banner_sku.png").read_bytes()).rgba == bytes((10, 20, 30, 120)) * (20 * 40)


def test_bad_banner_does_not_replace_a_working_cache(tmp_path):
    archive = tmp_path / "reference.zip"
    target = tmp_path / "icons"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("resource_pack/textures/entity/banner/banner_base.png", atlas())
    build_icon_cache(archive, [], target, {})
    before = {path.relative_to(target): path.read_bytes() for path in target.rglob("*") if path.is_file()}
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("resource_pack/textures/entity/banner/banner_base.png", b"invalid")
    with pytest.raises(ValueError):
        build_icon_cache(archive, [], target, {})
    assert before == {path.relative_to(target): path.read_bytes() for path in target.rglob("*") if path.is_file()}


@pytest.mark.parametrize("missing", [["illager"], list(BANNER_TEXTURES)])
def test_rebuild_cannot_remove_working_banner_faces_even_with_valid_item_icons(tmp_path, missing):
    archive = tmp_path / "reference.zip"
    target = tmp_path / "icons"
    apple = encode_rgba_png(16, 16, bytes((255, 0, 0, 255)) * 256)

    def pack(omit):
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("resource_pack/textures/items/apple.png", apple)
            for code, texture in BANNER_TEXTURES.items():
                if code not in omit:
                    zf.writestr(f"resource_pack/textures/{texture}.png", atlas())

    pack([])
    build_icon_cache(archive, ["apple"], target, {}, block_item_ids=set())
    before = {path.relative_to(target): path.read_bytes() for path in target.rglob("*") if path.is_file()}
    pack(missing)
    with pytest.raises(ValueError, match="Bannermuster"):
        build_icon_cache(archive, ["apple"], target, {}, block_item_ids=set())
    assert before == {path.relative_to(target): path.read_bytes() for path in target.rglob("*") if path.is_file()}
    assert not list(tmp_path.glob(".icons.staging-*"))
    assert not list(tmp_path.glob(".icons.rollback-*"))


@pytest.mark.parametrize("replacement", [["base"], ["base", "illager"]])
def test_partial_banner_cache_can_be_refreshed_and_extended(tmp_path, replacement):
    archive = tmp_path / "reference.zip"
    target = tmp_path / "icons"
    for codes, scale in [(["base"], 1), (replacement, 2)]:
        with zipfile.ZipFile(archive, "w") as zf:
            for code in codes:
                zf.writestr(f"resource_pack/textures/{BANNER_TEXTURES[code]}.png", atlas(scale))
        manifest = build_icon_cache(archive, [], target, {})
        assert set(manifest["display_assets"]) == {f"mcbe:banner_{code}" for code in codes}
        assert (target / "textures/display/banner_base.png").read_bytes() == crop_banner_texture(atlas(scale))


def test_public_banner_urls_keep_context_and_exclude_unreviewed_display_assets():
    index = {
        "_context_id": "shared-context",
        "icons": {},
        "display_icons": {
            "mcbe:banner_sku": {"url": "/api/icons/skull"},
            "mcbe:banner_unknown": {"url": "/api/icons/unknown"},
            "mcbe:axolotl_gold": {"url": "/api/icons/axolotl"},
        },
    }
    before = json.dumps(index)
    public = _public_icon_index(index)
    assert public["banner_patterns"] == {"sku": {"url": "/api/icons/skull?context=shared-context"}}
    assert "display_icons" not in public
    assert json.dumps(index) == before
    assert _public_icon_index({})["banner_patterns"] == {}


@pytest.mark.parametrize("missing", [[], ["illager"], ["base", "sku"], list(BANNER_TEXTURES)])
def test_populated_icon_status_reports_missing_faces_without_changing_the_cached_index(missing):
    index = {
        "count": 1972,
        "warnings": ["Existing source warning"],
        "display_icons": {f"mcbe:banner_{code}": {"url": f"/api/icons/banner_{code}"} for code in BANNER_TEXTURES if code not in missing},
    }
    before = json.dumps(index)
    public = _public_icon_index(index)
    assert set(public["missing_banner_patterns"]) == set(missing)
    assert public["warnings"] == ["Existing source warning"]
    assert public["count"] == 1972
    assert json.dumps(index) == before


def test_legacy_cache_gains_banner_faces_from_validated_zip_without_redownload(monkeypatch, tmp_path):
    from scripts import update_icons

    cache = tmp_path / "downloads"
    cache.mkdir()
    target = tmp_path / "icons"
    archive = cache / "bedrock-samples-fixture-full.zip"
    apple = encode_rgba_png(16, 16, bytes((255, 0, 0, 255)) * 256)
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("resource_pack/textures/items/apple.png", apple)
    build_icon_cache(archive, ["apple"], target, {}, block_item_ids=set())
    monkeypatch.setenv("MCBE_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.delenv("MCBE_ICON_ROOTS", raising=False)
    monkeypatch.setenv("MCBE_ICON_CACHE_ROOT", str(target))
    settings = str(tmp_path / "settings.json")
    before = _public_icon_index(scan_icons(settings_path=settings))
    assert before["count"] > 0
    assert set(before["missing_banner_patterns"]) == set(BANNER_TEXTURES)

    with zipfile.ZipFile(archive, "a") as zf:
        for texture in BANNER_TEXTURES.values():
            zf.writestr(f"resource_pack/textures/{texture}.png", atlas())
    info = {
        "resource_pack_release": "fixture",
        "resource_pack_asset": archive.name,
        "resource_pack_asset_size": archive.stat().st_size,
        "resource_pack_url": "https://github.com/Mojang/bedrock-samples/releases/download/fixture/" + archive.name,
    }
    monkeypatch.setattr(update_icons, "CACHE_DIR", cache)
    monkeypatch.setattr(update_icons, "ICON_ROOT", target)
    monkeypatch.setattr(update_icons, "read_release_metadata", lambda: info)
    monkeypatch.setattr(update_icons, "get_latest_full_release_info", lambda: info)
    monkeypatch.setattr(update_icons, "load_icon_targets", lambda _path: (["apple"], [], 1, set()))
    monkeypatch.setattr(update_icons, "_build_validating_opener", lambda *a, **kw: pytest.fail("The validated ZIP must be reused"))
    assert update_icons.main([]) == 0

    after = _public_icon_index(scan_icons(settings_path=settings, force=True))
    assert after["missing_banner_patterns"] == []
    assert set(after["banner_patterns"]) == set(BANNER_TEXTURES)
    assert "minecraft:apple" in after["icons"]
    assert (target / "textures/items/apple.png").read_bytes() == apple
    assert not any("Bannermuster fehlen" in warning for warning in after["warnings"])


def test_banner_tint_preserves_fractional_alpha_and_does_not_mutate_source():
    run_node(
        r"""
        const assert = require('assert');
        global.window = {};
        eval(require('fs').readFileSync('static/banner_preview.js','utf8'));
        const source = new Uint8ClampedArray([255,128,64,128, 10,20,30,0, 128,128,128,255]);
        const result = window.MCBEBannerPreview.tintPixels(source,'#804020');
        assert.deepStrictEqual(Array.from(result),[128,32,8,128, 5,5,4,0, 64,32,16,255]);
        assert.deepStrictEqual(Array.from(source),[255,128,64,128, 10,20,30,0, 128,128,128,255]);
        assert.throws(() => window.MCBEBannerPreview.tintPixels(source,'red'));
        """
    )
