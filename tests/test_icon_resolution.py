import pytest

from mcbe_editor.icon_resolution import item_icon_key, resolve_icon_definition


def resolve(item_id, *, items=None, terrain=None, blocks=None, definitions=None, available=None, is_block=True):
    return resolve_icon_definition(
        item_id, is_block=is_block, item_icons=definitions or {}, blocks=blocks or {},
        item_atlas=items or {}, terrain_atlas=terrain or {}, available=set(available or []),
    )


@pytest.mark.parametrize("component", ["gem", {"texture": "gem"}, {"textures": {"default": "gem", "open": "wrong"}}])
def test_item_component_formats_use_default_icon(component):
    assert item_icon_key(component) == "gem"
    result = resolve(
        "custom_item", definitions={"custom_item": component}, items={"gem": ["items/right"]},
        terrain={"gem": ["blocks/wrong"]}, available=["items/right", "blocks/wrong"],
    )
    assert result.path == "items/right"
    assert result.basis == "item_definition"


@pytest.mark.parametrize("item_id", ["brick_block", "brick_stairs", "brick_slab", "brick_wall"])
def test_block_material_never_resolves_through_item_atlas(item_id):
    result = resolve(
        item_id, items={"brick": ["items/brick"]}, terrain={"brick": ["blocks/masonry"]},
        blocks={item_id: {"textures": "brick"}}, available=["items/brick", "blocks/masonry"],
    )
    assert result.path == "blocks/masonry"
    assert result.faces == dict.fromkeys(("side", "top", "front"), "blocks/masonry")


def test_carried_binding_can_reference_item_sprite_through_terrain_atlas():
    result = resolve(
        "lantern", blocks={"lantern": {"textures": "atlas", "carried_textures": "inventory"}},
        items={"lantern": ["items/outdated"]}, terrain={"atlas": ["blocks/atlas"], "inventory": ["items/carried"]},
        available=["blocks/atlas", "items/carried", "items/outdated"],
    )
    assert result.path == "items/carried"
    assert result.basis == "block_carried"
    assert result.atlas == "terrain"


def test_placeable_item_keeps_dedicated_sprite():
    result = resolve(
        "brewing_stand", blocks={"brewing_stand": {"textures": "brewing_stand"}},
        items={"brewing_stand": ["items/stand"]}, terrain={"brewing_stand": ["blocks/stand"]},
        available=["items/stand", "blocks/stand"],
    )
    assert result.path == "items/stand"


@pytest.mark.parametrize("item,key", [("oak_sign", "sign"), ("dark_oak_sign", "sign_darkoak")])
def test_legacy_sign_sprite_names_preserve_inventory_identity(item, key):
    result = resolve(item, items={key: ["items/" + key]}, available=["items/" + key, "blocks/planks_oak"], is_block=False)
    assert result.path == "items/" + key


def test_declared_faces_override_filename_guesses_and_keep_carried_defaults():
    result = resolve(
        "quartz_stairs",
        blocks={"quartz_stairs": {"textures": {"side": "wall", "up": "cap"}, "carried_textures": {"up": "inventory_cap"}}},
        terrain={"wall": ["blocks/a"], "cap": ["blocks/b"], "inventory_cap": ["blocks/c"]},
        available=["blocks/a", "blocks/b", "blocks/c", "blocks/quartz_stairs_top"],
    )
    assert result.faces == {"side": "blocks/a", "front": "blocks/a", "top": "blocks/c"}


@pytest.mark.parametrize("paths,available,issue", [
    (["blocks/a", "blocks/b"], ["blocks/b"], "variant_selection_required"),
    (["blocks/a"], ["blocks/brick"], "missing_texture"),
    ([], ["blocks/brick"], "unknown_texture_key"),
    (["entity/shield"], ["entity/shield"], "model_required"),
])
def test_unresolved_declarations_do_not_choose_available_or_similarly_named_assets(paths, available, issue):
    result = resolve("brick_block", blocks={"brick_block": {"textures": "brick"}}, terrain={"brick": paths}, available=available)
    assert result.path is None
    assert result.issue == issue


def test_unrelated_block_suffix_does_not_select_ingredient_sprite():
    assert resolve("quartz_stairs", items={"quartz": ["items/quartz"]}, available=["items/quartz"]) is None


def test_explicit_broken_item_binding_does_not_fall_back_to_block_definition():
    result = resolve(
        "brick_block", definitions={"brick_block": {"texture": "missing"}},
        blocks={"brick_block": {"textures": "brick"}}, terrain={"brick": ["blocks/brick"]}, available=["blocks/brick"],
    )
    assert result.path is None
    assert result.issue == "unknown_texture_key"


def test_result_does_not_depend_on_atlas_insertion_order():
    common = {"blocks": {"brick_block": {"textures": "brick"}}, "available": ["blocks/brick", "blocks/other"]}
    first = resolve("brick_block", terrain={"other": ["blocks/other"], "brick": ["blocks/brick"]}, **common)
    second = resolve("brick_block", terrain={"brick": ["blocks/brick"], "other": ["blocks/other"]}, **common)
    assert first == second
