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


def test_frontend_state_snapshot_take_snapshot_deep_clones_state() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/state_snapshot.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/state_snapshot.js" });

            const state = {
                inventory: { 0: { name: "minecraft:apple", count: 3 } },
                enderChestInventory: {},
                playerStats: { health: 20 },
                playerEffects: [{ id: 1, amplifier: 0 }],
                playerAbilities: { mayfly: false },
                pendingMounts: [{ id: "mount-1", selectedPosition: { x: 1, y: 64, z: 2 } }],
            };
            const snapshot = context.window.MCBEStateSnapshot.createStateSnapshot(() => state);
            const snap = snapshot.takeSnapshot();

            // Live-Mutationen dürfen den Snapshot nicht verändern (Undo/Redo-Invariante).
            state.inventory[0].count = 64;
            state.playerEffects[0].amplifier = 255;
            state.pendingMounts[0].selectedPosition.x = 99;
            assert.strictEqual(snap.inv[0].count, 3);
            assert.strictEqual(snap.effects[0].amplifier, 0);
            assert.strictEqual(snap.mounts[0].selectedPosition.x, 1);
            """
        )
    )


def test_frontend_state_snapshot_hash_and_section_changed() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/state_snapshot.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/state_snapshot.js" });

            const api = context.window.MCBEStateSnapshot;
            assert.strictEqual(api.snapshotHash({ a: 1 }), api.snapshotHash({ a: 1 }));
            assert.notStrictEqual(api.snapshotHash({ a: 1 }), api.snapshotHash({ a: 2 }));

            assert.strictEqual(api.sectionChanged({ x: 1 }, { x: 1 }), false);
            assert.strictEqual(api.sectionChanged({ x: 1 }, { x: 2 }), true);
            assert.strictEqual(api.sectionChanged(null, undefined), false);

            const original = { nested: { value: 1 } };
            const clone = api.cloneJson(original);
            clone.nested.value = 2;
            assert.strictEqual(original.nested.value, 1);
            """
        )
    )


def test_frontend_status_store_deduplicates_and_limits_notices() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/status_store.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/status_store.js" });

            const store = context.window.MCBEStatusStore.createStatusStore({ maxNotices: 3 });

            store.addNotice({ time: "10:00", type: "info", message: "A" });
            store.addNotice({ time: "10:01", type: "info", message: "A" });
            assert.strictEqual(store.allNotices().length, 1, "identische Folge-Notiz wird dedupliziert");
            assert.strictEqual(store.allNotices()[0].time, "10:01", "Dedupe aktualisiert die Zeit");

            store.addNotice({ message: "   " });
            assert.strictEqual(store.allNotices().length, 1, "leere Nachrichten werden ignoriert");

            store.addNotice({ message: "B" });
            store.addNotice({ message: "C" });
            store.addNotice({ message: "D" });
            assert.strictEqual(store.allNotices().length, 3, "maxNotices wird eingehalten");
            assert.strictEqual(store.allNotices()[0].message, "D", "neueste Notiz steht vorn");

            store.clear();
            store.addNotice({ time: "10:10", type: "running", message: "Update läuft", key: "db-update" });
            assert.strictEqual(store.allNotices()[0].active, true, "laufender Vorgang ist aktiv");
            store.addNotice({ time: "10:11", type: "success", message: "Update abgeschlossen", key: "db-update" });
            assert.strictEqual(store.allNotices().length, 1, "gleicher Vorgang wird ersetzt");
            assert.strictEqual(store.allNotices()[0].message, "Update abgeschlossen");
            assert.strictEqual(store.allNotices()[0].active, false, "Erfolg löst laufenden Vorgang auf");

            store.clear();
            store.addNotice({ type: "warning", message: "Neustart erforderlich", key: "restart", active: true });
            store.addNotice({ type: "success", message: "Erfolg 1" });
            store.addNotice({ type: "success", message: "Erfolg 2" });
            store.addNotice({ type: "success", message: "Erfolg 3" });
            const retained = store.allNotices();
            assert.strictEqual(retained.length, 3, "aktive Hinweise zählen zum Limit, werden aber nicht verdrängt");
            assert.ok(retained.some(entry => entry.key === "restart" && entry.active), "aktiver Hinweis bleibt erhalten");
            assert.ok(!retained.some(entry => entry.message === "Erfolg 1"), "ältester abgeschlossener Verlauf wird entfernt");

            store.clear();
            assert.strictEqual(store.allNotices().length, 0);
            """
        )
    )


def test_frontend_status_store_hides_transient_dirty_notices_when_clean() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/status_store.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/status_store.js" });

            const api = context.window.MCBEStatusStore;
            const store = api.createStatusStore();
            store.addNotice({ message: "normal" });
            store.addNotice({ message: "dirty hint", category: api.TRANSIENT_DIRTY_NOTICE_CATEGORY, key: "dirty" });

            assert.strictEqual(store.visibleNotices({ isDirty: true }).length, 2);
            assert.strictEqual(store.allNotices()[0].active, true);
            const clean = store.visibleNotices({ isDirty: false });
            assert.strictEqual(clean.length, 1);
            assert.strictEqual(clean[0].message, "normal");

            store.addNotice({ message: "Zwischenmeldung", type: "success" });
            store.addNotice({ message: "dirty hint", category: api.TRANSIENT_DIRTY_NOTICE_CATEGORY, key: "dirty" });
            const dirtyNotices = store.visibleNotices({ isDirty: true }).filter(entry => entry.category === api.TRANSIENT_DIRTY_NOTICE_CATEGORY);
            assert.strictEqual(dirtyNotices.length, 1, "wiederkehrender Dirty-Zustand wird per Schlüssel ersetzt");
            assert.strictEqual(store.removeNotice("dirty"), true);
            assert.strictEqual(store.visibleNotices({ isDirty: true }).some(entry => entry.category === api.TRANSIENT_DIRTY_NOTICE_CATEGORY), false);
            assert.strictEqual(store.removeNotice("dirty"), false, "bereits entfernter Zustand meldet keine Änderung");

            assert.strictEqual(api.isTransientDirtyStatusText(" Ungespeicherte Änderungen vorhanden "), true);
            assert.strictEqual(api.isTransientDirtyStatusText("anderer Text"), false);
            """
        )
    )
