from __future__ import annotations

import json
import re
import shutil
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import windows_setup as setup
from scripts import windows_wheels as wheels
from scripts.runtime_layout import is_runtime_relative_path


@pytest.fixture
def bundle(tmp_path):
    (tmp_path / "requirements").mkdir()
    for name in ("runtime.txt", "build.txt"):
        shutil.copyfile(setup.ROOT / "requirements" / name, tmp_path / "requirements" / name)
    directory = tmp_path / "wheels/cp314"
    directory.mkdir(parents=True)
    path = directory / wheels.wheel_name("cp314")
    with zipfile.ZipFile(path, "w") as archive:
        prefix = f"amulet_leveldb-{wheels.WHEEL_VERSION}.dist-info/"
        archive.writestr(prefix + "METADATA", f"Metadata-Version: 2.4\r\nName: amulet-leveldb\r\nVersion: {wheels.WHEEL_VERSION}\r\n")
        archive.writestr(prefix + "WHEEL", "Wheel-Version: 1.0\r\nTag: cp314-cp314-win_amd64\r\n")
    for name in wheels.LICENSE_FILES:
        (directory / name).write_text("Fixture license notice\n")
    source_hash = re.search(r"sha256:([0-9a-f]{64})", wheels.leveldb_requirement(tmp_path))[1]
    manifest = {"schema": 1, "abi": "cp314", "source": {"sha256": source_hash},
                "build_requirements_sha256": wheels.build_lock_sha256(tmp_path),
                "files": {name: wheels.sha256(directory / name) for name in (path.name, *wheels.LICENSE_FILES)}}
    (directory / "provenance.json").write_text(json.dumps(manifest))
    return tmp_path, path


def test_bundle_verifies_metadata_hashes_and_cross_platform_lock_newlines(bundle):
    root, path = bundle
    assert wheels.validated_wheel(root, "cp314") == path
    build_lock = root / "requirements/build.txt"
    build_lock.write_bytes(build_lock.read_text().replace("\n", "\r\n").encode())
    assert wheels.validated_wheel(root, "cp314") == path
    assert is_runtime_relative_path(path.relative_to(root))
    assert not is_runtime_relative_path(Path("wheels/cp314/unreviewed.whl"))


@pytest.mark.parametrize("file", ["provenance.json", "LICENSE.leveldb.txt", wheels.wheel_name("cp314")])
def test_incomplete_or_tampered_bundle_is_rejected(bundle, file):
    root, path = bundle
    (path.parent / file).write_bytes(b"tampered")
    with pytest.raises((ValueError, OSError)):
        wheels.validated_wheel(root, "cp314")


@pytest.fixture
def setup_policy(monkeypatch):
    monkeypatch.setattr(setup, "supported_python", lambda: True)
    monkeypatch.setattr(setup.sysconfig, "get_platform", lambda: "win-amd64")
    monkeypatch.setattr(setup, "installed_driver", lambda: False)
    monkeypatch.setattr(setup, "bundled_wheel", lambda root: None)
    monkeypatch.setattr(setup, "published_wheel_available", lambda: False)
    monkeypatch.setattr(setup, "compiler_available", lambda: False)
    monkeypatch.setattr(setup, "require_cpp_runtime", lambda: None)


def test_missing_compiler_rejects_source_but_allows_published_fallback(setup_policy, monkeypatch, tmp_path):
    with pytest.raises(ValueError, match="No compatible wheel"):
        setup.installation_mode(tmp_path, existing=False)
    monkeypatch.setattr(setup, "published_wheel_available", lambda: True)
    assert setup.installation_mode(tmp_path, existing=False) == "published"


def test_bundle_precedes_compiler_detection_and_installed_global_driver(setup_policy, monkeypatch, tmp_path):
    monkeypatch.setattr(setup, "bundled_wheel", lambda root: root / "wheel.whl")
    monkeypatch.setattr(setup, "installed_driver", lambda: True)
    monkeypatch.setattr(setup, "compiler_available", lambda: pytest.fail("Wheel must not require compiler detection"))
    assert setup.installation_mode(tmp_path, existing=False) == "bundled"
    assert setup.installation_mode(tmp_path, existing=True) == "installed"


def test_source_build_is_explicitly_disablable(setup_policy, monkeypatch, tmp_path):
    monkeypatch.setattr(setup, "compiler_available", lambda: True)
    assert setup.installation_mode(tmp_path) == "source"
    with pytest.raises(ValueError, match="No compatible wheel"):
        setup.installation_mode(tmp_path, allow_build=False)


