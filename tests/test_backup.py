import io
import os
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest

from mcbe_editor.backup import (
    get_backups_dir,
    list_backups,
    resolve_backup_path,
    validate_zip_members,
)


def _try_symlink(testcase: unittest.TestCase, target: Path, link: Path, *, target_is_directory: bool = False) -> None:
    try:
        os.symlink(target, link, target_is_directory=target_is_directory)
    except OSError as exc:
        testcase.skipTest(f"Symlink-Erstellung nicht erlaubt: {exc}")


class TestBackupPaths(unittest.TestCase):
    def test_get_backups_dir_constructs_portable_data_path(self):
        with TemporaryDirectory() as tmp:
            world = Path(tmp) / "MyWorld"
            world.mkdir()
            backups = get_backups_dir(str(world))
            self.assertIn(os.path.normpath("data/backups"), os.path.normpath(backups))
            self.assertIn("MyWorld_", os.path.basename(backups))

    def test_get_backups_dir_normalizes_path(self):
        backups = get_backups_dir("/some/../path/./world")
        self.assertIn(os.path.normpath("data/backups"), os.path.normpath(backups))
        self.assertTrue(os.path.basename(backups).startswith("world_"))

    def test_rejects_backup_root_inside_world(self):
        from unittest.mock import patch
        from mcbe_editor.backup import create_backup

        with TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            (world / "db" / "file.dat").write_text("data")
            with (
                patch.dict(os.environ, {"MCBE_BACKUP_ROOT": str(world / "backups")}, clear=False),
                self.assertRaisesRegex(ValueError, "innerhalb des Weltordners"),
            ):
                create_backup(str(world))

    @unittest.skipUnless(hasattr(os, "symlink"), "Symlinks werden auf dieser Plattform nicht unterstützt")
    def test_rejects_backup_root_symlinked_into_world(self):
        from unittest.mock import patch
        from mcbe_editor.backup import create_backup

        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            world = base / "world"
            (world / "db").mkdir(parents=True)
            (world / "db" / "file.dat").write_text("data")
            inside_target = world / "actual_backups"
            inside_target.mkdir()
            apparent_external_root = base / "external_backups"
            _try_symlink(self, inside_target, apparent_external_root, target_is_directory=True)

            with (
                patch.dict(os.environ, {"MCBE_BACKUP_ROOT": str(apparent_external_root)}, clear=False),
                self.assertRaisesRegex(ValueError, "innerhalb des Weltordners"),
            ):
                create_backup(str(world))


class TestResolveBackupPath(unittest.TestCase):
    def test_accepts_valid_filename(self):
        with TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            world.mkdir()
            result = resolve_backup_path(str(world), "backup.zip")
            self.assertEqual(os.path.basename(result), "backup.zip")
            self.assertIn(os.path.normpath("data/backups"), os.path.normpath(result))

    def test_rejects_non_zip(self):
        with TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            world.mkdir()
            with self.assertRaisesRegex(ValueError, "ZIP"):
                resolve_backup_path(str(world), "backup.txt")

    def test_rejects_path_traversal(self):
        with TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            world.mkdir()
            with self.assertRaisesRegex(ValueError, "Backup-Dateiname"):
                resolve_backup_path(str(world), "../../etc/passwd")

    @unittest.skipUnless(hasattr(os, "symlink"), "Symlinks werden auf dieser Plattform nicht unterstützt")
    def test_rejects_symlink_backup_file(self):
        with TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            world.mkdir()
            backups_dir = Path(get_backups_dir(str(world)))
            backups_dir.mkdir(parents=True)
            outside = Path(tmp) / "outside.zip"
            outside.write_text("not really a backup")
            _try_symlink(self, outside, backups_dir / "linked.zip")

            with self.assertRaisesRegex(ValueError, "Symlink"):
                resolve_backup_path(str(world), "linked.zip")


class TestListBackups(unittest.TestCase):
    def test_returns_sorted_backups(self):
        with TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            backups_dir = Path(get_backups_dir(str(world)))
            backups_dir.mkdir(parents=True)
            for path in (backups_dir / "b.zip", backups_dir / "a.zip"):
                with zipfile.ZipFile(path, "w") as archive:
                    archive.writestr("db/CURRENT", path.stem)
            (backups_dir / "c.txt").write_text("not a zip")
            os.utime(backups_dir / "a.zip", (100, 100))
            os.utime(backups_dir / "b.zip", (200, 200))
            result = list_backups(str(world))
            filenames = [b["filename"] for b in result]
            self.assertEqual(filenames, ["b.zip", "a.zip"])

    def test_returns_empty_for_no_backups_dir(self):
        with TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            world.mkdir()
            result = list_backups(str(world))
            self.assertEqual(result, [])

    @unittest.skipUnless(hasattr(os, "symlink"), "Symlinks werden auf dieser Plattform nicht unterstützt")
    def test_skips_symlink_zip_entries(self):
        with TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            backups_dir = Path(get_backups_dir(str(world)))
            backups_dir.mkdir(parents=True)
            with zipfile.ZipFile(backups_dir / "real.zip", "w") as archive:
                archive.writestr("db/CURRENT", "real")
            outside = Path(tmp) / "outside.zip"
            outside.write_text("external")
            _try_symlink(self, outside, backups_dir / "linked.zip")

            filenames = [b["filename"] for b in list_backups(str(world))]
            self.assertEqual(filenames, ["real.zip"])


class TestCreateBackupConsistency(unittest.TestCase):
    def test_create_backup_fails_instead_of_silently_skipping_disappearing_file(self):
        from unittest.mock import patch
        from mcbe_editor.backup import create_backup, get_backups_dir

        with TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            (world / "db" / "file.dat").write_text("data")

            with patch("zipfile.ZipFile.write", side_effect=FileNotFoundError("vanished")), self.assertRaisesRegex(ValueError, "Backup abgebrochen"):
                create_backup(str(world))

            backups_dir = Path(get_backups_dir(str(world)))
            self.assertEqual(list(backups_dir.glob("*.zip")), [])

    def test_create_backup_preserves_empty_directories(self):
        from mcbe_editor.backup import create_backup, restore_backup

        with TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            (world / "db" / "file.dat").write_text("data")
            (world / "resource_packs" / "empty_pack_folder").mkdir(parents=True)

            backup_path = create_backup(str(world))
            with zipfile.ZipFile(backup_path, "r") as zipf:
                names = set(zipf.namelist())
            self.assertIn("resource_packs/", names)
            self.assertIn("resource_packs/empty_pack_folder/", names)

            shutil_target = world / "resource_packs" / "empty_pack_folder"
            shutil_target.rmdir()
            restore_backup(str(world), os.path.basename(backup_path))
            self.assertTrue(shutil_target.is_dir())


