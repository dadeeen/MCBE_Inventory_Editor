import json

from mcbe_editor.special_items import editor_schema
from tests.node_runner import run_node


def test_container_transfer_preserves_sources_rejects_overwrites_and_checks_bundle_weight():
    run_node(
        "const schema = "
        + json.dumps(editor_schema())
        + ";\n"
        + r"""
        const assert = require('node:assert/strict');
        global.window = global;
        require('./static/special_item_logic.js');
        const model = MCBESpecialItemLogic.createModel(schema, {
            getMaxStack: () => 64, hasVerifiedStackLimit: () => true,
        });
        const first = {slot:0, source_index:2, name:'minecraft:diamond', count:20, damage:0, lore:['draft']};
        const second = {slot:1, source_index:0, name:'minecraft:stone', count:1};
        const value = {items:[first,second]}, before = JSON.stringify(value);
        const shulker = {name:'minecraft:undyed_shulker_box'}, bundle = {name:'minecraft:bundle'};
        const copy = model.transferChild(shulker,value,0,2,true).data.items[2];
        assert.equal(copy.copy_source_index,2); assert.equal(copy.source_index,undefined);
        copy.lore.push('independent'); assert.deepEqual(first.lore,['draft']);
        assert(model.transferChild(shulker,value,0,1,true).error);
        const swapped = model.transferChild(shulker,value,0,1,false).data;
        assert.equal(swapped.items.find(x=>x.slot===1).source_index,2);
        assert.equal(swapped.items.find(x=>x.slot===0).source_index,0);
        const bundled = model.transferChild(bundle,value,0,2,true);
        assert.equal(bundled.data.items.length,2);
        assert.equal(bundled.data.items[0].count,40);
        assert.equal(bundled.data.items[0].source_index,2);
        assert.equal(bundled.slot,0);
        assert(model.transferChild(bundle,value,0,2,false).error);
        assert(model.transferChild(bundle,{items:[{...first,count:33}]},0,2,true).error);
        assert.equal(JSON.stringify(value),before);
        assert(model.transferChild(shulker,value,0,27,true).error);
    """
    )


def test_bundle_insertions_merge_only_matching_visible_and_preserved_data():
    run_node(
        "const schema = "
        + json.dumps(editor_schema())
        + ";\n"
        + r"""
        const assert = require('node:assert/strict');
        global.window = global;
        require('./static/special_item_logic.js');
        const model = MCBESpecialItemLogic.createModel(schema, {getMaxStack:()=>64});
        const bundle = {name:'minecraft:bundle'};
        const original = {slot:0,source_index:0,stack_key:'plain',name:'minecraft:torch',count:2,damage:0};
        const fresh = {name:'minecraft:torch',count:2,damage:0};
        const merge = (left,right) => model.withChild({items:[left]},1,right,bundle).items;
        assert.equal(merge(original,fresh).length,1);
        assert.equal(merge(original,fresh)[0].count,4);
        assert.equal(merge(original,{...fresh,display_name:'Different'}).length,2);
        assert.equal(merge(original,{...fresh,lore:['Different']}).length,2);
        assert.equal(merge(original,{...fresh,damage:1}).length,2);
        assert.equal(merge({...original,stack_key:'unknown-a'},fresh).length,2);
        assert.equal(merge({...original,stack_key:'unknown-a'}, {...fresh,source_index:1,stack_key:'unknown-b'}).length,2);
        assert.equal(merge({...original,stack_key:'unknown-a'}, {...fresh,source_index:1,stack_key:'unknown-a'})[0].count,4);
        assert.equal(merge(original,{...fresh,source_index:1,stack_key:undefined}).length,2);
        const duplicate = {...original,slot:1,source_index:1};
        const legacy = {items:[original,duplicate]};
        assert.deepEqual(model.withChild(legacy,1,{...duplicate},bundle),legacy,'unchanged legacy stacks survive');
        assert.equal(original.count,2);
        """
    )


