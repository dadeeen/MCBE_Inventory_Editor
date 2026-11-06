"""Generate narrow AppArmor user-namespace allowances for managed test browsers."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path, PurePath

ROOT = Path(__file__).resolve().parents[1]
USERNS_RESTRICTION = Path("/proc/sys/kernel/apparmor_restrict_unprivileged_userns")


def apparmor_profile(executables: list[PurePath]) -> str:
    profiles = ["abi <abi/4.0>,", "include <tunables/global>", ""]
    for executable in executables:
        target = str(executable)
        if not executable.is_absolute() or any(character in target for character in '\\"\n\r\0*?[]{}'):
            raise ValueError("The browser path must be absolute and contain no AppArmor pattern characters")
        name = hashlib.sha256(target.encode()).hexdigest()[:16]
        profiles.extend([f'profile playwright-{name} "{target}" flags=(unconfined) {{', "  userns,", "}", ""])
    return "\n".join(profiles)


def browser_executables(root: Path, cache: Path) -> list[Path]:
    manifest = json.loads((root / "node_modules/playwright-core/browsers.json").read_text(encoding="utf-8"))
    cache = cache.resolve()
    executables = []
    for browser in manifest["browsers"]:
        if browser["name"] not in {"chromium", "chromium-headless-shell"}:
            continue
        revision = str(browser["revision"])
        if not revision.isdecimal():
            raise ValueError("Unexpected managed browser revision")
        directory = cache / f"{browser['name'].replace('-', '_')}-{revision}"
        matches = [*directory.glob("*/chrome"), *directory.glob("*/chrome-headless-shell"), *directory.glob("*/headless_shell")]
        for candidate in matches:
            resolved = candidate.resolve(strict=True)
            if not resolved.is_relative_to(cache) or not resolved.is_file():
                raise ValueError("Managed browser executable is outside its cache")
            executables.append(resolved)
    if not executables:
        raise ValueError("Install the matching managed Chromium before preparing AppArmor")
    return sorted(set(executables))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, type=Path)
    args = parser.parse_args()
    if sys.platform != "linux" or not USERNS_RESTRICTION.is_file() or USERNS_RESTRICTION.read_text().strip() == "0":
        print("No AppArmor user-namespace allowance required.")
        return 0
    configured = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if configured == "0":
        cache = ROOT / "node_modules/playwright-core/.local-browsers"
    elif configured:
        cache = Path(configured).expanduser()
    else:
        cache = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "ms-playwright"
    executables = browser_executables(ROOT, cache)
    args.profile.write_text(apparmor_profile(executables), encoding="utf-8")
    print(f"Generated AppArmor user-namespace allowances for {len(executables)} managed browser executables.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
