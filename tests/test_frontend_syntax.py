"""Syntax-check every browser script with ``node --check`` (no npm dependencies)."""

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = ROOT / "static"
JS_FILES = sorted(STATIC_DIR.glob("*.js"))


def test_static_js_files_found() -> None:
    assert JS_FILES, f"Keine JS-Dateien unter {STATIC_DIR} gefunden."


@pytest.mark.parametrize("js_file", JS_FILES, ids=lambda path: path.name)
def test_static_js_syntax(js_file: Path) -> None:
    result = subprocess.run(
        ["node", "--check", str(js_file)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, f"Syntaxfehler in {js_file.name}:\n{result.stderr}{result.stdout}"
