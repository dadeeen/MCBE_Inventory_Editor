import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const customPath = '/worlds/custom';
const otherPath = '/worlds/other';
const fixedPath = '/worlds/configured';
const response = (customEnabled = true, otherEnabled = true) => ({ success: true, scan_roots: [
  { path: customPath, enabled: customEnabled, removable: true },
  { path: otherPath, enabled: otherEnabled, removable: true },
  { path: fixedPath, enabled: true, removable: false },
] });
const settle = () => new Promise(resolve => setImmediate(resolve));

function setup() {
  const requests = [];
  const status = { textContent: '' };
  let controls = [];
  const list = {
    set innerHTML(html) {
      // Replacing innerHTML creates new controls, as opening the panel does.
      controls = JSON.parse(html).scan_roots.map(root => ({
        checked: root.enabled,
        disabled: !root.removable,
        dataset: { path: root.path },
        handlers: {},
        addEventListener(name, handler) { this.handlers[name] = handler; },
      }));
    },
    querySelectorAll: selector => selector === '[data-scan-path-toggle]' ? controls : [],
  };
  const context = { window: {}, console };
  for (const path of ['static/api_client.js', 'static/scan_paths_controller.js']) {
    vm.runInNewContext(fs.readFileSync(path, 'utf8'), context, { filename: path });
  }
  const controller = context.window.MCBEScanPathsController.createScanPathsController({
    elements: { list, status },
    withCsrf: () => ({ 'Content-Type': 'application/json' }),
    parseJsonResponse: response => response,
    scanPathsHtml: JSON.stringify,
    consoleObj: { error() {} },
    fetchImpl: (url, options) => new Promise((resolve, reject) => {
      requests.push({ url, body: options?.body && JSON.parse(options.body), resolve, reject });
    }),
  });
  controller.renderScanPaths(response());
  const checkbox = (path = customPath) => controls.find(control => control.dataset.path === path);
  function userToggle(path = customPath) {
    const control = checkbox(path);
    if (control.disabled) return null;
    control.checked = !control.checked;
    return control.handlers.change();
  }
  async function reload(data = response()) {
    const pending = controller.loadScanPaths();
    requests.at(-1).resolve(data);
    await pending;
  }
  return { checkbox, requests, status, userToggle, reload };
}

test('a pending toggle stays locked across panel reloads and its own refresh', async () => {
  const h = setup();
  const original = h.checkbox();
  const pending = h.userToggle();
  assert.equal(h.userToggle(), null);
  assert.deepEqual(h.requests[0].body, { path: customPath, enabled: false });
  await h.reload();
  assert.notEqual(h.checkbox(), original);
  assert.equal(h.checkbox().disabled, true);
  assert.equal(h.userToggle(), null);
  await h.checkbox().handlers.change();
  assert.equal(h.requests.length, 2, 'even a dispatched change cannot submit a competing write');
  h.requests[0].resolve({ success: true });
  await settle();
  assert.equal(h.requests[2].url, '/api/scan_paths');
  assert.equal(h.checkbox().disabled, true);
  h.requests[2].resolve(response(false));
  await pending;
  assert.equal(h.checkbox().checked, false);
  assert.equal(h.checkbox().disabled, false);
  assert.equal(h.checkbox(fixedPath).disabled, true);
});

for (const failure of ['rejected', 'network']) {
  test(`${failure} toggle restores and unlocks the current checkbox after a reload`, async () => {
    const h = setup();
    const pending = h.userToggle();
    await h.reload(response(false));
    if (failure === 'network') h.requests[0].reject(new Error('Offline'));
    else h.requests[0].resolve({ success: false, error: 'Write rejected' });
    await pending;
    assert.equal(h.checkbox().checked, true);
    assert.equal(h.checkbox().disabled, false);
    assert.match(h.status.textContent, failure === 'network' ? /Verbindung/ : /Write rejected/);
    const retry = h.userToggle();
    assert.equal(h.requests.length, 3);
    h.requests[2].resolve({ success: false });
    await retry;
  });
}

test('a failed list refresh keeps the acknowledged setting on the current checkbox', async () => {
  const h = setup();
  const pending = h.userToggle();
  await h.reload();
  h.requests[0].resolve({ success: true });
  await settle();
  assert.equal(h.checkbox().disabled, true);
  h.requests[2].resolve({ success: false });
  await pending;
  assert.equal(h.checkbox().checked, false);
  assert.equal(h.checkbox().disabled, false);
});

test('an independent path can finish and refresh without unlocking the pending path', async () => {
  const h = setup();
  const first = h.userToggle();
  const second = h.userToggle(otherPath);
  h.requests[1].resolve({ success: true });
  await settle();
  h.requests[2].resolve(response(true, false));
  await second;
  assert.equal(h.checkbox().disabled, true);
  assert.equal(h.checkbox(otherPath).disabled, false);
  assert.equal(h.checkbox(otherPath).checked, false);
  assert.equal(h.userToggle(), null);
  h.requests[0].resolve({ success: true });
  await settle();
  h.requests[3].resolve(response(false, false));
  await first;
  assert.equal(h.checkbox().disabled, false);
  assert.equal(h.checkbox().checked, false);
  assert.equal(h.checkbox(fixedPath).disabled, true);
});

test('finishing a toggle preserves a newly fixed root as disabled', async () => {
  const h = setup();
  const pending = h.userToggle();
  const data = response();
  data.scan_roots[0].removable = false;
  await h.reload(data);
  h.requests[0].resolve({ success: false });
  await pending;
  assert.equal(h.checkbox().disabled, true);
  assert.equal(h.checkbox().checked, true);
});
