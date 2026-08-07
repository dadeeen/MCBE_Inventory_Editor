from __future__ import annotations

import ast
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_pytest_runtime_storage_is_isolated_from_the_repository(_isolated_runtime_storage: Path):
    from mcbe_editor.config import load_config

    config = load_config()
    isolated_root = _isolated_runtime_storage.resolve()
    pytest_options = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["pytest"]["ini_options"]

    assert Path(config.data_root).resolve() == isolated_root / "data"
    assert Path(config.backup_root).resolve() == isolated_root / "data" / "backups"
    assert ROOT.resolve() not in Path(config.backup_root).resolve().parents
    assert pytest_options["tmp_path_retention_count"] == 1
    assert pytest_options["tmp_path_retention_policy"] == "failed"


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_python_support_is_consistent_across_project_files():
    pyproject = _read("pyproject.toml")
    assert 'requires-python = ">=3.12,<3.13"' in pyproject

    setup = _read("setup.bat")
    assert "Python 3.12" in setup
    assert "Python 3.11, 3.13, and 3.14" in setup
    assert "EnableDelayedExpansion" in setup
    assert 'set "PYTHON_CMD=py -3.12"' in setup
    assert "!PYTHON_CMD! -m venv .venv" in setup

    workflow = _read(".github/workflows/ci.yml")
    assert 'python-version: "3.12"' in workflow
    assert "3.11" not in workflow
    assert "3.13" not in workflow
    assert "3.14" not in workflow

    readme = _read("README.md")
    security = _read("SECURITY.md")
    combined_docs = readme + "\n" + security
    assert "Python 3.11-3.14" not in combined_docs
    assert "Python 3.12" in readme
    assert "Python 3.12" in security


def test_docs_do_not_require_a_prerelease_changelog():
    readme = _read("README.md")
    development = _read("docs/development.md")

    assert not (ROOT / "CHANGELOG.md").exists()
    assert "CHANGELOG.md" not in readme
    assert "CHANGELOG.md" not in development


def test_public_docs_use_evergreen_release_links_and_an_unofficial_disclaimer():
    readme = _read("README.md")
    readme_de = _read("README.de.md")

    for source in (readme, readme_de):
        assert "https://github.com/dadeeen/MCBE_Inventory_Editor/releases" in source
        assert "_runtime.zip" in source
        assert ".sha256" in source
        assert "docs/assets/editor-overview.png" in source
        assert "docs/assets/editor-inventory.png" in source
        # Image references stay on the X.Y.Z placeholder so a release never
        # requires a documentation edit and can never leave a stale tag behind.
        assert "docker pull ghcr.io/dadeeen/mcbe-inventory-editor:X.Y.Z" in source
        assert "docker-compose.example.yml" in source
        assert re.search(r"mcbe-inventory-editor:\d", source) is None
    for asset in ("docs/assets/editor-overview.png", "docs/assets/editor-inventory.png"):
        assert (ROOT / asset).is_file()
        assert (ROOT / asset).stat().st_size > 0
    for source in (readme, readme_de):
        normalized = source.casefold()
        assert "mojang studios" in normalized
        assert "microsoft" in normalized
    assert "unofficial" in readme.casefold()
    assert "inoffiziell" in readme_de.casefold()


def test_security_policy_and_issue_forms_are_bilingual_and_version_neutral():
    security = _read("SECURITY.md")
    security_de = _read("SECURITY.de.md")
    issue_en = _read(".github/ISSUE_TEMPLATE/bug_report_en.yml")
    issue_de = _read(".github/ISSUE_TEMPLATE/bug_report_de.yml")
    issue_config = _read(".github/ISSUE_TEMPLATE/config.yml")

    assert "github.com/dadeeen/MCBE_Inventory_Editor/releases" in security
    assert "/security/advisories/new" in security
    assert re.search(r"\b(three|3) business days\b", security, flags=re.I)
    assert "github.com/dadeeen/MCBE_Inventory_Editor/releases" in security_de
    assert "/security/advisories/new" in security_de
    assert re.search(r"\b(drei|3) Arbeitstagen\b", security_de, flags=re.I)
    assert "name: Bug report (English)" in issue_en
    assert "name: Fehlerbericht (Deutsch)" in issue_de
    assert "vX.Y.Z or a commit hash" in issue_en
    assert "vX.Y.Z oder ein Commit-Hash" in issue_de
    assert "0.5.9" not in issue_en + issue_de
    assert "blank_issues_enabled: false" in issue_config
    assert "security/policy" in issue_config


