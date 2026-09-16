import { EnchantmentTypes, ItemStack, Potions } from "@minecraft/server";

export function snapshot(item, test = {}) {
    if (!item) return null;
    const durability = item.getComponent("minecraft:durability");
    const enchantable = item.getComponent("minecraft:enchantable");
    const result = {
        id: item.typeId, amount: item.amount, name: item.nameTag ?? "", lore: item.getLore(),
        damage: durability?.damage ?? 0,
        enchantments: (enchantable?.getEnchantments() ?? []).map(e => ({ id: e.type.id, level: e.level })).sort((a, b) => a.id.localeCompare(b.id)),
    };
    if (test.potion) {
        const potion = item.getComponent("minecraft:potion");
        result.potion = potion ? { effect: potion.potionEffectType.id, delivery: potion.potionDeliveryType.id } : null;
    }
    return result;
}

export function referenceItem(test, seed = false) {
    const item = test.potion ? Potions.resolve(test.potion.effect, test.potion.delivery) : new ItemStack(test.id, test.amount);
    if (item.typeId !== test.id || item.amount !== test.amount) throw new Error("Reference identity/count changed: " + test.case_id);
    if (!seed || test.seeded_metadata) {
        for (const value of test.enchantments ?? []) {
            item.getComponent("minecraft:enchantable").addEnchantment({ type: EnchantmentTypes.get(value.id), level: value.level });
        }
        if (test.durable) item.getComponent("minecraft:durability").damage = test.damage;
    }
    if (!seed) {
        item.nameTag = test.name;
        item.setLore(test.lore);
    }
    return item;
}
