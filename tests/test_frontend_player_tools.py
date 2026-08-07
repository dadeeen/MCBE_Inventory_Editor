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


def test_frontend_player_tools_row_html_escapes_model_text() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const htmlUtilsCode = fs.readFileSync("static/html_utils.js", "utf8");
            const viewModelsCode = fs.readFileSync("static/player_view_models.js", "utf8");
            const toolsCode = fs.readFileSync("static/player_tools.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(htmlUtilsCode, context, { filename: "static/html_utils.js" });
            vm.runInNewContext(viewModelsCode, context, { filename: "static/player_view_models.js" });
            vm.runInNewContext(toolsCode, context, { filename: "static/player_tools.js" });

            const tools = context.window.MCBEPlayerTools;
            const html = tools.playerRowHtml({
                name: "<Alex>",
                badgeClass: "player-badge readonly",
                badgeText: "Nur <Export>",
                badgeTitle: "Grund \"unsafe\"",
                meta: "Nicht & bearbeitbar",
            });
            assert.ok(html.includes("&lt;Alex&gt;"));
            assert.ok(html.includes("Nur &lt;Export&gt;"));
            assert.ok(html.includes("title=\"Grund &quot;unsafe&quot;\""));
            assert.ok(html.includes("Nicht &amp; bearbeitbar"));
            assert.ok(!html.includes("<Alex>"));
            """
        )
    )


def test_frontend_player_tools_row_element_uses_model_state_and_html() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const viewModelsCode = fs.readFileSync("static/player_view_models.js", "utf8");
            const toolsCode = fs.readFileSync("static/player_tools.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(viewModelsCode, context, { filename: "static/player_view_models.js" });
            vm.runInNewContext(toolsCode, context, { filename: "static/player_tools.js" });

            const tools = context.window.MCBEPlayerTools;
            const created = [];
            const doc = {
                createElement(tagName) {
                    const classNames = new Set();
                    const el = {
                        tagName,
                        type: "",
                        className: "",
                        disabled: false,
                        innerHTML: "",
                        classList: {
                            add(name) {
                                classNames.add(name);
                                el.className = [el.className, name].filter(Boolean).join(" ");
                            },
                            contains(name) {
                                return classNames.has(name);
                            },
                        },
                    };
                    created.push(el);
                    return el;
                },
            };
            const model = tools.playerRowModel({
                player_key: "p1",
                label: "Alex <main>",
                editable: true,
                kind: "remote",
            }, "p1");
            const row = tools.playerRowElement(model, doc);

            assert.strictEqual(created.length, 1);
            assert.strictEqual(row.tagName, "button");
            assert.strictEqual(row.type, "button");
            assert.strictEqual(row.className, "player-row active");
            assert.strictEqual(row.disabled, false);
            assert.ok(row.innerHTML.includes("Alex &lt;main&gt;"));
            assert.ok(row.innerHTML.includes("Multiplayer · Klick zum Bearbeiten"));

            const disabled = tools.playerRowElement({ ...model, active: false, canSelect: false }, doc);
            assert.strictEqual(disabled.disabled, true);
            assert.strictEqual(disabled.className, "player-row");
            """
        )
    )


