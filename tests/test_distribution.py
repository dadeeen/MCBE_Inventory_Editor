from __future__ import annotations

import json
import re
import zipfile
from pathlib import PurePath

from mcbe_editor.distribution import build_manifest, data_root_snapshot, distribution_snapshot, release_manifest_hash, write_tree_manifest
from scripts.release_check import check_archive
from scripts.runtime_layout import REQUIRED_RUNTIME_FILES


def _minimal_runtime_files() -> dict[str, bytes]:
    files = {name: b"" for name in REQUIRED_RUNTIME_FILES}
    files.update(
        {
            "README.md": b"readme",
            "SECURITY.md": b"security",
            "LICENSE": b"license",
            "pyproject.toml": b"[project]\nversion='1.2.3'\n",
            "mcbe_editor/resources/item_db.json": b"{}",
        }
    )
    return files


def _write_minimal_release_archive(path, *, extra_files: dict[str, bytes] | None = None, outside_root: dict[str, bytes] | None = None) -> None:
    import hashlib

    root_name = "pkg"
    files = {**_minimal_runtime_files(), **(extra_files or {})}
    entries = [{"path": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()} for name, data in files.items()]
    manifest = build_manifest(project_version="1.2.3", files=entries)
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in files.items():
            zf.writestr(f"{root_name}/{name}", data)
        zf.writestr(f"{root_name}/RELEASE_MANIFEST.json", json.dumps(manifest))
        for name, data in (outside_root or {}).items():
            zf.writestr(name, data)


def test_distribution_snapshot_reports_source_tree():
    snap = distribution_snapshot()

    assert snap["kind"] in {"source", "release", "release-dirty"}
    assert snap["app_root"]
    if snap["kind"] == "source":
        assert snap["release_manifest_present"] is False
    if snap["kind"] == "release-dirty":
        assert snap["release_manifest_present"] is True
        assert snap["manifest_status"]["status"] == "dirty"


def test_data_root_snapshot_reports_portable_and_writable(tmp_path):
    status = data_root_snapshot(str(tmp_path / "data"))

    assert status["configured"] is True
    assert status["exists"] is True
    assert status["writable"] is True
    assert isinstance(status["known_entries"], list)


def test_release_manifest_hash_is_stable():
    files = [
        {"path": "b.txt", "size": 2, "sha256": "b" * 64},
        {"path": "a.txt", "size": 1, "sha256": "a" * 64},
    ]

    assert release_manifest_hash(files) == release_manifest_hash(list(reversed(files)))
    manifest = build_manifest(project_version="1.2.3", files=files)
    assert manifest["format"] == "mcbe-inventory-editor-release-manifest"
    assert manifest["project_version"] == "1.2.3"
    assert manifest["content_sha256"] == release_manifest_hash(files)


