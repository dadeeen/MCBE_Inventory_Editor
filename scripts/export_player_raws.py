#!/usr/bin/env python3
"""Export raw Minecraft Bedrock player NBT records for diagnostics.

The script deliberately reuses the same conservative readonly scanner and
.mcbe-player.zip export format as the web app. It does not copy the whole world
or anonymize player data; generated files must be treated as private.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcbe_editor.leveldb_readonly import ReadonlyLevelDbAdapter  # noqa: E402
from mcbe_editor.players import PlayerScanner, create_player_export, decode_player_key, player_export_dir_for_world  # noqa: E402
from mcbe_editor.world import ensure_valid_world_path, get_world_name  # noqa: E402

EXPORT_INDEX_FORMAT = "mcbe-player-raw-export-index"
BUNDLE_EXTENSION = ".mcbe-player-bundle.zip"


class PlayerRawExportError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


def _safe_filename(value: str, *, fallback: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in value).strip("_")
    return safe[:64] or fallback


def _json_dump(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


@contextlib.contextmanager
def _open_readonly_db(world_path: str):
    db_path = ensure_valid_world_path(world_path)
    db = ReadonlyLevelDbAdapter(db_path)
    try:
        yield db
    finally:
        db.close()


def _list_players(world_path: str) -> list[dict[str, Any]]:
    with _open_readonly_db(world_path) as db:
        return PlayerScanner(db).list_players()


def _player_summary(player: dict[str, Any]) -> dict[str, Any]:
    debug = player.get("debug") if isinstance(player.get("debug"), dict) else {}
    return {
        "player_key": player.get("player_key"),
        "label": player.get("label"),
        "kind": player.get("kind"),
        "confidence": player.get("confidence"),
        "editable": bool(player.get("editable")),
        "exportable": bool(player.get("exportable")),
        "reason_code": player.get("reason_code"),
        "reason": player.get("reason"),
        "raw_length": debug.get("raw_length"),
        "has_inventory": bool(player.get("has_inventory")),
        "has_ender_chest": bool(player.get("has_ender_chest")),
    }


def _world_summary(world_path: str, *, include_private_paths: bool) -> dict[str, Any]:
    summary = {
        "name": get_world_name(world_path),
        "folder_name": os.path.basename(os.path.normpath(world_path)),
    }
    if include_private_paths:
        summary["path"] = os.path.abspath(os.path.normpath(world_path))
    return summary


def _print_player_table(world_path: str, players: list[dict[str, Any]]) -> None:
    print(f"Welt: {get_world_name(world_path)}")
    print(f"Erkannte Player-Datensätze: {len(players)}")
    if not players:
        return
    print()
    for index, player in enumerate(players, start=1):
        summary = _player_summary(player)
        exportable = "ja" if summary["exportable"] else "nein"
        editable = "ja" if summary["editable"] else "nein"
        raw_length = summary["raw_length"] if summary["raw_length"] is not None else "unbekannt"
        print(f"{index}. {summary['label']} ({summary['kind']}, confidence={summary['confidence']})")
        print(f"   player_key: {summary['player_key']}")
        print(f"   exportierbar: {exportable}; bearbeitbar: {editable}; raw_bytes: {raw_length}")
        print(f"   status: {summary['reason_code']} - {summary['reason']}")


def _selected_player_keys(players: list[dict[str, Any]], *, export_all: bool, player_keys: list[str] | None, editable_only: bool) -> list[str]:
    by_key = {str(player.get("player_key")): player for player in players if player.get("player_key")}
    if export_all:
        selected = [str(player["player_key"]) for player in players if player.get("exportable")]
    else:
        selected = []
        for key in player_keys or []:
            if key not in by_key:
                raise PlayerRawExportError(f"Unbekannter player_key: {key}. Nutze zuerst den list-Befehl für diese Welt.")
            selected.append(key)

    deduped: list[str] = []
    seen = set()
    for key in selected:
        if key in seen:
            continue
        seen.add(key)
        player = by_key[key]
        if not player.get("exportable"):
            raise PlayerRawExportError(f"Player ist nicht exportierbar: {player.get('label') or key} ({player.get('reason')})")
        if editable_only and not player.get("editable"):
            continue
        deduped.append(key)
    if not deduped:
        raise PlayerRawExportError("Keine passenden exportierbaren Player-Datensätze gefunden.")
    return deduped


def _default_bundle_path(world_path: str, output_dir: Path) -> Path:
    timestamp = _now().strftime("%Y-%m-%d_%H-%M-%S")
    world_slug = _safe_filename(get_world_name(world_path), fallback="world")
    return output_dir / f"{world_slug}_player_raws_{timestamp}{BUNDLE_EXTENSION}"


def _resolve_bundle_path(raw_value: str | None, world_path: str, output_dir: Path) -> Path | None:
    if raw_value is None:
        return None
    if raw_value == "auto":
        return _default_bundle_path(world_path, output_dir)
    path = Path(raw_value).expanduser()
    if path.suffix.lower() != ".zip":
        path = path.with_suffix(path.suffix + ".zip") if path.suffix else Path(str(path) + BUNDLE_EXTENSION)
    return path


def _write_bundle(bundle_path: Path, index: dict[str, Any], export_paths: list[Path]) -> Path:
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr("index.json", _json_dump(index))
        for export_path in export_paths:
            archive.write(export_path, f"players/{export_path.name}")
    return bundle_path


def export_players(
    world_path: str,
    *,
    export_all: bool,
    player_keys: list[str] | None,
    output_dir: str | None,
    bundle_zip: str | None,
    editable_only: bool,
    include_private_paths: bool,
) -> dict[str, Any]:
    world_path = os.path.abspath(os.path.normpath(os.path.expanduser(world_path)))
    output_path = Path(output_dir).expanduser() if output_dir else Path(player_export_dir_for_world(world_path))
    output_path.mkdir(parents=True, exist_ok=True)

    players = _list_players(world_path)
    selected_keys = _selected_player_keys(players, export_all=export_all, player_keys=player_keys, editable_only=editable_only)
    players_by_key = {str(player["player_key"]): player for player in players if player.get("player_key")}

    exports: list[dict[str, Any]] = []
    export_paths: list[Path] = []
    with _open_readonly_db(world_path) as db:
        for key in selected_keys:
            raw_key = decode_player_key(key)
            raw_bytes = db.get(raw_key)
            player = players_by_key[key]
            export_path = Path(create_player_export(world_path, player, raw_bytes, output_dir=str(output_path)))
            export_paths.append(export_path)
            exports.append(
                {
                    "player": _player_summary(player),
                    "export_file": str(export_path if include_private_paths else export_path.name),
                    "raw_length": len(raw_bytes),
                    "raw_sha256": hashlib.sha256(raw_bytes).hexdigest(),
                }
            )

    index = {
        "format": EXPORT_INDEX_FORMAT,
        "version": 1,
        "created_at": _now().replace(microsecond=0).isoformat(),
        "world": _world_summary(world_path, include_private_paths=include_private_paths),
        "selection": {
            "all": export_all,
            "editable_only": editable_only,
            "player_keys": player_keys or [],
        },
        "export_count": len(exports),
        "exports": exports,
        "privacy": {
            "contains_raw_player_nbt": True,
            "contains_full_world_leveldb": False,
            "safe_to_publish": False,
            "note": "Player-NBT kann persönliche oder serverbezogene Daten enthalten. Nur gezielt und privat teilen.",
        },
    }

    index_path = output_path / "player_raw_export_index.json"
    index_path.write_text(_json_dump(index), encoding="utf-8")

    resolved_bundle_path = _resolve_bundle_path(bundle_zip, world_path, output_path)
    bundle_result = None
    if resolved_bundle_path:
        bundle_result_path = _write_bundle(resolved_bundle_path, index, export_paths)
        bundle_result = str(bundle_result_path if include_private_paths else bundle_result_path.name)

    return {
        "success": True,
        "output_dir": str(output_path if include_private_paths else output_path.name),
        "index_file": str(index_path if include_private_paths else index_path.name),
        "bundle_zip": bundle_result,
        **index,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="List or export raw Minecraft Bedrock player records from a world folder.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    list_p = sub.add_parser("list", help="List detected player records without writing exports.")
    list_p.add_argument("--world", required=True, help="Direct Bedrock world folder containing the db/ directory.")
    list_p.add_argument("--json", action="store_true", help="Print machine-readable JSON instead of a small text table.")
    list_p.add_argument("--include-private-paths", action="store_true", help="Include absolute local paths in JSON output.")

    export_p = sub.add_parser("export", help="Export selected player raw NBT records as .mcbe-player.zip files.")
    export_p.add_argument("--world", required=True, help="Direct Bedrock world folder containing the db/ directory.")
    selector = export_p.add_mutually_exclusive_group(required=True)
    selector.add_argument("--all", action="store_true", help="Export all detected exportable player records.")
    selector.add_argument("--player-key", action="append", help="Export one detected player_key. Repeat for several players.")
    export_p.add_argument("--editable-only", action="store_true", help="With --all, skip read-only but exportable player records.")
    export_p.add_argument("--output-dir", help="Directory for individual .mcbe-player.zip exports. Default: player_exports next to the world.")
    export_p.add_argument(
        "--bundle-zip",
        nargs="?",
        const="auto",
        default=None,
        help="Also create one bundle ZIP containing index.json and the individual player exports. Optionally pass an output path.",
    )
    export_p.add_argument("--include-private-paths", action="store_true", help="Include absolute local paths in JSON output and index files.")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.cmd == "list":
            world_path = os.path.abspath(os.path.normpath(os.path.expanduser(args.world)))
            players = _list_players(world_path)
            if args.json:
                print(
                    _json_dump(
                        {
                            "success": True,
                            "world": _world_summary(world_path, include_private_paths=args.include_private_paths),
                            "player_count": len(players),
                            "players": [_player_summary(player) for player in players],
                        }
                    ),
                    end="",
                )
            else:
                _print_player_table(world_path, players)
            return 0

        if args.cmd == "export":
            result = export_players(
                args.world,
                export_all=args.all,
                player_keys=args.player_key,
                output_dir=args.output_dir,
                bundle_zip=args.bundle_zip,
                editable_only=args.editable_only,
                include_private_paths=args.include_private_paths,
            )
            print(_json_dump(result), end="")
            return 0
    except (OSError, KeyError, PlayerRawExportError, ValueError) as exc:
        print(f"export_player_raws: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