def test_existing_environment_keeps_working_without_compiler(setup_policy, monkeypatch, tmp_path):
    monkeypatch.setattr(setup, "installed_driver", lambda: True)
    assert setup.installation_mode(tmp_path, allow_build=False) == "installed"


def test_compiler_preflight_requires_both_msvc_and_sdk(monkeypatch, tmp_path):
    monkeypatch.setenv("PROGRAMFILES(X86)", str(tmp_path))
    assert not setup.compiler_available()
    vswhere = tmp_path / "Microsoft Visual Studio/Installer/vswhere.exe"
    vswhere.parent.mkdir(parents=True)
    vswhere.touch()
    installation = tmp_path / "VisualStudio"
    monkeypatch.setattr(setup.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout=str(installation)))
    for relative in ("VC/Auxiliary/Build/vcvarsall.bat", "VC/Tools/MSVC/14.0/bin/Hostx64/x64/cl.exe"):
        path = installation / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    assert not setup.compiler_available()
    for relative in ("Include/10.0/um/Windows.h", "Include/10.0/ucrt/stdio.h", "Lib/10.0/um/x64/kernel32.lib"):
        path = tmp_path / "Windows Kits/10" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    assert setup.compiler_available()


def test_wheel_install_uses_exact_hash_and_never_source_builds(bundle, setup_policy, monkeypatch):
    root, path = bundle
    venv = root / ".venv"
    venv.mkdir()
    monkeypatch.setattr(setup.sys, "prefix", str(venv))
    monkeypatch.setattr(setup, "bundled_wheel", lambda root: wheels.validated_wheel(root, "cp314"))
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if command[-1] == "check":
            monkeypatch.setattr(setup, "installed_driver", lambda: True)
        if "--no-index" in command:
            content = Path(command[-1]).read_text()
            assert path.as_uri() in content
            assert "--hash=sha256:" + wheels.sha256(path) in content
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(setup.subprocess, "run", run)
    setup.install(root, allow_build=False)
    assert len(calls) == 4
    assert all("--no-binary=amulet-leveldb" not in command for command in calls)
    assert all("requirements/build.lock" not in command for command in calls)
    assert "--only-binary=:all:" in calls[-2]
    assert calls[-1][-1] == "check"


def test_invalid_bundle_fails_before_any_package_install(bundle, setup_policy, monkeypatch):
    root, path = bundle
    (root / ".venv").mkdir()
    monkeypatch.setattr(setup.sys, "prefix", str(root / ".venv"))
    monkeypatch.setattr(setup, "bundled_wheel", lambda root: wheels.validated_wheel(root, "cp314"))
    monkeypatch.setattr(setup.subprocess, "run", lambda *a, **kw: pytest.fail("No pip call before successful validation"))
    path.write_bytes(b"damaged")
    with pytest.raises(ValueError, match="integrity"):
        setup.install(root)


def test_missing_cpp_runtime_reports_the_official_installer(monkeypatch):
    def unavailable(name):
        assert name == "msvcp140.dll"
        raise OSError("DLL missing")
    monkeypatch.setattr(setup.ctypes, "WinDLL", unavailable, raising=False)
    with pytest.raises(ValueError, match="Visual C\\+\\+ Redistributable") as caught:
        setup.require_cpp_runtime()
    assert setup.REDIST_HELP in str(caught.value)


def test_missing_cpp_runtime_fails_before_pip(setup_policy, monkeypatch, tmp_path):
    (tmp_path / ".venv").mkdir()
    monkeypatch.setattr(setup.sys, "prefix", str(tmp_path / ".venv"))
    monkeypatch.setattr(setup, "published_wheel_available", lambda: True)
    def unavailable():
        raise ValueError("Missing C++ runtime")
    monkeypatch.setattr(setup, "require_cpp_runtime", unavailable)
    monkeypatch.setattr(setup.subprocess, "run", lambda *a, **kw: pytest.fail("No pip before runtime preflight"))
    with pytest.raises(ValueError, match="Missing C\\+\\+ runtime"):
        setup.install(tmp_path)


def test_installed_metadata_without_loadable_driver_does_not_count_as_success(setup_policy, monkeypatch, tmp_path):
    (tmp_path / ".venv").mkdir()
    monkeypatch.setattr(setup.sys, "prefix", str(tmp_path / ".venv"))
    monkeypatch.setattr(setup, "published_wheel_available", lambda: True)
    monkeypatch.setattr(setup.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0))
    with pytest.raises(ValueError, match="could not be imported"):
        setup.install(tmp_path)
