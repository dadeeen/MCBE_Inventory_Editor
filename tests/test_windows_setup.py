from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts import windows_setup as setup
from scripts.runtime_layout import is_runtime_relative_path


@pytest.fixture
def installation(tmp_path, monkeypatch):
    (tmp_path / '.venv').mkdir()
    requirements = tmp_path / 'requirements'
    requirements.mkdir()
    for name in ('bootstrap', 'runtime'):
        (requirements / f'{name}.lock').write_text(f'-r {name}.txt\n')
        (requirements / f'{name}.txt').write_text('# fixture\n')
    monkeypatch.setattr(setup.sys, 'prefix', str(tmp_path / '.venv'))
    monkeypatch.setattr(setup, 'supported_python', lambda: True)
    return tmp_path


@pytest.mark.parametrize('version,expected', [((3, 11), False), ((3, 12), True), ((3, 13), True), ((3, 14), True), ((3, 15), False)])
def test_preflight_accepts_only_supported_python_versions(monkeypatch, version, expected):
    monkeypatch.setattr(setup.sys, 'version_info', version)
    monkeypatch.setattr(setup.sys, 'platform', 'win32')
    monkeypatch.setattr(setup.platform, 'python_implementation', lambda: 'CPython')
    monkeypatch.setattr(setup.sysconfig, 'get_config_var', lambda _name: None)
    assert setup.supported_python() is expected


@pytest.mark.parametrize('implementation,gil_disabled,platform_name', [('PyPy', None, 'win32'), ('CPython', 1, 'win32'), ('CPython', None, 'linux')])
def test_preflight_rejects_unvalidated_interpreters(monkeypatch, implementation, gil_disabled, platform_name):
    monkeypatch.setattr(setup.sys, 'version_info', (3, 14))
    monkeypatch.setattr(setup.sys, 'platform', platform_name)
    monkeypatch.setattr(setup.platform, 'python_implementation', lambda: implementation)
    monkeypatch.setattr(setup.sysconfig, 'get_config_var', lambda _name: gil_disabled)
    with pytest.raises(ValueError, match='standard CPython'):
        setup.preflight()


@pytest.mark.parametrize('global_environment', [True, False])
def test_install_rejects_environments_outside_project(installation, monkeypatch, global_environment):
    monkeypatch.setattr(setup.sys, 'prefix', setup.sys.base_prefix if global_environment else str(installation / 'other-venv'))
    monkeypatch.setattr(setup.subprocess, 'run', lambda *a, **kw: pytest.fail('No installation outside project .venv'))
    with pytest.raises(ValueError, match="project's .venv"):
        setup.install(installation)


def test_missing_lock_aborts_before_installation(installation, monkeypatch):
    (installation / 'requirements/runtime.txt').unlink()
    monkeypatch.setattr(setup.subprocess, 'run', lambda *a, **kw: pytest.fail('No unlocked fallback'))
    with pytest.raises(ValueError, match='Missing hash-locked'):
        setup.install(installation)


def test_install_uses_only_locked_wheels_and_checks_real_imports(installation, monkeypatch):
    calls = []

    def run(command, **kwargs):
        assert kwargs == {'cwd': installation, 'check': True}
        calls.append(command)

    monkeypatch.setattr(setup.subprocess, 'run', run)
    setup.install(installation)
    installs = [command for command in calls if 'install' in command]
    assert len(installs) == 2
    for command in installs:
        assert '--only-binary=:all:' in command
        assert '--require-hashes' in command
        assert command[-1] in ('requirements/bootstrap.lock', 'requirements/runtime.lock')
    assert calls[-2][-2:] == ['pip', 'check']
    assert calls[-1][:2] == [setup.sys.executable, '-c']
    assert 'mcbe_editor.db' in calls[-1][-1]
    assert 'leveldb' not in calls[-1][-1]


@pytest.mark.parametrize('fail_at', ['install', 'check', 'import'])
def test_installation_or_import_failure_is_reported(installation, monkeypatch, capsys, fail_at):
    def fail(command, **kwargs):
        if (fail_at == 'install' and 'install' in command or fail_at == 'check' and command[-1] == 'check'
                or fail_at == 'import' and command[1] == '-c'):
            raise subprocess.CalledProcessError(1, command)
    monkeypatch.setattr(setup.subprocess, 'run', fail)
    monkeypatch.setattr(setup, 'ROOT', installation)
    monkeypatch.setattr(setup.sys, 'argv', ['windows_setup.py', 'install'])
    assert setup.main() == 1
    assert 'Setup unavailable' in capsys.readouterr().err


@pytest.mark.parametrize('path', [
    'wheels/cp314/amulet_leveldb.whl', 'wheels/cp314/provenance.json',
    'requirements/leveldb-reference.txt', 'requirements/nbt-reference.txt',
])
def test_release_allowlist_excludes_native_reference_artifacts(path):
    assert not is_runtime_relative_path(Path(path))
