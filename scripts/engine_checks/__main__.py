from __future__ import annotations

import argparse
from pathlib import Path

from .protocol import ProbeError
from .runner import ROOT, run_probe


def main() -> int:
    parser = argparse.ArgumentParser(description="Run opt-in checks against a locally supplied official Linux Bedrock server in isolated Docker.")
    parser.add_argument("--archive", required=True, type=Path, help="Unmodified official Linux BDS ZIP; never downloaded by this tool")
    parser.add_argument("--sha256", required=True, help="Expected archive SHA-256")
    parser.add_argument("--server-version", required=True, help="Exact version printed by BDS, e.g. 1.26.50.5")
    parser.add_argument("--image", default="mcbe-engine-check:local", help="Locally built developer image")
    parser.add_argument("--suite", choices=("all", "catalog", "items", "extended", "addons", "service", "client"), default="all")
    parser.add_argument("--client-port", type=int, default=19134, help="Client suite only: IPv4 loopback TCP+UDP port; three real client joins required")
    parser.add_argument("--catalog", type=Path, help="Optional candidate item database; does not modify the bundled catalog")
    parser.add_argument("--work-root", type=Path, default=ROOT / ".engine-tests", help="Local generated artifacts; use an ignored directory")
    parser.add_argument("--timeout", type=float, default=300, help="Seconds per bounded engine phase")
    args = parser.parse_args()
    statuses = []
    try:
        for suite in ("extended", "service", "addons") if args.suite == "all" else (args.suite,):
            directory, report = run_probe(args.archive.resolve(), args.sha256, args.server_version, args.image, args.work_root, suite,
                                          args.timeout, args.catalog, client_port=args.client_port)
            statuses.append(report["status"])
            print(f"Engine check ({suite}): {report['status']}\nLocal report: {directory / 'run.json'}", flush=True)
            if report.get("failure"):
                print(report["failure"], flush=True)
    except (ProbeError, OSError, ValueError) as exc:
        parser.exit(1, f"Engine check could not start: {exc}\n")
    return 1 if any(status not in {"pass", "partial"} for status in statuses) else 2 if "partial" in statuses else 0


if __name__ == "__main__":
    raise SystemExit(main())
