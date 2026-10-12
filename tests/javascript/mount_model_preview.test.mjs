import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../../static/mount_model_preview.js', import.meta.url), 'utf8');

function load(translate) {
  const window = translate ? { t: translate } : {};
  vm.runInNewContext(source, { window });
  return window.MCBEMountModelPreview;
}

function element(attributes = {}) {
  const attrs = new Map(Object.entries(attributes));
  const listeners = new Map();
  const classes = new Set();
  const captures = new Set();
  return {
    innerHTML: '', textContent: '', listeners,
    classList: { add: value => classes.add(value), remove: value => classes.delete(value), contains: value => classes.has(value) },
    getAttribute: name => attrs.has(name) ? attrs.get(name) : null,
    setAttribute: (name, value) => attrs.set(name, value),
    addEventListener(name, handler) {
      if (!listeners.has(name)) listeners.set(name, new Set());
      listeners.get(name).add(handler);
    },
    removeEventListener: (name, handler) => listeners.get(name)?.delete(handler),
    setPointerCapture: id => captures.add(id),
    hasPointerCapture: id => captures.has(id),
    releasePointerCapture: id => captures.delete(id),
    dispatch(name, values = {}) {
      const event = { target: this, ...values, prevented: false, preventDefault() { this.prevented = true; } };
      for (const handler of listeners.get(name) || []) handler(event);
      return event;
    },
  };
}

function fixture() {
  const stage = element({ 'data-yaw': '0.58' });
  const svg = element();
  const caption = element();
  const buttons = ['left', 'reset', 'right'].map(action => element({ 'data-model-action': action }));
  const host = element();
  host.matches = selector => selector === '#mountModelPreview';
  host.querySelector = selector => ({ '.mount-model-stage': stage, '.mount-model-svg': svg, '.mount-model-appearance': caption })[selector];
  host.querySelectorAll = () => buttons;
  return { host, stage, svg, caption, buttons };
}

