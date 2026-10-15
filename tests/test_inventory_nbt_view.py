"""The read-only inspector must not round or normalize original NBT numbers."""

import json

import pytest

from mcbe_editor import nbt
from mcbe_editor._inventory_core import MAX_NBT_VIEW_ITEMS, _nbt_view_value


@pytest.mark.parametrize(
    ("tag", "expected"),
    [
        (nbt.LongTag((1 << 53) - 1), (1 << 53) - 1),
        (nbt.LongTag(-((1 << 53) - 1)), -((1 << 53) - 1)),
        (nbt.LongTag((1 << 53) + 1), str((1 << 53) + 1)),
        (nbt.LongTag((1 << 63) - 1), str((1 << 63) - 1)),
        (nbt.LongTag(-(1 << 63)), str(-(1 << 63))),
        (nbt.FloatTag(float("nan")), "NaN"),
        (nbt.FloatTag(float("inf")), "Infinity"),
        (nbt.DoubleTag(float("-inf")), "-Infinity"),
        (nbt.DoubleTag(1.25), 1.25),
    ],
)
def test_nbt_inspector_numbers_are_json_safe_and_exact(tag, expected) -> None:
    original = tag.save_to(compressed=False, little_endian=True)
    view = _nbt_view_value(tag)
    assert view == {"type": type(tag).__name__, "value": expected}
    assert json.loads(json.dumps(view, allow_nan=False)) == view
    assert tag.save_to(compressed=False, little_endian=True) == original


def test_nbt_inspector_long_arrays_keep_exact_values_and_truncation() -> None:
    tag = nbt.LongArrayTag([(1 << 63) - 1, -(1 << 63), 7] + [1] * MAX_NBT_VIEW_ITEMS)
    original = tag.save_to(compressed=False, little_endian=True)
    view = _nbt_view_value(tag)
    assert view["type"] == "LongArrayTag"
    assert view["value"][:3] == [str((1 << 63) - 1), str(-(1 << 63)), 7]
    assert len(view["value"]) == MAX_NBT_VIEW_ITEMS
    assert "truncated" in view
    assert tag.save_to(compressed=False, little_endian=True) == original
