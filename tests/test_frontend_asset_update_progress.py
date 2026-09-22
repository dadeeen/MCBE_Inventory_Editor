import subprocess
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_progress_counters_cancellation_and_client_refresh():
    source = r"""
    const assert = require('assert/strict');
    const fs = require('fs');
    const vm = require('vm');
    const timers = new Map();
    let nextTimer = 0;
    const node = () => ({
        textContent: '', hidden: true, style: {}, attributes: {},
        classList: {
            values: new Set(), add(k) { this.values.add(k); }, remove(k) { this.values.delete(k); },
            toggle(k, on) { if (on) this.add(k); else this.remove(k); },
        },
        setAttribute(k, v) { this.attributes[k] = v; },
        removeAttribute(k) { delete this.attributes[k]; },
        querySelectorAll() { return []; },
    });
    const ids = ['loadingOverlay', 'loadingText', 'assetUpdateProgress', 'assetProgressPhase',
        'assetProgressValue', 'assetProgressAmount', 'assetProgressBar', 'assetProgressFill', 'assetProgressHint'];
    const nodes = Object.fromEntries(ids.map(id => [id, node()]));
    let nextResponse = null;
    const requests = [];
    const window = {
        crypto: require('crypto').webcrypto,
        fetch: async (url, options) => { requests.push({ url, options }); return await nextResponse; },
    };
    vm.runInNewContext(fs.readFileSync('static/asset_update_progress.js', 'utf8'), {
        window, document: { getElementById: id => nodes[id] }, Intl, Uint8Array, AbortController,
        setTimeout: (callback, delay) => { timers.set(++nextTimer, { callback, delay }); return nextTimer; },
        clearTimeout: id => timers.delete(id),
    });
    const progress = window.MCBEAssetUpdateProgress;
    const response = snapshot => ({ ok: true, json: async () => ({ progress: snapshot }) });
    async function tick(delay) {
        const timer = [...timers].find(([, value]) => value.delay === delay);
        assert.ok(timer, `No scheduled timer for ${delay}`);
        timers.delete(timer[0]);
        await timer[1].callback();
    }
    (async () => {
        let view = progress.progressView({ phase: 'downloading', current: 6.2e6, total: 14.4e6, unit: 'bytes' });
        assert.equal(view.percent, 43);
        assert.equal(view.amount, '6,2 / 14,4 MB');
        view = progress.progressView({ phase: 'downloading', current: 6.2e6, unit: 'bytes' });
        assert.equal(view.percent, null, 'Unknown sizes must not show a fabricated percentage');
        assert.equal(view.amount, '6,2 MB geladen');
        assert.equal(progress.progressView({ phase: 'rendering', current: 3, total: 8, unit: 'items' }).percent, 37);
        assert.equal(progress.progressView({ phase: 'validating', current: 100, total: 100 }).percent, null);
        assert.equal(progress.progressView({ phase: 'cached' }).percent, null);

        const tracker = progress.start('Icon update');
        assert.match(tracker.headers['X-MCBE-Progress'], /^[a-f0-9]{32}$/);
        assert.equal(progress.isRunning(), true);
        nextResponse = response({ phase: 'downloading', current: 5, total: 10, unit: 'bytes' });
        await tick(250);
        assert.equal(nodes.assetProgressValue.textContent, '50 %');
        assert.equal(nodes.assetProgressBar.attributes['aria-valuenow'], '50');
        assert.ok(requests[0].url.endsWith(tracker.headers['X-MCBE-Progress']));
        assert.equal(requests[0].options.cache, 'no-store');

        nextResponse = response(null);
        await tick(1000); await tick(1000); await tick(1000);
        assert.match(nodes.assetProgressHint.textContent, /nicht verfügbar/);
        nextResponse = response({ phase: 'cached' });
        await tick(1000);
        assert.equal(nodes.assetProgressBar.attributes['aria-valuenow'], undefined);
        assert.match(nodes.assetProgressHint.textContent, /Cache/);

        let resolvePoll;
        nextResponse = new Promise(resolve => { resolvePoll = resolve; });
        const pending = tick(1000);
        tracker.finalizing();
        assert.equal(requests.at(-1).options.signal.aborted, true);
        resolvePoll(response({ phase: 'downloading', current: 9, total: 10, unit: 'bytes' }));
        await pending;
        assert.match(nodes.assetProgressPhase.textContent, /abgeschlossen/);
        assert.equal(nodes.assetProgressBar.attributes['aria-valuenow'], undefined);
        assert.equal(timers.size, 0, 'Client refresh must not keep polling the removed snapshot');
        assert.equal(nodes.assetUpdateProgress.hidden, false);

        tracker.stop();
        assert.equal(nodes.assetUpdateProgress.hidden, true);
        assert.equal(progress.isRunning(), false);
        const second = progress.start('Second update');
        tracker.stop();
        assert.equal(nodes.assetUpdateProgress.hidden, false, 'Late cleanup cannot hide a newer tracker');
        second.stop();
        assert.equal(timers.size, 0);
    })().catch(error => { console.error(error); process.exitCode = 1; });
    """
    result = subprocess.run(["node", "-e", textwrap.dedent(source)], cwd=ROOT, capture_output=True, text=True, timeout=15, check=False)
    assert result.returncode == 0, result.stderr + result.stdout
