"""The read-only inspector exposes exact types and bounded, explicit excerpts."""

import json

import pytest
from flask import Flask

from mcbe_editor import nbt
from mcbe_editor import _inventory_core as inventory_core
from mcbe_editor._inventory_core import MAX_NBT_VIEW_DEPTH, MAX_NBT_VIEW_ITEMS, MAX_NBT_VIEW_NODES, MAX_NBT_VIEW_STRING, _nbt_view_value


@pytest.mark.parametrize(
    ("tag", "expected"),
    [
        (nbt.ByteTag(-1), -1),
        (nbt.ShortTag(-32768), -32768),
        (nbt.IntTag((1 << 31) - 1), (1 << 31) - 1),
        (nbt.LongTag((1 << 53) - 1), (1 << 53) - 1),
        (nbt.LongTag(-((1 << 53) - 1)), -((1 << 53) - 1)),
        (nbt.LongTag((1 << 53) + 1), str((1 << 53) + 1)),
        (nbt.LongTag((1 << 63) - 1), str((1 << 63) - 1)),
        (nbt.LongTag(-(1 << 63)), str(-(1 << 63))),
        (nbt.FloatTag(float("nan")), "NaN"),
        (nbt.FloatTag(float("inf")), "Infinity"),
        (nbt.DoubleTag(float("-inf")), "-Infinity"),
        (nbt.FloatTag(-0.0), "-0"),
        (nbt.DoubleTag(-0.0), "-0"),
        (nbt.FloatTag(0.0), 0.0),
        (nbt.DoubleTag(0.0), 0.0),
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
    assert view["truncation"] == {"reason": "items", "total": MAX_NBT_VIEW_ITEMS + 3, "shown": MAX_NBT_VIEW_ITEMS}
    assert view["truncated"]
    assert tag.save_to(compressed=False, little_endian=True) == original


@pytest.mark.parametrize("kind", [nbt.CompoundTag, nbt.ListTag, nbt.ByteArrayTag, nbt.IntArrayTag, nbt.LongArrayTag])
def test_nbt_inspector_empty_containers_are_not_truncated(kind) -> None:
    tag = kind()
    expected = {"type": kind.__name__, "value": {} if kind is nbt.CompoundTag else []}
    if kind is nbt.ListTag:
        expected["list_type_id"] = nbt.ByteTag.tag_id
    assert _nbt_view_value(tag) == expected


@pytest.mark.parametrize("element_type", [nbt.IntTag.tag_id, nbt.CompoundTag.tag_id])
def test_nbt_inspector_empty_lists_preserve_declared_element_type(element_type) -> None:
    tag = nbt.ListTag([], list_data_type=element_type)
    original = tag.save_to(compressed=False, little_endian=True)

    view = _nbt_view_value(tag)

    assert view == {"type": "ListTag", "value": [], "list_type_id": element_type}
    assert tag.save_to(compressed=False, little_endian=True) == original


def test_nbt_inspector_depth_limited_list_preserves_declared_element_type() -> None:
    view = _nbt_view_value(nbt.ListTag([], list_data_type=nbt.CompoundTag.tag_id), depth=MAX_NBT_VIEW_DEPTH)
    assert view["type"] == "ListTag"
    assert view["list_type_id"] == nbt.CompoundTag.tag_id
    assert view["truncation"] == {"reason": "depth"}


@pytest.mark.parametrize("extra", [0, 1])
def test_nbt_inspector_compound_limit_is_explicit_and_sorted(extra) -> None:
    total = MAX_NBT_VIEW_ITEMS + extra
    tag = nbt.CompoundTag({f"field{index:03d}": nbt.IntTag(index) for index in reversed(range(total))})
    original = tag.save_to(compressed=False, little_endian=True)

    view = _nbt_view_value(tag)

    assert list(view["value"]) == [f"field{index:03d}" for index in range(MAX_NBT_VIEW_ITEMS)]
    assert view["value"]["field000"] == {"type": "IntTag", "value": 0}
    if extra:
        assert view["truncation"] == {"reason": "items", "total": total, "shown": MAX_NBT_VIEW_ITEMS}
        assert view["truncated"]
    else:
        assert "truncation" not in view
        assert "truncated" not in view
    assert tag.save_to(compressed=False, little_endian=True) == original


@pytest.mark.parametrize("kind", [nbt.ListTag, nbt.ByteArrayTag, nbt.IntArrayTag, nbt.LongArrayTag])
@pytest.mark.parametrize("extra", [0, 1])
def test_nbt_inspector_sequence_limit_preserves_order(kind, extra) -> None:
    total = MAX_NBT_VIEW_ITEMS + extra
    tag = kind([nbt.IntTag(index) if kind is nbt.ListTag else index for index in range(total)])
    original = tag.save_to(compressed=False, little_endian=True)

    view = _nbt_view_value(tag)

    expected = [{"type": "IntTag", "value": index} if kind is nbt.ListTag else index for index in range(MAX_NBT_VIEW_ITEMS)]
    assert view["value"] == expected
    if kind is nbt.ListTag:
        assert view["list_type_id"] == nbt.IntTag.tag_id
    if extra:
        assert view["truncation"] == {"reason": "items", "total": total, "shown": MAX_NBT_VIEW_ITEMS}
        assert view["truncated"]
    else:
        assert "truncation" not in view
        assert "truncated" not in view
    assert tag.save_to(compressed=False, little_endian=True) == original


@pytest.mark.parametrize("extra", [0, 1])
def test_nbt_inspector_string_limit_reports_original_length(extra) -> None:
    text = "🪨" * (MAX_NBT_VIEW_STRING + extra)
    tag = nbt.StringTag(text)
    view = _nbt_view_value(tag)

    assert view["type"] == "StringTag"
    assert view["value"] == text[:MAX_NBT_VIEW_STRING] + ("..." if extra else "")
    if extra:
        assert view["truncation"] == {"reason": "string", "total": len(text), "shown": MAX_NBT_VIEW_STRING}
        assert view["truncated"]
    else:
        assert "truncation" not in view
        assert "truncated" not in view
    assert tag.py_data == text


def test_nbt_inspector_depth_limit_has_structured_metadata() -> None:
    tag = nbt.StringTag("Original value")
    for _ in range(MAX_NBT_VIEW_DEPTH):
        tag = nbt.CompoundTag({"child": tag})
    original = tag.save_to(compressed=False, little_endian=True)

    view = _nbt_view_value(tag)
    for _ in range(MAX_NBT_VIEW_DEPTH):
        assert "truncation" not in view
        view = view["value"]["child"]
    assert view["type"] == "StringTag"
    assert view["truncation"] == {"reason": "depth"}
    assert view["truncated"]
    assert tag.save_to(compressed=False, little_endian=True) == original


@pytest.mark.parametrize(
    ("locale", "depth_message", "string_message"),
    [
        ("de", "Maximale Anzeigetiefe erreicht", "2 weitere Zeichen"),
        ("en", "Maximum display depth reached", "2 more characters"),
    ],
)
def test_nbt_inspector_structured_truncation_keeps_localized_messages(locale, depth_message, string_message) -> None:
    with Flask(__name__).test_request_context(headers={"Accept-Language": locale}):
        depth_view = _nbt_view_value(nbt.IntTag(42), depth=MAX_NBT_VIEW_DEPTH)
        string_view = _nbt_view_value(nbt.StringTag("a" * (MAX_NBT_VIEW_STRING + 2)))

    assert depth_view["truncated"] == depth_message
    assert depth_view["truncation"] == {"reason": "depth"}
    assert string_view["truncated"] == string_message
    assert string_view["truncation"] == {"reason": "string", "total": MAX_NBT_VIEW_STRING + 2, "shown": MAX_NBT_VIEW_STRING}


def _view_node_count(view) -> int:
    value = view["value"]
    if isinstance(value, dict):
        return 1 + sum(_view_node_count(child) for child in value.values())
    if isinstance(value, list):
        return 1 + sum(_view_node_count(child) if isinstance(child, dict) else 1 for child in value)
    return 1


def test_nbt_inspector_node_budget_bounds_nested_lists_and_resets_for_each_view() -> None:
    tag = nbt.CompoundTag({f"field{index:03d}": nbt.ListTag([nbt.IntTag(value) for value in range(MAX_NBT_VIEW_ITEMS)]) for index in range(MAX_NBT_VIEW_ITEMS)})
    original = tag.save_to(compressed=False, little_endian=True)

    view = _nbt_view_value(tag)

    assert _view_node_count(view) == MAX_NBT_VIEW_NODES
    assert view["truncation"]["reason"] == "budget"
    assert view["truncation"]["total"] == MAX_NBT_VIEW_ITEMS
    assert view["truncation"]["shown"] == len(view["value"])
    last_child = list(view["value"].values())[-1]
    assert last_child["truncation"]["reason"] == "budget"
    assert last_child["truncation"]["shown"] == len(last_child["value"])
    assert _nbt_view_value(tag) == view
    assert tag.save_to(compressed=False, little_endian=True) == original


def test_nbt_inspector_array_elements_share_the_node_budget(monkeypatch) -> None:
    monkeypatch.setattr(inventory_core, "MAX_NBT_VIEW_NODES", 17)
    tag = nbt.CompoundTag({f"array{index}": nbt.IntArrayTag(range(10)) for index in range(10)})

    view = _nbt_view_value(tag)

    assert _view_node_count(view) == 17
    assert view["truncation"] == {"reason": "budget", "total": 10, "shown": 2}
    assert view["value"]["array0"]["value"] == list(range(10))
    assert view["value"]["array1"]["truncation"] == {"reason": "budget", "total": 10, "shown": 4}
    assert view["value"]["array1"]["value"] == list(range(4))


@pytest.mark.parametrize("kind", [nbt.CompoundTag, nbt.ListTag, nbt.IntArrayTag])
def test_nbt_inspector_exhausted_budget_still_explains_omitted_children(monkeypatch, kind) -> None:
    monkeypatch.setattr(inventory_core, "MAX_NBT_VIEW_NODES", 1)
    tag = kind({"child": nbt.IntTag(7)}) if kind is nbt.CompoundTag else kind([nbt.IntTag(7)] if kind is nbt.ListTag else [7])

    view = _nbt_view_value(tag)

    assert _view_node_count(view) == 1
    assert view["truncation"] == {"reason": "budget", "total": 1, "shown": 0}
    assert view["truncated"]


def test_nbt_inspector_slices_arrays_before_converting_to_lists(monkeypatch) -> None:
    tag = nbt.IntArrayTag(range(MAX_NBT_VIEW_ITEMS + 1))

    def reject_full_copy(_self):
        pytest.fail("The inspector must not convert the entire array")

    monkeypatch.setattr(type(tag.py_data), "tolist", reject_full_copy)
    assert _nbt_view_value(tag)["value"] == list(range(MAX_NBT_VIEW_ITEMS))


def test_nbt_inspector_does_not_materialize_entire_lists(monkeypatch) -> None:
    tag = nbt.ListTag([nbt.IntTag(value) for value in range(MAX_NBT_VIEW_ITEMS + 1)])

    def reject_full_iteration(_self):
        pytest.fail("The inspector must only access list entries within the excerpt")

    monkeypatch.setattr(nbt.ListTag, "__iter__", reject_full_iteration)
    view = _nbt_view_value(tag)
    assert len(view["value"]) == MAX_NBT_VIEW_ITEMS
    assert view["truncation"] == {"reason": "items", "total": MAX_NBT_VIEW_ITEMS + 1, "shown": MAX_NBT_VIEW_ITEMS}


def test_nbt_inspector_preserves_special_keys_and_text_as_data() -> None:
    key = 'a.b[0]["quoted"]'
    text = '<script>alert("NBT")</script>\näöüß'
    view = _nbt_view_value(nbt.CompoundTag({key: nbt.StringTag(text)}))
    assert view == {"type": "CompoundTag", "value": {key: {"type": "StringTag", "value": text}}}
    assert json.loads(json.dumps(view, allow_nan=False)) == view
