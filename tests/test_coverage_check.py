from __future__ import annotations

from scripts import coverage_check


def test_coverage_args_exclude_non_python_and_multiprocessing_suites(monkeypatch, tmp_path):
    monkeypatch.setattr(coverage_check.test_full, "DEFAULT_BASETEMP", tmp_path / "coverage-basetemp")
    monkeypatch.setattr(coverage_check.test_full, "_default_basetemp", lambda: tmp_path / "run")

    args, basetemp = coverage_check.coverage_pytest_args(["-q"])

    assert args[0] == "-q"
    assert "--ignore-glob=tests/test_frontend_*.py" in args
    assert "--ignore-glob=tests/test_world_locks.py" in args
    assert f"--basetemp={tmp_path / 'run'}" in args
    assert "faulthandler_timeout=120" in " ".join(args)
    assert "faulthandler_exit_on_timeout=true" in " ".join(args)
    assert basetemp == tmp_path / "run"


def test_coverage_args_prune_stale_artifacts_with_explicit_basetemp(monkeypatch):
    calls = []
    monkeypatch.setattr(coverage_check.test_full, "prune_stale_test_artifacts", lambda **kwargs: calls.append(kwargs) or [])

    args, basetemp = coverage_check.coverage_pytest_args(["--basetemp=custom"])

    assert "--basetemp=custom" in args
    assert basetemp is None
    assert calls == [{}]


def test_coverage_runner_runs_tests_and_writes_thresholded_xml(monkeypatch, tmp_path):
    commands: list[list[str]] = []
    xml_path = tmp_path / "coverage.xml"

    monkeypatch.setattr(coverage_check.test_full, "_missing_core_dependencies", lambda: [])
    monkeypatch.setattr(coverage_check, "coverage_pytest_args", lambda _args: (["-q"], None))
    monkeypatch.setattr(coverage_check, "COVERAGE_XML", xml_path)
    xml_path.write_text("stale", encoding="utf-8")

    def fake_run(command: list[str]) -> int:
        if not commands:
            assert not xml_path.exists()
        commands.append(command)
        if "xml" in command:
            xml_path.write_text(
                '<coverage lines-valid="80" lines-covered="60" branches-valid="20" branches-covered="16"/>',
                encoding="utf-8",
            )
        return 0

    monkeypatch.setattr(coverage_check, "_run", fake_run)

    assert coverage_check.main(["-q"]) == 0
    assert commands[0][-2:] == ["coverage", "erase"]
    assert "--source=mcbe_editor,main" in commands[1]
    assert commands[1][-3:] == ["pytest", "tests", "-q"]
    assert commands[2][2:4] == ["coverage", "xml"]
    assert "--include=main.py,mcbe_editor/*" in commands[2]
    assert "--fail-under=75" in commands[2]
    assert commands[2][-1] == str(xml_path)


def test_coverage_runner_preserves_test_failure_after_writing_xml(monkeypatch, tmp_path):
    statuses = iter([0, 7, 0])

    monkeypatch.setattr(coverage_check.test_full, "_missing_core_dependencies", lambda: [])
    monkeypatch.setattr(coverage_check, "coverage_pytest_args", lambda _args: ([], None))
    monkeypatch.setattr(coverage_check, "COVERAGE_XML", tmp_path / "missing.xml")
    monkeypatch.setattr(coverage_check, "_run", lambda _command: next(statuses))

    assert coverage_check.main([]) == 7


def test_coverage_runner_reports_retained_failure_diagnostics(monkeypatch, tmp_path, capsys):
    statuses = iter([0, 7, 0])
    basetemp = tmp_path / "coverage-basetemp"
    basetemp.mkdir()

    monkeypatch.setattr(coverage_check.test_full, "_missing_core_dependencies", lambda: [])
    monkeypatch.setattr(coverage_check, "coverage_pytest_args", lambda _args: ([], basetemp))
    monkeypatch.setattr(coverage_check, "COVERAGE_XML", tmp_path / "missing.xml")
    monkeypatch.setattr(coverage_check, "_run", lambda _command: next(statuses))

    assert coverage_check.main([]) == 7
    assert basetemp.is_dir()
    assert str(basetemp) in capsys.readouterr().err


def test_coverage_percent_combines_lines_and_branches(tmp_path):
    xml_path = tmp_path / "coverage.xml"
    xml_path.write_text(
        '<coverage lines-valid="80" lines-covered="60" branches-valid="20" branches-covered="15"/>',
        encoding="utf-8",
    )

    assert coverage_check._coverage_percent_from_xml(xml_path) == 75.0


def test_coverage_threshold_is_enforced_from_pyproject():
    assert coverage_check._coverage_fail_under() == 75.0
