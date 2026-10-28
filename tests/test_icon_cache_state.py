"""Synthetic end-to-end coverage of build reuse, migration and local repair."""

import io
import errno
import json
import os
import struct
import zipfile
import zlib
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from mcbe_editor import icon_cache_state as state
from mcbe_editor.block_icon_renderer import encode_rgba_png
from scripts import update_icons as updater


@pytest.fixture
def installed(tmp_path, monkeypatch):
    cache = tmp_path / "downloads"
    cache.mkdir()
    archive = cache / "bedrock-samples-v1.26.50.4.zip"
    png = encode_rgba_png(16, 16, bytes((30, 80, 50, 255)) * 256)
    with zipfile.ZipFile(archive, "w") as pack:
        for name in ("apple", "stick"):
            pack.writestr(f"resource_pack/textures/items/{name}.png", png)
    info = {
        "resource_pack_release": "v1.26.50.4",
        "resource_pack_asset": archive.name,
        "resource_pack_asset_size": archive.stat().st_size,
        "resource_pack_url": "https://github.com/Mojang/bedrock-samples/releases/download/v1.26.50.4/" + archive.name,
        "resource_pack_asset_id": 123,
        "resource_pack_asset_digest": "sha256:" + state.file_digest(archive),
    }
    root = tmp_path / "icons"
    db = tmp_path / "items.json"
    db.write_text(json.dumps({"items": {"minecraft:apple": ["Apfel", "Apple"]}, "block_items": []}), encoding="utf-8")
    monkeypatch.setattr(updater, "ICON_ROOT", root)
    monkeypatch.setattr(updater, "ITEM_DB_PATH", db)
    monkeypatch.setattr(updater, "CACHE_DIR", cache)
    monkeypatch.setattr(updater, "RELEASE_METADATA_PATH", cache / "source.json")
    monkeypatch.setattr(updater, "EXTRA_ITEM_ICON_IDS", set())
    monkeypatch.setattr(updater, "get_latest_full_release_info", lambda: info.copy())
    updater.write_release_metadata(info)
    updater.build_icon_cache(archive, ["apple"], root, info, block_item_ids=set())
    download_impl = updater.download_release_zip
    download = Mock(side_effect=AssertionError("No download was authorized or needed"))
    monkeypatch.setattr(updater, "download_release_zip", download)
    return SimpleNamespace(root=root, db=db, archive=archive, info=info, download=download, download_impl=download_impl, cache=cache)


def snapshot(root):
    return {str(path.relative_to(root)): (path.read_bytes(), path.stat().st_mtime_ns, path.stat().st_ino) for path in root.rglob("*") if path.is_file()}


def run(capsys, *args):
    assert updater.main(list(args)) == 0
    _, report = state.extract_report(capsys.readouterr().out)
    assert report is not None
    return report


@pytest.mark.parametrize("args", [(), ("--dry-run",), ("--no-download",)])
def test_current_cache_does_not_rebuild_download_or_write_even_without_archive(installed, monkeypatch, capsys, args):
    before = snapshot(installed.root)
    installed.archive.unlink()
    build = Mock(side_effect=AssertionError("An unchanged cache must not be rebuilt"))
    monkeypatch.setattr(updater, "build_icon_cache", build)
    report = run(capsys, *args)
    assert report["already_current"] and not report["needs_update"] and not report["images_changed"]
    assert snapshot(installed.root) == before
    installed.download.assert_not_called()
    build.assert_not_called()


def test_catalog_labels_editor_metadata_and_unrelated_blocks_do_not_invalidate_icons(installed, capsys):
    installed.db.write_text(
        json.dumps(
            {
                "items": {"minecraft:apple": ["Name geändert", "Renamed"]},
                "effects": {"38": "Freezing"},
                "block_items": ["minecraft:unrelated_block"],
            }
        ),
        encoding="utf-8",
    )
    installed.info.update(fetched_at="irrelevant", editor_version="future")
    before = snapshot(installed.root)
    assert run(capsys)["already_current"]
    assert snapshot(installed.root) == before


@pytest.mark.parametrize("change", ["target", "block", "contract"])
def test_changed_build_inputs_need_only_the_valid_local_archive(installed, monkeypatch, capsys, change):
    data = json.loads(installed.db.read_text(encoding="utf-8"))
    if change == "target":
        data["items"]["minecraft:stick"] = []
    elif change == "block":
        data["block_items"] = ["minecraft:apple"]
    else:
        monkeypatch.setattr(state, "BUILD_CONTRACT", state.BUILD_CONTRACT + 1)
    installed.db.write_text(json.dumps(data), encoding="utf-8")
    before = snapshot(installed.root)
    preview = run(capsys, "--dry-run")
    assert preview["needs_update"] and preview["update_kind"] == "local" and preview["state"] == "stale"
    assert snapshot(installed.root) == before
    run(capsys, "--no-download")
    assert run(capsys, "--dry-run")["already_current"]
    installed.download.assert_not_called()
    if change == "target":
        assert (installed.root / "textures/items/stick.png").exists()


