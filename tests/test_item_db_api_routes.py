from types import SimpleNamespace
from unittest.mock import Mock, patch

from mcbe_editor import item_db_api_routes


def _jsonify(payload):
    return ("json", payload)


def _api_error(message, status=400, **_kwargs):
    return ("error", str(message), status)


def _json_bool(data, key, default=False):
    value = data.get(key, default)
    if isinstance(value, bool):
        return value
    if value in ("true", "1", 1):
        return True
    if value in ("false", "0", 0):
        return False
    raise ValueError(f"Feld '{key}' muss ein boolescher Wert sein.")


def _deps(**overrides):
    deps = item_db_api_routes.ItemDbRouteDeps(
        source_version_history_path=overrides.pop("source_version_history_path", "history.json"),
        jsonify=_jsonify,
        api_error=_api_error,
        log_api_exception=overrides.pop("log_api_exception", Mock()),
        json_bool=overrides.pop("json_bool", _json_bool),
        run_update_db=overrides.pop("run_update_db", Mock(return_value=(0, "ok"))),
        looks_like_network_failure=overrides.pop("looks_like_network_failure", Mock(return_value=False)),
        item_db_status_snapshot=overrides.pop("item_db_status_snapshot", Mock(return_value={"status": "ok"})),
        source_version_history_entries=overrides.pop("source_version_history_entries", Mock(return_value=[])),
        reload_item_db_after_update=overrides.pop("reload_item_db_after_update", Mock(return_value={"reloaded": True})),
        audit_event=overrides.pop("audit_event", Mock()),
        logger=overrides.pop("logger", SimpleNamespace(warning=Mock())),
    )
    assert not overrides
    return deps


def test_update_db_rejects_invalid_scope_without_running_update():
    run_update_db = Mock()
    deps = _deps(run_update_db=run_update_db)

    result = item_db_api_routes.update_db({"only": "blocks"}, deps)

    assert result == ("error", "Ungültiger Update-Bereich. Erlaubt sind: items, effects, enchants.", 400)
    run_update_db.assert_not_called()


def test_update_db_rejects_falsey_non_string_scope_without_running_update():
    run_update_db = Mock()
    deps = _deps(run_update_db=run_update_db)

    result = item_db_api_routes.update_db({"only": []}, deps)

    assert result == ("error", "Feld 'only' muss ein Textwert sein.", 400)
    run_update_db.assert_not_called()


def test_update_db_successful_non_dry_run_merges_reload_payload():
    reload_item_db = Mock(return_value={"reloaded": True, "item_db": {"status": "ok"}})
    deps = _deps(reload_item_db_after_update=reload_item_db)

    result = item_db_api_routes.update_db({"dry_run": False, "force": True, "only": "items"}, deps)

    assert result == (
        "json",
        {
            "success": True,
            "returncode": 0,
            "output": "ok",
            "update_committed": True,
            "reloaded": True,
            "item_db": {"status": "ok"},
        },
    )
    deps.run_update_db.assert_called_once_with(dry_run=False, force=True, only="items", use_cache=True)
    reload_item_db.assert_called_once()
    deps.audit_event.assert_called_once()


def test_update_db_rejects_write_without_explicit_confirmation():
    run_update_db = Mock()
    deps = _deps(run_update_db=run_update_db)

    result = item_db_api_routes.update_db({"dry_run": False, "force": False}, deps)

    assert result == ("error", "Ein schreibendes Item-DB-Update erfordert eine ausdrückliche Bestätigung.", 400)
    run_update_db.assert_not_called()


def test_update_db_network_failure_adds_hint_and_logs_failure():
    logger = SimpleNamespace(warning=Mock())
    deps = _deps(
        run_update_db=Mock(return_value=(1, "Temporary failure in name resolution")),
        looks_like_network_failure=Mock(return_value=True),
        logger=logger,
    )

    result = item_db_api_routes.update_db({}, deps)

    assert result[0] == "json"
    payload = result[1]
    assert payload["success"] is False
    assert payload["returncode"] == 1
    assert payload["error"] == "Item-DB-Update konnte die Online-Quellen nicht erreichen."
    assert "HTTPS-Ausgang" in payload["hint"]
    logger.warning.assert_called_once()
    deps.audit_event.assert_called_once()


def test_item_db_versions_returns_newest_first_with_configured_path():
    entries = [{"id": 1}, {"id": 2}]
    deps = _deps(source_version_history_entries=Mock(return_value=entries), source_version_history_path="custom-history.json")

    result = item_db_api_routes.item_db_versions(deps)

    assert result == (
        "json",
        {
            "success": True,
            "entries": [{"id": 2}, {"id": 1}],
            "count": 2,
            "path": "custom-history.json",
        },
    )


def test_item_db_update_guard_serializes_complete_updates():
    import threading
    import time

    import main

    active = 0
    max_active = 0
    active_lock = threading.Lock()
    first_entered = threading.Event()
    release_first = threading.Event()

    @main.item_db_update_guard
    def guarded_update(name):
        nonlocal active, max_active
        with active_lock:
            active += 1
            max_active = max(max_active, active)
        if name == "first":
            first_entered.set()
            assert release_first.wait(timeout=2)
        with active_lock:
            active -= 1
        return name

    results = []
    first = threading.Thread(target=lambda: results.append(guarded_update("first")))
    second = threading.Thread(target=lambda: results.append(guarded_update("second")))
    first.start()
    assert first_entered.wait(timeout=2)
    second.start()
    time.sleep(0.05)
    assert max_active == 1
    release_first.set()
    first.join(timeout=2)
    second.join(timeout=2)

    assert sorted(results) == ["first", "second"]
    assert max_active == 1


