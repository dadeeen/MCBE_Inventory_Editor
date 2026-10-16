"""Small wrappers around native GUI file/folder dialogs."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable

from .i18n import t
from .service_errors import UserFacingRuntimeError

_desktop_dialog: Callable[..., str] | None = None


def set_desktop_dialog(provider: Callable[..., str] | None) -> None:
    """Inject the desktop window's native picker without importing a GUI runtime."""
    global _desktop_dialog
    _desktop_dialog = provider


def run_gui_script(script: str, timeout: int = 60) -> str:
    if getattr(sys, "frozen", False):
        # The EXE is not an arbitrary Python interpreter. A missing native
        # provider must fail visibly, never relaunch the editor with -c.
        raise UserFacingRuntimeError(t("Der native Dateidialog ist nicht verfügbar. Bitte den Desktop-Editor neu starten."))
    # File paths must survive both legacy Windows code pages and inherited
    # PYTHONIOENCODING overrides. Set the same encoding on both pipe ends.
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        res = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            check=False,
            timeout=timeout,
        )
        if res.returncode != 0:
            stderr = res.stderr.strip()
            raise RuntimeError(t("GUI-Dialog fehlgeschlagen: {error}", error=stderr or t("Unbekannter Fehler")))
        return res.stdout.strip()
    except subprocess.TimeoutExpired as exc:
        raise UserFacingRuntimeError(t("GUI-Dialog hat zu lange gedauert (Timeout).")) from exc


def select_folder(initial_dir: str | None = None) -> str:
    if _desktop_dialog is not None:
        return _desktop_dialog(folder=True, initial_dir=initial_dir)
    # This is embedded Python source, not JSON (non-BMP escapes differ).
    initial = ascii(initial_dir or "")
    title = ascii(t('Wähle den Minecraft Welt-Ordner (der den "db" Ordner enthält)'))
    script = (
        "import tkinter as tk; "
        "from tkinter import filedialog; "
        "root = tk.Tk(); "
        "root.withdraw(); "
        "root.attributes('-topmost', True); "
        f"initialdir = {initial}; "
        f"kwargs = {{'title': {title}}}; "
        "kwargs.update({'initialdir': initialdir} if initialdir else {}); "
        "path = filedialog.askdirectory(**kwargs); "
        "print(path)"
    )
    return run_gui_script(script)


def select_player_export(initial_dir: str | None = None) -> str:
    if _desktop_dialog is not None:
        return _desktop_dialog(folder=False, initial_dir=initial_dir, file_types=(t("Spieler-Export (*.mcbe-player.zip;*.zip)"),))
    initial = ascii(initial_dir or "")
    title = ascii(t("Wähle einen Spieler-Export"))
    all_files = ascii(t("Alle Dateien"))
    script = (
        "import tkinter as tk; "
        "from tkinter import filedialog; "
        "root = tk.Tk(); "
        "root.withdraw(); "
        "root.attributes('-topmost', True); "
        f"initialdir = {initial}; "
        f"kwargs = {{'title': {title}, "
        f"    'filetypes': [('MCBE Player Export', '*.mcbe-player.zip'), ('ZIP', '*.zip'), ({all_files}, '*.*')]}}; "
        "kwargs.update({'initialdir': initialdir} if initialdir else {}); "
        "path = filedialog.askopenfilename("
        "    **kwargs"
        "); "
        "print(path)"
    )
    return run_gui_script(script)


def select_icon_pack() -> str:
    if _desktop_dialog is not None:
        return _desktop_dialog(folder=False, file_types=(t("Bedrock-Ressourcenpaket (*.mcpack;*.zip)"),))
    title = ascii(t("Wähle Resource Pack / Icon Pack"))
    all_files = ascii(t("Alle Dateien"))
    script = (
        "import tkinter as tk; "
        "from tkinter import filedialog; "
        "root = tk.Tk(); "
        "root.withdraw(); "
        "root.attributes('-topmost', True); "
        "path = filedialog.askopenfilename("
        f"    title={title}, "
        f"    filetypes=[('Bedrock Resource Pack', '*.mcpack'), ('ZIP', '*.zip'), ({all_files}, '*.*')]"
        "); "
        "print(path)"
    )
    return run_gui_script(script)


def select_icon_folder() -> str:
    if _desktop_dialog is not None:
        return _desktop_dialog(folder=True)
    title = ascii(t("Wähle Resource-Pack- oder Icon-Ordner"))
    script = (
        "import tkinter as tk; "
        "from tkinter import filedialog; "
        "root = tk.Tk(); "
        "root.withdraw(); "
        "root.attributes('-topmost', True); "
        f"path = filedialog.askdirectory(title={title}); "
        "print(path)"
    )
    return run_gui_script(script)
