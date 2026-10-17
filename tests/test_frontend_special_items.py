import json

from mcbe_editor.special_items import editor_schema
from tests.node_runner import run_node


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
