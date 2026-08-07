#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / ".pip-tools-cache"
REQUIREMENTS_DIR = ROOT / "requirements"
BUILD_CONSTRAINTS = REQUIREMENTS_DIR / "build-constraints.txt"
LOCK_TARGETS = [
    (REQUIREMENTS_DIR / "bootstrap.in", REQUIREMENTS_DIR / "bootstrap.txt"),
    (REQUIREMENTS_DIR / "runtime.in", REQUIREMENTS_DIR / "runtime.txt"),
    (REQUIREMENTS_DIR / "docker.in", REQUIREMENTS_DIR / "docker.txt"),
    (REQUIREMENTS_DIR / "dev.in", REQUIREMENTS_DIR / "dev.txt"),
]


def _piptools_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PIP_BUILD_CONSTRAINT"] = str(BUILD_CONSTRAINTS)
    return env


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, cwd=ROOT, check=True, env=_piptools_env())


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _normalized_lockfile_text(path: Path) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    return "\n".join(line for line in lines if not _is_piptools_comment_noise(line)) + "\n"


def _is_piptools_comment_noise(line: str) -> bool:
    stripped = line.strip()
    return line.startswith("#    pip-compile ") or stripped.startswith("# via") or stripped.startswith("#   ")


def _sync_compatibility_locks(*, check: bool) -> bool:
    ok = True
    for _, target in LOCK_TARGETS:
        wrapper = target.with_suffix(".lock")
        expected = f"-r {target.name}\n"
        if check:
            if not wrapper.exists() or wrapper.read_text(encoding="utf-8") != expected:
                print(f"ERROR: Compatibility lock is out of date: {_rel(wrapper)}", file=sys.stderr)
                ok = False
        else:
            wrapper.write_text(expected, encoding="utf-8")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate hash-locked Python dependency files with pip-tools for the active target runtime.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate committed lockfiles without opportunistically upgrading already-pinned transitive dependencies.",
    )
    args = parser.parse_args()

    if not ((3, 12) <= sys.version_info[:2] < (3, 13)):
        print("ERROR: This project targets Python >=3.12,<3.13. Generate lockfiles with Python 3.12.", file=sys.stderr)
        return 2

    tmp_dir = ROOT / ".lockcheck" if args.check else ROOT
    if args.check:
        tmp_dir.mkdir(exist_ok=True)

    for source, target in LOCK_TARGETS:
        output = tmp_dir / target.name if args.check else target
        if args.check:
            if not target.exists():
                print(f"ERROR: Missing committed lockfile: {_rel(target)}", file=sys.stderr)
                return 1
            # pip-compile intentionally reuses pins from an existing output
            # file unless inputs or constraints force a change. Seeding the
            # check output with the committed lock keeps CI deterministic when
            # unrelated transitive releases appear on PyPI.
            shutil.copyfile(target, output)
        cmd = [
            sys.executable,
            "-m",
            "piptools",
            "compile",
            "--generate-hashes",
            "--allow-unsafe",
            "--resolver=backtracking",
            "--strip-extras",
            "--cache-dir",
            _rel(CACHE_DIR),
            "--output-file",
            _rel(output),
            _rel(source),
        ]
        run(cmd)
        if args.check and _normalized_lockfile_text(output) != _normalized_lockfile_text(target):
            print(f"ERROR: Lockfile is out of date: {_rel(target)}. Run python scripts/compile_lockfiles.py", file=sys.stderr)
            return 1
    if args.check:
        for _, target in LOCK_TARGETS:
            (tmp_dir / target.name).unlink(missing_ok=True)
        with os.scandir(tmp_dir) as entries:
            if not any(True for _ in entries):
                tmp_dir.rmdir()
    if not _sync_compatibility_locks(check=args.check):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
