(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));

    function localizedNamePair(de, en) {
        const shared = window.MCBEI18n?.localizedPair?.(de, en);
        if (shared) return shared;
        const primary = de || en || "";
        const secondaryCandidate = en || "";
        return {
            primary,
            secondary: secondaryCandidate === primary ? "" : secondaryCandidate,
        };
    }

    function isEnglishItemLocale() {
        return Boolean(window.MCBEI18n?.isEnglish?.());
    }

    function localizedItemNamePair(de, en) {
        if (isEnglishItemLocale()) {
            return { primary: String(en || ""), secondary: "" };
        }
        return localizedNamePair(de, en);
    }

    function itemMatchesQuery(id, names, query, metadata = null) {
        const normalized = String(query || "").toLowerCase().trim();
        if (!normalized) return true;
        const de = String(names?.[0] || "").toLowerCase();
        const en = String(names?.[1] || "").toLowerCase();
        const rawId = String(id || "").toLowerCase();
        const searchIds = Array.isArray(metadata?.searchIds)
            ? metadata.searchIds.map(value => String(value || "").toLowerCase())
            : [];
        return rawId.includes(normalized)
            || en.includes(normalized)
            || searchIds.some(value => value.includes(normalized))
            || (!isEnglishItemLocale() && de.includes(normalized));
    }

    const COMMON_ITEM_IDS = new Set([
        "minecraft:diamond_sword", "minecraft:diamond_pickaxe", "minecraft:diamond_axe", "minecraft:diamond_shovel",
        "minecraft:netherite_sword", "minecraft:netherite_pickaxe", "minecraft:bow", "minecraft:crossbow",
        "minecraft:diamond", "minecraft:emerald", "minecraft:iron_ingot", "minecraft:gold_ingot",
        "minecraft:apple", "minecraft:golden_apple", "minecraft:bread", "minecraft:cooked_beef",
        "minecraft:torch", "minecraft:chest", "minecraft:crafting_table", "minecraft:ender_pearl",
    ]);

    const ITEM_BROWSER_CATEGORY_ORDER = [
        "armor", "food", "consumables", "redstone", "transport",
        "containers", "spawn_eggs", "weapons", "materials", "blocks",
    ];
    const ITEM_CATEGORY_CACHE = new Map();

    // Kuratierte Semantik für IDs, deren Name allein keine zuverlässige
    // Kategorie liefert. Moderne und Legacy-Aliasse sollen identisch wirken.
    const ITEM_CATEGORY_OVERRIDES = new Map([
        ["kelp", { add: ["blocks"], remove: ["food"] }],
        ["chorus_fruit", { add: ["food"] }],
        ["popped_chorus_fruit", { add: ["materials"], remove: ["consumables"] }],
        ["enchanted_golden_apple", { add: ["consumables"] }],
        ["fireworkscharge", { add: ["materials"], remove: ["consumables"] }],
    ]);
    const REDSTONE_OVERRIDE_IDS = new Set([
        "activator_rail", "chiseled_bookshelf", "detector_rail", "golden_rail",
        "jukebox", "lectern", "lightning_rod", "noteblock", "trapped_chest",
    ]);

    const FOOD_SEGMENTS = new Set([
        "apple", "bread", "beef", "porkchop", "chicken", "mutton", "rabbit",
        "cod", "salmon", "potato", "carrot", "beetroot", "cookie", "melon",
        "stew", "soup", "pie", "berries", "kelp",
    ]);
    const FOOD_EXACT_IDS = new Set([
        "appleenchanted", "cake", "clownfish", "cooked_fish", "fish", "honey_bottle",
        "muttoncooked", "muttonraw", "porkchop_cooked", "pufferfish", "rotten_flesh",
        "spider_eye", "steak", "tropical_fish",
    ]);
    const FOOD_EXCLUDED_IDS = new Set([
        "glistering_melon_slice", "speckled_melon",
    ]);
    const CONSUMABLE_EXACT_IDS = new Set([
        "appleenchanted", "blue_egg", "brown_egg", "bucket", "egg", "fireball", "fireworks",
        "fireworkscharge", "golden_apple", "ice_bomb", "milk", "rapid_fertilizer", "totem_of_undying",
    ]);
    const MATERIAL_EXACT_IDS = new Set([
        "amethyst_shard", "armadillo_scute", "blaze_powder", "blaze_rod", "bone", "bone_meal",
        "ancient_debris", "book", "breeze_rod", "brick", "charcoal", "chorus_fruit_popped",
        "cinnabar", "clay_ball", "coal", "cocoa_beans", "copper_ingot", "copper_nugget", "diamond", "disc_fragment",
        "disc_fragment_5", "dragon_breath", "echo_shard", "emerald", "enchanted_book",
        "ender_eye", "ender_pearl", "feather", "fermented_spider_eye", "firework_star", "flint", "ghast_tear", "glistering_melon_slice", "glow_ink_sac",
        "glowstone_dust", "gold_ingot", "gold_nugget", "gunpowder", "heart_of_the_sea",
        "heavy_core", "honeycomb", "ink_sac", "iron_ingot", "iron_nugget", "lapis_lazuli",
        "leather", "magma_cream", "nautilus_shell", "nether_brick", "nether_star", "nether_wart",
        "netherbrick", "netherite_ingot", "netherite_scrap", "netherstar", "paper", "phantom_membrane",
        "oreruby", "pitcher_pod", "potent_sulfur", "prismarine_crystals", "prismarine_shard", "quartz", "rabbit_foot", "resin_brick",
        "rabbit_hide", "raw_copper", "raw_gold", "raw_iron", "redstone", "resin_clump", "ruby",
        "shulker_shell", "slime_ball", "speckled_melon", "stick", "string", "sugar", "sugar_cane", "sulfur", "turtle_scute", "turtle_shell_piece",
        "wheat", "writable_book", "written_book",
    ]);
    const MATERIAL_ENDINGS = ["banner_pattern", "dye", "pottery_sherd", "seeds", "smithing_template"];
    const RESOURCE_BLOCK_SEGMENTS = new Set([
        "amethyst", "bone", "coal", "copper", "diamond", "emerald", "gold", "iron",
        "lapis", "netherite", "quartz", "raw", "redstone",
    ]);
    const REDSTONE_SEGMENTS = new Set([
        "redstone", "repeater", "comparator", "piston", "observer", "hopper",
        "dropper", "dispenser", "lever", "target", "crafter",
    ]);
    const CONTAINER_SEGMENTS = new Set([
        "chest", "barrel", "furnace", "smoker", "hopper", "dispenser",
        "dropper", "crafter", "bundle", "shelf",
    ]);
    const BLOCK_ENDINGS = [
        "andesite", "anvil", "banner", "barrel", "bars", "basalt", "bed", "beehive", "block", "bricks", "bud",
        "bulb", "bush", "button", "candle", "carpet", "chain", "chest", "cluster", "concrete",
        "concrete_powder", "coral", "coral_fan", "deepslate", "diorite", "dirt", "door", "fence",
        "fence_gate", "flower", "froglight", "furnace", "fungus", "glass", "glass_pane",
        "granite", "grass", "grate", "hanging_sign", "head", "hyphae", "ice", "lantern", "leaves",
        "lichen", "log", "moss", "mushroom", "nest", "nylium", "obsidian", "ore", "pane",
        "petals", "pillar", "planks", "plant", "pressure_plate", "prismarine", "pumpkin", "roots", "sapling", "stone",
        "shelf", "sign", "skull", "slab", "stairs", "statue", "stem", "table", "terracotta",
        "tiles", "torch", "trapdoor", "tuff", "vines", "wall", "wood", "wool",
    ];
    const BLOCK_EXACT_IDS = new Set([
        "azalea", "bamboo", "barrier", "basalt", "beacon", "bedrock", "big_dripleaf", "blackstone",
        "ancient_debris", "armor_stand", "azalea_leaves_flowered", "azure_bluet", "bamboo_mosaic", "bee_nest", "beehive", "bell", "bookshelf",
        "budding_amethyst", "cactus", "calcite", "campfire", "carved_pumpkin", "cauldron", "clay",
        "chalkboard", "chiseled_bookshelf", "cobbled_deepslate", "cobblestone", "composter",
        "concretepowder", "conduit", "creaking_heart", "deadbush", "decorated_pot", "deepslate",
        "dirt", "doorwood", "dragon_egg", "end_crystal", "end_gateway", "end_portal_frame",
        "dandelion", "dried_ghast", "end_rod", "farmland", "flower_pot", "flowering_azalea", "frame", "frog_spawn", "frosted_ice", "glow_frame",
        "glowingobsidian", "glowstone", "grass", "grass_path", "gravel", "grindstone", "hardened_clay", "ice",
        "invisible_bedrock", "invisiblebedrock", "jigsaw", "jukebox", "ladder", "leaf_litter",
        "leaves2", "lectern", "lightning_rod", "lit_pumpkin", "lodestone", "loom", "magma",
        "mangrove_propagule", "mob_spawner", "monster_egg", "mud", "mushroom_stem", "mycelium",
        "netherrack", "netherreactor", "noteblock", "obsidian", "packed_ice", "packed_mud", "podzol",
        "lily_of_the_valley", "pointed_dripstone", "poppy", "prismarine", "pumpkin", "sand", "scaffolding", "sculk", "sea_pickle",
        "painting", "photo", "pitcher_plant", "red_nether_brick", "respawn_anchor", "sealantern", "shroomlight", "slime",
        "smooth_basalt", "smooth_quartz", "sniffer_egg", "snow", "sponge", "stained_hardened_clay",
        "stone", "stonebrick", "stonecutter", "structure_void", "sulfur_spike", "tallgrass", "trial_spawner",
        "tuff", "turtle_egg", "vault", "waterlily", "web", "wet_sponge", "wildflowers",
    ]);

    function itemPath(id) {
        const lower = String(id || "").toLowerCase();
        const separator = lower.indexOf(":");
        return separator >= 0 ? lower.slice(separator + 1) : lower;
    }

    function pathSegments(path) {
        return String(path || "").split("_").filter(Boolean);
    }

    function hasAnySegment(path, expected) {
        return pathSegments(path).some(segment => expected.has(segment));
    }

    function endsWithTerm(path, term) {
        return path === term || path.endsWith(`_${term}`);
    }

    function endsWithAnyTerm(path, terms) {
        return terms.some(term => endsWithTerm(path, term));
    }

    function isArmor(path) {
        return endsWithAnyTerm(path, ["helmet", "chestplate", "leggings", "boots", "horse_armor", "nautilus_armor", "harness"])
            || ["elytra", "shield", "wolf_armor"].includes(path)
            || path.startsWith("horsearmor");
    }

    function isFood(path) {
        if (FOOD_EXCLUDED_IDS.has(path) || path.endsWith("_spawn_egg") || path.includes("_bucket") || path.startsWith("bucket")) return false;
        if (path.startsWith("music_disc_") || path.startsWith("record_")) return false;
        if (endsWithAnyTerm(path, ["block", "seeds", "foot", "hide", "shell_piece", "on_a_stick"]) || path.endsWith("onastick")) return false;
        return FOOD_EXACT_IDS.has(path) || hasAnySegment(path, FOOD_SEGMENTS);
    }

    function isConsumable(path) {
        if (path.endsWith("_spawn_egg")) return false;
        return endsWithAnyTerm(path, ["potion", "arrow", "bucket", "bottle", "rocket", "totem", "pearl", "fruit", "charge", "snowball"])
            || CONSUMABLE_EXACT_IDS.has(path)
            || path.startsWith("bucket");
    }

    function isRedstone(path) {
        return hasAnySegment(path, REDSTONE_SEGMENTS)
            || endsWithAnyTerm(path, [
                "daylight_detector", "tripwire", "tripwire_hook", "button", "pressure_plate",
                "sculk_sensor", "redstone_lamp", "redstone_torch",
            ])
            || ["tnt", "copper_bulb"].includes(path);
    }

    function isTransport(path) {
        return endsWithAnyTerm(path, ["boat", "chest_boat", "raft", "chest_raft", "minecart", "rail"])
            || path.startsWith("minecart")
            || ["elytra", "saddle", "carrot_on_a_stick", "carrotonastick", "warped_fungus_on_a_stick", "lead"].includes(path);
    }

    function isContainer(path) {
        return hasAnySegment(path, CONTAINER_SEGMENTS)
            || endsWithTerm(path, "brewing_stand")
            || endsWithTerm(path, "shulker_box")
            || ["enderchest", "lockedchest", "chiseled_bookshelf", "decorated_pot"].includes(path)
            || path.startsWith("shulkerbox");
    }

    function isWeaponOrTool(path) {
        return endsWithAnyTerm(path, ["sword", "pickaxe", "axe", "shovel", "hoe", "spear"])
            || [
                "bow", "crossbow", "trident", "mace", "shears", "fishing_rod", "flint_and_steel",
                "brush", "debug_stick", "glow_stick", "clock", "compass", "recovery_compass",
                "lodestone_compass", "lodestonecompass", "spyglass", "empty_map", "emptylocatormap",
                "emptymap", "filled_map", "map", "goat_horn",
            ].includes(path);
    }

    function isMaterial(path) {
        if (MATERIAL_EXACT_IDS.has(path) || endsWithAnyTerm(path, MATERIAL_ENDINGS)) return true;
        if (path.endsWith("_ore") && hasAnySegment(path, RESOURCE_BLOCK_SEGMENTS)) return true;
        return path.endsWith("_block") && hasAnySegment(path, RESOURCE_BLOCK_SEGMENTS);
    }

    function isBlock(path) {
        if (BLOCK_EXACT_IDS.has(path) || endsWithAnyTerm(path, BLOCK_ENDINGS)) return true;
        return /^(?:waxed_)?(?:(?:exposed|weathered|oxidized)_)?(?:chiseled_|cut_)?copper$/.test(path)
            || ["blackstone", "cobblestone", "sandstone"].some(suffix => path.endsWith(suffix))
            || path.endsWith("fence")
            || path.endsWith("flower")
            || path.includes("coral")
            || path.startsWith("chiseled_")
            || endsWithAnyTerm(path, [
                "campfire", "catalyst", "daisy", "dandelion", "eyeblossom", "fern", "lightning_rod", "orchid",
                "blossom", "rose", "sand", "sculk_shrieker", "sculk_vein", "seagrass", "snow_layer", "soil",
                "spawner", "sprouts", "suspicious_gravel", "suspicious_sand", "tulip", "vine",
            ])
            || path.startsWith("colored_torch_")
            || path.startsWith("deprecated_purpur_block_")
            || path.startsWith("light_block_")
            || path.startsWith("polished_")
            || /^stone_(?:block_)?slab\d+$/.test(path);
    }

    const ITEM_BROWSER_RULES = {
        armor: isArmor,
        food: isFood,
        consumables: isConsumable,
        redstone: isRedstone,
        transport: isTransport,
        containers: isContainer,
        spawn_eggs: path => path === "spawn_egg" || path.endsWith("_spawn_egg"),
        weapons: isWeaponOrTool,
        materials: isMaterial,
        blocks: isBlock,
    };

    // Die Positivliste addableIds ist die fachliche Grenze. blockOnlyIds bleibt
    // als defensive Kompatibilitätsprüfung für ältere externe Item-Datenbanken,
    // die noch keine Positivliste liefern.
    function isBlockOnly(blockOnlyIds, id) {
        return Boolean(blockOnlyIds && typeof blockOnlyIds.has === "function" && blockOnlyIds.has(String(id || "").toLowerCase()));
    }

    function isRegisteredBlockItem(blockItemIds, id) {
        return Boolean(blockItemIds && typeof blockItemIds.has === "function" && blockItemIds.has(String(id || "").toLowerCase()));
    }

    function isAddable(addableIds, id) {
        return !addableIds
            || typeof addableIds.has !== "function"
            || addableIds.has(String(id || "").toLowerCase());
    }

    function browserEntries(itemsDb, itemVariantsForId = null) {
        const entries = [];
        for (const [id, names] of Object.entries(itemsDb || {})) {
            const variants = typeof itemVariantsForId === "function" ? itemVariantsForId(id) : [];
            if (Array.isArray(variants) && variants.length) {
                variants.forEach(variant => {
                    entries.push([
                        id,
                        Array.isArray(variant?.names) ? variant.names : names,
                        {
                            damage: Number(variant?.damage),
                            searchIds: Array.isArray(variant?.searchIds) ? variant.searchIds : [],
                        },
                    ]);
                });
                continue;
            }
            entries.push([id, names, null]);
        }
        return entries;
    }

    function autocompleteMatches(itemsDb, query, limit = 10, blockOnlyIds = null, addableIds = null, itemVariantsForId = null) {
        const normalized = String(query || "").toLowerCase().trim();
        if (!normalized) return [];
        const matches = [];
        for (const [id, names, metadata] of browserEntries(itemsDb, itemVariantsForId)) {
            if (!isAddable(addableIds, id) || isBlockOnly(blockOnlyIds, id)) continue;
            if (itemMatchesQuery(id, names, normalized, metadata)) {
                matches.push({
                    id,
                    de: names[0],
                    en: names[1],
                    ...(Number.isInteger(metadata?.damage) ? { damage: metadata.damage } : {}),
                    searchIds: metadata?.searchIds || [],
                });
            }
        }
        const exactIndex = matches.findIndex(item => (
            item.id.toLowerCase() === normalized
            || item.searchIds.some(value => String(value || "").toLowerCase() === normalized)
        ));
        if (exactIndex > 0) {
            const [exact] = matches.splice(exactIndex, 1);
            matches.unshift(exact);
        }
        return matches.slice(0, limit);
    }

    function ruleCategories(id) {
        const lower = String(id || "").toLowerCase();
        const cached = ITEM_CATEGORY_CACHE.get(lower);
        if (cached) return cached;

        const path = itemPath(lower);
        const selected = new Set(ITEM_BROWSER_CATEGORY_ORDER.filter(category => ITEM_BROWSER_RULES[category](path)));
        const override = ITEM_CATEGORY_OVERRIDES.get(path);
        for (const category of override?.remove || []) selected.delete(category);
        for (const category of override?.add || []) selected.add(category);
        if (REDSTONE_OVERRIDE_IDS.has(path)) selected.add("redstone");
        const categories = ITEM_BROWSER_CATEGORY_ORDER.filter(category => selected.has(category));
        const result = Object.freeze(categories);
        ITEM_CATEGORY_CACHE.set(lower, result);
        return result;
    }

    function itemBrowserCategories(id, blockItemIds = null) {
        const lower = String(id || "").toLowerCase();
        const categories = [...ruleCategories(lower)];
        if (isRegisteredBlockItem(blockItemIds, lower) && !categories.includes("blocks")) categories.push("blocks");
        if (!categories.length) categories.push("other");
        if (COMMON_ITEM_IDS.has(lower)) categories.unshift("common");
        return Object.freeze(categories);
    }

    // Rückwärtskompatible Hauptkategorie für Sortierung und Einzelanzeigen.
    // Filter verwenden itemBrowserCategories(), damit sinnvolle Überschneidungen erhalten bleiben.
    function itemBrowserCategory(id, blockItemIds = null) {
        return itemBrowserCategories(id, blockItemIds).find(category => category !== "common") || "other";
    }

    function itemMatchesBrowserCategory(id, selected, blockItemIds = null) {
        if (!selected || selected === "all") return true;
        return itemBrowserCategories(id, blockItemIds).includes(selected);
    }

    function rankedMatch(lower, ranks, fallback = 999) {
        return ranks.find(([needle]) => lower.includes(needle))?.[1] || fallback;
    }

    function itemBrowserTypeRank(id, category = "") {
        const lower = itemPath(id);
        const effectiveCategory = ITEM_BROWSER_CATEGORY_ORDER.includes(category) ? category : itemBrowserCategory(id);
        if (effectiveCategory === "armor") {
            return rankedMatch(lower, [
                ["helmet", 110],
                ["chestplate", 120],
                ["leggings", 130],
                ["boots", 140],
                ["shield", 150],
                ["elytra", 160],
                ["horse_armor", 170],
                ["nautilus_armor", 171],
                ["wolf_armor", 172],
                ["harness", 173],
            ]);
        }
        if (effectiveCategory === "food") {
            return rankedMatch(lower, [
                ["apple", 210],
                ["bread", 220],
                ["beef", 230],
                ["porkchop", 231],
                ["chicken", 232],
                ["mutton", 233],
                ["rabbit", 234],
                ["cod", 240],
                ["salmon", 241],
                ["potato", 250],
                ["carrot", 251],
                ["beetroot", 252],
                ["melon", 253],
                ["berries", 254],
                ["kelp", 255],
                ["cookie", 260],
                ["pie", 261],
                ["stew", 270],
                ["soup", 271],
            ]);
        }
        if (effectiveCategory === "consumables") {
            return rankedMatch(lower, [
                ["potion", 280],
                ["totem", 281],
                ["bucket", 282],
                ["experience_bottle", 283],
                ["firework", 284],
                ["ender_pearl", 285],
            ]);
        }
        if (effectiveCategory === "materials") {
            return rankedMatch(lower, [
                ["diamond", 310],
                ["emerald", 311],
                ["ingot", 320],
                ["nugget", 321],
                ["coal", 330],
                ["lapis", 331],
                ["redstone", 332],
                ["quartz", 333],
                ["amethyst", 334],
                ["stick", 340],
                ["string", 341],
                ["leather", 342],
                ["paper", 350],
                ["book", 351],
                ["pearl", 360],
                ["blaze", 361],
                ["bone", 370],
                ["gunpowder", 371],
            ]);
        }
        if (effectiveCategory === "redstone") return 380;
        if (effectiveCategory === "transport") return rankedMatch(lower, [["boat", 390], ["raft", 391], ["minecart", 392], ["rail", 393]], 399);
        if (effectiveCategory === "containers") return 395;
        if (effectiveCategory === "spawn_eggs") return 398;
        if (effectiveCategory === "blocks") {
            return rankedMatch(lower, [
                ["ore", 410],
                ["stone", 420],
                ["dirt", 421],
                ["sand", 422],
                ["log", 430],
                ["wood", 431],
                ["planks", 432],
                ["leaves", 433],
                ["brick", 440],
                ["glass", 441],
                ["wool", 450],
                ["concrete", 451],
                ["terracotta", 452],
                ["slab", 460],
                ["stairs", 461],
                ["fence", 462],
                ["door", 463],
                ["trapdoor", 464],
                ["wall", 465],
                ["button", 470],
                ["pressure_plate", 471],
                ["block", 480],
            ]);
        }
        if (effectiveCategory !== "weapons") return 999;
        return rankedMatch(lower, [
            ["pickaxe", 20],
            ["sword", 10],
            ["_axe", 30],
            ["shovel", 40],
            ["hoe", 50],
            ["crossbow", 61],
            ["bow", 60],
            ["trident", 62],
            ["shears", 70],
            ["fishing_rod", 80],
            ["flint_and_steel", 90],
            ["mace", 91],
            ["spear", 92],
        ]);
    }

    function compareBrowserItems(a, b, sortMode, category) {
        const leftName = localizedNamePair(a[1][0], a[1][1]).primary;
        const rightName = localizedNamePair(b[1][0], b[1][1]).primary;
        const nameCompare = window.MCBEI18n?.compare?.(leftName, rightName)
            ?? leftName.localeCompare(rightName, undefined, { sensitivity: "base" });
        if (sortMode === "type" && !["all", "common"].includes(category)) {
            const rankCompare = itemBrowserTypeRank(a[0], category) - itemBrowserTypeRank(b[0], category);
            if (rankCompare !== 0) return rankCompare;
        }
        if (sortMode === "type" && category !== "all") {
            const idCompare = a[0].localeCompare(b[0], undefined, { sensitivity: "base" });
            if (idCompare !== 0) return idCompare;
        }
        return nameCompare
            || a[0].localeCompare(b[0], undefined, { sensitivity: "base" })
            || (Number(a[2]?.damage) || 0) - (Number(b[2]?.damage) || 0);
    }

    function browserItems(itemsDb, {
        query = "", category = "all", sortMode = "type", blockOnlyIds = null, addableIds = null, blockItemIds = null,
        itemVariantsForId = null,
    } = {}) {
        const q = String(query || "").toLowerCase().trim();
        let items = browserEntries(itemsDb, itemVariantsForId).filter(([id]) => (
            isAddable(addableIds, id)
            && !isBlockOnly(blockOnlyIds, id)
            && itemMatchesBrowserCategory(id, category, blockItemIds)
        ));
        if (q) {
            items = items.filter(([id, names, metadata]) => itemMatchesQuery(id, names, q, metadata));
        }
        items.sort((a, b) => compareBrowserItems(a, b, sortMode, category));
        return items;
    }

    // Chunk-Rendering: Die Suche filtert immer den vollen Datensatz im Speicher;
    // nur das DOM wird in Portionen aufgebaut, damit das Öffnen des Browsers
    // und breite Suchergebnisse nicht ~2000 Karten auf einmal erzeugen.
    const BROWSER_RENDER_CHUNK_SIZE = 200;

    function browserRenderChunkPlan({ totalCount = 0, renderedCount = 0, chunkSize = BROWSER_RENDER_CHUNK_SIZE } = {}) {
        const total = Math.max(0, Number(totalCount) || 0);
        const start = Math.min(total, Math.max(0, Number(renderedCount) || 0));
        const size = Math.max(1, Number(chunkSize) || BROWSER_RENDER_CHUNK_SIZE);
        const end = Math.min(total, start + size);
        const remaining = total - end;
        return {
            start,
            end,
            remaining,
            hasMore: remaining > 0,
            buttonLabel: remaining > 0 ? t("Weitere {count} von {remaining} anzeigen", { count: Math.min(remaining, size), remaining }) : "",
        };
    }

    function escapeHtml(value) {
        if (window.MCBEHtmlUtils?.escapeHtml) return window.MCBEHtmlUtils.escapeHtml(value ?? "");
        return String(value ?? "")
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
    }

    function escapeAttr(value) {
        if (window.MCBEHtmlUtils?.escapeAttr) return window.MCBEHtmlUtils.escapeAttr(value ?? "");
        return escapeHtml(value);
    }

    function browserCountText({ count = 0, categoryLabel = "Alle Kategorien", sortMode = "type" } = {}) {
        const itemCount = window.MCBEI18n?.tp?.(count, "{count} Item", "{count} Items") || `${count} Item${count !== 1 ? "s" : ""}`;
        return `${itemCount} · ${t(categoryLabel || "Alle Kategorien")} · ${sortMode === "type" ? t("Typ") : "A-Z"}`;
    }

    function browserEmptyHtml() {
        return `<div class="no-backups">${t("Keine Items gefunden.")}</div>`;
    }

    function itemIconContent({ iconUrl = "", fallbackIcon = "□", iconTint = "", lazy = false } = {}) {
        const tintAttr = iconTint ? ` data-icon-tint="${escapeAttr(iconTint)}"` : "";
        const loadingAttr = lazy ? ' loading="lazy"' : "";
        return iconUrl
            ? `<img src="${escapeAttr(iconUrl)}" alt=""${loadingAttr} data-icon-fallback="${escapeAttr(fallbackIcon || "□")}"${tintAttr}>`
            : escapeHtml(fallbackIcon || "□");
    }

    function technicalItemLabel(id, damage) {
        return damage !== null && damage !== undefined && damage !== "" && Number.isInteger(Number(damage))
            ? `${id} · ${t("Datenwert")} ${Number(damage)}`
            : id;
    }

    function availabilityBadgeHtml(availability = null) {
        if (!availability || typeof availability !== "object") return "";
        const key = String(availability.key || "").trim();
        const label = String(availability.label || "").trim();
        if (!key || !label) return "";
        const description = String(availability.description || "").trim();
        const ariaLabel = String(availability.ariaLabel || [label, description].filter(Boolean).join(". "));
        const titleAttribute = description ? ` title="${escapeAttr(description)}"` : "";
        return `<span class="item-availability-badge" data-item-availability="${escapeAttr(key)}"${titleAttribute} aria-label="${escapeAttr(ariaLabel)}">${escapeHtml(label)}</span>`;
    }

    function autocompleteItemHtml({ id = "", de = "", en = "", damage = null } = {}, icon = {}, availability = null) {
        const names = localizedItemNamePair(de, en);
        return `
                    <span class="autocomplete-emoji">${itemIconContent(icon)}</span>
                    <span class="autocomplete-name"><strong>${escapeHtml(names.primary)}</strong>${names.secondary ? ` (${escapeHtml(names.secondary)})` : ""}</span>
                    ${availabilityBadgeHtml(availability)}
                    <span class="item-id">${escapeHtml(technicalItemLabel(id, damage))}</span>
                `;
    }

    function autocompleteItemElement(item = {}, icon = {}, availability = null, doc = null) {
        // Keep the previous (item, icon, document) calling convention usable for
        // isolated consumers while allowing the controller to pass a badge model.
        const availabilityIsDocument = availability && typeof availability.createElement === "function";
        const documentObj = doc || (availabilityIsDocument ? availability : document);
        const badge = availabilityIsDocument ? null : availability;
        const row = documentObj.createElement("div");
        row.className = "autocomplete-item";
        row.innerHTML = autocompleteItemHtml(item, icon, badge);
        return row;
    }

    function browserItemCardHtml({ id = "", names = [], damage = null, iconUrl = "", fallbackIcon = "□", iconTint = "", availability = null } = {}) {
        const localizedNames = localizedItemNamePair(names[0], names[1]);
        const iconHtml = itemIconContent({ iconUrl, fallbackIcon, iconTint, lazy: true });
        return `
                <div class="browser-item-icon">${iconHtml}</div>
                <div class="browser-item-name">${escapeHtml(localizedNames.primary)}</div>
                ${availabilityBadgeHtml(availability)}
                <div class="browser-item-id">${escapeHtml(technicalItemLabel(id, damage))}</div>
            `;
    }

    function browserItemCardElement(model = {}, doc = document) {
        const card = doc.createElement("div");
        card.className = "browser-item";
        card.innerHTML = browserItemCardHtml(model);
        return card;
    }

    window.MCBEItemBrowserLogic = {
        autocompleteMatches,
        autocompleteItemElement,
        autocompleteItemHtml,
        availabilityBadgeHtml,
        browserCountText,
        browserItemCardElement,
        browserEmptyHtml,
        browserItemCardHtml,
        browserRenderChunkPlan,
        itemBrowserCategories,
        itemBrowserCategory,
        itemMatchesBrowserCategory,
        itemBrowserTypeRank,
        compareBrowserItems,
        browserItems,
    };
}());
