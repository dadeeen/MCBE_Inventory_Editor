"""Run generated dialog scripts in real children with only Tk replaced."""

import json

import pytest

from mcbe_editor import gui_dialogs


@pytest.fixture
def dialog_arguments(monkeypatch):
    # A headless dialog boundary returns the arguments it received. The actual
    # generated Python and UTF-8 subprocess pipe still execute unchanged.
    prefix = """
import json, sys, types
class Root:
    def withdraw(self): pass
    def attributes(self, *args): pass
def pick(**kwargs):
    return json.dumps(kwargs, ensure_ascii=False)
tk = types.ModuleType("tkinter")
tk.Tk = Root
tk.filedialog = types.SimpleNamespace(askdirectory=pick, askopenfilename=pick)
sys.modules["tkinter"] = tk
"""
    run = gui_dialogs.run_gui_script
    monkeypatch.setenv("PYTHONIOENCODING", "cp1252")
    monkeypatch.setattr(gui_dialogs, "run_gui_script", lambda script: run(prefix + script, timeout=15))
    return lambda name, *args: json.loads(getattr(gui_dialogs, name)(*args))


@pytest.mark.parametrize("name", ["select_folder", "select_player_export"])
@pytest.mark.parametrize(
    "initial",
    [
        "C:/Worlds/normal",
        "C:/Welten/München",
        "C:/Welten/世界",
        "C:/Welten/😀",
        "C:/Welten/𐐷/𝄞",
        "C:/Welten/😀/世界",
        'C:/Worlds/"Quoted"/It\'s a folder',
        "C:\\Worlds\\'); raise RuntimeError('not code') #",
    ],
)
def test_generated_dialog_keeps_initial_directory(dialog_arguments, name, initial):
    assert dialog_arguments(name, initial)["initialdir"] == initial


@pytest.mark.parametrize("name", ["select_folder", "select_player_export", "select_icon_pack", "select_icon_folder"])
@pytest.mark.parametrize("label", ["München / 世界", "Dialog 😀 / 𐐷", "Quote \" / ' / \\ / \n"])
def test_generated_dialog_keeps_translated_labels(dialog_arguments, monkeypatch, name, label):
    monkeypatch.setattr(gui_dialogs, "t", lambda text: label)
    arguments = dialog_arguments(name)
    assert arguments["title"] == label
    assert "initialdir" not in arguments
    if "filetypes" in arguments:
        assert arguments["filetypes"][-1] == [label, "*.*"]
