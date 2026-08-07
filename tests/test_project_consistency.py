from __future__ import annotations

import sys
import tomllib
from pathlib import Path

from tests import project_consistency_base as _base
from tests.project_consistency_base import *  # noqa: F403


def test_ci_and_docker_bootstrap_pip_from_a_hash_locked_file():
    workflow = _base._read(".github/workflows/ci.yml")
    dockerfile = _base._read("Dockerfile")
    bootstrap_source = _base._read("requirements/bootstrap.txt")
    bootstrap_wrapper = _base._read("requirements/bootstrap.lock")

    assert "pip install --upgrade pip" not in workflow
    assert "pip install --upgrade pip" not in dockerfile
    assert workflow.count("pip install --require-hashes -r requirements/bootstrap.lock") == 7
    assert "pip install --no-cache-dir --require-hashes -r requirements/bootstrap.lock" in dockerfile
    assert "pip==26.1.2" in bootstrap_source
    assert bootstrap_source.count("--hash=sha256:") == 2
    assert bootstrap_wrapper == "-r bootstrap.txt\n"
    check_script = _base._read("scripts/check_lockfiles.py")
    assert '"bootstrap.txt"' in check_script
    assert '"bootstrap.lock"' in check_script


def test_requirements_are_grouped_without_legacy_plaintext_fallbacks():
    expected = {
        "README.md",
        "bootstrap.in",
        "bootstrap.lock",
        "bootstrap.txt",
        "build-constraints.txt",
        "dev.in",
        "dev.lock",
        "dev.txt",
        "docker.in",
        "docker.lock",
        "docker.txt",
        "runtime.in",
        "runtime.lock",
        "runtime.txt",
    }
    actual = {path.name for path in (_base.ROOT / "requirements").iterdir() if path.is_file()}

    assert actual == expected
    assert not list(_base.ROOT.glob("requirements*.txt"))
    assert not list(_base.ROOT.glob("requirements*.in"))
    assert not list(_base.ROOT.glob("requirements*.lock"))

    project_dependencies = tomllib.loads(_base._read("pyproject.toml"))["project"]["dependencies"]
    runtime_dependencies = [
        line.strip()
        for line in _base._read("requirements/runtime.in").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert runtime_dependencies == project_dependencies

    for name in ("bootstrap", "runtime", "docker", "dev"):
        assert _base._read(f"requirements/{name}.lock") == f"-r {name}.txt\n"

    # Dependabot cannot run pip-compile, so it can only widen version ceilings
    # in pyproject.toml and the .in files while the hash-pinned lockfiles keep
    # installing the old version -- a green pipeline that proves nothing.
    # Dependency updates stay deliberate; SECURITY.md documents the procedure.
    assert not (_base.ROOT / ".github" / "dependabot.yml").exists()

    dockerignore = _base._read(".dockerignore")
    assert "requirements/*.in" in dockerignore
    assert "requirements/README.md" in dockerignore


def test_lockfile_check_seeds_existing_pins_before_compile(tmp_path: Path, monkeypatch):
    from scripts import compile_lockfiles

    requirements_dir = tmp_path / "requirements"
    requirements_dir.mkdir()
    source = requirements_dir / "runtime.in"
    target = requirements_dir / "runtime.txt"
    source.write_text("example>=1\n", encoding="utf-8")
    target.write_text("example==1.0.0\n", encoding="utf-8")
    target.with_suffix(".lock").write_text("-r runtime.txt\n", encoding="utf-8")
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
