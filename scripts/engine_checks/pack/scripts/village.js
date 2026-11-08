import { GameMode, ItemStack, world } from "@minecraft/server";

// This profile never creates villagers, trades, food pickups or a village.
// Names and seed-only player supplies make genuine gameplay observable.
const TYPES = ["minecraft:villager", "minecraft:villager_v2"];
const CARROT = "minecraft:carrot", BREAD = "minecraft:bread", EMERALD = "minecraft:emerald";

function inventory(entity) {
    const container = entity.getComponent("minecraft:inventory")?.container;
    if (!container) throw new Error("Missing native inventory");
    return container;
}

function count(entity, id) {
    const container = inventory(entity);
    let total = 0;
    for (let slot = 0; slot < container.size; slot++) {
        const item = container.getItem(slot);
        if (item?.typeId === id) total += item.amount;
    }
    return total;
}

function actorSnapshot(entity) {
    const health = entity.getComponent("minecraft:health"), container = inventory(entity);
    if (!health || container.size !== 8) throw new Error("Unsupported native villager shape");
    return {
        identity: entity.id, type: entity.typeId,
        current: health.currentValue, maximum: health.effectiveMax,
        variant: entity.getComponent("minecraft:variant")?.value ?? -1,
        items: Array.from({length: 8}, (_, slot) => {
            const item = container.getItem(slot);
            return item ? {name: item.typeId, count: item.amount} : null;
        }),
    };
}

function snapshots(actors) {
    return Object.fromEntries(Object.entries(actors).map(([role, actor]) => [role, actorSnapshot(actor)]));
}

function sameActorSnapshot(actual, expected, farming = false) {
    if (!expected || !["identity", "type", "current", "maximum"].every(key => actual[key] === expected[key]) ||
        !Array.isArray(expected.items) || expected.items.length !== 8) return false;
    if (farming) {
        const carrots = items => items.reduce((total, item) => total + (item?.name === CARROT ? item.count : 0), 0);
        return actual.variant === expected.variant && carrots(actual.items) === carrots(expected.items);
    }
    return actual.items.every((item, index) => {
            const previous = expected.items[index];
            return item === null ? previous === null : previous && item.name === previous.name && item.count === previous.count;
        });
}

function blockPosition(position) {
    return Object.fromEntries(["x", "y", "z"].map(key => [key, Math.floor(position[key])]));
}

function* loadVillageArea(dimension, plan) {
    let loaded = false, failure;
    world.tickingAreaManager.createTickingArea("village_probe", {
        dimension, from: {x: plan.center.x - 96, y: 64, z: plan.center.z - 96},
        to: {x: plan.center.x + 96, y: 80, z: plan.center.z + 96},
    }).then(() => { loaded = true; }, error => { failure = error; });
    for (let tick = 0; !loaded && !failure && tick < 400; tick++) yield {wait: 1};
    if (!loaded) throw new Error("Natural village chunks did not load: " + (failure ?? "timeout"));
}

function playerSnapshot(player) {
    return {emerald: count(player, EMERALD), bread: count(player, BREAD), carrot: count(player, CARROT)};
}

function selectItem(player, typeId) {
    const container = inventory(player);
    for (let slot = 0; slot < 9; slot++) {
        if (container.getItem(slot)?.typeId === typeId) { player.selectedSlotIndex = slot; return; }
    }
    throw new Error("Required client item is not in the hotbar: " + typeId);
}

function residents(dimension, plan) {
    return dimension.getEntities({location: plan.center, maxDistance: 180}).filter(entity => TYPES.includes(entity.typeId));
}

function namedResidents(dimension, plan) {
    const found = residents(dimension, plan), result = {};
    for (const [role, name] of Object.entries(plan.names)) {
        const matches = found.filter(entity => entity.nameTag === name);
        if (matches.length !== 1) throw new Error("Missing or duplicate natural resident: " + role);
        result[role] = matches[0];
    }
    return result;
}

