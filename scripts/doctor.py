#!/usr/bin/env python3
"""Print a compact local/runtime diagnostic without importing Flask or Amulet.

This helps distinguish a developer/source tree from an unpacked release and
shows where portable state is stored.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    from mcbe_editor.config import load_config
    from mcbe_editor.deployment import worlds_root_status, write_gate_setup_status
    from mcbe_editor.distribution import data_root_snapshot, distribution_snapshot
    from mcbe_editor.item_data import load_item_database

    config = load_config()
    db = load_item_database()
    report = {
        "distribution": distribution_snapshot(),
        "mode": config.mode,
        "bind": {"host": config.host, "port": config.port},
        "paths": {
            "data_root": data_root_snapshot(config.data_root),
            "worlds_root": worlds_root_status(config),
            "settings_path": config.settings_path,
            "backup_root": config.backup_root,
            "item_db_path": config.item_db_path,
        },
        "write_gate": write_gate_setup_status(config),
        "item_db": {
            "source": db["SOURCE_PATH"],
            "schema_version": db["SCHEMA_VERSION"],
            "items": len(db["ITEMS"]),
            "effects": len(db["EFFECTS"]),
            "enchantments": len(db["ENCHANTMENTS"]),
        },
        "security": {
            "auth_required_config": config.auth_required,
            "audit_log_enabled": config.audit_log_enabled,
            "trust_proxy_headers": config.trust_proxy_headers,
            "startup_network_check": config.startup_network_check,
        },
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
