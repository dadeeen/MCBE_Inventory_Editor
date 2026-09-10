"""Compare two locally generated icon caches, including actual PNG contents.

The self-contained HTML embeds locally installed Minecraft textures. Keep its
output under ignored data/; do not publish it or bundle it in releases.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import re
from collections import Counter
from pathlib import Path


def _png(root: Path, item_id: str) -> bytes:
    if not re.fullmatch(r"minecraft:[a-z0-9_]+(?:#\d+)?", item_id):
        raise ValueError(f"Invalid Vanilla item ID: {item_id}")
    path = root / "textures" / "items" / (item_id.removeprefix("minecraft:") + ".png")
    return path.read_bytes() if path.is_file() else b""


def compare_caches(before: Path, after: Path, output: Path) -> dict:
    manifests = [json.loads((root / "manifest.json").read_text(encoding="utf-8")) for root in (before, after)]
    old, new = manifests
    if old.get("release") != new.get("release"):
        raise ValueError("Compare caches built from the same release and catalog metadata.")
    images = []
    for root, manifest in zip((before, after), manifests, strict=True):
        mapped = {item: _png(root, item) for item in manifest["items"]}
        missing = sorted(item for item, raw in mapped.items() if not raw)
        if missing:
            raise ValueError(f"Cache {root} lists missing or empty PNGs: {', '.join(missing)}")
        images.append(mapped)
    rows, cards = [], []
    unchanged = 0
    for item in sorted(set(old["items"]) | set(new["items"])):
        previous, current = images[0].get(item, b""), images[1].get(item, b"")
        source_changed = old["items"].get(item) != new["items"].get(item)
        if previous == current and not source_changed:
            unchanged += 1
            continue
        row = {
            "id": item, "before": old["items"].get(item), "after": new["items"].get(item),
            "image_changed": previous != current,
            "before_sha256": hashlib.sha256(previous).hexdigest() if previous else None,
            "after_sha256": hashlib.sha256(current).hexdigest() if current else None,
            "resolution": new.get("resolutions", {}).get(item),
        }
        rows.append(row)
        previews = []
        for label, raw, source in (("Before", previous, row["before"]), ("After", current, row["after"])):
            preview = '<span class="missing">Missing</span>'
            if raw:
                preview = '<img alt="' + label + '" src="data:image/png;base64,' + base64.b64encode(raw).decode("ascii") + '">'
            previews.append(f'<div><b>{label}</b>{preview}<small>{html.escape(source or "missing")}</small></div>')
        details = html.escape(json.dumps(row["resolution"], ensure_ascii=False))
        cards.append(f'<article><h2>{html.escape(item)}</h2><section>{"".join(previews)}</section><details><summary>Resolution</summary><pre>{details}</pre></details></article>')
    report = {
        "release": new.get("release"), "unchanged": unchanged, "changed": len(rows),
        "new_missing": sorted(set(old["items"]) - set(new["items"])),
        "newly_mapped": sorted(set(new["items"]) - set(old["items"])),
        "before_missing": old["missing_items"], "after_missing": new["missing_items"],
        "resolution_counts": dict(Counter(value["basis"] for value in new.get("resolutions", {}).values())),
        "review_required": {
            key: value for key, value in new.get("resolutions", {}).items()
            if value.get("basis") == "legacy_heuristic" or value.get("issue")
        },
        "changes": rows,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "comparison.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    page = """<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Inventory icon comparison</title><style>
body{background:#182530;color:#edf2f5;font:16px system-ui;margin:32px}h1{margin-bottom:8px}
input{padding:12px;width:min(600px,85%);margin:16px 0}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px}
article{background:#233746;padding:18px;border-radius:10px}h2{font:14px monospace;overflow-wrap:anywhere}
section{display:flex;gap:12px}section>div{width:50%;display:flex;align-items:center;flex-direction:column;gap:10px}
img,.missing{width:96px;height:96px;object-fit:contain;image-rendering:pixelated;background:#15222c;padding:12px;border-radius:6px}
small{font:12px monospace;overflow-wrap:anywhere;width:100%}details{font-size:12px;margin-top:15px}pre{white-space:pre-wrap;overflow-wrap:anywhere}
</style><h1>Inventory icon comparison</h1>"""
    page += f'<p>{len(rows)} changed entries · {unchanged} unchanged · {len(report["new_missing"])} newly missing</p>'
    page += '<p>Matching release metadata; input identity depends on the recorded archive and catalog hashes. '
    page += 'Local review only; previews are not a guarantee of in-game equivalence.</p>'
    page += '<details><summary>Resolution strategies and remaining approximations</summary><pre>'
    page += html.escape(json.dumps(report["resolution_counts"], indent=2)) + '</pre><p>'
    page += str(len(report["review_required"])) + ' entries still use compatibility heuristics or have an unresolved condition.</p><pre>'
    page += html.escape("\n".join(report["review_required"])) + '</pre></details>'
    page += ('<input aria-label="Filter item IDs" placeholder="Filter item IDs…" '
             'oninput="for(const a of document.querySelectorAll(\'article\'))'
             'a.hidden=!a.querySelector(\'h2\').textContent.includes(this.value.toLowerCase())">')
    page += '<main>' + "".join(cards) + '</main></html>'
    (output / "comparison.html").write_text(page, encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = compare_caches(args.before, args.after, args.output)
    print(json.dumps({key: value for key, value in result.items() if key not in {"changes", "review_required"}}, indent=2))


if __name__ == "__main__":
    main()
