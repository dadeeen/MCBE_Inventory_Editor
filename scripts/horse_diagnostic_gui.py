#!/usr/bin/env python3
"""Small Windows-friendly GUI for horse diagnostic reports.

The CLI diagnostic is still the source of truth, but this wrapper avoids copying
world paths into PowerShell for every before/after load snapshot.
"""

from __future__ import annotations

import contextlib
import json
import os
import queue
import re
import sys
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
for path in (ROOT, SCRIPT_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from horse_diagnostic import MOUNT_IDENTIFIERS, find_horses  # noqa: E402

from mcbe_editor.runtime_data import atomic_write_private_text, ensure_private_directory  # noqa: E402

MINECRAFT_SUBPATH = Path("games") / "com.mojang" / "minecraftWorlds"


def default_report_directory() -> Path:
    configured = os.environ.get("MCBE_HORSE_DIAGNOSTIC_DIR")
    if configured:
        return Path(configured).expanduser()
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "MCBE Inventory Editor" / "diagnostics" / "horse"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "MCBE Inventory Editor" / "diagnostics" / "horse"
    state_home = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")).expanduser()
    return state_home / "mcbe-inventory-editor" / "diagnostics" / "horse"


REPORT_DIR = default_report_directory()
# GUI reports always include the full typed NBT tree and raw hex bytes for
# every mount type: state variants (tamed vs wild, sitting vs standing, ...)
# differ in definitions/Temper/OwnerNew details that the aggregated summary
# does not capture, and the evidence-first workflow needs them exactly.
RAW_DUMP_IDENTIFIERS = MOUNT_IDENTIFIERS


def safe_text(value: object) -> str:
    return "" if value is None else str(value)


def sanitize_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.=-]+", "_", value.strip())
    return cleaned.strip("_") or "world"


def read_level_name(world_dir: Path) -> str:
    for name in ("levelname.txt", "LevelName.txt"):
        path = world_dir / name
        if path.exists():
            try:
                text = path.read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                text = ""
            if text:
                return text
    return world_dir.name


def mtime_for_world(world_dir: Path) -> float:
    candidates = [world_dir]
    db_dir = world_dir / "db"
    if db_dir.exists():
        candidates.append(db_dir)
    level_dat = world_dir / "level.dat"
    if level_dat.exists():
        candidates.append(level_dat)
    values = []
    for path in candidates:
        with contextlib.suppress(OSError):
            values.append(path.stat().st_mtime)
    return max(values) if values else 0.0


def candidate_world_roots() -> list[Path]:
    roots: list[Path] = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        users_root = Path(appdata) / "Minecraft Bedrock" / "Users"
        if users_root.exists():
            for user_dir in users_root.iterdir():
                root = user_dir / MINECRAFT_SUBPATH
                if root.exists():
                    roots.append(root)
    localappdata = os.environ.get("LOCALAPPDATA")
    if localappdata:
        uwp_root = Path(localappdata) / "Packages" / "Microsoft.MinecraftUWP_8wekyb3d8bbwe" / "LocalState" / MINECRAFT_SUBPATH
        if uwp_root.exists():
            roots.append(uwp_root)
    unique: list[Path] = []
    seen = set()
    for root in roots:
        resolved = str(root.resolve()) if root.exists() else str(root)
        if resolved not in seen:
            seen.add(resolved)
            unique.append(root)
    return unique


