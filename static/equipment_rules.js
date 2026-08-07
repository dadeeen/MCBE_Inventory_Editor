(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));

    // Spiegelt mcbe_editor/root_equipment.py: Welche Items sind in den
    // Ausrüstungsslots (100-103, -106) tatsächlich tragbar? Rüstung wird über
    // die Item-ID abgeleitet (Suffix + kuratierte Ausnahmen); die Schildhand
    // nutzt die kuratierte Bedrock-Positivliste (Minecraft Wiki "Off-hand").
    const HEAD_ITEM_NAMES = new Set([
        "carved_pumpkin",
        "mob_head",
        "player_head",
        "skull",
        "turtle_helmet",
        "turtle_shell",
    ]);
    const CHEST_ITEM_NAMES = new Set(["elytra"]);
    const OFFHAND_ITEM_NAMES = new Set([
        "arrow",
        "filled_map",
        "firework_rocket",
        "nautilus_shell",
        "shield",
        "sparkler",
        "tipped_arrow",
        "totem",
        "totem_of_undying",
    ]);
    const OFFHAND_SLOT = -106;
    const ARMOR_SLOTS = new Set([100, 101, 102, 103]);
    const EQUIPMENT_SLOT_LABELS = {
        103: "Helm",
        102: "Brustpanzer",
        101: "Hose",
        100: "Stiefel",
        [OFFHAND_SLOT]: "Schildhand",
    };
    const WEARABLE_COMPONENT_UI_SLOTS = {
        "slot.armor.head": 103,
        "slot.armor.chest": 102,
        "slot.armor.legs": 101,
        "slot.armor.feet": 100,
        "slot.weapon.offhand": OFFHAND_SLOT,
    };
    let itemComponents = {};

    function localItemName(name) {
        const normalized = String(name || "").trim().toLowerCase();
        const parts = normalized.split(":");
        return parts[parts.length - 1];
    }

    function officialWearableSlot(name) {
        const normalized = String(name || "").trim().toLowerCase();
        const wearable = itemComponents?.wearable;
        if (!wearable || !Object.prototype.hasOwnProperty.call(wearable, normalized)) {
            return { known: false, slot: null };
        }
        const componentSlot = String(wearable[normalized]?.slot || "").trim();
        return {
            known: true,
            slot: WEARABLE_COMPONENT_UI_SLOTS[componentSlot] ?? null,
        };
    }

    function inferredArmorSlot(name) {
        const official = officialWearableSlot(name);
        // Für Rüstung ist die offizielle Komponente abschließend: ein Item mit
        // bekanntem Nicht-Rüstungs-Slot (z. B. slot.armor.body) darf nicht über
        // ein irreführendes Namenssuffix doch noch einem Slot zugeordnet werden.
        if (official.known) return ARMOR_SLOTS.has(official.slot) ? official.slot : null;
        const local = localItemName(name);
        if (local.endsWith("_helmet") || local.endsWith("_head") || local.endsWith("_skull") || HEAD_ITEM_NAMES.has(local)) return 103;
        if (local.endsWith("_chestplate") || CHEST_ITEM_NAMES.has(local)) return 102;
        if (local.endsWith("_leggings")) return 101;
        if (local.endsWith("_boots")) return 100;
        return null;
    }

    function isEquipmentSlot(slotId, containerName = "inventory") {
        if (containerName === "ender_chest") return false;
        const slot = Number(slotId);
        return slot === OFFHAND_SLOT || ARMOR_SLOTS.has(slot);
    }

    function itemAllowedInEquipmentSlot(slotId, name) {
        const slot = Number(slotId);
        // Die Schildhand entscheidet bewusst anders als die Rüstungsslots:
        // minecraft:wearable ist in Bedrock nicht das Prädikat für die
        // Offhand-Erlaubnis (Totem, Pfeile oder Karten haben gar keine
        // Wearable-Komponente). Die offizielle Angabe ergänzt deshalb nur die
        // kuratierte Positivliste, statt sie zu ersetzen.
        if (slot === OFFHAND_SLOT) {
            return officialWearableSlot(name).slot === OFFHAND_SLOT || OFFHAND_ITEM_NAMES.has(localItemName(name));
        }
        if (ARMOR_SLOTS.has(slot)) return inferredArmorSlot(name) === slot;
        return true;
    }

    function equipmentSlotLabel(slotId) {
        const label = EQUIPMENT_SLOT_LABELS[Number(slotId)];
        return label ? t(label) : String(slotId);
    }

    function notWearableMessage(slotId, name) {
        const slot = Number(slotId);
        const base = t("'{name}' ist kein im {slot}-Slot tragbares Item.", { name: String(name || "?"), slot: equipmentSlotLabel(slot) });
        if (slot === OFFHAND_SLOT) {
            return `${base} ${t("Erlaubt sind Schild, Pfeile, Feuerwerksraketen, Totem, gefüllte Karten und Nautilusschale.")}`;
        }
        return base;
    }

    function setItemComponents(value) {
        itemComponents = value && typeof value === "object" ? value : {};
    }

    window.MCBEEquipmentRules = {
        equipmentSlotLabel,
        inferredArmorSlot,
        isEquipmentSlot,
        itemAllowedInEquipmentSlot,
        localItemName,
        notWearableMessage,
        setItemComponents,
    };
}());
