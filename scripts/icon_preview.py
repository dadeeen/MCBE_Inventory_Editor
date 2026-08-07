#!/usr/bin/env python3
"""Erzeugt eine lokale, nicht versionierte HTML-Gesamtvorschau aller Item-Icons."""

# ruff: noqa: E501 -- CSS/JavaScript bleiben im eigenständig erzeugten HTML kompakt.

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import urllib.parse
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ITEM_DB = ROOT / "data" / "item_db.json"
DEFAULT_ICON_INDEX = ROOT / "data" / "icon_index_cache.json"
DEFAULT_OUTPUT = ROOT / ".tmp" / "icon-preview.html"
MAX_ARCHIVE_ICON_BYTES = 2_000_000


def _read_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"{label} nicht gefunden: {path}") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise RuntimeError(f"{label} ist nicht lesbar oder ungültig: {path}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"{label} enthält kein JSON-Objekt: {path}")
    return data


def _archive_data_url(entry: dict[str, Any]) -> tuple[str, str]:
    archive_raw = entry.get("archive_path")
    member_raw = entry.get("archive_member")
    if not archive_raw or not member_raw:
        return "", "Icon-Eintrag enthält weder Datei noch Archiveintrag."
    archive = Path(str(archive_raw)).expanduser()
    member = str(member_raw).replace("\\", "/")
    try:
        with zipfile.ZipFile(archive) as zf:
            matches = [info for info in zf.infolist() if info.filename.replace("\\", "/") == member]
            if len(matches) != 1:
                return "", "Archiveintrag fehlt oder ist nicht eindeutig."
            info = matches[0]
            if info.is_dir() or info.file_size <= 0 or info.file_size > MAX_ARCHIVE_ICON_BYTES:
                return "", "Archiveintrag hat eine ungültige Größe."
            raw = zf.read(info)
    except (OSError, zipfile.BadZipFile) as exc:
        return "", f"Archiv nicht lesbar: {exc.__class__.__name__}"
    suffix = PurePosixPath(member).suffix.lower()
    mime = mimetypes.types_map.get(suffix, "application/octet-stream")
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}", ""


def _file_data_url(path: Path) -> tuple[str, str]:
    try:
        size = path.stat().st_size
        if size <= 0 or size > MAX_ARCHIVE_ICON_BYTES:
            return "", "Icon-Datei hat eine ungültige Größe."
        raw = path.read_bytes()
    except OSError as exc:
        return "", f"Icon-Datei nicht lesbar: {exc.__class__.__name__}"
    mime = mimetypes.types_map.get(path.suffix.lower(), "application/octet-stream")
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}", ""


def _preview_url(entry: dict[str, Any], output_path: Path, *, embed_files: bool) -> tuple[str, str]:
    path_raw = entry.get("path")
    if path_raw:
        try:
            path = Path(str(path_raw)).expanduser()
            if embed_files:
                return _file_data_url(path)
            return _browser_reference(path, output_path), ""
        except (OSError, ValueError) as exc:
            return "", f"Icon-Pfad ist ungültig: {exc.__class__.__name__}"
    return _archive_data_url(entry)


