from tests.node_runner import run_node


def test_bulk_actions_use_the_numeric_value_of_number_inputs() -> None:
    run_node(r"""
        const assert = require("node:assert/strict");
        const fs = require("fs");
        const vm = require("vm");
        const context = { window: {} };
        vm.runInNewContext(fs.readFileSync("static/bulk_edit_logic.js", "utf8"), context);
        const logic = context.window.MCBEBulkEditLogic;

        for (const [value, expected] of [["1e1", 10], ["2E1", 20], [".9e1", 9], ["12.9", 12]]) {
            const fill = logic.bulkFillPlan({ rawName: "minecraft:stone", rawCount: value,
                rawDamage: "1e2", maxDamage: 1000, writableCount: 2, selectedCount: 2 });
            assert.equal(fill.item.count, expected);
            assert.equal(fill.item.damage, 100);
            const setCount = logic.bulkSetCountPlan({ targetCount: 2, rawDesired: value });
            assert.equal(setCount.desired, expected);
        }
        for (const rawDesired of ["", "1e", "7junk", "Infinity", "-1e2"]) {
            assert.equal(logic.bulkSetCountPlan({ targetCount: 2, rawDesired }).ok, false);
        }
        assert.equal(logic.bulkFillPlan({ rawName: "minecraft:stone", rawCount: "1e3",
            maxStack: 64, writableCount: 1 }).item.count, 64);
    """)


def test_effect_number_inputs_preserve_notation_and_original_tick_precision() -> None:
    run_node(r"""
        const assert = require("node:assert/strict");
        const fs = require("fs");
        const vm = require("vm");
        const context = { window: {} };
        vm.runInNewContext(fs.readFileSync("static/effects_view.js", "utf8"), context);
        const view = context.window.MCBEEffectsView;

        const patch = view.effectPatchFromRowValues({ levelValue: "1e2", durationSecondsValue: "1e5" });
        assert.equal(patch.amplifier, 99);
        assert.equal(patch.duration, 2_000_000);
        const preserved = view.effectPatchFromRowValues({ levelValue: "2", durationSecondsValue: "3e1" },
            { amplifier: 0, duration: 601 });
        assert.equal(preserved.amplifier, 1);
        assert.equal(preserved.duration, 601);
        const invalid = view.effectPatchFromRowValues({ levelValue: "Infinity", durationSecondsValue: "1e" });
        assert.equal(invalid.amplifier, 0);
        assert.equal(invalid.duration, 0);
    """)


def test_mount_search_radius_uses_the_numeric_value_of_number_inputs() -> None:
    run_node(r"""
        const assert = require("node:assert/strict");
        const fs = require("fs");
        const vm = require("vm");
        const context = { window: {} };
        vm.runInNewContext(fs.readFileSync("static/mount_controller.js", "utf8"), context);
        const input = { value: "1e1", addEventListener: () => {} };
        const requests = [];
        const controller = context.window.MCBEMountController.createMountController({
            doc: { getElementById: id => id === "mountPlacementRadiusInput" ? input : null,
                querySelectorAll: () => [] },
            getWorldPath: () => "world", getCurrentPlayerKey: () => "player",
            getCurrentPlayer: () => ({ player_key: "player" }),
            apiClient: { previewMountOrThrow: async request => {
                requests.push(request);
                return { can_create: true, candidate_positions: [] };
            } },
            render: { applyMountPanelState: () => {} },
        });
        (async () => {
            for (const [value, expected] of [["1e1", 10], ["1.2e1", 12], ["2e1", 16], ["1", 2], ["10", 10]]) {
                input.value = value;
                await controller.loadPreview();
                assert.equal(requests.at(-1).placementRadius, expected);
            }
            input.value = "";
            await controller.loadPreview();
            assert.equal(requests.at(-1).placementRadius, 10, "empty draft retains the previous radius");
        })().catch(error => { console.error(error); process.exit(1); });
    """)
