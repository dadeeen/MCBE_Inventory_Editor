"""Session history keeps real actions, their context and safe display text."""

from tests.node_runner import run_node


def test_session_log_keeps_same_second_actions_and_their_original_context():
    run_node(r"""
const assert = require('node:assert/strict');
global.window = global;
require('./static/session_log.js');
const container = { innerHTML: '' }, clear = { disabled: false };
let player = 'Alex', world = 'World A', renders = 0;
const log = MCBESessionLog.createStatusSessionController({
    elements: { sessionLogContainer: container, clearSessionLogButton: clear },
    getCurrentPlayerLabel: () => player, getWorldName: () => world,
    getCurrentPlayer: () => ({}),
    renderUndoRedoPanel: () => renders++, maxSessionLog: 3,
});
log.recordAction('Move 2 to 11');
log.recordAction('Move 11 to 2');
assert.equal(renders, 2);
assert.equal((container.innerHTML.match(/role="listitem"/g) || []).length, 2);
player = 'Sam'; world = 'World B';
log.recordAction('<img src=x onerror=alert(1)>');
assert.ok(container.innerHTML.includes('&lt;img'));
assert.ok(!container.innerHTML.includes('<img'));
assert.ok(container.innerHTML.includes('Alex'));
assert.ok(container.innerHTML.includes('Sam'));
const copied = log.buildSessionLogText();
assert.ok(copied.includes('Alex'));
assert.ok(copied.includes('World A'));
assert.ok(copied.indexOf('Move 2 to 11') < copied.indexOf('Move 11 to 2'));
log.recordAction('Fourth');
assert.ok(!container.innerHTML.includes('Move 2 to 11'));
log.clearSessionLog();
assert.equal(renders, 4); // Clearing the log never changes the undo stack.
assert.equal(clear.disabled, true);
assert.ok(!log.buildSessionLogText().includes('Fourth'));
""")
