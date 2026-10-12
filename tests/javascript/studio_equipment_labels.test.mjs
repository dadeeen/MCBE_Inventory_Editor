import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const template = readFileSync(new URL('../../templates/index.html', import.meta.url), 'utf8');
const css = readFileSync(new URL('../../static/layout_variants.css', import.meta.url), 'utf8');
const inventoryRenderer = readFileSync(new URL('../../static/inventory_rendering.js', import.meta.url), 'utf8');
const english = JSON.parse(readFileSync(new URL('../../static/i18n/en.json', import.meta.url), 'utf8'));

const slots = [
  ['103', 'Helm'],
  ['102', 'Brust'],
  ['101', 'Beine'],
  ['100', 'Füße'],
  ['-106', 'Nebenhand'],
];

test('equipment captions have their own translated element instead of the enchantment pseudo-element', () => {
  for (const [id, label] of slots) {
    const slot = template.match(new RegExp(`<div class="inventory-slot (?:armor|offhand)-slot" data-slot="${id}"[^>]*>([\\s\\S]*?)<\\/div>\\s*<span class="studio-equipment-label" aria-hidden="true">\\{\\{ t\\("${label}"\\) \\}\\}<\\/span>`));
    assert.ok(slot, `Missing translated label for equipment slot ${id}`);
    assert.ok(english[label], `English translation missing: ${label}`);
  }
  assert.doesNotMatch(template, /data-studio-label=/);
  assert.doesNotMatch(css, /(?:\.armor-slot|\.offhand-slot)::before\s*\{\s*content:\s*attr\(data-studio-label\)/);
  // Visual behavior across all three designs (including enchanted equipment)
  // is covered by design_polish_smoke.py; captions are no longer Studio-only.
  assert.match(css, /:root\[data-layout="studio"\] body\[data-workflow-view="inventory"\] \.armor-slot > \.studio-equipment-label/);
});

test('equipment label survives real slot rendering and does not interfere with click targets', () => {
  // The renderer deliberately removes only the dynamic children. The label
  // is a static, pointer-transparent child and must not be removed.
  assert.match(inventoryRenderer, /function removeSlotChildren\(slotEl\)/);
  const dynamicChildren = inventoryRenderer.match(/function removeSlotChildren\(slotEl\) \{\s*\[([\s\S]*?)\]/)?.[1] || '';
  assert.doesNotMatch(dynamicChildren, /studio-equipment-label/);
  assert.match(css, /\.offhand-slot > \.studio-equipment-label\s*\{[\s\S]*?pointer-events: none;/);
});
