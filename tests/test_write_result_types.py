"""Invalid recovery/result combinations must fail the configured static gate."""

import subprocess
import sys
from pathlib import Path


def test_write_result_types_reject_contradictory_outcomes(tmp_path):
    source = tmp_path / "result_contract.py"
    source.write_text(
        "from mcbe_editor.write_results import SaveNoOp, SavePostWriteFailure\n"
        "from mcbe_editor.services import BedrockEditorService\n"
        "noop: SaveNoOp = {\n"
        " 'success': True, 'no_op': False, 'backup_file': 'backup.zip',\n"
        " 'message': '', 'player_revision': 'revision',\n"
        " 'item_source_digests': {}, 'saved_items': {}}\n"
        "failure: SavePostWriteFailure = {\n"
        " 'success': False, 'no_op': False, 'write_committed': False,\n"
        " 'validation_failed': True, 'backup_file': None, 'message': '', 'error': '',\n"
        " 'item_source_digests': {}, 'saved_items': {}}\n"
        "def invalid_callbacks(service: BedrockEditorService) -> None:\n"
        " service.save_player('world', 'player', [], {}, pre_write_check=lambda: 1)\n"
        " service.import_player('export', 'world', 'player', write_gate_check=lambda: 1)\n"
        " service.restore_backup('world', 'backup', pre_restore_check=lambda: 1)\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, "-m", "mypy", "--no-pretty", "--no-incremental", "--cache-dir", str(tmp_path / "cache"), str(source)],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    for field in ("no_op", "backup_file", "write_committed"):
        assert f'TypedDict item "{field}"' in result.stdout, result.stdout
    for callback in ("pre_write_check", "write_gate_check", "pre_restore_check"):
        assert f'Argument "{callback}"' in result.stdout, result.stdout
