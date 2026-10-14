import textwrap

from tests.node_runner import run_node


def test_world_source_labels_use_active_locale_and_preserve_custom_labels() -> None:
    run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const catalog = JSON.parse(fs.readFileSync("static/i18n/en.json", "utf8"));
            const t = text => catalog[text] ?? text;
            const context = { window: { t, MCBEI18n: { compare: (a, b) => a.localeCompare(b, "en") } } };
            vm.runInNewContext(fs.readFileSync("static/api_client.js", "utf8"), context, { filename: "static/api_client.js" });
            vm.runInNewContext(fs.readFileSync("static/world_browser.js", "utf8"), context, {
                filename: "static/world_browser.js",
            });

            const labels = context.window.MCBEWorldBrowser.sourceLabelForWorld;
            assert.strictEqual(labels({ source_kind: "configured-root", source_label: "Konfigurierter Welt-Root" }), "Configured world root");
            assert.strictEqual(labels({ source_kind: "minecraft-default", source_label: "Minecraft-Standardordner" }), "Minecraft default folder");
            assert.strictEqual(labels({ source_kind: "user-root", source_label: "Meine Welten" }), "Meine Welten");
            """
        ),
    )


def test_world_scan_ignores_older_response() -> None:
    run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");

            function deferred() {
                let resolve;
                const promise = new Promise(done => { resolve = done; });
                return { promise, resolve };
            }

            const responses = [];
            const context = {
                console,
                fetch: () => {
                    const next = deferred();
                    responses.push(next);
                    return next.promise;
                },
                window: {
                    MCBEWorldCardsView: {
                        applyWorldCardsRender: () => true,
                        worldSearchStatusHtml: (title, body) => `${title}:${body}`,
                        applyWorldDiagnostics: () => {},
                    },
                    MCBEScanPathsView: { scanRootKindLabel: () => "root" },
                    MCBEPlayerDiagnostics: {
                        buildWorldDiagnosticsText: () => "",
                        buildPlayersDiagnosticsText: () => "",
                    },
                },
            };
            vm.runInNewContext(fs.readFileSync("static/api_client.js", "utf8"), context, { filename: "static/api_client.js" });
            vm.runInNewContext(fs.readFileSync("static/world_browser.js", "utf8"), context, { filename: "static/world_browser.js" });

            (async () => {
                let lastScan = null;
                const rendered = [];
                const loading = { style: {} };
                const controller = context.window.MCBEWorldBrowser.createWorldBrowserController({
                    elements: {
                        worldList: { innerHTML: "", querySelectorAll: () => [] },
                        worldPicker: { style: {} },
                        scanLoading: loading,
                        scanWarning: { style: {}, textContent: "" },
                        scanEmpty: { style: {}, innerHTML: "" },
                        countHint: { textContent: "" },
                    },
                    getLastWorldScan: () => lastScan,
                    setLastWorldScan: value => { lastScan = value; },
                    setLastRenderedWorlds: worlds => rendered.push(worlds.map(world => world.name)),
                    parseJsonResponse: response => response.json(),
                });

                const first = controller.scanWorlds();
                const second = controller.scanWorlds();
                responses[1].resolve({ json: async () => ({ success: true, worlds: [{ name: "new", path: "/new" }] }) });
                await second;
                assert.strictEqual(lastScan.worlds[0].name, "new");
                assert.strictEqual(loading.style.display, "none");

                responses[0].resolve({ json: async () => ({ success: true, worlds: [{ name: "old", path: "/old" }] }) });
                await first;
                assert.strictEqual(lastScan.worlds[0].name, "new");
                assert.deepStrictEqual(rendered[rendered.length - 1], ["new"]);
                assert.strictEqual(loading.style.display, "none");
            })().catch(error => {
                console.error(error);
                process.exit(1);
            });
            """
        ),
    )