def test_container_child_replacement_keeps_the_selected_slot_and_siblings():
    run_node(
        "const schema = "
        + json.dumps(editor_schema())
        + ";\n"
        + r"""
        const assert = require('node:assert/strict');
        global.window = global;
        require('./static/special_item_logic.js');
        const model = MCBESpecialItemLogic.createModel(schema, {});
        const original = {slot:3,source_index:7,name:'minecraft:diamond',count:8,damage:37,
            special_item:{editable:false,reason:'opaque'},custom_marker:{keep:true}};
        const neighbor = {slot:4,source_index:1,name:'minecraft:stone',count:2};
        const contents = {items:[original,neighbor]};
        const before = JSON.stringify(contents);
        const edited = {...original,slot:4,count:9};
        const changed = model.withChild(contents,3,edited);
        assert.deepEqual(changed.items[0],{...edited,slot:3});
        assert.deepEqual(changed.items[1],neighbor);
        assert.equal(JSON.stringify(contents),before);
        assert.equal(edited.slot,4,'placing a draft must not mutate its source');
        const inserted = model.withChild(contents,6,{slot:4,name:'minecraft:apple',count:1});
        assert.deepEqual(inserted.items.map(item=>item.slot),[3,4,6]);
        assert.deepEqual(model.withChild(contents,3,null).items,[neighbor]);
        assert.deepEqual(model.withChild(contents,9,null),contents);
        """
    )


def test_container_count_limits_account_for_existing_slots_and_nested_bundle_weight():
    run_node(
        "const schema = "
        + json.dumps(editor_schema())
        + ";\n"
        + r"""
        const assert = require('assert');
        const fs = require('fs');
        global.window = {};
        eval(fs.readFileSync('static/special_item_logic.js', 'utf8'));
        const limits = {'minecraft:diamond':64,'minecraft:ender_pearl':16,'minecraft:diamond_sword':1};
        const model = window.MCBESpecialItemLogic.createModel(schema, {
            getMaxStack: name => limits[name] || 1, hasVerifiedStackLimit: name => name in limits,
        });
        const bundle = {name:'minecraft:bundle',count:1};
        const shulker = {name:'minecraft:undyed_shulker_box',count:1};
        const diamond = {slot:0,name:'minecraft:diamond',count:60};
        const contents = {items:[diamond]};
        const limit = (parent, data, slot, name) => model.childCountLimit(parent,data,slot,{name,count:1});
        assert.strictEqual(limit(bundle,contents,1,'minecraft:diamond').maximum,4);
        assert.strictEqual(limit(bundle,contents,0,'minecraft:diamond').maximum,64);
        assert.strictEqual(limit(bundle,contents,1,'minecraft:ender_pearl').maximum,1);
        assert.strictEqual(limit(bundle,contents,1,'minecraft:diamond_sword').maximum,0);
        assert.strictEqual(limit(shulker,contents,1,'minecraft:diamond').maximum,64);
        assert.strictEqual(limit(shulker,contents,1,'minecraft:ender_pearl').maximum,16);
        assert.strictEqual(limit(shulker,contents,1,'minecraft:diamond_sword').maximum,1);
        assert.strictEqual(limit(bundle,contents,1,'minecraft:bundle').maximum,1);
        const nested = {...bundle,special_edit:{kind:'bundle',data:{items:[{...diamond,count:1}]}}};
        assert.strictEqual(model.childCountLimit(bundle,contents,1,nested).maximum,0);
        assert(limit(bundle,contents,1,'addon:unknown').error);
        assert(limit(bundle,{items:[{slot:0,name:'addon:unknown',count:1}]},1,'minecraft:diamond').error);
        assert(limit(bundle,contents,1,shulker.name).error);
        assert(limit(shulker,contents,1,shulker.name).error);
        assert.strictEqual(limit(bundle,contents,1,'minecraft:diamond').maximum,4);
        assert.strictEqual(contents.items[0].count,60);
        assert.strictEqual(limit(bundle,{items:[{...diamond,count:65}]},1,'minecraft:diamond').maximum,0);
        """
    )


