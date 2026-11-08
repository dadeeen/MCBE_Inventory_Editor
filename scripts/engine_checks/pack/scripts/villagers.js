import { ItemStack, world } from "@minecraft/server";

function snapshot(entity) {
    const health = entity.getComponent("minecraft:health");
    const container = entity.getComponent("minecraft:inventory")?.container;
    if (!health || !container || container.size !== 8) throw new Error("Missing native villager health/eight-slot inventory");
    return {
        type: entity.typeId, name: entity.nameTag, current: health.currentValue, maximum: health.effectiveMax,
        items: Array.from({length: 8}, (_, slot) => {
            const item = container.getItem(slot);
            return item ? {name: item.typeId, count: item.amount} : null;
        }),
    };
}

export function* villagerRoundtrip(config, emit) {
    const dimension = world.getDimension("overworld");
    if (config.phase === "seed") {
        dimension.runCommand("gamerule mobgriefing false");
        dimension.runCommand("gamerule domobspawning false");
        dimension.runCommand("gamerule dodaylightcycle false");
        dimension.runCommand("time set day");
        for (let index = 0; index < config.cases.length; index++) {
            const test = config.cases[index], x = (index % 5) * 8, z = Math.floor(index / 5) * 8;
            // Separate cells avoid supply sharing and job/bed interactions.
            for (let dx = 0; dx < 5; dx++) for (let dz = 0; dz < 5; dz++) {
                dimension.getBlock({x: x + dx, y: 80, z: z + dz}).setType("minecraft:bedrock");
                for (let y = 81; y <= 84; y++) {
                    dimension.getBlock({x: x + dx, y, z: z + dz}).setType(
                        dx === 0 || dx === 4 || dz === 0 || dz === 4 || y === 84 ? "minecraft:glass" : "minecraft:air");
                }
            }
            const location = {x: x + 2.5, y: 81, z: z + 2.5};
            dimension.spawnEntity("minecraft:villager", location);
            yield {wait: 5};
            // Native conversion can discard tags. Only during seeding, locate
            // the sole villager in this isolated cell and tag the final actor.
            const matches = dimension.getEntities({location, maxDistance: 3}).filter(entity =>
                ["minecraft:villager", "minecraft:villager_v2"].includes(entity.typeId));
            if (matches.length !== 1) throw new Error("Native villager conversion lost identity " + test.name);
            const entity = matches[0], health = entity.getComponent("minecraft:health");
            entity.addTag(test.name);
            if (test.seed.name) entity.nameTag = test.seed.name;
            if (test.seed.current !== 20) health.setCurrentValue(test.seed.current);
            const container = entity.getComponent("minecraft:inventory").container;
            for (let slot = 0; slot < 8; slot++) {
                const item = test.seed.items[slot];
                if (item) container.setItem(slot, new ItemStack(item.name, item.count));
            }
        }
    }
    // Warmups/reloads only observe: never seed or repair persisted values here.
    let found;
    for (let tick = 0; tick < 200; tick++) {
        found = dimension.getEntities().filter(entity => config.cases.some(test => entity.hasTag(test.name)));
        if (found.length === config.cases.length) break;
        yield {wait: 1};
    }
    if (found.length !== config.cases.length) throw new Error("Missing or extra tagged villagers");
    for (const test of config.cases) {
        const matches = found.filter(entity => entity.hasTag(test.name));
        if (matches.length !== 1) throw new Error("Duplicate villager " + test.name);
        emit("case", {case_id: test.case_id, snapshot: snapshot(matches[0])});
        yield;
    }
}
