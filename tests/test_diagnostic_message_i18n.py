from types import SimpleNamespace

import pytest
from flask import Flask

from mcbe_editor import nbt
from mcbe_editor._inventory_core import MAX_NBT_VIEW_ITEMS, _nbt_view_value
from mcbe_editor.compatibility import analyze_player_compatibility
from mcbe_editor.deployment import worlds_root_status, write_gate_setup_status


@pytest.mark.parametrize("locale, suffix", [("en", "more"), ("de", "weitere")])
def test_root_tag_note_translates_nested_count(locale, suffix):
    player = nbt.CompoundTag({f"Extra{i:02}": nbt.IntTag(i) for i in range(28)})
    with Flask(__name__).test_request_context(headers={"Accept-Language": locale}):
        report = analyze_player_compatibility(player)
    note = report["notes"][0]
    assert f"(+16 {suffix})" in note
    assert "Extra00" in note
    assert note.startswith("Additional root tags:" if locale == "en" else "Zusätzliche Root-Tags:")


@pytest.mark.parametrize("locale", ["en", "de"])
def test_world_root_messages_follow_request_locale(tmp_path, locale):
    config = SimpleNamespace(mode="local", is_docker=False, worlds_root=None, world_scan_depth=3)
    with Flask(__name__).test_request_context(headers={"Accept-Language": locale}):
        assert worlds_root_status(config)["message"] == ("No worlds root configured." if locale == "en" else "Kein Welt-Root konfiguriert.")
        config.worlds_root = str(tmp_path / "missing")
        assert worlds_root_status(config)["message"] == (
            f"World root does not exist: {config.worlds_root}" if locale == "en" else f"Welt-Root existiert nicht: {config.worlds_root}"
        )
        config.worlds_root = str(tmp_path)
        empty = worlds_root_status(config)
        assert ("is empty" if locale == "en" else "ist leer") in empty["message"]
        (tmp_path / "example.txt").touch()
        readable = worlds_root_status(config)
        assert ("is readable" if locale == "en" else "ist lesbar") in readable["message"]
        assert str(tmp_path) in readable["message"]


def test_write_gate_setup_translates_dynamic_host():
    config = SimpleNamespace(require_server_offline=True, server_host="localhost", server_port=19132)
    with Flask(__name__).test_request_context(headers={"Accept-Language": "en"}):
        assert write_gate_setup_status(config)["message"] == "The server-offline write gate checks localhost:19132."


@pytest.mark.parametrize("locale, fields, values", [("en", "more fields", "more values"), ("de", "weitere Felder", "weitere Werte")])
def test_nbt_truncation_messages_follow_locale(locale, fields, values):
    count = MAX_NBT_VIEW_ITEMS + 2
    compound = nbt.CompoundTag({f"field{i}": nbt.IntTag(i) for i in range(count)})
    array = nbt.IntArrayTag(list(range(count)))
    with Flask(__name__).test_request_context(headers={"Accept-Language": locale}):
        assert _nbt_view_value(compound)["truncated"] == f"2 {fields}"
        assert _nbt_view_value(array)["truncated"] == f"2 {values}"
