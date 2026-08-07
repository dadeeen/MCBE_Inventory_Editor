import subprocess
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run_node(source: str) -> None:
    result = subprocess.run(
        ["node", "-e", source],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout


def test_frontend_app_state_bridge_applies_known_patches_and_warns_unknown_keys() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/app_state_bridge.js", "utf8");
            const warnings = [];
            const context = { window: {}, console: { warn(message) { warnings.push(message); } } };
            vm.runInNewContext(code, context, { filename: "static/app_state_bridge.js" });

            const bridge = context.window.MCBEAppStateBridge;
            const state = { worldPath: "", isDirty: false };
            const assign = bridge.createPatchAssigner({
                worldPath: value => { state.worldPath = value; },
                isDirty: value => { state.isDirty = value; },
            }, {
                onUnknownKey: bridge.unknownPatchKeyLogger(context.console, "Unbekannt"),
            });

            assign({ worldPath: "C:/World", isDirty: true, typo: "ignored" });

            assert.deepStrictEqual(state, { worldPath: "C:/World", isDirty: true });
            assert.deepStrictEqual(warnings, ["Unbekannt: typo"]);
            assert.strictEqual(JSON.stringify(assign.knownKeys()), JSON.stringify(["worldPath", "isDirty"]));
            assert.strictEqual(
                JSON.stringify(bridge.pickState(
                    { worldPath: "C:/World", players: [1], ignored: true },
                    ["players", "worldPath"],
                )),
                JSON.stringify({ players: [1], worldPath: "C:/World" }),
            );
        """
        )
    )
