import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = fs.readFileSync('static/focus_workspace.js','utf8');
const scope = { window: {} };
vm.runInNewContext(source, scope, { filename: 'focus_workspace.js' });
const { createFocusWorkspaceController } = scope.window.MCBEFocusWorkspaceFactory;

class Node {
  constructor(id = '') { this.id = id; this.children = []; this.parentNode = null; this.style = {}; this.textContent = ''; this.value = ''; this.listeners = {}; }
  get nextSibling() { if (!this.parentNode) return null; return this.parentNode.children[this.parentNode.children.indexOf(this) + 1] || null; }
  insertBefore(child, next) {
    if (child.parentNode) child.parentNode.children.splice(child.parentNode.children.indexOf(child), 1);
    child.parentNode = this;
    const at = next ? this.children.indexOf(next) : -1;
    this.children.splice(at < 0 ? this.children.length : at, 0, child);
    return child;
  }
  appendChild(child) { return this.insertBefore(child, null); }
  addEventListener(type, cb) { (this.listeners[type] ||= []).push(cb); }
  setAttribute(key, value) { (this.attributes ||= {})[key] = value; }
  getAttribute(key) { return this.attributes?.[key] || null; }
  focus() { this.focused = true; }
  contains(node) { return node === this || this.children.some(child => child.contains(node)); }
  dispatch(type, event = {}) { for (const cb of this.listeners[type] || []) cb({ target: this, ...event }); }
  querySelectorAll(key) { if (key === '.player-row') return this.children; return []; }
  querySelector(key) { if (key === '.player-name') return this.name || null; return null; }
  closest(key) { if (key === '.layout-context-action' && this.id === 'layoutSaveAction') return this.parentNode; if (key === '.inventory-toolbar' && this.id === 'gridSearch') return this.parentNode; return null; }
}
function setup() {
  const nodes = {};
  const add = id => nodes[id] = new Node(id);
  const root = add('root'), body = add('body');
  root.dataset = { layout: 'classic' };
  body.dataset = { workflowView: 'world' };
  let playerLoaded = false;
  body.classList = { contains: cls => cls === 'app-player-loaded' && playerLoaded };
  const header = add('header'), headerStatus = add('headerStatus'), headerActions = add('headerActions'), layoutChoice = add('layoutChoice');
  const history = add('history'), panelToggle = add('panelToggle');
  const inlineStatus = add('focusInlineStatus'), historyMount=add('focusHistoryMount'), saveMount=add('focusSaveMount'), settingsMount=add('focusSettingsMount');
  const settingsMenu=add('focusSettingsMenu'), settingsToggle=add('focusSettingsToggle'), settingsPanel=add('focusSettingsPanel');
  settingsPanel.hidden=true;
  settingsMenu.appendChild(settingsToggle); settingsMenu.appendChild(settingsPanel); settingsPanel.appendChild(settingsMount);
  const contextBar = add('contextBar'), saveArea = add('saveArea'), saveAction = add('layoutSaveAction');
  const manager = add('playerManager'), list = add('playersList'), railMount = add('focusPlayerListMount');
  const inventory = add('inventoryContainer'), section = add('inventorySection'), equipment = add('equipment');
  const dashboard = add('dashboardPanel'), dashboardSection = add('dashboardSection');
  dashboard.appendChild(dashboardSection);
  dashboard.querySelector = key => key === '.dashboard-section' ? dashboardSection : null;
  const equipmentSlot = add('equipmentSlot'); equipment.appendChild(equipmentSlot);
  const worldSection=add('worldSection');
  const loadError=add('loadErrorPanel'), presence=add('worldPresenceBanner'), dirty=add('dirtyBanner');
  const toolbar = add('toolbar'), gridSearch = add('gridSearch');
  const input = add('focusPlayerSearch'), refresh = add('focusRefreshPlayers'), refreshOriginal = add('btnRefreshPlayers');
  add('focusPlayerSearchEmpty').hidden = true;
  const playerSummary = add('playerSummaryName');
  const positionX = add('statPosX'), positionY = add('statPosY'), positionZ = add('statPosZ'), xp=add('statXpLevel');
  const gamemode=add('statGamemode'), health=add('statHealth'), food=add('statFoodLevel'), dim=add('statDimensionId');
  for (const id of ['focusSummaryPlayerName','focusFactMode','focusFactPosition','focusFactDimension','focusVitalXp','focusVitalHealth','focusVitalFood']) add(id);
  dim.selectedOptions = [{ textContent:'Oberwelt', disabled:false }];
  const rowA = new Node('rowA'); rowA.name={textContent:'Steve'};
  const rowB = new Node('rowB'); rowB.name={textContent:'Alex'};
  list.appendChild(rowA); list.appendChild(rowB);
  manager.appendChild(list); section.appendChild(toolbar); toolbar.appendChild(gridSearch);
  section.appendChild(equipment); inventory.appendChild(section);
  worldSection.appendChild(loadError); worldSection.appendChild(presence); worldSection.appendChild(dirty);
  inventory.querySelector = key => key === '.inventory-section' ? section : null;
  saveArea.appendChild(saveAction); contextBar.appendChild(saveArea);
  headerActions.appendChild(layoutChoice); header.appendChild(headerStatus); header.appendChild(headerActions);
  header.appendChild(history); header.appendChild(panelToggle);
  let clicks = 0;
  refreshOriginal.click=()=>clicks++;
  const doc = {
    body, documentElement: root, listeners: {}, getElementById: id => nodes[id] || null,
    dispatch(type, event) { for (const cb of this.listeners[type] || []) cb(event); },
    querySelector(key) {
      if (key === '.app-header .header-status-area') return headerStatus;
      if (key === '.app-header .header-actions') return headerActions;
      if (key === '.app-header .undo-redo-btns') return history;
      return null;
    },
    addEventListener(type,cb) { (this.listeners[type] ||= []).push(cb); },
  };
  headerActions.querySelector = key => key === '.layout-choice' ? layoutChoice : null;
  const controller = createFocusWorkspaceController({ doc, observerFactory: cb => ({ observe() {} }) });
  return { nodes, root, body, doc, controller, rowA, rowB, enable() { playerLoaded=true; body.dataset.workflowView='inventory'; root.dataset.layout='focus'; }, getClicks() { return clicks; } };
}