def test_mount_documentation_uses_the_current_generic_name():
    development = _read("docs/development.md")
    runtime_layout = _read("scripts/runtime_layout.py")

    assert (ROOT / "docs" / "experimental_mount_creation_status.md").is_file()
    assert not (ROOT / "docs" / "experimental_horse_create_status.md").exists()
    assert "experimental_mount_creation_status.md" in development
    assert "docs/experimental_mount_creation_status.md" not in runtime_layout
    assert "experimental_horse_create_status.md" not in development + runtime_layout


def test_architecture_overview_matches_the_mount_module_boundary():
    architecture = _read("docs/architecture.md")
    development = _read("docs/development.md")
    routes = _read("mcbe_editor/mount_api_routes.py")
    placement = _read("mcbe_editor/mount_placement.py")
    pyproject = tomllib.loads(_read("pyproject.toml"))

    assert "architecture.md" in development
    assert "main.py" in architecture
    assert "*_api_routes.py" in architecture
    assert "mount_placement.py" in architecture
    assert "from .mount_placement import placement_safety_from_preview, refine_preview_placement" in routes
    assert "def _candidate_with_footprint_probe(" not in routes
    assert "def refine_preview_placement(" in placement
    assert "def placement_safety_from_preview(" in placement
    assert "from flask" not in placement
    assert "mcbe_editor/mount_placement.py" in pyproject["tool"]["mypy"]["files"]


def test_docker_permission_docs_keep_safe_and_compatibility_paths_explicit():
    readme = _read("README.md")
    readme_de = _read("README.de.md")
    security = _read("SECURITY.md")
    security_de = _read("SECURITY.de.md")
    compose = _read("docker-compose.example.yml")

    assert "Recommended: targeted ACL for UID 10001" in readme
    assert "Empfohlen: gezielte ACL für UID 10001" in readme_de
    assert "Compatibility mode: shared group or shared UID" in readme
    assert "Kompatibilitätsmodus: gemeinsame Gruppe oder gemeinsame UID" in readme_de
    for source in (readme, readme_de):
        assert "setfacl -R -m u:10001:rwX" in source
        assert "group_add:" in source
        assert 'user: "1234:1234"' in source
        assert "chmod -R 777" in source
        assert "privileged: true" in source
        assert "db/LOCK" in source
    for source in (security, security_de, compose):
        assert "chmod 777" in source
        assert "privileged" in source
        assert "LevelDB" in source


def test_in_app_help_uses_existing_actions_and_layout_neutral_guidance():
    template = _read("templates/index.html")

    assert "Item-Doppelklick" not in template
    assert "Tools → Sicherheit" not in template
    assert "Werkzeuge → Backup-Manager" in template
    assert "Werkzeuge → Status & Diagnose" in template
    assert "Wähle links eine gefundene Welt aus" not in template
    assert "Details stehen rechts" not in template
    assert "btnApplySingleInline" not in template
    assert "Dry-Run" in template


def test_ci_uses_full_test_runner_so_core_dependency_skips_do_not_pass_release_tests():
    workflow = _read(".github/workflows/ci.yml")
    assert "python scripts/test_full.py -v" in workflow
    assert "python scripts/coverage_check.py -q" in workflow

    runner = _read("scripts/test_full.py")
    assert '"amulet_nbt"' in runner
    assert '"leveldb"' in runner
    assert "pytest" in runner
    assert "DEFAULT_BASETEMP" in runner
    assert "--basetemp" in runner
    assert "DEFAULT_FAULTHANDLER_TIMEOUT_SECONDS" in runner
    assert "faulthandler_timeout" in runner
    assert "faulthandler_exit_on_timeout=true" in runner
    assert "proc.terminate()" in runner

    coverage_runner = _read("scripts/coverage_check.py")
    assert "test_full._missing_core_dependencies" in coverage_runner
    assert 'COVERAGE_TARGETS = ("mcbe_editor", "main")' in coverage_runner
    assert 'COVERAGE_IGNORES = ("tests/test_frontend_*.py", "tests/test_world_locks.py")' in coverage_runner
    assert 'COVERAGE_INCLUDE = "main.py,mcbe_editor/*"' in coverage_runner
    assert "f\"--source={','.join(COVERAGE_TARGETS)}\"" in coverage_runner
    assert "COVERAGE_XML.unlink(missing_ok=True)" in coverage_runner
    assert '"coverage",' in coverage_runner
    assert '"run",' in coverage_runner
    assert '"xml",' in coverage_runner