@pytest.mark.parametrize("damage", ["missing", "empty", "changed"])
def test_damaged_images_are_repaired_locally_even_at_same_release(installed, capsys, damage):
    path = installed.root / "textures/items/apple.png"
    original = path.read_bytes()
    if damage == "missing":
        path.unlink()
    elif damage == "empty":
        path.write_bytes(b"")
    else:
        path.write_bytes(bytes([original[0] ^ 1]) + original[1:])
    preview = run(capsys, "--dry-run")
    assert preview["state"] == "damaged" and preview["update_kind"] == "local"
    assert run(capsys, "--no-download")["images_changed"]
    assert path.read_bytes() == original
    assert run(capsys)["already_current"]


def make_legacy(root):
    manifest = state.read_manifest(root)
    manifest.pop("verification")
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_legacy_cache_adopts_verification_without_replacing_identical_images(installed, capsys):
    make_legacy(installed.root)
    before = snapshot(installed.root)
    preview = run(capsys, "--dry-run")
    assert preview["reason"] == "legacy" and preview["update_kind"] == "local"
    assert snapshot(installed.root) == before
    report = run(capsys, "--no-download")
    assert report["already_current"] and report["metadata_updated"] and not report["images_changed"]
    after = snapshot(installed.root)
    assert {k: v for k, v in before.items() if k != "manifest.json"} == {k: v for k, v in after.items() if k != "manifest.json"}
    assert "verification" in state.read_manifest(installed.root)
    assert run(capsys)["already_current"]
    installed.download.assert_not_called()


@pytest.mark.parametrize("args", [("--dry-run",), ("--no-download",)])
def test_legacy_without_archive_remains_usable_and_does_not_download(installed, capsys, args):
    make_legacy(installed.root)
    installed.archive.unlink()
    before = snapshot(installed.root)
    report = run(capsys, *args)
    assert report["needs_update"] and report["check_only"] and report["update_kind"] == "download"
    assert report["source_unchanged"] and report["reason"] == "legacy"
    assert snapshot(installed.root) == before
    installed.download.assert_not_called()


@pytest.mark.parametrize("change", ["release", "asset_id", "digest"])
def test_changed_source_requires_new_archive_without_mutating_existing_icons(installed, capsys, change):
    if change == "release":
        installed.info["resource_pack_release"] = "v1.26.60.6"
    elif change == "asset_id":
        installed.info["resource_pack_asset_id"] += 1
    else:
        installed.info["resource_pack_asset_digest"] = "sha256:" + "0" * 64
    before = snapshot(installed.root)
    report = run(capsys, "--no-download")
    assert report["needs_update"] and report["update_kind"] == "download"
    assert snapshot(installed.root) == before
    installed.download.assert_not_called()


def test_known_missing_source_textures_do_not_create_an_endless_update(installed, capsys):
    installed.db.write_text(json.dumps({"items": {"minecraft:apple": [], "minecraft:missing_texture": []}}), encoding="utf-8")
    run(capsys, "--no-download")
    assert "minecraft:missing_texture" in state.read_manifest(installed.root)["missing_items"]
    assert run(capsys)["already_current"]


def test_corrupt_local_archive_does_not_get_used_for_repair(installed, capsys):
    make_legacy(installed.root)
    before = snapshot(installed.root)
    raw = installed.archive.read_bytes()
    installed.archive.write_bytes(b"bad" + raw[3:])
    report = run(capsys, "--no-download")
    assert report["update_kind"] == "download" and report["check_only"]
    assert snapshot(installed.root) == before