def build_preview_payload(
    item_db: dict[str, Any],
    icon_index: dict[str, Any],
    output_path: Path = DEFAULT_OUTPUT,
    *,
    embed_files: bool = False,
) -> dict[str, Any]:
    items = item_db.get("items")
    aliases = item_db.get("compat_item_aliases")
    addable_raw = item_db.get("addable_items")
    block_only_raw = item_db.get("block_only_items", [])
    raw_icons = icon_index.get("icons")
    raw_display_icons = icon_index.get("display_icons", {})
    if not isinstance(items, dict):
        raise RuntimeError("Die Item-Datenbank enthält kein gültiges 'items'-Objekt.")
    if not isinstance(raw_icons, dict):
        raise RuntimeError("Der Icon-Index enthält kein gültiges 'icons'-Objekt.")
    if not isinstance(raw_display_icons, dict):
        raise RuntimeError("Der Icon-Index enthält kein gültiges 'display_icons'-Objekt.")

    def preview_entries(raw_entries: dict[str, Any]) -> dict[str, dict[str, str]]:
        entries: dict[str, dict[str, str]] = {}
        for entry_id, raw_entry in raw_entries.items():
            if not isinstance(entry_id, str) or not isinstance(raw_entry, dict):
                continue
            url, preview_error = _preview_url(raw_entry, output_path, embed_files=embed_files)
            texture = raw_entry.get("archive_member") or raw_entry.get("path") or ""
            entries[entry_id.lower()] = {
                "url": url,
                "source": str(raw_entry.get("source") or ""),
                "texture": str(texture),
                "preview_error": preview_error,
            }
        return entries

    icons = preview_entries(raw_icons)
    display_icons = preview_entries(raw_display_icons)

    normalized_items = {str(item_id).lower(): value for item_id, value in items.items() if isinstance(item_id, str)}
    normalized_aliases = {
        str(item_id).lower(): str(target).lower()
        for item_id, target in (aliases.items() if isinstance(aliases, dict) else [])
        if isinstance(item_id, str) and isinstance(target, str)
    }
    block_only_ids = {str(item_id).lower() for item_id in (block_only_raw if isinstance(block_only_raw, list) else []) if isinstance(item_id, str)}
    if isinstance(addable_raw, list):
        addable_ids = {str(item_id).lower() for item_id in addable_raw if isinstance(item_id, str)}
    else:
        addable_ids = set(normalized_items) - block_only_ids
    catalog_item_ids = set(normalized_items)
    compatibility_ids = sorted(catalog_item_ids - addable_ids)
    for item_id in addable_ids:
        alias_target = normalized_aliases.get(item_id)
        if item_id not in normalized_items and alias_target in normalized_items:
            normalized_items[item_id] = normalized_items[alias_target]
    item_ids = sorted(addable_ids)
    return {
        "items": normalized_items,
        "aliases": normalized_aliases,
        "icons": icons,
        "display_icons": display_icons,
        "item_ids": item_ids,
        "compatibility_ids": compatibility_ids,
        "extra_ids": sorted(set(icons) - set(item_ids) - set(compatibility_ids)),
        "display_ids": sorted(display_icons),
        "excluded_non_addable_count": len(compatibility_ids),
        "index_count": len(icons),
        "display_count": len(display_icons),
        "warning_count": len(icon_index.get("warnings") or []) if isinstance(icon_index.get("warnings"), list) else 0,
    }


