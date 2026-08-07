import json

from mcbe_editor.audit import sanitize_detail, sanitize_error


def test_sanitize_error_removes_full_windows_and_posix_paths():
    error = "Backup failed at C:\\Users\\test\\minecraftWorlds\\SecretWorld\\db\\LOCK and /home/test/worlds/SecretWorld/db/LOCK"

    sanitized = sanitize_error(error)

    assert sanitized is not None
    assert "C:\\Users" not in sanitized
    assert "/home/test" not in sanitized
    assert "SecretWorld" not in sanitized
    assert "LOCK" in sanitized


def test_sanitize_error_removes_quoted_paths_with_spaces():
    error = "Backup failed at 'C:\\Users\\Jane Doe\\Secret World\\db\\LOCK' and \"/home/jane doe/Secret World/db/LOCK\""

    sanitized = sanitize_error(error)

    assert sanitized is not None
    assert "Jane Doe" not in sanitized
    assert "jane doe" not in sanitized
    assert "Secret World" not in sanitized
    assert sanitized.count("LOCK") == 2


def test_sanitize_detail_converts_non_finite_floats_to_valid_json_values():
    sanitized = sanitize_detail({"nan": float("nan"), "positive": float("inf"), "negative": float("-inf")})

    assert sanitized == {"nan": "nan", "positive": "inf", "negative": "-inf"}
    assert json.loads(json.dumps(sanitized, allow_nan=False)) == sanitized
