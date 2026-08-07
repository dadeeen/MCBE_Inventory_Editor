import subprocess
import textwrap
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _run_node(source: str) -> None:
    result = subprocess.run(
        ["node", "-e", source],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout


def test_dedicated_item_paste_uses_real_clipboard_controller() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");

            class FakeElement {
                constructor(tagName, closestValue = null) {
                    this.tagName = tagName;
                    this.isContentEditable = false;
                    this.closestValue = closestValue;
                }
                closest() { return this.closestValue; }
            }

            const selectionApi = {
                hasSelection(selection) {
                    return (selection.selectedSlots || []).length > 0 || Number.isInteger(selection.selectedEnderSlot) && selection.selectedEnderSlot >= 0;
                },
                selectedClipboardSourceTarget(selection) {
                    if (Number.isInteger(selection.selectedEnderSlot) && selection.selectedEnderSlot >= 0) {
                        return { isEnder: true, slotId: selection.selectedEnderSlot, containerName: "ender_chest" };
                    }
                    const slotId = (selection.selectedSlots || [])[0];
                    return Number.isInteger(slotId) ? { isEnder: false, slotId, containerName: "inventory" } : null;
                },
                selectedSingleTarget(selection) {
                    if (Number.isInteger(selection.selectedEnderSlot) && selection.selectedEnderSlot >= 0) {
                        return { isEnder: true, slotId: selection.selectedEnderSlot, containerName: "ender_chest" };
                    }
                    const slots = selection.selectedSlots || [];
                    return slots.length === 1 ? { isEnder: false, slotId: slots[0], containerName: "inventory" } : null;
                },
                selectedWritableInventorySlots(selection, isProtected) {
                    return (selection.selectedSlots || []).filter(slotId => !isProtected(slotId, "inventory"));
                },
            };

            const context = {
                Element: FakeElement,
                window: {
                    MCBESelectionState: selectionApi,
                    MCBEEquipmentRules: {
                        isEquipmentSlot() { return false; },
                        itemAllowedInEquipmentSlot() { return true; },
                        notWearableMessage() { return "not wearable"; },
                    },
                    getSelection() { return { isCollapsed: true, toString() { return ""; } }; },
                    t(text, params) {
                        return String(text).replace(/\{(\w+)\}/g, (match, key) => params && key in params ? String(params[key]) : match);
                    },
                },
            };
            vm.runInNewContext(
                fs.readFileSync("static/inventory_clipboard_logic.js", "utf8"),
                context,
                { filename: "static/inventory_clipboard_logic.js" },
            );

            const logic = context.window.MCBEInventoryClipboardLogic;
            const inventory = {
                1: { slot: 1, source_slot: 1, name: "minecraft:filled_map", count: 1 },
            };
            let currentSelection = { selectedSlots: [1], selectedEnderSlot: -1 };
            let undoCalls = 0;
            let gridUpdates = 0;
            let dirtyCalls = 0;
            const toasts = [];

            const doc = {
                querySelector() { return null; },
            };
            const controller = logic.createInventoryClipboardController({
                doc,
                win: context.window,
                getInventory: () => inventory,
                getEnderChestInventory: () => ({}),
                getCurrentPlayerKey: () => "player-1",
                getWorldPath: () => "C:/world",
                getCurrentSelectionState: () => currentSelection,
                getActiveWorkflowView: () => "inventory",
                isProtectedKnownSlot: () => false,
                pushUndo: () => { undoCalls += 1; },
                updateGridVisuals: () => { gridUpdates += 1; },
                setDirty: value => { if (value) dirtyCalls += 1; },
                showToast: (...args) => { toasts.push(args); },
                recordAction: () => {},
                cloneSlotItem(item, containerName, helpers) {
                    const clone = JSON.parse(JSON.stringify(item));
                    return helpers.ensureOrigin(clone, containerName);
                },
                pasteClipboard(clipboard, targets) {
                    targets.forEach(target => {
                        target.map[target.slotId] = { ...JSON.parse(JSON.stringify(clipboard)), slot: target.slotId };
                    });
                },
            });

            function keyEvent({ key, shiftKey = false, target }) {
                return {
                    key,
                    ctrlKey: true,
                    metaKey: false,
                    shiftKey,
                    altKey: false,
                    target,
                    defaultPrevented: false,
                    preventDefault() { this.defaultPrevented = true; },
                };
            }

            const slotTarget = new FakeElement("DIV", {});
            const inputTarget = new FakeElement("INPUT");

            const copyEvent = keyEvent({ key: "c", target: slotTarget });
            assert.strictEqual(controller.handleKeydown(copyEvent), true);
            assert.strictEqual(copyEvent.defaultPrevented, true);
            assert.strictEqual(controller.state().hasClipboard, true);

            currentSelection = { selectedSlots: [2], selectedEnderSlot: -1 };

            const normalPasteEvent = keyEvent({ key: "v", target: inputTarget });
            assert.strictEqual(controller.handleKeydown(normalPasteEvent), false);
            assert.strictEqual(normalPasteEvent.defaultPrevented, false);
            assert.strictEqual(inventory[2], undefined);

            const itemPasteEvent = keyEvent({ key: "v", shiftKey: true, target: inputTarget });
            assert.strictEqual(controller.handleKeydown(itemPasteEvent), true);
            assert.strictEqual(itemPasteEvent.defaultPrevented, true);
            assert.strictEqual(inventory[2].name, "minecraft:filled_map");
            assert.strictEqual(inventory[2].slot, 2);
            assert.strictEqual(inventory[2].source_slot, 1);
            assert.strictEqual(undoCalls, 1);
            assert.strictEqual(gridUpdates, 1);
            assert.strictEqual(dirtyCalls, 1);

            assert.strictEqual(logic.clipboardShortcutIntent(normalPasteEvent), "");
            assert.strictEqual(logic.clipboardShortcutIntent(itemPasteEvent), "paste_item");

            const emptyController = logic.createInventoryClipboardController({
                doc,
                win: context.window,
                getInventory: () => inventory,
                getCurrentSelectionState: () => currentSelection,
                getActiveWorkflowView: () => "inventory",
                showToast: (...args) => { toasts.push(args); },
            });
            const emptyPasteEvent = keyEvent({ key: "v", shiftKey: true, target: inputTarget });
            assert.strictEqual(emptyController.handleKeydown(emptyPasteEvent), true);
            assert.strictEqual(emptyPasteEvent.defaultPrevented, true);
            assert.ok(toasts.some(args => String(args[0]).includes("📄 Einfügen: keine Daten")));
            """
        )
    )


def test_same_item_copy_prefers_source_nbt_over_existing_target() -> None:
    nbt = pytest.importorskip("amulet_nbt")
    from mcbe_editor import inventory

    source = nbt.CompoundTag(
        {
            "Slot": nbt.ByteTag(1),
            "Name": nbt.StringTag("minecraft:filled_map"),
            "Count": nbt.ByteTag(1),
            "Damage": nbt.ShortTag(0),
            "tag": nbt.CompoundTag({"map_uuid": nbt.LongTag(111)}),
        }
    )
    target = nbt.CompoundTag(
        {
            "Slot": nbt.ByteTag(2),
            "Name": nbt.StringTag("minecraft:filled_map"),
            "Count": nbt.ByteTag(1),
            "Damage": nbt.ShortTag(0),
            "tag": nbt.CompoundTag({"map_uuid": nbt.LongTag(222)}),
        }
    )
    player = nbt.CompoundTag({"Inventory": nbt.ListTag([source, target])})

    def item_payload(slot: int, source_slot: int) -> dict:
        return {
            "slot": slot,
            "source_slot": source_slot,
            "source_player_key": "player-1",
            "source_container": "inventory",
            "name": "minecraft:filled_map",
            "count": 1,
            "damage": 0,
            "display_name": "",
            "lore": [],
            "enchantments": [],
            "has_preserved_nbt": True,
        }

    saved = inventory.build_inventory_nbt(
        player,
        [item_payload(1, 1), item_payload(2, 1)],
        inventory.ENCHANTMENTS,
        target_player_key="player-1",
    )
    by_slot = {entry["Slot"].py_data: entry for entry in saved}

    assert by_slot[1]["tag"]["map_uuid"].py_data == 111
    assert by_slot[2]["tag"]["map_uuid"].py_data == 111


def test_inventory_clipboard_uses_only_central_catalog(monkeypatch) -> None:
    from mcbe_editor import i18n

    monkeypatch.setattr(i18n, "_catalog_cache", None)
    assert i18n.translate("keine Daten", "en") == "no data"
    assert i18n.translate("Strg", "en") == "Ctrl"
    assert i18n.translate("Rechtsklick", "en") == "Right-click"

    clipboard_logic = (ROOT / "static" / "inventory_clipboard_logic.js").read_text(encoding="utf-8")
    app_bootstrap = (ROOT / "static" / "app_bootstrap.js").read_text(encoding="utf-8")
    i18n_source = (ROOT / "mcbe_editor" / "i18n.py").read_text(encoding="utf-8")
    assert "enhanceInventoryClipboardHelp" not in clipboard_logic
    assert "inventoryClipboardHelpModel" not in clipboard_logic
    assert "inventoryClipboardHelpModel" in app_bootstrap
    assert "installInventoryClipboardHelp" in app_bootstrap
    assert '`${t("📄 Einfügen")}: ${t("keine Daten")}`' in clipboard_logic
    assert "_CATALOG_FRAGMENT_GLOB" not in i18n_source
    assert not (ROOT / "static" / "i18n" / "en.inventory_clipboard.json").exists()
