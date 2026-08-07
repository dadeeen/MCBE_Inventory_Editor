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


def test_frontend_world_cards_view_empty_and_status_html_escape_values() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/world_cards_view.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/world_cards_view.js" });

            const view = context.window.MCBEWorldCardsView;
            assert.strictEqual(
                view.worldSearchStatusHtml("Fehler <A>", "Pfad & Server"),
                "<strong>Fehler &lt;A&gt;</strong><span>Pfad &amp; Server</span>",
            );
            assert.ok(view.emptyWorldsHtml("<Suchwert>").includes("&lt;Suchwert&gt;"));
            assert.ok(!view.emptyWorldsHtml("<Suchwert>").includes("<Suchwert>"));
            """
        )
    )


def test_frontend_world_cards_view_count_and_card_html() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/world_cards_view.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/world_cards_view.js" });

            const view = context.window.MCBEWorldCardsView;
            assert.strictEqual(view.worldCountText({ allCount: 1 }), "1 Welt gefunden");
            assert.strictEqual(
                view.worldCountText({ visibleCount: 2, allCount: 4, query: "nether" }),
                "2 von 4 Welten sichtbar",
            );

            const html = view.worldCardsHtml([{
                name: "Welt <A>",
                path: "C:/Worlds/A&B",
                folder: "A&B",
            }], {
                selectedPath: "C:/Worlds/A&B",
                dirtyWorldPath: "C:/Worlds/A&B",
                isDirty: true,
                sourceLabelForWorld: () => "Quelle <lokal>",
                formatModified: () => "heute",
            });

            assert.ok(html.includes("world-card selected"));
            assert.ok(html.includes("Ungespeichert"));
            assert.ok(html.includes("Welt &lt;A&gt;"));
            assert.ok(html.includes("Quelle &lt;lokal&gt;"));
            assert.ok(html.includes("A&amp;B"));
            assert.ok(!html.includes("Welt <A>"));

            const worldList = { innerHTML: "old" };
            const emptyEl = { innerHTML: "", style: { display: "none" } };
            const worldCountHint = { textContent: "" };
            assert.strictEqual(view.applyWorldCardsRender({ worldList, emptyEl, worldCountHint }, [], {
                allCount: 3,
                query: "nether",
            }), true);
            assert.strictEqual(worldList.innerHTML, "");
            assert.strictEqual(emptyEl.style.display, "flex");
            assert.strictEqual(worldCountHint.textContent, "0 von 3 Welten sichtbar");

            view.applyWorldCardsRender({ worldList, emptyEl, worldCountHint }, [{
                name: "A",
                path: "world-a",
                folder: "A",
            }]);
            assert.ok(worldList.innerHTML.includes("world-card"));
            assert.strictEqual(emptyEl.style.display, "none");

            const classes = new Set(["collapsed"]);
            const diagnostics = {
                innerHTML: "",
                style: { display: "none" },
                classList: {
                    contains: name => classes.has(name),
                    toggle: (name, enabled) => enabled ? classes.add(name) : classes.delete(name),
                },
            };
            view.applyWorldDiagnostics(diagnostics, {
                checked_dirs: 1,
                worlds: [{}],
                scan_roots: [{ kind: "custom", status: "ok", world_count: 1, path: "C:/Worlds" }],
            }, () => "Eigener Ort");
            assert.strictEqual(diagnostics.style.display, "block");
            assert.ok(diagnostics.innerHTML.includes("Eigener Ort"));
            """
        )
    )
