"""Localization helper for updater subprocess output."""

from __future__ import annotations

import os

from mcbe_editor.i18n import SUPPORTED_LOCALES, translate

UPDATE_LOCALE_ENV = "MCBE_UPDATE_LOCALE"


def update_output_locale() -> str:
    """Return the explicitly forwarded UI locale, defaulting to German."""

    locale = os.environ.get(UPDATE_LOCALE_ENV, "").strip().lower()
    return locale if locale in SUPPORTED_LOCALES else "de"


def output_t(text: str, **params: object) -> str:
    """Translate an updater message for the locale forwarded by the app."""

    return translate(text, update_output_locale(), params or None)