def test_ci_enforces_typed_core_and_publishes_coverage():
    workflow = _read(".github/workflows/ci.yml")
    pyproject = tomllib.loads(_read("pyproject.toml"))
    mypy = pyproject["tool"]["mypy"]
    coverage = pyproject["tool"]["coverage"]

    assert "typecheck:" in workflow
    assert "python -m mypy" in workflow
    assert "needs: [lint, typecheck, integrity, tests, browser-smoke]" in workflow
    assert "python-coverage-${{ github.sha }}" in workflow
    assert "path: coverage.xml" in workflow
    assert mypy["strict"] is True
    assert mypy["python_version"] == "3.12"
    assert "mcbe_editor/world_locks.py" in mypy["files"]
    assert coverage["run"]["branch"] is True
    assert coverage["report"]["fail_under"] == 75


def test_full_test_runner_uses_unique_basetemp(monkeypatch):
    from scripts import test_artifacts, test_full

    tokens = iter(["aaaa1111", "bbbb2222"])
    monkeypatch.setattr(test_artifacts.os, "getpid", lambda: 12345)
    monkeypatch.setattr(test_artifacts.secrets, "token_hex", lambda _size: next(tokens))

    first = test_full._default_basetemp()
    second = test_full._default_basetemp()

    assert first.parent == test_full.DEFAULT_BASETEMP.parent
    assert first.name == "full-suite-basetemp-12345-aaaa1111"
    assert second.name == "full-suite-basetemp-12345-bbbb2222"
    assert ROOT.resolve() not in first.resolve().parents


def test_ci_manual_runs_validate_without_publishing():
    workflow = _read(".github/workflows/ci.yml")
    docker_publish = workflow.split("  docker-publish:", 1)[1].split("  release:", 1)[0]

    assert "workflow_dispatch:" in workflow
    assert "publish_docker:" not in workflow
    assert "workflow_dispatch" not in docker_publish
    assert "Dependency audit" in workflow
    assert "python scripts/security_check.py --require-pip-audit" in workflow
    assert not (ROOT / ".github/workflows/docker-publish.yml").exists()


def test_ci_publishes_docker_only_for_version_tags_and_protects_latest():
    workflow = _read(".github/workflows/ci.yml")
    docker_build = workflow.split("  docker-build:", 1)[1].split("  docker-publish:", 1)[0]
    docker_publish = workflow.split("  docker-publish:", 1)[1].split("  release:", 1)[0]

    assert "startsWith(github.ref, 'refs/tags/v')" in docker_build
    assert "github.event_name != 'push'" not in docker_build
    assert "workflow_dispatch" not in docker_build
    assert "startsWith(github.ref, 'refs/tags/v')" in docker_publish
    assert "github.ref == 'refs/heads/main'" not in docker_publish
    assert "workflow_dispatch" not in docker_publish
    assert "latest=false" in docker_publish
    assert "type=raw,value=latest,enable=${{ steps.release_channel.outputs.publish_latest }}" in docker_publish
    assert r'[[ "${GITHUB_REF_NAME}" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]' in docker_publish
    assert "type=sha,prefix=sha-" in docker_publish
    assert "type=pep440,pattern={{version}}" in docker_publish
    assert "type=pep440,pattern={{major}}.{{minor}}" in docker_publish


