from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("amulet_nbt")

from mcbe_editor import _inventory_core, inventory


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


def test_inventory_facade_owns_core_data_reload(monkeypatch) -> None:
    reloaded = []
    monkeypatch.setattr(inventory._importlib, "reload", lambda module: reloaded.append(module) or module)

    result = inventory._reload_inventory_core_data()

    assert result is _inventory_core
    assert reloaded == [_inventory_core]


def test_main_reloads_item_data_then_inventory_core_then_facade() -> None:
    source = (ROOT / "main.py").read_text(encoding="utf-8")

    item_data_reload = source.index("fresh_item_data_module = importlib.reload(fresh_item_data_module)")
    core_reload = source.index("inventory_module._reload_inventory_core_data()")
    facade_reload = source.index("importlib.reload(inventory_module)", core_reload)

    assert item_data_reload < core_reload < facade_reload
