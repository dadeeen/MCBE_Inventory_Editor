import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const template = readFileSync(new URL('../../templates/index.html', import.meta.url), 'utf8');
const css = readFileSync(new URL('../../static/layout_variants.css', import.meta.url), 'utf8');

const count = (text, pattern) => [...text.matchAll(pattern)].length;

test('context selectors and global save action have one shared instance in all layouts', () => {
  assert.equal(count(template, /id="layoutCurrentWorld"/g), 1);
  assert.equal(count(template, /id="layoutCurrentPlayer"/g), 1);
  assert.equal(count(template, /id="layoutSaveAction"/g), 1);
  assert.equal(count(template, /class="layout-context-bar"/g), 1);
  assert.equal(count(template, /class="app-section-nav app-workflow-nav"/g), 1);
  assert.match(template, /<div class="layout-controls">[\s\S]*?<nav class="app-section-nav app-workflow-nav"[\s\S]*?<\/nav>[\s\S]*?<section class="layout-context-bar"/);
});

test('visible navigation has no redundant grouping headings', () => {
  for (const className of ['layout-nav-heading', 'layout-context-caption', 'layout-nav-optional', 'layout-nav-admin']) {
    assert.doesNotMatch(template, new RegExp(`class="${className}"`));
  }
  assert.doesNotMatch(template, />\s*\{\{ t\("(Kontext|Bearbeiten|Verwalten|Optional)"\) \}\}\s*</);
  assert.match(template, /class="layout-context-name">\{\{ t\("Welt"\) \}\}/);
  assert.match(template, /class="layout-context-name">\{\{ t\("Spieler"\) \}\}/);
  assert.match(template, /data-workflow-view="inventory"/);
  assert.match(template, /data-workflow-view="player-edit"/);
  assert.match(template, /data-workflow-view="mounts"/);
});

test('studio docks the selectors with sidebar while classic stays flattened', () => {
  assert.match(css, /\.layout-controls \{ display: contents; \}/);
  assert.match(css, /:root\[data-layout="studio"\] \.layout-controls \{\s*display: flex/);
  assert.match(css, /:root\[data-layout="studio"\] \.layout-controls > \.layout-context-bar \{\s*display: contents/);
  assert.match(css, /:root\[data-layout="focus"\] \.layout-context-bar \{ order: -3; \}/);
});

test('studio alone clips body horizontally so its sidebar can stick to the viewport', () => {
  assert.match(css, /@media \(min-width: 1181px\) \{\s*:root\[data-layout="studio"\] body:not\(\.item-browser-open\) \{\s*overflow-x: clip;\s*overflow-y: visible;/);
  assert.match(css, /:root\[data-layout="studio"\] \.layout-controls \{[\s\S]*?position: sticky;/);
});

test('studio keeps the world load action above a bounded, scrollable result grid', () => {
  assert.match(css, /:root\[data-layout="studio"\] body\[data-workflow-view="world"\] #worldSection > #selectedWorldBar \{ order: -2; \}/);
  assert.match(css, /:root\[data-layout="studio"\] \.world-card-list \{[\s\S]*?max-height: clamp\([\s\S]*?overflow-y: auto;/);
  assert.match(css, /:root\[data-layout="studio"\] \.world-card-list \{[\s\S]*?grid-auto-rows: minmax\(76px, max-content\);[\s\S]*?overflow-y: auto;/);
  assert.doesNotMatch(css, /:root\[data-layout="studio"\] \.world-card-list > \.world-source-group \{/);
  assert.doesNotMatch(css, /:root\[data-layout="studio"\] \.world-card-list \.world-card-main small \{/);
});

test('studio removes only the extra worldSection border outside world selection', () => {
  assert.match(css, /:root\[data-layout="studio"\] body\.app-world-loaded:not\(\[data-workflow-view="world"\]\) #worldSection \{\s*padding: 0;\s*border: 0;/);
  assert.match(template, /id="selectedWorldBar"/);
});


test('studio viewport insets do not create a phantom page scroll at full height', () => {
  assert.match(css, /:root\[data-layout="studio"\] body \{ padding: 0 20px 18px; \}/);
  assert.match(css, /:root\[data-layout="studio"\] \.layout-controls \{[\s\S]*?top: 18px;[\s\S]*?height: calc\(100dvh - 36px\);/);
  assert.match(css, /:root\[data-layout="studio"\] \.world-card-list \{[\s\S]*?scrollbar-gutter: stable;/);
});