def test_container_search_uses_current_drafts_paths_and_reports_unsearched_contents():
    run_node(
        "const schema = "
        + json.dumps(editor_schema())
        + ";\n"
        + r"""
        const assert = require('assert');
        const fs = require('fs');
        global.window = {};
        eval(fs.readFileSync('static/special_item_logic.js', 'utf8'));
        const model = window.MCBESpecialItemLogic.createModel(schema, {});
        const diamond = {slot:3,name:'minecraft:diamond',count:7};
        const bundle = {slot:2,name:'minecraft:bundle',count:1,
            special_item:{kind:'bundle',editable:true,data:{items:[diamond]}}};
        const root = {name:'minecraft:undyed_shulker_box',count:1,
            special_item:{kind:'shulker',editable:true,data:{items:[bundle]}}};
        const before = JSON.stringify(root);
        const matches = item => item.name.includes('diamond');
        let found = model.searchContents(root,matches);
        assert.deepStrictEqual(found.hits.map(hit => hit.path.map(item => item.slot)), [[2,3]]);
        assert.strictEqual(found.incomplete,false);
        assert.strictEqual(JSON.stringify(root),before);
        bundle.special_edit = {kind:'bundle',data:{items:[{...diamond,slot:9,count:2}]}};
        found = model.searchContents(root,matches);
        assert.deepStrictEqual(found.hits.map(hit => hit.path.map(item => item.slot)), [[2,9]]);
        assert.strictEqual(found.hits[0].item.count,2);
        bundle.special_edit.data.items = [];
        assert.strictEqual(model.searchContents(root,matches).hits.length,0);
        root.special_item.data.items.push({name:'minecraft:bundle',slot:5,
            special_item:{kind:'bundle',editable:false,reason:'opaque'}});
        assert.strictEqual(model.searchContents(root,matches).incomplete,true);
        // The bounded walk stops even for an accidentally cyclic browser draft.
        bundle.special_edit.data.items = [bundle];
        assert.strictEqual(model.searchContents(root,matches).incomplete,true);
        const dense = {name:'minecraft:bundle',special_edit:{kind:'bundle',data:{items:
            Array.from({length:schema.limits.nodes+1},(_,slot)=>({...diamond,slot}))}}};
        found = model.searchContents(dense,matches);
        assert.strictEqual(found.hits.length,schema.limits.nodes);
        assert.strictEqual(found.incomplete,true);
        const exact = {...dense,special_edit:{kind:'bundle',data:{items:dense.special_edit.data.items.slice(1)}}};
        assert.strictEqual(model.searchContents(exact,matches).incomplete,false);
        """
    )