def test_ci_release_artifacts_are_revision_specific_and_tags_match_project_version():
    workflow = _read(".github/workflows/ci.yml")

    assert "Verify release tag matches project version" in workflow
    assert 'test "v${project_version}" = "${GITHUB_REF_NAME}"' in workflow
    assert "mcbe_inventory_editor_${GITHUB_SHA}_runtime.zip" in workflow
    assert "mcbe_inventory_editor_${{ github.sha }}_runtime.zip" in workflow
    assert "needs: [package, docker-publish]" in workflow
    assert 'gh release create "$GITHUB_REF_NAME"' in workflow
    assert 'sha256sum "$release_name"' in workflow
    assert "release_flags+=(--prerelease)" in workflow


def test_ci_external_actions_are_immutably_pinned_with_version_comments():
    workflow = _read(".github/workflows/ci.yml")
    uses_lines = [line.strip() for line in workflow.splitlines() if "uses:" in line]

    assert uses_lines
    for line in uses_lines:
        match = re.fullmatch(r"-?\s*uses:\s+([^@\s]+)@([0-9a-f]{40})\s+#\s+(v\d+\.\d+\.\d+)", line)
        assert match is not None, f"Action is not immutably pinned: {line}"

    assert "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0 # v7.0.0" in workflow
    assert "docker/build-push-action@53b7df96c91f9c12dcc8a07bcb9ccacbed38856a # v7.3.0" in workflow
    assert "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c # v8.0.1" in workflow


def test_ci_and_docker_bootstrap_pip_from_a_hash_locked_file():
    workflow = _read(".github/workflows/ci.yml")
    dockerfile = _read("Dockerfile")
    bootstrap_lock = _read("requirements/bootstrap.lock")

    assert "pip install --upgrade pip" not in workflow
    assert "pip install --upgrade pip" not in dockerfile
    assert workflow.count("pip install --require-hashes -r requirements/bootstrap.lock") == 7
    assert "pip install --no-cache-dir --require-hashes -r requirements/bootstrap.lock" in dockerfile
    assert "pip==26.1.2" in bootstrap_lock
    assert bootstrap_lock.count("--hash=sha256:") == 2
    assert '"bootstrap.lock"' in _read("scripts/check_lockfiles.py")


def test_requirements_are_grouped_without_legacy_plaintext_fallbacks():
    expected = {
        "README.md",
        "bootstrap.in",
        "bootstrap.lock",
        "build-constraints.txt",
        "dev.in",
        "dev.lock",
        "docker.in",
        "docker.lock",
        "runtime.in",
        "runtime.lock",
    }
    actual = {path.name for path in (ROOT / "requirements").iterdir() if path.is_file()}

    assert actual == expected
    assert not list(ROOT.glob("requirements*.txt"))
    assert not list(ROOT.glob("requirements*.in"))
    assert not list(ROOT.glob("requirements*.lock"))

    project_dependencies = tomllib.loads(_read("pyproject.toml"))["project"]["dependencies"]
    runtime_dependencies = [line.strip() for line in _read("requirements/runtime.in").splitlines() if line.strip() and not line.lstrip().startswith("#")]
    assert runtime_dependencies == project_dependencies

    dockerignore = _read(".dockerignore")
    assert "requirements/*.in" in dockerignore
    assert "requirements/README.md" in dockerignore


def test_docker_runtime_uses_an_explicit_allowlist_and_validated_manifest():
    dockerfile = _read("Dockerfile")
    dockerignore = _read(".dockerignore")

    assert "COPY . ." not in dockerfile
    assert "COPY main.py pyproject.toml ./" in dockerfile
    assert "COPY main.py item_db.json pyproject.toml ./" not in dockerfile
    assert "COPY mcbe_editor/ ./mcbe_editor/" in dockerfile
    assert "COPY static/ ./static/" in dockerfile
    assert "COPY templates/ ./templates/" in dockerfile
    assert "python -m mcbe_editor.distribution --write-manifest /app" in dockerfile
    assert "status['kind'] == 'release'" in dockerfile
    for blocked in (
        "diagnostics/",
        ".agents/",
        ".claude/",
        ".codex/",
        ".playwright-cli/",
        "node_modules/",
        "test-results/",
        "playwright-report/",
        "tests/",
        "RELEASE_MANIFEST.json",
    ):
        assert blocked in dockerignore