def test_frontend_player_tools_list_status_html_formats_known_states() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const viewModelsCode = fs.readFileSync("static/player_view_models.js", "utf8");
            const toolsCode = fs.readFileSync("static/player_tools.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(viewModelsCode, context, { filename: "static/player_view_models.js" });
            vm.runInNewContext(toolsCode, context, { filename: "static/player_tools.js" });

            const tools = context.window.MCBEPlayerTools;
            assert.strictEqual(
                tools.playerListStatusHtml("empty"),
                '<div class="no-backups">Keine Spieler-Datensätze erkannt.</div>',
            );
            assert.strictEqual(
                tools.playerListStatusHtml("loading"),
                '<div class="no-backups">Suche Spieler...</div>',
            );
            assert.strictEqual(
                tools.playerListStatusHtml("loadError"),
                '<div class="no-backups error">Spieler konnten nicht geladen werden.</div>',
            );
            assert.strictEqual(
                tools.playerListStatusHtml("connectionError"),
                '<div class="no-backups error">Verbindungsfehler beim Laden der Spieler.</div>',
            );
            """
        )
    )


def test_frontend_player_tools_options_html_escapes_and_disables_current() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const htmlUtilsCode = fs.readFileSync("static/html_utils.js", "utf8");
            const viewModelsCode = fs.readFileSync("static/player_view_models.js", "utf8");
            const toolsCode = fs.readFileSync("static/player_tools.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(htmlUtilsCode, context, { filename: "static/html_utils.js" });
            vm.runInNewContext(viewModelsCode, context, { filename: "static/player_view_models.js" });
            vm.runInNewContext(toolsCode, context, { filename: "static/player_tools.js" });

            const tools = context.window.MCBEPlayerTools;
            const model = tools.playerToolOptionModels([
                { player_key: "local", label: "Alex <main>", editable: true },
                { player_key: "other", label: "Steve & Co", editable: true },
            ], {
                currentPlayerKey: "local",
                previousValue: "missing",
            });
            assert.strictEqual(model.selectedValue, "other");
            const html = tools.playerToolOptionsHtml(model, { disableCurrent: true });
            assert.ok(html.includes('value="local" disabled'));
            assert.ok(html.includes("Alex &lt;main&gt; (aktuell)"));
            assert.ok(html.includes("Steve &amp; Co"));
            assert.ok(!html.includes("Alex <main>"));
            assert.strictEqual(
                tools.playerToolOptionsHtml({ disabled: true }),
                '<option value="">Keine bearbeitbaren Spieler</option>',
            );
            """
        )
    )


def test_frontend_player_tools_copy_request_model() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const viewModelsCode = fs.readFileSync("static/player_view_models.js", "utf8");
            const toolsCode = fs.readFileSync("static/player_tools.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(viewModelsCode, context, { filename: "static/player_view_models.js" });
            vm.runInNewContext(toolsCode, context, { filename: "static/player_tools.js" });

            const tools = context.window.MCBEPlayerTools;
            assert.strictEqual(
                tools.copyFromPlayerRequestModel({ currentPlayerKey: "" }).message,
                "Lade zuerst den Zielspieler.",
            );
            assert.strictEqual(
                tools.copyFromPlayerRequestModel({ currentPlayerKey: "target", sourcePlayerKey: "target" }).message,
                "Wähle einen anderen Quellspieler.",
            );
            assert.strictEqual(
                tools.copyFromPlayerRequestModel({ currentPlayerKey: "target", sourcePlayerKey: "source" }).message,
                "Wähle mindestens einen Bereich.",
            );
            const valid = tools.copyFromPlayerRequestModel({
                currentPlayerKey: "target",
                sourcePlayerKey: "source",
                useInventory: true,
                sourceLabel: "Steve",
                targetLabel: "Alex",
            });
            assert.strictEqual(valid.valid, true);
            assert.strictEqual(valid.message, "");
            assert.strictEqual(
                valid.confirmationText,
                "Daten von Steve in Alex übernehmen? Die Änderung bleibt bis zum Speichern nur lokal und kann per Undo rückgängig gemacht werden.",
            );
            """
        )
    )


def test_frontend_player_tools_snapshot_counts_only_repairable_damage_as_damaged() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const viewModelsCode = fs.readFileSync("static/player_view_models.js", "utf8");
            const toolsCode = fs.readFileSync("static/player_tools.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(viewModelsCode, context, { filename: "static/player_view_models.js" });
            vm.runInNewContext(toolsCode, context, { filename: "static/player_tools.js" });

            const tools = context.window.MCBEPlayerTools;
            const summary = tools.snapshotSummaryForComparison(
                {
                    inventory: {
                        0: { name: "minecraft:potion", count: 1, damage: 20 },
                        1: { name: "minecraft:iron_pickaxe", count: 1, damage: 4 },
                    },
                    ender_chest: {
                        0: { name: "minecraft:splash_potion", count: 1, damage: 25 },
                    },
                    stats: { xp_level: 7, health: 20, food_level: 18 },
                },
                item => !!(item && item.name && item.name !== "minecraft:air" && Number(item.count || 0) > 0),
                item => item.name === "minecraft:iron_pickaxe" && Number(item.damage || 0) > 0,
            );

            assert.strictEqual(summary.inv, 2);
            assert.strictEqual(summary.ec, 1);
            assert.strictEqual(summary.damaged, 1);
            assert.strictEqual(summary.xp, 7);
            """
        )
    )


