import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from mcbe_editor.world import (
    add_scan_path,
    detect_capabilities,
    ensure_valid_world_path,
    get_configured_paths,
    get_configured_scan_roots,
    get_minecraft_saves_candidates,
    get_minecraft_saves_dir,
    get_world_name,
    remove_scan_path,
    scan_minecraft_worlds,
    scan_minecraft_worlds_with_meta,
)


class TestEnsureValidWorldPath(unittest.TestCase):
    def test_rejects_empty_path(self):
        with self.assertRaisesRegex(ValueError, "Pfad"):
            ensure_valid_world_path("")

    def test_rejects_non_existent_directory(self):
        with self.assertRaisesRegex(ValueError, "existiert"):
            ensure_valid_world_path("/nonexistent/path")

    def test_rejects_missing_db_folder(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "world"
            path.mkdir()
            with self.assertRaisesRegex(ValueError, "db"):
                ensure_valid_world_path(str(path))

    def test_rejects_parent_saves_folder_with_actionable_message(self):
        with TemporaryDirectory() as tmp:
            saves = Path(tmp) / "minecraftWorlds"
            (saves / "world_one" / "db").mkdir(parents=True)
            (saves / "world_one" / "levelname.txt").write_text("World One", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Sammelordner"):
                ensure_valid_world_path(str(saves))

    def test_returns_db_path_for_valid_world(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "world"
            (path / "db").mkdir(parents=True)
            result = ensure_valid_world_path(str(path))
            self.assertEqual(result, os.path.join(str(path), "db"))


class TestGetWorldName(unittest.TestCase):
    def test_returns_name_from_levelname_txt(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "world"
            path.mkdir()
            (path / "levelname.txt").write_text("  My Cool World  ", encoding="utf-8")
            self.assertEqual(get_world_name(str(path)), "My Cool World")

    def test_returns_folder_name_when_no_levelname(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "world"
            path.mkdir()
            self.assertEqual(get_world_name(str(path)), "world")

    def test_handles_levelname_read_error_gracefully(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "world"
            path.mkdir()
            levelname = path / "levelname.txt"
            levelname.write_text("name", encoding="utf-8")
            with patch("builtins.open", side_effect=OSError("mock error")):
                result = get_world_name(str(path))
            self.assertEqual(result, "world")


class TestGetMinecraftSavesDir(unittest.TestCase):
    @patch.dict(os.environ, {"LOCALAPPDATA": "/mock/appdata"}, clear=True)
    def test_returns_none_when_saves_dir_not_found(self):
        result = get_minecraft_saves_dir()
        self.assertIsNone(result)

    def test_returns_none_when_localappdata_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            result = get_minecraft_saves_dir()
            self.assertIsNone(result)

    @patch.dict(os.environ, {"USERPROFILE": "/mock/user"}, clear=True)
    @patch("pathlib.Path.is_dir", return_value=True)
    def test_candidates_include_userprofile_and_preview_package(self, _mock_is_dir):
        result = [str(path) for path in get_minecraft_saves_candidates()]
        self.assertTrue(any("Microsoft.MinecraftUWP_8wekyb3d8bbwe" in path for path in result))
        self.assertTrue(any("Microsoft.MinecraftWindowsBeta_8wekyb3d8bbwe" in path for path in result))
        self.assertTrue(all("AppData" in path for path in result))

    def test_candidates_include_new_roaming_bedrock_users_worlds(self):
        with TemporaryDirectory() as tmp:
            roaming = Path(tmp) / "Roaming"
            saves = roaming / "Minecraft Bedrock" / "Users" / "123456789" / "games" / "com.mojang" / "minecraftWorlds"
            saves.mkdir(parents=True)
            with patch.dict(os.environ, {"APPDATA": str(roaming)}, clear=True):
                result = get_minecraft_saves_candidates()
                self.assertEqual(result[0], saves)
                self.assertEqual(get_minecraft_saves_dir(), saves)

    def test_candidates_include_multiple_roaming_minecraft_users(self):
        with TemporaryDirectory() as tmp:
            roaming = Path(tmp) / "Roaming"
            saves_a = roaming / "Minecraft Bedrock" / "Users" / "111" / "games" / "com.mojang" / "minecraftWorlds"
            saves_b = roaming / "Minecraft Bedrock" / "Users" / "222" / "games" / "com.mojang" / "minecraftWorlds"
            saves_a.mkdir(parents=True)
            saves_b.mkdir(parents=True)
            with patch.dict(os.environ, {"APPDATA": str(roaming)}, clear=True):
                result = get_minecraft_saves_candidates()
                self.assertIn(saves_a, result)
                self.assertIn(saves_b, result)


class TestScanPathSettings(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.settings_file = self.tmp_path / "settings.json"
        self.settings_patcher = patch("mcbe_editor.world.SCAN_PATHS_FILE", self.settings_file)
        self.settings_patcher.start()

    def tearDown(self):
        self.settings_patcher.stop()
        self.tmp.cleanup()

    def test_add_and_remove_scan_path(self):
        world = self.tmp_path / "my_world"
        (world / "db").mkdir(parents=True)
        add_scan_path(str(world))
        self.assertTrue(self.settings_file.exists())
        data = json.loads(self.settings_file.read_text(encoding="utf-8"))
        self.assertIn(str(world), [root["path"] for root in data["scan_roots"]])
        remove_scan_path(str(world))
        data = json.loads(self.settings_file.read_text(encoding="utf-8"))
        self.assertNotIn(str(world), [root["path"] for root in data["scan_roots"]])

    def test_scan_path_rejects_missing_folder(self):
        with self.assertRaisesRegex(ValueError, "existiert nicht"):
            add_scan_path("/nonexistent")

    def test_scan_path_rejects_without_db(self):
        no_db = self.tmp_path / "no_db"
        no_db.mkdir()
        with self.assertRaisesRegex(ValueError, "db"):
            add_scan_path(str(no_db))

    def test_scan_path_rejects_duplicate(self):
        world = self.tmp_path / "world"
        (world / "db").mkdir(parents=True)
        add_scan_path(str(world))
        with self.assertRaisesRegex(ValueError, "bereits konfiguriert"):
            add_scan_path(str(world))

    def test_scan_path_can_be_disabled(self):
        from mcbe_editor.world import set_scan_path_enabled

        world = self.tmp_path / "world_toggle"
        (world / "db").mkdir(parents=True)
        add_scan_path(str(world))
        set_scan_path_enabled(str(world), False)
        with patch("mcbe_editor.world.get_minecraft_saves_dir", return_value=None):
            self.assertNotIn(str(world), get_configured_paths())
            roots = get_configured_scan_roots(include_disabled=True)
            self.assertFalse(next(root for root in roots if root["path"] == str(world))["enabled"])

    def test_missing_user_scan_path_stays_visible_for_cleanup(self):
        missing = self.tmp_path / "missing_mount"
        self.settings_file.write_text(json.dumps({"scan_roots": [{"path": str(missing), "enabled": True}]}), encoding="utf-8")

        with patch("mcbe_editor.world.get_minecraft_saves_dir", return_value=None):
            self.assertNotIn(str(missing), get_configured_paths())
            roots = get_configured_scan_roots(include_disabled=True)

        stale = next(root for root in roots if root["path"] == str(missing))
        self.assertTrue(stale["removable"])
        self.assertTrue(stale["enabled"])

    def test_docker_rejects_scan_path_outside_worlds_root(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "worlds"
            root.mkdir()
            outside = Path(tmp) / "outside_world"
            (outside / "db").mkdir(parents=True)
            with (
                patch.dict(
                    os.environ,
                    {
                        "MCBE_EDITOR_MODE": "docker",
                        "MCBE_WORLDS_ROOT": str(root),
                        "MCBE_SETTINGS_PATH": str(self.settings_file),
                    },
                    clear=False,
                ),
                self.assertRaisesRegex(ValueError, "unter"),
            ):
                add_scan_path(str(outside))

    def test_docker_filters_configured_paths_outside_worlds_root(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "worlds"
            inside = root / "world_a"
            outside = Path(tmp) / "outside_world"
            (inside / "db").mkdir(parents=True)
            (outside / "db").mkdir(parents=True)
            self.settings_file.write_text(
                json.dumps(
                    {
                        "scan_roots": [
                            {"path": str(inside), "enabled": True},
                            {"path": str(outside), "enabled": True},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {
                    "MCBE_EDITOR_MODE": "docker",
                    "MCBE_WORLDS_ROOT": str(root),
                    "MCBE_SETTINGS_PATH": str(self.settings_file),
                },
                clear=False,
            ):
                paths = get_configured_paths()
            self.assertIn(str(root), paths)
            self.assertIn(str(inside), paths)
            self.assertNotIn(str(outside), paths)

    def test_remove_nonexistent_raises(self):
        with self.assertRaisesRegex(ValueError, "nicht konfiguriert"):
            remove_scan_path("/nonexistent")

    def test_get_configured_paths_includes_default_and_extra(self):
        world = self.tmp_path / "world"
        (world / "db").mkdir(parents=True)
        add_scan_path(str(world))
        with patch("mcbe_editor.world.get_minecraft_saves_dir", return_value=None):
            paths = get_configured_paths()
            self.assertIn(str(world), paths)

    def test_get_configured_paths_with_default(self):
        default = self.tmp_path / "default"
        (default / "db").mkdir(parents=True)
        world = self.tmp_path / "world"
        (world / "db").mkdir(parents=True)
        add_scan_path(str(world))
        with patch("mcbe_editor.world.get_minecraft_saves_dir", return_value=default):
            paths = get_configured_paths()
            self.assertIn(str(default), paths)
            self.assertIn(str(world), paths)

    def test_get_configured_paths_includes_all_detected_default_roots(self):
        default_a = self.tmp_path / "default_a"
        default_b = self.tmp_path / "default_b"
        (default_a / "world_a" / "db").mkdir(parents=True)
        (default_b / "world_b" / "db").mkdir(parents=True)
        with (
            patch("mcbe_editor.world.get_minecraft_saves_candidates", return_value=[default_a, default_b]),
            patch("mcbe_editor.world.get_minecraft_saves_dir", return_value=None),
        ):
            paths = get_configured_paths()
            self.assertIn(str(default_a), paths)
            self.assertIn(str(default_b), paths)


class TestScanMinecraftWorlds(unittest.TestCase):
    def test_returns_empty_for_empty_path_list(self):
        result = scan_minecraft_worlds(paths=[])
        self.assertEqual(result, [])

    def test_finds_worlds_with_db_folder(self):
        with TemporaryDirectory() as tmp:
            saves = Path(tmp) / "saves"
            (saves / "world1" / "db").mkdir(parents=True)
            (saves / "world1" / "levelname.txt").write_text("World One", encoding="utf-8")
            (saves / "world2" / "db").mkdir(parents=True)
            (saves / "not_a_world" / "other").mkdir(parents=True)
            result = scan_minecraft_worlds(paths=[str(saves)])
            names = {w["folder"] for w in result}
            self.assertIn("world1", names)
            self.assertIn("world2", names)
            self.assertNotIn("not_a_world", names)
            self.assertEqual(len(result), 2)

    def test_skips_hidden_restore_staging_and_rollback_worlds(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "worlds"
            (root / "world" / "db").mkdir(parents=True)
            (root / ".world_restoring_random" / "db").mkdir(parents=True)
            (root / ".world_rollback_2026-01-01_00-00-00-00000000_deadbeefdeadbeef" / "db").mkdir(parents=True)

            result = scan_minecraft_worlds(paths=[str(root)])

            self.assertEqual([world["folder"] for world in result], ["world"])

    def test_finds_direct_world_path(self):
        with TemporaryDirectory() as tmp:
            world = Path(tmp) / "direct_world"
            (world / "db").mkdir(parents=True)
            result = scan_minecraft_worlds(paths=[str(world)])
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["path"], str(world))
            self.assertEqual(result[0]["folder"], "direct_world")

    def test_finds_nested_worlds_with_relative_folder(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "worlds"
            nested = root / "server1" / "world_a"
            (nested / "db").mkdir(parents=True)
            result = scan_minecraft_worlds(paths=[str(root)])
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["path"], str(nested))
            self.assertEqual(result[0]["folder"], os.path.join("server1", "world_a"))

    def test_respects_scan_depth(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "worlds"
            nested = root / "server1" / "deep" / "world_a"
            (nested / "db").mkdir(parents=True)
            with patch.dict(os.environ, {"MCBE_WORLD_SCAN_DEPTH": "1"}):
                result = scan_minecraft_worlds(paths=[str(root)])
            self.assertEqual(result, [])

    def test_does_not_scan_parent_directories(self):
        with TemporaryDirectory() as tmp:
            parent = Path(tmp)
            root = parent / "worlds"
            root.mkdir()
            outside = parent / "outside_world"
            (outside / "db").mkdir(parents=True)
            result = scan_minecraft_worlds(paths=[str(root)])
            self.assertEqual(result, [])

    def test_skips_symlinked_worlds(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "worlds"
            root.mkdir()
            outside = Path(tmp) / "outside_world"
            (outside / "db").mkdir(parents=True)
            link = root / "linked_world"
            try:
                os.symlink(outside, link, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("Symlinks are not available in this environment")
            result = scan_minecraft_worlds_with_meta(paths=[str(root)])
            self.assertEqual(result["worlds"], [])
            self.assertTrue(any("Symlinks" in warning for warning in result["warnings"]))

    def test_scan_reports_truncation_for_too_many_directories(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "worlds"
            root.mkdir()
            for idx in range(120):
                (root / f"folder_{idx:03d}").mkdir()
            with patch.dict(os.environ, {"MCBE_WORLD_SCAN_MAX_DIRS": "100", "MCBE_WORLD_SCAN_DEPTH": "2"}):
                result = scan_minecraft_worlds_with_meta(paths=[str(root)])
            self.assertTrue(result["truncated"])
            self.assertTrue(result["warnings"])

    def test_scan_limit_is_shared_fairly_without_starving_later_roots(self):
        with TemporaryDirectory() as tmp:
            broad_root = Path(tmp) / "broad"
            broad_root.mkdir()
            for idx in range(140):
                (broad_root / f"folder_{idx:03d}").mkdir()
            later_root = Path(tmp) / "later"
            expected_world = later_root / "ActualWorld"
            (expected_world / "db").mkdir(parents=True)

            with patch.dict(os.environ, {"MCBE_WORLD_SCAN_MAX_DIRS": "100", "MCBE_WORLD_SCAN_DEPTH": "2"}):
                result = scan_minecraft_worlds_with_meta(paths=[str(broad_root), str(later_root)])

            self.assertEqual([world["path"] for world in result["worlds"]], [str(expected_world)])
            self.assertLessEqual(result["checked_dirs"], 100)
            self.assertTrue(result["truncated"])
            self.assertEqual(result["scan_roots"][0]["status"], "limited")
            self.assertIn("teilweise geprüft", result["scan_roots"][0]["message"])
            self.assertEqual(result["scan_roots"][1]["status"], "ok")
            self.assertEqual(result["scan_roots"][1]["world_count"], 1)

    def test_scans_multiple_paths(self):
        with TemporaryDirectory() as tmp:
            p1 = Path(tmp) / "path1"
            (p1 / "world_a" / "db").mkdir(parents=True)
            p2 = Path(tmp) / "path2"
            (p2 / "world_b" / "db").mkdir(parents=True)
            result = scan_minecraft_worlds(paths=[str(p1), str(p2)])
            self.assertEqual(len(result), 2)
            folders = {w["folder"] for w in result}
            self.assertIn("world_a", folders)
            self.assertIn("world_b", folders)

    def test_deduplicates_identical_paths(self):
        with TemporaryDirectory() as tmp:
            saves = Path(tmp) / "saves"
            (saves / "world1" / "db").mkdir(parents=True)
            result = scan_minecraft_worlds(paths=[str(saves), str(saves)])
            self.assertEqual(len(result), 1)

    def test_uses_folder_name_when_no_levelname(self):
        with TemporaryDirectory() as tmp:
            saves = Path(tmp) / "saves"
            (saves / "world1" / "db").mkdir(parents=True)
            result = scan_minecraft_worlds(paths=[str(saves)])
            self.assertEqual(result[0]["name"], "world1")

    def test_default_arg_calls_get_configured_paths(self):
        with TemporaryDirectory() as tmp:
            saves = Path(tmp) / "saves"
            (saves / "world1" / "db").mkdir(parents=True)
            with patch("mcbe_editor.world.get_configured_paths", return_value=[str(saves)]):
                result = scan_minecraft_worlds()
                self.assertEqual(len(result), 1)


class TestDetectCapabilities(unittest.TestCase):
    def test_returns_conservative_flags(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "world"
            (path / "db").mkdir(parents=True)
            result = detect_capabilities(str(path))
            self.assertTrue(result["supports_local_player"])
            self.assertFalse(result["supports_multiple_players"])
            self.assertEqual(result["world_format"], "bedrock-leveldb")
            self.assertEqual(result["write_mode"], "local_player_only")

    def test_raises_on_invalid_path(self):
        with self.assertRaises(ValueError):
            detect_capabilities("/nonexistent")


def test_parallel_scan_path_additions_are_serialized(monkeypatch, tmp_path):
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor

    import mcbe_editor.world as world_module

    settings_path = tmp_path / "settings.json"
    roots = [tmp_path / "root_a", tmp_path / "root_b"]
    for root in roots:
        root.mkdir()

    monkeypatch.setattr(world_module, "get_scan_paths_file", lambda: settings_path)
    monkeypatch.setattr(world_module, "_validate_scan_path", lambda _path: None)
    original_save = world_module._save_settings
    state_lock = threading.Lock()
    active = 0
    max_active = 0

    def slow_save(*args, **kwargs):
        nonlocal active, max_active
        with state_lock:
            active += 1
            max_active = max(max_active, active)
        try:
            time.sleep(0.05)
            return original_save(*args, **kwargs)
        finally:
            with state_lock:
                active -= 1

    monkeypatch.setattr(world_module, "_save_settings", slow_save)
    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(world_module.add_scan_path, map(str, roots)))

    assert max_active == 1
    assert {Path(root["path"]).name for root in world_module._load_settings()["scan_roots"]} == {"root_a", "root_b"}


if __name__ == "__main__":
    unittest.main()


def test_load_settings_tolerates_invalid_utf8(monkeypatch, tmp_path):
    import mcbe_editor.world as world_module

    path = tmp_path / "settings.json"
    path.write_bytes(b"\xff\xfe")
    monkeypatch.setattr(world_module, "SCAN_PATHS_FILE", path)

    assert world_module._load_settings() == world_module._empty_settings()


def test_load_settings_tolerates_excessive_json_nesting(monkeypatch, tmp_path):
    import mcbe_editor.world as world_module

    path = tmp_path / "settings.json"
    path.write_text('{"x":' * 10000 + "0" + "}" * 10000, encoding="utf-8")
    monkeypatch.setattr(world_module, "SCAN_PATHS_FILE", path)

    assert world_module._load_settings() == world_module._empty_settings()
