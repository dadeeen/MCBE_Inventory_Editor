from unittest.mock import Mock

from mcbe_editor import app_info_routes


def _jsonify(payload):
    return ("json", payload)


def _render_template(template, **context):
    return ("template", template, context)


def _deps(**overrides):
    deps = app_info_routes.AppInfoRouteDeps(
        jsonify=_jsonify,
        render_template=_render_template,
        get_csrf_token=overrides.pop("get_csrf_token", Mock(return_value="csrf-token")),
        public_app_config=overrides.pop("public_app_config", Mock(return_value={"mode": "local"})),
        runtime_status_snapshot=overrides.pop("runtime_status_snapshot", Mock(return_value={"ok": True})),
        source_version_history_entries=overrides.pop("source_version_history_entries", Mock(return_value=[])),
    )
    assert not overrides
    return deps


def test_index_renders_csrf_and_public_config():
    deps = _deps()

    result = app_info_routes.index(deps)

    assert result == ("template", "index.html", {"csrf_token": "csrf-token", "app_config": {"mode": "local"}})


def test_runtime_status_wraps_snapshot():
    deps = _deps(runtime_status_snapshot=Mock(return_value={"status": "ok"}))

    result = app_info_routes.runtime_status(deps)

    assert result == ("json", {"success": True, "runtime_status": {"status": "ok"}})


def test_versions_renders_newest_entries_first():
    deps = _deps(source_version_history_entries=Mock(return_value=[{"id": 1}, {"id": 2}]))

    result = app_info_routes.versions(deps)

    assert result[0] == "template"
    assert result[1] == "versions.html"
    assert list(result[2]["entries"]) == [{"id": 2}, {"id": 1}]