def test_mount_probe_production_logic_is_directly_testable_without_runtime_monkey_patch():
    package_init = _read("mcbe_editor/__init__.py")
    runtime_bootstrap = _read("mcbe_editor/runtime_bootstrap.py")
    mount_probe = _read("mcbe_editor/mount_block_probe.py")

    assert "_install_bedrock_subchunk_index_order_patch" not in package_init
    assert "_install_bedrock_subchunk_index_order_patch" not in runtime_bootstrap
    assert 'if "pytest" in sys.modules' not in package_init
    assert "def probe_candidate_chunk(" in mount_probe
    assert "PROBE_INDEX_ORDERS" in mount_probe


def test_bundled_item_database_is_a_packaged_resource_not_runtime_data():
    from mcbe_editor.runtime_data import BUNDLED_ITEM_DB_JSON, BUNDLED_ITEM_DB_RELATIVE_PATH

    expected = ROOT / "mcbe_editor" / "resources" / "item_db.json"
    assert BUNDLED_ITEM_DB_RELATIVE_PATH.as_posix() == "mcbe_editor/resources/item_db.json"
    assert expected == BUNDLED_ITEM_DB_JSON
    assert expected.is_file()
    assert not (ROOT / "item_db.json").exists()
    assert '"mcbe_editor/resources/item_db.json"' in _read("scripts/runtime_layout.py")
    assert '"mcbe_editor/resources/enchantment_max_levels.json"' in _read("scripts/runtime_layout.py")
    assert "DEFAULT_ITEM_DB_PATH = BUNDLED_ITEM_DB_JSON" in _read("scripts/update_db.py")


def test_windows_release_workflow_replaces_only_explicitly_and_after_validation():
    workflow = _read("scripts/release_windows.bat")
    build_temporary = 'scripts\\make_release_zip.py --output "%TEMP_RELEASE%"'
    validate_temporary = 'scripts\\release_check.py --archive "%TEMP_RELEASE%"'
    replace_validated = "os.replace(r'%TEMP_RELEASE%', r'%RELEASE%')"

    assert "scripts\\test_full.py -v" in workflow
    assert "scripts\\coverage_check.py -q" in workflow
    assert "scripts\\browser_smoke.py" in workflow
    assert "scripts\\security_check.py --require-pip-audit" in workflow
    assert "scripts\\release_check.py --archive" in workflow
    assert "already exists" in workflow
    assert "git status --porcelain" in workflow
    assert "--replace-existing" in workflow
    assert "if not defined REPLACE_EXISTING" in workflow
    assert 'git show-ref --verify --quiet "refs/tags/v%VERSION%"' in workflow
    assert build_temporary in workflow
    assert validate_temporary in workflow
    assert replace_validated in workflow
    assert workflow.index(build_temporary) < workflow.index(validate_temporary) < workflow.index(replace_validated)
    assert 'if defined TEMP_RELEASE if exist "%TEMP_RELEASE%" del /q "%TEMP_RELEASE%"' in workflow