@pytest.fixture
def damaged_legacy_deflate(installed):
    """A structurally intact legacy ZIP with a reserved DEFLATE block type."""
    with zipfile.ZipFile(installed.archive) as archive:
        members = [(entry.filename, archive.read(entry)) for entry in archive.infolist()]
    with zipfile.ZipFile(installed.archive, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, raw in members:
            archive.writestr(name, raw)
    healthy = installed.archive.read_bytes()
    damaged = bytearray(healthy)
    name_size, extra_size = struct.unpack_from("<HH", damaged, 26)
    start = 30 + name_size + extra_size
    damaged[start] = (damaged[start] & ~6) | 6
    installed.archive.write_bytes(damaged)
    # Older releases/receipts have no upstream or locally verified digest.
    installed.info.pop("resource_pack_asset_digest")
    installed.info["resource_pack_asset_size"] = len(healthy)
    manifest = state.read_manifest(installed.root)
    manifest.pop("verification")
    manifest["release"] = installed.info.copy()
    (installed.root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    updater.write_release_metadata(installed.info)
    return installed, healthy


def test_zip_decoder_failure_is_normalized_at_archive_validation(damaged_legacy_deflate):
    installed, _ = damaged_legacy_deflate
    with pytest.raises(RuntimeError, match="keine gültige ZIP-Datei") as error:
        updater.validate_icon_archive(installed.archive, installed.info)
    assert isinstance(error.value.__cause__, zlib.error)


@pytest.mark.parametrize("error_type", updater.ZIP_READ_ERRORS)
def test_all_supported_zip_decoder_errors_use_the_update_error_contract(installed, monkeypatch, error_type):
    error = error_type("synthetic decoder failure")

    def fail(_archive):
        raise error

    monkeypatch.setattr(zipfile.ZipFile, "testzip", fail)
    with pytest.raises(RuntimeError) as caught:
        updater._validate_downloaded_zip(installed.archive)
    assert caught.value is error or caught.value.__cause__ is error


@pytest.mark.parametrize("args", [("--dry-run",), ("--no-download",)])
def test_legacy_deflate_damage_plans_download_without_writing(damaged_legacy_deflate, capsys, args):
    installed, _ = damaged_legacy_deflate
    before = snapshot(installed.root.parent)
    report = run(capsys, *args)
    assert report["check_only"] and report["needs_update"] and report["update_kind"] == "download"
    assert snapshot(installed.root.parent) == before
    installed.download.assert_not_called()


def test_legacy_deflate_damage_is_replaced_by_valid_download_and_reused(damaged_legacy_deflate, monkeypatch, capsys):
    installed, healthy = damaged_legacy_deflate
    before = snapshot(installed.root)

    class Response(io.BytesIO):
        url = installed.info["resource_pack_url"]

    download = Mock(side_effect=lambda *_args, **_kwargs: Response(healthy))
    monkeypatch.setattr(updater, "_build_validating_opener", lambda *_args, **_kwargs: SimpleNamespace(open=download))
    monkeypatch.setattr(updater, "download_release_zip", installed.download_impl)
    report = run(capsys, "--cache")
    download.assert_called_once()
    assert installed.archive.read_bytes() == healthy
    assert report["already_current"] and report["metadata_updated"] and not report["images_changed"]
    after = snapshot(installed.root)
    assert {k: v for k, v in before.items() if k != "manifest.json"} == {k: v for k, v in after.items() if k != "manifest.json"}
    assert run(capsys, "--cache")["already_current"]
    download.assert_called_once()


def test_release_change_between_check_and_local_apply_never_downloads(installed, capsys):
    make_legacy(installed.root)
    assert run(capsys, "--dry-run")["update_kind"] == "local"
    before = snapshot(installed.root)
    installed.info["resource_pack_asset_id"] += 1
    assert run(capsys, "--no-download")["update_kind"] == "download"
    assert snapshot(installed.root) == before
    installed.download.assert_not_called()


@pytest.mark.parametrize("damage", ["manifest", "receipt", "traversal", "linked", "oversized"])
def test_invalid_verification_and_unsafe_files_are_never_current(installed, monkeypatch, damage):
    manifest = state.read_manifest(installed.root)
    inputs = updater.icon_build_inputs(installed.info, ["apple"], set())
    if damage == "manifest":
        manifest["items"]["minecraft:apple"] = "wrong/mapping"
    elif damage == "receipt":
        manifest["verification"]["files"] = {}
    elif damage == "traversal":
        manifest["items"] = {"minecraft:../outside": "items/apple"}
        with pytest.raises(ValueError):
            state.image_hashes(installed.root, manifest)
    elif damage == "oversized":
        monkeypatch.setattr(state, "MAX_ICON_BYTES", 1)
    else:
        path = installed.root / "textures/items/apple.png"
        original = path.with_name("original.png")
        path.rename(original)
        try:
            path.symlink_to(original)
        except OSError:
            pytest.skip("Symlinks are unavailable on this host")
    (installed.root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert state.assess_cache(installed.root, inputs)["state"] != "current"


@pytest.mark.parametrize("restore_timestamp", [False, True])
def test_hash_detects_same_size_content_change(installed, restore_timestamp):
    path = installed.root / "textures/items/apple.png"
    first = state.file_digest(path)
    original = path.read_bytes()
    before = path.stat()
    path.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + (0 if restore_timestamp else 1_000_000)))
    assert state.file_digest(path) != first


def test_status_and_updater_detect_damage_after_timestamp_preserving_restore(installed, capsys):
    from mcbe_editor import icon_api_routes as routes

    index = {"count": 1, "sources": [{"vanilla": True, "enabled": True, "exists": True, "path": str(installed.root)}]}
    deps = SimpleNamespace(item_db_path=str(installed.db))
    assert routes._with_vanilla_status(index, deps)["vanilla_cache"]["state"] == "current"
    image = installed.root / "textures/items/apple.png"
    before = image.stat()
    raw = image.read_bytes()
    image.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
    os.utime(image, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert routes._with_vanilla_status(index, deps)["vanilla_cache"]["state"] == "damaged"
    assert run(capsys, "--dry-run")["state"] == "damaged"
    assert run(capsys, "--no-download")["state"] == "current"
    assert image.read_bytes() == raw
    assert routes._with_vanilla_status(index, deps)["vanilla_cache"]["state"] == "current"


def test_unknown_and_empty_block_classifications_cannot_share_a_build_receipt(installed):
    with zipfile.ZipFile(installed.archive, "w") as archive:
        archive.writestr("resource_pack/textures/blocks/brick.png", encode_rgba_png(16, 16, bytes((30, 80, 50, 255)) * 256))
    unknown = updater.build_icon_cache(installed.archive, ["brick"], installed.root, installed.info, block_item_ids=None)
    explicit_root = installed.root.with_name("explicit")
    explicit = updater.build_icon_cache(installed.archive, ["brick"], explicit_root, installed.info, block_item_ids=set())
    assert unknown["items"] == {"minecraft:brick": "blocks/brick"}
    assert explicit["items"] == {}
    assert unknown["verification"]["inputs"] != explicit["verification"]["inputs"]
    assert state.assess_cache(installed.root, updater.icon_build_inputs(installed.info, ["brick"], set()))["state"] == "stale"
    assert state.assess_cache(explicit_root, updater.icon_build_inputs(installed.info, ["brick"], set()))["state"] == "current"


def test_previous_build_contract_is_reverified_without_replacing_images(installed, capsys):
    manifest = state.read_manifest(installed.root)
    receipt = manifest["verification"]
    receipt["inputs"]["contract"] = 1
    receipt["inputs_sha256"] = state.digest(receipt["inputs"])
    (installed.root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    before = snapshot(installed.root)
    assert run(capsys, "--dry-run")["state"] == "stale"
    report = run(capsys, "--no-download")
    assert report["already_current"] and report["state"] == "current"
    after = snapshot(installed.root)
    assert {k: v for k, v in before.items() if k != "manifest.json"} == {k: v for k, v in after.items() if k != "manifest.json"}


@pytest.mark.parametrize("phase", ["before_build", "during_build"])
def test_archive_change_before_publication_keeps_installed_images(installed, monkeypatch, capsys, phase):
    make_legacy(installed.root)
    before = snapshot(installed.root)

    def change_archive():
        stamp = installed.archive.stat()
        raw = installed.archive.read_bytes()
        installed.archive.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
        os.utime(installed.archive, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))

    if phase == "before_build":
        build = updater.build_icon_cache

        def changed_build(*args, **kwargs):
            change_archive()
            return build(*args, **kwargs)

        monkeypatch.setattr(updater, "build_icon_cache", changed_build)
    else:
        progress = updater.report_progress

        def changed_progress(stage, **kwargs):
            if stage == "finalizing":
                change_archive()
            return progress(stage, **kwargs)

        monkeypatch.setattr(updater, "report_progress", changed_progress)
    with pytest.raises(ValueError, match="während der Verarbeitung verändert"):
        run(capsys, "--no-download")
    assert snapshot(installed.root) == before
    installed.download.assert_not_called()


@pytest.mark.parametrize("failed_read", ["manifest", "image"])
def test_unreadable_cache_is_not_reported_as_missing_or_current(installed, monkeypatch, failed_read):
    read = state._stamp
    denied = installed.root / ("manifest.json" if failed_read == "manifest" else "textures/items/apple.png")

    def denied_read(path):
        if path == denied:
            raise PermissionError(errno.EACCES, "Permission denied", str(path))
        return read(path)

    monkeypatch.setattr(state, "_stamp", denied_read)
    with pytest.raises(PermissionError):
        state.assess_cache(installed.root, updater.icon_build_inputs(installed.info, ["apple"], set()))


def test_report_parser_does_not_expose_machine_record():
    raw = "visible\n" + state.REPORT_PREFIX + '{"schema":1,"already_current":true}\n'
    output, report = state.extract_report(raw)
    assert output == "visible\n" and report["already_current"]


def test_download_checksum_failure_keeps_previous_archive_and_icons(tmp_path, monkeypatch):
    archive = tmp_path / "bedrock-samples-test.zip"
    archive.write_bytes(b"previous archive")
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as pack:
        pack.writestr("synthetic.txt", "synthetic source")
    raw = payload.getvalue()
    info = {
        "resource_pack_asset": archive.name,
        "resource_pack_asset_size": len(raw),
        "resource_pack_url": "https://github.com/Mojang/bedrock-samples/releases/download/test/test.zip",
        "resource_pack_asset_digest": "sha256:" + "0" * 64,
    }

    class Response(io.BytesIO):
        url = info["resource_pack_url"]

    monkeypatch.setattr(updater, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(updater, "_build_validating_opener", lambda *_args, **_kwargs: SimpleNamespace(open=lambda *_a, **_k: Response(raw)))
    with pytest.raises(RuntimeError, match="Prüfsumme"):
        updater.download_release_zip(info, use_cache=False)
    assert archive.read_bytes() == b"previous archive"
    assert not list(tmp_path.glob("*.part"))


@pytest.mark.parametrize("status", ["current", "available", "updated", "invalid"])
def test_api_distinguishes_checks_from_committed_changes(installed, monkeypatch, status):
    from mcbe_editor import icon_api_routes as routes

    report = {
        "schema": 1,
        "status": status,
        "already_current": status == "current",
        "needs_update": status == "available",
        "check_only": status != "updated",
        "images_changed": status == "updated",
    }
    output = "visible\n" + (state.REPORT_PREFIX + json.dumps(report) if status != "invalid" else "")
    deps = SimpleNamespace(
        data_root=str(installed.root.parent),
        settings_path=str(installed.root.parent / "sources.json"),
        get_icon_index=lambda: {},
        json_bool=lambda data, key, default: data.get(key, default),
        run_update_icons=Mock(return_value=(0, output)),
        looks_like_network_failure=lambda _output: False,
        audit_event=Mock(),
        jsonify=lambda value: value,
        api_error=lambda message, status=400: ({"error": message}, status),
        log_api_exception=Mock(),
    )
    scan = Mock(return_value={"success": True, "count": 1, "icons": {}})
    clear = Mock()
    monkeypatch.setattr(routes, "_scan_and_store_icons", scan)
    monkeypatch.setattr(routes, "clear_icon_cache", clear)
    result = routes.icons_vanilla_update({"check_only": status != "updated", "allow_download": False}, deps)
    assert result["success"] == (status != "invalid")
    assert result.get("update_committed", False) == (status == "updated")
    assert state.REPORT_PREFIX not in result["output"]
    assert deps.run_update_icons.call_args.kwargs["allow_download"] is False
    if status in {"current", "updated"}:
        assert scan.call_args.kwargs["force"] == (status == "updated")
        assert clear.call_count == (status == "updated")
    else:
        scan.assert_not_called()
        clear.assert_not_called()
    deps.audit_event.assert_called_once()


def test_local_status_separates_known_source_gaps_and_damage(installed):
    from mcbe_editor import icon_api_routes as routes

    index = {"count": 1, "icons": {}, "sources": [{"vanilla": True, "enabled": True, "exists": True, "path": str(installed.root)}]}
    deps = SimpleNamespace(item_db_path=str(installed.db), log_api_exception=Mock())
    result = routes._with_vanilla_status(index, deps)
    assert result["vanilla_cache"]["state"] == "current"
    assert routes._public_icon_index(result)["missing_banner_patterns"] == []
    assert result["unsupported_banner_patterns"]
    (installed.root / "textures/items/apple.png").unlink()
    damaged = routes._with_vanilla_status(result, deps)
    assert damaged["vanilla_cache"]["state"] == "damaged"
    assert "unsupported_banner_patterns" not in damaged
    assert "vanilla_cache" not in index


def test_legacy_status_is_read_only_and_does_not_mandate_a_rebuild(installed):
    from mcbe_editor import icon_api_routes as routes

    make_legacy(installed.root)
    before = snapshot(installed.root)
    index = {"count": 1, "sources": [{"vanilla": True, "enabled": True, "exists": True, "path": str(installed.root)}]}
    deps = SimpleNamespace(item_db_path=str(installed.db), log_api_exception=Mock())
    assert routes._with_vanilla_status(index, deps)["vanilla_cache"] == {"state": "unverified", "reason": "legacy"}
    assert snapshot(installed.root) == before
    installed.download.assert_not_called()