class TestValidateZipMembers(unittest.TestCase):
    def test_accepts_valid_members(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as zipf:
            zipf.writestr("db/file1.dat", b"data")
            zipf.writestr("db/file2.dat", b"data2")
        data.seek(0)
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "restore"
            with zipfile.ZipFile(data, "r") as zipf:
                validate_zip_members(zipf, str(target))

    def test_rejects_traversal_on_odd_platform_separators(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as zipf:
            zipf.writestr("..\\outside.txt", "bad")
        data.seek(0)
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "restore"
            with zipfile.ZipFile(data, "r") as zipf, self.assertRaisesRegex(ValueError, "Unsicherer Pfad"):
                validate_zip_members(zipf, str(target))


class TestRestoreBackup(unittest.TestCase):
    def test_restore_journal_publication_failure_removes_partial_marker(self):
        from mcbe_editor.backup import _write_restore_transaction

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            transaction_id = "aaaaaaaaaaaaaaaa"
            rollback = root / f".world_rollback_2026-01-01_00-00-00-00000000_{transaction_id}"
            staging = root / ".world_restoring_interrupted"

            def fail_after_partial_publication(path, _text):
                Path(path).write_text("{", encoding="utf-8")
                raise OSError("simulated journal write failure")

            with (
                patch("mcbe_editor.backup.atomic_write_private_text", side_effect=fail_after_partial_publication),
                self.assertRaisesRegex(OSError, "simulated journal write failure"),
            ):
                _write_restore_transaction(
                    str(root),
                    "world",
                    str(rollback),
                    str(staging),
                    transaction_id,
                )

            self.assertEqual(list(root.glob(".mcbe_restore_*.json")), [])

    def test_startup_recovery_restores_original_after_interrupted_swap(self):
        from mcbe_editor.backup import create_backup, recover_interrupted_restores, restore_backup

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            world_dir = root / "world"
            (world_dir / "db").mkdir(parents=True)
            (world_dir / "db" / "state.dat").write_text("backup", encoding="utf-8")
            backup_path = create_backup(str(world_dir))
            (world_dir / "db" / "state.dat").write_text("current", encoding="utf-8")

            real_replace = os.replace

            def interrupt_before_commit(src, dst):
                if Path(src).name.startswith(".world_restoring_"):
                    raise SystemExit("simulated container stop")
                return real_replace(src, dst)

            with patch("mcbe_editor.backup.os.replace", side_effect=interrupt_before_commit), self.assertRaises(SystemExit):
                restore_backup(str(world_dir), os.path.basename(backup_path))

            self.assertFalse(world_dir.exists())
            self.assertEqual(len(list(root.glob(".mcbe_restore_*.json"))), 1)
            self.assertEqual(len(list(root.glob(".world_rollback_*"))), 1)
            self.assertEqual(len(list(root.glob(".world_restoring_*"))), 1)

            recovered = recover_interrupted_restores([str(world_dir)])

            self.assertEqual(recovered[0]["status"], "original-restored")
            self.assertEqual((world_dir / "db" / "state.dat").read_text(encoding="utf-8"), "current")
            self.assertEqual(list(root.glob(".mcbe_restore_*.json")), [])
            self.assertEqual(list(root.glob(".world_rollback_*")), [])
            self.assertEqual(list(root.glob(".world_restoring_*")), [])

    def test_restore_keeps_recovery_state_when_parent_fsync_fails_after_first_rename(self):
        from mcbe_editor.backup import create_backup, recover_interrupted_restores, restore_backup

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            world_dir = root / "world"
            (world_dir / "db").mkdir(parents=True)
            (world_dir / "db" / "state.dat").write_text("backup", encoding="utf-8")
            backup_path = create_backup(str(world_dir))
            (world_dir / "db" / "state.dat").write_text("current", encoding="utf-8")
            fsync_calls = 0

            def fail_after_first_world_rename(_path):
                nonlocal fsync_calls
                fsync_calls += 1
                if fsync_calls == 2:
                    raise OSError("simulated parent fsync failure")

            with (
                patch("mcbe_editor.backup._fsync_directory", side_effect=fail_after_first_world_rename),
                self.assertRaisesRegex(OSError, "simulated parent fsync failure") as raised,
            ):
                restore_backup(str(world_dir), os.path.basename(backup_path))

            self.assertFalse(world_dir.exists())
            self.assertEqual(len(list(root.glob(".mcbe_restore_*.json"))), 1)
            self.assertEqual(len(list(root.glob(".world_rollback_*"))), 1)
            self.assertEqual(len(list(root.glob(".world_restoring_*"))), 1)
            self.assertIn("sichere Wiederaufnahme", getattr(raised.exception, "cleanup_warning", ""))

            recovered = recover_interrupted_restores([str(world_dir)])

            self.assertEqual(recovered[0]["status"], "original-restored")
            self.assertEqual((world_dir / "db" / "state.dat").read_text(encoding="utf-8"), "current")
            self.assertEqual(list(root.glob(".mcbe_restore_*.json")), [])
            self.assertEqual(list(root.glob(".world_rollback_*")), [])
            self.assertEqual(list(root.glob(".world_restoring_*")), [])

    def test_startup_recovery_ignores_unmarked_rollback_directory(self):
        from mcbe_editor.backup import recover_interrupted_restores

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            rollback = root / ".world_rollback_2026-01-01_00-00-00-00000000_deadbeefdeadbeef"
            (rollback / "db").mkdir(parents=True)

            self.assertEqual(recover_interrupted_restores([str(root)]), [])
            self.assertTrue(rollback.is_dir())
            self.assertFalse((root / "world").exists())

    def test_startup_recovery_defers_all_mutation_when_write_gate_is_blocked(self):
        from mcbe_editor.backup import _write_restore_transaction, recover_interrupted_restores

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            world_dir = root / "world"
            rollback = root / ".world_rollback_2026-01-01_00-00-00-00000000_aaaaaaaaaaaaaaaa"
            staging = root / ".world_restoring_interrupted"
            (rollback / "db").mkdir(parents=True)
            (rollback / "db" / "state.dat").write_text("original", encoding="utf-8")
            (staging / "db").mkdir(parents=True)
            (staging / "db" / "state.dat").write_text("backup", encoding="utf-8")
            journal = _write_restore_transaction(
                str(root),
                "world",
                str(rollback),
                str(staging),
                "aaaaaaaaaaaaaaaa",
            )

            recovered = recover_interrupted_restores(
                [str(world_dir)],
                recovery_gate_check=lambda: {"allowed": False, "reason": "Server läuft noch."},
            )

            self.assertEqual(recovered[0]["status"], "deferred-write-gate")
            self.assertIn("Server läuft", recovered[0]["reason"])
            self.assertFalse(world_dir.exists())
            self.assertTrue(rollback.is_dir())
            self.assertTrue(staging.is_dir())
            self.assertTrue(Path(journal).exists())

    def test_startup_recovery_finishes_cleanup_after_committed_swap(self):
        from mcbe_editor.backup import _write_restore_transaction, recover_interrupted_restores

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            world_dir = root / "world"
            rollback = root / ".world_rollback_2026-01-01_00-00-00-00000000_aaaaaaaaaaaaaaaa"
            staging = root / ".world_restoring_interrupted"
            (world_dir / "db").mkdir(parents=True)
            (world_dir / "db" / "state.dat").write_text("restored", encoding="utf-8")
            (rollback / "db").mkdir(parents=True)
            (rollback / "db" / "state.dat").write_text("original", encoding="utf-8")
            journal = _write_restore_transaction(
                str(root),
                "world",
                str(rollback),
                str(staging),
                "aaaaaaaaaaaaaaaa",
            )

            recovered = recover_interrupted_restores([str(root)])

            self.assertEqual(recovered[0]["status"], "committed-cleaned")
            self.assertEqual((world_dir / "db" / "state.dat").read_text(encoding="utf-8"), "restored")
            self.assertFalse(rollback.exists())
            self.assertFalse(staging.exists())
            self.assertFalse(Path(journal).exists())

    def test_startup_recovery_preserves_all_candidates_when_world_and_staging_exist(self):
        from mcbe_editor.backup import _write_restore_transaction, recover_interrupted_restores

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            world_dir = root / "world"
            rollback = root / ".world_rollback_2026-01-01_00-00-00-00000000_aaaaaaaaaaaaaaaa"
            staging = root / ".world_restoring_interrupted"
            for path, marker in ((world_dir, "external"), (rollback, "original"), (staging, "backup")):
                (path / "db").mkdir(parents=True)
                (path / "db" / "state.dat").write_text(marker, encoding="utf-8")
            journal = _write_restore_transaction(
                str(root),
                "world",
                str(rollback),
                str(staging),
                "aaaaaaaaaaaaaaaa",
            )

            recovered = recover_interrupted_restores([str(root)])

            self.assertEqual(recovered[0]["status"], "manual-recovery-required")
            self.assertIn("Keine der vorhandenen Weltkopien wurde gelöscht", recovered[0]["error"])
            self.assertEqual((world_dir / "db" / "state.dat").read_text(encoding="utf-8"), "external")
            self.assertEqual((rollback / "db" / "state.dat").read_text(encoding="utf-8"), "original")
            self.assertEqual((staging / "db" / "state.dat").read_text(encoding="utf-8"), "backup")
            self.assertTrue(Path(journal).exists())

    def test_startup_recovery_cleans_journal_and_staging_when_swap_never_started(self):
        from mcbe_editor.backup import create_backup, recover_interrupted_restores, restore_backup

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            world_dir = root / "world"
            (world_dir / "db").mkdir(parents=True)
            (world_dir / "db" / "state.dat").write_text("backup", encoding="utf-8")
            backup_path = create_backup(str(world_dir))
            (world_dir / "db" / "state.dat").write_text("current", encoding="utf-8")

            real_replace = os.replace

            def interrupt_before_world_swap(src, dst):
                if Path(dst).name.startswith(".world_rollback_"):
                    raise SystemExit("simulated container stop")
                return real_replace(src, dst)

            with patch("mcbe_editor.backup.os.replace", side_effect=interrupt_before_world_swap), self.assertRaises(SystemExit):
                restore_backup(str(world_dir), os.path.basename(backup_path))

            self.assertEqual((world_dir / "db" / "state.dat").read_text(encoding="utf-8"), "current")
            self.assertEqual(len(list(root.glob(".mcbe_restore_*.json"))), 1)
            self.assertEqual(list(root.glob(".world_rollback_*")), [])
            self.assertEqual(len(list(root.glob(".world_restoring_*"))), 1)

            recovered = recover_interrupted_restores([str(world_dir)])

            self.assertEqual(recovered[0]["status"], "not-started-cleaned")
            self.assertEqual((world_dir / "db" / "state.dat").read_text(encoding="utf-8"), "current")
            self.assertEqual(list(root.glob(".mcbe_restore_*.json")), [])
            self.assertEqual(list(root.glob(".world_restoring_*")), [])
            self.assertEqual(recover_interrupted_restores([str(world_dir)]), [])

    def test_startup_recovery_resumes_cleanup_after_interrupted_recovery(self):
        from mcbe_editor.backup import create_backup, recover_interrupted_restores, restore_backup

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            world_dir = root / "world"
            (world_dir / "db").mkdir(parents=True)
            (world_dir / "db" / "state.dat").write_text("backup", encoding="utf-8")
            backup_path = create_backup(str(world_dir))
            (world_dir / "db" / "state.dat").write_text("current", encoding="utf-8")

            real_replace = os.replace

            def interrupt_before_commit(src, dst):
                if Path(src).name.startswith(".world_restoring_"):
                    raise SystemExit("simulated container stop")
                return real_replace(src, dst)

            with patch("mcbe_editor.backup.os.replace", side_effect=interrupt_before_commit), self.assertRaises(SystemExit):
                restore_backup(str(world_dir), os.path.basename(backup_path))

            with patch("mcbe_editor.backup._remove_restore_staging", side_effect=OSError("simulated stop during recovery cleanup")):
                first_attempt = recover_interrupted_restores([str(world_dir)])

            self.assertEqual(first_attempt[0]["status"], "manual-recovery-required")
            self.assertEqual((world_dir / "db" / "state.dat").read_text(encoding="utf-8"), "current")
            self.assertEqual(list(root.glob(".world_rollback_*")), [])
            self.assertEqual(len(list(root.glob(".world_restoring_*"))), 1)
            self.assertEqual(len(list(root.glob(".mcbe_restore_*.json"))), 1)

            recovered = recover_interrupted_restores([str(world_dir)])

            self.assertEqual(recovered[0]["status"], "not-started-cleaned")
            self.assertEqual((world_dir / "db" / "state.dat").read_text(encoding="utf-8"), "current")
            self.assertEqual(list(root.glob(".mcbe_restore_*.json")), [])
            self.assertEqual(list(root.glob(".world_restoring_*")), [])

    def test_startup_recovery_keeps_manual_state_when_rollback_entry_is_not_a_world(self):
        from mcbe_editor.backup import _write_restore_transaction, recover_interrupted_restores

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            world_dir = root / "world"
            staging = root / ".world_restoring_interrupted"
            rollback = root / ".world_rollback_2026-01-01_00-00-00-00000000_aaaaaaaaaaaaaaaa"
            for path, marker in ((world_dir, "current"), (staging, "backup")):
                (path / "db").mkdir(parents=True)
                (path / "db" / "state.dat").write_text(marker, encoding="utf-8")
            rollback.mkdir()
            journal = _write_restore_transaction(
                str(root),
                "world",
                str(rollback),
                str(staging),
                "aaaaaaaaaaaaaaaa",
            )

            recovered = recover_interrupted_restores([str(root)])

            self.assertEqual(recovered[0]["status"], "manual-recovery-required")
            self.assertEqual((world_dir / "db" / "state.dat").read_text(encoding="utf-8"), "current")
            self.assertEqual((staging / "db" / "state.dat").read_text(encoding="utf-8"), "backup")
            self.assertTrue(rollback.is_dir())
            self.assertTrue(Path(journal).exists())

    def test_restore_backup_clears_stale_files_and_cleans_up(self):
        from mcbe_editor.backup import create_backup, get_backups_dir, restore_backup

        with TemporaryDirectory() as tmp:
            world_dir = Path(tmp) / "world"
            world_dir.mkdir()
            (world_dir / "db").mkdir()
            (world_dir / "db" / "file1.dat").write_text("file1_data")
            (world_dir / "levelname.txt").write_text("My World")

            backup_path = create_backup(str(world_dir))
            backup_filename = os.path.basename(backup_path)

            (world_dir / "db" / "file1.dat").write_text("file1_modified")
            (world_dir / "db" / "stale.dat").write_text("stale_data")
            (world_dir / "levelname.txt").write_text("Modified World")

            restore_backup(str(world_dir), backup_filename)

            self.assertEqual((world_dir / "db" / "file1.dat").read_text(), "file1_data")
            self.assertFalse((world_dir / "db" / "stale.dat").exists())
            self.assertEqual((world_dir / "levelname.txt").read_text(), "My World")

            parent = Path(get_backups_dir(str(world_dir))).parent
            restoring_dir = parent / "world_restoring"
            self.assertFalse(restoring_dir.exists())
            self.assertEqual(list(parent.glob(".world_restoring_*")), [])

            rollback_folders = list(parent.glob(".world_rollback_*"))
            self.assertEqual(len(rollback_folders), 0)

    def test_restore_backup_restores_original_when_restore_swap_fails(self):
        from mcbe_editor.backup import create_backup, restore_backup

        with TemporaryDirectory() as tmp:
            world_dir = Path(tmp) / "world"
            (world_dir / "db").mkdir(parents=True)
            (world_dir / "db" / "file1.dat").write_text("backup_data")
            (world_dir / "levelname.txt").write_text("Backup World")

            backup_path = create_backup(str(world_dir))
            backup_filename = os.path.basename(backup_path)

            (world_dir / "db" / "file1.dat").write_text("current_data")
            (world_dir / "levelname.txt").write_text("Current World")

            real_replace = os.replace
            calls = []

            def flaky_replace(src, dst):
                calls.append((str(src), str(dst)))
                if len(calls) == 2:
                    raise OSError("simulated restore placement failure")
                return real_replace(src, dst)

            with patch("mcbe_editor.backup.os.replace", side_effect=flaky_replace), self.assertRaisesRegex(OSError, "simulated restore"):
                restore_backup(str(world_dir), backup_filename)

            self.assertTrue(world_dir.is_dir())
            self.assertEqual((world_dir / "db" / "file1.dat").read_text(), "current_data")
            self.assertEqual((world_dir / "levelname.txt").read_text(), "Current World")
            self.assertEqual(list(Path(tmp).glob(".world_restoring_*")), [])
            self.assertEqual(list(Path(tmp).glob(".world_rollback_*")), [])

    def test_restore_backup_accepts_pre_resolved_backup_path(self):
        from mcbe_editor.backup import create_backup, restore_backup

        with TemporaryDirectory() as tmp:
            world_dir = Path(tmp) / "world"
            (world_dir / "db").mkdir(parents=True)
            (world_dir / "db" / "file.dat").write_text("backup-data")

            backup_path = create_backup(str(world_dir))
            (world_dir / "db" / "file.dat").write_text("modified")

            restore_backup(str(world_dir), os.path.basename(backup_path), resolved_backup_path=backup_path)

            self.assertEqual((world_dir / "db" / "file.dat").read_text(), "backup-data")

    def test_restore_snapshot_is_unchanged_when_selected_zip_is_replaced(self):
        from mcbe_editor.backup import create_backup, restore_backup, snapshot_backup_for_restore

        with TemporaryDirectory() as tmp:
            world_dir = Path(tmp) / "world"
            (world_dir / "db").mkdir(parents=True)
            (world_dir / "db" / "file.dat").write_text("selected-backup")
            selected_path = create_backup(str(world_dir))
            snapshot_path = snapshot_backup_for_restore(str(world_dir), selected_path)
            try:
                (world_dir / "db" / "file.dat").write_text("replacement-backup")
                replacement_path = create_backup(str(world_dir))
                os.replace(replacement_path, selected_path)
                (world_dir / "db" / "file.dat").write_text("current")

                restore_backup(
                    str(world_dir),
                    os.path.basename(selected_path),
                    resolved_backup_path=snapshot_path,
                )

                self.assertEqual((world_dir / "db" / "file.dat").read_text(), "selected-backup")
            finally:
                Path(snapshot_path).unlink(missing_ok=True)

    def test_restore_backup_pre_restore_check_blocks_before_world_replace(self):
        from mcbe_editor.backup import create_backup, restore_backup

        with TemporaryDirectory() as tmp:
            world_dir = Path(tmp) / "world"
            world_dir.mkdir()
            (world_dir / "db").mkdir()
            (world_dir / "db" / "file.dat").write_text("backup-data")
            backup_path = create_backup(str(world_dir))
            backup_filename = os.path.basename(backup_path)

            (world_dir / "db" / "file.dat").write_text("current-data")

            def pre_restore_check():
                raise ValueError("Restore abgelehnt: finaler Test-Guard")

            with self.assertRaisesRegex(ValueError, "finaler Test-Guard"):
                restore_backup(str(world_dir), backup_filename, pre_restore_check=pre_restore_check)

            self.assertTrue(world_dir.is_dir())
            self.assertEqual((world_dir / "db" / "file.dat").read_text(), "current-data")

    def test_restore_backup_does_not_delete_preexisting_fixed_restore_dir(self):
        from mcbe_editor.backup import create_backup, restore_backup

        with TemporaryDirectory() as tmp:
            parent = Path(tmp)
            world_dir = parent / "world"
            world_dir.mkdir()
            (world_dir / "db").mkdir()
            (world_dir / "db" / "file.dat").write_text("backup-data")

            backup_path = create_backup(str(world_dir))
            backup_filename = os.path.basename(backup_path)

            stale_restore_dir = parent / "world_restoring"
            stale_restore_dir.mkdir()
            (stale_restore_dir / "keep.txt").write_text("must survive")

            (world_dir / "db" / "file.dat").write_text("modified")
            restore_backup(str(world_dir), backup_filename)

            self.assertEqual((world_dir / "db" / "file.dat").read_text(), "backup-data")
            self.assertEqual((stale_restore_dir / "keep.txt").read_text(), "must survive")


class TestBackupRetention(unittest.TestCase):
    def test_default_max_backups_is_bounded(self):
        from unittest.mock import patch
        from mcbe_editor.config import load_config

        with patch.dict(os.environ, {"MCBE_MAX_BACKUPS_PER_WORLD": ""}, clear=False):
            self.assertEqual(load_config().max_backups_per_world, 20)
            self.assertEqual(load_config().max_pre_restore_backups_per_world, 5)

    def test_backup_root_uses_world_path_hash_to_avoid_collisions(self):
        from unittest.mock import patch

        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"MCBE_BACKUP_ROOT": str(Path(tmp) / "backups")}, clear=False):
            root = Path(tmp) / "root"
            w1 = root / "server1" / "world"
            w2 = root / "server2" / "world"
            w1.mkdir(parents=True)
            w2.mkdir(parents=True)
            self.assertNotEqual(get_backups_dir(str(w1)), get_backups_dir(str(w2)))
            self.assertTrue(Path(get_backups_dir(str(w1))).name.startswith("world_"))
            self.assertTrue(Path(get_backups_dir(str(w2))).name.startswith("world_"))

    def test_deferred_pruning_does_not_delete_existing_backup_on_failed_save_path(self):
        from unittest.mock import patch
        from mcbe_editor.backup import create_backup, prune_backups

        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"MCBE_MAX_BACKUPS_PER_WORLD": "1"}, clear=False):
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            (world / "db" / "file.dat").write_text("before")
            first = create_backup(str(world))

            (world / "db" / "file.dat").write_text("after")
            second = create_backup(str(world), prune_after=False)
            os.remove(second)  # Simulate validation failing before any DB write.

            self.assertTrue(os.path.exists(first))
            prune_backups(str(world))
            self.assertTrue(os.path.exists(first))

    def test_prune_can_protect_pre_restore_backup(self):
        from unittest.mock import patch
        from mcbe_editor.backup import create_backup, prune_backups

        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"MCBE_MAX_BACKUPS_PER_WORLD": "1"}, clear=False):
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            (world / "db" / "file.dat").write_text("old")
            old = create_backup(str(world), prune_after=False)
            (world / "db" / "file.dat").write_text("pre-restore")
            pre_restore = create_backup(str(world), prune_after=False)

            prune_backups(str(world), keep_paths=[pre_restore])

            self.assertTrue(os.path.exists(pre_restore))
            self.assertFalse(os.path.exists(old))

    def test_prune_keeps_all_protected_restore_backups_even_above_limit(self):
        from unittest.mock import patch
        from mcbe_editor.backup import create_backup, prune_backups

        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"MCBE_MAX_BACKUPS_PER_WORLD": "1"}, clear=False):
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            (world / "db" / "file.dat").write_text("source")
            source = create_backup(str(world), prune_after=False)
            (world / "db" / "file.dat").write_text("pre-restore")
            pre_restore = create_backup(str(world), prune_after=False)

            prune_backups(str(world), keep_paths=[source, pre_restore])

            self.assertTrue(os.path.exists(source))
            self.assertTrue(os.path.exists(pre_restore))


