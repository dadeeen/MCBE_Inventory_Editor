import { ItemStack, world } from "@minecraft/server";
import { referenceItem, snapshot } from "./items.js";

export function* clientRoundtrip(config, emit) {
    emit("checkpoint", { stage: "waiting_for_client" });
    let player;
    while (!player) {
        const players = world.getAllPlayers();
        if (players.length > 1) throw new Error("Client profile requires exactly one connected player");
        player = players[0];
        if (!player) yield { wait: 5 };
    }
    yield { wait: 20 };
    const containers = {
        Inventory: player.getComponent("minecraft:inventory")?.container,
        EnderChestInventory: player.getComponent("minecraft:ender_inventory")?.container,
    };
    if (containers.Inventory?.size !== 36 || containers.EnderChestInventory?.size !== 27) {
        throw new Error("Client inventory/Ender Chest API unavailable or unexpected size");
    }
    if (config.phase === "seed") {
        for (const [field, container] of Object.entries(containers)) {
            container.clearAll();
            const control = new ItemStack("minecraft:stone", 1);
            control.nameTag = config.client_control_name;
            container.setItem(config.client_control_slots[field], control);
        }
        for (const test of config.cases) {
            if (test.mode === "create") continue;
            const [field, slot] = config.client_locations[test.case_id];
            containers[field].setItem(slot, referenceItem(test, true));
        }
    }
    // Reload phases observe only. The same account must return with saved items.
    for (const [field, container] of Object.entries(containers)) {
        const expected = new Set([config.client_control_slots[field]]);
        for (const test of config.cases) {
            const [location, slot] = config.client_locations[test.case_id];
            if (location === field && (config.phase !== "seed" || test.mode !== "create")) expected.add(slot);
        }
        for (let slot = 0; slot < container.size; slot++) {
            if (!!container.getItem(slot) !== expected.has(slot)) throw new Error("Client inventory has missing or extra items");
        }
        const control = snapshot(container.getItem(config.client_control_slots[field]));
        if (control.id !== "minecraft:stone" || control.amount !== 1 || control.name !== config.client_control_name ||
            control.lore.length || control.damage || control.enchantments.length) throw new Error("Client control changed");
    }
    for (const test of config.cases) {
        const [field, slot] = config.client_locations[test.case_id];
        emit("case", { case_id: test.case_id, snapshot: snapshot(containers[field].getItem(slot), test) });
        yield;
    }
    yield { wait: 20 };
}
