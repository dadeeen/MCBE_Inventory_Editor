"""A server-stopped confirmation must not authorize a later independent action."""

import json

import pytest

from tests.node_runner import run_node


_HARNESS = r"""
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
let dialogs = 0;
const node = () => ({
    style: {}, textContent: '', replaceChildren() {}, appendChild() {}, append() {},
    classList: { add() {} }, remove() {},
});
const okButton = node();
okButton.focus = () => {
    dialogs++;
    setTimeout(() => okButton.onclick?.(), 0);
};
const elements = {
    confirmOverlay: node(), confirmMessage: node(), confirmOk: okButton,
    confirmCancel: node(), loadingOverlay: node(),
};
const document = {
    body: { appendChild() {} }, querySelector: () => null,
    createElement: node, getElementById: id => elements[id] || null,
};
const calls = [];
const unknown = {
    success: false,
    write_gate: { allowed: false, requires_unknown_server_confirmation: true,
        server_status: { status: 'unknown' } },
};
const response = (data, status = 200) => new Response(JSON.stringify(data), {
    status, headers: { 'Content-Type': 'application/json' },
});
let confirmedAttempts = 0;
const window = {
    document, location: { href: 'http://127.0.0.1/' },
    fetch: async (path, init) => {
        const body = JSON.parse(init.body);
        calls.push(body);
        if (body.confirm_unknown_server_status !== true) return response(unknown, 409);
        confirmedAttempts++;
        if (confirmedAttempts === 1) {
            if (outcome === 'network') throw new TypeError('Failed to fetch');
            if (outcome === 'unreadable') return new Response('<html>Proxy unavailable</html>', { status: 502 });
            if (outcome === 'disk_full') return response({ success: false, error: 'No space left on device' }, 500);
            if (outcome === 'server_online') return response({ success: false, write_gate: { allowed: false, server_status: { status: 'online' } } }, 409);
            if (outcome === 'rolled_back') return response({ success: false, write_committed: false, rolled_back: true }, 500);
            if (outcome === 'presence') return response({ success: false, presence_conflict: { conflict: true } }, 409);
            if (outcome === 'reload_presence') return response({ success: false, reload_required: true, presence_conflict: { conflict: true } }, 409);
            if (outcome === 'ambiguous_presence') return response({ success: false, write_outcome_unknown: true, presence_conflict: { conflict: true } }, 500);
            if (outcome === 'committed_presence') return response({ success: false, write_committed: true, presence_conflict: { conflict: true } }, 500);
            if (outcome === 'empty_presence') return response({ success: false, presence_conflict: {} }, 409);
        }
        return response({ success: true });
    },
};
const context = { window, document, Response, URL, console, setTimeout };
// The production template loads the API client before the single fetch guard.
vm.runInNewContext(fs.readFileSync('static/api_client.js', 'utf8'), context);
vm.runInNewContext(fs.readFileSync('static/ui_feedback.js', 'utf8'), context);
const body = { world_path: '/worlds/Survival', server_guard_token: 'unchanged-token', backup_file: 'manual.zip' };
const send = (extra = {}) => window.fetch(path, { method: 'POST', body: JSON.stringify({ ...body, ...extra }) });
"""


@pytest.mark.parametrize("path", ["/api/backup/create", "/api/restore_backup", "/api/player/import", "/api/player/state_transfer"])
@pytest.mark.parametrize("outcome", ["network", "unreadable", "disk_full", "server_online", "rolled_back", "presence"])
def test_new_action_requires_fresh_confirmation(path: str, outcome: str) -> None:
    run_node(
        f"const path = {json.dumps(path)}; const outcome = {json.dumps(outcome)};\n"
        + _HARNESS
        + r"""
(async () => {
    try { await send(); } catch (error) { assert.strictEqual(outcome, 'network'); }
    assert.strictEqual(dialogs, 1);
    const later = await send();
    assert.strictEqual((await later.json()).success, true);
    assert.strictEqual(calls[2].confirm_unknown_server_status, undefined,
        'A later independent action must start without the earlier server-stopped confirmation');
    assert.strictEqual(dialogs, 2, 'A fresh server-status warning is required');
    assert.strictEqual(calls.length, 4);
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    )


@pytest.mark.parametrize("outcome", ["presence", "ambiguous_presence", "committed_presence", "reload_presence", "empty_presence", "disk_full"])
def test_only_definite_presence_conflict_continuation_reuses_confirmation(outcome: str) -> None:
    run_node(
        f"const path = '/api/restore_backup'; const outcome = {json.dumps(outcome)};\n"
        + _HARNESS
        + r"""
(async () => {
    await send();
    await send({ confirm_presence_conflict: true });
    const reusable = outcome === 'presence';
    assert.strictEqual(calls[2].confirm_unknown_server_status, reusable ? true : undefined);
    assert.strictEqual(dialogs, reusable ? 1 : 2);
    // A successful continuation also consumes the confirmation.
    const nextCall = calls.length;
    await send({ confirm_presence_conflict: true });
    assert.strictEqual(calls[nextCall].confirm_unknown_server_status, undefined);
    assert.strictEqual(dialogs, reusable ? 2 : 3);
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    )


@pytest.mark.parametrize("path", ["/api/backup/create", "/api/restore_backup", "/api/player/import", "/api/player/state_transfer"])
@pytest.mark.parametrize("flag", ["write_outcome_unknown", "write_committed", "reload_required", "response_unreadable"])
def test_fetch_guard_never_retries_a_potentially_completed_write(path: str, flag: str) -> None:
    run_node(
        f"const path = {json.dumps(path)}; const outcome = 'presence';\n"
        + _HARNESS
        + f"\nunknown[{json.dumps(flag)}] = true;\n"
        + r"""
(async () => {
    const result = await send();
    assert.strictEqual((await result.json()).success, false);
    assert.strictEqual(dialogs, 0, 'A confirmation cannot settle the outcome of a previous write');
    assert.strictEqual(calls.length, 1, 'Return the uncertain outcome to the controller without retrying');
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
    )
