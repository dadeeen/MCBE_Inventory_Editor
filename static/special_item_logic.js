(function () {
    "use strict";
    const t = (value, args) => window.MCBEI18n?.t(value, args) || value;
    const clone = value => JSON.parse(JSON.stringify(value));
    const ORIGIN_FIELDS = ["source_slot", "source_player_key", "source_world_path", "source_container", "source_item_digest", "replace_original_nbt", "nbt_view"];
    const LABELS = {
        shulker: "Inhalte bearbeiten", bundle: "Inhalte bearbeiten", book: "Buch bearbeiten",
        fireworks: "Feuerwerk bearbeiten", firework_star: "Feuerwerksstern bearbeiten", banner: "Banner bearbeiten",
    };

    function sameUserFields(before, after) {
        if (!before || !after) return before === after;
        const fields = item => [item.slot, item.name, item.count, item.damage || 0, item.display_name || "", item.lore || [], item.enchantments || [], item.entity_variant_edit || null, item.special_edit || null];
        return JSON.stringify(fields(before)) === JSON.stringify(fields(after));
    }

    function changeLabel(before, after) {
        if (!after?.special_edit || JSON.stringify(before?.special_edit) === JSON.stringify(after.special_edit)) return "";
        const kind = after.special_edit.kind;
        if (["bundle", "shulker"].includes(kind)) return t("Container-Inhalte geändert");
        if (kind === "book") return t("Buchinhalt geändert");
        if (kind === "banner") return t("Bannermuster geändert");
        return t("Feuerwerkseffekte geändert");
    }

    function createModel(schema, catalog) {
        const kind = item => schema.item_kinds[String(item?.name || "").trim().toLowerCase()] || "";
        const label = item => t(LABELS[kind(item)] || "Spezialdaten bearbeiten");
        function data(item) {
            if (item.special_edit?.kind === kind(item)) return clone(item.special_edit.data);
            if (item.special_item?.kind === kind(item) && item.special_item.editable) return clone(item.special_item.data);
            if (["bundle", "shulker"].includes(kind(item))) return { items: [] };
            if (kind(item) === "book") return item.name === "minecraft:written_book" ? { pages: [], title: "", author: "" } : { pages: [] };
            if (kind(item) === "banner") return { patterns: [] };
            return kind(item) === "fireworks" ? { flight: 1, explosions: [] } : { explosions: [] };
        }
        function editable(item) {
            return Boolean(kind(item)) && item.special_item?.editable !== false && !item.item_tag_opaque;
        }
        function searchContents(item, matches) {
            const hits = [];
            let remaining = schema.limits.nodes;
            let incomplete = false;
            function visit(parent, path) {
                if (!["bundle", "shulker"].includes(kind(parent))) return;
                if (!editable(parent) || path.length >= schema.limits.depth) { incomplete = true; return; }
                // Search the current draft without cloning each nested subtree.
                const value = parent.special_edit?.kind === kind(parent) ? parent.special_edit.data
                    : parent.special_item?.data;
                for (const child of value?.items || []) {
                    if (--remaining < 0) { incomplete = true; return; }
                    const nextPath = [...path, child];
                    if (matches(child)) hits.push({ item: child, path: nextPath });
                    visit(child, nextPath);
                    if (remaining < 0) return;
                }
            }
            visit(item, []);
            return { hits, incomplete };
        }
        function weight(item, depth = 0) {
            if (depth >= schema.limits.depth || kind(item) === "shulker") return null;
            if (kind(item) === "bundle") {
                if (!editable(item) || Number(item.count) !== 1) return null;
                const inside = contentWeight(data(item).items, depth + 1);
                return inside === null ? null : inside + 4;
            }
            if (!catalog.hasVerifiedStackLimit(item.name)) return null;
            const maximum = catalog.getMaxStack(item.name);
            return [1, 16, 64].includes(maximum) ? Number(item.count) * 64 / maximum : null;
        }
        function contentWeight(items, depth = 1) {
            let result = 0;
            for (const item of items) {
                const value = weight(item, depth);
                if (value === null) return null;
                result += value;
            }
            return result;
        }
        function validate(item, value, depth = 0) {
            // Existing unusual data remains a valid no-op, just as in the NBT
            // writer. Apply creation rules only to an actual special-data edit.
            if (JSON.stringify(data(item)) === JSON.stringify(value)) return "";
            if (["bundle", "shulker"].includes(kind(item))) {
                if (value.items.some(child => kind(child) === "shulker")) return t("Shulkerkisten dürfen nicht in Bundles oder andere Shulkerkisten gelegt werden.");
                const isBundle = kind(item) === "bundle";
                const pending = value.items.map(child => [child, depth + 1]);
                let remaining = schema.limits.nodes;
                while (pending.length) {
                    if (--remaining < 0) return t("Der Container enthält zu viele verschachtelte Items. Maximal {max} Items sind erlaubt.", { max: schema.limits.nodes });
                    const [child, childDepth] = pending.pop();
                    if (isBundle && childDepth >= schema.limits.depth) return t("Die maximale Verschachtelungstiefe ist erreicht.");
                    if (["bundle", "shulker"].includes(kind(child)) && editable(child)) pending.push(...data(child).items.map(entry => [entry, childDepth + 1]));
                }
                if (isBundle) {
                    const used = contentWeight(value.items, depth + 1);
                    if (used === null) return t("Das Gewicht dieses Items ist ungeprüft. Der Bundle-Inhalt kann nicht sicher geändert werden.");
                    if (used > 64) return t("Das Bundle ist zu voll. Maximal 64 Gewichtseinheiten sind erlaubt.");
                }
            }
            if (kind(item) === "firework_star" && value.explosions.length !== 1) return t("Ein Feuerwerksstern benötigt genau einen Effekt.");
            if (value.explosions?.some(effect => effect.colors.length === 0)) return t("Wähle mindestens eine gültige Feuerwerksfarbe.");
            return "";
        }
        function apply(item, value) {
            const result = clone(item);
            if (JSON.stringify(data(item)) !== JSON.stringify(value)) {
                result.special_edit = { kind: kind(item), data: clone(value) };
                delete result.nbt_view;
                delete result.special_nbt_defaulted;
                delete result.special_nbt_requirement;
            }
            return result;
        }
        function cleanChild(item) {
            const result = clone(item);
            ORIGIN_FIELDS.forEach(key => delete result[key]);
            return result;
        }
        function withChild(value, slot, child) {
            const items = value.items.slice();
            const index = items.findIndex(entry => entry.slot === slot);
            if (index < 0) { if (child) items.push(child); }
            else if (child) items[index] = child;
            else items.splice(index, 1);
            return { ...value, items };
        }
        return { kind, label, data, editable, searchContents, weight, contentWeight, validate, apply, cleanChild, withChild, schema };
    }
    window.MCBESpecialItemLogic = { createModel, clone, sameUserFields, changeLabel };
}());
