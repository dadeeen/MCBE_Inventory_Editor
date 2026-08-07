from __future__ import annotations

import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _script_names() -> list[str]:
    html = _read("templates/index.html")
    return re.findall(r"filename='([^']+\.js)'", html)


def _assert_before_app(script: str) -> None:
    scripts = _script_names()
    assert script in scripts
    assert scripts.index(script) < scripts.index("app.js")


def _assert_order(before: str, after: str) -> None:
    scripts = _script_names()
    assert before in scripts
    assert after in scripts
    assert scripts.index(before) < scripts.index(after)


def test_dirty_banner_is_hidden_on_world_view() -> None:
    css = _read("static/style.css")

    assert 'body[data-workflow-view="world"] .dirty-banner' in css


def test_dirty_loaded_world_is_marked_inline() -> None:
    app_js = _read("static/app.js")
    world_cards_js = _read("static/world_cards_view.js")
    world_status_js = _read("static/world_status_view.js")
    css = _read("static/style.css")

    assert "window.MCBEWorldStatusView.createInventoryWorldStatusController" in app_js
    assert "window.MCBEWorldBrowser.createInventoryWorldBrowserController" in app_js
    assert "updateSelectedWorld," in app_js
    assert "selectedWorldDirtyHint" in world_status_js
    assert "applySelectedWorldDirtyHint" in world_status_js
    assert "hasUnsavedChanges" in world_cards_js
    assert "world-card-dirty" in world_cards_js
    assert "world-card-badges" in css
    assert "selected-world-safety-note" in css


def test_dirty_header_notice_is_transient() -> None:
    app_js = _read("static/app.js")
    session_log_js = _read("static/session_log.js")
    store_js = _read("static/status_store.js")
    stack_view_js = _read("static/status_stack_view.js")
    workflow_js = _read("static/workflow_state.js")

    _assert_order("status_store.js", "status_stack_view.js")
    _assert_before_app("status_store.js")
    _assert_before_app("status_stack_view.js")
    _assert_before_app("session_log.js")
    _assert_before_app("workflow_state.js")
    assert "window.MCBESessionLog.createInventoryStatusSessionController" in app_js
    assert "window.MCBEWorkflowState.createDirtyStateController" in app_js
    assert "statusSessionController.clearStatus(key)" in app_js
    assert "visibleNotices({ isDirty: getIsDirty() })" in session_log_js
    assert "statusNoticeStore?.removeNotice(key)" in session_log_js
    assert "key: transientDirtyNoticeCategory" in workflow_js
    assert "active: true" in workflow_js
    assert "clearStatus(transientDirtyNoticeCategory)" in workflow_js
    assert 'const TRANSIENT_DIRTY_NOTICE_CATEGORY = "dirty";' in store_js
    assert "function createStatusStore" in store_js
    assert "notices.filter(entry => entry.category !== TRANSIENT_DIRTY_NOTICE_CATEGORY)" in store_js
    assert "function isTransientDirtyStatusText(text)" in store_js
    assert "function applyStatusStackModel" in stack_view_js
    assert "function statusStackModel" in stack_view_js
    assert "function statusStackPanelHtml" in stack_view_js
    assert "window.MCBEStatusStackView" in stack_view_js
    assert 'id="statusStackLive" role="status" aria-live="polite"' in _read("templates/index.html")
    assert 'id="statusStackPanel" role="log"' in _read("templates/index.html")


