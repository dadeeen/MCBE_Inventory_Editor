(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));

    // Bedrock liefert Leder-Rüstung als Graustufen-Basistextur; das Spiel
    // multipliziert sie zur Laufzeit mit der Lederfarbe (ungefärbt #A06540,
    // vgl. Minecraft Wiki "Leather Tunic"). Ohne Tint sähen die Icons wie
    // Metall aus. Angewendet wird der Tint clientseitig per Canvas-Multiply.
    const ICON_TINTS = {
        "minecraft:leather_helmet": "#a06540",
        "minecraft:leather_chestplate": "#a06540",
        "minecraft:leather_leggings": "#a06540",
        "minecraft:leather_boots": "#a06540",
        "minecraft:leather_horse_armor": "#a06540",
        "minecraft:horsearmorleather": "#a06540",
    };

    const EMOJI_MAP = {
        sword: "🗡️",
        pickaxe: "⛏️",
        axe: "🪓",
        shovel: "🥄",
        hoe: "🚜",
        bow: "🏹",
        crossbow: "🏹",
        trident: "🔱",
        arrow: "💘",
        helmet: "🪖",
        chestplate: "👕",
        leggings: "👖",
        boots: "🥾",
        elytra: "🦋",
        shield: "🛡️",
        // Banner haben in Bedrock kein Item-Sprite (entity-gerendert):
        // bewusstes Emoji-Fallback statt leerer Iconfläche.
        banner: "🚩",
        skull: "💀",
        head: "💀",
        totem: "🗿",
        apple: "🍎",
        bread: "🍞",
        beef: "🥩",
        chicken: "🍗",
        porkchop: "🥓",
        pearl: "🔮",
        eye: "👁️",
        experience: "🧪",
        bucket: "🪣",
        block: "📦",
        diamond: "💎",
        ingot: "🪙",
        coal: "🪨",
        redstone: "🔴",
        lapis: "🔵",
        emerald: "💚",
        dirt: "🟫",
        stone: "🪨",
        obsidian: "🖤",
        bedrock: "🧱",
        sand: "⏳",
        glass: "🥛",
        tnt: "🧨",
        sponge: "🧽",
        chest: "📦",
        furnace: "🔥",
        table: "🪵",
        anvil: "🔨",
        book: "📕",
        star: "⭐",
        saddle: "🏇",
        tag: "🏷️",
        lantern: "🏮",
        glowstone: "✨",
        flower: "🌸",
        tulip: "🌷",
        dandelion: "🌼",
        poppy: "🌺",
    };

    const WOOL_COLOR_BY_DAMAGE = [
        "white", "orange", "magenta", "light_blue", "yellow", "lime", "pink", "gray",
        "light_gray", "cyan", "purple", "blue", "brown", "green", "red", "black",
    ];
    const BED_VARIANT_BY_DAMAGE = [
        { color: "white", de: "Weißes Bett", en: "White Bed" },
        { color: "orange", de: "Oranges Bett", en: "Orange Bed" },
        { color: "magenta", de: "Magenta Bett", en: "Magenta Bed" },
        { color: "light_blue", de: "Hellblaues Bett", en: "Light Blue Bed" },
        { color: "yellow", de: "Gelbes Bett", en: "Yellow Bed" },
        { color: "lime", de: "Hellgrünes Bett", en: "Lime Bed" },
        { color: "pink", de: "Rosa Bett", en: "Pink Bed" },
        { color: "gray", de: "Graues Bett", en: "Gray Bed" },
        { color: "light_gray", de: "Hellgraues Bett", en: "Light Gray Bed" },
        { color: "cyan", de: "Türkises Bett", en: "Cyan Bed" },
        { color: "purple", de: "Violettes Bett", en: "Purple Bed" },
        { color: "blue", de: "Blaues Bett", en: "Blue Bed" },
        { color: "brown", de: "Braunes Bett", en: "Brown Bed" },
        { color: "green", de: "Grünes Bett", en: "Green Bed" },
        { color: "red", de: "Rotes Bett", en: "Red Bed" },
        { color: "black", de: "Schwarzes Bett", en: "Black Bed" },
    ];
    // Bedrock hält diese Itemfamilien weiterhin unter einer gemeinsamen ID;
    // der Root-Damage-Wert ist hier ein Variantenschlüssel und kein Verschleiß.
    // Die Zuordnungen stammen aus Mojangs aktuellem Vanilla-Resource-/Behavior-Pack.
    const BANNER_VARIANT_BY_DAMAGE = [
        { color: "black", de: "Schwarzes Banner", en: "Black Banner" },
        { color: "red", de: "Rotes Banner", en: "Red Banner" },
        { color: "green", de: "Grünes Banner", en: "Green Banner" },
        { color: "brown", de: "Braunes Banner", en: "Brown Banner" },
        { color: "blue", de: "Blaues Banner", en: "Blue Banner" },
        { color: "purple", de: "Violettes Banner", en: "Purple Banner" },
        { color: "cyan", de: "Türkises Banner", en: "Cyan Banner" },
        { color: "light_gray", de: "Hellgraues Banner", en: "Light Gray Banner" },
        { color: "gray", de: "Graues Banner", en: "Gray Banner" },
        { color: "pink", de: "Rosa Banner", en: "Pink Banner" },
        { color: "lime", de: "Hellgrünes Banner", en: "Lime Banner" },
        { color: "yellow", de: "Gelbes Banner", en: "Yellow Banner" },
        { color: "light_blue", de: "Hellblaues Banner", en: "Light Blue Banner" },
        { color: "magenta", de: "Magenta Banner", en: "Magenta Banner" },
        { color: "orange", de: "Oranges Banner", en: "Orange Banner" },
        { color: "white", de: "Weißes Banner", en: "White Banner" },
    ];
    const GOAT_HORN_VARIANT_BY_DAMAGE = [
        { de: "Bockshorn: Sinnieren", en: "Goat Horn: Ponder" },
        { de: "Bockshorn: Singen", en: "Goat Horn: Sing" },
        { de: "Bockshorn: Suchen", en: "Goat Horn: Seek" },
        { de: "Bockshorn: Fühlen", en: "Goat Horn: Feel" },
        { de: "Bockshorn: Bewundern", en: "Goat Horn: Admire" },
        { de: "Bockshorn: Rufen", en: "Goat Horn: Call" },
        { de: "Bockshorn: Sehnen", en: "Goat Horn: Yearn" },
        { de: "Bockshorn: Traum", en: "Goat Horn: Dream" },
    ];
    const OMINOUS_BOTTLE_VARIANT_BY_DAMAGE = [
        { de: "Ominöse Flasche (Drohendes Unheil I)", en: "Ominous Bottle (Bad Omen I)" },
        { de: "Ominöse Flasche (Drohendes Unheil II)", en: "Ominous Bottle (Bad Omen II)" },
        { de: "Ominöse Flasche (Drohendes Unheil III)", en: "Ominous Bottle (Bad Omen III)" },
        { de: "Ominöse Flasche (Drohendes Unheil IV)", en: "Ominous Bottle (Bad Omen IV)" },
        { de: "Ominöse Flasche (Drohendes Unheil V)", en: "Ominous Bottle (Bad Omen V)" },
    ];
    const SUSPICIOUS_STEW_VARIANT_BY_DAMAGE = [
        { de: "Verdächtige Suppe: Nachtsicht (Mohn)", en: "Suspicious Stew: Night Vision (Poppy)" },
        { de: "Verdächtige Suppe: Sprungkraft (Kornblume)", en: "Suspicious Stew: Jump Boost (Cornflower)" },
        { de: "Verdächtige Suppe: Schwäche (Tulpe)", en: "Suspicious Stew: Weakness (Tulip)" },
        { de: "Verdächtige Suppe: Blindheit (Porzellansternchen)", en: "Suspicious Stew: Blindness (Azure Bluet)" },
        { de: "Verdächtige Suppe: Vergiftung (Maiglöckchen)", en: "Suspicious Stew: Poison (Lily of the Valley)" },
        { de: "Verdächtige Suppe: Sättigung (Löwenzahn)", en: "Suspicious Stew: Saturation (Dandelion)" },
        { de: "Verdächtige Suppe: Sättigung (Blaue Orchidee)", en: "Suspicious Stew: Saturation (Blue Orchid)" },
        { de: "Verdächtige Suppe: Feuerresistenz (Zierlauch)", en: "Suspicious Stew: Fire Resistance (Allium)" },
        { de: "Verdächtige Suppe: Regeneration (Margerite)", en: "Suspicious Stew: Regeneration (Oxeye Daisy)" },
        { de: "Verdächtige Suppe: Wither (Witherrose)", en: "Suspicious Stew: Wither (Wither Rose)" },
        { de: "Verdächtige Suppe: Nachtsicht (Fackellilie)", en: "Suspicious Stew: Night Vision (Torchflower)" },
        { de: "Verdächtige Suppe: Blindheit (Offene Augenblüte)", en: "Suspicious Stew: Blindness (Open Eyeblossom)" },
        { de: "Verdächtige Suppe: Übelkeit (Geschlossene Augenblüte)", en: "Suspicious Stew: Nausea (Closed Eyeblossom)" },
    ];
    const EMPTY_MAP_VARIANT_BY_DAMAGE = {
        0: { de: "Leere Karte", en: "Empty Map", searchIds: ["minecraft:empty_map"] },
        2: { de: "Leere Lokator-Karte", en: "Empty Locator Map", searchIds: ["minecraft:empty_locator_map"] },
    };
    const DATA_VALUE_VARIANTS_BY_ITEM = {
        "minecraft:bed": BED_VARIANT_BY_DAMAGE,
        "minecraft:banner": BANNER_VARIANT_BY_DAMAGE,
        "minecraft:goat_horn": GOAT_HORN_VARIANT_BY_DAMAGE,
        "minecraft:ominous_bottle": OMINOUS_BOTTLE_VARIANT_BY_DAMAGE,
        "minecraft:suspicious_stew": SUSPICIOUS_STEW_VARIANT_BY_DAMAGE,
        "minecraft:empty_map": EMPTY_MAP_VARIANT_BY_DAMAGE,
        // Serialisierungsalias in vorhandenen Welten; nicht neu hinzufügbar,
        // aber im Slot-Editor weiterhin korrekt benannt.
        "minecraft:emptymap": EMPTY_MAP_VARIANT_BY_DAMAGE,
    };
    const DATA_VALUE_LABELS = {
        "minecraft:bed": "Bettfarbe",
        "minecraft:banner": "Bannerfarbe",
        "minecraft:goat_horn": "Hornklang",
        "minecraft:ominous_bottle": "Stufe von Drohendes Unheil",
        "minecraft:suspicious_stew": "Suppeneffekt",
        "minecraft:empty_map": "Kartentyp",
        "minecraft:emptymap": "Kartentyp",
    };
    const DYE_COLOR_BY_DAMAGE = [
        "black", "red", "green", "brown", "blue", "purple", "cyan", "light_gray",
        "gray", "pink", "lime", "yellow", "light_blue", "magenta", "orange", "white",
    ];
    const RED_FLOWER_BY_DAMAGE = {
        0: "poppy",
        1: "blue_orchid",
        2: "allium",
        3: "azure_bluet",
        4: "red_tulip",
        5: "orange_tulip",
        6: "white_tulip",
        7: "pink_tulip",
        8: "oxeye_daisy",
        9: "cornflower",
        10: "lily_of_the_valley",
    };
    const DOUBLE_PLANT_BY_DAMAGE = {
        0: "sunflower",
        1: "lilac",
        2: "tallgrass",
        3: "large_fern",
        4: "rose_bush",
        5: "peony",
    };
    const DOUBLE_STONE_SLAB_BY_DAMAGE = {
        0: "stone_slab",
        1: "sandstone_slab",
        2: "wooden_slab",
        3: "cobblestone_slab",
        4: "brick_slab",
        5: "stone_brick_slab",
        6: "quartz_slab",
        7: "nether_brick_slab",
    };
    const STONE_BLOCK_SLAB_BY_DAMAGE = {
        0: "smooth_stone_slab",
        1: "sandstone_slab",
        2: "petrified_oak_slab",
        3: "cobblestone_slab",
        4: "brick_slab",
        5: "stone_brick_slab",
        6: "quartz_slab",
        7: "nether_brick_slab",
    };
    const POTION_ICON_DAMAGE_VALUES = new Set([
        0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20,
        21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35,
        36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46,
    ]);
    const POTION_ICON_ITEMS = new Set([
        "minecraft:potion",
        "minecraft:splash_potion",
        "minecraft:lingering_potion",
        "minecraft:tipped_arrow",
    ]);
    const POTION_VARIANT_BY_DAMAGE = {
        0: { de: "Wasserflasche", en: "Water Bottle", water: true },
        1: { de: "Mundan", en: "Mundane" },
        2: { de: "Mundan", en: "Mundane", modifierDe: "verlängert", modifierEn: "Long" },
        3: { de: "Dickflüssig", en: "Thick" },
        4: { de: "Seltsam", en: "Awkward" },
        5: { de: "Nachtsicht", en: "Night Vision" },
        6: { de: "Nachtsicht", en: "Night Vision", modifierDe: "verlängert", modifierEn: "Long" },
        7: { de: "Unsichtbarkeit", en: "Invisibility" },
        8: { de: "Unsichtbarkeit", en: "Invisibility", modifierDe: "verlängert", modifierEn: "Long" },
        9: { de: "Sprungkraft", en: "Leaping" },
        10: { de: "Sprungkraft", en: "Leaping", modifierDe: "verlängert", modifierEn: "Long" },
        11: { de: "Sprungkraft", en: "Leaping", modifierDe: "verstärkt", modifierEn: "Strong" },
        12: { de: "Feuerresistenz", en: "Fire Resistance" },
        13: { de: "Feuerresistenz", en: "Fire Resistance", modifierDe: "verlängert", modifierEn: "Long" },
        14: { de: "Schnelligkeit", en: "Swiftness" },
        15: { de: "Schnelligkeit", en: "Swiftness", modifierDe: "verlängert", modifierEn: "Long" },
        16: { de: "Schnelligkeit", en: "Swiftness", modifierDe: "verstärkt", modifierEn: "Strong" },
        17: { de: "Langsamkeit", en: "Slowness" },
        18: { de: "Langsamkeit", en: "Slowness", modifierDe: "verlängert", modifierEn: "Long" },
        19: { de: "Wasseratmung", en: "Water Breathing" },
        20: { de: "Wasseratmung", en: "Water Breathing", modifierDe: "verlängert", modifierEn: "Long" },
        21: { de: "Heilung", en: "Healing" },
        22: { de: "Heilung", en: "Healing", modifierDe: "verstärkt", modifierEn: "Strong" },
        23: { de: "Schaden", en: "Harming" },
        24: { de: "Schaden", en: "Harming", modifierDe: "verstärkt", modifierEn: "Strong" },
        25: { de: "Vergiftung", en: "Poison" },
        26: { de: "Vergiftung", en: "Poison", modifierDe: "verlängert", modifierEn: "Long" },
        27: { de: "Vergiftung", en: "Poison", modifierDe: "verstärkt", modifierEn: "Strong" },
        28: { de: "Regeneration", en: "Regeneration" },
        29: { de: "Regeneration", en: "Regeneration", modifierDe: "verlängert", modifierEn: "Long" },
        30: { de: "Regeneration", en: "Regeneration", modifierDe: "verstärkt", modifierEn: "Strong" },
        31: { de: "Stärke", en: "Strength" },
        32: { de: "Stärke", en: "Strength", modifierDe: "verlängert", modifierEn: "Long" },
        33: { de: "Stärke", en: "Strength", modifierDe: "verstärkt", modifierEn: "Strong" },
        34: { de: "Schwäche", en: "Weakness" },
        35: { de: "Schwäche", en: "Weakness", modifierDe: "verlängert", modifierEn: "Long" },
        36: { de: "Wither", en: "Decay" },
        37: { de: "Schildkrötenmeister", en: "Turtle Master" },
        38: { de: "Schildkrötenmeister", en: "Turtle Master", modifierDe: "verlängert", modifierEn: "Long" },
        39: { de: "Schildkrötenmeister", en: "Turtle Master", modifierDe: "verstärkt", modifierEn: "Strong" },
        40: { de: "Sanfter Fall", en: "Slow Falling" },
        41: { de: "Sanfter Fall", en: "Slow Falling", modifierDe: "verlängert", modifierEn: "Long" },
        42: { de: "Langsamkeit IV", en: "Slowness IV" },
        43: { de: "Windgeladen", en: "Wind Charged" },
        44: { de: "Weben", en: "Weaving" },
        45: { de: "Schleimig", en: "Oozing" },
        46: { de: "Befallen", en: "Infested" },
    };
    const POTION_WATER_NAMES = {
        "minecraft:potion": ["Wasserflasche", "Water Bottle"],
        "minecraft:splash_potion": ["Wurfwasserflasche", "Splash Water Bottle"],
        "minecraft:lingering_potion": ["Verweilwasserflasche", "Lingering Water Bottle"],
    };
    const POTION_ITEM_LABEL_PREFIXES = {
        "minecraft:potion": ["Trank", "Potion"],
        "minecraft:splash_potion": ["Wurftrank", "Splash Potion"],
        "minecraft:lingering_potion": ["Verweiltrank", "Lingering Potion"],
        "minecraft:tipped_arrow": ["Getränkter Pfeil", "Tipped Arrow"],
    };

    const SPECIAL_ITEM_NBT_HINTS = [
        { test: name => name === "minecraft:filled_map", label: "Karten-ID/Map-Daten" },
        { test: name => name.includes("potion") || name === "minecraft:tipped_arrow", label: "Potion-/Effektdaten" },
        { test: name => name === "minecraft:writable_book" || name === "minecraft:written_book", label: "Buchseiten/Autor/Titel" },
        { test: name => name.startsWith("minecraft:firework"), label: "Feuerwerksdaten" },
        { test: name => name.includes("suspicious_stew"), label: "Stew-Effektdaten" },
        { test: name => name.includes("bundle"), label: "Container-Inhalt" },
        { test: name => name.includes("shulker_box"), label: "Container-Inhalt" },
    ];

    function createItemCatalog(deps) {
        const getItemsDb = deps.getItemsDb;
        const getCompatItemAliases = deps.getCompatItemAliases;
        const getAddableItems = deps.getAddableItems || (() => null);
        const getItemIconIndex = deps.getItemIconIndex;
        const getStackLimits = deps.getStackLimits;
        const getMaxDamageMap = deps.getMaxDamageMap;
        const getEnchantmentCompatibility = deps.getEnchantmentCompatibility || (() => ({}));
        const getItemComponents = deps.getItemComponents || (() => ({}));
        const itemIdRe = deps.itemIdRe;
        const defaultMaxDamage = deps.defaultMaxDamage;
        const maxBedrockStackCount = deps.maxBedrockStackCount;

        function enchantmentCompatibility() {
            return getEnchantmentCompatibility() || {};
        }

        function itemComponents() {
            return getItemComponents() || {};
        }

        function slotList(map, key) {
            const value = map?.[key];
            return Array.isArray(value) ? value : [];
        }

        function canonicalItemId(itemId) {
            const normalized = String(itemId || "").trim().toLowerCase();
            return getCompatItemAliases()[normalized] || normalized;
        }

        function itemNamesForId(itemId) {
            const normalized = String(itemId || "").trim().toLowerCase();
            const itemsDb = getItemsDb();
            return itemsDb[normalized] || itemsDb[canonicalItemId(normalized)] || ["", ""];
        }

        function damageKey(value) {
            const parsed = parseInt(value, 10);
            return Number.isFinite(parsed) ? Math.max(0, parsed) : 0;
        }

        function itemBlockNameFromNbt(item) {
            const blockName = item?.nbt_view?.value?.Block?.value?.name?.value;
            return typeof blockName === "string" && blockName.startsWith("minecraft:") ? blockName.toLowerCase() : "";
        }

        function variantModifierText(label, modifier) {
            return modifier ? `${label} (${modifier})` : label;
        }

        function potionVariantNamesForItem(itemOrId, damageArg = null) {
            const item = typeof itemOrId === "object" && itemOrId ? itemOrId : null;
            const rawName = item ? item.name : itemOrId;
            const name = String(rawName || "").trim().toLowerCase();
            if (!POTION_ICON_ITEMS.has(name)) return null;
            const damage = damageKey(item ? item.damage : damageArg);
            const variant = POTION_VARIANT_BY_DAMAGE[damage];
            if (!variant) return null;
            if (variant.water && POTION_WATER_NAMES[name]) return POTION_WATER_NAMES[name];
            const prefixes = POTION_ITEM_LABEL_PREFIXES[name];
            const deVariant = variantModifierText(variant.de, variant.modifierDe);
            const enVariant = variantModifierText(variant.en, variant.modifierEn);
            return [`${prefixes[0]}: ${deVariant}`, `${prefixes[1]} of ${enVariant}`];
        }

        function variantItemNamesForId(itemOrId, damageArg = null) {
            const potionNames = potionVariantNamesForItem(itemOrId, damageArg);
            if (potionNames) return potionNames;
            const item = typeof itemOrId === "object" && itemOrId ? itemOrId : null;
            const name = String(item ? item.name : itemOrId || "").trim().toLowerCase();
            const damage = damageKey(item ? item.damage : damageArg);
            const variant = DATA_VALUE_VARIANTS_BY_ITEM[name]?.[damage]
                || DATA_VALUE_VARIANTS_BY_ITEM[canonicalItemId(name)]?.[damage];
            return variant ? [variant.de, variant.en] : null;
        }

        function dataValueVariantsForId(itemId) {
            const normalized = String(itemId || "").trim().toLowerCase();
            const canonical = canonicalItemId(normalized);
            const variants = DATA_VALUE_VARIANTS_BY_ITEM[normalized] || DATA_VALUE_VARIANTS_BY_ITEM[canonical];
            if (!variants) return [];
            return Object.entries(variants)
                .map(([rawDamage, variant]) => {
                    const damage = Number(rawDamage);
                    const searchIds = Array.isArray(variant.searchIds) ? [...variant.searchIds] : [];
                    if (variant.color && canonical === "minecraft:bed") searchIds.push(`minecraft:${variant.color}_bed`);
                    if (variant.color && canonical === "minecraft:banner") searchIds.push(`minecraft:${variant.color}_banner`);
                    return {
                        id: normalized,
                        damage,
                        names: [variant.de, variant.en],
                        searchIds,
                    };
                })
                .sort((left, right) => left.damage - right.damage);
        }

        function addableItemVariantsForId(itemId) {
            return dataValueVariantsForId(itemId);
        }

        function itemUsesDurabilityDamage(itemName) {
            const normalized = String(itemName || "").trim().toLowerCase();
            return Boolean(normalized) && !POTION_ICON_ITEMS.has(normalized) && getMaxDamage(normalized) !== defaultMaxDamage;
        }

        function itemDamageLabel(itemName) {
            const normalized = String(itemName || "").trim().toLowerCase();
            if (POTION_ICON_ITEMS.has(normalized)) return t("Potion-Datenwert");
            const dataValueLabel = DATA_VALUE_LABELS[normalized] || DATA_VALUE_LABELS[canonicalItemId(normalized)];
            if (dataValueLabel) return t(dataValueLabel);
            return itemUsesDurabilityDamage(normalized) ? t("Abnutzung") : t("Datenwert");
        }

        function variantTargetItemId(itemOrId, damageArg = null) {
            const item = typeof itemOrId === "object" && itemOrId ? itemOrId : null;
            const rawName = item ? item.name : itemOrId;
            const name = String(rawName || "").trim().toLowerCase();
            const canonical = canonicalItemId(name);
            const damage = damageKey(item ? item.damage : damageArg);
            const color = WOOL_COLOR_BY_DAMAGE[damage];
            const dyeColor = DYE_COLOR_BY_DAMAGE[damage];
            if (!name || name === "minecraft:air") return "";
            const bedColor = canonical === "minecraft:bed" ? BED_VARIANT_BY_DAMAGE[damage]?.color : "";
            if (bedColor) return `minecraft:${bedColor}_bed`;
            const bannerColor = canonical === "minecraft:banner" ? BANNER_VARIANT_BY_DAMAGE[damage]?.color : "";
            if (bannerColor) return `minecraft:${bannerColor}_banner`;
            if (color) {
                if (name === "minecraft:carpet") return `minecraft:${color}_carpet`;
                if (name === "minecraft:concrete_powder") return `minecraft:${color}_concrete_powder`;
                if (name === "minecraft:wool") return `minecraft:${color}_wool`;
                if (name === "minecraft:stained_glass" || name === "minecraft:hard_stained_glass") return `minecraft:${color}_stained_glass`;
                if (name === "minecraft:stained_glass_pane" || name === "minecraft:hard_stained_glass_pane") return `minecraft:${color}_stained_glass_pane`;
            }
            if (dyeColor && name === "minecraft:dye") return `minecraft:${dyeColor}_dye`;
            if (name === "minecraft:red_flower" && RED_FLOWER_BY_DAMAGE[damage]) return `minecraft:${RED_FLOWER_BY_DAMAGE[damage]}`;
            if (name === "minecraft:double_plant" && DOUBLE_PLANT_BY_DAMAGE[damage]) return `minecraft:${DOUBLE_PLANT_BY_DAMAGE[damage]}`;
            if ((name === "minecraft:double_stone_slab" || name === "minecraft:double_stone_slab2" || name === "minecraft:double_stone_slab3" || name === "minecraft:double_stone_slab4") && DOUBLE_STONE_SLAB_BY_DAMAGE[damage]) {
                return `minecraft:${DOUBLE_STONE_SLAB_BY_DAMAGE[damage]}`;
            }
            if ((name === "minecraft:stone_block_slab" || name === "minecraft:stone_block_slab2" || name === "minecraft:stone_block_slab3" || name === "minecraft:stone_block_slab4") && STONE_BLOCK_SLAB_BY_DAMAGE[damage]) {
                return `minecraft:${STONE_BLOCK_SLAB_BY_DAMAGE[damage]}`;
            }
            return "";
        }

        function variantIconKey(itemOrId, damageArg = null) {
            const item = typeof itemOrId === "object" && itemOrId ? itemOrId : null;
            const rawName = item ? item.name : itemOrId;
            const name = String(rawName || "").trim().toLowerCase();
            if (!name || name === "minecraft:air") return "";
            const damage = damageKey(item ? item.damage : damageArg);
            if (POTION_ICON_ITEMS.has(name) && POTION_ICON_DAMAGE_VALUES.has(damage)) {
                return `${name}#${damage}`;
            }
            const variantTarget = variantTargetItemId(itemOrId, damageArg);
            return variantTarget ? `${name}#${damage}` : "";
        }

        function potionIconFallbackCandidates(itemName) {
            const normalized = String(itemName || "").trim().toLowerCase();
            const shortName = normalized.startsWith("minecraft:") ? normalized.slice("minecraft:".length) : normalized;
            if (!shortName) return [];
            if (shortName === "potion" || shortName === "splash_potion" || shortName === "lingering_potion" || shortName === "tipped_arrow") {
                return [];
            }
            if (shortName.endsWith("_tipped_arrow")) return ["minecraft:tipped_arrow"];
            if (!shortName.includes("potion")) return [];
            if (shortName.startsWith("splash_") || shortName.includes("_splash_") || shortName.endsWith("_splash_potion")) {
                return ["minecraft:splash_potion"];
            }
            if (shortName.startsWith("lingering_") || shortName.includes("_lingering_") || shortName.endsWith("_lingering_potion")) {
                return ["minecraft:lingering_potion"];
            }
            return ["minecraft:potion"];
        }

        function iconLookupCandidates(itemOrId, damageArg = null) {
            const item = typeof itemOrId === "object" && itemOrId ? itemOrId : null;
            const rawName = item ? item.name : itemOrId;
            const normalized = String(rawName || "").trim().toLowerCase();
            const candidates = [];
            const variantKey = variantIconKey(itemOrId, damageArg);
            const variantTarget = variantTargetItemId(itemOrId, damageArg);
            const blockName = item ? itemBlockNameFromNbt(item) : "";
            [variantKey, variantTarget, ...potionIconFallbackCandidates(normalized), normalized, canonicalItemId(normalized), blockName, canonicalItemId(blockName)]
                .filter(Boolean)
                .forEach(candidate => {
                    if (!candidates.includes(candidate)) candidates.push(candidate);
                });
            return candidates;
        }

        function getItemIconMeta(itemOrId, damageArg = null) {
            const itemIconIndex = getItemIconIndex();
            for (const candidate of iconLookupCandidates(itemOrId, damageArg)) {
                if (itemIconIndex[candidate]) return itemIconIndex[candidate];
            }
            return null;
        }

        function getItemEmoji(itemId) {
            if (!itemId || itemId === "minecraft:air") return "";
            const lowerId = itemId.toLowerCase();
            for (const [key, emoji] of Object.entries(EMOJI_MAP)) {
                if (lowerId.includes(key)) return emoji;
            }
            return "📦";
        }

        // Vanilla-Ausschlussregeln (Amboss/Zaubertisch) aus exclusive_groups.
        // Rein informativ: per NBT gesetzte Kombinationen funktionieren im Spiel
        // und bleiben speicherbar; die UI zeigt nur einen Hinweis.
        function vanillaExclusiveEnchantmentConflicts(enchantments = [], itemName = "") {
            if (canonicalItemId(String(itemName || "").trim().toLowerCase()) === "minecraft:enchanted_book") {
                return [];
            }
            const groups = getEnchantmentCompatibility()?.exclusive_groups;
            if (!Array.isArray(groups)) return [];
            const presentIds = new Set(
                (Array.isArray(enchantments) ? enchantments : [])
                    .map(e => Number(e?.id))
                    .filter(Number.isInteger)
            );
            const conflicts = [];
            groups.forEach(group => {
                if (!Array.isArray(group)) return;
                const hits = group.filter(id => presentIds.has(Number(id)));
                if (hits.length >= 2) conflicts.push(hits.map(Number));
            });
            return conflicts;
        }

        function getItemIconTint(itemOrId) {
            const item = typeof itemOrId === "object" && itemOrId ? itemOrId : null;
            const normalized = String((item ? item.name : itemOrId) || "").trim().toLowerCase();
            // Bewusst nur die kuratierte Tabelle: minecraft:dyeable liefert die
            // Fabrikfarbe ungefärbten Leders, nicht die tatsächliche Item-Farbe
            // (die steckt in tag.customColor) — als Fallback wäre sie falsch.
            return ICON_TINTS[normalized] || ICON_TINTS[canonicalItemId(normalized)] || "";
        }

        function clampNumber(value, fallback, min, max) {
            const parsed = parseInt(value, 10);
            if (!Number.isFinite(parsed)) return fallback;
            if (min > max) [min, max] = [max, min];
            return Math.min(Math.max(parsed, min), max);
        }

        function finiteNumber(value, fallback) {
            const parsed = parseFloat(value);
            return Number.isFinite(parsed) ? parsed : fallback;
        }

        function clampFiniteNumber(value, fallback, min, max) {
            const parsed = finiteNumber(value, fallback);
            if (min > max) [min, max] = [max, min];
            return Math.min(Math.max(parsed, min), max);
        }

        function isValidItemId(itemName) {
            return itemIdRe.test(String(itemName || "").trim().toLowerCase());
        }

        function isKnownItemId(itemName) {
            const normalized = String(itemName || "").trim().toLowerCase();
            const itemsDb = getItemsDb();
            const compatItemAliases = getCompatItemAliases();
            return !!normalized && (Object.prototype.hasOwnProperty.call(itemsDb, normalized) || Object.prototype.hasOwnProperty.call(compatItemAliases, normalized));
        }

        function isAddableItemId(itemName) {
            const normalized = String(itemName || "").trim().toLowerCase();
            const addableItems = getAddableItems();
            // Null bedeutet nur Rückwärtskompatibilität für isolierte Clients;
            // die App liefert stets Mojangs positive Registry als Set.
            if (!addableItems || typeof addableItems.has !== "function") return isKnownItemId(normalized);
            return Boolean(normalized) && addableItems.has(normalized);
        }

        function getMaxStack(itemName) {
            if (!itemName) return 64;
            if (!isKnownItemId(itemName)) return maxBedrockStackCount;
            const normalized = String(itemName).trim().toLowerCase();
            const stackLimits = getStackLimits();
            const defaultLimit = stackLimits.__default__ ?? 64;
            return stackLimits[normalized] ?? stackLimits[canonicalItemId(normalized)] ?? defaultLimit;
        }

        function getMaxDamage(itemName) {
            if (!itemName) return defaultMaxDamage;
            const normalized = String(itemName).trim().toLowerCase();
            const maxDamage = getMaxDamageMap();
            const defaultDmg = maxDamage.__default__ ?? defaultMaxDamage;
            return maxDamage[normalized] ?? maxDamage[canonicalItemId(normalized)] ?? defaultDmg;
        }

        function itemComponent(itemName, componentName) {
            const normalized = canonicalItemId(String(itemName || "").trim().toLowerCase());
            const componentMap = itemComponents()?.[String(componentName || "").trim().toLowerCase()];
            const component = componentMap?.[normalized];
            return component && typeof component === "object" ? component : null;
        }

        function enchantmentSlotsForItem(itemName) {
            const normalized = canonicalItemId(String(itemName || "").trim().toLowerCase());
            if (!normalized || normalized === "minecraft:air") return [];
            const compatibility = enchantmentCompatibility();
            const officialSlots = compatibility.official_item_slots;
            if (officialSlots && Object.prototype.hasOwnProperty.call(officialSlots, normalized)) {
                return Array.from(expandEnchantmentSlotGroups(slotList(officialSlots, normalized)));
            }
            const exactSlots = slotList(compatibility.item_slots, normalized);
            if (exactSlots.length) return Array.from(expandEnchantmentSlotGroups(exactSlots));
            const shortName = normalized.replace(/^minecraft:/, "");
            const suffixSlots = Array.isArray(compatibility.item_slot_suffixes) ? compatibility.item_slot_suffixes : [];
            const match = suffixSlots.find(entry => Array.isArray(entry) && entry.length === 2 && shortName.endsWith(String(entry[0] || "")));
            return match ? Array.from(expandEnchantmentSlotGroups([String(match[1] || "")].filter(Boolean))) : [];
        }

        function expandEnchantmentSlotGroups(slots) {
            const slotGroups = enchantmentCompatibility().slot_groups || {};
            const expanded = new Set();
            (slots || []).forEach(slot => {
                (slotGroups[slot] || [slot]).forEach(expandedSlot => expanded.add(expandedSlot));
            });
            return expanded;
        }

        function isEnchantableItemForEditor(itemName) {
            return enchantmentSlotsForItem(itemName).length > 0;
        }

        function isEnchantmentCompatibleWithItem(enchantmentId, itemName) {
            const itemSlots = new Set(enchantmentSlotsForItem(itemName));
            if (itemSlots.size === 0) return false;
            const compatibleSlots = expandEnchantmentSlotGroups(slotList(enchantmentCompatibility().compatible_slots, String(Number(enchantmentId))));
            for (const slot of itemSlots) {
                if (compatibleSlots.has(slot)) return true;
            }
            return false;
        }

        function specialItemNbtRequirement(itemName) {
            const normalized = String(itemName || "").trim().toLowerCase();
            if (!normalized || normalized === "minecraft:air") return null;
            const match = SPECIAL_ITEM_NBT_HINTS.find(entry => entry.test(normalized));
            return match ? t(match.label) : null;
        }

        return {
            canonicalItemId,
            clampFiniteNumber,
            clampNumber,
            enchantmentSlotsForItem,
            expandEnchantmentSlotGroups,
            finiteNumber,
            getItemEmoji,
            getItemIconMeta,
            getItemIconTint,
            getMaxDamage,
            vanillaExclusiveEnchantmentConflicts,
            getMaxStack,
            iconLookupCandidates,
            itemDamageLabel,
            itemComponent,
            itemUsesDurabilityDamage,
            isEnchantableItemForEditor,
            isEnchantmentCompatibleWithItem,
            isAddableItemId,
            isKnownItemId,
            isValidItemId,
            itemNamesForId,
            addableItemVariantsForId,
            dataValueVariantsForId,
            specialItemNbtRequirement,
            variantItemNamesForId,
            variantIconKey,
            variantTargetItemId,
        };
    }

    window.MCBEItemCatalog = {
        createItemCatalog,
    };
}());
