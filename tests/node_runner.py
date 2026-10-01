"""Run frontend JavaScript under Node for the tests.

Each call starts its own Node process from the repository root, so scripts
cannot share module state or leak globals into each other.
"""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TIMEOUT = 60


def run_node(source: str, *, timeout: float = DEFAULT_TIMEOUT) -> subprocess.CompletedProcess[str]:
    """Run ``source`` with ``node -e`` and fail the test unless it exits cleanly."""

    result = subprocess.run(
        ["node", "-e", source],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    return result
