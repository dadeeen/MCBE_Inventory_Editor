"""First launch and restart use persistent files, not replacement bundled copies."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PROBE = """
import json
from mcbe_editor import runtime_bootstrap as runtime
print(json.dumps({
    'items': str(runtime.PERSISTENT_ITEM_DB_PATH),
    'source': str(runtime.PERSISTENT_SOURCE_VERSION_PATH),
    'history': str(runtime.PERSISTENT_SOURCE_VERSION_HISTORY_PATH),
}))
"""


def _probe(environment, cwd):
    result = subprocess.run([sys.executable, "-c", PROBE], env=environment, cwd=cwd, text=True, capture_output=True, timeout=30, check=True)
    return {name: Path(path) for name, path in json.loads(result.stdout).items()}


@pytest.mark.parametrize("custom_paths", [False, True])
def test_runtime_bootstrap_seeds_once_and_preserves_updated_data_after_restart(tmp_path, custom_paths):
    env = {key: value for key, value in os.environ.items() if not key.startswith("MCBE_")}
    env.update(PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1", MCBE_DATA_ROOT=str(tmp_path / "persistent"))
    if custom_paths:
        env.update(
            MCBE_ITEM_DB_PATH="custom/item_db.json",
            MCBE_SOURCE_VERSION_PATH="custom/source_version.json",
            MCBE_SOURCE_VERSION_HISTORY_PATH="custom/source_version_history.json",
        )
    paths = _probe(env, tmp_path)
    bundled = {
        "items": ROOT / "mcbe_editor/resources/item_db.json",
        "source": ROOT / "mcbe_editor/resources/item_db_source.json",
        "history": ROOT / "mcbe_editor/resources/item_db_source_history.json",
    }
    for key, path in paths.items():
        assert path.is_absolute()
        assert path.is_relative_to(tmp_path)
        assert path.read_bytes() == bundled[key].read_bytes()
    replacement = b'{"operator_updated": true}\n'
    for path in paths.values():
        path.write_bytes(replacement)
    second = _probe(env, tmp_path)
    assert paths == second
    assert all(path.read_bytes() == replacement for path in second.values())
    assert not list(tmp_path.rglob("*.tmp"))
