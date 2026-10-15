"""Exercise real child-process pipes independently of the OS default encoding."""

import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from mcbe_editor import gui_dialogs, update_script_runner


@pytest.mark.parametrize("path", ["C:/World", "C:/Welten/München", "C:/Welten/世界", "C:/Welten/😀"])
def test_gui_child_preserves_unicode_paths_with_legacy_inherited_encoding(monkeypatch, path):
    monkeypatch.setenv("PYTHONIOENCODING", "cp1252")

    assert gui_dialogs.run_gui_script(f"print({ascii(path)})") == path
    assert os.environ["PYTHONIOENCODING"] == "cp1252"


def test_gui_child_reports_unicode_stderr_without_losing_the_message(monkeypatch):
    monkeypatch.setenv("PYTHONIOENCODING", "cp1252")
    message = "Auswahl für München / 世界 fehlgeschlagen"

    with pytest.raises(RuntimeError, match=message):
        gui_dialogs.run_gui_script(f"raise RuntimeError({ascii(message)})")


def test_gui_reader_does_not_use_the_parent_locale(monkeypatch):
    monkeypatch.setenv("PYTHONIOENCODING", "utf-8")
    monkeypatch.setattr(subprocess, "_text_encoding", lambda: "cp1252")
    path = "C:/Welten/München/世界"

    assert gui_dialogs.run_gui_script(f"print({ascii(path)})") == path


@pytest.mark.parametrize("kind", ["db", "icons"])
@pytest.mark.parametrize("inherited_encoding", ["cp1252", "ascii"])
def test_update_child_preserves_unicode_output(tmp_path, monkeypatch, kind, inherited_encoding):
    monkeypatch.setenv("PYTHONIOENCODING", inherited_encoding)
    # Tiny real child modules exercise the runner, without network/update writes.
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "__init__.py").write_text("", encoding="utf-8")
    text = "München / 世界 → fertig"
    (scripts / f"update_{kind}.py").write_text(f"print({ascii(text)})\n", encoding="utf-8")
    config = _config(tmp_path)

    result = getattr(update_script_runner, f"run_update_{kind}")(tmp_path, config)

    assert result == (0, text + "\n")
    assert os.environ["PYTHONIOENCODING"] == inherited_encoding


@pytest.mark.parametrize("kind", ["db", "icons"])
def test_update_reader_keeps_unicode_failure_output_with_non_utf8_parent(tmp_path, monkeypatch, kind):
    monkeypatch.setenv("PYTHONIOENCODING", "utf-8")
    monkeypatch.setattr(subprocess, "_text_encoding", lambda: "cp1252")
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "__init__.py").write_text("", encoding="utf-8")
    text = "Fehler für München / 世界"
    (scripts / f"update_{kind}.py").write_text(f"import sys\nprint({ascii(text)}, file=sys.stderr)\nraise SystemExit(7)\n", encoding="utf-8")

    assert getattr(update_script_runner, f"run_update_{kind}")(tmp_path, _config(tmp_path)) == (7, text + "\n")


def _config(root: Path) -> SimpleNamespace:
    return SimpleNamespace(
        data_root=str(root / "data"),
        item_db_path=str(root / "data" / "item_db.json"),
        update_cache_dir=str(root / "cache"),
        source_version_path=str(root / "meta" / "source_version.json"),
        source_version_history_path=str(root / "meta" / "source_version_history.json"),
    )
