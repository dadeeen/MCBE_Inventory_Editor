#!/usr/bin/env python3
"""Measure backend branch coverage with the same native dependency gate as CI tests."""

from __future__ import annotations

import importlib
import shutil
import subprocess
import sys
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(ROOT))

test_full = importlib.import_module("scripts.test_full")

PYPROJECT = ROOT / "pyproject.toml"
COVERAGE_XML = ROOT / "coverage.xml"
COVERAGE_TARGETS = ("mcbe_editor", "main")
COVERAGE_IGNORES = ("tests/test_frontend_*.py", "tests/test_world_locks.py")
COVERAGE_INCLUDE = "main.py,mcbe_editor/*"


def _coverage_fail_under() -> float:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    value = data["tool"]["coverage"]["report"]["fail_under"]
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise RuntimeError("tool.coverage.report.fail_under must be numeric")
    return float(value)


def coverage_pytest_args(argv: list[str] | None = None) -> tuple[list[str], Path | None]:
    args = list(argv or [])
    args.extend(f"--ignore-glob={pattern}" for pattern in COVERAGE_IGNORES)

    default_basetemp: Path | None = None
    if not any(arg == "--basetemp" or arg.startswith("--basetemp=") for arg in args):
        default_basetemp = test_full._prepare_default_basetemp()
        args.append(f"--basetemp={default_basetemp}")
    else:
        test_full.prune_stale_test_artifacts()
    test_full._add_default_hang_diagnostics(args)
    return args, default_basetemp


def _run(command: list[str]) -> int:
    return subprocess.run(command, cwd=ROOT, check=False).returncode


def _render_threshold(value: float) -> str:
    return str(int(value)) if value.is_integer() else str(value)


def _coverage_percent_from_xml(path: Path) -> float:
    root = ET.parse(path).getroot()
    lines_valid = int(root.attrib.get("lines-valid", "0"))
    lines_covered = int(root.attrib.get("lines-covered", "0"))
    branches_valid = int(root.attrib.get("branches-valid", "0"))
    branches_covered = int(root.attrib.get("branches-covered", "0"))
    total_valid = lines_valid + branches_valid
    if total_valid == 0:
        return 100.0
    return 100.0 * (lines_covered + branches_covered) / total_valid


def main(argv: list[str] | None = None) -> int:
    missing = test_full._missing_core_dependencies()
    if missing:
        print(
            "Coverage suite requires installed core dependencies: " + ", ".join(missing),
            file=sys.stderr,
        )
        print(
            "Use Python 3.12 and install the locked build and dev requirements before running release/CI checks.",
            file=sys.stderr,
        )
        return 2

    args, default_basetemp = coverage_pytest_args(list(argv or sys.argv[1:]))
    COVERAGE_XML.unlink(missing_ok=True)
    erase_status = _run([sys.executable, "-m", "coverage", "erase"])
    if erase_status != 0:
        return erase_status

    test_status = _run(
        [
            sys.executable,
            "-m",
            "coverage",
            "run",
            f"--source={','.join(COVERAGE_TARGETS)}",
            "-m",
            "pytest",
            "tests",
            *args,
        ]
    )
    threshold = _coverage_fail_under()
    xml_status = _run(
        [
            sys.executable,
            "-m",
            "coverage",
            "xml",
            f"--include={COVERAGE_INCLUDE}",
            f"--fail-under={_render_threshold(threshold)}",
            "-o",
            str(COVERAGE_XML),
        ]
    )
    if COVERAGE_XML.is_file():
        measured = _coverage_percent_from_xml(COVERAGE_XML)
        print(f"Backend branch coverage: {measured:.1f}% (minimum {threshold:.1f}%)")

    if test_status == 0 and default_basetemp is not None:
        shutil.rmtree(default_basetemp, ignore_errors=True)
    elif default_basetemp is not None and default_basetemp.exists():
        print(f"Coverage test diagnostics retained at {default_basetemp}", file=sys.stderr)

    if test_status != 0:
        return test_status
    return xml_status


if __name__ == "__main__":
    raise SystemExit(main())
