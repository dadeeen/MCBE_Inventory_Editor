"""Declared pack images remain readable when legacy item aliases share a token."""

from urllib.parse import parse_qs, urlsplit

import pytest

from mcbe_editor import icon_api_routes as routes
from mcbe_editor import icons
from tests.test_icon_context_regressions import _deps
from tests.test_resource_pack_icons import _pack, _scan, _world


@pytest.mark.parametrize("archive", [False, True])
@pytest.mark.parametrize("fresh_worker", [False, True])
def test_declared_texture_survives_legacy_variant_alias_and_cache(tmp_path, monkeypatch, archive, fresh_worker):
    monkeypatch.setenv("MCBE_ICON_ROOTS", "")
    monkeypatch.setattr(icons, "_default_roots", lambda: [])
    monkeypatch.setattr(icons, "_vanilla_icon_roots", lambda: [])
    image = b"declared red wool icon"
    _, rp = _pack(
        tmp_path / "resource_packs",
        "colors",
        {
            "textures/item_texture.json": {"texture_data": {"red_wool": {"textures": "textures/custom/red"}}},
            "textures/custom/red.png": image,
        },
        archive=archive,
    )
    world = _world(tmp_path, "world", [rp])
    public, worker = _scan(tmp_path, world)
    if fresh_worker:
        worker = _deps(tmp_path)
        worker.read_only = True
        monkeypatch.setattr(routes, "scan_icons", lambda *args, **kwargs: pytest.fail("Published icons must not need another scan"))
        cached = routes.icons_status(worker, world_path=str(world))
        assert cached["cache"]["state"] == "hit"
        assert cached["icons"] == public["icons"]

    assert public["icons"]["minecraft:red_wool"]["token"] == public["icons"]["minecraft:wool#14"]["token"]
    for item in ("minecraft:red_wool", "minecraft:wool#14"):
        url = urlsplit(public["icons"][item]["url"])
        context = parse_qs(url.query)["context"][0]
        response = routes.icon_file(url.path.rsplit("/", 1)[1], worker, context_id=context)
        assert response["data"] == image