def _json_for_html(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")


HTML_TEMPLATE = r"""<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>MCBE Icon-Vorschau</title>
  <style>
    :root{color-scheme:dark;--bg:#071112;--panel:#101821;--line:#263541;--text:#e8f0f2;--muted:#92a4ae;--ok:#19c986;--warn:#f59e0b;--bad:#fb7185}
    *{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 15% 0,rgba(16,185,129,.16),transparent 35%),var(--bg);color:var(--text);font:14px/1.4 system-ui,sans-serif}
    header{position:sticky;top:0;z-index:2;padding:18px 22px;background:rgba(7,17,18,.94);border-bottom:1px solid var(--line);backdrop-filter:blur(12px)}
    h1{margin:0 0 4px;font-size:20px}.summary{color:var(--muted)}.toolbar{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}.toolbar:first-of-type{margin-top:14px}.toolbar-label{align-self:center;color:var(--muted);font-size:12px}
    input,button{border:1px solid var(--line);border-radius:9px;background:var(--panel);color:var(--text);padding:8px 11px;font:inherit}input{min-width:260px;flex:1}button{cursor:pointer}button.active{border-color:var(--ok);color:var(--ok)}
    main{padding:18px 22px}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px}.card{min-width:0;border:1px solid var(--line);border-radius:12px;background:var(--panel);padding:10px}.card.hidden{display:none}.card[data-status="fallback"]{border-color:rgba(245,158,11,.65)}.card[data-status="error"]{border-color:var(--bad)}.card[data-scope="indexed"]{border-style:dashed}.card[data-scope="display"]{border-color:#38bdf8;border-style:dashed}
    .visual{height:78px;display:grid;place-items:center;border-radius:8px;background:#081116;font-size:34px}.visual img{width:56px;height:56px;object-fit:contain;image-rendering:pixelated}.id{margin-top:8px;font:600 11px/1.3 ui-monospace,monospace;overflow-wrap:anywhere}.name,.meta{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.name{margin-top:4px;color:var(--muted);font-size:12px}.meta{margin-top:7px;font-size:10px;color:var(--muted)}.badge{display:inline-block;margin-top:6px;border-radius:99px;padding:2px 6px;background:#1b2932;color:var(--muted);font-size:10px}.card[data-status="fallback"] .badge{color:var(--warn)}.card[data-status="error"] .badge{color:var(--bad)}
  </style>
  <script src="__ITEM_CATALOG_URI__"></script>
  <script src="__BOOTSTRAP_URI__"></script>
</head>
<body>
  <header>
    <h1>MCBE Icon-Vorschau</h1>
    <div class="summary" id="summary">Wird aufgebaut …</div>
    <div class="toolbar">
      <input id="search" type="search" placeholder="Item-ID oder Name filtern …" autofocus>
      <span class="toolbar-label">Bereich:</span>
      <button class="active" data-scope-filter="addable" data-label="Hinzufügbar">Hinzufügbar</button>
      <button data-scope-filter="compatibility" data-label="Kompatibilität/Altbestand">Kompatibilität/Altbestand</button>
      <button data-scope-filter="indexed" data-label="Nur im Index">Nur im Index</button>
      <button data-scope-filter="display" data-label="Darstellungsassets">Darstellungsassets</button>
    </div>
    <div class="toolbar">
      <span class="toolbar-label">Status:</span>
      <button class="active" data-status-filter="all" data-label="Alle">Alle</button>
      <button data-status-filter="mapped" data-label="Gemappt">Gemappt</button>
      <button data-status-filter="fallback" data-label="Fallback">Fallback</button>
      <button data-status-filter="error" data-label="Ladefehler">Ladefehler</button>
    </div>
  </header>
  <main><div class="grid" id="grid"></div></main>
  <script id="payload" type="application/json">__PAYLOAD__</script>
  <script>
  (() => {
    "use strict";
    const data = JSON.parse(document.getElementById("payload").textContent);
    const catalog = window.MCBEItemCatalog.createItemCatalog({
      getItemsDb: () => data.items,
      getCompatItemAliases: () => data.aliases,
      getItemIconIndex: () => data.icons,
      getStackLimits: () => ({}),
      getMaxDamageMap: () => ({__default__: 32767}),
      getEnchantmentCompatibility: () => ({}),
      itemIdRe: /^[a-z0-9_.-]+:[a-z0-9_.-]+$/,
      defaultMaxDamage: 32767,
      maxBedrockStackCount: 127,
    });
    let activeScope = "addable";
    let activeStatus = "all";
    const grid = document.getElementById("grid");
    const search = document.getElementById("search");
    const cards = [];

    function labelFor(id) {
      const names = data.items[id];
      return Array.isArray(names) ? names.filter(Boolean).join(" / ") : "";
    }
    function statusLabel(status) {
      return ({mapped: "Gemappt", fallback: "Fallback", error: "Ladefehler"})[status] || status;
    }
    function updateSummary() {
      const statuses = {mapped: 0, fallback: 0, error: 0};
      const scopedStatuses = {mapped: 0, fallback: 0, error: 0};
      const scopes = {addable: 0, compatibility: 0, indexed: 0, display: 0};
      cards.forEach(card => {
        statuses[card.dataset.status] = (statuses[card.dataset.status] || 0) + 1;
        scopes[card.dataset.scope] = (scopes[card.dataset.scope] || 0) + 1;
        if (card.dataset.scope === activeScope) {
          scopedStatuses[card.dataset.status] = (scopedStatuses[card.dataset.status] || 0) + 1;
        }
      });
      document.getElementById("summary").textContent = `${scopes.addable} neu hinzufügbar · ${scopes.compatibility} Kompatibilität/Altbestand · ${statuses.mapped} gemappt · ${statuses.fallback} Fallback · ${statuses.error} Ladefehler · ${scopes.indexed} nur im Index · ${scopes.display} Darstellungsassets · ${data.warning_count} Scan-Warnungen`;
      document.querySelectorAll("button[data-scope-filter]").forEach(button => {
        button.textContent = `${button.dataset.label} ${scopes[button.dataset.scopeFilter] || 0}`;
      });
      document.querySelectorAll("button[data-status-filter]").forEach(button => {
        const key = button.dataset.statusFilter;
        button.textContent = `${button.dataset.label} ${key === "all" ? (scopes[activeScope] || 0) : (scopedStatuses[key] || 0)}`;
      });
    }
    function applyFilters() {
      const needle = search.value.trim().toLowerCase();
      cards.forEach(card => {
        const matchesText = !needle || card.dataset.search.includes(needle);
        const matchesScope = card.dataset.scope === activeScope;
        const matchesStatus = activeStatus === "all" || card.dataset.status === activeStatus;
        card.classList.toggle("hidden", !(matchesText && matchesScope && matchesStatus));
      });
    }
    function makeCard(id, kind) {
      const isDisplay = kind === "display";
      const meta = isDisplay ? data.display_icons[id] : catalog.getItemIconMeta(id);
      const fallback = isDisplay ? "□" : (catalog.getItemEmoji(id) || "□");
      const previewError = meta?.preview_error || "";
      const card = document.createElement("article");
      card.className = "card";
      card.dataset.scope = kind;
      card.dataset.status = previewError ? "error" : (meta?.url ? "mapped" : "fallback");
      const label = isDisplay ? "Internes Darstellungsasset" : labelFor(id);
      card.dataset.search = `${id} ${label}`.toLowerCase();

      const visual = document.createElement("div");
      visual.className = "visual";
      if (meta?.url) {
        const image = document.createElement("img");
        image.src = meta.url;
        image.alt = "";
        image.setAttribute("data-icon-fallback", fallback);
        const tint = isDisplay ? "" : catalog.getItemIconTint({name: id});
        if (tint) image.setAttribute("data-icon-tint", tint);
        visual.appendChild(image);
      } else {
        const fallbackNode = document.createElement("span");
        fallbackNode.textContent = fallback;
        visual.appendChild(fallbackNode);
      }
      const idNode = document.createElement("div"); idNode.className = "id"; idNode.textContent = id;
      const nameNode = document.createElement("div"); nameNode.className = "name"; nameNode.textContent = label || "Zusätzlicher Indexeintrag"; nameNode.title = nameNode.textContent;
      const badge = document.createElement("span"); badge.className = "badge"; badge.textContent = statusLabel(card.dataset.status);
      const detail = document.createElement("div"); detail.className = "meta"; detail.textContent = previewError || meta?.texture || meta?.source || "Kein Icon-Mapping"; detail.title = detail.textContent;
      card.append(visual, idNode, nameNode, badge, detail);
      return card;
    }

    document.addEventListener("error", event => {
      const image = event.target;
      if (!(image instanceof HTMLImageElement) || !image.closest(".card")) return;
      const card = image.closest(".card");
      card.dataset.status = "error";
      card.querySelector(".badge").textContent = statusLabel("error");
      card.querySelector(".meta").textContent = "Bilddatei konnte nicht geladen werden";
      updateSummary(); applyFilters();
    }, true);
    window.MCBEAppBootstrap.installIconErrorFallback(document);
    window.MCBEAppBootstrap.installIconTintHandler(document);

    data.item_ids.forEach(id => cards.push(makeCard(id, "addable")));
    data.compatibility_ids.forEach(id => cards.push(makeCard(id, "compatibility")));
    data.extra_ids.forEach(id => cards.push(makeCard(id, "indexed")));
    data.display_ids.forEach(id => cards.push(makeCard(id, "display")));
    grid.append(...cards);
    document.querySelectorAll("button[data-scope-filter]").forEach(button => button.addEventListener("click", () => {
      activeScope = button.dataset.scopeFilter;
      document.querySelectorAll("button[data-scope-filter]").forEach(item => item.classList.toggle("active", item === button));
      updateSummary();
      applyFilters();
    }));
    document.querySelectorAll("button[data-status-filter]").forEach(button => button.addEventListener("click", () => {
      activeStatus = button.dataset.statusFilter;
      document.querySelectorAll("button[data-status-filter]").forEach(item => item.classList.toggle("active", item === button));
      applyFilters();
    }));
    search.addEventListener("input", applyFilters);
    updateSummary();
    applyFilters();
  })();
  </script>
</body>
</html>
"""


def _browser_reference(target: Path, output_path: Path) -> str:
    try:
        relative = os.path.relpath(target, start=output_path.parent).replace("\\", "/")
    except ValueError:
        return target.resolve().as_uri()
    return urllib.parse.quote(relative, safe="/:")


def render_preview(payload: dict[str, Any], output_path: Path = DEFAULT_OUTPUT) -> str:
    return (
        HTML_TEMPLATE.replace("__PAYLOAD__", _json_for_html(payload))
        .replace("__ITEM_CATALOG_URI__", _browser_reference(ROOT / "static" / "item_catalog.js", output_path))
        .replace("__BOOTSTRAP_URI__", _browser_reference(ROOT / "static" / "app_bootstrap.js", output_path))
    )


def generate_preview(
    item_db_path: Path,
    icon_index_path: Path,
    output_path: Path,
    *,
    embed_files: bool = False,
) -> dict[str, Any]:
    payload = build_preview_payload(
        _read_object(item_db_path, label="Item-Datenbank"),
        _read_object(icon_index_path, label="Icon-Index"),
        output_path,
        embed_files=embed_files,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_preview(payload, output_path), encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Erzeugt eine lokale HTML-Gesamtvorschau der Item-Icons.")
    parser.add_argument("--item-db", type=Path, default=DEFAULT_ITEM_DB)
    parser.add_argument("--icon-index", type=Path, default=DEFAULT_ICON_INDEX)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--embed-files", action="store_true", help="Icon-Dateien direkt in die HTML-Datei einbetten.")
    args = parser.parse_args(argv)
    try:
        payload = generate_preview(args.item_db, args.icon_index, args.output, embed_files=args.embed_files)
    except RuntimeError as exc:
        parser.error(str(exc))
    print(
        f"Icon-Vorschau: {args.output.resolve()} "
        f"({len(payload['item_ids'])} hinzufügbar, "
        f"{len(payload['compatibility_ids'])} Kompatibilität/Altbestand, "
        f"{payload['index_count']} Indexeinträge)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