def test_tree_manifest_covers_exact_staged_runtime_tree(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.2.3"\n', encoding="utf-8")
    (tmp_path / "main.py").write_text("print('ok')\n", encoding="utf-8")

    output = write_tree_manifest(tmp_path, created_by="test")

    manifest = json.loads(output.read_text(encoding="utf-8"))
    assert manifest["project_version"] == "1.2.3"
    assert manifest["created_by"] == "test"
    assert [entry["path"] for entry in manifest["files"]] == ["main.py", "pyproject.toml"]


def test_release_check_validates_manifest_hashes(tmp_path):
    archive = tmp_path / "release.zip"
    _write_minimal_release_archive(archive)

    assert check_archive(str(archive)) == 0


def test_release_builder_uses_stable_root_and_excludes_coverage_artifacts(tmp_path):
    import subprocess
    import sys

    from scripts.make_release_zip import ARCHIVE_ROOT, ROOT, should_include
    from scripts.runtime_layout import iter_runtime_files

    assert ARCHIVE_ROOT == "mcbe_inventory_editor"
    assert should_include(ROOT / ".coverage") is False
    assert should_include(ROOT / ".coverage.local") is False
    assert should_include(ROOT / "coverage.xml") is False
    assert should_include(ROOT / ".tmp" / "local-artifact") is False
    assert should_include(ROOT / "mcbe_editor" / ".pytest-local" / "private.json") is False
    assert should_include(ROOT / "node_modules" / "playwright" / "index.js") is False
    assert should_include(ROOT / "test-results" / ".last-run.json") is False
    assert should_include(ROOT / "diagnostics" / "horse" / "private.json") is False
    assert should_include(ROOT / ".playwright-cli" / "page.yml") is False
    assert should_include(ROOT / ".claude" / "launch.json") is False
    assert should_include(ROOT / ".agents" / "notes.md") is False
    assert should_include(ROOT / ".codex" / "state.json") is False
    assert should_include(ROOT / "playwright-report" / "index.html") is False
    assert should_include(ROOT / "server.log") is False
    assert should_include(ROOT / "audit.jsonl") is False
    assert should_include(ROOT / ".env") is False
    assert should_include(ROOT / ".env.local") is False
    assert should_include(ROOT / ".env.example") is False
    assert should_include(ROOT / ".world_restoring_2026") is False
    assert should_include(ROOT / ".world_rollback_2026") is False
    assert should_include(ROOT / "data" / "settings.json") is False
    assert should_include(ROOT / "tests" / "data" / "camel_actor_record.hex") is False
    assert should_include(ROOT / ".github" / "workflows" / "ci.yml") is False
    assert should_include(ROOT / "package-lock.json") is False
    assert should_include(ROOT / "docs" / "development.md") is False
    assert should_include(ROOT / "docs" / "save_contract.md") is False
    assert should_include(ROOT / "docs" / "experimental_mount_creation_status.md") is False
    assert should_include(ROOT / "docs" / "assets" / "editor-overview.png") is True
    assert should_include(ROOT / "docs" / "assets" / "editor-inventory.png") is True
    assert should_include(ROOT / "scripts" / "make_release_zip.py") is False
    assert should_include(ROOT / "item_db.json") is False
    assert should_include(ROOT / "main.py") is True
    assert should_include(ROOT / "mcbe_editor" / "config.py") is True
    assert should_include(ROOT / "mcbe_editor" / "resources" / "item_db.json") is True
    assert should_include(ROOT / "mcbe_editor" / "resources" / "item_availability.json") is True
    assert should_include(ROOT / "static" / "app.js") is True
    assert should_include(ROOT / "templates" / "index.html") is True
    assert should_include(ROOT / "scripts" / "update_db.py") is True
    assert should_include(ROOT / "scripts" / "export_player_raws.py") is True

    archive = tmp_path / "release.zip"
    subprocess.run([sys.executable, "scripts/make_release_zip.py", "--output", str(archive)], cwd=ROOT, check=True)
    with zipfile.ZipFile(archive) as zf:
        names = [name for name in zf.namelist() if name and not name.endswith("/")]
    roots = {name.split("/", 1)[0] for name in names}
    assert roots == {"mcbe_inventory_editor"}
    assert not any(PurePath(name).name == ".coverage" or PurePath(name).name.startswith(".coverage.") for name in names)
    assert not any(PurePath(name).name == "coverage.xml" for name in names)
    assert not any(PurePath(name).name == ".env" or PurePath(name).name.startswith(".env.") for name in names)
    assert not any("/tests/" in f"/{name}" for name in names)
    assert not any("/.github/" in f"/{name}" for name in names)
    assert not any(name.endswith("package.json") or name.endswith("package-lock.json") for name in names)
    assert not any(name.endswith(("docs/development.md", "docs/save_contract.md", "docs/experimental_mount_creation_status.md")) for name in names)
    assert not any(name.endswith("scripts/make_release_zip.py") for name in names)
    relative_names = {name.split("/", 1)[1] for name in names if "/" in name}
    assert relative_names >= REQUIRED_RUNTIME_FILES

    enumerated_roots = {path.relative_to(ROOT).parts[0] for path in iter_runtime_files(ROOT)}
    assert enumerated_roots.isdisjoint({".tmp", ".venv", "node_modules", "tests"})


def test_runtime_file_iterator_never_enters_non_runtime_roots(tmp_path):
    from scripts.runtime_layout import iter_runtime_files

    (tmp_path / "main.py").write_text("print('runtime')\n", encoding="utf-8")
    (tmp_path / "static").mkdir()
    (tmp_path / "static" / "app.js").write_text("// runtime\n", encoding="utf-8")
    (tmp_path / ".tmp").mkdir()
    (tmp_path / ".tmp" / "private.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_private.py").write_text("PRIVATE = True\n", encoding="utf-8")

    relative_files = {path.relative_to(tmp_path).as_posix() for path in iter_runtime_files(tmp_path)}

    assert relative_files == {"main.py", "static/app.js"}


def test_runtime_markdown_links_only_target_shipped_files():
    from scripts.make_release_zip import ROOT, should_include
    from scripts.runtime_layout import iter_runtime_files

    for path in iter_runtime_files(ROOT):
        if path.suffix.casefold() != ".md" or not should_include(path):
            continue
        content = path.read_text(encoding="utf-8")
        for match in re.finditer(r"\[[^\]]+\]\(([^)]+)\)", content):
            target = match.group(1)
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            target_path = target.split("#", 1)[0]
            if not target_path:
                continue
            resolved = (path.parent / target_path).resolve()
            assert resolved.is_relative_to(ROOT), f"runtime Markdown link escapes project: {path} -> {target}"
            assert resolved.exists(), f"runtime Markdown link is missing: {path} -> {target}"
            assert should_include(resolved), f"runtime Markdown link is not shipped: {path} -> {target}"


def test_release_check_rejects_coverage_artifact(tmp_path):
    import hashlib

    from scripts.release_check import check_archive

    root_name = "pkg"
    files = {**_minimal_runtime_files(), ".coverage": b"sqlite coverage data"}
    entries = [{"path": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()} for name, data in files.items()]
    manifest = build_manifest(project_version="1.2.3", files=entries)
    archive = tmp_path / "bad_release.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for name, data in files.items():
            zf.writestr(f"{root_name}/{name}", data)
        zf.writestr(f"{root_name}/RELEASE_MANIFEST.json", json.dumps(manifest))

    assert check_archive(str(archive)) == 1


def test_release_check_rejects_env_file_and_restore_work_dir(tmp_path):
    import hashlib

    from scripts.release_check import check_archive

    root_name = "pkg"
    files = {
        **_minimal_runtime_files(),
        ".env.local": b"MCBE_SERVER_HOST=private",
        ".world_rollback_2026/level.dat": b"private",
    }
    entries = [{"path": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()} for name, data in files.items()]
    manifest = build_manifest(project_version="1.2.3", files=entries)
    archive = tmp_path / "bad_private_release.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for name, data in files.items():
            zf.writestr(f"{root_name}/{name}", data)
        zf.writestr(f"{root_name}/RELEASE_MANIFEST.json", json.dumps(manifest))

    assert check_archive(str(archive)) == 1


def test_release_check_rejects_node_modules_and_test_results(tmp_path):
    archive = tmp_path / "bad_frontend_artifacts.zip"
    _write_minimal_release_archive(
        archive,
        extra_files={
            "node_modules/pkg/index.js": b"module",
            "test-results/report.json": b"{}",
        },
    )

    assert check_archive(str(archive)) == 1


def test_release_check_rejects_private_tool_and_diagnostic_artifacts(tmp_path):
    archive = tmp_path / "bad_local_artifacts.zip"
    _write_minimal_release_archive(
        archive,
        extra_files={
            "diagnostics/horse/private.json": b"{}",
            ".playwright-cli/page.yml": b"page",
            ".claude/launch.json": b"{}",
            ".agents/notes.md": b"private",
            ".codex/state.json": b"{}",
            "mcbe_editor/.pytest-local/private.json": b"{}",
            "playwright-report/index.html": b"report",
            "server.log": b"local path",
        },
    )

    assert check_archive(str(archive)) == 1


def test_release_check_rejects_multi_root_runtime_data_bypass(tmp_path):
    archive = tmp_path / "bad_multi_root.zip"
    _write_minimal_release_archive(
        archive,
        extra_files={"data/audit/events.jsonl": b"private"},
        outside_root={"other-root.txt": b"force multiple roots"},
    )

    assert check_archive(str(archive)) == 1
