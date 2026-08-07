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


def test_frontend_player_import_view_controls_model() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/player_import_view.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/player_import_view.js" });

            const view = context.window.MCBEPlayerImportView;
            const exportControl = view.exportFolderControl({ worldPath: "C:/World", dockerMode: false });
            assert.strictEqual(exportControl.disabled, false);
            assert.strictEqual(exportControl.title, "Exportordner der geladenen Welt im Dateimanager öffnen");

            const exportButton = { disabled: true, title: "" };
            view.applyExportFolderControl(exportButton, exportControl);
            assert.strictEqual(exportButton.disabled, false);
            assert.strictEqual(exportButton.title, "Exportordner der geladenen Welt im Dateimanager öffnen");

            const missingPath = view.importControlsModel({
                worldPath: "C:/World",
                importPath: "",
                importAsExported: true,
            });
            assert.strictEqual(missingPath.importDisabled, true);
            assert.strictEqual(missingPath.previewBlocksImport, false);
            assert.strictEqual(missingPath.previewRequired, false);

            const previewRequired = view.importControlsModel({
                worldPath: "C:/World",
                importPath: "C:/exports/player.zip",
                importAsExported: false,
                canOverwriteSelected: true,
                playerLabel: "Alex",
            });
            assert.strictEqual(previewRequired.importDisabled, true);
            assert.strictEqual(previewRequired.previewRequired, true);
            assert.ok(previewRequired.targetHint.includes("Import-Vorschau"));

            const overwriteSelected = view.importControlsModel({
                worldPath: "C:/World",
                importPath: "C:/exports/player.zip",
                importAsExported: false,
                canOverwriteSelected: true,
                playerLabel: "Alex",
                currentImportPreview: {
                    export_path: "C:/exports/player.zip",
                    world_path: "C:/World",
                    importable: true,
                    import_token: { version: 1 },
                },
            });
            assert.strictEqual(overwriteSelected.importDisabled, false);
            assert.ok(overwriteSelected.targetHint.includes("Alex"));
            assert.ok(overwriteSelected.targetHint.includes("direkt in der gewählten Welt"));

            const importedAsExported = view.importControlsModel({
                worldPath: "C:/World",
                importPath: "C:/exports/player.zip",
                importAsExported: true,
                currentImportPreview: {
                    export_path: "C:/exports/player.zip",
                    world_path: "C:/World",
                    importable: true,
                    import_token: { version: 1 },
                    player: { player_key: "exported-player" },
                },
            });
            assert.strictEqual(importedAsExported.importDisabled, false);
            assert.strictEqual(importedAsExported.exportedKeyRequired, false);
            assert.ok(importedAsExported.targetHint.includes("direkt in der gewählten Welt"));

            const missingExportedKey = view.importControlsModel({
                worldPath: "C:/World",
                importPath: "C:/exports/player.zip",
                importAsExported: true,
                currentImportPreview: {
                    export_path: "C:/exports/player.zip",
                    world_path: "C:/World",
                    importable: true,
                    import_token: { version: 1 },
                    player: { label: "Steve" },
                },
            });
            assert.strictEqual(missingExportedKey.importDisabled, true);
            assert.strictEqual(missingExportedKey.exportedKeyRequired, true);
            assert.ok(missingExportedKey.targetHint.includes("keinen exportierten Spieler-Key"));

            const staleWorldPreview = view.importControlsModel({
                worldPath: "C:/WorldB",
                importPath: "C:/exports/player.zip",
                importAsExported: false,
                canOverwriteSelected: true,
                playerLabel: "Alex",
                currentImportPreview: {
                    export_path: "C:/exports/player.zip",
                    world_path: "C:/WorldA",
                    importable: true,
                    import_token: { version: 1 },
                },
            });
            assert.strictEqual(staleWorldPreview.previewMatches, false);
            assert.strictEqual(staleWorldPreview.previewRequired, true);
            assert.strictEqual(staleWorldPreview.importDisabled, true);

            const blockedPreview = view.importControlsModel({
                worldPath: "C:/World",
                importPath: "C:/exports/player.zip",
                importAsExported: true,
                currentImportPreview: {
                    export_path: "C:/exports/player.zip",
                    world_path: "C:/World",
                    importable: false,
                },
            });
            assert.strictEqual(blockedPreview.previewMatches, true);
            assert.strictEqual(blockedPreview.previewBlocksImport, true);
            assert.strictEqual(blockedPreview.importDisabled, true);

            const writeBlocked = view.importControlsModel({
                worldPath: "C:/World",
                importPath: "C:/exports/player.zip",
                importAsExported: true,
                writeBlocked: true,
                currentImportPreview: {
                    export_path: "C:/exports/player.zip",
                    world_path: "C:/World",
                    importable: true,
                    import_token: { version: 1 },
                    player: { player_key: "exported-player" },
                },
            });
            assert.strictEqual(writeBlocked.importDisabled, true);
            """
        )
    )


def test_frontend_player_import_view_applies_controls_and_preview_dom_models() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/player_import_view.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/player_import_view.js" });

            const view = context.window.MCBEPlayerImportView;
            const controls = {
                importButton: { disabled: false },
                targetHint: { textContent: "" },
            };
            view.applyImportControlsModel(controls, {
                importDisabled: true,
                targetHint: "Zielspieler in der Kopie: Alex.",
            });
            assert.strictEqual(controls.importButton.disabled, true);
            assert.strictEqual(controls.targetHint.textContent, "Zielspieler in der Kopie: Alex.");

            const previewEl = { style: { display: "" }, className: "", innerHTML: "" };
            view.applyImportPreviewModel(previewEl, {
                className: "import-preview ok",
                html: "<strong>Import-Vorschau</strong>",
            });
            assert.strictEqual(previewEl.style.display, "block");
            assert.strictEqual(previewEl.className, "import-preview ok");
            assert.strictEqual(previewEl.innerHTML, "<strong>Import-Vorschau</strong>");

            view.clearImportPreviewElement(previewEl);
            assert.strictEqual(previewEl.style.display, "none");
            assert.strictEqual(previewEl.innerHTML, "");
            """
        )
    )