def test_frontend_player_tools_strips_read_only_root_equipment_on_copy() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const viewModelsCode = fs.readFileSync("static/player_view_models.js", "utf8");
            const toolsCode = fs.readFileSync("static/player_tools.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(viewModelsCode, context, { filename: "static/player_view_models.js" });
            vm.runInNewContext(toolsCode, context, { filename: "static/player_tools.js" });

            const tools = context.window.MCBEPlayerTools;
            const result = tools.stripUntransferableRootEquipment({
                0: { name: "minecraft:apple", count: 3, slot: 0 },
                // Editierbare moderne Root-Ausrüstung bleibt übertragbar.
                103: { name: "minecraft:iron_helmet", count: 1, slot: 103, source_container: "inventory" },
                // Read-only Fallbacks (Legacy-Shape) dürfen nicht mitkopiert
                // werden: die Save-Pipeline würde sie still verwerfen.
                102: { name: "minecraft:diamond_chestplate", count: 1, slot: 102, root_equipment_read_only: true },
                "-106": { name: "minecraft:shield", count: 1, slot: -106, source_container: "offhand" },
            });

            assert.strictEqual(result.skipped, 2);
            assert.deepStrictEqual(Object.keys(result.inventory).sort(), ["0", "103"]);

            // Mit geladener Save-Payload-Logik entscheidet deren geteilter Filter.
            const savePayloadCode = fs.readFileSync("static/save_payload_logic.js", "utf8");
            vm.runInNewContext(savePayloadCode, context, { filename: "static/save_payload_logic.js" });
            const shared = tools.stripUntransferableRootEquipment({
                102: { name: "minecraft:diamond_chestplate", count: 1, slot: 102, root_equipment_read_only: true },
            });
            assert.strictEqual(shared.skipped, 1);
            """
        )
    )


def test_frontend_player_tools_does_not_copy_into_a_new_target_player() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const viewModelsCode = fs.readFileSync("static/player_view_models.js", "utf8");
            const toolsCode = fs.readFileSync("static/player_tools.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(viewModelsCode, context, { filename: "static/player_view_models.js" });
            vm.runInNewContext(toolsCode, context, { filename: "static/player_tools.js" });

            function deferred() {
                let resolve;
                const promise = new Promise(done => { resolve = done; });
                return { promise, resolve };
            }

            (async () => {
                const response = deferred();
                const state = { world: "world", target: "target-a" };
                let inventoryWrites = 0;
                let undoWrites = 0;
                const toasts = [];
                const loading = [];
                const controller = context.window.MCBEPlayerTools.createPlayerToolsController({
                    elements: {
                        copySourcePlayerSelect: { value: "source" },
                        copyInventoryArea: { checked: true },
                        copyEnderArea: { checked: false },
                        copyStatsArea: { checked: false },
                    },
                    getPlayers: () => [{ player_key: "source", label: "Quelle" }],
                    getWorldPath: () => state.world,
                    getCurrentPlayerKey: () => state.target,
                    currentPlayerLabel: () => state.target,
                    showConfirmDialog: async () => true,
                    api: { loadPlayerOrThrow: async () => response.promise },
                    setInventory: () => { inventoryWrites += 1; },
                    pushUndo: () => { undoWrites += 1; },
                    showToast: (message, type) => toasts.push({ message, type }),
                    showLoading: message => loading.push(["show", message]),
                    hideLoading: () => loading.push(["hide"]),
                });

                const copying = controller.copyFromSelectedPlayer();
                await new Promise(resolve => setImmediate(resolve));
                assert.deepStrictEqual(loading, [["show", "Spielerdaten werden für die Übernahme geladen..."]]);
                state.target = "target-b";
                response.resolve({ player: { label: "Quelle" }, inventory: { 0: { name: "minecraft:apple", count: 1 } } });
                await copying;

                assert.strictEqual(inventoryWrites, 0);
                assert.strictEqual(undoWrites, 0);
                assert.ok(toasts.some(toast => toast.type === "warning" && toast.message.includes("Zielspieler")));
                assert.deepStrictEqual(loading, [
                    ["show", "Spielerdaten werden für die Übernahme geladen..."],
                    ["hide"],
                ]);
            })().catch(error => {
                console.error(error);
                process.exit(1);
            });
            """
        )
    )


