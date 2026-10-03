from __future__ import annotations

from pathlib import Path


from mcbe_editor import nbt  # noqa: F401

from mcbe_editor import _inventory_core, inventory, item_data


ROOT = Path(__file__).resolve().parents[1]


def test_inventory_facade_keeps_public_api_and_owns_write_policy() -> None:
    assert inventory.nbt_to_json.__module__ == "mcbe_editor.inventory"
    assert inventory.parse_ender_chest.__module__ == "mcbe_editor.inventory"
    assert inventory.parse_abilities is _inventory_core.parse_abilities
    assert inventory.parse_effects is _inventory_core.parse_effects
    assert inventory.validate_inventory_item is _inventory_core.validate_inventory_item
    assert inventory.build_inventory_nbt.__module__ == "mcbe_editor.inventory"
    assert inventory.build_ender_chest_nbt.__module__ == "mcbe_editor.inventory"
    assert inventory._resolve_base_item_tag.__module__ == "mcbe_editor.inventory"


def test_inventory_facade_has_only_explicit_core_imports() -> None:
    source = (ROOT / "mcbe_editor" / "inventory.py").read_text(encoding="utf-8")
    assert "globals()[" not in source
    assert "import *" not in source
    assert all(not name.startswith("_") for name in inventory.__all__)
    assert {"build_inventory_nbt", "build_ender_chest_nbt", "validate_inventory_item"} <= set(inventory.__all__)
    for accidental_export in ("math", "re", "Any", "TypedDict", "nbt", "t"):
        assert not hasattr(inventory, accidental_export)


def test_internal_inventory_core_is_not_imported_elsewhere() -> None:
    offenders = []
    for path in sorted((ROOT / "mcbe_editor").glob("*.py")):
        if path.name in {"inventory.py", "_inventory_core.py"}:
            continue
        if "_inventory_core" in path.read_text(encoding="utf-8"):
            offenders.append(path.name)
    assert not offenders, f"Internal inventory core imported outside facade: {offenders}"


def test_inventory_facade_catalog_exports_follow_the_bound_snapshot() -> None:
    original_effects = inventory.EFFECTS
    original_enchantments = inventory.ENCHANTMENTS
    catalog = {**item_data.current_item_catalog(), "EFFECTS": {}, "ENCHANTMENTS": {}}
    with item_data.use_item_catalog(catalog):
        assert inventory.EFFECTS is catalog["EFFECTS"]
        assert inventory.ENCHANTMENTS is catalog["ENCHANTMENTS"]
        assert inventory.parse_effects is _inventory_core.parse_effects
    assert inventory.EFFECTS is original_effects
    assert inventory.ENCHANTMENTS is original_enchantments


def test_runtime_catalog_update_does_not_reload_executable_modules() -> None:
    for path in (ROOT / "main.py", ROOT / "mcbe_editor" / "inventory.py"):
        source = path.read_text(encoding="utf-8")
        assert "importlib.reload(" not in source
        assert "_reload_inventory_core_data" not in source