function faceFarmer(player, farmer, plan) {
    // Anchor the observer to the known booth floor, not the actor's fractional
    // Y coordinate. Native actors can stand slightly below the integer surface.
    // Every candidate is inside the walls; there is no unchecked fallback.
    const pos = farmer.location, dimension = farmer.dimension;
    const booth = Object.values(plan.booths).find(center => pos.x >= center.x - 2 && pos.x < center.x + 3 &&
        pos.z >= center.z - 2 && pos.z < center.z + 3 && pos.y >= center.y - 0.1 && pos.y < center.y + 3);
    if (!booth) throw new Error("Natural farmer is outside its interaction booth");
    const candidates = [];
    for (let dx = -2; dx <= 2; dx++) for (let dz = -2; dz <= 2; dz++) {
        const block = {x: booth.x + dx, y: booth.y, z: booth.z + dz};
        const location = {x: block.x + 0.5, y: block.y + 0.1, z: block.z + 0.5};
        const distance = Math.hypot(location.x - pos.x, location.z - pos.z);
        const feet = dimension.getBlock(block), head = dimension.getBlock({...block, y: block.y + 1});
        const floor = dimension.getBlock({...block, y: block.y - 1});
        // isSolid is experimental and absent from the stable API. This
        // fixture has a known full-block stone floor, so verify its type.
        if (distance >= 1.25 && distance <= 3.5 && feet?.isAir && head?.isAir && floor?.typeId === "minecraft:stone") {
            candidates.push({location, distance});
        }
    }
    candidates.sort((a, b) => Math.abs(a.distance - 2) - Math.abs(b.distance - 2));
    if (!candidates.length) throw new Error("No safe player position inside the interaction booth");
    player.teleport(candidates[0].location, {dimension, facingLocation: {...pos, y: Math.max(booth.y, pos.y) + 1.1}});
}

function instruction(player, emit, stage, message, farmer) {
    player.sendMessage(message);
    emit("checkpoint", {stage, message, farmer: {...farmer.location}});
}

function* waitForResidents(dimension, plan) {
    for (let tick = 0; tick < 400; tick++) {
        try { return namedResidents(dimension, plan); } catch (_) { /* chunks are still loading */ }
        yield {wait: 1};
    }
    throw new Error("Natural residents did not load");
}

function* prepareBooths(dimension, plan, actors) {
    // Preserve the natural actors and their Vanilla definitions. Separate
    // interaction booths prevent harvesting/sharing from changing tested
    // supplies between editor writes and the next real client connection.
    // Verify the entire footprint is empty before placing any fixture block.
    for (const position of Object.values(plan.booths)) {
        for (let x = -3; x <= 3; x++) for (let z = -3; z <= 3; z++) for (let y = -1; y <= 3; y++) {
            if (!dimension.getBlock({x: position.x + x, y: position.y + y, z: position.z + z})?.isAir) {
                throw new Error("Natural village interaction booth footprint is not empty");
            }
        }
        yield;
    }
    for (const [role, position] of Object.entries(plan.booths)) {
        for (let x = -3; x <= 3; x++) {
            for (let z = -3; z <= 3; z++) for (let y = -1; y <= 3; y++) {
                if (y !== -1 && y !== 3 && Math.abs(x) !== 3 && Math.abs(z) !== 3) continue;
                dimension.getBlock({x: position.x + x, y: position.y + y, z: position.z + z})
                    .setType(y === -1 ? "minecraft:stone" : "minecraft:glass");
            }
            yield;
        }
        dimension.getBlock({x: position.x + 2, y: position.y, z: position.z + 2}).setType(plan.workstation);
        actors[role].teleport({x: position.x + 0.5, y: position.y, z: position.z + 0.5}, {dimension});
    }
}

function* settleProfessions(candidates) {
    let signature = "", stable = 0;
    for (let tick = 0; tick < 2400; tick++) {
        const variants = candidates.map(actor => actor.getComponent("minecraft:variant")?.value ?? -1);
        const current = variants.join(",");
        stable = current === signature ? stable + 1 : 0;
        signature = current;
        const farmer = candidates.find((_, index) => variants[index] === 1);
        if (farmer && variants.every(variant => variant > 0) && stable >= 100) {
            const others = candidates.filter(actor => actor !== farmer).sort((a, b) => a.id.localeCompare(b.id));
            return {farmer, injured: others[0], control: others[1]};
        }
        yield {wait: 1};
    }
    throw new Error("Native workstations did not establish a farmer and two settled adult controls: " + signature);
}

