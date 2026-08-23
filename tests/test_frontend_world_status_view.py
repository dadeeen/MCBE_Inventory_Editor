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


def test_frontend_world_status_view_selected_world_bar_model() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/world_status_view.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/world_status_view.js" });

            const view = context.window.MCBEWorldStatusView;
            const hidden = view.selectedWorldBarModel({ selectedWorld: null });
            assert.strictEqual(hidden.visible, false);
            assert.strictEqual(hidden.loadDisabled, true);

            const searchResult = view.selectedWorldBarModel({
                selectedWorld: {
                    name: "Überleben",
                    folder: "WorldFolder",
                    path: "C:/minecraftWorlds/WorldFolder",
                },
                fromManual: false,
                isDocker: false,
            });
            assert.strictEqual(searchResult.visible, true);
            assert.strictEqual(searchResult.name, "Überleben");
            assert.strictEqual(searchResult.pathText, "Suchergebnis · WorldFolder");
            assert.strictEqual(searchResult.pathTitle, "C:/minecraftWorlds/WorldFolder");
            assert.strictEqual(searchResult.loadDisabled, false);
            assert.strictEqual(searchResult.openDisabled, false);
            assert.strictEqual(searchResult.openTitle, "Ausgewählten Weltordner im Dateimanager öffnen");

            const manualDocker = view.selectedWorldBarModel({
                selectedWorld: { path: "D:/World", source_label: "" },
                fromManual: true,
                isDocker: true,
            });
            assert.strictEqual(manualDocker.name, "Ausgewählte Welt");
            assert.strictEqual(manualDocker.pathText, "Manueller Pfad · D:/World");
            assert.strictEqual(manualDocker.openDisabled, true);
            assert.strictEqual(manualDocker.openTitle, "Im Docker-/LAN-Modus kann der Browser keinen Host-Explorer öffnen.");

            const hint = view.pathHintModel("Automatisch erkannt", "success");
            assert.strictEqual(hint.text, "Automatisch erkannt");
            assert.strictEqual(hint.className, "path-card-hint success");
            const neutralHint = view.pathHintModel("Bereit");
            assert.strictEqual(neutralHint.className, "path-card-hint");

            const hintEl = { textContent: "", className: "" };
            view.applyPathHintModel(hintEl, hint);
            assert.strictEqual(hintEl.textContent, "Automatisch erkannt");
            assert.strictEqual(hintEl.className, "path-card-hint success");
            """
        )
    )


def test_frontend_world_status_view_dirty_ui_model() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/world_status_view.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/world_status_view.js" });

            const view = context.window.MCBEWorldStatusView;
            const clean = view.dirtyUiModel({ worldPath: "C:/World", currentPlayerKey: "local", isDirty: false });
            assert.strictEqual(clean.dirtyBannerDisplay, "none");
            assert.strictEqual(clean.dirtyReviewDisabled, true);
            assert.strictEqual(clean.savePreviewDisabled, true);
            assert.strictEqual(clean.safeEditText, "Keine ungespeicherten Änderungen.");

            const dirty = view.dirtyUiModel({
                worldPath: "C:/World",
                currentPlayerKey: "local",
                isDirty: true,
                blocked: false,
                playerLabel: "Alex",
                changeTotal: 2,
            });
            assert.strictEqual(dirty.dirtyBannerDisplay, "flex");
            assert.strictEqual(dirty.dirtyBannerText, "Alex · 2 Änderungen · Backup automatisch vor dem Schreiben.");
            assert.strictEqual(dirty.dirtyReviewDisabled, false);
            assert.strictEqual(dirty.dirtySaveDisabled, false);
            assert.strictEqual(dirty.dirtyDiscardDisabled, false);
            assert.strictEqual(dirty.savePreviewDisabled, false);
            assert.strictEqual(dirty.saveDiscardDisabled, false);
            assert.strictEqual(dirty.safeEditDirty, true);
            assert.strictEqual(dirty.safeEditBlocked, false);
            assert.strictEqual(dirty.safeEditText, "Ungespeicherte Änderungen: 2 Änderungen");

            const blocked = view.dirtyUiModel({
                worldPath: "C:/World",
                currentPlayerKey: "local",
                isDirty: true,
                blocked: true,
                blockedReason: "Server online",
                playerLabel: "Alex",
                changeTotal: 1,
            });
            assert.strictEqual(blocked.dirtyReviewDisabled, true);
            assert.strictEqual(blocked.dirtySaveDisabled, true);
            assert.strictEqual(blocked.dirtyDiscardDisabled, false);
            assert.strictEqual(blocked.savePreviewDisabled, true);
            assert.strictEqual(blocked.saveDiscardDisabled, false);
            assert.strictEqual(blocked.safeEditText, "Ungespeicherte Änderungen: 1 Änderung · Server online");
            """
        )
    )


