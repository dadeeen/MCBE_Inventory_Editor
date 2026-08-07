from __future__ import annotations

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


def test_player_load_warning_guides_users_to_the_player_analysis() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {} };
            vm.runInNewContext(fs.readFileSync("static/analysis_logic.js", "utf8"), context);
            const logic = context.window.MCBEAnalysisLogic.createAnalysisLogic({
                appConfig: {},
                currentPlayerLabel: () => "Alex",
                firstEmptyWritableSlot: () => null,
                getCurrentCompatibility: () => ({ player: { warnings: ["Unknown data"] }, world: {} }),
                getEnderChestInventory: () => ({}),
                getHasEnderChest: () => false,
                getHiddenUnknownSlots: () => ({}),
                getInventory: () => ({}),
                getPlayers: () => [],
                getProtectedNbt: () => ({}),
                getProtectedKnownSlots: () => ({}),
                getSelectedWorld: () => null,
                getWorldName: () => "World",
                getWorldPath: () => "/world",
                inventorySlotCount: 36,
                enderChestSlotCount: 27,
                isKnownItemId: () => true,
                itemIsVisiblePresent: () => false,
                maxDamage: () => ({}),
                protectedAbilityFields: () => ({}),
                protectedStatFields: () => ({}),
                getCreateRequiresConfirmation: () => ({}),
            });

            const message = logic.playerLoadStatusMessage();
            assert.ok(message.includes("Alex"));
            assert.ok(message.includes("Analyse"));
            assert.ok(!message.includes("Werkzeuge"));
            """
        )
    )


def test_player_analysis_combines_and_renders_informational_notes_safely() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const context = { window: {} };
            vm.runInNewContext(fs.readFileSync("static/analysis_logic.js", "utf8"), context);
            vm.runInNewContext(fs.readFileSync("static/world_analysis_view.js", "utf8"), context);

            const compatibility = {
                player: { notes: ["Player <metadata>"] },
                world: { notes: ["World metadata"] },
            };
            const logic = context.window.MCBEAnalysisLogic.createAnalysisLogic({
                appConfig: {}, currentPlayerLabel: () => "Alex", firstEmptyWritableSlot: () => null,
                getCurrentCompatibility: () => compatibility, getEnderChestInventory: () => ({}),
                getHasEnderChest: () => false, getHiddenUnknownSlots: () => ({}), getInventory: () => ({}),
                getPlayers: () => [], getProtectedNbt: () => ({}), getProtectedKnownSlots: () => ({}),
                getSelectedWorld: () => null, getWorldName: () => "World", getWorldPath: () => "/world",
                inventorySlotCount: 36, enderChestSlotCount: 27, isKnownItemId: () => true,
                itemIsVisiblePresent: () => false, maxDamage: () => ({}), protectedAbilityFields: () => ({}),
                protectedStatFields: () => ({}), getCreateRequiresConfirmation: () => ({}),
            });
            const notes = logic.currentCompatibilityNotes();
            assert.deepStrictEqual(Array.from(notes), ["Player <metadata>", "World metadata"]);

            const markup = context.window.MCBEWorldAnalysisView.worldAnalysisHtml({
                player: "Alex",
                players_total: 1,
                players_editable: 1,
                players_export_only: 0,
                inventory: {}, ender: {}, hidden: {},
                compat_notes: notes,
            });
            assert.ok(markup.includes("Player &lt;metadata&gt;"));
            assert.ok(markup.includes("World metadata"));
            assert.ok(!markup.includes("Player <metadata>"));
            """
        )
    )


def test_world_analysis_module_loads_before_the_main_app() -> None:
    html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    assert html.index("world_analysis_view.js") < html.index("app.js")


def test_unknown_dimension_option_is_a_state_and_not_a_choice() -> None:
    """The empty option only reports a missing or opaque DimensionId tag.

    ``disabled`` keeps it out of the dropdown list while the code can still select
    it programmatically. ``selected`` is required alongside it: without an explicit
    selection the browser preselects the first enabled option, which would claim
    "Oberwelt" for a world whose tag is absent.
    """

    html = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
    select_start = html.index('id="statDimensionId"')
    option_start = html.index('<option value=""', select_start)
    option = html[option_start : html.index(">", option_start) + 1]

    assert "disabled" in option, option
    assert "selected" in option, option
