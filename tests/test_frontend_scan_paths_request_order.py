"""Late scan-path replies must not resurrect removed or superseded roots."""

import json
import textwrap

import pytest

from tests.node_runner import run_node


@pytest.mark.parametrize("latest", ["success", "refused", "transport"])
def test_scan_paths_ignore_a_superseded_success_reply(latest):
    script = textwrap.dedent(
        r"""
        const assert = require('assert');
        const fs = require('fs');
        const vm = require('vm');
        const context = {window: {}, console};
        vm.runInNewContext(fs.readFileSync('static/scan_paths_controller.js', 'utf8'), context);
        const pending = [];
        const hints = [];
        const list = {innerHTML: 'existing-view', querySelectorAll: () => []};
        const controller = context.window.MCBEScanPathsController.createScanPathsController({
            elements: {list},
            fetchImpl: () => new Promise((resolve, reject) => pending.push({resolve, reject})),
            parseJsonResponse: async response => response,
            withCsrf: () => ({}),
            scanPathsHtml: data => data.scan_roots.join(','),
            updateAutoPathHint: value => hints.push(value),
            consoleObj: {error() {}},
        });
        (async () => {
            const oldRequest = controller.loadScanPaths();
            const newRequest = controller.loadScanPaths();
            if (latest === 'transport') pending[1].reject(new Error('offline'));
            else pending[1].resolve({success: latest === 'success', scan_roots: ['new-root'], default_path: 'new-default'});
            await newRequest;
            pending[0].resolve({success: true, scan_roots: ['removed-root'], default_path: 'old-default'});
            assert.strictEqual(await oldRequest, false);
            assert.strictEqual(list.innerHTML, latest === 'success' ? 'new-root' : 'existing-view');
            assert.strictEqual(hints.length, latest === 'success' ? 1 : 0);
            assert.ok(!hints.some(hint => hint.includes('old-default')));
        })().catch(error => { console.error(error); process.exitCode = 1; });
        """
    )
    run_node(f"const latest = {json.dumps(latest)};\n{script}")
