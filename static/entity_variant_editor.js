(function () {
    "use strict";

    const t = window.t || (text => text);

    const AXOLOTL_ITEM_IDS = new Set([
        "minecraft:axolotl_bucket",
        "minecraft:bucketaxolotl",
    ]);
    const TROPICAL_FISH_ITEM_IDS = new Set([
        "minecraft:tropical_fish_bucket",
        "minecraft:buckettropical",
        "minecraft:bucketcustomfish",
    ]);

    const AXOLOTL_COLORS = [
        { value: 0, de: "Leuzistisch", en: "Leucistic" },
        { value: 1, de: "Türkis", en: "Cyan" },
        { value: 2, de: "Gold", en: "Gold" },
        { value: 3, de: "Wild/Braun", en: "Wild/Brown" },
        { value: 4, de: "Blau", en: "Blue" },
    ];
    const AXOLOTL_AGES = [
        { value: "adult", de: "Erwachsen", en: "Adult" },
        { value: "baby", de: "Jungtier", en: "Baby" },
    ];
    const TROPICAL_FISH_PATTERNS = [
        { value: "0:0", variant: 0, markVariant: 0, de: "Kabeljau", en: "Kob" },
        { value: "0:1", variant: 0, markVariant: 1, de: "SunStreak", en: "SunStreak" },
        { value: "0:2", variant: 0, markVariant: 2, de: "Snooper", en: "Snooper" },
        { value: "0:3", variant: 0, markVariant: 3, de: "Dasher/Flitzer", en: "Dasher" },
        { value: "0:4", variant: 0, markVariant: 4, de: "Brinely", en: "Brinely" },
        { value: "0:5", variant: 0, markVariant: 5, de: "Spotty", en: "Spotty" },
        { value: "1:0", variant: 1, markVariant: 0, de: "Flopper", en: "Flopper" },
        { value: "1:1", variant: 1, markVariant: 1, de: "Stripey", en: "Stripey" },
        { value: "1:2", variant: 1, markVariant: 2, de: "Glitter", en: "Glitter" },
        { value: "1:3", variant: 1, markVariant: 3, de: "Blockfish", en: "Blockfish" },
        { value: "1:4", variant: 1, markVariant: 4, de: "Betty", en: "Betty" },
        { value: "1:5", variant: 1, markVariant: 5, de: "Clayfish", en: "Clayfish" },
    ];
    const TROPICAL_FISH_COLORS = [
        { value: 0, de: "Weiß", en: "White" },
        { value: 1, de: "Orange", en: "Orange" },
        { value: 2, de: "Magenta", en: "Magenta" },
        { value: 3, de: "Himmel", en: "Sky" },
        { value: 4, de: "Gelb", en: "Yellow" },
        { value: 5, de: "Hellgrün", en: "Lime" },
        { value: 6, de: "Rose", en: "Rose" },
        { value: 7, de: "Grau", en: "Gray" },
        { value: 8, de: "Silber", en: "Silver" },
        { value: 9, de: "Aquamarin", en: "Teal" },
        { value: 10, de: "Pflaumenblau", en: "Plum" },
        { value: 11, de: "Blau", en: "Blue" },
        { value: 12, de: "Braun", en: "Brown" },
        { value: 13, de: "Grün", en: "Green" },
        { value: 14, de: "Rot", en: "Red" },
        { value: 15, de: "Schwarz", en: "Black" },
    ];

    function normalizedName(value) {
        return String(value || "").trim().toLowerCase();
    }

    function localizedLabel(entry) {
        const pair = window.MCBEI18n?.localizedPair?.(entry.de, entry.en);
        const primary = pair?.primary || entry.de || entry.en || "";
        return pair?.secondary ? `${primary} (${pair.secondary})` : primary;
    }

    function optionsFor(entries) {
        return entries.map(entry => ({
            value: String(entry.value),
            label: localizedLabel(entry),
        }));
    }

    function kindForItemName(itemName) {
        const normalized = normalizedName(itemName);
        if (AXOLOTL_ITEM_IDS.has(normalized)) return "axolotl";
        if (TROPICAL_FISH_ITEM_IDS.has(normalized)) return "tropical_fish";
        return "";
    }

    function integerInRange(value, min, max) {
        const parsed = Number(value);
        return Number.isInteger(parsed) && parsed >= min && parsed <= max ? parsed : null;
    }

    function editorModel({ item = null, itemName = "" } = {}) {
        const kind = kindForItemName(itemName);
        if (!kind) return { visible: false, editable: false, kind: "" };

        const sameItem = Boolean(item && normalizedName(item.name) === normalizedName(itemName));
        const source = sameItem && item?.entity_variant && typeof item.entity_variant === "object"
            ? item.entity_variant
            : null;
        const backendAllowsEdit = source?.can_edit === true;

        if (kind === "axolotl") {
            const variant = integerInRange(source?.variant, 0, 4);
            const editable = Boolean(source && variant !== null && backendAllowsEdit);
            const state = source
                ? "captured"
                : sameItem && item?.entity_variant_state === "unresolved"
                    ? "unresolved"
                    : "generic";
            return {
                visible: true,
                editable,
                kind,
                state,
                title: t("Axolotl im Eimer"),
                note: state === "generic"
                    ? t("Gültiger Kreativ-Eimer ohne gespeichertes Tier. Minecraft bestimmt die Variante beim Aussetzen.")
                    : state === "unresolved"
                        ? t("Vorhandene Axolotl-Daten konnten nicht sicher aufgelöst werden und bleiben unverändert.")
                        : editable
                            ? t("Farbe und Alter werden im vorhandenen Entity-NBT geändert; alle übrigen Daten bleiben erhalten.")
                            : t("Die gespeicherte Variante ist erkennbar, aber ohne vollständige numerische Entity-Daten nicht sicher bearbeitbar."),
                variant,
                isBaby: Boolean(source?.is_baby),
            };
        }

        const variant = integerInRange(source?.variant, 0, 1);
        const markVariant = integerInRange(source?.mark_variant, 0, 5);
        const color = integerInRange(source?.color, 0, 15);
        const color2 = integerInRange(source?.color2, 0, 15);
        const editable = Boolean(
            source
            && variant !== null
            && markVariant !== null
            && color !== null
            && color2 !== null
            && backendAllowsEdit
        );
        return {
            visible: true,
            editable,
            kind,
            title: t("Tropenfisch im Eimer"),
            note: editable
                ? t("Form, Muster und Farben werden im vorhandenen Entity-NBT geändert; alle übrigen Daten bleiben erhalten.")
                : t("Eine konkrete Variante kann nur bei einem bereits gefangenen Tropenfisch mit vollständigen Entity-Daten geändert werden."),
            variant: variant ?? 0,
            markVariant: markVariant ?? 0,
            color: color ?? 0,
            color2: color2 ?? 0,
        };
    }

    function editFromValues({
        kind = "",
        axolotlVariant = 0,
        axolotlAge = "adult",
        tropicalPattern = "0:0",
        tropicalColor = 0,
        tropicalColor2 = 0,
    } = {}) {
        if (kind === "axolotl") {
            const variant = integerInRange(axolotlVariant, 0, 4);
            if (variant === null || !["adult", "baby"].includes(String(axolotlAge))) return null;
            return {
                kind,
                variant,
                is_baby: String(axolotlAge) === "baby",
            };
        }
        if (kind !== "tropical_fish") return null;
        const pattern = TROPICAL_FISH_PATTERNS.find(entry => entry.value === String(tropicalPattern));
        const color = integerInRange(tropicalColor, 0, 15);
        const color2 = integerInRange(tropicalColor2, 0, 15);
        if (!pattern || color === null || color2 === null) return null;
        return {
            kind,
            variant: pattern.variant,
            mark_variant: pattern.markVariant,
            color,
            color2,
        };
    }

    function sourceEditFromModel(model = {}) {
        if (!model.editable) return null;
        if (model.kind === "axolotl") {
            return {
                kind: "axolotl",
                variant: Number(model.variant),
                is_baby: Boolean(model.isBaby),
            };
        }
        if (model.kind === "tropical_fish") {
            return {
                kind: "tropical_fish",
                variant: Number(model.variant),
                mark_variant: Number(model.markVariant),
                color: Number(model.color),
                color2: Number(model.color2),
            };
        }
        return null;
    }

    function editsEqual(left, right) {
        if (!left || !right || left.kind !== right.kind) return false;
        if (left.kind === "axolotl") {
            return Number(left.variant) === Number(right.variant)
                && Boolean(left.is_baby) === Boolean(right.is_baby);
        }
        return Number(left.variant) === Number(right.variant)
            && Number(left.mark_variant) === Number(right.mark_variant)
            && Number(left.color) === Number(right.color)
            && Number(left.color2) === Number(right.color2);
    }

    function updatedEntityVariantMetadata(source = {}, edit = null) {
        if (!edit || !source || typeof source !== "object") return source;
        const updated = JSON.parse(JSON.stringify(source));
        if (edit.kind === "axolotl") {
            const color = AXOLOTL_COLORS.find(entry => entry.value === Number(edit.variant));
            if (!color) return source;
            updated.entity_id = "minecraft:axolotl";
            updated.variant = color.value;
            updated.key = ["lucy", "cyan", "gold", "wild", "blue"][color.value];
            updated.label_de = color.de;
            updated.label_en = color.en;
            updated.display_name_de = [
                "Leuzistischer Axolotl",
                "Türkiser Axolotl",
                "Gold-Axolotl",
                "Brauner/Wilder Axolotl",
                "Blauer Axolotl",
            ][color.value];
            updated.display_name_en = [
                "Leucistic Axolotl",
                "Cyan Axolotl",
                "Gold Axolotl",
                "Wild/Brown Axolotl",
                "Blue Axolotl",
            ][color.value];
            updated.is_baby = Boolean(edit.is_baby);
            updated.adult_icon_key = `mcbe:axolotl_${updated.key}`;
            updated.baby_icon_key = `mcbe:axolotl_${updated.key}_baby`;
            updated.icon_key = updated.is_baby ? updated.baby_icon_key : updated.adult_icon_key;
            updated.can_edit = true;
            return updated;
        }
        if (edit.kind !== "tropical_fish") return source;
        const pattern = TROPICAL_FISH_PATTERNS.find(entry => (
            entry.variant === Number(edit.variant)
            && entry.markVariant === Number(edit.mark_variant)
        ));
        const color = TROPICAL_FISH_COLORS.find(entry => entry.value === Number(edit.color));
        const color2 = TROPICAL_FISH_COLORS.find(entry => entry.value === Number(edit.color2));
        if (!pattern || !color || !color2) return source;
        const germanPattern = pattern.value === "0:3"
            ? (color.value === color2.value ? "Dasher" : "Flitzer")
            : pattern.de;
        const germanColors = color.value === color2.value ? color.de : `${color.de}/${color2.de}`;
        const englishColors = color.value === color2.value ? color.en : `${color.en}/${color2.en}`;
        updated.entity_id = "minecraft:tropical_fish";
        updated.variant = pattern.variant;
        updated.mark_variant = pattern.markVariant;
        updated.color = color.value;
        updated.color2 = color2.value;
        updated.key = `${pattern.en}_${color.en}_${color2.en}`.toLowerCase().replace(/[^a-z0-9]+/g, "_");
        updated.label_de = `${germanPattern}, ${germanColors}`;
        updated.label_en = `${pattern.en}, ${englishColors}`;
        updated.display_name_de = `Tropenfisch: ${updated.label_de}`;
        updated.display_name_en = `Tropical Fish: ${updated.label_en}`;
        updated.fields = [
            {
                key: "BodyID",
                label_de: "Körperform",
                label_en: "Body",
                raw: `item.tropicalBody${pattern.en.replace("SunStreak", "Sunstreak")}${color.value === color2.value ? "Single" : "Multi"}.name`,
                display_de: germanPattern,
                display_en: pattern.en,
            },
            {
                key: "ColorID",
                label_de: "Farbe 1",
                label_en: "Color 1",
                raw: `item.tropicalColor${color.en}.name`,
                display_de: color.de,
                display_en: color.en,
            },
            {
                key: "Color2ID",
                label_de: "Farbe 2",
                label_en: "Color 2",
                raw: `item.tropicalColor${color2.en}.name`,
                display_de: color2.de,
                display_en: color2.en,
            },
        ];
        updated.source = "BodyID, ColorID, Color2ID";
        updated.can_edit = true;
        return updated;
    }

    window.MCBEEntityVariantEditor = {
        axolotlAgeOptions: () => optionsFor(AXOLOTL_AGES),
        axolotlColorOptions: () => optionsFor(AXOLOTL_COLORS),
        genericAxolotlAgeOptions: () => [
            { value: "adult", label: t("Erwachsen beim Aussetzen") },
        ],
        genericAxolotlColorOptions: () => [
            { value: "generic", label: t("Zufällig beim Aussetzen") },
        ],
        tropicalFishColorOptions: () => optionsFor(TROPICAL_FISH_COLORS),
        tropicalFishPatternOptions: () => optionsFor(TROPICAL_FISH_PATTERNS),
        editFromValues,
        editorModel,
        editsEqual,
        kindForItemName,
        sourceEditFromModel,
        updatedEntityVariantMetadata,
    };
}());
