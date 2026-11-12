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
    parser.add_argument(
        "--suite",
        choices=("all", "catalog", "items", "extended", "special", "addons", "service", "villagers", "villager_trades", "village", "client"),
        default="all",
        help="villager_trades is explicit opt-in until its first verified BDS run; all retains the established suites",
    )
    parser.add_argument("--client-port", type=int, default=19134, help="Client/village suites: IPv4 loopback TCP+UDP port")
    parser.add_argument("--client-reloads", type=int, choices=(1, 2), help="Client suite only: 2 reloads (default, 3 joins) or 1 limited reload (2 joins)")
    parser.add_argument("--catalog", type=Path, help="Optional candidate item database; does not modify the bundled catalog")
    parser.add_argument("--vanilla-samples", type=Path, help="villager_trades: official Mojang bedrock-samples min ZIP for servers with packed Vanilla files")
    parser.add_argument("--samples-sha256", help="Expected SHA-256 of the samples ZIP")
    parser.add_argument("--samples-version", help="Exact stable samples release, e.g. v1.26.60.5")
    parser.add_argument("--work-root", type=Path, default=ROOT / ".engine-tests", help="Local generated artifacts; use an ignored directory")
    parser.add_argument("--timeout", type=float, default=300, help="Seconds per bounded engine phase")
    args = parser.parse_args()
    if args.client_reloads is not None and args.suite != "client":
        parser.error("--client-reloads requires --suite client")
    samples_options = {}
    if any(value is not None for value in (args.vanilla_samples, args.samples_sha256, args.samples_version)):
        samples_options = {"samples_archive": args.vanilla_samples, "samples_sha256": args.samples_sha256, "samples_version": args.samples_version}
    statuses = []
    try:
        for suite in ("extended", "special", "service", "addons", "villagers") if args.suite == "all" else (args.suite,):
            directory, report = run_probe(
                args.archive.resolve(),
                args.sha256,
                args.server_version,
                args.image,
                args.work_root,
                suite,
                args.timeout,
                args.catalog,
                client_port=args.client_port,
                client_reloads=2 if args.client_reloads is None else args.client_reloads,
                **samples_options,
            )
            statuses.append(report["status"])
            print(f"Engine check ({suite}): {report['status']}\nLocal report: {directory / 'run.json'}", flush=True)
            if report.get("failure"):
                print(report["failure"], flush=True)
    except (ProbeError, OSError, ValueError) as exc:
        parser.exit(1, f"Engine check could not start: {exc}\n")
    return 1 if any(status not in {"pass", "partial"} for status in statuses) else 2 if "partial" in statuses else 0


if __name__ == "__main__":
    raise SystemExit(main())
