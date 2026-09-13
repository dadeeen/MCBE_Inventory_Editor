"""Run real mount/transfer/export/import services with either NBT backend.

Only standard-library imports may precede install_backend. The comparison uses
today's services with the pre-migration NBT binding, not a historical checkout.
All paths belong to disposable test copies; guards for an active web app are
disabled, but validation, backups, native writes and rereads remain real.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from tests.nbt_backend_worker import install_backend, view


def run(backend: str, world: Path, request: dict, output: Path) -> dict:
    install_backend(backend)
    import mcbe_editor.db as db_module
    from mcbe_editor.backup import get_backups_dir
    from mcbe_editor.item_data import ENCHANTMENTS, ITEMS
    from mcbe_editor.mount_write import create_horse_mount_with_service
    from mcbe_editor.services import BedrockEditorService

    db_module._runtime_app_modules = lambda: ()
    db_module._registered_write_guard = None
    service = BedrockEditorService(ITEMS, ENCHANTMENTS)
    world_path = str(world.resolve())
    operation = request["operation"]

    def saved_result(result):
        assert result.get("success") is True, "Service operation failed"
        assert result.get("write_committed") is True, "Service did not commit"
        assert not result.get("cleanup_warning"), "Service cleanup failed"
        backup = result["backup_file"]
        assert backup and (Path(get_backups_dir(world_path)) / backup).is_file(), "Backup missing"
        return {**result, "backup_file": "<backup>"}

    report = {"nbt_module": sys.modules["mcbe_editor.nbt"].__name__}
    if operation == "mounts":
        report["results"] = []
        for case in request["cases"]:
            result = create_horse_mount_with_service(
                service, world_path, request["player_key"],
                {"mount_type": case["mount_type"], "selected_position": case["position"]},
                create_mode=case["create_mode"], horse_profile=case.get("horse_profile"),
                mount_stats=case.get("mount_stats"), tamed=case.get("tamed", False),
            )
            assert result.get("post_create_validation", {}).get("ok") is True, "Mount validation failed"
            report["results"].append(saved_result(result))
    elif operation == "transfer":
        source, target = request["source"], request["target"]
        report["before"] = view(service.load_player(world_path, target))
        preview = service.preview_player_state_transfer(world_path, source, target)
        assert preview.get("success") is True and preview.get("transfer_token"), "Transfer preview failed"
        result = service.transfer_player_state(
            world_path, source, target, confirm_transfer=True, transfer_token=preview["transfer_token"],
        )
        assert result.get("validation", {}).get("valid") is True, "Transfer validation failed"
        report["result"] = saved_result(result)
        report["preview"] = {key: value for key, value in preview.items() if key != "transfer_token"}
        report["after"] = view(service.load_player(world_path, target))
    elif operation == "export":
        result = service.export_player(world_path, request["player_key"])
        assert result.get("success") is True, "Export failed"
        shutil.copyfile(result["export_path"], output.with_suffix(".zip"))
        report["result"] = {**result, "export_path": "<export>"}
        report["view"] = view(service.load_player(world_path, request["player_key"]))
    elif operation == "import":
        archive = request["archive"]
        target = request["target"]
        new_player = request.get("new_player", False)
        before = None if new_player else service.load_player(world_path, target)
        report["before"] = None if before is None else view(before)
        preview = service.preview_player_export(archive, world_path)
        assert preview.get("success") is True and preview.get("importable") is True, "Import preview rejected"
        assert preview.get("import_token"), "Import token missing"
        result = service.import_player(
            archive, world_path, None if new_player else target, confirm_overwrite=True,
            import_as_exported_player=new_player, import_token=preview["import_token"],
            base_revision=None if before is None else before["player_revision"],
        )
        assert result.get("post_write_validated") is True, "Import validation failed"
        report["result"] = saved_result(result)
        # These three fields are archive/time/path-specific, not NBT results.
        report["preview"] = {key: value for key, value in preview.items() if key not in {"import_token", "created_at", "export_path"}}
        report["after"] = view(service.load_player(world_path, target))
    else:
        raise ValueError(f"Unknown workflow: {operation}")

    serialized = json.dumps(report, sort_keys=True)
    for variant in (world_path, world_path.replace("\\", "/")):
        serialized = serialized.replace(json.dumps(variant)[1:-1], "<world>")
    return json.loads(serialized)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("project", "amulet"), required=True)
    parser.add_argument("--world", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.backend, args.world, json.loads(args.request.read_text(encoding="utf-8")), args.output)
    args.output.write_text(json.dumps(report, sort_keys=True, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