def test_windows_entrypoints_are_portable_and_use_reproducible_setup():
    entrypoints = (
        "scripts/docker/build_image.bat",
        "scripts/docker/export_image.bat",
        "scripts/horse_diagnostic_gui.cmd",
        "scripts/release_windows.bat",
        "setup.bat",
        "start.bat",
    )
    sources = {path: _read(path) for path in entrypoints}
    combined = "\n".join(sources.values())

    for path in entrypoints:
        raw = (ROOT / path).read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf"), f"{path} must use UTF-8 without BOM"
        assert b"\r\n" in raw, f"{path} must use CRLF for cmd.exe"
        assert b"\n" not in raw.replace(b"\r\n", b""), f"{path} contains mixed line endings"
        assert "chcp 65001 >nul" in sources[path]

    assert re.search(r"(?i)[a-z]:\\users\\[^\\\r\n]+", combined) is None
    assert re.search(r"(?i)(?:/home|/users)/[^/\s]+", combined) is None
    assert re.search(r"\b(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2})\b", combined) is None
    assert re.search(r"\b172\.(?:1[6-9]|2\d|3[01])\.(?:\d{1,3}\.)\d{1,3}\b", combined) is None
    assert re.search(r"(?im)^\s*echo\b.*%CD%", combined) is None
    assert re.search(r"(?im)^\s*set\s+\"?[^=\r\n]*(?:password|secret|token|api[_-]?key)[^=\r\n]*=.+$", combined) is None

    setup = sources["setup.bat"]
    assert "pip install --upgrade pip" not in setup
    assert "pip install --require-hashes -r requirements\\runtime.lock" in setup
    assert "pip install -r requirements.txt" not in setup

    release = sources["scripts/release_windows.bat"]
    assert 'set "PYTHON=.venv\\Scripts\\python.exe"' in release
    assert 'set "PYTHON=py"' not in release

    diagnostic = sources["scripts/horse_diagnostic_gui.cmd"]
    assert '\n    python "scripts\\horse_diagnostic_gui.py"' not in diagnostic

    start = sources["start.bat"]
    assert "ExecutionPolicy Bypass" not in start
    assert 'set "MCBE_EDITOR_HOST=127.0.0.1"' in start

    export = sources["scripts/docker/export_image.bat"].lower()
    build = sources["scripts/docker/build_image.bat"].lower()
    assert 'cd /d "%~dp0\\..\\.."' in build
    assert 'cd /d "%~dp0\\..\\.."' in export
    build_call = 'call "%~dp0build_image.bat" --no-pause'
    assert build_call not in export
    assert "docker image inspect" not in export
    assert "docker save" not in export
    assert 'docker buildx build --tag "%image_name%" --output "type=docker,dest=%temp_file%" .' in export
    assert "the finished image is not loaded into docker desktop" in export
    assert "portainer" not in export
    assert "ubuntu-lxc" not in export
    assert "/tmp/" not in export


def test_linux_docker_helper_uses_project_root_as_build_context():
    source = _read("scripts/docker/build_image.sh")

    assert 'cd "$(dirname "$0")/../.."' in source
    assert 'docker build -t "${IMAGE_NAME}" .' in source


def test_gitignore_uses_explicit_runtime_and_local_tool_patterns():
    lines = {line.strip() for line in _read(".gitignore").splitlines() if line.strip() and not line.startswith("#")}
    docker_lines = {line.strip() for line in _read(".dockerignore").splitlines() if line.strip() and not line.startswith("#")}

    assert {"/setup.json", "/settings.json", "/cache/item_update/", "/.cache_item_update/"} <= lines
    assert {"/.idea/", "/.vscode/", "/.pytest-*/", ".hypothesis/", ".nox/", ".tox/", "build/", "*.egg-info/"} <= lines
    assert {".pytest-*/", ".tmp/"} <= docker_lines
    assert "setup.json" not in lines
    assert "settings.json" not in lines


def test_lockfile_compiler_uses_project_build_constraints(monkeypatch):
    from scripts import compile_lockfiles

    monkeypatch.setenv("PIP_BUILD_CONSTRAINT", "outside-constraints.txt")

    assert compile_lockfiles.BUILD_CONSTRAINTS == ROOT / "requirements" / "build-constraints.txt"
    assert compile_lockfiles._piptools_env()["PIP_BUILD_CONSTRAINT"] == str(ROOT / "requirements" / "build-constraints.txt")
    assert "PIP_BUILD_CONSTRAINT: ${{ github.workspace }}/requirements/build-constraints.txt" in _read(".github/workflows/ci.yml")
    assert "PIP_BUILD_CONSTRAINT=/app/requirements/build-constraints.txt" in _read("Dockerfile")