test('each mount has a distinct Minecraft-style appearance and the random horse is an explicitly labelled stable example', () => {
  const api = load();
  const models = ['horse', 'donkey', 'mule', 'camel', 'skeleton_horse'].map(type => api.markup({ mountType: `minecraft:${type}` }));
  assert.equal(new Set(models.map(markup => markup.match(/<svg class="mount-model-svg"[\s\S]*?<\/svg>/)[0])).size, 5);
  for (const markup of models) {
    assert.match(markup, /class="mount-model-texels" transform="matrix\([-\d. ]+\)"/);
    assert.match(markup, /<path d="M[\d,]+h\d+v1h-\d+z/);
    assert.doesNotMatch(markup, /<image|https?:|NaN|Infinity/);
  }
  const first = api.markup({ horseProfile: { mode: 'random_like_game', color: 0, mark_variant: 0 } });
  const second = api.markup({ horseProfile: { mode: 'random_like_game', color: 6, mark_variant: 4 } });
  assert.equal(first, second);
  assert.match(first, /Beispiel · zufälliges Aussehen/);
  assert.match(first, /data-random="true"/);
});

test('all seven coat colors and five markings produce visible differences in custom mode', () => {
  const api = load();
  const rendered = (color, mark_variant) => api.markup({ horseProfile: { mode: 'custom', color, mark_variant } }).match(/<svg class="mount-model-svg"[\s\S]*?<\/svg>/)[0];
  assert.equal(new Set(Array.from({ length: 7 }, (_, color) => rendered(color, 0))).size, 7);
  assert.equal(new Set(Array.from({ length: 5 }, (_, mark) => rendered(2, mark))).size, 5);
});

test('untrusted option values cannot become markup or geometry, and translated labels are escaped', () => {
  const payload = '"><img src=x onerror=alert(1)>';
  const markup = load().markup({ mountType: payload, horseProfile: { mode: 'custom', color: payload, mark_variant: payload } });
  assert.doesNotMatch(markup, /onerror|<img|NaN/);
  assert.match(markup, /data-mount-type="minecraft:horse"/);
  const translated = load(() => payload).markup();
  assert.match(translated, /&quot;&gt;&lt;img/);
  assert.doesNotMatch(translated, /<img/);
});

test('profile changes update the existing visual while a view survives reattachment', () => {
  const api = load();
  const first = fixture();
  const controller = api.attach(first.host, { horseProfile: { mode: 'custom', color: 2, mark_variant: 0 } });
  first.buttons[2].dispatch('click');
  const savedView = controller.getView();
  const previous = first.svg.innerHTML;
  controller.update({ horseProfile: { mode: 'custom', color: 4, mark_variant: 3 } });
  assert.notEqual(first.svg.innerHTML, previous);
  assert.equal(first.caption.textContent, 'Schwarz · Weiße Punkte');
  assert.equal(controller.getView().yaw, savedView.yaw);
  controller.destroy();
  const second = fixture();
  const restored = api.attach(second.host, { mountType: 'minecraft:camel', view: savedView });
  assert.equal(restored.getView().yaw, savedView.yaw);
  assert.equal(second.stage.getAttribute('data-mount-type'), 'minecraft:camel');
});

test('keyboard rotation is scoped, resettable and fully removed on destruction', () => {
  const api = load();
  const { host, stage, buttons } = fixture();
  const controller = api.attach(host);
  const initial = controller.getView().yaw;
  assert.equal(stage.dispatch('keydown', { key: 'ArrowLeft' }).prevented, true);
  assert.ok(controller.getView().yaw < initial);
  assert.equal(stage.dispatch('keydown', { key: 'ArrowDown' }).prevented, false);
  assert.equal(stage.dispatch('keydown', { key: 'ArrowRight', ctrlKey: true }).prevented, false);
  assert.equal(stage.dispatch('keydown', { key: 'ArrowRight', target: buttons[0] }).prevented, false);
  stage.dispatch('keydown', { key: 'Home' });
  assert.ok(Math.abs(controller.getView().yaw - initial) < 1e-12);
  controller.destroy();
  for (const node of [stage, ...buttons]) for (const handlers of node.listeners.values()) assert.equal(handlers.size, 0);
  stage.dispatch('keydown', { key: 'ArrowRight' });
  assert.ok(Math.abs(controller.getView().yaw - initial) < 1e-12);
});

test('vertical touch gestures remain available to page scroll; horizontal gestures capture and cancel cleanly', () => {
  const api = load();
  const { host, stage } = fixture();
  const controller = api.attach(host);
  const initial = controller.getView().yaw;
  stage.dispatch('pointerdown', { pointerId: 1, clientX: 100, clientY: 100 });
  assert.equal(stage.dispatch('pointermove', { pointerId: 1, clientX: 102, clientY: 124, cancelable: true }).prevented, false);
  assert.equal(stage.hasPointerCapture(1), false);
  assert.equal(controller.getView().yaw, initial);
  stage.dispatch('pointerdown', { pointerId: 2, clientX: 100, clientY: 100 });
  assert.equal(stage.dispatch('pointermove', { pointerId: 2, clientX: 144, clientY: 103, cancelable: true }).prevented, true);
  assert.equal(stage.hasPointerCapture(2), true);
  assert.equal(stage.classList.contains('is-dragging'), true);
  assert.notEqual(controller.getView().yaw, initial);
  stage.dispatch('pointercancel', { pointerId: 2 });
  assert.equal(stage.hasPointerCapture(2), false);
  assert.equal(stage.classList.contains('is-dragging'), false);
});

test('reattaching one DOM card disposes its previous listeners', () => {
  const api = load();
  const { host, stage } = fixture();
  const previous = api.attach(host);
  const next = api.attach(host);
  assert.equal(stage.listeners.get('keydown').size, 1);
  const before = previous.getView().yaw;
  stage.dispatch('keydown', { key: 'ArrowRight' });
  assert.equal(previous.getView().yaw, before);
  assert.notEqual(next.getView().yaw, before);
  next.destroy();
});

test('re-entering after mouseup outside the stage cannot resume a pending drag', () => {
  const api = load();
  const { host, stage } = fixture();
  const controller = api.attach(host);
  const initial = controller.getView().yaw;
  const mouse = { pointerId: 1, pointerType: 'mouse', clientY: 100 };
  stage.dispatch('pointerdown', { ...mouse, clientX: 198, buttons: 1 });
  stage.dispatch('pointermove', { ...mouse, clientX: 202, buttons: 1 });
  assert.equal(stage.hasPointerCapture(1), false);
  // Pointerup occurs outside before capture; only the next hover is received.
  stage.dispatch('pointermove', { ...mouse, clientX: 158, buttons: 0 });
  assert.equal(controller.getView().yaw, initial);
  assert.equal(stage.classList.contains('is-dragging'), false);
  assert.equal(stage.hasPointerCapture(1), false);
  // A fresh gesture with the button held still rotates normally.
  stage.dispatch('pointerdown', { ...mouse, clientX: 150, buttons: 1 });
  stage.dispatch('pointermove', { ...mouse, clientX: 174, buttons: 1 });
  assert.notEqual(controller.getView().yaw, initial);
  assert.equal(stage.hasPointerCapture(1), true);
  controller.destroy();
});


test('taming never invents equipment, and non-horse materials ignore the remembered horse profile', () => {
  const api = load();
  const scene = options => api.markup(options).match(/<svg class="mount-model-svg"[\s\S]*?<\/svg>/)[0];
  for (const type of ['horse', 'donkey', 'mule', 'camel', 'skeleton_horse']) {
    assert.equal(scene({ mountType: `minecraft:${type}`, mountTamed: false }), scene({ mountType: `minecraft:${type}`, mountTamed: true }));
  }
  for (const type of ['donkey', 'mule', 'camel', 'skeleton_horse']) {
    assert.equal(scene({ mountType: `minecraft:${type}`, horseProfile: { mode: 'custom', color: 0, mark_variant: 0 } }), scene({ mountType: `minecraft:${type}`, horseProfile: { mode: 'custom', color: 6, mark_variant: 4 } }));
  }
});

test('equine proportions stay shared, donkey and mule retain their client scales, and bones use open two-sided surfaces', () => {
  const api = load();
  const horse = api.markup({ mountType: 'minecraft:horse' });
  const skeleton = api.markup({ mountType: 'minecraft:skeleton_horse' });
  const face = (html, part, direction) => html.match(new RegExp(`<g data-model-part="${part}" data-model-face="${direction}">[\\s\\S]*?<g class="mount-model-texels" transform="matrix\\(([^)]+)\\)">`))?.[1];
  assert.equal(face(horse, 'body', 'near'), face(skeleton, 'body', 'near'));
  assert.equal(face(horse, 'head', 'near'), face(skeleton, 'head', 'near'));
  assert.ok(face(skeleton, 'body', 'far'), 'the rear rib surface remains visible through the front cutouts');
  assert.equal(face(horse, 'body', 'far'), undefined, 'opaque coats cull hidden rear faces');
  assert.match(skeleton, /data-model-material="bone-cutout"/);
  assert.doesNotMatch(skeleton, /<polygon/, 'opaque base polygons must not fill bone cutouts');
  assert.match(api.markup({ mountType: 'minecraft:donkey' }), /data-model-scale="0.87"/);
  assert.match(api.markup({ mountType: 'minecraft:mule' }), /data-model-scale="0.92"/);
});

test('all painted texels remain inside the viewport through a full rotation, including camel and long ears', () => {
  const api = load();
  const groups = /<g class="mount-model-texels" transform="matrix\(([^)]+)\)">([\s\S]*?)<\/g>/g;
  const pixels = /M(\d+),(\d+)h(\d+)v1h-\d+z/g;
  for (const type of ['horse', 'donkey', 'mule', 'camel', 'skeleton_horse']) {
    for (let step = 0; step < 24; step += 1) {
      const html = api.markup({ mountType: `minecraft:${type}`, view: { yaw: step * Math.PI / 12 } });
      let painted = 0;
      for (const group of html.matchAll(groups)) {
        const [a, b, c, d, e, f] = group[1].split(' ').map(Number);
        for (const pixel of group[2].matchAll(pixels)) {
          const [x, y, width] = pixel.slice(1).map(Number);
          for (const [u, v] of [[x, y], [x + width, y], [x + width, y + 1], [x, y + 1]]) {
            const px = a * u + c * v + e;
            const py = b * u + d * v + f;
            assert.ok(Number.isFinite(px) && Number.isFinite(py) && px >= 1 && px <= 359 && py >= 1 && py <= 259, `${type}, angle ${step * 15}°, texel ${px}/${py} lies outside the viewport`);
          }
          painted += 1;
        }
      }
      assert.ok(painted > 50, `${type} should keep a complete textured model at every angle`);
    }
  }
});
