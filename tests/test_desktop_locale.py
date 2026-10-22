from __future__ import annotations

import ctypes
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from mcbe_editor import desktop_app, desktop_locale


@pytest.mark.parametrize("language,expected", [(0x0407, "de"), (0x0807, "de"), (0x0409, "en"), (0x040C, "en"), (0xFFFF, "en")])
def test_native_language_uses_windows_display_language(monkeypatch, language, expected):
    get_language = Mock(return_value=language)
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(kernel32=SimpleNamespace(GetUserDefaultUILanguage=get_language)), raising=False)
    assert desktop_locale.windows_ui_locale() == expected


def test_native_language_falls_back_to_english_when_windows_query_fails(monkeypatch):
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(kernel32=SimpleNamespace(GetUserDefaultUILanguage=Mock(side_effect=OSError))), raising=False)
    assert desktop_locale.windows_ui_locale() == "en"


@pytest.mark.parametrize("saved,expected", [(b"en\n", "en"), (b"de\n", "de"), (b"fr", "de"), (b"\xff", "de")])
def test_native_language_loads_only_supported_saved_preferences(tmp_path, monkeypatch, saved, expected):
    monkeypatch.setattr(desktop_locale, "windows_ui_locale", lambda: "de")
    (tmp_path / "desktop-language.txt").write_bytes(saved)
    assert desktop_locale.DesktopLocale(tmp_path).locale == expected


def test_native_language_follows_editor_selection_and_survives_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(desktop_locale, "windows_ui_locale", lambda: "de")
    translations = desktop_locale.DesktopLocale(tmp_path)
    assert translations.translate("Editor schließen") == "Editor schließen"
    translations.remember("en")
    assert translations.translate("Editor schließen") == "Close editor"
    restarted = desktop_locale.DesktopLocale(tmp_path)
    assert restarted.locale == "en"
    restarted.remember("de")
    assert desktop_locale.DesktopLocale(tmp_path).locale == "de"
    restarted.remember("fr")
    restarted.remember(None)
    assert desktop_locale.DesktopLocale(tmp_path).locale == "de"


def test_native_language_stays_usable_when_preference_cannot_be_written(tmp_path, monkeypatch):
    translations = desktop_locale.DesktopLocale(tmp_path)
    monkeypatch.setattr(desktop_locale, "atomic_write_private_text", Mock(side_effect=OSError("read only")))
    translations.remember("en")
    assert translations.translate("Editor schließen") == "Close editor"


def test_startup_and_unknown_document_errors_use_the_selected_language(tmp_path, monkeypatch):
    monkeypatch.setattr(desktop_locale, "windows_ui_locale", lambda: "de")
    translations = desktop_locale.DesktopLocale(tmp_path)
    translations.remember("en")
    message = desktop_app.startup_error_message(RuntimeError("example error"), tmp_path / "desktop.log", translate=translations.translate)
    assert message.startswith("The editor could not be started: example error")
    assert "for details." in message
    window = Mock()
    window.evaluate_js.return_value = None
    window.create_confirmation_dialog.return_value = False
    guard = desktop_app.CloseGuard(window, lambda: False, translate=translations.translate)
    guard._confirming.acquire()
    guard._confirm()
    title, message = window.create_confirmation_dialog.call_args.args
    assert title == "Close editor"
    assert "could not be checked" in message
    window.destroy.assert_not_called()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows instance lock")
def test_duplicate_instance_error_uses_saved_language(tmp_path):
    translations = desktop_locale.DesktopLocale(tmp_path)
    translations.remember("en")
    with (
        desktop_app.desktop_instance(tmp_path),
        pytest.raises(RuntimeError, match="already open"),
        desktop_app.desktop_instance(tmp_path, translate=translations.translate),
    ):
        pytest.fail("Second host acquired the lock")
