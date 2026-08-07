(function () {
    "use strict";

    const CATEGORY_PRESENTATION = Object.freeze({
        technical: Object.freeze({
            label: "Technisch",
            description: "Technischer Block oder Gegenstand außerhalb des normalen Kreativinventars.",
        }),
        command_only: Object.freeze({
            label: "Befehlsitem",
            description: "Nicht im Kreativinventar gelistet; über Befehle oder Blockauswahl erhältlich.",
        }),
        education: Object.freeze({
            label: "Education",
            description: "Für Welten mit aktivierten Education-Funktionen vorgesehen.",
        }),
        generated_state: Object.freeze({
            label: "Zustandsblock",
            description: "Entsteht als Spielzustand und ist nicht als regulärer Gegenstand erhältlich.",
        }),
        legacy: Object.freeze({
            label: "Legacy",
            description: "Historischer Gegenstand für alte Welten; nicht regulär erhältlich.",
        }),
        creative: Object.freeze({
            label: "Kreativ",
            description: "Im Kreativinventar verfügbar, im normalen Überlebensmodus nicht als Gegenstand erhältlich.",
        }),
    });

    function normalizedItemId(value) {
        return String(value || "").trim().toLowerCase();
    }

    function normalizedDamage(value) {
        if (value === null || value === undefined || value === "") return null;
        const damage = Number(value);
        return Number.isInteger(damage) ? damage : null;
    }

    function createItemAvailabilityCatalog(initialPayload = {}) {
        let categoriesByItemId = new Map();
        let categoriesByVariant = new Map();
        let sourceMetadata = {};

        function replace(payload = {}) {
            const nextItems = new Map();
            const nextVariants = new Map();
            const classifications = payload && typeof payload.classifications === "object"
                ? payload.classifications
                : {};

            Object.entries(classifications || {}).forEach(([category, itemIds]) => {
                if (!CATEGORY_PRESENTATION[category] || !Array.isArray(itemIds)) return;
                itemIds.forEach(rawItemId => {
                    const itemId = normalizedItemId(rawItemId);
                    if (itemId) nextItems.set(itemId, category);
                });
            });

            const variants = payload && typeof payload.variants === "object" ? payload.variants : {};
            Object.entries(variants || {}).forEach(([rawItemId, rawDataValues]) => {
                const itemId = normalizedItemId(rawItemId);
                if (!itemId || !rawDataValues || typeof rawDataValues !== "object") return;
                const categoryByDamage = new Map();
                Object.entries(rawDataValues).forEach(([rawDamage, category]) => {
                    const damage = normalizedDamage(rawDamage);
                    if (damage === null || !CATEGORY_PRESENTATION[category]) return;
                    categoryByDamage.set(damage, category);
                });
                if (categoryByDamage.size) nextVariants.set(itemId, categoryByDamage);
            });

            categoriesByItemId = nextItems;
            categoriesByVariant = nextVariants;
            sourceMetadata = {
                schemaVersion: Number(payload?.schema_version) || 0,
                sourceRelease: String(payload?.source_release || ""),
                reviewedAt: String(payload?.reviewed_at || ""),
                references: Array.isArray(payload?.references) ? payload.references.slice() : [],
            };
        }

        function categoryFor(itemId, damage = null) {
            const normalizedId = normalizedItemId(itemId);
            if (!normalizedId) return null;
            const normalizedDataValue = normalizedDamage(damage);
            if (normalizedDataValue !== null) {
                const variantCategory = categoriesByVariant.get(normalizedId)?.get(normalizedDataValue);
                if (variantCategory) return variantCategory;
            }
            return categoriesByItemId.get(normalizedId) || null;
        }

        function badgeFor(itemId, damage = null) {
            const key = categoryFor(itemId, damage);
            const presentation = key ? CATEGORY_PRESENTATION[key] : null;
            if (!presentation) return null;
            const translate = window.t || ((text, params) => String(text).replace(
                /\{(\w+)\}/g,
                (match, keyName) => params && keyName in params ? String(params[keyName]) : match,
            ));
            const label = translate(presentation.label);
            const description = translate(presentation.description);
            return {
                key,
                label,
                description,
                ariaLabel: translate("Klassifikation: {label}. {description}", { label, description }),
            };
        }

        function metadata() {
            return {
                ...sourceMetadata,
                references: sourceMetadata.references.slice(),
            };
        }

        replace(initialPayload);
        return { badgeFor, categoryFor, metadata, replace };
    }

    window.MCBEItemAvailability = {
        categoryKeys: () => Object.keys(CATEGORY_PRESENTATION),
        createItemAvailabilityCatalog,
    };
}());