EXPECTED_NAMESPACES: dict[str, tuple[str, ...]] = {
    "api_client.js": ("MCBEApiClient",),
    "app_bootstrap.js": ("MCBEAppBootstrap",),
    "html_utils.js": ("MCBEHtmlUtils", "MCBEAppDomRefs"),
    "status_store.js": ("MCBEStatusStore",),
    "status_stack_view.js": ("MCBEStatusStackView",),
    "state_snapshot.js": ("MCBEStateSnapshot",),
    "inventory_state.js": ("MCBEInventoryState",),
    "selection_state.js": ("MCBESelectionState",),
    "inventory_clipboard_logic.js": ("MCBEInventoryClipboardLogic",),
    "slot_interaction_logic.js": ("MCBESlotInteractionLogic",),
    "bulk_edit_logic.js": ("MCBEBulkEditLogic",),
    "entity_variant_editor.js": ("MCBEEntityVariantEditor",),
    "slot_detail_logic.js": ("MCBESlotDetailLogic",),
    "enchantment_editor_logic.js": ("MCBEEnchantmentEditorLogic",),
    "session_log.js": ("MCBESessionLog",),
    "item_catalog.js": ("MCBEItemCatalog",),
    "item_availability.js": ("MCBEItemAvailability",),
    "item_browser_logic.js": ("MCBEItemBrowserLogic",),
    "item_browser_controller.js": ("MCBEItemBrowserController",),
    "enchantments_view.js": ("MCBEEnchantmentsView",),
    "slot_display.js": ("MCBESlotDisplay",),
    "inventory_rendering.js": ("MCBEInventoryRendering",),
    "inventory_view_preferences.js": ("MCBEInventoryViewPreferences",),
    "world_cards_view.js": ("MCBEWorldCardsView",),
    "world_browser.js": ("MCBEWorldBrowser",),
    "world_analysis_view.js": ("MCBEWorldAnalysisView",),
    "world_status_view.js": ("MCBEWorldStatusView",),
    "workflow_state.js": ("MCBEWorkflowState",),
    "workspace_view.js": ("MCBEWorkspaceView",),
    "theme_controller.js": ("MCBEThemeController",),
    "ui_feedback.js": ("MCBEUiFeedback",),
    "undo_redo_view.js": ("MCBEUndoRedoView",),
    "undo_redo_controller.js": ("MCBEUndoRedoController",),
    "ability_state.js": ("MCBEAbilityState",),
    "ability_view.js": ("MCBEAbilityView",),
    "analysis_logic.js": ("MCBEAnalysisLogic",),
    "backups_view.js": ("MCBEBackupsView",),
    "backup_restore_logic.js": ("MCBEBackupRestoreLogic",),
    "data_source_view.js": ("MCBEDataSourceView",),
    "status_center_view.js": ("MCBEStatusCenterView",),
    "diagnostics_view.js": ("MCBEDiagnosticsView",),
    "effects_logic.js": ("MCBEEffectsLogic",),
    "effects_view.js": ("MCBEEffectsView",),
    "icon_manager_view.js": ("MCBEIconManagerView",),
    "icon_sources_controller.js": ("MCBEIconSourcesController",),
    "nbt_inspector.js": ("MCBENbtInspector",),
    "player_compare_view.js": ("MCBEPlayerCompareView",),
    "player_diagnostics.js": ("MCBEPlayerDiagnostics",),
    "player_import_view.js": ("MCBEPlayerImportView",),
    "player_transfer_logic.js": ("MCBEPlayerTransferLogic",),
    "player_inventory_summary_view.js": ("MCBEPlayerInventorySummaryView",),
    "player_view_models.js": ("MCBEPlayerViewModels",),
    "player_api.js": ("MCBEPlayerApi",),
    "player_load_controller.js": ("MCBEPlayerLoadController",),
    "player_load_app.js": ("MCBEPlayerLoadApp",),
    "player_tools.js": ("MCBEPlayerTools",),
    "mount_api.js": ("MCBEMountApi",),
    "mount_view.js": ("MCBEMountView",),
    "mount_controller.js": ("MCBEMountController",),
    "presence_view.js": ("MCBEPresenceView",),
    "restore_review.js": ("MCBERestoreReview",),
    "scan_paths_view.js": ("MCBEScanPathsView",),
    "scan_paths_controller.js": ("MCBEScanPathsController",),
    "save_logic.js": ("MCBESaveLogic",),
    "save_payload_logic.js": ("MCBESavePayloadLogic",),
    "save_controller.js": ("MCBESaveController",),
    "save_review_view.js": ("MCBESaveReviewView",),
    "save_workflow_view.js": ("MCBESaveWorkflowView",),
    "write_status_view.js": ("MCBEWriteStatusView",),
    "update_db_view.js": ("MCBEUpdateDbView",),
    "app_state_bridge.js": ("MCBEAppStateBridge",),
}


@pytest.mark.parametrize("script,namespaces", sorted(EXPECTED_NAMESPACES.items()))
def test_frontend_modules_publish_namespaces_before_app(script: str, namespaces: tuple[str, ...]) -> None:
    source = _read(f"static/{script}")

    _assert_before_app(script)
    for namespace in namespaces:
        assert f"window.{namespace}" in source


DEPENDENCY_ORDER = [
    ("api_client.js", "html_utils.js"),
    ("api_client.js", "app_bootstrap.js"),
    ("app_bootstrap.js", "app.js"),
    ("status_store.js", "status_stack_view.js"),
    ("inventory_state.js", "inventory_clipboard_logic.js"),
    ("selection_state.js", "inventory_clipboard_logic.js"),
    ("inventory_state.js", "slot_interaction_logic.js"),
    ("selection_state.js", "slot_interaction_logic.js"),
    ("inventory_state.js", "bulk_edit_logic.js"),
    ("selection_state.js", "bulk_edit_logic.js"),
    ("bulk_edit_logic.js", "slot_detail_logic.js"),
    ("entity_variant_editor.js", "slot_detail_logic.js"),
    ("slot_detail_logic.js", "enchantment_editor_logic.js"),
    ("item_browser_logic.js", "item_browser_controller.js"),
    ("item_availability.js", "app.js"),
    ("item_browser_logic.js", "enchantments_view.js"),
    ("inventory_rendering.js", "inventory_view_preferences.js"),
    ("world_cards_view.js", "world_browser.js"),
    ("workspace_view.js", "theme_controller.js"),
    ("undo_redo_view.js", "undo_redo_controller.js"),
    ("ability_state.js", "ability_view.js"),
    ("backups_view.js", "backup_restore_logic.js"),
    ("effects_logic.js", "effects_view.js"),
    ("icon_manager_view.js", "icon_sources_controller.js"),
    ("player_import_view.js", "player_transfer_logic.js"),
    ("player_transfer_logic.js", "player_inventory_summary_view.js"),
    ("player_api.js", "player_load_controller.js"),
    ("player_api.js", "player_tools.js"),
    ("player_view_models.js", "player_load_controller.js"),
    ("player_view_models.js", "player_tools.js"),
    ("mount_api.js", "mount_controller.js"),
    ("mount_view.js", "mount_controller.js"),
    ("mount_controller.js", "app.js"),
    ("player_load_controller.js", "player_load_app.js"),
    ("player_load_app.js", "app.js"),
    ("player_load_controller.js", "app.js"),
    ("player_inventory_summary_view.js", "player_tools.js"),
    ("scan_paths_view.js", "scan_paths_controller.js"),
    ("save_logic.js", "save_payload_logic.js"),
    ("save_payload_logic.js", "save_controller.js"),
    ("app_state_bridge.js", "app.js"),
]