def test_worker_lazily_reloads_item_db_after_external_commit():
    import main

    old_signature = (1, 1, 1, 1, 1)
    new_signature = (1, 2, 2, 2, 2)
    reload_item_db = Mock(return_value={"reloaded": True})
    with (
        patch.object(main, "_ITEM_DB_RUNTIME_SIGNATURE", old_signature),
        patch.object(main, "_item_db_file_signature", Mock(return_value=new_signature)),
        patch.object(main, "reload_item_db_after_update", reload_item_db),
    ):
        assert main.reload_item_db_after_external_worker_update() is None

    reload_item_db.assert_called_once_with()


def test_update_db_frontend_disables_controls_and_ignores_duplicate_run():
    import subprocess
    import textwrap
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            "node",
            "-e",
            textwrap.dedent(
                r"""
                const assert = require("assert");
                const fs = require("fs");
                const vm = require("vm");
                const code = fs.readFileSync("static/update_db_view.js", "utf8");
                const context = { window: { fetch: async () => ({}) }, console };
                vm.runInNewContext(code, context, { filename: "static/update_db_view.js" });
                const view = context.window.MCBEUpdateDbView;
                let resolveFetch;
                let fetchCount = 0;
                const fetchPromise = new Promise(resolve => { resolveFetch = resolve; });
                const dryRunButton = { disabled: false, addEventListener() {} };
                const applyButton = { disabled: false, addEventListener() {} };
                const onlySelect = { disabled: false, value: "items", options: [{ text: "Items" }], selectedIndex: 0 };
                const useCacheCheckbox = { disabled: false, checked: true };
                const outputEl = { textContent: "Noch kein Update ausgeführt.", scrollTop: 0, scrollHeight: 0 };
                const controller = view.createUpdateDbController({
                    outputEl,
                    dryRunButton,
                    applyButton,
                    onlySelect,
                    useCacheCheckbox,
                    fetchImpl: async () => { fetchCount += 1; return fetchPromise; },
                    parseJsonResponse: response => response.json(),
                    withCsrf: () => ({}),
                });

                (async () => {
                    const first = controller.run(true, false);
                    const second = controller.run(false, true);
                    assert.strictEqual(controller.isRunning(), true);
                    assert.strictEqual(fetchCount, 1);
                    assert.strictEqual(dryRunButton.disabled, true);
                    assert.strictEqual(applyButton.disabled, true);
                    assert.strictEqual(onlySelect.disabled, true);
                    assert.strictEqual(useCacheCheckbox.disabled, true);
                    resolveFetch({ json: async () => ({ success: true, output: "ok" }) });
                    const [firstResult, secondResult] = await Promise.all([first, second]);
                    assert.strictEqual(firstResult.success, true);
                    assert.strictEqual(secondResult.success, false);
                    assert.strictEqual(secondResult.busy, true);
                    assert.strictEqual(controller.isRunning(), false);
                    assert.strictEqual(dryRunButton.disabled, false);
                    assert.strictEqual(applyButton.disabled, false);
                    assert.strictEqual(onlySelect.disabled, false);
                    assert.strictEqual(useCacheCheckbox.disabled, false);
                })().catch(error => { console.error(error); process.exit(1); });
                """
            ),
        ],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout


def test_update_db_reports_reload_failure_after_successful_commit():
    reload_error = RuntimeError("reload failed")
    deps = _deps(reload_item_db_after_update=Mock(side_effect=reload_error))

    result = item_db_api_routes.update_db({"dry_run": False, "force": True}, deps)

    assert result[0] == "json"
    payload = result[1]
    assert payload["success"] is True
    assert payload["update_committed"] is True
    assert payload["reloaded"] is False
    assert "Anwendung neu starten" in payload["reload_warning"]
    deps.log_api_exception.assert_called_once_with("item_db_reload_after_update", reload_error)


def test_update_db_frontend_reports_post_commit_reload_warning():
    import subprocess
    import textwrap
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            "node",
            "-e",
            textwrap.dedent(
                r"""
                const assert = require("assert");
                const fs = require("fs");
                const vm = require("vm");
                const code = fs.readFileSync("static/update_db_view.js", "utf8");
                const context = { window: { fetch: async () => ({}) }, console };
                vm.runInNewContext(code, context, { filename: "static/update_db_view.js" });
                const view = context.window.MCBEUpdateDbView;
                const outputEl = { textContent: "Noch kein Update ausgeführt.", scrollTop: 0, scrollHeight: 0 };
                const toasts = [];
                const statuses = [];
                const controller = view.createUpdateDbController({
                    outputEl,
                    fetchImpl: async () => ({
                        json: async () => ({
                            success: true,
                            update_committed: true,
                            reloaded: false,
                            reload_warning: "Gespeichert, Neustart nötig.",
                        }),
                    }),
                    parseJsonResponse: response => response.json(),
                    withCsrf: () => ({}),
                    showToast: (...args) => toasts.push(args),
                    logStatus: (...args) => statuses.push(args),
                });

                (async () => {
                    const updateResult = await controller.run(false, true);
                    assert.strictEqual(updateResult.success, true);
                    assert.strictEqual(updateResult.reloaded, false);
                    assert.match(outputEl.textContent, /Gespeichert, Neustart nötig/);
                    assert.strictEqual(toasts.at(-1)[1], "warning");
                    assert.strictEqual(statuses.at(-1)[1], "warning");
                    assert.doesNotMatch(outputEl.textContent, /Dry-Run abgeschlossen/);
                })().catch(error => { console.error(error); process.exit(1); });
                """
            ),
        ],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
