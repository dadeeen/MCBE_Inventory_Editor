#!/usr/bin/env python3
"""Run dependency consistency and vulnerability checks.

This script is CI-friendly and intentionally does not upgrade packages.
It answers: "Are the currently pinned/installable dependencies known to be
broken or vulnerable?"
"""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIREMENT_FILES = [
    ROOT / "requirements" / "bootstrap.txt",
    ROOT / "requirements" / "build.txt",
    ROOT / "requirements" / "runtime.txt",
    ROOT / "requirements" / "docker.txt",
    ROOT / "requirements" / "dev.txt",
]


def default_requirement_files() -> list[Path]:
    return list(REQUIREMENT_FILES)


def run(cmd: list[str]) -> int:
    print("+", " ".join(cmd), flush=True)
    return subprocess.call(cmd, cwd=ROOT)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run pip check and pip-audit against project requirements.")
    parser.add_argument(
        "--require-pip-audit",
        action="store_true",
        help="Fail if pip-audit is not installed. Use this in CI/release builds.",
    )
    parser.add_argument(
        "--requirements",
        action="append",
        default=[],
        help="Compiled, hash-pinned requirement file to audit. Can be passed multiple times.",
    )
    args = parser.parse_args(argv)

    failures = 0
    failures += run([sys.executable, "-m", "pip", "check"]) != 0

    if importlib.util.find_spec("pip_audit") is None:
        print(
            "pip-audit is not installed. Install the locked build and dev requirements or run inside the dependency-audit Docker target.",
            file=sys.stderr,
        )
        return 2 if args.require_pip_audit else (1 if failures else 0)

    requirement_files = [Path(item) for item in args.requirements] if args.requirements else default_requirement_files()
    audited = 0
    for req_file in requirement_files:
        req_path = req_file if req_file.is_absolute() else ROOT / req_file
        if req_path.exists():
            audited += 1
            failures += (
                run(
                    [
                        sys.executable,
                        "-m",
                        "pip_audit",
                        "--disable-pip",
                        "--require-hashes",
                        "-r",
                        str(req_path),
                    ]
                )
                != 0
            )
        else:
            print(f"Requirement file not found: {req_path}", file=sys.stderr)
            failures += 1

    if audited == 0:
        print("No requirement files were audited.", file=sys.stderr)
        failures += 1

    if failures:
        print("Security/dependency check FAILED.", file=sys.stderr)
        return 1
    print("Security/dependency check OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