if __name__ == "__main__":
    unittest.main()


class TestBackupPreview(unittest.TestCase):
    def test_preview_backup_reports_safe_restore_summary(self):
        from mcbe_editor.backup import create_backup, preview_backup

        with TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            (world / "db" / "CURRENT").write_text("manifest")
            (world / "levelname.txt").write_text("Preview World")

            backup_path = create_backup(str(world))
            result = preview_backup(str(world), os.path.basename(backup_path))

            self.assertTrue(result["success"])
            self.assertEqual(result["target_world"]["name"], "Preview World")
            self.assertTrue(result["backup"]["has_db"])
            self.assertGreaterEqual(result["backup"]["file_count"], 2)
            self.assertIn("db", result["backup"]["top_level_entries"])


def test_preview_backup_reads_levelname_with_bounded_stream(tmp_path):
    import zipfile
    from mcbe_editor.backup import get_backups_dir, preview_backup

    world = tmp_path / "World"
    (world / "db").mkdir(parents=True)
    backup_dir = Path(get_backups_dir(str(world)))
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / "preview.zip"
    with zipfile.ZipFile(backup, "w") as zf:
        zf.writestr("levelname.txt", "A" * 10_000)
        zf.writestr("db/CURRENT", "CURRENT")

    preview = preview_backup(str(world), "preview.zip")

    assert preview["success"] is True
    assert preview["backup"]["levelname"] == "A" * 160