def test_world_folder_picker_replaces_running_status_with_terminal_status() -> None:
    run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const statuses = [];
            const selected = [];
            const worldPathInput = { value: "" };
            const context = {
                window: {},
                fetch: async () => ({ payload: { success: true, path: "C:/World" } }),
            };
            vm.runInNewContext(fs.readFileSync("static/api_client.js", "utf8"), context, { filename: "static/api_client.js" });
            vm.runInNewContext(fs.readFileSync("static/world_browser.js", "utf8"), context, {
                filename: "static/world_browser.js",
            });
            const controller = context.window.MCBEWorldBrowser.createWorldBrowserController({
                elements: { worldPathInput },
                parseJsonResponse: async response => response.payload,
                updateSelectedWorld: world => selected.push(world),
                logStatus: (message, type, options) => statuses.push({ message, type, options }),
            });

            (async () => {
                await controller.browseWorldFolder();
                assert.strictEqual(worldPathInput.value, "C:/World");
                assert.strictEqual(selected.length, 1);
                assert.strictEqual(statuses[0].type, "running");
                assert.strictEqual(statuses.at(-1).type, "info");
                assert.ok(statuses.every(entry => entry.options.key === "world-folder-picker"));
            })().catch(error => {
                console.error(error);
                process.exit(1);
            });
            """
        ),
    )


def test_world_list_navigation_preserves_selection_focus_and_scroll() -> None:
    run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const doc = { activeElement:null };
            const searchInput = {value:"",focus(){doc.activeElement=this;}};
            let cards = [];
            let html = "";
            const list = {
                ownerDocument:doc,scrollTop:0,
                contains:node=>cards.includes(node),querySelectorAll:()=>cards,
                get innerHTML(){return html;},
                set innerHTML(value){
                    if(cards.includes(doc.activeElement)) doc.activeElement=null;
                    html=value;
                    cards=[...value.matchAll(/<button[^>]*tabindex="(-?\d+)"[^>]*data-world-path="([^"]+)"[^>]*>/g)].map(match=>({
                        tabIndex:Number(match[1]),dataset:{worldPath:match[2]},listeners:{},
                        addEventListener(type,handler){this.listeners[type]=handler;},
                        focus(options){doc.activeElement=this;this.focusOptions=options;this.listeners.focus?.();},
                    }));
                },
            };
            let rendered=[];
            let selected=null;
            const worlds=Array.from({length:100},(_,index)=>({name:index===87?'Zielwelt':`Welt ${index}`,path:`/worlds/${index}`}));
            const context={window:{}};
            for(const name of ['world_cards_view.js','world_browser.js']){
                vm.runInNewContext(fs.readFileSync(`static/${name}`,'utf8'),context,{filename:name});
            }
            const controller=context.window.MCBEWorldBrowser.createWorldBrowserController({
                elements:{worldList:list,searchInput},
                getLastWorldScan:()=>({worlds}),getLastRenderedWorlds:()=>rendered,
                setLastRenderedWorlds:value=>{rendered=value;},getSelectedWorld:()=>selected,
                updateSelectedWorld:value=>{selected=value;},
            });
            const key=(value)=>{
                let prevented=false;
                doc.activeElement.listeners.keydown({key:value,preventDefault(){prevented=true;}});
                return prevented;
            };
            controller.renderWorldCards(worlds);
            cards[0].focus();
            assert.strictEqual(key('ArrowDown'),true);
            assert.strictEqual(doc.activeElement.dataset.worldPath,'/worlds/1');
            assert.strictEqual(selected,null,'Arrow navigation must not select or load a world');
            key('End');
            assert.strictEqual(doc.activeElement.dataset.worldPath,'/worlds/99');
            assert.strictEqual(key('Tab'),false,'Tab must leave the list normally');
            list.scrollTop=912;
            const oldCard=doc.activeElement;
            oldCard.listeners.click();
            assert.strictEqual(selected.path,'/worlds/99');
            assert.notStrictEqual(doc.activeElement,oldCard,'A render replaced the old option');
            assert.strictEqual(doc.activeElement.dataset.worldPath,'/worlds/99');
            assert.strictEqual(doc.activeElement.focusOptions.preventScroll,true);
            assert.strictEqual(list.scrollTop,912,'Selection must preserve the scroll position');
            assert.strictEqual(cards.filter(card=>card.tabIndex===0).length,1);
            key('Home');
            assert.strictEqual(doc.activeElement.dataset.worldPath,'/worlds/0');
            key('z');
            assert.strictEqual(doc.activeElement.dataset.worldPath,'/worlds/87');
            assert.strictEqual(selected.path,'/worlds/99','Typeahead only moves focus');
            searchInput.focus();
            controller.renderWorldCards(worlds.slice(80,90));
            assert.strictEqual(doc.activeElement,searchInput,'Filtering must not steal search focus');
            assert.strictEqual(list.scrollTop,0);
            assert.strictEqual(cards.filter(card=>card.tabIndex===0).length,1);
            cards[0].focus();
            controller.renderWorldCards([]);
            assert.strictEqual(doc.activeElement,searchInput,'Removing the focused result must not strand focus');
            """
        )
    )