def test_frontend_world_status_view_applies_selected_world_dom_models() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/world_status_view.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/world_status_view.js" });

            const view = context.window.MCBEWorldStatusView;
            const elements = {
                bar: { style: { display: "" } },
                name: { textContent: "" },
                path: { textContent: "", title: "" },
                safetyNote: { textContent: "alt", style: { display: "inline-flex" } },
                loadButton: { disabled: true },
                openButton: { disabled: false, title: "" },
            };

            const visible = view.applySelectedWorldBarModel(elements, {
                visible: true,
                name: "Überleben",
                pathText: "Suchergebnis · World",
                pathTitle: "C:/World",
                loadDisabled: false,
                openDisabled: true,
                openTitle: "Docker",
            });
            assert.strictEqual(visible, true);
            assert.strictEqual(elements.bar.style.display, "flex");
            assert.strictEqual(elements.name.textContent, "Überleben");
            assert.strictEqual(elements.path.textContent, "Suchergebnis · World");
            assert.strictEqual(elements.path.title, "C:/World");
            assert.strictEqual(elements.safetyNote.textContent, "");
            assert.strictEqual(elements.safetyNote.style.display, "none");
            assert.strictEqual(elements.loadButton.disabled, false);
            assert.strictEqual(elements.openButton.disabled, true);
            assert.strictEqual(elements.openButton.title, "Docker");

            const hidden = view.applySelectedWorldBarModel(elements, { visible: false });
            assert.strictEqual(hidden, false);
            assert.strictEqual(elements.bar.style.display, "none");

            view.applySelectedWorldDirtyHint(elements.safetyNote, { visible: true, text: "Ungespeicherte Änderungen" });
            assert.strictEqual(elements.safetyNote.textContent, "Ungespeicherte Änderungen");
            assert.strictEqual(elements.safetyNote.style.display, "inline-flex");
            view.applySelectedWorldDirtyHint(elements.safetyNote, { visible: false });
            assert.strictEqual(elements.safetyNote.textContent, "");
            assert.strictEqual(elements.safetyNote.style.display, "none");
            """
        )
    )


def test_frontend_world_status_view_applies_and_clears_load_error_panel() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/world_status_view.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/world_status_view.js" });

            const view = context.window.MCBEWorldStatusView;
            const panel = { innerHTML: "", style: { display: "none" } };
            view.applyLoadErrorPanel(panel, "<strong>Fehler</strong>");
            assert.strictEqual(panel.innerHTML, "<strong>Fehler</strong>");
            assert.strictEqual(panel.style.display, "block");

            view.clearLoadErrorPanel(panel);
            assert.strictEqual(panel.innerHTML, "");
            assert.strictEqual(panel.style.display, "none");
            """
        )
    )


