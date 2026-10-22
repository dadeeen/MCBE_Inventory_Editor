from __future__ import annotations

import hashlib
import json
import stat
import warnings
import zipfile

import pytest

from scripts.release_check import check_archive
from scripts.runtime_layout import REQUIRED_RUNTIME_FILES


def write_archive(path, *, extra_files=None, extra_members=(), member_modes=None, duplicate_manifest_entry=False, manifest_alias=None, manifest_override=None):
    """Construct ZIPs independently of the release builder and manifest writer."""
    files = {name: b"runtime" for name in REQUIRED_RUNTIME_FILES}
    files.update(extra_files or {})
    entries = [{"path": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()} for name, data in sorted(files.items())]
    if duplicate_manifest_entry:
        entries.append(dict(entries[0]))
    if manifest_alias is not None:
        entries.append({**next(entry for entry in entries if entry["path"] == "static/app.js"), "path": manifest_alias})
    digest = hashlib.sha256()
    for entry in sorted(entries, key=lambda item: item["path"]):
        digest.update(f"{entry['path']}\0{entry['sha256']}\0{entry['size']}\n".encode())
    manifest = {
        "format": "mcbe-inventory-editor-release-manifest",
        "files": entries,
        "content_sha256": digest.hexdigest(),
    }
    if manifest_override is not None:
        manifest = manifest_override
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(path, "w") as archive:
            for name, data in files.items():
                member = zipfile.ZipInfo(f"pkg/{name}")
                if name in (member_modes or {}):
                    member.create_system = 3
                    member.external_attr = member_modes[name] << 16
                archive.writestr(member, data)
            archive.writestr("pkg/RELEASE_MANIFEST.json", json.dumps(manifest))
            for info, data in extra_members:
                archive.writestr(info, data)


def test_release_check_accepts_an_independently_constructed_valid_archive(tmp_path):
    archive = tmp_path / "valid.zip"
    write_archive(archive)
    assert check_archive(str(archive)) == 0


@pytest.mark.parametrize(
    "name",
    [
        "pkg/static/app.js",  # Duplicate physical member.
        "pkg/static//app.js",  # Alias after path normalization.
        "pkg/static/./app.js",
        "pkg/../outside/",  # Unsafe directory entries matter as well.
        "pkg/static/../../outside/",
    ],
)
def test_release_check_rejects_duplicate_and_noncanonical_zip_members(tmp_path, name):
    archive = tmp_path / "ambiguous.zip"
    write_archive(archive, extra_members=[(name, b"runtime" if not name.endswith("/") else b"")])
    assert check_archive(str(archive)) == 1


@pytest.mark.parametrize(
    "name",
    [
        "static/App.js",
        "static/..\\..\\outside.py",
        "static/secret:stream",
        "static/trailing.",
        "static/NUL",
        "static/con.txt",
        "static/AUX .json",
        "static/COM1/asset.js",
        "static/LPT².txt",
        "static/CONOUT$",
    ],
)
def test_release_check_rejects_windows_aliases_and_unsafe_paths(tmp_path, name):
    archive = tmp_path / "windows-ambiguous.zip"
    write_archive(archive, extra_files={name: b"runtime"})
    assert check_archive(str(archive)) == 1


def test_release_check_rejects_physical_names_truncated_by_zipfile(tmp_path):
    original = tmp_path / "original.zip"
    write_archive(original, extra_files={"static/asset.js": b"runtime"})
    malformed = tmp_path / "nul-member.zip"
    with zipfile.ZipFile(original) as source, zipfile.ZipFile(malformed, "w") as target:
        for info in source.infolist():
            data = source.read(info)
            if info.filename == "pkg/static/asset.js":
                # ZipInfo's constructor strips NULs. Assign afterwards so both
                # physical ZIP headers contain the malformed name independently
                # of the release validator and the manifest builder.
                info.filename += "\0hidden"
            target.writestr(info, data)
    with zipfile.ZipFile(malformed) as archive:
        member = archive.getinfo("pkg/static/asset.js")
        assert member.orig_filename == "pkg/static/asset.js\0hidden"
    assert check_archive(str(malformed)) == 1


@pytest.mark.parametrize("mode", [stat.S_IFLNK | 0o777, stat.S_IFIFO | 0o600])
def test_release_check_rejects_non_regular_zip_members(tmp_path, mode):
    archive = tmp_path / "special-member.zip"
    write_archive(archive, extra_files={"static/link.js": b"runtime"}, member_modes={"static/link.js": mode})
    assert check_archive(str(archive)) == 1


def test_release_check_rejects_duplicate_manifest_paths(tmp_path):
    archive = tmp_path / "duplicate-manifest-entry.zip"
    write_archive(archive, duplicate_manifest_entry=True)
    assert check_archive(str(archive)) == 1


@pytest.mark.parametrize("alias", ["./static/app.js", "static//app.js", "static/./app.js"])
def test_release_check_rejects_manifest_aliases_for_canonical_zip_members(tmp_path, alias):
    archive = tmp_path / "alias-manifest-entry.zip"
    write_archive(archive, manifest_alias=alias)
    assert check_archive(str(archive)) == 1


@pytest.mark.parametrize("manifest", [[], {"format": "mcbe-inventory-editor-release-manifest", "files": ["bad"]}])
def test_release_check_reports_malformed_manifest_as_failure(tmp_path, manifest):
    archive = tmp_path / "bad-manifest.zip"
    write_archive(archive, manifest_override=manifest)
    assert check_archive(str(archive)) == 1


@pytest.mark.parametrize(
    "relative",
    [
        "mcbe_editor/service.log.1",
        "static/diagnostic.JSONL.2026",
        "templates/.ENV.local",
        "mcbe_editor/SETTINGS.JSON",
        "static/world_BACKUPS/player.bin",
        "mcbe_editor/DATA/player.bin",
    ],
)
def test_release_gate_and_builder_exclude_rotated_logs_and_case_variant_state(tmp_path, relative):
    from scripts.make_release_zip import ROOT, should_include

    archive = tmp_path / "private-state.zip"
    write_archive(archive, extra_files={relative: b"SYNTHETIC_PRIVATE_MARKER"})
    assert check_archive(str(archive)) == 1
    assert should_include(ROOT / relative) is False
