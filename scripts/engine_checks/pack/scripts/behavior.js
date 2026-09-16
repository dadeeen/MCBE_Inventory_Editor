import { ItemStack } from "@minecraft/server";
import { referenceItem, snapshot } from "./items.js";

function assertEqual(actual, expected, label) {
    if (JSON.stringify(actual) !== JSON.stringify(expected)) throw new Error(label + ": " + JSON.stringify({ actual, expected }));
}

function contents(container, test = {}) {
    const result = [];
    for (let slot = 0; slot < container.size; slot++) {
        const item = container.getItem(slot);
        if (item) result.push(snapshot(item, test));
    }
    return result;
}

export function* runBehaviors(config, dimension, carriers, emit) {
    const cases = new Map(config.cases.map(test => [test.case_id, test]));
    const itemFor = test => carriers.get(test.carrier).getItem(test.slot);
    const scratchBlock = dimension.getBlock({ x: 47, y: 70, z: 0 });
    scratchBlock.setType("minecraft:chest");
    const scratch = scratchBlock.getComponent("minecraft:inventory").container;
    function merge(left, right, leftAmount, rightAmount, full = false) {
        scratch.clearAll();
        const a = left.clone(), b = right.clone();
        a.amount = leftAmount; b.amount = rightAmount;
        if (a.amount !== leftAmount || b.amount !== rightAmount) throw new Error("Merge input was clamped");
        let fillerAmount = 0;
        if (full) {
            const filler = new ItemStack("minecraft:barrier", 64);
            filler.nameTag = "MCBE merge filler " + config.run_id;
            for (let slot = 1; slot < scratch.size; slot++) { scratch.setItem(slot, filler); fillerAmount += filler.amount; }
        }
        scratch.setItem(0, a);
        const remainder = scratch.addItem(b);
        const slots = contents(scratch);
        const total = slots.reduce((sum, item) => sum + item.amount, remainder?.amount ?? 0);
        if (total !== leftAmount + rightAmount + fillerAmount) throw new Error("Merge lost or duplicated items");
        return { slots, remainder: snapshot(remainder) };
    }
    for (const test of config.merges) {
        const leftCase = cases.get(test.left), rightCase = cases.get(test.right);
        const left = itemFor(leftCase), right = itemFor(rightCase);
        const leftReference = referenceItem(leftCase), rightReference = referenceItem(rightCase);
        assertEqual([left.isStackableWith(right), right.isStackableWith(left)],
            [leftReference.isStackableWith(rightReference), rightReference.isStackableWith(leftReference)], "Stack equivalence " + test.id);
        const boundaries = leftReference.isStackableWith(rightReference) ? [[1, 1], [left.maxAmount - 1, 1], [left.maxAmount, 1]] : [[1, 1]];
        for (const [a, b] of boundaries) assertEqual(merge(left, right, a, b), merge(leftReference, rightReference, a, b), "Container merge " + test.id);
        assertEqual(merge(left, right, left.maxAmount, 1, true), merge(leftReference, rightReference, leftReference.maxAmount, 1, true),
            "Full container remainder " + test.id);
        assertEqual(snapshot(itemFor(leftCase), leftCase), snapshot(left, leftCase), "Merge changed source item");
        assertEqual(snapshot(itemFor(rightCase), rightCase), snapshot(right, rightCase), "Merge changed second source item");
        emit("behavior", { id: test.id, passed: true, boundary_checks: boundaries.length + 1, stackable: left.isStackableWith(right) });
        yield;
    }
    scratch.clearAll();
    for (const test of config.gameplay) {
        const sourceCase = cases.get(test.source);
        const original = itemFor(sourceCase);
        const hopperBlock = dimension.getBlock({ x: 44, y: 70, z: 0 });
        const chestBlock = dimension.getBlock({ x: 44, y: 71, z: 0 });
        hopperBlock.setType("minecraft:hopper");
        const hopper = hopperBlock.getComponent("minecraft:inventory").container;
        hopper.clearAll();
        let source, dropped;
        if (test.action === "hopper") {
            chestBlock.setType("minecraft:chest");
            source = chestBlock.getComponent("minecraft:inventory").container;
            source.clearAll(); source.setItem(0, original.clone());
        } else {
            chestBlock.setType("minecraft:air");
            dropped = dimension.spawnItem(original.clone(), { x: 44.5, y: 71.1, z: 0.5 });
            // Control the fall geometry: spawnItem can launch the item sideways
            // past the hopper. Collection and item metadata still use the engine.
            dropped.clearVelocity();
            assertEqual(snapshot(dropped.getComponent("minecraft:item").itemStack, sourceCase), snapshot(original, sourceCase), "Dropped item");
        }
        for (let ticks = 0; ticks < 160 && hopper.emptySlotsCount === hopper.size; ticks++) yield { wait: 1 };
        assertEqual(contents(hopper, sourceCase), [snapshot(original, sourceCase)], "Hopper changed item " + test.id);
        if (source && source.emptySlotsCount !== source.size) throw new Error("Hopper duplicated source item");
        if (dropped && dimension.getEntities({ type: "minecraft:item", location: { x: 44.5, y: 71.1, z: 0.5 }, maxDistance: 3 }).some(entity => entity.id === dropped.id)) {
            throw new Error("Dropped source item remained after collection");
        }
        hopper.clearAll();
        emit("behavior", { id: test.id, passed: true });
        yield;
    }
}