class HorseDiagnosticGui:
    def __init__(self, master: tk.Tk) -> None:
        self.master = master
        self.master.title("MCBE Horse Diagnostic")
        self.master.geometry("1080x720")
        self.worlds: list[dict[str, object]] = []
        self.result_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        roots = candidate_world_roots()
        self.world_root = tk.StringVar(value=str(roots[0]) if roots else "")
        self.status_text = tk.StringVar(value="Bereit.")
        self.selected_report_dir = REPORT_DIR
        self._build_ui()
        self.refresh_worlds()
        self.master.after(150, self._poll_queue)

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.master, padding=12)
        outer.pack(fill=tk.BOTH, expand=True)

        root_frame = ttk.LabelFrame(outer, text="Minecraft-Weltordner")
        root_frame.pack(fill=tk.X)
        ttk.Entry(root_frame, textvariable=self.world_root).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 6), pady=8)
        ttk.Button(root_frame, text="Suchen...", command=self.choose_world_root).pack(side=tk.LEFT, padx=4, pady=8)
        ttk.Button(root_frame, text="Aktualisieren", command=self.refresh_worlds).pack(side=tk.LEFT, padx=(4, 8), pady=8)

        middle = ttk.Frame(outer)
        middle.pack(fill=tk.BOTH, expand=True, pady=(10, 8))

        world_frame = ttk.LabelFrame(middle, text="Welten")
        world_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 8))
        columns = ("name", "folder", "modified")
        self.world_tree = ttk.Treeview(world_frame, columns=columns, show="headings", selectmode="browse")
        self.world_tree.heading("name", text="Name")
        self.world_tree.heading("folder", text="Ordner")
        self.world_tree.heading("modified", text="Geändert")
        self.world_tree.column("name", width=220, anchor=tk.W)
        self.world_tree.column("folder", width=190, anchor=tk.W)
        self.world_tree.column("modified", width=150, anchor=tk.W)
        self.world_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(8, 0), pady=8)
        world_scroll = ttk.Scrollbar(world_frame, orient=tk.VERTICAL, command=self.world_tree.yview)
        world_scroll.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 8), pady=8)
        self.world_tree.configure(yscrollcommand=world_scroll.set)

        output_frame = ttk.LabelFrame(middle, text="Ausgabe")
        output_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(8, 0))
        self.output = tk.Text(output_frame, wrap=tk.WORD, height=18)
        self.output.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(8, 0), pady=8)
        output_scroll = ttk.Scrollbar(output_frame, orient=tk.VERTICAL, command=self.output.yview)
        output_scroll.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 8), pady=8)
        self.output.configure(yscrollcommand=output_scroll.set)

        button_frame = ttk.Frame(outer)
        button_frame.pack(fill=tk.X)
        ttk.Button(button_frame, text="Diagnose: vor Weltladen", command=lambda: self.run_diagnostic("before_load")).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(button_frame, text="Diagnose: nach Weltladen", command=lambda: self.run_diagnostic("after_load")).pack(side=tk.LEFT, padx=8)
        ttk.Button(button_frame, text="Weltordner öffnen", command=self.open_selected_world).pack(side=tk.LEFT, padx=8)
        ttk.Button(button_frame, text="Report-Ordner öffnen", command=self.open_report_dir).pack(side=tk.LEFT, padx=8)
        ttk.Label(button_frame, textvariable=self.status_text).pack(side=tk.RIGHT)

    def choose_world_root(self) -> None:
        initial = self.world_root.get() or str(Path.home())
        path = filedialog.askdirectory(title="minecraftWorlds-Ordner auswählen", initialdir=initial)
        if path:
            self.world_root.set(path)
            self.refresh_worlds()

    def refresh_worlds(self) -> None:
        root = Path(self.world_root.get()).expanduser()
        self.world_tree.delete(*self.world_tree.get_children())
        self.worlds = []
        if not root.exists():
            self.status_text.set("Weltordner nicht gefunden.")
            return
        for world_dir in root.iterdir():
            if not world_dir.is_dir() or not (world_dir / "db").exists():
                continue
            mtime = mtime_for_world(world_dir)
            self.worlds.append(
                {
                    "path": world_dir,
                    "name": read_level_name(world_dir),
                    "folder": world_dir.name,
                    "mtime": mtime,
                }
            )
        self.worlds.sort(key=lambda item: float(item["mtime"]), reverse=True)
        for index, item in enumerate(self.worlds):
            modified = datetime.fromtimestamp(float(item["mtime"])).strftime("%Y-%m-%d %H:%M:%S") if item["mtime"] else "?"
            self.world_tree.insert("", tk.END, iid=str(index), values=(item["name"], item["folder"], modified))
        if self.worlds:
            self.world_tree.selection_set("0")
            self.world_tree.focus("0")
            self.status_text.set(f"{len(self.worlds)} Welten gefunden.")
        else:
            self.status_text.set("Keine Welten gefunden.")

    def selected_world(self) -> dict[str, object] | None:
        selection = self.world_tree.selection()
        if not selection:
            messagebox.showwarning("Keine Welt", "Bitte zuerst eine Welt auswählen.")
            return None
        try:
            return self.worlds[int(selection[0])]
        except (IndexError, ValueError):
            messagebox.showwarning("Keine Welt", "Die ausgewählte Welt konnte nicht gelesen werden.")
            return None

    def run_diagnostic(self, label: str) -> None:
        world = self.selected_world()
        if not world:
            return
        world_path = Path(world["path"])
        self.status_text.set("Diagnose läuft...")
        self._append(f"\nStarte Diagnose {label} für {world['name']} ({world['folder']})...\n")
        thread = threading.Thread(target=self._diagnostic_worker, args=(world_path, label), daemon=True)
        thread.start()

    def _diagnostic_worker(self, world_path: Path, label: str) -> None:
        try:
            result = find_horses(str(world_path), identifiers=MOUNT_IDENTIFIERS, dump_identifiers=RAW_DUMP_IDENTIFIERS)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"horse_diag_{label}_{sanitize_filename(world_path.name)}_{timestamp}.json"
            report_path = self.selected_report_dir / filename
            atomic_write_private_text(report_path, json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
            self.result_queue.put(("success", (label, result, report_path)))
        except Exception as exc:  # pragma: no cover - GUI safety net
            self.result_queue.put(("error", exc))

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self.result_queue.get_nowait()
                if kind == "success":
                    label, result, report_path = payload  # type: ignore[misc]
                    self.status_text.set("Diagnose fertig.")
                    self._append(self._format_result(label, result, Path(report_path)))
                else:
                    self.status_text.set("Fehler.")
                    messagebox.showerror("Diagnose fehlgeschlagen", str(payload))
                    self._append(f"Fehler: {payload}\n")
        except queue.Empty:
            pass
        self.master.after(150, self._poll_queue)

    def _format_result(self, label: str, result: dict[str, object], report_path: Path) -> str:
        world = result.get("world", {}) if isinstance(result.get("world"), dict) else {}
        counts = result.get("counts", {}) if isinstance(result.get("counts"), dict) else {}
        diagnosis = result.get("diagnosis", {}) if isinstance(result.get("diagnosis"), dict) else {}
        records = result.get("records", []) if isinstance(result.get("records"), list) else []
        by_identifier = counts.get("by_identifier") if isinstance(counts.get("by_identifier"), dict) else {}
        per_type = " ".join(f"{str(name).replace('minecraft:', '')}={count}" for name, count in sorted(by_identifier.items())) or "keine"
        evidence = result.get("writer_evidence", {}) if isinstance(result.get("writer_evidence"), dict) else {}
        lines = [
            f"\n[{label}] {safe_text(world.get('name'))} ({safe_text(world.get('folder_name'))})",
            f"Mounts gefunden: {safe_text(counts.get('horses'))} ({per_type})",
            f"digp verknüpft: {safe_text(diagnosis.get('indexed_horses'))}",
            f"digp fehlt:      {safe_text(diagnosis.get('not_indexed_horses'))}",
        ]
        for index, record in enumerate(records, start=1):
            if not isinstance(record, dict):
                continue
            pos = record.get("position", {}) if isinstance(record.get("position"), dict) else {}
            lines.append(
                f"{index}. {safe_text(str(record.get('identifier', '?')).replace('minecraft:', ''))} "
                f"suffix={safe_text(record.get('actor_suffix_hex'))} "
                f"class={safe_text(record.get('classification'))} "
                f"pos=({float(pos.get('x', 0.0)):.2f}, {float(pos.get('y', 0.0)):.2f}, {float(pos.get('z', 0.0)):.2f}) "
                f"raw={safe_text(record.get('raw_length'))} "
                f"digp={safe_text(record.get('digp_contains_actor_suffix'))}"
            )
        for identifier, entry in sorted(evidence.items()):
            if not isinstance(entry, dict):
                continue
            variants = entry.get("definitions_variants") or []
            lines.append(
                f"Evidenz {safe_text(str(identifier).replace('minecraft:', ''))}: "
                f"{safe_text(entry.get('observed_records'))} Minecraft-Records, "
                f"{len(variants)} Definitions-Variante(n) im Report."
            )
        dump_count = counts.get("raw_nbt_dumps") or 0
        if dump_count:
            dump_types = " ".join(str(name).replace("minecraft:", "") for name in RAW_DUMP_IDENTIFIERS)
            lines.append(f"Raw-NBT-Dump: {dump_count} Record(s) für {dump_types} (typisierter NBT-Baum + Roh-Hex im Report).")
        lines.append(f"Report: {report_path}")
        lines.append("")
        return "\n".join(lines)

    def _append(self, text: str) -> None:
        self.output.insert(tk.END, text)
        self.output.see(tk.END)

    def open_selected_world(self) -> None:
        world = self.selected_world()
        if not world:
            return
        path = Path(world["path"])
        if path.exists():
            os.startfile(path)  # type: ignore[attr-defined]

    def open_report_dir(self) -> None:
        ensure_private_directory(self.selected_report_dir)
        os.startfile(self.selected_report_dir)  # type: ignore[attr-defined]


def main() -> int:
    root = tk.Tk()
    with contextlib.suppress(tk.TclError):
        root.call("tk", "scaling", 1.25)
    HorseDiagnosticGui(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
