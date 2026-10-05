"""Keep bulk protection and restore recovery details consistent across callers."""

from unittest.mock import Mock

import pytest

from mcbe_editor.api_errors import add_exception_cleanup_details
from mcbe_editor.backup_api_routes import BackupRouteDeps, restore_backup
from tests.node_runner import run_node


def test_bulk_target_discovery_uses_the_same_container_aware_protection():
    run_node(r"""
const assert = require('node:assert/strict');
global.window = global;
require('./static/inventory_state.js');
const state = MCBEInventoryState;
const item = () => ({name: 'minecraft:iron_helmet', count: 1, damage: 12});
const inventory = {0: item(), 1: item(), 103: {...item(), root_equipment_read_only: true}};
const enderChestInventory = {0: item(), 1: item()};
const options = {
    maxDamage: {'minecraft:iron_helmet': 165},
    isItemVisiblePresent: item => item?.count > 0,
    isProtectedKnownSlot: (slot, container) => {
        assert.equal(typeof slot, 'number');
        assert.ok(['inventory', 'ender_chest'].includes(container));
        return container === 'inventory' ? [1, 103].includes(slot) : slot === 0;
    },
};
const sources = [{container: 'inventory', map: inventory}, {container: 'ender_chest', map: enderChestInventory}];
const selected = state.selectedBulkTargets({selectedSlots: [0, 1, 103], selectedEnderSlot: 1,
    inventory, enderChestInventory, isProtectedKnownSlot: options.isProtectedKnownSlot});
const all = state.damagedInventoryTargets({sources, ...options});
const coordinates = targets => targets.map(({container, slotId}) => [container, Number(slotId)]);
assert.deepEqual(coordinates(all), coordinates(state.damagedItemTargets(selected, options)));
assert.deepEqual(coordinates(all), [['inventory', 0], ['ender_chest', 1]]);
assert.equal(all[0].map, inventory);
assert.equal(all[1].map, enderChestInventory);
assert.deepEqual(state.damagedInventoryTargets({sources, ...options, isProtectedKnownSlot: () => true}), []);
assert.deepEqual(state.damagedInventoryTargets(), []);
""")


def test_cleanup_details_preserve_only_recovery_metadata():
    error = OSError("restore failed")
    details = {"cleanup_warning": "retained", "source_snapshot_path": "/tmp/snapshot.zip", "pre_restore_backup": "safety.zip"}
    for key, value in details.items():
        setattr(error, key, value)
    error.write_committed = True
    payload = {"success": False, "code": "restore_failed"}
    assert add_exception_cleanup_details(payload, error) is payload
    assert payload == {"success": False, "code": "restore_failed", **details}
    assert add_exception_cleanup_details({}, ValueError("no leftovers")) == {}


@pytest.mark.parametrize("error_type", [ValueError, OSError])
@pytest.mark.parametrize("field", ["cleanup_warning", "source_snapshot_path", "pre_restore_backup"])
@pytest.mark.parametrize("unknown", [False, True])
def test_restore_preserves_recovery_details_on_each_error_path(error_type, field, unknown):
    error = error_type("restore failed")
    setattr(error, field, "retained.zip")
    if unknown:
        error.write_outcome_unknown = True
    service = Mock()
    service.restore_backup.side_effect = error
    deps = BackupRouteDeps(
        service=service,
        jsonify=lambda payload: payload,
        api_error=lambda error, status=400: ({"success": False, "error": str(error)}, status),
        log_api_exception=Mock(),
        json_string=lambda data, key: data[key],
        require_world_write_allowed=lambda: None,
        require_final_world_write_allowed=lambda operation: None,
        presence_conflict_response=lambda *args, **kwargs: None,
        audit_event=Mock(),
        final_write_gate_blocked_error=type("GateError", (Exception,), {}),
    )
    payload, status = restore_backup({"world_path": "world", "backup_file": "input.zip", "backup_token": {}}, deps)
    assert payload[field] == "retained.zip"
    assert status == (500 if unknown or error_type is OSError else 400)
    assert payload["success"] is False
    if unknown:
        assert payload["code"] == "restore_outcome_unknown"
        assert payload["write_outcome_unknown"] is True
        assert payload["reload_required"] is True
    else:
        assert "write_outcome_unknown" not in payload
        assert "reload_required" not in payload
    assert "write_committed" not in payload
    assert "rolled_back" not in payload
