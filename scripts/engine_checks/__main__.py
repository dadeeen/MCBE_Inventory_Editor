from __future__ import annotations

import argparse
from pathlib import Path

from .protocol import ProbeError
from .runner import ROOT, run_probe


def main() -> int:
    parser = argparse.ArgumentParser(description="Run opt-in checks against a locally supplied official Linux Bedrock server in Docker with no network.")
    parser.add_argument("--archive", required=True, type=Path, help="Unmodified official Linux BDS ZIP; never downloaded by this tool")
    parser.add_argument("--sha256", required=True, help="Expected archive SHA-256")
    parser.add_argument("--server-version", required=True, help="Exact version printed by BDS, e.g. 1.26.50.5")
    parser.add_argument("--image", default="mcbe-engine-check:local", help="Locally built developer image")
    parser.add_argument("--suite", choices=("catalog", "items"), default="items")
    parser.add_argument("--catalog", type=Path, help="Optional candidate item database; does not modify the bundled catalog")
    parser.add_argument("--work-root", type=Path, default=ROOT / ".engine-tests", help="Local generated artifacts; use an ignored directory")
    parser.add_argument("--timeout", type=float, default=300, help="Seconds per bounded engine phase")
    args = parser.parse_args()
    try:
        directory, report = run_probe(args.archive.resolve(), args.sha256, args.server_version, args.image, args.work_root, args.suite,
                                      args.timeout, args.catalog)
    except (ProbeError, OSError, ValueError) as exc:
        parser.exit(1, f"Engine check could not start: {exc}\n")
    print(f"Engine check: {report['status']}\nLocal report: {directory / 'run.json'}")
    if report.get("failure"):
        print(report["failure"])
    return {"pass": 0, "partial": 2}.get(report["status"], 1)


if __name__ == "__main__":
    raise SystemExit(main())