def test_lockfile_check_seeds_existing_pins_before_compile(tmp_path, monkeypatch):
    from scripts import compile_lockfiles

    requirements_dir = tmp_path / "requirements"
    requirements_dir.mkdir()
    source = requirements_dir / "runtime.in"
    target = requirements_dir / "runtime.lock"
    source.write_text("example>=1\n", encoding="utf-8")
    target.write_text("example==1.0.0\n", encoding="utf-8")
    observed = {}

    def fake_run(cmd):
        output_path = compile_lockfiles.ROOT / cmd[cmd.index("--output-file") + 1]
        observed["seeded_output"] = output_path.read_text(encoding="utf-8")

    monkeypatch.setattr(compile_lockfiles, "ROOT", tmp_path)
    monkeypatch.setattr(compile_lockfiles, "CACHE_DIR", tmp_path / ".pip-tools-cache")
    monkeypatch.setattr(compile_lockfiles, "BUILD_CONSTRAINTS", requirements_dir / "build-constraints.txt")
    monkeypatch.setattr(compile_lockfiles, "LOCK_TARGETS", [(source, target)])
    monkeypatch.setattr(compile_lockfiles, "run", fake_run)
    monkeypatch.setattr(sys, "argv", ["compile_lockfiles.py", "--check"])

    assert compile_lockfiles.main() == 0
    assert observed["seeded_output"] == "example==1.0.0\n"
    assert not (tmp_path / ".lockcheck").exists()


def test_lockfile_check_ignores_platform_specific_piptools_annotations(tmp_path):
    from scripts import compile_lockfiles

    linux_lock = tmp_path / "linux.lock"
    windows_lock = tmp_path / "windows.lock"
    linux_lock.write_text(
        "\n".join(
            [
                "#",
                "# This file is autogenerated by pip-compile with Python 3.12",
                "# by the following command:",
                "#",
                "#    pip-compile --output-file=.lockcheck/runtime.lock requirements/runtime.in",
                "#",
                "colorama==0.4.6 \\",
                "    --hash=sha256:08695f5cb7ed6e0531a20572697273c47b8cae5a63ffc6d6ed5c201be6e44",
                "    # via -r requirements/runtime.in",
                "",
            ]
        ),
        encoding="utf-8",
    )
    windows_lock.write_text(
        "\n".join(
            [
                "#",
                "# This file is autogenerated by pip-compile with Python 3.12",
                "# by the following command:",
                "#",
                "#    pip-compile --output-file=requirements/runtime.lock requirements/runtime.in",
                "#",
                "colorama==0.4.6 \\",
                "    --hash=sha256:08695f5cb7ed6e0531a20572697273c47b8cae5a63ffc6d6ed5c201be6e44",
                "    # via",
                "    #   -r requirements/runtime.in",
                "    #   click",
                "",
            ]
        ),
        encoding="utf-8",
    )

    assert compile_lockfiles._normalized_lockfile_text(linux_lock) == compile_lockfiles._normalized_lockfile_text(windows_lock)


def test_nbt_dependent_test_modules_are_explicitly_known():
    expected = {
        "tests/test_compatibility.py",
        "tests/test_bulk_replace_nbt.py",
        "tests/test_cross_world_provenance.py",
        "tests/test_inventory.py",
        "tests/test_inventory_facade.py",
        "tests/test_integrity_and_backup_regressions.py",
        "tests/test_item_copy_regressions.py",
        "tests/test_mount_diagnostic_evidence.py",
        "tests/test_mount_write.py",
        "tests/test_mount_write_horse_profile.py",
        "tests/test_mounts.py",
        "tests/test_nbt_safety.py",
        "tests/test_player_import_snapshot.py",
        "tests/test_players.py",
        "tests/test_root_equipment.py",
        "tests/test_security_fixes.py",
        "tests/test_service.py",
        "tests/test_source_digest_opaque_values.py",
        "tests/test_untouched_field_invariance.py",
    }
    found = {
        path.relative_to(ROOT).as_posix()
        for path in sorted((ROOT / "tests").glob("test_*.py"))
        if path.name != "test_project_consistency.py" and 'importorskip("amulet_nbt"' in path.read_text(encoding="utf-8")
    }
    assert found == expected


def test_full_suite_has_meaningful_number_of_nbt_tests():
    nbt_test_count = 0
    for rel in (
        "tests/test_compatibility.py",
        "tests/test_inventory.py",
        "tests/test_inventory_facade.py",
        "tests/test_item_copy_regressions.py",
        "tests/test_nbt_safety.py",
        "tests/test_players.py",
        "tests/test_root_equipment.py",
        "tests/test_security_fixes.py",
        "tests/test_service.py",
    ):
        tree = ast.parse(_read(rel))
        nbt_test_count += sum(1 for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"))
    assert nbt_test_count >= 200
