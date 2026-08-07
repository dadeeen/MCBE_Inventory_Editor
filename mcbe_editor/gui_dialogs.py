"""Small wrappers around native GUI file/folder dialogs."""

from __future__ import annotations

import json
import subprocess
import sys

from .i18n import t


def run_gui_script(script: str, timeout: int = 60) -> str:
    try:
        res = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
        if res.returncode != 0:
            stderr = res.stderr.strip()
            raise RuntimeError(t("GUI-Dialog fehlgeschlagen: {error}", error=stderr or t("Unbekannter Fehler")))
        return res.stdout.strip()
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(t("GUI-Dialog hat zu lange gedauert (Timeout).")) from exc


def select_folder(initial_dir: str | None = None) -> str:
    initial = json.dumps(initial_dir or "")
    title = json.dumps(t('Wähle den Minecraft Welt-Ordner (der den "db" Ordner enthält)'))
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
    initial = json.dumps(initial_dir or "")
    title = json.dumps(t("Wähle einen Spieler-Export"))
    all_files = json.dumps(t("Alle Dateien"))
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
    title = json.dumps(t("Wähle Resource Pack / Icon Pack"))
    all_files = json.dumps(t("Alle Dateien"))
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
    title = json.dumps(t("Wähle Resource-Pack- oder Icon-Ordner"))
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
