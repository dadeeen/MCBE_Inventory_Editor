"""Regression checks for failed icon updates, using only synthetic inputs."""

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from mcbe_editor import icon_cache, update_script_runner
from mcbe_editor.block_icon_renderer import encode_rgba_png
from scripts import update_icons

ROOT = Path(__file__).resolve().parents[1]


def _pack(path: Path, *, apple: bool) -> None:
    texture = "apple" if apple else "fixture_unknown_texture"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "resource_pack/textures/item_texture.json",
            json.dumps({"texture_data": {texture: {"textures": f"textures/items/{texture}"}}}),
        )
        archive.writestr(
            f"resource_pack/textures/items/{texture}.png",
            encode_rgba_png(16, 16, bytes([255, 0, 0, 255]) * 256),
        )


def _files(root: Path) -> dict[str, bytes]:
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}


class IconUpdateFailureSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.target = self.root / "vanilla"

    def _existing_cache(self):
        archive = self.root / "good.zip"
        _pack(archive, apple=True)
        update_icons.build_icon_cache(archive, ["apple"], self.target, {}, block_item_ids=set())
        return _files(self.target)

    def test_unrecognized_pack_layout_preserves_existing_cache(self):
        before = self._existing_cache()
        archive = self.root / "changed-layout.zip"
        with zipfile.ZipFile(archive, "w") as pack:
            pack.writestr("pack-v2/texture-data.json", "{}")
        update_icons._validate_downloaded_zip(archive)

        with self.assertRaisesRegex(ValueError, "keine unterstützten Vanilla-Texturen"):
            update_icons.build_icon_cache(archive, ["apple"], self.target, {}, block_item_ids=set())

        self.assertEqual(before, _files(self.target))
        self.assertFalse(list(self.root.glob(".vanilla.staging-*")))

    def test_empty_result_preserves_populated_cache_even_with_recognized_textures(self):
        before = self._existing_cache()
        archive = self.root / "unmatched.zip"
        _pack(archive, apple=False)

        with self.assertRaisesRegex(ValueError, "keine Item-Icons"):
            update_icons.build_icon_cache(archive, ["apple"], self.target, {}, block_item_ids=set())

        self.assertEqual(before, _files(self.target))
        self.assertFalse(list(self.root.glob(".vanilla.staging-*")))
        self.assertFalse(list(self.root.glob(".vanilla.rollback-*")))

    def test_partial_result_keeps_supported_icons_and_reports_unknown_items(self):
        archive = self.root / "partial.zip"
        _pack(archive, apple=True)

        result = update_icons.build_icon_cache(archive, ["apple", "fixture_unknown_item"], self.target, {}, block_item_ids=set())

        self.assertEqual(result["mapped_items"], 1)
        self.assertEqual(result["missing_items"], ["minecraft:fixture_unknown_item"])
        self.assertTrue((self.target / "textures/items/apple.png").is_file())

    def test_initial_unknown_item_result_can_still_report_missing_mapping(self):
        archive = self.root / "unknown.zip"
        _pack(archive, apple=False)

        result = update_icons.build_icon_cache(archive, ["fixture_unknown_item"], self.target, {}, block_item_ids=set())

        self.assertEqual(result["mapped_items"], 0)
        self.assertEqual(result["missing_items"], ["minecraft:fixture_unknown_item"])

    def _config(self):
        return SimpleNamespace(
            data_root=str(self.root / "data"),
            item_db_path=str(self.root / "data/item_db.json"),
            update_cache_dir=str(self.root / "cache"),
        )

    def test_timed_out_download_is_cleaned_by_parent_without_touching_other_runs(self):
        cache = self.root / "cache"
        cache.mkdir()
        existing = cache / "bedrock-samples-test-full.zip"
        existing.write_bytes(b"previous completed download")
        unrelated = cache / ".unrelated.part"
        unrelated.write_bytes(b"keep")
        other_run = cache / ".icon-download-other"
        other_run.mkdir()
        (other_run / "active.part").write_bytes(b"keep active")
        observed = {}
        child = """
import pathlib, time
from scripts import update_icons as updater
class Response:
    url = 'https://github.com/Mojang/bedrock-samples/releases/download/vtest/bedrock-samples-test-full.zip'
    def __enter__(self): self.reads = 0; return self
    def __exit__(self, *args): pass
    def read(self, size):
        self.reads += 1
        if self.reads == 1: return b'x' * (1024 * 1024)
        (updater.CACHE_DIR / 'download-started').write_text('yes')
        time.sleep(60)
        return b''
class Opener:
    def open(self, *args, **kwargs): return Response()
updater._build_validating_opener = lambda *args, **kwargs: Opener()
updater.download_release_zip({'resource_pack_asset': 'bedrock-samples-test-full.zip',
    'resource_pack_asset_size': 2 * 1024 * 1024, 'resource_pack_url': Response.url}, use_cache=False)
"""

        def run_child(_command, **kwargs):
            observed["directory"] = Path(kwargs["env"]["MCBE_ICON_DOWNLOAD_TEMP_DIR"])
            return subprocess.run(
                [sys.executable, "-c", child],
                cwd=kwargs["cwd"],
                env=kwargs["env"],
                timeout=3,
                capture_output=True,
                check=False,
            )

        with patch.object(update_script_runner, "_run_update", side_effect=run_child), self.assertRaises(subprocess.TimeoutExpired):
            update_script_runner.run_update_icons(ROOT, self._config())

        self.assertTrue((cache / "download-started").is_file())
        self.assertFalse(observed["directory"].exists())
        self.assertEqual(existing.read_bytes(), b"previous completed download")
        self.assertEqual(unrelated.read_bytes(), b"keep")
        self.assertEqual((other_run / "active.part").read_bytes(), b"keep active")
        self.assertEqual(sorted(cache.glob(".icon-download-*")), [other_run])

    def test_completed_zip_remains_reusable_after_parent_cleanup(self):
        cache = self.root / "cache"
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, "w") as archive:
            archive.writestr("fixture.txt", "synthetic archive")
        raw = payload.getvalue()
        info = {
            "resource_pack_asset": "bedrock-samples-test-full.zip",
            "resource_pack_asset_size": len(raw),
            "resource_pack_url": "https://github.com/Mojang/bedrock-samples/releases/download/vtest/bedrock-samples-test-full.zip",
        }
        observed = {}

        class Response(io.BytesIO):
            url = info["resource_pack_url"]

        def run_download(command, **kwargs):
            observed["directory"] = Path(kwargs["env"]["MCBE_ICON_DOWNLOAD_TEMP_DIR"])
            opener = SimpleNamespace(open=lambda *_args, **_kwargs: Response(raw))
            with (
                patch.dict(os.environ, {"MCBE_ICON_DOWNLOAD_TEMP_DIR": str(observed["directory"])}),
                patch.object(update_icons, "CACHE_DIR", cache),
                patch.object(update_icons, "_build_validating_opener", return_value=opener),
            ):
                self.assertEqual(update_icons.download_release_zip(info, use_cache=False), cache / info["resource_pack_asset"])
            return subprocess.CompletedProcess(command, 0, "done")

        with patch.object(update_script_runner, "_run_update", side_effect=run_download):
            self.assertEqual(update_script_runner.run_update_icons(ROOT, self._config()), (0, "done"))

        self.assertFalse(observed["directory"].exists())
        with (
            patch.object(update_icons, "CACHE_DIR", cache),
            patch.object(update_icons, "_build_validating_opener", side_effect=AssertionError("network must not be used")),
        ):
            result = update_icons.download_release_zip(info, use_cache=True)
        self.assertEqual(result.read_bytes(), raw)

    def test_timed_out_render_is_cleaned_without_touching_cache_or_other_staging(self):
        config = self._config()
        target = Path(config.data_root) / "icons/vanilla"
        archive = self.root / "good.zip"
        _pack(archive, apple=True)
        update_icons.build_icon_cache(archive, ["apple"], target, {}, block_item_ids=set())
        before = _files(target)
        other_run = target.parent / ".vanilla.staging-other"
        other_run.mkdir()
        (other_run / "active.txt").write_bytes(b"keep active")
        child = """
import pathlib, sys, time
from scripts import update_icons as updater
def progress(phase, **kwargs):
    if phase == 'finalizing':
        rendered = list(updater.ICON_ROOT.parent.glob('.vanilla.staging-*/textures/items/apple.png'))
        (updater.CACHE_DIR / 'render-complete').write_text('rendered' if rendered else 'missing')
        time.sleep(60)
updater.report_progress = progress
updater.build_icon_cache(pathlib.Path(sys.argv[1]), ['apple'], updater.ICON_ROOT, {}, block_item_ids=set())
"""

        def run_child(_command, **kwargs):
            return subprocess.run(
                [sys.executable, "-c", child, str(archive)],
                cwd=kwargs["cwd"],
                env=kwargs["env"],
                timeout=3,
                capture_output=True,
                check=False,
            )

        with patch.object(update_script_runner, "_run_update", side_effect=run_child), self.assertRaises(subprocess.TimeoutExpired):
            update_script_runner.run_update_icons(ROOT, config)

        self.assertEqual((Path(config.update_cache_dir) / "render-complete").read_text(), "rendered")
        self.assertEqual(before, _files(target))
        self.assertEqual(sorted(target.parent.glob(".vanilla.staging-*")), [other_run])
        self.assertEqual((other_run / "active.txt").read_bytes(), b"keep active")
        self.assertFalse(list(Path(config.update_cache_dir).glob(".icon-download-*")))

    def test_app_owned_staging_publishes_with_rename_or_windows_copy_fallback(self):
        archive = self.root / "good.zip"
        _pack(archive, apple=True)
        config = self._config()
        target = Path(config.data_root) / "icons/vanilla"
        real_replace = icon_cache.os.replace

        for copy_publish in (False, True):
            with self.subTest(copy_publish=copy_publish):
                observed = {"copy_fallback": False}

                def run_build(command, *, copy_publish=copy_publish, observed=observed, **kwargs):
                    staging = Path(kwargs["env"]["MCBE_ICON_STAGING_DIR"])
                    observed["staging"] = staging
                    self.assertEqual(staging.parent, target.parent)
                    self.assertEqual(list(staging.iterdir()), [])

                    def replace(source, destination):
                        if copy_publish and Path(source) == staging and Path(destination) == target:
                            observed["copy_fallback"] = True
                            raise PermissionError("simulate Windows directory rename restriction")
                        return real_replace(source, destination)

                    with (
                        patch.dict(os.environ, {"MCBE_ICON_STAGING_DIR": str(staging)}),
                        patch.object(icon_cache.os, "replace", side_effect=replace),
                    ):
                        result = update_icons.build_icon_cache(archive, ["apple"], target, {}, block_item_ids=set())
                    self.assertEqual(result["mapped_items"], 1)
                    return subprocess.CompletedProcess(command, 0, "done")

                with patch.object(update_script_runner, "_run_update", side_effect=run_build):
                    self.assertEqual(update_script_runner.run_update_icons(ROOT, config), (0, "done"))

                self.assertEqual(observed["copy_fallback"], copy_publish)
                self.assertFalse(observed["staging"].exists())
                self.assertTrue((target / "textures/items/apple.png").is_file())
                self.assertFalse(list(target.parent.glob(".vanilla.staging-*")))
                self.assertFalse(list(target.parent.glob(".vanilla.rollback-*")))

    def test_invalid_app_staging_is_rejected_without_changing_existing_files(self):
        before = self._existing_cache()
        archive = self.root / "good.zip"
        outside = self.root / "outside/.vanilla.staging-fixture"
        outside.mkdir(parents=True)
        occupied = self.root / ".vanilla.staging-occupied"
        occupied.mkdir()
        (occupied / "keep.txt").write_bytes(b"keep")
        wrong_name = self.root / "unrelated"
        wrong_name.mkdir()
        regular_file = self.root / ".vanilla.staging-file"
        regular_file.write_bytes(b"keep file")
        candidates = [outside, occupied, wrong_name, regular_file, self.target, self.root / ".vanilla.staging-missing"]
        link = self.root / ".vanilla.staging-link"
        try:
            link.symlink_to(wrong_name, target_is_directory=True)
        except OSError:
            pass  # Some Windows environments cannot create unprivileged symlinks.
        else:
            candidates.append(link)

        for staging in candidates:
            with self.subTest(staging=staging.name), patch.dict(os.environ, {"MCBE_ICON_STAGING_DIR": str(staging)}):
                with self.assertRaisesRegex(ValueError, "eigener, leerer Ordner"):
                    update_icons.build_icon_cache(archive, ["apple"], self.target, {}, block_item_ids=set())
                self.assertEqual(before, _files(self.target))

        self.assertEqual((occupied / "keep.txt").read_bytes(), b"keep")
        self.assertEqual(regular_file.read_bytes(), b"keep file")
        self.assertTrue(wrong_name.is_dir())
        self.assertTrue(outside.is_dir())

    def test_frozen_worker_timeout_cleans_downloads_in_effective_cache_directory(self):
        config = self._config()
        config.update_cache_dir = None
        inherited_cache = self.root / "inherited-cache"
        observed = {}

        def frozen_worker(module, args, *, cwd, env, timeout):
            self.assertEqual(module, "scripts.update_icons")
            self.assertEqual(timeout, 300)
            directory = Path(env["MCBE_ICON_DOWNLOAD_TEMP_DIR"])
            self.assertEqual(directory.parent, inherited_cache)
            self.assertEqual(env["MCBE_UPDATE_CACHE_DIR"], str(inherited_cache))
            observed["directory"] = directory
            (directory / "frozen-download.part").write_bytes(b"incomplete")
            staging = Path(env["MCBE_ICON_STAGING_DIR"])
            observed["staging"] = staging
            (staging / "partial-icon.png").write_bytes(b"incomplete")
            raise subprocess.TimeoutExpired([module, *args], timeout)

        with (
            patch.dict(os.environ, {"MCBE_UPDATE_CACHE_DIR": str(inherited_cache)}),
            patch.object(sys, "frozen", True, create=True),
            patch("mcbe_editor.desktop_worker.run_frozen_update", side_effect=frozen_worker),
            self.assertRaises(subprocess.TimeoutExpired),
        ):
            update_script_runner.run_update_icons(ROOT, config)

        self.assertFalse(observed["directory"].exists())
        self.assertFalse(observed["staging"].exists())


if __name__ == "__main__":
    unittest.main()