export function* villageRoundtrip(config, emit) {
    const plan = config.village_profile, dimension = world.getDimension("overworld");
    if (world.seed !== plan.seed) throw new Error("The generated world seed differs from the natural village plan");
    if (typeof dimension.isChunkLoaded !== "function") throw new Error("Stable native chunk-load observations unavailable");
    // Build the natural-actor fixture before inviting a human. Native job
    // assignment needs a nearby real player, even with loaded ticking areas.
    yield* loadVillageArea(dimension, plan);
    let actors, origin;
    if (config.phase === "seed") {
        dimension.runCommand("gamerule mobgriefing true");
        dimension.runCommand("gamerule dodaylightcycle false");
        dimension.runCommand("time set 6000");
        let natural;
        for (let tick = 0; tick < 400; tick++) {
            natural = residents(dimension, plan).filter(entity => !entity.getComponent("minecraft:is_baby") &&
                entity.getComponent("minecraft:variant")?.value !== 14);
            if (natural.length >= 3) break;
            yield {wait: 1};
        }
        if (natural.length < 3) throw new Error("Natural village lacks three eligible adults; no client interaction is ready");
        const selected = natural.sort((a, b) => a.id.localeCompare(b.id)).slice(0, 3);
        actors = Object.fromEntries(Object.keys(plan.names).map((role, index) => [role, selected[index]]));
        const landmarks = plan.landmarks.map(marker => ({position: marker.position, type: dimension.getBlock(marker.position)?.typeId}));
        if (landmarks.some((marker, index) => marker.type !== plan.landmarks[index].type)) throw new Error("Natural village landmarks are missing");
        origin = {
            seed: world.seed, center: plan.center, natural_residents: natural.length, landmarks,
            actors: Object.fromEntries(selected.map(actor => [actor.id, {
                identity: actor.id, type: actor.typeId, variant: actor.getComponent("minecraft:variant")?.value ?? -1,
                position: {...actor.location}, original_name: actor.nameTag,
            }])),
        };
        yield* prepareBooths(dimension, plan, actors);
    } else {
        actors = yield* waitForResidents(dimension, plan);
    }
    emit("checkpoint", {stage: "waiting_for_client"});
    let player;
    while (!player) {
        const players = world.getAllPlayers();
        if (players.length > 1) throw new Error("Village profile requires one real client");
        player = players[0];
        if (!player) yield {wait: 5};
    }
    emit("checkpoint", {stage: "client_connected"});
    player.setGameMode(GameMode.Creative);
    faceFarmer(player, actors.farmer, plan);
    if (config.phase === "seed") player.sendMessage("Dorfprüfung: Die Bewohner wählen ihre Berufe. Das kann bis zu zwei Minuten dauern. Bitte warten.");
    yield {wait: 100};
    if (config.phase === "seed") {
        actors = yield* settleProfessions(Object.values(actors));
        emit("case", {case_id: "origin", snapshot: {
            ...origin, actors: Object.fromEntries(Object.entries(actors).map(([role, actor]) => [role, origin.actors[actor.id]])),
        }});
        for (const [role, actor] of Object.entries(actors)) actor.nameTag = plan.names[role];
        actors.injured.getComponent("minecraft:health").setCurrentValue(6);
        const supplies = inventory(player);
        supplies.clearAll();
        supplies.setItem(0, new ItemStack(EMERALD, 64));
        supplies.setItem(1, new ItemStack(CARROT, 8));
    }
    const before = snapshots(actors), playerBefore = playerSnapshot(player);
    emit("case", {case_id: "before", snapshot: {actors: before, player: playerBefore}});
    if (config.phase !== "seed") {
        if (!config.village_expected) throw new Error("Missing offline village expectation");
        for (const role of Object.keys(plan.names)) {
            const expected = config.village_expected[role], actual = before[role];
            if (!sameActorSnapshot(actual, expected, role === "farmer")) {
                throw new Error("Persisted natural villager state did not survive: " + role);
            }
        }
    }
    const farmer = actors.farmer;
    if (before.farmer.variant !== 1) throw new Error("Selected natural farmer changed profession");
    if (playerBefore.emerald < 1 || playerBefore.carrot < 1) throw new Error("Saved client supplies are missing; reloads never replenish them");
    let interactions = 0, pickupPhase = false;
    const spawned = new Map(), attempted = new Map();
    const interact = event => { if (event.player.id === player.id && event.target.id === farmer.id) interactions++; };
    const spawn = event => {
        if (!pickupPhase || event.entity.typeId !== "minecraft:item") return;
        const entity = event.entity, item = entity.getComponent("minecraft:item")?.itemStack;
        if (item?.typeId !== CARROT || entity.dimension.id !== player.dimension.id) return;
        const distance = Math.hypot(...["x", "y", "z"].map(key => entity.location[key] - player.location[key]));
        if (distance <= 4) spawned.set(entity.id, {identity: entity.id, spawned: item.amount, player_distance: distance});
    };
    const pickup = event => {
        if (!pickupPhase || event.entity.id !== farmer.id) return;
        const item = event.item.getComponent("minecraft:item")?.itemStack;
        if (item?.typeId === CARROT) attempted.set(event.item.id, (attempted.get(event.item.id) ?? 0) + item.amount);
    };
    // BDS 1.26.61.1 does not fire entityItemPickupAfterEvent for villager
    // supplies. Bind the before-event's exact item entity to its observed
    // spawn near the client, then prove completion through both inventories
    // and the independent saved-NBT observer. Never manufacture a pickup.
    if (!world.afterEvents.entitySpawn || !world.beforeEvents.entityItemPickup) throw new Error("Stable native item/pickup observations unavailable");
    world.afterEvents.playerInteractWithEntity.subscribe(interact);
    world.afterEvents.entitySpawn.subscribe(spawn);
    world.beforeEvents.entityItemPickup.subscribe(pickup);
    try {
        faceFarmer(player, farmer, plan);
        player.setGameMode(GameMode.Survival);
        selectItem(player, EMERALD);
        instruction(player, emit, "trade_required", "Dorfprüfung: Beim MCBE-Farmer einmal Brot mit Smaragden kaufen, dann das Handelsfenster schließen.", farmer);
        let traded;
        while (!traded) {
            if (world.getAllPlayers().length !== 1) throw new Error("Client left before completing the village interaction");
            const current = playerSnapshot(player);
            // While the trading GUI is open its input slots can hold the whole
            // emerald stack outside the player inventory. Wait for the exact
            // completed exchange, including returned change, before observing.
            if (interactions > 0 && current.emerald === playerBefore.emerald - plan.trade.emerald &&
                current.bread === playerBefore.bread + plan.trade.bread && current.carrot === playerBefore.carrot) traded = current;
            else yield {wait: 5};
        }
        emit("case", {case_id: "trade", snapshot: {interactions, before: playerBefore, after: traded}});
        const carrotBefore = count(farmer, CARROT), playerCarrotBefore = count(player, CARROT);
        const initialCarrots = before.farmer.items.reduce((sum, item) => sum + (item?.name === CARROT ? item.count : 0), 0);
        if (carrotBefore !== initialCarrots) throw new Error("Farmer supplies changed before the controlled client drop");
        faceFarmer(player, farmer, plan);
        selectItem(player, CARROT);
        pickupPhase = true;
        instruction(player, emit, "pickup_required", "Dorfprüfung: Handelsfenster schließen und eine Karotte mit Q vor dem MCBE-Farmer fallen lassen.", farmer);
        let sources, pickedUp, progress = "";
        while (true) {
            if (world.getAllPlayers().length !== 1) throw new Error("Client left before the native food pickup");
            sources = [...spawned.values()].map(item => ({...item, attempted: attempted.get(item.identity) ?? 0}));
            pickedUp = count(farmer, CARROT) - carrotBefore;
            const total = sources.reduce((sum, item) => sum + item.spawned, 0);
            const current = JSON.stringify({spawned: total, attempted: [...attempted.values()].reduce((sum, amount) => sum + amount, 0),
                farmer_gain: pickedUp, client_loss: playerCarrotBefore - count(player, CARROT)});
            if (current !== progress) { emit("checkpoint", {stage: "pickup_progress", ...JSON.parse(current)}); progress = current; }
            if (total > 0 && pickedUp === total && playerCarrotBefore - count(player, CARROT) === total &&
                attempted.size === sources.length && sources.every(item => item.attempted === item.spawned)) break;
            yield {wait: 5};
        }
        emit("case", {case_id: "pickup", snapshot: {
            sources, picked_up: pickedUp, farmer_before: carrotBefore, farmer_after: count(farmer, CARROT),
            player_before: playerCarrotBefore, player_after: count(player, CARROT),
        }});
    } finally {
        world.afterEvents.playerInteractWithEntity.unsubscribe(interact);
        world.afterEvents.entitySpawn.unsubscribe(spawn);
        world.beforeEvents.entityItemPickup.unsubscribe(pickup);
    }
    const after = snapshots(actors);
    for (const role of ["injured", "control"]) {
        if (!sameActorSnapshot(after[role], before[role])) throw new Error("Untouched natural resident changed during gameplay: " + role);
    }
    emit("case", {case_id: "after", snapshot: {actors: after, player: playerSnapshot(player)}});
    const farmerPosition = {...farmer.location};
    const chunkChecks = [
        ...Object.entries(actors).map(([role, actor]) => ({role, position: blockPosition(actor.location)})),
        ...plan.landmarks.map((marker, index) => ({role: "landmark_" + index, position: marker.position})),
    ].map(probe => ({...probe, before: dimension.isChunkLoaded(probe.position)}));
    if (chunkChecks.some(probe => probe.before !== true)) throw new Error("Village actor or landmark chunk was not initially loaded");
    instruction(player, emit, "chunk_reload", "Dorfprüfung: Bewohner speichern und Chunks neu laden. Bitte warten.", farmer);
    player.setGameMode(GameMode.Creative);
    world.tickingAreaManager.removeTickingArea("village_probe");
    player.teleport({x: plan.center.x + 2048, y: 120, z: plan.center.z + 2048}, {dimension});
    let unloaded = false;
    for (let tick = 0; tick < 600; tick++) {
        for (const probe of chunkChecks) probe.away = dimension.isChunkLoaded(probe.position);
        if (chunkChecks.every(probe => probe.away === false)) { unloaded = true; break; }
        yield {wait: 1};
    }
    if (!unloaded) throw new Error("Village chunks did not unload; no chunk-reload evidence");
    player.teleport({...farmerPosition, y: farmerPosition.y + 8}, {dimension});
    yield* loadVillageArea(dimension, plan);
    let returned = false;
    for (let tick = 0; tick < 400; tick++) {
        for (const probe of chunkChecks) probe.returned = dimension.isChunkLoaded(probe.position);
        if (chunkChecks.every(probe => probe.returned === true)) { returned = true; break; }
        yield {wait: 1};
    }
    if (!returned) throw new Error("Village actor and landmark chunks did not reload");
    actors = yield* waitForResidents(dimension, plan);
    const reloaded = snapshots(actors);
    for (const role of Object.keys(plan.names)) {
        if (!sameActorSnapshot(reloaded[role], after[role], role === "farmer")) throw new Error("Natural resident state changed across chunk reload: " + role);
    }
    emit("case", {case_id: "chunk_reload", snapshot: {unloaded: true, chunks: chunkChecks, actors: reloaded}});
    faceFarmer(player, actors.farmer, plan);
    player.setGameMode(GameMode.Survival);
    world.tickingAreaManager.removeTickingArea("village_probe");
    yield {wait: 20};
}
