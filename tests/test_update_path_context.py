"""Update children must use the same configured files as their parent."""

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from mcbe_editor import update_script_runner


@pytest.mark.parametrize("kind", ["db", "icons"])
@pytest.mark.parametrize("path_form", ["relative", "absolute", "home"])
def test_update_child_preserves_configured_path_context(tmp_path, monkeypatch, kind, path_form):
    project = Path(__file__).resolve().parents[1]
    caller = tmp_path / "caller"
    application = tmp_path / "application"
    home = tmp_path / "home"
    for directory in (caller, application, home):
        directory.mkdir()
    monkeypatch.chdir(caller)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    base = {"relative": "state", "absolute": str(caller / "state"), "home": "~/state"}[path_form]
    config = SimpleNamespace(
        data_root=base,
        item_db_path=str(Path(base) / "catalog" / "item_db.json"),
        update_cache_dir=str(Path(base) / "cache"),
        source_version_path=str(Path(base) / "meta" / "source_version.json"),
        source_version_history_path=str(Path(base) / "meta" / "source_version_history.json"),
    )
    # Match the caller's environment to its loaded configuration.
    monkeypatch.setenv("MCBE_DATA_ROOT", base)
    expected = {
        "DATA_ROOT": str(Path(config.data_root).expanduser().resolve()),
        "ITEM_DB_PATH": str(Path(config.item_db_path).expanduser().resolve()),
        "CACHE_DIR": str(Path(config.update_cache_dir).expanduser().resolve()),
    }
    if kind == "db":
        expected.update(
            SOURCE_VERSION_JSON=str(Path(config.source_version_path).expanduser().resolve()),
            SOURCE_VERSION_HISTORY=str(Path(config.source_version_history_path).expanduser().resolve()),
        )
    else:
        expected["ICON_ROOT"] = str(Path(expected["DATA_ROOT"]) / "icons" / "vanilla")
    catalog = Path(expected["ITEM_DB_PATH"])
    catalog.parent.mkdir(parents=True)
    catalog.write_text("{}\n", encoding="utf-8")

    # The runner starts a real child in a different cwd. Its entrypoint imports
    # the real updater without running a network update, and reports the paths
    # that the updater itself resolved. No path-selection logic is duplicated.
    scripts = application / "scripts"
    scripts.mkdir()
    (scripts / "__init__.py").write_text("", encoding="utf-8")
    source = project / "scripts" / f"update_{kind}.py"
    probe = f"""
import importlib.util, json, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location("update_path_probe", {str(source)!r})
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
print(json.dumps({{name: str(getattr(module, name).resolve()) for name in {list(expected)!r}}}))
"""
    (scripts / f"update_{kind}.py").write_text(probe, encoding="utf-8")
    before = dict(os.environ)
    status, output = getattr(update_script_runner, f"run_update_{kind}")(application, config)

    assert status == 0, output
    assert json.loads(output) == expected
    assert dict(os.environ) == before
    assert Path.cwd() == caller
    assert catalog.read_text(encoding="utf-8") == "{}\n"
    assert not (application / "state").exists()
