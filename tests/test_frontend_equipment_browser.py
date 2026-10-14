from tests.node_runner import run_node


def test_equipment_filter_precedes_limit_and_rechecks_selection():
    run_node(r"""
        const assert = require('assert'), fs = require('fs'), vm = require('vm');
        const context = {window: {}, document: {}, Event: function () {}};
        for (const script of ['equipment_rules', 'item_browser_logic', 'item_browser_controller']) {
            vm.runInNewContext(fs.readFileSync(`static/${script}.js`, 'utf8'), context);
        }
        const db = Object.fromEntries(Array.from({length: 20}, (_,i) => [`minecraft:block_${i}`, ['Block', 'Block']]));
        db['minecraft:iron_helmet'] = ['Eisenhelm', 'Iron helmet'];
        const detail = {value: '', style: {}, dispatchEvent() {}, focus() {}}, bulk = {};
        let targets = [{slotId: 103, container: 'inventory'}], applied = 0;
        const controller = context.window.MCBEItemBrowserController.createItemBrowserController({
            elements: {detailInput: detail, bulkInput: bulk},
            getItemsDb: () => db,
            getEquipmentTargets: () => targets,
            onApplyDetailItem: () => applied++,
        });
        assert.deepStrictEqual(Array.from(controller.autocompleteMatches('minecraft:', detail, 1), i => i.id), ['minecraft:iron_helmet']);
        targets = [{slotId: 100, container: 'inventory'}];
        controller.selectAutocompleteItem(detail, {style: {}}, {id: 'minecraft:iron_helmet'}, {applyOnSelect: true});
        assert.strictEqual(detail.value, '');
        assert.strictEqual(applied, 0);
        targets = [{slotId: 103, container: 'inventory'}, {slotId: 100, container: 'inventory'}];
        assert.strictEqual(controller.autocompleteMatches('minecraft:', bulk).length, 0);
        targets = [{slotId: 103, container: 'inventory'}, {slotId: 0, container: 'inventory'}];
        assert.strictEqual(controller.autocompleteMatches('minecraft:', bulk).length, 1);
        targets = [{slotId: 103, container: 'ender_chest'}];
        assert.strictEqual(controller.autocompleteMatches('minecraft:', detail, Infinity).length, 21);
    """)