test('focus reuses the player list and keeps equipment beside the inventory', () => {
  const h = setup();
  h.enable(); h.controller.sync();
  assert.equal(h.nodes.playersList.parentNode, h.nodes.focusPlayerListMount);
  assert.equal(h.nodes.equipment.parentNode, h.nodes.inventorySection);
  assert.equal(h.nodes.equipmentSlot.parentNode, h.nodes.equipment);
  assert.equal(h.nodes.toolbar.parentNode, h.nodes.inventorySection);
  assert.equal(h.nodes.inventorySection.children[0], h.nodes.toolbar, 'search stays before inventory slots');
  assert.equal(h.nodes.saveArea.parentNode, h.nodes.focusSaveMount);
  assert.equal(h.nodes.history.parentNode, h.nodes.focusHistoryMount);
  assert.equal(h.nodes.headerActions.parentNode, h.nodes.focusSettingsMount);
  assert.equal(h.nodes.headerStatus.parentNode, h.nodes.focusInlineStatus);
  for (const id of ['loadErrorPanel','worldPresenceBanner']) {
    assert.equal(h.nodes[id].parentNode, h.nodes.inventoryContainer, `${id} remains visible inside focus inventory`);
  }
  h.root.dataset.layout='studio'; h.controller.sync();
  assert.equal(h.nodes.playersList.parentNode, h.nodes.playerManager);
  assert.equal(h.nodes.equipment.parentNode, h.nodes.inventorySection);
  assert.equal(h.nodes.toolbar.parentNode, h.nodes.inventorySection);
  assert.equal(h.nodes.toolbar.nextSibling, h.nodes.equipment);
  assert.equal(h.nodes.saveArea.parentNode, h.nodes.contextBar);
  assert.deepEqual(h.nodes.header.children.map(node => node.id),
    ['headerStatus','headerActions','history','panelToggle'], 'original header node order restored');
  for (const id of ['loadErrorPanel','worldPresenceBanner']) {
    assert.equal(h.nodes[id].parentNode, h.nodes.worldSection, `${id} is restored`);
  }
  assert.deepEqual(h.nodes.worldSection.children.map(node => node.id),
    ['loadErrorPanel','worldPresenceBanner','dirtyBanner']);
});

test('filters the live player list only in the rail, not in the full player-management view', () => {
  const h=setup(); h.enable(); h.nodes.focusPlayerSearch.value='al';
  h.controller.sync();
  assert.equal(h.rowA.style.display,'none');
  assert.equal(h.rowB.style.display,'');
  h.body.dataset.workflowView='player'; h.controller.sync();
  assert.equal(h.rowA.style.display,'');
  assert.equal(h.rowB.style.display,'');
  assert.equal(h.nodes.playersList.parentNode,h.nodes.playerManager);
});

