import { EnchantmentTypes, ItemStack, Potions } from "@minecraft/server";

export function* measureMatrix(config, emit) {
    const types = EnchantmentTypes.getAll().sort((a, b) => a.id.localeCompare(b.id));
    const effects = Potions.getAllEffectTypes().map(type => type.id).sort();
    const deliveries = Potions.getAllDeliveryTypes().map(type => type.id).sort();
    emit("matrix_registry", { enchantments: Object.fromEntries(types.map(type => [type.id, type.maxLevel])), effects, deliveries });
    for (const id of config.expected_ids) {
        const item = new ItemStack(id);
        const component = item.getComponent("minecraft:enchantable");
        const allowed = component ? types.filter(type => component.canAddEnchantment({ type, level: type.maxLevel })) : [];
        const pairFits = (first, second) => {
            const pairStack = new ItemStack(id);
            const target = pairStack.getComponent("minecraft:enchantable");
            target.addEnchantment({ type: first, level: first.maxLevel });
            try {
                const fits = target.canAddEnchantment({ type: second, level: second.maxLevel });
                if (fits) {
                    target.addEnchantment({ type: second, level: second.maxLevel });
                    if (target.getEnchantments().length !== 2) throw new Error("Enchantment pair was silently changed");
                }
                return { accepted: fits };
            } catch (error) {
                // This BDS build also uses the documented bounds exception for
                // conflicting pairs. Both individual types use valid max levels.
                if (["EnchantmentLevelOutOfBoundsError", "EnchantmentTypeNotCompatibleError"].includes(error.name)) {
                    return { accepted: false, error: error.name };
                }
                throw new Error(`${id}: ${first.id} + ${second.id}: ${String(error)}`);
            }
        };
        const pairs = [];
        for (let a = 0; a < allowed.length; a++) {
            for (let b = a + 1; b < allowed.length; b++) {
                const forward = pairFits(allowed[a], allowed[b]), reverse = pairFits(allowed[b], allowed[a]);
                pairs.push({ left: allowed[a].id, right: allowed[b].id, forward: forward.accepted, reverse: reverse.accepted,
                    forward_error: forward.error ?? null, reverse_error: reverse.error ?? null });
                yield;
            }
        }
        emit("enchantability", { id, allowed: allowed.map(type => type.id), pairs });
        yield;
    }
    for (const effect of effects) for (const delivery of deliveries) {
        const item = Potions.resolve(effect, delivery);
        const component = item.getComponent("minecraft:potion");
        if (!component || component.potionEffectType.id !== effect || component.potionDeliveryType.id !== delivery) {
            throw new Error("Potion constructor changed its requested variant");
        }
        emit("potion", { effect, delivery, id: item.typeId });
        yield;
    }
}
