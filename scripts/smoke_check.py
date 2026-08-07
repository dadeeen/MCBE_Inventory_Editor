#!/usr/bin/env python3
"""Cheap release smoke checks that avoid mutating Minecraft worlds."""

from __future__ import annotations

import compileall
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    ok = compileall.compile_file(str(ROOT / "main.py"), quiet=1, force=True)
    for rel in ("mcbe_editor", "scripts", "tests"):
        ok = compileall.compile_dir(str(ROOT / rel), quiet=1, force=True) and ok
    if not ok:
        print("Python compile smoke check FAILED.", file=sys.stderr)
        return 1

    from mcbe_editor.config import load_config

    config = load_config()
    print(
        "Config smoke check OK: "
        f"mode={config.mode} host={config.host} port={config.port} "
        f"auth_required={config.auth_required} log_level={config.log_level} "
        f"audit_log_enabled={config.audit_log_enabled} "
        f"trust_proxy_headers={config.trust_proxy_headers} "
        f"setup_path={config.setup_path or 'none'}"
    )
    assert hasattr(config, "fail_on_insecure_config")
    assert hasattr(config, "audit_log_enabled")
    assert hasattr(config, "audit_log_path")
    assert hasattr(config, "audit_log_max_bytes")
    assert hasattr(config, "trust_proxy_headers")
    assert hasattr(config, "presence_conflict_guard_enabled")
    assert hasattr(config, "setup_path")
    assert config.item_db_path is None or str(config.item_db_path).endswith("item_db.json")

    from mcbe_editor.item_data import load_item_database

    db = load_item_database()
    assert "minecraft:air" in db["ITEMS"]
    print(f"Item-DB smoke check OK: items={len(db['ITEMS'])} source={db['SOURCE_PATH']}")

    from mcbe_editor.distribution import data_root_snapshot, distribution_snapshot

    dist = distribution_snapshot()
    data_status = data_root_snapshot(config.data_root)
    assert dist["kind"] in {"source", "release", "release-dirty"}
    assert data_status["configured"] is True
    assert data_status["writable"] is True
    print(f"Distribution smoke check OK: kind={dist['kind']} portable_data={data_status['portable']} data_root={data_status['path']}")

    # In CI with runtime dependencies installed, also prove the Flask app imports.
    if os.environ.get("MCBE_SMOKE_IMPORT_APP", "").strip().lower() in {"1", "true", "yes", "on"}:
        import main  # noqa: F401, PLC0415

        print("App import smoke check OK.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