test('live notices retain their order and handlers across Focus editors and other layouts', () => {
  const h = setup(); h.enable();
  const notices = [h.nodes.loadErrorPanel, h.nodes.worldPresenceBanner];
  let activations = 0;
  notices[0].addEventListener('click', () => activations++);
  for (const [layout, view, host, next] of [
    ['focus', 'inventory', 'inventoryContainer', 'inventorySection'],
    ['focus', 'player-edit', 'dashboardPanel', 'dashboardSection'],
    ['focus', 'inventory', 'inventoryContainer', 'inventorySection'],
    ['focus', 'player-edit', 'dashboardPanel', 'dashboardSection'],
    ['studio', 'player-edit', 'worldSection', 'dirtyBanner'],
    ['focus', 'player-edit', 'dashboardPanel', 'dashboardSection'],
    ['classic', 'player', 'worldSection', 'dirtyBanner'],
  ]) {
    h.root.dataset.layout = layout;
    h.body.dataset.workflowView = view;
    h.controller.sync(); h.controller.sync();
    assert.deepEqual(h.nodes[host].children.slice(0, 3), [...notices, h.nodes[next]]);
    for (const node of notices) assert.equal(node.parentNode, h.nodes[host]);
    notices[0].dispatch('click');
  }
  assert.equal(activations, 7);
});

test('an unmatched Focus player search shows a local empty state and clears it when leaving the rail', () => {
  const h = setup(); h.enable();
  h.nodes.focusPlayerSearch.value = 'missing';
  h.controller.sync();
  assert.equal(h.nodes.focusPlayerSearchEmpty.hidden, false);
  assert.equal(h.rowA.style.display, 'none');
  assert.equal(h.rowB.style.display, 'none');
  h.nodes.focusPlayerSearch.value = 'ste';
  h.controller.filterPlayers();
  assert.equal(h.nodes.focusPlayerSearchEmpty.hidden, true);
  assert.equal(h.rowA.style.display, '');
  h.nodes.focusPlayerSearch.value = 'missing';
  h.controller.filterPlayers();
  assert.equal(h.nodes.focusPlayerSearchEmpty.hidden, false);
  h.body.dataset.workflowView = 'player';
  h.controller.sync();
  assert.equal(h.nodes.focusPlayerSearchEmpty.hidden, true);
  assert.equal(h.rowA.style.display, '');
  assert.equal(h.rowB.style.display, '');
});

test('shows real form values and uses placeholders when no editable player exists', () => {
  const h=setup(); h.enable();
  Object.assign(h.nodes.statPosX,{value:'-67'}); Object.assign(h.nodes.statPosY,{value:'104'});
  Object.assign(h.nodes.statPosZ,{value:'-152'}); Object.assign(h.nodes.statHealth,{value:'20'});
  Object.assign(h.nodes.statFoodLevel,{value:'18'}); Object.assign(h.nodes.statXpLevel,{value:'24'});
  Object.assign(h.nodes.statGamemode,{value:'Survival'}); h.nodes.playerSummaryName.textContent='Steve';
  h.controller.updateFacts();
  assert.equal(h.nodes.focusFactPosition.textContent,'-67, 104, -152');
  assert.equal(h.nodes.focusSummaryPlayerName.textContent,'Steve');
  assert.equal(h.nodes.focusFactDimension.textContent,'Oberwelt');
  assert.equal(h.nodes.focusVitalFood.textContent,'18');
  assert.equal(h.nodes.focusFactMode.textContent,'Survival');
  h.nodes.statGamemode.value = 'Standard/Weltmodus (Default) · NBT-Wert 5';
  h.nodes.statGamemode.dataset = {summaryLabel:'Weltvorgabe',summaryTitle:'Verwendet die Spielmodus-Vorgabe der Welt oder des Servers.'};
  h.controller.updateFacts();
  assert.equal(h.nodes.focusFactMode.textContent, 'Weltvorgabe');
  assert.equal(h.nodes.focusFactMode.title, h.nodes.statGamemode.dataset.summaryTitle);
  assert.equal(h.nodes.statGamemode.value, 'Standard/Weltmodus (Default) · NBT-Wert 5', 'technical source stays intact');
  h.nodes.statPosX.value='<script>';
  h.controller.updateFacts();
  assert.equal(h.nodes.focusFactPosition.textContent,'—');
  h.root.dataset.layout='classic'; h.body.dataset.workflowView='world';
  h.controller.updateFacts();
});

test('wiring is idempotent and refresh delegates to existing player refresh', () => {
  const h=setup();
  h.controller.wire(); h.controller.wire();
  assert.equal(h.nodes.focusRefreshPlayers.listeners.click.length,1);
  h.nodes.focusRefreshPlayers.dispatch('click');
  assert.equal(h.getClicks(),1);
});