def test_special_item_drafts_weights_noops_and_origin_boundaries():
    run_node(
        "const schema = "
        + json.dumps(editor_schema())
        + ";\n"
        + r"""
        const assert = require('assert');
        const fs = require('fs');
        global.window = {};
        eval(fs.readFileSync('static/special_item_logic.js', 'utf8'));
        const limits = { 'minecraft:diamond':64, 'minecraft:ender_pearl':16, 'minecraft:diamond_sword':1 };
        const logic = window.MCBESpecialItemLogic;
        const model = logic.createModel(schema, { getMaxStack:name => limits[name] || 1, hasVerifiedStackLimit:name => name in limits });
        const item = { slot:0, name:'minecraft:bundle', count:1, damage:0,
            special_item:{kind:'bundle',editable:true,data:{items:[{slot:7,source_index:3,name:'minecraft:diamond',count:7}]}} };
        const data = model.data(item);
        data.items[0].count = 9;
        assert.strictEqual(item.special_item.data.items[0].count, 7);
        assert.strictEqual(model.weight(item), 11);
        const edited = model.apply(item, data);
        assert.strictEqual(model.weight(edited), 13);
        assert.strictEqual(model.data(edited).items[0].source_index, 3);
        assert.strictEqual(model.apply(item, model.data(item)).special_edit, undefined);
        assert.strictEqual(model.weight({ name:'minecraft:ender_pearl',count:16 }), 64);
        assert.strictEqual(model.weight({ name:'minecraft:diamond_sword',count:1 }), 64);
        assert.strictEqual(model.weight({ name:'addon:unknown',count:1 }), null);
        assert(model.validate(item,{items:[{name:'minecraft:diamond',count:64},{name:'minecraft:diamond',count:1}]}));
        assert(model.validate(item,{items:[{name:'minecraft:blue_shulker_box',count:1}]}));
        assert(!model.editable({...item,special_item:{editable:false}}));
        const child = model.cleanChild({ ...edited, source_player_key:'other',source_slot:3,source_container:'inventory',
            source_world_path:'other',source_item_digest:'abc',replace_original_nbt:true,source_index:2 });
        assert.strictEqual(child.source_index,2);
        assert.strictEqual(child.source_player_key,undefined);
        assert.strictEqual(child.source_slot,undefined);
        assert.strictEqual(child.source_item_digest,undefined);
        assert.strictEqual(child.special_edit.data.items[0].count,9);
        assert(logic.sameUserFields({name:'minecraft:bundle',slot:0,count:1},
            {slot:0,count:1,name:'minecraft:bundle',damage:0,lore:[],enchantments:[],display_name:'',source_slot:0}));
        assert(!logic.sameUserFields(item,edited));
        assert(logic.changeLabel(item,edited));
        const emptyStar = {name:'minecraft:firework_star',count:1};
        assert.strictEqual(model.validate(emptyStar,model.data(emptyStar)), '');
        const unknownBundle = {name:'minecraft:bundle',count:1,special_item:{kind:'bundle',editable:true,
            data:{items:[{slot:0,name:'addon:unknown',count:1},{slot:1,name:'minecraft:diamond',count:1}]}}};
        assert.strictEqual(model.validate(unknownBundle,model.data(unknownBundle)), '');
        const echoed = model.data(unknownBundle);
        assert.strictEqual(model.validate(unknownBundle,model.withChild(echoed,0,model.cleanChild(echoed.items[0]))), '');
        assert(model.validate(unknownBundle,{items:[{slot:0,name:'addon:unknown',count:2}]}));
        let nested = {slot:0,name:'minecraft:diamond',count:1};
        for(let i=0;i<schema.limits.depth-2;i++) nested = {slot:0,name:'minecraft:bundle',count:1,
            special_edit:{kind:'bundle',data:{items:[nested]}}};
        assert.strictEqual(model.validate(item,{items:[nested]}), '');
        nested = {slot:0,name:'minecraft:bundle',count:1,special_edit:{kind:'bundle',data:{items:[nested]}}};
        assert(model.validate(item,{items:[nested]}));
        // An editor opened inside a shulker still uses the absolute depth.
        // Otherwise its locally valid draft fails only when the player saves.
        const emptyBundle = {name:'minecraft:bundle',count:1};
        const diamond = {slot:0,name:'minecraft:diamond',count:1};
        assert.strictEqual(model.validate(emptyBundle,{items:[diamond]},schema.limits.depth-2), '');
        assert(model.validate(emptyBundle,{items:[diamond]},schema.limits.depth-1));
        assert.strictEqual(model.validate(emptyBundle,{items:[]},schema.limits.depth-1), '');
        const originalDeepBundle = {...emptyBundle,special_item:{kind:'bundle',editable:true,data:{items:[diamond]}}};
        assert.strictEqual(model.validate(originalDeepBundle,model.data(originalDeepBundle),schema.limits.depth-1), '');
        let emptyNested = {slot:0,name:'minecraft:bundle',count:1};
        for(let i=0;i<schema.limits.depth-2;i++) emptyNested = {slot:0,name:'minecraft:bundle',count:1,
            special_edit:{kind:'bundle',data:{items:[emptyNested]}}};
        assert.strictEqual(model.validate(item,{items:[emptyNested]}), '');
        const contents = {items:Array.from({length:8},(_,slot)=>({slot,name:'minecraft:bundle',count:1,
            special_edit:{kind:'bundle',data:{items:Array.from({length:31},(_,slot)=>({slot,name:'minecraft:diamond',count:1}))}}}))};
        const shulker = {name:'minecraft:undyed_shulker_box',count:1};
        assert.strictEqual(model.validate(shulker,contents), '');
        contents.items.push({slot:8,name:'minecraft:diamond',count:1});
        assert(model.validate(shulker,contents));
        """
    )
