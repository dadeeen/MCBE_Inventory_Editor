import textwrap

from tests.node_runner import run_node


def test_frontend_world_cards_view_empty_and_status_html_escape_values() -> None:
    run_node(
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
    run_node(
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
            assert.ok(html.includes('role="option" aria-selected="true" tabindex="0"'));
            assert.ok(html.includes('role="group" aria-label="Quelle &lt;lokal&gt;"'));
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


def test_world_results_keep_one_tab_stop_separate_from_the_selected_option() -> None:
    run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {} };
            vm.runInNewContext(fs.readFileSync("static/world_cards_view.js", "utf8"), context);
            const view = context.window.MCBEWorldCardsView;
            const worlds = Array.from({length:100}, (_, index) => ({
                name:`Welt ${index}`,path:`/worlds/${index}`,source:index < 50 ? "A" : "B",
            }));
            const html = view.worldCardsHtml(worlds, {
                selectedPath:"/worlds/0",tabStopPath:"/worlds/99",sourceLabelForWorld:world=>world.source,
            });
            assert.strictEqual((html.match(/tabindex="0"/g) || []).length, 1);
            assert.strictEqual((html.match(/aria-selected="true"/g) || []).length, 1);
            assert.ok(html.includes('aria-selected="false" tabindex="0" data-world-path="/worlds/99"'));
            assert.ok(html.includes('aria-selected="true" tabindex="-1" data-world-path="/worlds/0"'));
            assert.ok(html.includes('aria-label="Welt 99"'));
            assert.strictEqual((html.match(/role="group"/g) || []).length, 2);
            const filtered = view.worldCardsHtml(worlds.slice(50), {selectedPath:"/worlds/0"});
            assert.ok(filtered.includes('tabindex="0" data-world-path="/worlds/50"'));
            assert.strictEqual((filtered.match(/aria-selected="true"/g) || []).length, 0);
            const duplicates = view.worldCardsHtml([
                {name:'Survival',path:'/A',folder:'A'},
                {name:'Survival',path:'/B',folder:'B'},
            ]);
            assert.ok(duplicates.includes('aria-label="Survival · A"'));
            assert.ok(duplicates.includes('aria-label="Survival · B"'));
            """
        )
    )