@pytest.mark.parametrize("before,after", DEPENDENCY_ORDER)
def test_frontend_dependency_scripts_keep_required_order(before: str, after: str) -> None:
    _assert_order(before, after)


def test_app_global_dependencies_are_defined_by_preloaded_scripts() -> None:
    scripts = _script_names()
    before_app = scripts[: scripts.index("app.js")]
    definitions: dict[str, str] = {}
    for script in before_app:
        source_path = ROOT / "static" / script
        if not source_path.exists():
            continue
        source = source_path.read_text(encoding="utf-8")
        for namespace in re.findall(r"window\.(MCBE[A-Za-z0-9_]+)\s*=", source):
            definitions.setdefault(namespace, script)

    app_uses = set(re.findall(r"window\.(MCBE[A-Za-z0-9_]+)", _read("static/app.js")))
    missing = sorted(namespace for namespace in app_uses if namespace not in definitions)

    assert missing == []


APP_CONTROLLER_WIRING = [
    "window.MCBEWorkspaceView.createInventoryWorkspaceController",
    "window.MCBEWorkflowState.createConfiguredInventoryEditorWorkflowShell",
    "window.MCBEEffectsLogic.createConfiguredStatsFormController",
    "window.MCBEInventoryRendering.createConfiguredInventoryGridController",
    "window.MCBESessionLog.createInventoryStatusSessionController",
    "window.MCBEWorldStatusView.createInventoryWorldStatusController",
    "window.MCBESaveWorkflowView.createInventorySaveWorkflowController",
    "window.MCBESaveReviewView.createInventorySaveReviewController",
    "window.MCBEWriteStatusView.createInventoryWriteGateController",
    "window.MCBEPresenceView.createConfiguredWorldPresenceController",
    "window.MCBEPlayerLoadApp.createInventoryPlayerLoadApp",
    "window.MCBEIconSourcesController.createInventoryIconSourcesController",
    "window.MCBEUndoRedoController.createInventoryUndoRedoAppController",
    "window.MCBEInventoryClipboardLogic.createConfiguredInventoryClipboardController",
    "window.MCBEWorldBrowser.createInventoryWorldBrowserController",
    "window.MCBEScanPathsController.createInventoryScanPathsController",
    "window.MCBESaveController.createConfiguredSaveAppController",
    "window.MCBESlotDetailLogic.createInventorySlotDetailController",
    "window.MCBEBulkEditLogic.createInventoryBulkEditController",
    "window.MCBEEffectsLogic.createEffectsAbilitiesController",
    "window.MCBEDiagnosticsView.createInventoryDiagnosticsController",
    "window.MCBEBackupsView.createInventoryBackupsController",
    "window.MCBEUpdateDbView.createInventoryUpdateDbController",
    "window.MCBEPlayerTransferLogic.createInventoryPlayerTransferController",
    "window.MCBEMountController.createMountController",
    "window.MCBEBackupRestoreLogic.createConfiguredBackupRestoreController",
    "window.MCBEItemBrowserController.createInventoryItemBrowserController",
    "window.MCBEWorkflowState.createInventoryEditorBootController",
]


@pytest.mark.parametrize("needle", APP_CONTROLLER_WIRING)
def test_app_wires_features_through_configured_controllers(needle: str) -> None:
    app_js = _read("static/app.js")

    assert needle in app_js


def test_item_catalog_stays_behind_facade() -> None:
    app_js = _read("static/app.js")
    catalog_js = _read("static/item_catalog.js")

    assert "window.MCBEItemCatalog.createItemCatalog" in app_js
    assert "function canonicalItemId" not in app_js
    assert "function createItemCatalog" in catalog_js
    assert "function canonicalItemId" in catalog_js


def test_player_tool_lookup_stays_out_of_app_entrypoint() -> None:
    app_js = _read("static/app.js")
    player_load_app_js = _read("static/player_load_app.js")
    view_models_js = _read("static/player_view_models.js")

    assert "window.MCBEPlayerLoadApp.createInventoryPlayerLoadApp" in app_js
    assert "window.MCBEPlayerLoadController?.createInventoryPlayerLoadController" in player_load_app_js
    assert "function playerByKey" not in app_js
    assert "function playerByKey" in view_models_js