def test_frontend_player_api_exposes_safe_state_transfer_endpoints() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const apiCode = fs.readFileSync("static/player_api.js", "utf8");
            const calls = [];
            const context = { window: {}, fetch: async (url, options) => {
                calls.push({ url, options, body: JSON.parse(options.body) });
                return { json: async () => ({ success: true }) };
            } };
            vm.runInNewContext(apiCode, context, { filename: "static/player_api.js" });

            (async () => {
                const api = context.window.MCBEPlayerApi.createPlayerApiClient({
                    fetchFn: context.fetch,
                    withCsrf: () => ({ "Content-Type": "application/json", "X-CSRF-Token": "token" }),
                });
                await api.previewStateTransfer("world", "local", "remote");
                await api.applyStateTransfer({
                    worldPath: "world",
                    sourcePlayerKey: "local",
                    targetPlayerKey: "remote",
                    transferToken: { version: 4 },
                    serverGuardEpoch: 4,
                    serverGuardToken: "guard-token",
                    sessionId: "session-1",
                    confirmPresenceConflict: true,
                });

                assert.strictEqual(calls[0].url, "/api/player/state_transfer_preview");
                assert.deepStrictEqual(calls[0].body, {
                    world_path: "world",
                    source_player_key: "local",
                    target_player_key: "remote",
                });
                assert.strictEqual(calls[1].url, "/api/player/state_transfer");
                assert.strictEqual(calls[1].body.confirm_transfer, true);
                assert.strictEqual(calls[1].body.server_guard_epoch, 4);
                assert.strictEqual(calls[1].body.server_guard_token, "guard-token");
                assert.strictEqual(calls[1].body.session_id, "session-1");
                assert.strictEqual(calls[1].body.confirm_presence_conflict, true);
                assert.deepStrictEqual(calls[1].body.transfer_token, { version: 4 });
            })().catch(error => {
                console.error(error);
                process.exit(1);
            });
            """
        )
    )


def test_frontend_player_tools_previews_and_applies_state_transfer_with_backup() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const htmlUtilsCode = fs.readFileSync("static/html_utils.js", "utf8");
            const viewModelsCode = fs.readFileSync("static/player_view_models.js", "utf8");
            const toolsCode = fs.readFileSync("static/player_tools.js", "utf8");
            const context = { window: {}, fetch: async () => ({ json: async () => ({ success: true }) }) };
            vm.runInNewContext(htmlUtilsCode, context, { filename: "static/html_utils.js" });
            vm.runInNewContext(viewModelsCode, context, { filename: "static/player_view_models.js" });
            vm.runInNewContext(toolsCode, context, { filename: "static/player_tools.js" });

            function element(extra = {}) {
                return {
                    value: "",
                    innerHTML: "",
                    disabled: false,
                    checked: false,
                    style: { display: "none" },
                    attributes: {},
                    addEventListener() {},
                    setAttribute(name, value) { this.attributes[name] = String(value); },
                    removeAttribute(name) { delete this.attributes[name]; },
                    focus() { this.focused = true; },
                    ...extra,
                };
            }

            (async () => {
                const source = element();
                const target = element();
                const previewPanel = element();
                const applyButton = element({ disabled: true });
                const detailsButton = element();
                const detailsOverlay = element();
                const detailsBody = element();
                const detailsCloseButton = element();
                const apiCalls = [];
                const loading = [];
                let acceptPresenceConflict = false;
                const token = {
                    version: 4,
                    source_player_key: "local",
                    target_player_key: "remote",
                };
                const controller = context.window.MCBEPlayerTools.createPlayerToolsController({
                    elements: {
                        stateTransferSourcePlayerSelect: source,
                        stateTransferTargetPlayerSelect: target,
                        stateTransferPreview: previewPanel,
                        stateTransferPreviewButton: element(),
                        stateTransferApplyButton: applyButton,
                        stateTransferSwapButton: element(),
                        stateTransferDetailsOpenButton: detailsButton,
                        stateTransferDetailsOverlay: detailsOverlay,
                        stateTransferDetailsBody: detailsBody,
                        stateTransferDetailsCloseButton: detailsCloseButton,
                    },
                    getPlayers: () => [
                        { player_key: "local", label: "Local player", editable: true, kind: "local" },
                        { player_key: "remote", label: "Remote player", editable: true, kind: "remote" },
                    ],
                    getWorldPath: () => "C:/world",
                    getIsDirty: () => false,
                    writeBlocked: () => false,
                    getServerGuardEpoch: () => 3,
                    getWorldPresenceSessionId: () => "session-1",
                    confirmPresenceConflict: async () => acceptPresenceConflict,
                    showConfirmDialog: async () => true,
                    showLoading: message => loading.push(["show", message]),
                    hideLoading: () => loading.push(["hide"]),
                    api: {
                        previewStateTransfer: async (...args) => {
                            apiCalls.push(["preview", ...args]);
                            return {
                                success: true,
                                source_player: { label: "Local player" },
                                target_player: { label: "Remote player" },
                                transfer_token: token,
                                plan: {
                                    groups: [
                                        { id: "inventory", label: "Inventar und Ausrüstung", change_count: 4 },
                                        {
                                            id: "location",
                                            label: "Position, Spawnpunkt und letzter Todesort",
                                            change_count: 5,
                                            copied_fields: [
                                                "HasDiedBefore",
                                                "DeathDimension",
                                                "DeathPositionX",
                                                "DeathPositionY",
                                                "DeathPositionZ",
                                            ],
                                        },
                                        {
                                            id: "vitals",
                                            label: "Gesundheit, Hunger, Erschöpfung und Effekte",
                                            change_count: 1,
                                            copied_fields: ["TimeSinceRest"],
                                        },
                                        { id: "progress", label: "Erfahrung, Fortschritt und Rezepte", change_count: 1 },
                                    ],
                                    skipped_source_fields: ["UniqueID"],
                                    preserved_target_fields: ["UniqueID"],
                                    structured_fields: {
                                        attributes: {
                                            copied_fields: ["Attributes[minecraft:player.exhaustion]"],
                                            cleared_fields: [],
                                            preserved_target_fields: [],
                                            skipped_source_fields: [],
                                        },
                                        recipe_unlocking: {
                                            copied_fields: ["unlocked_recipes"],
                                            cleared_fields: [],
                                            preserved_target_fields: [],
                                            skipped_source_fields: [],
                                            source_present: true,
                                            source_recipe_count: 85,
                                            added_recipe_count: 23,
                                            result_recipe_count: 1641,
                                        },
                                    },
                                },
                            };
                        },
                        applyStateTransfer: async payload => {
                            apiCalls.push(["apply", payload]);
                            if (payload.confirmPresenceConflict !== true) {
                                return {
                                    success: false,
                                    error: "Andere Sitzung bearbeitet diese Welt.",
                                    presence_conflict: { conflict: true },
                                };
                            }
                            return {
                                success: true,
                                backup_file: "world_backup.zip",
                                validation: { transferred_field_count: 4 },
                                plan: {
                                    structured_fields: {
                                        recipe_unlocking: { added_recipe_count: 23 },
                                    },
                                },
                            };
                        },
                    },
                });

                controller.renderOptions();
                assert.strictEqual(source.value, "local");
                assert.strictEqual(target.value, "remote");
                assert.strictEqual(await controller.previewStateTransfer(), true);
                assert.strictEqual(applyButton.disabled, false);
                assert.ok(previewPanel.innerHTML.includes("Local player"));
                assert.ok(previewPanel.innerHTML.includes("23 fehlende Rezeptfreischaltungen"));
                assert.ok(previewPanel.innerHTML.includes("letzter Todesort"));
                assert.ok(previewPanel.innerHTML.includes("Erschöpfung"));
                assert.strictEqual(detailsButton.style.display, "inline-flex");
                assert.ok(detailsBody.innerHTML.includes("UniqueID"));
                assert.ok(detailsBody.innerHTML.includes("recipe_unlocking.unlocked_recipes"));
                assert.ok(detailsBody.innerHTML.includes("Letzter Todesort X"));
                assert.ok(detailsBody.innerHTML.includes("Attributes[minecraft:player.exhaustion]"));
                assert.strictEqual(controller.openStateTransferDetails(), true);
                assert.strictEqual(detailsOverlay.style.display, "flex");
                assert.strictEqual(detailsCloseButton.focused, true);
                controller.closeStateTransferDetails();
                assert.strictEqual(detailsOverlay.style.display, "none");
                assert.strictEqual(detailsButton.focused, true);
                assert.strictEqual(await controller.applyStateTransfer(), false);
                assert.strictEqual(applyButton.disabled, false);
                assert.ok(previewPanel.innerHTML.includes("Bearbeitungskonflikt"));
                assert.strictEqual(detailsButton.style.display, "inline-flex");

                acceptPresenceConflict = true;
                assert.strictEqual(await controller.applyStateTransfer(), true);
                assert.strictEqual(apiCalls[1][0], "apply");
                assert.strictEqual(apiCalls[1][1].serverGuardEpoch, 3);
                assert.strictEqual(apiCalls[1][1].transferToken, token);
                assert.strictEqual(apiCalls[1][1].sessionId, "session-1");
                assert.strictEqual(apiCalls[1][1].confirmPresenceConflict, false);
                assert.strictEqual(apiCalls[2][0], "apply");
                assert.strictEqual(apiCalls[2][1].confirmPresenceConflict, false);
                assert.strictEqual(apiCalls[3][0], "apply");
                assert.strictEqual(apiCalls[3][1].confirmPresenceConflict, true);
                assert.ok(previewPanel.innerHTML.includes("world_backup.zip"));
                assert.ok(previewPanel.innerHTML.includes("23 Rezeptfreischaltungen wurden ergänzt"));
                assert.ok(previewPanel.innerHTML.includes('class="state-transfer-result-path"'));
                assert.strictEqual(applyButton.disabled, true);
                assert.strictEqual(applyButton.textContent, "Migration gespeichert");
                assert.strictEqual(detailsButton.style.display, "none");
                assert.ok(loading.some(entry => entry[0] === "show" && entry[1].includes("Backup erstellen")));
                assert.ok(loading.some(entry => entry[0] === "show" && entry[1].includes("Spieleransicht")));
                assert.strictEqual(loading.at(-1)[0], "hide");
            })().catch(error => {
                console.error(error);
                process.exit(1);
            });
            """
        )
    )


