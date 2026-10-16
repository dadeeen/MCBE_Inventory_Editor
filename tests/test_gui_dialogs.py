import ast
import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from mcbe_editor import gui_dialogs


def test_run_gui_script_returns_stripped_stdout(monkeypatch):
    monkeypatch.setattr(
        gui_dialogs.subprocess,
        "run",
        Mock(return_value=SimpleNamespace(returncode=0, stdout=" C:/World \n", stderr="")),
    )

    result = gui_dialogs.run_gui_script("print('x')", timeout=12)

    assert result == "C:/World"
    gui_dialogs.subprocess.run.assert_called_once_with(
        [gui_dialogs.sys.executable, "-c", "print('x')"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        check=False,
        timeout=12,
    )


def test_run_gui_script_reports_stderr_on_failure(monkeypatch):
    monkeypatch.setattr(
        gui_dialogs.subprocess,
        "run",
        Mock(return_value=SimpleNamespace(returncode=1, stdout="", stderr="boom")),
    )

    with pytest.raises(RuntimeError, match="boom"):
        gui_dialogs.run_gui_script("broken")


def test_select_folder_escapes_initial_dir(monkeypatch):
    run_gui_script = Mock(return_value="C:/World")
    monkeypatch.setattr(gui_dialogs, "run_gui_script", run_gui_script)

    result = gui_dialogs.select_folder('C:/Worlds/"Quoted"')

    assert result == "C:/World"
    script = run_gui_script.call_args.args[0]
    initial = next(
        node.value
        for node in ast.parse(script).body
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "initialdir"
    )
    assert ast.literal_eval(initial) == 'C:/Worlds/"Quoted"'
    assert "askdirectory" in script


def test_select_player_export_uses_export_file_filter(monkeypatch):
    run_gui_script = Mock(return_value="C:/player.mcbe-player.zip")
    monkeypatch.setattr(gui_dialogs, "run_gui_script", run_gui_script)

    result = gui_dialogs.select_player_export("C:/Exports")

    assert result == "C:/player.mcbe-player.zip"
    script = run_gui_script.call_args.args[0]
    assert "*.mcbe-player.zip" in script
    assert "askopenfilename" in script


def test_select_icon_dialogs_use_resource_pack_titles(monkeypatch):
    run_gui_script = Mock(return_value="C:/pack.mcpack")
    monkeypatch.setattr(gui_dialogs, "run_gui_script", run_gui_script)

    assert gui_dialogs.select_icon_pack() == "C:/pack.mcpack"
    assert "Resource Pack / Icon Pack" in run_gui_script.call_args.args[0]

    assert gui_dialogs.select_icon_folder() == "C:/pack.mcpack"
    assert "Resource-Pack- oder Icon-Ordner" in run_gui_script.call_args.args[0]


@pytest.mark.parametrize("picker", ["select_folder", "select_player_export", "select_icon_pack", "select_icon_folder"])
def test_frozen_dialog_without_provider_fails_without_relaunch(monkeypatch, picker):
    monkeypatch.setattr(gui_dialogs.sys, "frozen", True, raising=False)
    monkeypatch.setattr(gui_dialogs, "_desktop_dialog", None)
    run = Mock(side_effect=AssertionError("must not invoke the EXE with -c"))
    monkeypatch.setattr(gui_dialogs.subprocess, "run", run)
    with pytest.raises(gui_dialogs.UserFacingRuntimeError, match="Dateidialog|file dialog"):
        getattr(gui_dialogs, picker)()
    run.assert_not_called()
