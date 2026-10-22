"""Exercise contained item forms through their real event handlers and catalog."""

import json

from mcbe_editor.special_items import editor_schema
from tests.node_runner import run_node


HARNESS = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
global.window = global;
global.MCBEI18n = {t: (text, args) => text.replace(/\{(\w+)\}/g, (match, key) => args?.[key] ?? match)};
global.MCBEBannerPreview = {createRenderer: () => ({})};
for (const file of ['item_catalog','slot_detail_logic','enchantment_editor_logic','enchantments_view','special_item_logic','special_item_editor']) {
    require('./static/' + file + '.js');
}
const db = JSON.parse(fs.readFileSync('mcbe_editor/resources/item_db.json', 'utf8'));
const catalog = MCBEItemCatalog.createItemCatalog({
    getItemsDb: () => db.items, getCompatItemAliases: () => db.compat_item_aliases,
    getAddableItems: () => new Set(db.addable_items), getItemIconIndex: () => ({}),
    getStackLimits: () => db.stack_limits, getMaxDamageMap: () => db.durability,
    getEnchantmentCompatibility: () => ({}), getItemComponents: () => db.item_components,
    itemIdRe: /^[a-z0-9_.-]+:[a-z0-9_./-]+$/, defaultMaxDamage: 32767, maxBedrockStackCount: 127,
});
const model = MCBESpecialItemLogic.createModel(schema, catalog);
class Element {
    constructor(tag, doc) {
        this.tag = tag; this.ownerDocument = doc; this.children = []; this.listeners = {};
        this.attributes = {}; this.className = ''; this.hidden = false; this.disabled = false;
        this.classList = {toggle() {}}; this._value = ''; this._text = '';
    }
    set value(value) { this._value = String(value ?? ''); }
    get value() { return this._value; }
    get valueAsNumber() { return this.value === '' ? NaN : Number(this.value); }
    set textContent(value) { this._text = String(value); this.children = []; }
    get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
    get firstChild() { return this.children[0]; }
    setAttribute(key, value) { this.attributes[key] = String(value); }
    getAttribute(key) { return this.attributes[key] ?? null; }
    addEventListener(type, fn) { (this.listeners[type] ??= []).push(fn); }
    emit(type) { for (const fn of this.listeners[type] ?? []) fn({target:this,preventDefault(){},stopPropagation(){}}); }
    click() { if (!this.disabled) this.emit('click'); }
    focus() { this.ownerDocument.activeElement = this; }
    append(...nodes) { for (const node of nodes) {
        if (node.parentElement) node.parentElement.children = node.parentElement.children.filter(child => child !== node);
        node.parentElement = this; this.children.push(node);
    } }
    replaceChildren(...nodes) { this.children = []; this.append(...nodes); }
    matches(selector) {
        if (selector.startsWith('.')) return this.className.split(' ').includes(selector.slice(1));
        if (selector.startsWith('[data-special=')) return this.getAttribute('data-special') === selector.match(/"(.*?)"/)[1];
        return this.tag === selector;
    }
    querySelectorAll(selector) {
        const selectors = selector.split(',').map(value => value.trim());
        const all = this.children.flatMap(child => [child,...child.querySelectorAll('*')]);
        return selector === '*' ? all : all.filter(child => selectors.some(value => child.matches(value)));
    }
    querySelector(selector) { return this.querySelectorAll(selector)[0] ?? null; }
    showModal() { this.open = true; }
    close() { this.open = false; this.emit('close'); }
}
function fixture(child, siblings = [], parentName = 'minecraft:undyed_shulker_box') {
    const doc = {createElement(tag) { return new Element(tag,this); }};
    doc.body = new Element('body',doc); doc.activeElement = doc.body;
    const dialog = new Element('dialog',doc);
    const parts = {};
    for (const [key,tag,cls] of [['body','div','special-body'],['title','h2',''],['path','p','special-path'],
        ['error','p','special-error'],['accept','button',''],['cancel','button','']]) {
        const node = new Element(tag,doc); node.className = cls;
        if (['accept','cancel'].includes(key)) node.setAttribute('data-special',key);
        parts[key] = node; dialog.append(node);
    }
    let picker, committed = null;
    const original = {slot:0,name:parentName,count:1,damage:0,
        special_item:{kind:parentName === 'minecraft:bundle' ? 'bundle' : 'shulker',editable:true,data:{items:[child,...siblings]}}};
    const editor = MCBESpecialItemEditor.createEditor({
        dialog,model,catalog,textLimits:{maxDisplayName:64,maxLoreLines:8,maxLoreLineLength:80},
        getItemBrowser: () => ({setupAutocomplete(input,list,options) { picker = options; return () => {}; },openPicker(){}}),
        isCurrentContext: () => true, getEnchantments: () => ({}),
        itemLabel: item => `${item.name}:${item.damage ?? 0}`, canEdit: () => true,
        commit(context,item) { committed = item; return {ok:true}; },
    });
    editor.open(original,{},[child.slot]);
    function control(labelText) {
        const label = parts.body.querySelectorAll('label').find(node => node._text === labelText);
        assert(label, `missing control: ${labelText}`);
        return label.htmlFor ? parts.body.querySelectorAll('*').find(node => node.id === label.htmlFor) : label.children[0];
    }
    return {dialog,parts,control,editor,original,get committed(){return committed;},
        select(item){picker.onSelect(item);},
        change(input,value,type='input'){input.value=value;input.emit(type);},
        accept(){parts.accept.click();},
    };
}
"""


def _check(script):
    run_node("const schema = " + json.dumps(editor_schema()) + ";\n" + HARNESS + script)


def test_contained_plain_item_keeps_unknown_damage_and_selected_slot_when_renamed():
    _check(r"""
    const original = {slot:7,source_index:2,name:'minecraft:diamond',count:7,damage:123,
        display_name:'Before',lore:['Original'],enchantments:[],has_preserved_nbt:true};
    const neighbor = {slot:8,source_index:4,name:'minecraft:stone',count:3,damage:0};
    const h = fixture(original,[neighbor]);
    assert.equal(h.control('Abnutzung').parentElement.hidden,true);
    assert.equal(h.control('Variante').parentElement.hidden,true);
    assert.equal(h.parts.body.querySelectorAll('label').some(node=>node._text==='Zielslot'),false);
    assert.match(h.parts.body.querySelector('.special-selected-slot').textContent,/8/);
    assert.match(h.parts.body.querySelector('.special-damage-note').textContent,/123/);
    h.change(h.control('Anzeigename'),'After');
    h.change(h.control('Menge'),'8');
    assert.equal(h.parts.accept.disabled,false);
    h.accept(); h.accept();
    const items = h.committed.special_edit.data.items;
    assert.deepEqual(items[0],{...original,count:8,display_name:'After'});
    assert.deepEqual(items[1],neighbor);
    assert.equal(h.original.special_item.data.items[0].display_name,'Before');
    """)


def test_bundle_quantity_edit_keeps_stack_identity_for_later_insertions():
    _check(r"""
    const original = {slot:0,source_index:0,stack_key:'plain',name:'minecraft:torch',count:2,damage:0,
        display_name:'',lore:[],enchantments:[]};
    const h = fixture(original,[],'minecraft:bundle');
    h.change(h.control('Menge'),'3');
    h.accept();
    const insertion = h.parts.body.querySelectorAll('button').find(node=>node.getAttribute('data-special-slot')==='1');
    assert(insertion); insertion.click();
    h.select({id:'minecraft:torch'});
    h.change(h.control('Menge'),'2');
    h.accept(); h.accept();
    assert.deepEqual(h.committed.special_edit.data.items,[{...original,count:5}]);
    assert.equal(h.original.special_item.data.items[0].count,2);

    const replacement = fixture(original,[],'minecraft:bundle');
    replacement.select({id:'minecraft:stone'});
    replacement.accept(); replacement.accept();
    const changed = replacement.committed.special_edit.data.items[0];
    assert.equal(changed.name,'minecraft:stone');
    assert.equal(changed.source_index,undefined);
    assert.equal(changed.stack_key,undefined,'a replacement must not inherit the previous item fingerprint');
    """)


def test_contained_wear_validation_blocks_bad_values_and_shows_remaining_durability():
    _check(r"""
    const original = {slot:3,source_index:6,name:'minecraft:diamond_sword',count:1,damage:37,
        display_name:'Sword',lore:[],enchantments:[]};
    const h = fixture(original);
    const damage = h.control('Abnutzung');
    assert.equal(damage.parentElement.hidden,false);
    assert.equal(h.control('Variante').parentElement.hidden,true);
    assert.equal(damage.max,String(db.durability[original.name]));
    assert.match(h.parts.body.querySelector('.special-damage-note').textContent,/1524/);
    for (const value of ['', '-1', '2.5', '1562']) {
        h.change(damage,value);
        assert.equal(h.parts.accept.disabled,true,value);
        assert(h.parts.error.textContent,value);
        h.accept(); assert.equal(h.committed,null);
    }
    h.change(damage,'10');
    assert.equal(h.parts.accept.disabled,false);
    assert.equal(h.parts.error.textContent,'');
    assert.match(h.parts.body.querySelector('.special-damage-note').textContent,/1551/);
    h.accept(); h.accept();
    assert.deepEqual(h.committed.special_edit.data.items[0],{...original,damage:10});
    """)


def test_contained_unknown_variant_can_be_kept_or_explicitly_replaced_without_new_raw_values():
    _check(r"""
    const original = {slot:5,source_index:9,name:'minecraft:bed',count:1,damage:99,
        display_name:'Bed',lore:[],enchantments:[]};
    const h = fixture(original);
    const variant = h.control('Variante');
    assert.equal(variant.parentElement.hidden,false);
    assert.equal(h.control('Abnutzung').parentElement.hidden,true);
    assert.equal(variant.value,'99');
    assert.equal(variant.children.filter(option=>option.value==='99').length,1);
    h.change(variant,'3','change');
    assert.equal(h.parts.accept.disabled,false);
    assert(variant.children.some(option=>option.value==='99'));
    h.change(variant,'99','change');
    h.change(h.control('Anzeigename'),'Kept variant');
    h.accept(); h.accept();
    assert.deepEqual(h.committed.special_edit.data.items[0],{...original,display_name:'Kept variant'});
    const replacement = fixture(original);
    replacement.change(replacement.control('Variante'),'3','change');
    replacement.accept(); replacement.accept();
    assert.equal(replacement.committed.special_edit.data.items[0].damage,3);
    assert.equal(replacement.committed.special_edit.data.items[0].source_index,9);
    const changedItem = fixture(original);
    changedItem.select({id:'minecraft:goat_horn'});
    assert.equal(changedItem.control('Variante').value,'0');
    assert(!changedItem.control('Variante').children.some(option=>option.value==='99'));
    changedItem.accept(); changedItem.accept();
    const horn = changedItem.committed.special_edit.data.items[0];
    assert.equal(horn.slot,5); assert.equal(horn.damage,0);
    assert.equal(horn.source_index,undefined);
    """)