def test_frontend_world_status_view_applies_dirty_and_save_preview_models() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/world_status_view.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/world_status_view.js" });

            const view = context.window.MCBEWorldStatusView;
            const bannerElements = {
                banner: { style: { display: "" } },
                text: { textContent: "" },
                reviewButton: { disabled: true },
                saveButton: { disabled: true },
                discardButton: { disabled: true },
            };
            view.applyDirtyBannerModel(bannerElements, {
                dirtyBannerDisplay: "flex",
                dirtyBannerText: "Alex · 2 Änderungen · Backup automatisch vor dem Schreiben.",
                dirtyReviewDisabled: false,
                dirtySaveDisabled: false,
                dirtyDiscardDisabled: false,
            });
            assert.strictEqual(bannerElements.banner.style.display, "flex");
            assert.strictEqual(bannerElements.text.textContent, "Alex · 2 Änderungen · Backup automatisch vor dem Schreiben.");
            assert.strictEqual(bannerElements.reviewButton.disabled, false);
            assert.strictEqual(bannerElements.saveButton.disabled, false);
            assert.strictEqual(bannerElements.discardButton.disabled, false);

            const toggles = [];
            const safeTitle = { textContent: "" };
            const safeText = { textContent: "" };
            const safeEditBanner = {
                classList: {
                    toggle(name, enabled) {
                        toggles.push([name, enabled]);
                    },
                },
                querySelector(selector) {
                    if (selector === "strong") return safeTitle;
                    return selector === "span" ? safeText : null;
                },
            };
            const previewElements = {
                previewButton: { disabled: false },
                discardButton: { disabled: true },
                safeEditBanner,
            };
            view.applySavePreviewTriggerModel(previewElements, {
                savePreviewDisabled: true,
                saveDiscardDisabled: false,
                safeEditDirty: true,
                safeEditBlocked: false,
                safeEditTitle: "Bereit zum Speichern",
                safeEditText: "Ungespeicherte Änderungen: 2 Änderungen",
            });
            assert.strictEqual(previewElements.previewButton.disabled, true);
            assert.strictEqual(previewElements.discardButton.disabled, false);
            assert.deepStrictEqual(toggles, [["dirty", true], ["blocked", false]]);
            assert.strictEqual(safeTitle.textContent, "Bereit zum Speichern");
            assert.strictEqual(safeText.textContent, "Ungespeicherte Änderungen: 2 Änderungen");
            """
        )
    )


def test_frontend_world_status_view_uses_central_write_block_decision() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/world_status_view.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/world_status_view.js" });

            const view = context.window.MCBEWorldStatusView;
            const title = { textContent: "" };
            const text = { textContent: "" };
            const reviewButton = { disabled: true };
            const saveButton = { disabled: true };
            const previewButton = { disabled: true };
            const dirtyDiscardButton = { disabled: true };
            const safeEditDiscardButton = { disabled: true };
            let gate = {
                allowed: false,
                requires_unknown_server_confirmation: true,
                reason: "Serverstatus unbekannt.",
            };
            let writeBlockChecks = 0;
            const controller = view.createWorldStatusController({
                elements: {
                    dirtyBanner: { style: { display: "" } },
                    dirtyBannerText: { textContent: "" },
                    dirtyReviewButton: reviewButton,
                    dirtySaveButton: saveButton,
                    dirtyDiscardButton,
                    savePreviewButton: previewButton,
                    safeEditDiscardButton,
                    safeEditBanner: {
                        classList: { toggle() {} },
                        querySelector(selector) {
                            return selector === "strong" ? title : selector === "span" ? text : null;
                        },
                    },
                },
                getWorldPath: () => "C:/World",
                getCurrentPlayerKey: () => "local",
                getIsDirty: () => true,
                buildChangeSummary: () => ({ total: 1 }),
                effectiveWriteGate: () => gate,
                writeBlocked: () => {
                    writeBlockChecks += 1;
                    return gate.allowed === false && gate.requires_unknown_server_confirmation !== true;
                },
            });

            controller.updateDirtyBanner();
            assert.strictEqual(reviewButton.disabled, false);
            assert.strictEqual(saveButton.disabled, false);
            assert.strictEqual(previewButton.disabled, false);
            assert.strictEqual(dirtyDiscardButton.disabled, false);
            assert.strictEqual(safeEditDiscardButton.disabled, false);
            assert.strictEqual(title.textContent, "Bereit zum Speichern");
            assert.strictEqual(text.textContent, "Ungespeicherte Änderungen: 1 Änderung");

            gate = {
                allowed: false,
                requires_unknown_server_confirmation: false,
                reason: "Server online.",
            };
            controller.updateDirtyBanner();
            assert.strictEqual(reviewButton.disabled, true);
            assert.strictEqual(saveButton.disabled, true);
            assert.strictEqual(previewButton.disabled, true);
            assert.strictEqual(dirtyDiscardButton.disabled, false);
            assert.strictEqual(safeEditDiscardButton.disabled, false);
            assert.strictEqual(title.textContent, "Schreiben gesperrt");
            assert.strictEqual(text.textContent, "Ungespeicherte Änderungen: 1 Änderung · Server online.");
            assert.strictEqual(writeBlockChecks, 2);
            """
        )
    )
