import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = fs.readFileSync('static/world_browser.js', 'utf8');

function setup(fetchResponse, { locale = 'de' } = {}) {
  const requests = [], statuses = [], toasts = [];
  const attributes = new Map();
  const button = {
    textContent: locale === 'en' ? 'Open folder' : 'Ordner öffnen',
    disabled: false,
    setAttribute: (key, value) => attributes.set(key, value),
    removeAttribute: key => attributes.delete(key),
  };
  const catalog = locale === 'en' ? JSON.parse(fs.readFileSync('static/i18n/en.json', 'utf8')) : {};
  const context = {
    fetch: (...args) => { requests.push(args); return fetchResponse(...args); },
    window: {
      t: (text, params = {}) => (catalog[text] ?? text).replace(/\{(\w+)\}/g, (whole, key) => params[key] ?? whole),
    },
  };
  vm.runInNewContext(fs.readFileSync('static/status_store.js', 'utf8'), context, { filename: 'status_store.js' });
  vm.runInNewContext(source, context, { filename: 'world_browser.js' });
  const statusStore = context.window.MCBEStatusStore.createStatusStore();
  const controller = context.window.MCBEWorldBrowser.createWorldBrowserController({
    elements: { openSelectedWorldButton: button },
    withCsrf: () => ({ 'Content-Type': 'application/json', 'X-CSRF-Token': 'test-token' }),
    logStatus: (message, type, options = {}) => {
      statuses.push([message, type, options]);
      statusStore.addNotice({ message, type, ...options });
    },
    showToast: (...args) => toasts.push(args),
  });
  return { controller, button, attributes, requests, statuses, toasts, statusStore };
}

test('folder opening reports pending and success and prevents duplicate launches', async () => {
  let resolve;
  const h = setup(() => new Promise(done => { resolve = done; }));
  const first = h.controller.openPathInFileManager('C:/Welten/Meine Welt');
  assert.equal(h.attributes.get('aria-busy'), 'true');
  assert.equal(h.attributes.get('aria-disabled'), 'true');
  assert.equal(h.button.textContent, 'Öffne Ordner…');
  assert.equal(h.statusStore.allNotices()[0].active, true, 'the shared status store recognizes the request as running');
  await h.controller.openPathInFileManager('C:/Welten/Meine Welt');
  assert.equal(h.requests.length, 1, 'a second click must not open another window');
  assert.equal(h.requests[0][0], '/api/open_folder');
  assert.equal(h.requests[0][1].headers['X-CSRF-Token'], 'test-token');
  assert.deepEqual(JSON.parse(h.requests[0][1].body), { path: 'C:/Welten/Meine Welt' });
  resolve({ ok: true, json: async () => ({ success: true }) });
  await first;
  assert.equal(h.attributes.size, 0);
  assert.equal(h.button.textContent, 'Ordner öffnen');
  assert.equal(h.toasts.length, 1);
  assert.equal(h.toasts[0][1], 'success');
  assert.ok(h.toasts[0][2] >= 6000, 'the foreground hint needs enough reading time');
  assert.match(h.toasts[0][0], /Taskleiste/);
  assert.equal(h.statuses.at(-1)[1], 'success');
  assert.equal(h.statuses[0][2].key, h.statuses.at(-1)[2].key, 'terminal status replaces pending status');
  assert.equal(h.statusStore.allNotices().length, 1);
  assert.equal(h.statusStore.allNotices()[0].active, false);
});

for (const [name, response] of [
  ['API rejection', async () => ({ ok: true, json: async () => ({ success: false, error: 'Kein Zugriff' }) })],
  ['HTTP error despite a success payload', async () => ({ ok: false, json: async () => ({ success: true }) })],
  ['unreadable response', async () => ({ ok: true, json: async () => { throw new Error('Ungültige Antwort'); } })],
  ['network failure', async () => { throw new Error('Verbindung unterbrochen'); }],
]) {
  test(`folder opening restores the control after ${name}`, async () => {
    const h = setup(response);
    await h.controller.openPathInFileManager('/worlds/test');
    assert.equal(h.attributes.size, 0);
    assert.equal(h.button.textContent, 'Ordner öffnen');
    assert.equal(h.toasts.length, 1);
    assert.equal(h.toasts[0][1], 'error');
    assert.equal(h.statuses.at(-1)[1], 'error');
    await h.controller.openPathInFileManager('/worlds/test');
    assert.equal(h.requests.length, 2, 'a failed request must allow retry');
  });
}

test('late folder responses preserve native disabled state after clearing the world', async () => {
  let resolve;
  const h = setup(() => new Promise(done => { resolve = done; }));
  const pending = h.controller.openPathInFileManager('/worlds/old');
  h.button.disabled = true; // The separate world-status view cleared the selection.
  resolve({ ok: true, json: async () => ({ success: true }) });
  await pending;
  assert.equal(h.button.disabled, true);
  assert.equal(h.attributes.size, 0);
  assert.match(h.statuses.at(-1)[0], /\/worlds\/old/, 'feedback identifies the requested path');
});

test('an empty folder path has no side effects', async () => {
  const h = setup(() => { throw new Error('must not launch'); });
  await h.controller.openPathInFileManager('');
  assert.equal(h.requests.length, 0);
  assert.equal(h.statuses.length, 0);
  assert.equal(h.toasts.length, 0);
});

test('folder opening feedback uses the active English locale', async () => {
  const h = setup(async () => ({ ok: true, json: async () => ({ success: true }) }), { locale: 'en' });
  await h.controller.openPathInFileManager('/worlds/test');
  assert.equal(h.button.textContent, 'Open folder');
  assert.equal(h.statuses[0][0], 'Opening folder…');
  assert.match(h.statuses.at(-1)[0], /^Folder handed to the file manager:/);
  assert.match(h.toasts[0][0], /taskbar or Dock/);
});