def test_player_migration_uses_preview_then_final_confirmation_without_extra_checkbox() -> None:
    template = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    assert 'id="confirmStateTransfer"' not in template
    assert 't("Schritt 2")' not in template
    assert 't("Schritt 4")' not in template
    assert 'id="stateTransferDetailsOverlay"' in template
    assert 'aria-labelledby="stateTransferDetailsTitle"' in template
    assert 'id="btnCloseStateTransferDetails"' in template


def test_state_transfer_confirmation_is_single_flight_and_rechecks_world_context() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const viewModelsCode = fs.readFileSync("static/player_view_models.js", "utf8");
            const toolsCode = fs.readFileSync("static/player_tools.js", "utf8");
            const context = { window: {}, console };
            vm.runInNewContext(viewModelsCode, context, { filename: "static/player_view_models.js" });
            vm.runInNewContext(toolsCode, context, { filename: "static/player_tools.js" });

            function element(extra = {}) {
                return {
                    value: "",
                    innerHTML: "",
                    disabled: false,
                    style: { display: "none" },
                    attributes: {},
                    addEventListener() {},
                    setAttribute(name, value) { this.attributes[name] = String(value); },
                    removeAttribute(name) { delete this.attributes[name]; },
                    ...extra,
                };
            }

            (async () => {
                const source = element();
                const target = element();
                const applyButton = element({ disabled: true });
                let worldPath = "C:/world";
                let confirmCalls = 0;
                let resolveConfirmation;
                let applyCalls = 0;
                let hideLoadingCalls = 0;
                const toasts = [];
                const confirmation = new Promise(resolve => { resolveConfirmation = resolve; });
                const controller = context.window.MCBEPlayerTools.createPlayerToolsController({
                    elements: {
                        stateTransferSourcePlayerSelect: source,
                        stateTransferTargetPlayerSelect: target,
                        stateTransferPreview: element(),
                        stateTransferPreviewButton: element(),
                        stateTransferApplyButton: applyButton,
                        stateTransferSwapButton: element(),
                    },
                    getPlayers: () => [
                        { player_key: "local", label: "Local player", editable: true, kind: "local" },
                        { player_key: "remote", label: "Remote player", editable: true, kind: "remote" },
                    ],
                    getWorldPath: () => worldPath,
                    getIsDirty: () => false,
                    writeBlocked: () => false,
                    showToast: (message, type) => toasts.push({ message, type }),
                    showConfirmDialog: async () => {
                        confirmCalls += 1;
                        return confirmation;
                    },
                    hideLoading: () => { hideLoadingCalls += 1; },
                    api: {
                        previewStateTransfer: async () => ({
                            success: true,
                            source_player: { label: "Local player" },
                            target_player: { label: "Remote player" },
                            transfer_token: {
                                version: 4,
                                source_player_key: "local",
                                target_player_key: "remote",
                            },
                            plan: { groups: [] },
                        }),
                        applyStateTransfer: async () => {
                            applyCalls += 1;
                            return { success: true };
                        },
                    },
                });

                controller.renderOptions();
                assert.strictEqual(await controller.previewStateTransfer(), true);
                const firstApply = controller.applyStateTransfer();
                assert.strictEqual(applyButton.disabled, true);
                assert.strictEqual(applyButton.attributes["aria-busy"], "true");
                assert.strictEqual(await controller.applyStateTransfer(), false);
                assert.strictEqual(confirmCalls, 1);

                worldPath = "C:/other-world";
                resolveConfirmation(true);
                assert.strictEqual(await firstApply, false);
                assert.strictEqual(applyCalls, 0);
                assert.strictEqual(hideLoadingCalls, 0);
                assert.strictEqual(applyButton.disabled, true);
                assert.strictEqual(applyButton.attributes["aria-busy"], undefined);
                assert.ok(toasts.some(entry => (
                    entry.type === "warning"
                    && entry.message.includes("während der Bestätigung geändert")
                )));
            })().catch(error => {
                console.error(error);
                process.exit(1);
            });
            """
        )
    )


def test_state_transfer_discards_preview_response_after_selection_changes() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const viewModelsCode = fs.readFileSync("static/player_view_models.js", "utf8");
            const toolsCode = fs.readFileSync("static/player_tools.js", "utf8");
            const context = { window: {}, console };
            vm.runInNewContext(viewModelsCode, context, { filename: "static/player_view_models.js" });
            vm.runInNewContext(toolsCode, context, { filename: "static/player_tools.js" });

            function element(extra = {}) {
                const listeners = {};
                return {
                    value: "",
                    innerHTML: "",
                    disabled: false,
                    style: { display: "none" },
                    listeners,
                    addEventListener(name, callback) { listeners[name] = callback; },
                    ...extra,
                };
            }

            (async () => {
                const source = element();
                const target = element();
                const previewPanel = element();
                const applyButton = element({ disabled: true });
                let resolvePreview;
                const pendingResponse = new Promise(resolve => { resolvePreview = resolve; });
                const controller = context.window.MCBEPlayerTools.createPlayerToolsController({
                    elements: {
                        stateTransferSourcePlayerSelect: source,
                        stateTransferTargetPlayerSelect: target,
                        stateTransferPreview: previewPanel,
                        stateTransferPreviewButton: element(),
                        stateTransferApplyButton: applyButton,
                        stateTransferSwapButton: element(),
                    },
                    getPlayers: () => [
                        { player_key: "local", label: "Local player", editable: true, kind: "local" },
                        { player_key: "remote", label: "Remote player", editable: true, kind: "remote" },
                    ],
                    getWorldPath: () => "C:/world",
                    api: { previewStateTransfer: async () => pendingResponse },
                });

                controller.renderOptions();
                controller.wire();
                const pending = controller.previewStateTransfer();
                source.value = "remote";
                source.listeners.change();
                assert.strictEqual(target.value, "local");

                resolvePreview({
                    success: true,
                    source_player: { label: "Local player" },
                    target_player: { label: "Remote player" },
                    transfer_token: { source_player_key: "local", target_player_key: "remote" },
                    plan: { groups: [] },
                });

                assert.strictEqual(await pending, false);
                assert.strictEqual(previewPanel.innerHTML, "");
                assert.strictEqual(previewPanel.style.display, "none");
                assert.strictEqual(applyButton.disabled, true);
            })().catch(error => {
                console.error(error);
                process.exit(1);
            });
            """
        )
    )


