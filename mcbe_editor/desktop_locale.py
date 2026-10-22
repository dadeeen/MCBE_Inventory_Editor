"""Native messages follow the editor language, including before WebView starts."""

from __future__ import annotations

import ctypes
import locale
import logging
import threading
from pathlib import Path

from mcbe_editor.i18n import DEFAULT_LOCALE, SUPPORTED_LOCALES, resolve_locale, translate
from mcbe_editor.runtime_data import atomic_write_private_text

LOGGER = logging.getLogger(__name__)


def windows_ui_locale() -> str:
    """Use the display language, not regional number/date formatting settings."""
    try:
        language = ctypes.windll.kernel32.GetUserDefaultUILanguage
        language.argtypes = []
        language.restype = ctypes.c_ushort
        tag = locale.windows_locale.get(language(), "").replace("_", "-")
        return resolve_locale(None, tag)
    except (AttributeError, OSError):
        return DEFAULT_LOCALE


class DesktopLocale:
    def __init__(self, data: Path | None = None):
        self.locale = windows_ui_locale()
        self._path: Path | None = None
        self._saved: str | None = None
        self._lock = threading.Lock()
        if data is not None:
            self.load(data)

    def load(self, data: Path) -> None:
        self._path = data / "desktop-language.txt"
        try:
            saved = self._path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            return
        if saved in SUPPORTED_LOCALES:
            self.locale = self._saved = saved

    def remember(self, selected: str) -> None:
        if not isinstance(selected, str) or selected not in SUPPORTED_LOCALES:
            return
        with self._lock:
            self.locale = selected
            if self._path is not None and self._saved != selected:
                try:
                    atomic_write_private_text(self._path, selected + "\n")
                    self._saved = selected
                except OSError:
                    # A preference write must never prevent opening/closing the editor.
                    LOGGER.warning("Could not remember the native dialog language", exc_info=True)

    def translate(self, text: str, **params: object) -> str:
        return translate(text, self.locale, params or None)