def test_preview_backup_rejects_crc_corrupt_database_member(tmp_path):
    import struct

    from mcbe_editor.backup import get_backups_dir, preview_backup

    world = tmp_path / "World"
    (world / "db").mkdir(parents=True)
    backup_dir = Path(get_backups_dir(str(world)))
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / "crc-corrupt.zip"
    with zipfile.ZipFile(backup, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("levelname.txt", "CRC Preview")
        archive.writestr("db/CURRENT", b"corrupt-me")

    with zipfile.ZipFile(backup, "r") as archive:
        info = archive.getinfo("db/CURRENT")
    raw = bytearray(backup.read_bytes())
    name_length, extra_length = struct.unpack_from("<HH", raw, info.header_offset + 26)
    data_offset = info.header_offset + 30 + name_length + extra_length
    raw[data_offset] ^= 0xFF
    backup.write_bytes(raw)

    with pytest.raises(ValueError, match="CRC-Fehler"):
        preview_backup(str(world), backup.name)


class TestManualBackupRoute(unittest.TestCase):
    def test_create_backup_route_creates_zip_and_read_only_blocks(self):
        import main
        from dataclasses import replace
        from mcbe_editor.item_data import ENCHANTMENTS, ITEMS
        from mcbe_editor.services import BedrockEditorService

        with TemporaryDirectory() as tmp:
            world = Path(tmp) / "world"
            (world / "db").mkdir(parents=True)
            (world / "levelname.txt").write_text("Backup World", encoding="utf-8")
            (world / "db" / "CURRENT").write_text("MANIFEST-000001", encoding="utf-8")

            service = BedrockEditorService(ITEMS, ENCHANTMENTS)
            with patch.dict(os.environ, {"MCBE_BACKUP_ROOT": str(Path(tmp) / "backups")}):
                result = service.create_manual_backup(str(world))

                self.assertTrue(result["success"])
                self.assertTrue(result["backup_file"].endswith(".zip"))
                backups = list((Path(tmp) / "backups").rglob("*.zip"))
                self.assertEqual(len(backups), 1)
                with zipfile.ZipFile(backups[0]) as zf:
                    self.assertIn("db/CURRENT", {name.replace("\\", "/") for name in zf.namelist()})

        # Route-Ebene: Read-Only-Modus blockiert das Anlegen mit 403.
        previous_config = main.APP_CONFIG
        main.APP_CONFIG = replace(main.APP_CONFIG, read_only=True)
        try:
            with patch("main.CSRF_TOKEN", "backup-token"):
                client = main.app.test_client()
                client.testing = True
                resp = client.post(
                    "/api/backup/create",
                    json={"world_path": "C:/world"},
                    headers={"X-CSRF-Token": "backup-token"},
                )
        finally:
            main.APP_CONFIG = previous_config

        self.assertEqual(resp.status_code, 403)
        self.assertFalse(resp.get_json()["success"])

    def test_delete_backup_route_calls_service_without_server_write_gate(self):
        import main

        with (
            patch("main.CSRF_TOKEN", "backup-token"),
            patch.object(
                main.editor_service,
                "delete_backup",
                return_value={"success": True, "backup_file": "manual.zip"},
            ) as delete_backup,
            patch("main.write_gate") as write_gate,
        ):
            client = main.app.test_client()
            client.testing = True
            response = client.post(
                "/api/backup/delete",
                json={"world_path": "C:/world", "backup_file": "manual.zip"},
                headers={"X-CSRF-Token": "backup-token"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["success"])
        delete_backup.assert_called_once_with("C:/world", "manual.zip")
        write_gate.assert_not_called()


def test_prune_reports_real_delete_failures_and_continues(tmp_path):
    from mcbe_editor.backup import BackupRetentionError, get_backups_dir, prune_backups

    world = tmp_path / "world"
    (world / "db").mkdir(parents=True)
    backups_dir = Path(get_backups_dir(str(world)))
    backups_dir.mkdir(parents=True, exist_ok=True)
    newest = backups_dir / "newest.zip"
    failed = backups_dir / "old_failed.zip"
    removable = backups_dir / "old_removable.zip"
    for path in (newest, failed, removable):
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("db/CURRENT", path.stem)
    os.utime(newest, (30, 30))
    os.utime(failed, (20, 20))
    os.utime(removable, (10, 10))

    original_remove = os.remove

    def remove_with_one_failure(path):
        if os.path.normpath(path) == os.path.normpath(failed):
            raise PermissionError("locked")
        return original_remove(path)

    with (
        patch.dict(os.environ, {"MCBE_MAX_BACKUPS_PER_WORLD": "1"}, clear=False),
        patch(
            "mcbe_editor.backup.os.remove",
            side_effect=remove_with_one_failure,
        ),
        pytest.raises(BackupRetentionError, match="old_failed.zip"),
    ):
        prune_backups(str(world))

    assert newest.exists()
    assert failed.exists()
    assert not removable.exists()


def test_create_backup_cleanup_error_does_not_mask_original_failure(tmp_path):
    from mcbe_editor.backup import create_backup

    world = tmp_path / "world"
    (world / "db").mkdir(parents=True)
    (world / "db" / "CURRENT").write_text("manifest", encoding="utf-8")

    with (
        patch("mcbe_editor.backup._verify_zip_integrity", side_effect=ValueError("original integrity failure")),
        patch(
            "mcbe_editor.backup.os.remove",
            side_effect=PermissionError("cleanup masked original"),
        ),
        pytest.raises(ValueError, match="original integrity failure"),
    ):
        create_backup(str(world), prune_after=False)


def test_aborted_write_backup_cleanup_failure_is_attached_to_primary_error(tmp_path):
    from mcbe_editor.backup import remove_backup_after_aborted_write

    backup_file = tmp_path / "world_before_write.zip"
    backup_file.write_bytes(b"backup")
    primary_error = ValueError("write gate changed")

    with patch("mcbe_editor.backup.os.remove", side_effect=PermissionError("backup locked")):
        remove_backup_after_aborted_write(
            str(backup_file),
            primary_error,
            operation="test.write",
        )

    assert backup_file.exists()
    assert "backup locked" in primary_error.cleanup_warning
    assert str(backup_file) in primary_error.cleanup_warning


def test_restore_snapshot_rejects_backup_replaced_after_preview(tmp_path):
    from mcbe_editor.backup import create_backup, preview_backup, snapshot_backup_for_restore

    world = tmp_path / "world"
    (world / "db").mkdir(parents=True)
    (world / "db" / "CURRENT").write_text("first", encoding="utf-8")
    (world / "levelname.txt").write_text("Previewed A", encoding="utf-8")
    backup_path = Path(create_backup(str(world), prune_after=False))
    preview = preview_backup(str(world), backup_path.name)

    with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        zipf.writestr("db/CURRENT", "replacement")
        zipf.writestr("levelname.txt", "Replacement B")

    with pytest.raises(ValueError, match="seit der Vorschau verändert"):
        snapshot_backup_for_restore(
            str(world),
            str(backup_path),
            expected_token=preview["backup_token"],
        )


def test_restore_snapshot_rejects_preview_token_for_different_world(tmp_path):
    from mcbe_editor.backup import create_backup, get_backups_dir, preview_backup, snapshot_backup_for_restore

    world_a = tmp_path / "world_a"
    world_b = tmp_path / "world_b"
    for world, content in ((world_a, "A"), (world_b, "B")):
        (world / "db").mkdir(parents=True)
        (world / "db" / "CURRENT").write_text(content, encoding="utf-8")

    backup_a = Path(create_backup(str(world_a), prune_after=False))
    preview_a = preview_backup(str(world_a), backup_a.name)
    backup_b_dir = Path(get_backups_dir(str(world_b)))
    backup_b_dir.mkdir(parents=True, exist_ok=True)
    backup_b = backup_b_dir / backup_a.name
    backup_b.write_bytes(backup_a.read_bytes())

    with pytest.raises(ValueError, match="Welt wurde seit der Vorschau gewechselt"):
        snapshot_backup_for_restore(
            str(world_b),
            str(backup_b),
            expected_token=preview_a["backup_token"],
        )


def test_create_backup_never_overwrites_existing_timestamp_collision(tmp_path):
    from datetime import UTC, datetime as real_datetime

    from mcbe_editor.backup import create_backup, get_backups_dir

    world = tmp_path / "World"
    (world / "db").mkdir(parents=True)
    (world / "db" / "CURRENT").write_text("new", encoding="utf-8")
    backups_dir = Path(get_backups_dir(str(world)))
    backups_dir.mkdir(parents=True, exist_ok=True)
    existing_second = backups_dir / "World_20260712_143000_123456.zip"
    existing_second.write_bytes(b"existing-backup")

    with patch("mcbe_editor.backup._utc_now", return_value=real_datetime(2026, 7, 12, 14, 30, 0, 123456, tzinfo=UTC)):
        created = Path(create_backup(str(world), prune_after=False))

    assert existing_second.read_bytes() == b"existing-backup"
    assert created != existing_second
    assert created.is_file()
    with zipfile.ZipFile(created, "r") as archive:
        assert archive.read("db/CURRENT") == b"new"


def test_incomplete_backup_placeholders_are_ignored_by_listing_and_retention(tmp_path):
    from mcbe_editor.backup import get_backups_dir, list_backups, prune_backups

    world = tmp_path / "world"
    (world / "db").mkdir(parents=True)
    backup_root = tmp_path / "backup-root"
    with patch.dict(
        os.environ,
        {
            "MCBE_BACKUP_ROOT": str(backup_root),
            "MCBE_MAX_BACKUPS_PER_WORLD": "1",
        },
        clear=False,
    ):
        backups_dir = Path(get_backups_dir(str(world)))
        backups_dir.mkdir(parents=True, exist_ok=True)
        old_valid = backups_dir / "old.zip"
        new_valid = backups_dir / "new.zip"
        for path, value in ((old_valid, b"old"), (new_valid, b"new")):
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("db/CURRENT", value)
        placeholder = backups_dir / "crashed.zip"
        placeholder.write_bytes(b"")
        os.utime(old_valid, (1, 1))
        os.utime(new_valid, (2, 2))
        os.utime(placeholder, (3, 3))

        assert [entry["filename"] for entry in list_backups(str(world))] == ["new.zip", "old.zip"]
        prune_backups(str(world))

        assert new_valid.exists()
        assert not old_valid.exists()
        assert placeholder.exists()


def test_failed_backup_creation_leaves_no_visible_zip_placeholder(tmp_path):
    from mcbe_editor.backup import create_backup, get_backups_dir

    world = tmp_path / "world"
    (world / "db").mkdir(parents=True)
    (world / "db" / "CURRENT").write_text("manifest", encoding="utf-8")
    backup_root = tmp_path / "backup-root"
    with (
        patch.dict(os.environ, {"MCBE_BACKUP_ROOT": str(backup_root)}, clear=False),
        patch(
            "mcbe_editor.backup._verify_zip_integrity",
            side_effect=ValueError("integrity failed"),
        ),
    ):
        with pytest.raises(ValueError, match="integrity failed"):
            create_backup(str(world), prune_after=False)
        backups_dir = Path(get_backups_dir(str(world)))
        assert list(backups_dir.glob("*.zip")) == []
        assert list(backups_dir.glob("*.part")) == []


def test_corrupt_nonempty_backup_is_ignored_by_listing_and_retention(tmp_path):
    from mcbe_editor.backup import get_backups_dir, list_backups, prune_backups

    world = tmp_path / "world"
    (world / "db").mkdir(parents=True)
    with patch.dict(
        os.environ,
        {
            "MCBE_BACKUP_ROOT": str(tmp_path / "backup-root"),
            "MCBE_MAX_BACKUPS_PER_WORLD": "1",
        },
        clear=False,
    ):
        backups_dir = Path(get_backups_dir(str(world)))
        backups_dir.mkdir(parents=True, exist_ok=True)
        valid = backups_dir / "valid.zip"
        with zipfile.ZipFile(valid, "w") as archive:
            archive.writestr("db/CURRENT", "valid")
        corrupt = backups_dir / "newer-corrupt.zip"
        corrupt.write_bytes(b"not-a-zip-but-not-empty")
        os.utime(valid, (1, 1))
        os.utime(corrupt, (2, 2))

        assert [entry["filename"] for entry in list_backups(str(world))] == ["valid.zip"]
        prune_backups(str(world))

        assert valid.exists()
        assert corrupt.exists()


def test_backup_publish_fallback_never_replaces_existing_target(tmp_path):
    import errno

    from mcbe_editor.backup import _publish_archive_no_clobber

    source = tmp_path / "source.part"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("db/CURRENT", "new")
    target = tmp_path / "target.zip"
    target.write_bytes(b"existing")

    with patch("mcbe_editor.backup.os.link", side_effect=OSError(errno.EPERM, "no hardlinks")):
        assert _publish_archive_no_clobber(str(source), str(target)) is False

    assert target.read_bytes() == b"existing"
    assert source.exists()


def test_crc_corrupt_backup_is_ignored_by_listing_and_retention(tmp_path):
    import struct

    from mcbe_editor.backup import get_backups_dir, list_backups, prune_backups

    world = tmp_path / "world"
    (world / "db").mkdir(parents=True)
    with patch.dict(
        os.environ,
        {
            "MCBE_BACKUP_ROOT": str(tmp_path / "backup-root"),
            "MCBE_MAX_BACKUPS_PER_WORLD": "1",
        },
        clear=False,
    ):
        backups_dir = Path(get_backups_dir(str(world)))
        backups_dir.mkdir(parents=True, exist_ok=True)
        valid = backups_dir / "valid.zip"
        corrupt = backups_dir / "newer-crc-corrupt.zip"
        for archive_path, payload in ((valid, b"valid"), (corrupt, b"corrupt-me")):
            with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_STORED) as archive:
                archive.writestr("db/CURRENT", payload)

        with zipfile.ZipFile(corrupt, "r") as archive:
            info = archive.getinfo("db/CURRENT")
        raw = bytearray(corrupt.read_bytes())
        name_length, extra_length = struct.unpack_from("<HH", raw, info.header_offset + 26)
        data_offset = info.header_offset + 30 + name_length + extra_length
        raw[data_offset] ^= 0xFF
        corrupt.write_bytes(raw)
        assert zipfile.is_zipfile(corrupt)

        os.utime(valid, (1, 1))
        os.utime(corrupt, (2, 2))

        assert [entry["filename"] for entry in list_backups(str(world))] == ["valid.zip"]
        prune_backups(str(world))

        assert valid.exists()
        assert corrupt.exists()


def test_crc_corrupt_backup_with_valid_looking_metadata_is_not_trusted(tmp_path):
    import json
    import struct

    from mcbe_editor.backup import get_backups_dir, list_backups

    world = tmp_path / "world"
    (world / "db").mkdir(parents=True)
    with patch.dict(os.environ, {"MCBE_BACKUP_ROOT": str(tmp_path / "backup-root")}, clear=False):
        backups_dir = Path(get_backups_dir(str(world)))
        backups_dir.mkdir(parents=True, exist_ok=True)
        corrupt = backups_dir / "world__manual__20260712T120000Z__0123456789abcdef.zip"
        with zipfile.ZipFile(corrupt, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr("db/CURRENT", b"corrupt-me")
            archive.comment = json.dumps(
                {
                    "schema_version": 1,
                    "kind": "manual",
                    "retention_class": "pinned",
                    "created_at": "2026-07-12T12:00:00Z",
                }
            ).encode("utf-8")

        with zipfile.ZipFile(corrupt, "r") as archive:
            info = archive.getinfo("db/CURRENT")
        raw = bytearray(corrupt.read_bytes())
        name_length, extra_length = struct.unpack_from("<HH", raw, info.header_offset + 26)
        data_offset = info.header_offset + 30 + name_length + extra_length
        raw[data_offset] ^= 0xFF
        corrupt.write_bytes(raw)

        assert zipfile.is_zipfile(corrupt)
        assert list_backups(str(world)) == []


def test_backup_kinds_are_persisted_in_name_comment_and_listing(tmp_path):
    import json
    from datetime import UTC, datetime

    from mcbe_editor.backup import (
        BACKUP_KIND_AUTOMATIC,
        BACKUP_KIND_MANUAL,
        BACKUP_KIND_PRE_RESTORE,
        create_backup,
        list_backups,
    )

    world = tmp_path / "world"
    (world / "db").mkdir(parents=True)
    (world / "db" / "CURRENT").write_text("manifest", encoding="utf-8")
    (world / "levelname.txt").write_text("Meine Welt", encoding="utf-8")
    kinds = (BACKUP_KIND_AUTOMATIC, BACKUP_KIND_MANUAL, BACKUP_KIND_PRE_RESTORE)
    times = [datetime(2026, 7, 12, 10, index, tzinfo=UTC) for index in range(len(kinds))]

    with (
        patch.dict(os.environ, {"MCBE_BACKUP_ROOT": str(tmp_path / "backups")}, clear=False),
        patch(
            "mcbe_editor.backup._utc_now",
            side_effect=times,
        ),
    ):
        paths = [
            Path(
                create_backup(
                    str(world),
                    prune_after=False,
                    backup_kind=kind,
                    restore_source="source.zip" if kind == BACKUP_KIND_PRE_RESTORE else None,
                )
            )
            for kind in kinds
        ]
        listed = {entry["filename"]: entry for entry in list_backups(str(world))}

    for path, kind in zip(paths, kinds, strict=True):
        assert f"__{kind}__" in path.name
        assert len(path.name) <= 180
        with zipfile.ZipFile(path, "r") as archive:
            metadata = json.loads(archive.comment.decode("utf-8"))
        assert metadata["kind"] == kind
        assert listed[path.name]["kind"] == kind
        assert listed[path.name]["kind_label"]
        if kind == BACKUP_KIND_MANUAL:
            assert metadata["retention_class"] == "pinned"
        elif kind == BACKUP_KIND_PRE_RESTORE:
            assert metadata["retention_class"] == "recovery"
            assert metadata["restore_source"] == "source.zip"
        else:
            assert metadata["retention_class"] == "rolling"


def test_listing_and_preview_expose_iso_utc_timestamps_for_the_ui(tmp_path):
    """Names and shapes of these fields are a contract with the frontend.

    ``created_at`` carries metadata time for modern archives; ``modified_at``
    gives legacy archives a language-neutral filesystem time. Both are ISO UTC
    strings so the browser can render them in the active page language instead
    of falling back to the pre-rendered German display value.
    """

    from datetime import UTC, datetime

    from mcbe_editor.backup import BACKUP_KIND_MANUAL, create_backup, preview_backup

    world = tmp_path / "world"
    (world / "db").mkdir(parents=True)
    (world / "db" / "CURRENT").write_text("manifest", encoding="utf-8")
    created = datetime(2026, 7, 12, 10, 0, tzinfo=UTC)

    with patch.dict(os.environ, {"MCBE_BACKUP_ROOT": str(tmp_path / "backups")}, clear=False):
        with patch("mcbe_editor.backup._utc_now", side_effect=[created]):
            path = Path(create_backup(str(world), prune_after=False, backup_kind=BACKUP_KIND_MANUAL))

        # An archive that predates the metadata format: it carries no ISO value,
        # so the listing has to keep offering the server-rendered string.
        legacy = Path(get_backups_dir(str(world))) / "world_backup_old.zip"
        with zipfile.ZipFile(legacy, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr("db/CURRENT", b"manifest")
        legacy_modified = datetime(2025, 11, 9, 8, 7, 6, tzinfo=UTC)
        os.utime(legacy, (legacy_modified.timestamp(), legacy_modified.timestamp()))

        listed = {entry["filename"]: entry for entry in list_backups(str(world))}
        preview = preview_backup(str(world), path.name)
        legacy_preview = preview_backup(str(world), legacy.name)

    assert listed[path.name]["created_at"] == "2026-07-12T10:00:00Z"
    assert preview["backup"]["created_at"] == "2026-07-12T10:00:00Z"
    assert listed[path.name]["modified_at"] == preview["backup"]["modified_at"]

    assert listed[legacy.name]["created_at"] is None
    assert legacy_preview["backup"]["created_at"] is None
    assert listed[legacy.name]["modified_at"] == "2025-11-09T08:07:06Z"
    assert legacy_preview["backup"]["modified_at"] == "2025-11-09T08:07:06Z"
    assert listed[legacy.name]["date"]


def test_retention_separates_automatic_manual_and_pre_restore_backups(tmp_path):
    from datetime import UTC, datetime

    from mcbe_editor.backup import (
        BACKUP_KIND_AUTOMATIC,
        BACKUP_KIND_MANUAL,
        BACKUP_KIND_PRE_RESTORE,
        create_backup,
        prune_backups,
    )

    world = tmp_path / "world"
    (world / "db").mkdir(parents=True)
    (world / "db" / "CURRENT").write_text("manifest", encoding="utf-8")
    times = [datetime(2026, 7, 12, 10, minute, tzinfo=UTC) for minute in range(6)]
    env = {
        "MCBE_BACKUP_ROOT": str(tmp_path / "backups"),
        "MCBE_MAX_BACKUPS_PER_WORLD": "1",
        "MCBE_MAX_PRE_RESTORE_BACKUPS_PER_WORLD": "1",
    }
    with patch.dict(os.environ, env, clear=False), patch("mcbe_editor.backup._utc_now", side_effect=times):
        automatic_old = Path(create_backup(str(world), prune_after=False, backup_kind=BACKUP_KIND_AUTOMATIC))
        automatic_new = Path(create_backup(str(world), prune_after=False, backup_kind=BACKUP_KIND_AUTOMATIC))
        manual_old = Path(create_backup(str(world), prune_after=False, backup_kind=BACKUP_KIND_MANUAL))
        manual_new = Path(create_backup(str(world), prune_after=False, backup_kind=BACKUP_KIND_MANUAL))
        recovery_old = Path(create_backup(str(world), prune_after=False, backup_kind=BACKUP_KIND_PRE_RESTORE))
        recovery_new = Path(create_backup(str(world), prune_after=False, backup_kind=BACKUP_KIND_PRE_RESTORE))
        prune_backups(str(world))

    assert not automatic_old.exists()
    assert automatic_new.exists()
    assert manual_old.exists()
    assert manual_new.exists()
    assert not recovery_old.exists()
    assert recovery_new.exists()


def test_metadata_creation_time_controls_listing_and_rotation_not_mtime(tmp_path):
    from datetime import UTC, datetime

    from mcbe_editor.backup import create_backup, list_backups, prune_backups

    world = tmp_path / "world"
    (world / "db").mkdir(parents=True)
    (world / "db" / "CURRENT").write_text("manifest", encoding="utf-8")
    env = {
        "MCBE_BACKUP_ROOT": str(tmp_path / "backups"),
        "MCBE_MAX_BACKUPS_PER_WORLD": "1",
    }
    with (
        patch.dict(os.environ, env, clear=False),
        patch(
            "mcbe_editor.backup._utc_now",
            side_effect=[
                datetime(2026, 7, 12, 10, 0, tzinfo=UTC),
                datetime(2026, 7, 12, 11, 0, tzinfo=UTC),
            ],
        ),
    ):
        older = Path(create_backup(str(world), prune_after=False))
        newer = Path(create_backup(str(world), prune_after=False))
        os.utime(older, (9_999_999_999, 9_999_999_999))
        os.utime(newer, (1, 1))
        assert [entry["filename"] for entry in list_backups(str(world))][:2] == [newer.name, older.name]
        prune_backups(str(world))

    assert newer.exists()
    assert not older.exists()


def test_app_created_backups_do_not_repeat_full_crc_scan_for_list_or_rotation(tmp_path):
    from mcbe_editor.backup import create_backup, list_backups, prune_backups

    world = tmp_path / "world"
    (world / "db").mkdir(parents=True)
    (world / "db" / "CURRENT").write_text("manifest", encoding="utf-8")
    with patch.dict(
        os.environ,
        {
            "MCBE_BACKUP_ROOT": str(tmp_path / "backups"),
            "MCBE_MAX_BACKUPS_PER_WORLD": "1",
        },
        clear=False,
    ):
        created = Path(create_backup(str(world), prune_after=False))
        with patch("mcbe_editor.backup._verify_zip_integrity", side_effect=AssertionError("unexpected CRC scan")):
            assert [entry["filename"] for entry in list_backups(str(world))] == [created.name]
            prune_backups(str(world))


def test_stale_temporary_backup_artifacts_are_cleaned_without_touching_recent_files(tmp_path):
    import time

    from mcbe_editor.backup import get_backups_dir, list_backups

    world = tmp_path / "world"
    (world / "db").mkdir(parents=True)
    with patch.dict(os.environ, {"MCBE_BACKUP_ROOT": str(tmp_path / "backups")}, clear=False):
        backups_dir = Path(get_backups_dir(str(world)))
        backups_dir.mkdir(parents=True)
        old_part = backups_dir / ".mcbe_backup_old.part"
        recent_part = backups_dir / ".mcbe_backup_recent.part"
        old_part.write_bytes(b"old")
        recent_part.write_bytes(b"recent")
        old_time = time.time() - (2 * 24 * 60 * 60)
        os.utime(old_part, (old_time, old_time))
        list_backups(str(world))

    assert not old_part.exists()
    assert recent_part.exists()


def test_delete_backup_removes_only_validated_file_in_world_backup_directory(tmp_path):
    from mcbe_editor.backup import create_backup, delete_backup

    world = tmp_path / "world"
    (world / "db").mkdir(parents=True)
    (world / "db" / "CURRENT").write_text("manifest", encoding="utf-8")
    with patch.dict(os.environ, {"MCBE_BACKUP_ROOT": str(tmp_path / "backups")}, clear=False):
        created = Path(create_backup(str(world), prune_after=False, backup_kind="manual"))
        deleted = delete_backup(str(world), created.name)
        assert Path(deleted) == created
        assert not created.exists()
        with pytest.raises(ValueError, match="Ungültiger Backup-Dateiname"):
            delete_backup(str(world), "../outside.zip")


def test_backup_integrity_cache_ignores_valid_non_object_json(tmp_path):
    from mcbe_editor.backup import BACKUP_INTEGRITY_CACHE_FILENAME, _load_integrity_cache

    cache_path = tmp_path / BACKUP_INTEGRITY_CACHE_FILENAME
    cache_path.write_text("[]", encoding="utf-8")

    assert _load_integrity_cache(str(tmp_path)) == {}


def test_delete_backup_succeeds_when_integrity_cache_has_wrong_json_type(tmp_path):
    from mcbe_editor.backup import BACKUP_INTEGRITY_CACHE_FILENAME, create_backup, delete_backup, get_backups_dir

    world = tmp_path / "world"
    (world / "db").mkdir(parents=True)
    (world / "db" / "CURRENT").write_text("manifest", encoding="utf-8")
    with patch.dict(os.environ, {"MCBE_BACKUP_ROOT": str(tmp_path / "backups")}, clear=False):
        created = Path(create_backup(str(world), prune_after=False, backup_kind="manual"))
        cache_path = Path(get_backups_dir(str(world))) / BACKUP_INTEGRITY_CACHE_FILENAME
        cache_path.write_text("null", encoding="utf-8")

        deleted = delete_backup(str(world), created.name)

    assert Path(deleted) == created
    assert not created.exists()


def test_filename_metadata_fallback_requires_complete_generated_suffix():
    from mcbe_editor.backup import _metadata_from_filename

    assert _metadata_from_filename("Meine_Welt__pre_restore__Altbestand_2025.zip") is None
    assert _metadata_from_filename("Meine_Welt__manual__Notiz.zip") is None
    assert _metadata_from_filename("Meine_Welt__manual__20260712T120000Z__0123456789abcdef.zip")["kind"] == "manual"


def test_pre_restore_filename_does_not_accumulate_restore_source_tags(tmp_path):
    from mcbe_editor.backup import create_backup

    world = tmp_path / "world"
    (world / "db").mkdir(parents=True)
    (world / "db" / "CURRENT").write_text("manifest", encoding="utf-8")
    (world / "levelname.txt").write_text("Meine Welt", encoding="utf-8")
    source = "Meine_Welt__pre_restore__20260101T000000Z__0123456789abcdef.zip"
    with patch.dict(os.environ, {"MCBE_BACKUP_ROOT": str(tmp_path / "backups")}, clear=False):
        created = Path(
            create_backup(
                str(world),
                prune_after=False,
                backup_kind="pre_restore",
                restore_source=source,
            )
        )

    assert created.name.count("__pre_restore__") == 1
    assert source not in created.name


def test_legacy_backup_crc_is_cached_by_size_and_mtime(tmp_path):
    import mcbe_editor.backup as backup_module
    from mcbe_editor.backup import get_backups_dir, list_backups

    world = tmp_path / "world"
    (world / "db").mkdir(parents=True)
    with patch.dict(os.environ, {"MCBE_BACKUP_ROOT": str(tmp_path / "backups")}, clear=False):
        backups_dir = Path(get_backups_dir(str(world)))
        backups_dir.mkdir(parents=True)
        legacy = backups_dir / "legacy.zip"
        with zipfile.ZipFile(legacy, "w") as archive:
            archive.writestr("db/CURRENT", "valid")

        with patch(
            "mcbe_editor.backup._verify_zip_integrity",
            wraps=backup_module._verify_zip_integrity,
        ) as verify:
            assert [entry["filename"] for entry in list_backups(str(world))] == ["legacy.zip"]
            assert [entry["filename"] for entry in list_backups(str(world))] == ["legacy.zip"]

    assert verify.call_count == 1
