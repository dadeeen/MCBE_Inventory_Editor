import json

import pytest

from scripts.compare_icon_caches import compare_caches


def cache(root, content, *, release="same"):
    (root / "textures/items").mkdir(parents=True)
    (root / "textures/items/brick_block.png").write_bytes(content)
    (root / "manifest.json").write_text(json.dumps({
        "items": {"minecraft:brick_block": "blocks/brick"}, "missing_items": [], "release": release,
    }))


def test_comparison_detects_render_changes_without_source_path_changes(tmp_path):
    before, after = tmp_path / "before", tmp_path / "after"
    cache(before, b"old render")
    cache(after, b"new render")
    result = compare_caches(before, after, tmp_path / "report")
    assert result["changed"] == 1
    assert result["changes"][0]["image_changed"] is True
    assert result["new_missing"] == []
    assert (tmp_path / "report/comparison.html").is_file()


def test_comparison_rejects_different_inputs(tmp_path):
    before, after = tmp_path / "before", tmp_path / "after"
    cache(before, b"same image", release="old")
    cache(after, b"same image", release="new")
    with pytest.raises(ValueError, match="same release"):
        compare_caches(before, after, tmp_path / "report")


@pytest.mark.parametrize("empty", [False, True])
def test_comparison_rejects_incomplete_cache_even_when_manifest_claims_coverage(tmp_path, empty):
    before, after = tmp_path / "before", tmp_path / "after"
    cache(before, b"same image")
    cache(after, b"" if empty else b"same image")
    if not empty:
        (after / "textures/items/brick_block.png").unlink()
    with pytest.raises(ValueError, match="missing or empty PNGs"):
        compare_caches(before, after, tmp_path / "report")
    assert not (tmp_path / "report").exists()