test('repeated focus/classic switches keep one warning element and do not duplicate player or equipment nodes', () => {
  const h=setup(); h.enable();
  for(let i=0;i<12;i++) {
    h.root.dataset.layout='focus'; h.controller.sync();
    assert.equal(h.nodes.inventoryContainer.children.filter(n=>n===h.nodes.worldPresenceBanner).length,1);
    assert.equal(h.nodes.focusPlayerListMount.children.filter(n=>n===h.nodes.playersList).length,1);
    assert.equal(h.nodes.inventorySection.children.filter(n=>n===h.nodes.equipment).length,1);
    h.root.dataset.layout=i%2===0?'studio':'classic'; h.controller.sync();
    assert.equal(h.nodes.worldSection.children.filter(n=>n===h.nodes.worldPresenceBanner).length,1);
    assert.equal(h.nodes.playerManager.children.filter(n=>n===h.nodes.playersList).length,1);
    assert.equal(h.nodes.inventorySection.children.filter(n=>n===h.nodes.equipment).length,1);
    assert.deepEqual(h.nodes.header.children.map(node => node.id), ['headerStatus','headerActions','history','panelToggle']);
  }
});

test('equipment keeps its parent, live handlers and identity across repeated layout syncs', () => {
  const h = setup(); h.enable();
  const equipment = h.nodes.equipment;
  const slot = h.nodes.equipmentSlot;
  let edits = 0;
  slot.addEventListener('click', () => edits++);
  for (const layout of ['focus', 'studio', 'classic', 'focus']) {
    h.root.dataset.layout = layout;
    h.controller.sync();
    // Repeated observer notifications must never reparent these live slots.
    for (let notification = 0; notification < 3; notification++) {
      h.controller.sync();
      slot.dispatch('click');
      assert.equal(equipment.parentNode, h.nodes.inventorySection);
      assert.equal(slot.parentNode, equipment);
      assert.equal(h.nodes.toolbar.nextSibling, equipment);
    }
  }
  assert.equal(edits, 12, 'the existing equipment handler fires once per click');
});


test('focus settings menu keeps original select nodes, closes on Escape/outside and resets on layout switch', () => {
  const h = setup(); h.controller.wire(); h.enable(); h.controller.sync();
  assert.equal(h.nodes.headerActions.parentNode, h.nodes.focusSettingsMount);
  h.nodes.focusSettingsToggle.dispatch('click');
  assert.equal(h.nodes.focusSettingsPanel.hidden, false);
  assert.equal(h.nodes.focusSettingsToggle.getAttribute('aria-expanded'), 'true');
  h.doc.dispatch('keydown', { key: 'Escape' });
  assert.equal(h.nodes.focusSettingsPanel.hidden, true);
  assert.equal(h.nodes.focusSettingsToggle.focused, true);
  h.nodes.focusSettingsToggle.dispatch('click');
  h.doc.dispatch('click', { target: h.nodes.body });
  assert.equal(h.nodes.focusSettingsPanel.hidden, true);
  h.nodes.focusSettingsToggle.dispatch('click');
  h.root.dataset.layout='studio'; h.controller.sync();
  assert.equal(h.nodes.headerActions.parentNode, h.nodes.header);
  assert.equal(h.nodes.focusSettingsPanel.hidden, true);
  assert.equal(h.nodes.focusSettingsToggle.getAttribute('aria-expanded'), 'false');
});


test('compact Focus status preserves write-block severity and full accessible server message', () => {
  const h = setup();
  h.root.dataset.layout = 'focus';
  for (const id of ['serverStatusBadge','statusStackButton','statusStackSummary','focusServerStatusText','focusServerStatusHint','languageSelect']) {
    h.nodes[id] = new Node(id);
  }
  const server = h.nodes.serverStatusBadge;
  const stack = h.nodes.statusStackButton;
  server.dataset = {};
  stack.dataset = {};
  server.textContent = 'Server: unbekannt · Schreiben gesperrt';
  server.title = 'Bevor du speicherst, Server manuell stoppen.';
  server.classList = { contains: cls => ['server-status-badge','unknown','blocked'].includes(cls) };
  stack.classList = { contains: cls => cls === 'warning' };
  h.nodes.statusStackSummary.textContent = 'Automatische Weltsuche läuft';
  h.nodes.languageSelect.value = 'de';
  h.controller.updateFocusStatusLabels();
  assert.equal(server.dataset.focusLabel, 'Schreiben gesperrt');
  assert.equal(stack.dataset.focusLabel, 'Hinweise');
  assert.equal(h.nodes.focusServerStatusText.textContent, server.textContent);
  assert.equal(h.nodes.focusServerStatusHint.textContent, server.title);
  assert.equal(server.getAttribute('role'), 'button');
  assert.equal(server.getAttribute('aria-controls'), 'focusServerStatusPanel');

  h.nodes.languageSelect.value = 'en';
  h.controller.updateFocusStatusLabels();
  assert.equal(server.dataset.focusLabel, 'Writes blocked');
  assert.equal(stack.dataset.focusLabel, 'Notices');
  server.classList = { contains: cls => cls === 'status-check-failed' };
  h.controller.updateFocusStatusLabels();
  assert.equal(server.dataset.focusLabel, 'Check failed');
});
