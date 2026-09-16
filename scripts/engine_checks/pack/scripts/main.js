import { ItemStack, ItemTypes, system, world } from "@minecraft/server";
import { config } from "./config.js";

let sequence = 0;
const totals = { items: 0, cases: 0, errors: 0 };
function emit(kind, fields = {}) {
    if (kind === "item") totals.items++;
    if (kind === "case") totals.cases++;
    if (kind === "error") totals.errors++;
    // BDS console encoding differs between platforms. Escape Unicode on the
    // wire so that names/lore reach the observer without a lossy console codec.
    const json = JSON.stringify({ run_id: config.run_id, phase: config.phase, seq: sequence++, kind, ...fields });
    console.warn("[MCBE_ENGINE] " + json.replace(/[\u007f-\uffff]/g, ch => "\\u" + ch.charCodeAt(0).toString(16).padStart(4, "0")));
}
function snapshot(item) {
    if (!item) return null;
    const durability = item.getComponent("minecraft:durability");
    const enchantable = item.getComponent("minecraft:enchantable");
    return {
        id: item.typeId, amount: item.amount, name: item.nameTag ?? "", lore: item.getLore(),
        damage: durability?.damage ?? 0,
        enchantments: (enchantable?.getEnchantments() ?? []).map(e => ({ id: e.type.id, level: e.level })).sort((a, b) => a.id.localeCompare(b.id)),
    };
}
function* catalog() {
    const ids = ItemTypes.getAll().map(type => type.id).sort();
    emit("registry", { ids });
    for (const id of [...new Set([...ids, ...config.expected_ids])].sort()) {
        try {
            const item = new ItemStack(id, 1);
            if (item.typeId !== id) throw new Error("Item resolved to a different type: " + item.typeId);
            emit("item", {
                id, max_amount: item.maxAmount,
                max_durability: item.getComponent("minecraft:durability")?.maxDurability ?? null,
                components: item.getComponents().map(component => component.typeId).sort(),
            });
        } catch (error) {
            emit("error", { id, message: String(error) });
        }
        yield;
    }
}
function* roundtrip() {
    const dimension = world.getDimension("overworld");
    const names = [...new Set(config.cases.map(test => test.carrier))];
    const carriers = new Map();
    if (config.phase === "seed") {
        for (let i = 0; i < names.length; i++) {
            const x = (i % 16) * 3, z = Math.floor(i / 16) * 3;
            dimension.getBlock({ x, y: 64, z }).setType("minecraft:bedrock");
            dimension.getBlock({ x, y: 65, z }).setType("minecraft:rail");
            const carrier = dimension.spawnEntity("minecraft:chest_minecart", { x: x + 0.5, y: 65.1, z: z + 0.5 });
            carrier.nameTag = names[i];
            const container = carrier.getComponent("minecraft:inventory").container;
            const control = new ItemStack("minecraft:stone", 1);
            control.nameTag = "MCBE untouched control";
            container.setItem(26, control);
            carriers.set(names[i], container);
            yield { wait: 1 };
        }
    } else {
        // Observation phases must never reconstruct items or overwrite stored data.
        for (let ticks = 0; ticks < 200; ticks++) {
            carriers.clear();
            for (const carrier of dimension.getEntities({ type: "minecraft:chest_minecart" })) {
                if (!names.includes(carrier.nameTag)) continue;
                if (carriers.has(carrier.nameTag)) throw new Error("Duplicate carrier " + carrier.nameTag);
                carriers.set(carrier.nameTag, carrier.getComponent("minecraft:inventory").container);
            }
            if (carriers.size === names.length) break;
            yield { wait: 1 };
        }
    }
    if (carriers.size !== names.length) throw new Error(`Missing carriers: ${carriers.size}/${names.length}`);
    for (const [name, container] of carriers) {
        const control = container.getItem(26);
        if (!control || control.typeId !== "minecraft:stone" || control.amount !== 1 || control.nameTag !== "MCBE untouched control") {
            throw new Error("Untouched control changed in " + name);
        }
    }
    for (const test of config.cases) {
        const container = carriers.get(test.carrier);
        if (config.phase === "seed" && test.mode !== "create") {
            const item = new ItemStack(test.id, test.amount);
            // Constructor clamping must be detected during reference creation too.
            if (item.amount !== test.amount) throw new Error("Reference amount was clamped: " + test.case_id);
            container.setItem(test.slot, item);
        }
        emit("case", { case_id: test.case_id, snapshot: snapshot(container.getItem(test.slot)) });
        yield;
    }
}
let started = false;
world.afterEvents.worldLoad.subscribe(() => {
    if (started) return;
    started = true;
    emit("begin");
    const task = config.phase === "catalog" ? catalog() : roundtrip();
    function advance() {
        try {
            for (let budget = 0; budget < 25; budget++) {
                const next = task.next();
                if (next.done) { emit("done", totals); return; }
                if (next.value?.wait) { system.runTimeout(advance, next.value.wait); return; }
            }
            system.run(advance);
        } catch (error) {
            emit("error", { message: String(error) });
            emit("done", totals);
        }
    }
    system.run(() => {
        if (config.phase === "catalog") { advance(); return; }
        const count = new Set(config.cases.map(test => test.carrier)).size;
        world.tickingAreaManager.createTickingArea("engine_probe", {
            dimension: world.getDimension("overworld"),
            from: { x: 0, y: 64, z: 0 }, to: { x: 47, y: 68, z: Math.floor((count - 1) / 16) * 3 },
        }).then(() => system.run(advance), error => {
            emit("error", { message: String(error) });
            emit("done", totals);
        });
    });
});