def test_frontend_failed_migration_rollback_invalidates_preview_and_reloads_player_state() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const viewModelsCode = fs.readFileSync("static/player_view_models.js", "utf8");
            const toolsCode = fs.readFileSync("static/player_tools.js", "utf8");
            const context = { window: {}, console };
            vm.runInNewContext(viewModelsCode, context, { filename: "static/player_view_models.js" });
            vm.runInNewContext(toolsCode, context, { filename: "static/player_tools.js" });

            function element(extra = {}) {
                return {
                    value: "",
                    innerHTML: "",
                    disabled: false,
                    style: { display: "none" },
                    addEventListener() {},
                    ...extra,
                };
            }

            (async () => {
                const source = element();
                const target = element();
                const previewPanel = element();
                const applyButton = element({ disabled: true });
                let refreshes = 0;
                const toasts = [];
                const token = {
                    version: 4,
                    source_player_key: "local",
                    target_player_key: "remote",
                };
                const controller = context.window.MCBEPlayerTools.createPlayerToolsController({
                    elements: {
                        stateTransferSourcePlayerSelect: source,
                        stateTransferTargetPlayerSelect: target,
                        stateTransferPreview: previewPanel,
                        stateTransferPreviewButton: element(),
                        stateTransferApplyButton: applyButton,
                        stateTransferSwapButton: element(),
                    },
                    getPlayers: () => [
                        { player_key: "local", label: "Local player", editable: true, kind: "local" },
                        { player_key: "remote", label: "Remote player", editable: true, kind: "remote" },
                    ],
                    getWorldPath: () => "C:/world",
                    getIsDirty: () => false,
                    writeBlocked: () => false,
                    showToast: (message, type) => { toasts.push({ message, type }); },
                    showConfirmDialog: async () => true,
                    refreshAfterStateTransfer: async () => { refreshes += 1; },
                    api: {
                        previewStateTransfer: async () => ({
                            success: true,
                            source_player: { label: "Local player" },
                            target_player: { label: "Remote player" },
                            transfer_token: token,
                            plan: { groups: [] },
                        }),
                        applyStateTransfer: async () => ({
                            success: false,
                            write_committed: true,
                            rolled_back: false,
                            error: "Migrations-Rollback unvollständig",
                            cleanup_warning: "Zusätzliches Backup blieb zurück",
                        }),
                    },
                });

                controller.renderOptions();
                assert.strictEqual(await controller.previewStateTransfer(), true);
                assert.strictEqual(applyButton.disabled, false);
                assert.strictEqual(await controller.applyStateTransfer(), false);
                assert.strictEqual(refreshes, 1);
                assert.strictEqual(applyButton.disabled, true);
                assert.ok(previewPanel.innerHTML.includes("Migrations-Rollback unvollständig"));
                assert.ok(toasts.some(entry => entry.type === "warning" && entry.message.includes("Zusätzliches Backup")));
                assert.strictEqual(await controller.applyStateTransfer(), false);
                assert.strictEqual(refreshes, 1);
            })().catch(error => {
                console.error(error);
                process.exit(1);
            });
            """
        )
    )
