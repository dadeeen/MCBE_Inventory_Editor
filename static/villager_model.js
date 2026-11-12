(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));
    const finite = value => typeof value === "number" && Number.isFinite(value);
    const compareText = (a, b) => window.MCBEI18n?.compare?.(a, b) ?? String(a).localeCompare(String(b), "de", { sensitivity: "base" });

    function shortId(row) {
        const id = String(row?.unique_id ?? row?.id ?? "");
        return id.length > 12 ? `…${id.slice(-10)}` : id;
    }

    function aliasKey(row) {
        if (row && Object.hasOwn(row, "alias_key")) return typeof row.alias_key === "string" ? row.alias_key : "";
        // Legacy row IDs identify a position inside a chunk's actor list. They
        // can be reused by another villager and must never identify an alias.
        return row?.storage === "legacy" || String(row?.id || "").startsWith("legacy:") ? "" : String(row?.id || "");
    }

    function displayName(row, aliases = {}) {
        const key = aliasKey(row);
        return String(row.name || (key && aliases[key]) || t("Dorfbewohner #{id}", { id: shortId(row) }));
    }

    function nameChanges(value) {
        if (/[\p{Cc}\p{Cs}\u2028\u2029]/u.test(value)) throw new Error(t("Der Name darf keine Zeilenumbrüche oder Steuerzeichen enthalten."));
        const name = value.trim();
        if ([...name].length > 80) throw new Error(t("Der Name darf höchstens 80 Zeichen enthalten."));
        return { name };
    }

    function careerTierEditable(career, profession = career?.profession) {
        if (!career || ["unemployed", "nitwit"].includes(profession)) return false;
        return profession !== career.profession ? career.profession_editable === true && career.can_set_tier_on_profession_change === true
            : career.tier_editable === true;
    }

    function careerChanges(career, { profession, trade_tier: tier } = {}) {
        if (!career) throw new Error(t("Beruf und Handelsstufe können für diesen Datensatz nicht sicher geändert werden."));
        const changes = {}, professionChanged = profession !== career.profession;
        if (professionChanged) {
            if (!career.profession_editable || !career.professions?.some(option => option.id === profession)) {
                throw new Error(career.profession_reason || t("Wähle einen verfügbaren Beruf."));
            }
            changes.profession = profession;
        }
        if (careerTierEditable(career, profession) && (professionChanged || String(tier) !== String(career.trade_tier))) {
            const value = Number(tier);
            if (String(tier).trim() === "" || !Number.isInteger(value) || !career.tiers?.some(option => option.value === value)) {
                throw new Error(t("Wähle eine verfügbare Handelsstufe."));
            }
            changes.trade_tier = value;
        } else if (!professionChanged && String(tier) !== String(career.trade_tier) && String(tier).trim() !== "") {
            throw new Error(career.tier_reason || t("Die Handelsstufe dieses Datensatzes bleibt geschützt."));
        }
        if (!Object.keys(changes).length) throw new Error(t("Wähle einen anderen Beruf oder eine andere Handelsstufe."));
        return { career: changes };
    }

    function careerText(career) {
        if (!career) return "—";
        const tier = career.trade_tier_label ? t(career.trade_tier_label)
            : Number.isInteger(career.trade_tier) ? t("Stufe {tier}", { tier: career.trade_tier + 1 }) : "—";
        return [t(career.profession_label || career.profession || "Unbekannt"), tier].join(" · ");
    }

    function dimensionLabel(value) {
        if (value === 0) return t("Oberwelt");
        if (value === 1) return t("Nether");
        if (value === 2) return t("Ende");
        return Number.isInteger(value) ? t("Dimension {id}", { id: value }) : t("Unbekannt");
    }

    function healthNumber(value) {
        if (!finite(value)) return "—";
        if (Math.abs(value) > 1e12) return String(value);
        const small = value !== 0 && Math.abs(value) < 0.01;
        const precision = small ? { maximumSignificantDigits: 3 } : { maximumFractionDigits: 2 };
        if (window.MCBEI18n?.formatNumber) return window.MCBEI18n.formatNumber(value, precision);
        return small ? String(Number(value.toPrecision(3))) : String(Math.round(value * 100) / 100);
    }

    function healthText(health) {
        return `${healthNumber(health?.current)} / ${healthNumber(health?.max)}`;
    }

    function isInjured(row) {
        return finite(row.health?.current) && finite(row.health?.max) && 0 < row.health.current && row.health.current < row.health.max;
    }

    function hasPosition(row) {
        return row.position && [row.position.x, row.position.y, row.position.z].every(finite);
    }

    function positionText(row) {
        return hasPosition(row) ? ["x", "y", "z"].map(axis => healthNumber(row.position[axis])).join(" / ") : t("Unbekannt");
    }

    function matchingRegions(row, regions = []) {
        if (!hasPosition(row) || !Number.isInteger(row.dimension)) return [];
        const { x, y, z } = row.position;
        return regions.filter(region => region.dimension === row.dimension
            && x >= region.min_x && x <= region.max_x && z >= region.min_z && z <= region.max_z
            && (region.min_y === undefined || region.min_y === null || y >= region.min_y)
            && (region.max_y === undefined || region.max_y === null || y <= region.max_y));
    }

    function regionText(row, regions = []) {
        return matchingRegions(row, regions).map(region => region.name).join(", ") || t("Ohne Region");
    }

    function filterRows(rows = [], filters = {}, preferences = {}) {
        const query = String(filters.query || "").trim().toLocaleLowerCase();
        return rows.filter(row => {
            if (filters.profession && String(row.profession?.id ?? "unknown") !== filters.profession) return false;
            if (filters.tier && String(row.trade_tier ?? "unknown") !== filters.tier) return false;
            if (filters.dimension && String(row.dimension ?? "unknown") !== filters.dimension) return false;
            const regions = matchingRegions(row, preferences.regions);
            if (filters.region === "none" && regions.length) return false;
            if (filters.region && filters.region !== "none" && !regions.some(region => region.id === filters.region)) return false;
            if (filters.injured && !isInjured(row)) return false;
            if (filters.editable && !row.editable && !row.inventory_editable && !row.name_editable && !row.career_editable) return false;
            if (!query) return true;
            return [displayName(row, preferences.aliases), preferences.aliases?.[aliasKey(row)], row.name, row.unique_id, row.id,
                row.profession?.label, row.profession?.label ? t(row.profession.label) : "",
                row.trade_tier_label, row.trade_tier_label ? t(row.trade_tier_label) : "", regionText(row, preferences.regions),
                row.village?.label, row.village?.name, row.village?.id, dimensionLabel(row.dimension), positionText(row)]
                .filter(value => value !== null && value !== undefined).join(" ").toLocaleLowerCase().includes(query);
        });
    }

    function sortedRows(rows, sort = "name", direction = "asc", preferences = {}) {
        const value = row => {
            if (sort === "health") return finite(row.health?.current) ? row.health.current : null;
            if (sort === "profession") return row.profession?.id && row.profession.id !== "unknown" && row.profession.label ? t(row.profession.label) : null;
            if (sort === "tier") return Number.isInteger(row.trade_tier) ? row.trade_tier : null;
            if (sort === "region") return matchingRegions(row, preferences.regions).map(region => region.name).join(", ") || null;
            if (sort === "dimension") return Number.isInteger(row.dimension) ? row.dimension : null;
            const name = row.name || (aliasKey(row) && preferences.aliases?.[aliasKey(row)]);
            return typeof name === "string" && name.trim() ? name : null;
        };
        const values = new Map(rows.map(row => [row, value(row)]));
        return [...rows].sort((a, b) => {
            const av = values.get(a), bv = values.get(b);
            // Unknown values stay at the end, including descending numeric sorts.
            if (av === null || av === undefined) return bv === null || bv === undefined ? String(a.id).localeCompare(String(b.id)) : 1;
            if (bv === null || bv === undefined) return -1;
            const compare = typeof av === "number" && typeof bv === "number" ? av - bv
                : compareText(av, bv);
            return compare ? compare * (direction === "desc" ? -1 : 1) : String(a.id).localeCompare(String(b.id));
        });
    }

    function pageRows(rows, page = 1, pageSize = 50) {
        const pages = Math.max(1, Math.ceil(rows.length / pageSize));
        const current = Math.min(pages, Math.max(1, Math.trunc(page) || 1));
        return { rows: rows.slice((current - 1) * pageSize, current * pageSize), page: current, pages, total: rows.length };
    }

    function mapPoints(rows, dimension, limit = 1000) {
        const candidates = rows.filter(row => row.dimension === dimension && hasPosition(row)
            && Math.abs(row.position.x) <= 2 ** 35 && Math.abs(row.position.z) <= 2 ** 35);
        if (!candidates.length) return { points: [], total: 0, omitted: 0, bounds: null };
        let minX = Infinity, maxX = -Infinity, minZ = Infinity, maxZ = -Infinity;
        for (const row of candidates) {
            minX = Math.min(minX, row.position.x); maxX = Math.max(maxX, row.position.x);
            minZ = Math.min(minZ, row.position.z); maxZ = Math.max(maxZ, row.position.z);
        }
        const span = Math.max(maxX - minX, maxZ - minZ, 16);
        const centerX = (maxX + minX) / 2, centerZ = (maxZ + minZ) / 2;
        return {
            points: candidates.slice(0, limit).map(row => ({ row,
                x: 50 + 84 * (row.position.x - centerX) / span,
                z: 50 + 84 * (row.position.z - centerZ) / span,
            })),
            total: candidates.length,
            omitted: Math.max(0, candidates.length - limit),
            bounds: { min_x: minX, max_x: maxX, min_z: minZ, max_z: maxZ },
        };
    }

    function healthChanges({ max = "", current = "", heal = false } = {}) {
        const changes = {};
        for (const [key, input] of [["max_health", max], ["current_health", heal ? "" : current]]) {
            if (String(input).trim() === "") continue;
            const value = Number(input);
            if (!Number.isFinite(value) || value < 1 || value > 2048) throw new Error(t("Lebenspunkte müssen zwischen 1 und 2048 liegen."));
            changes[key] = value;
        }
        if (heal) changes.heal = true;
        if (!Object.keys(changes).length) throw new Error(t("Gib einen Gesundheitswert ein oder wähle vollständig heilen."));
        if (changes.current_health !== undefined && changes.max_health !== undefined && changes.current_health > changes.max_health) {
            throw new Error(t("Aktuelle Lebenspunkte dürfen das Maximum nicht überschreiten."));
        }
        return changes;
    }

    function normalizeRegion(input) {
        const name = String(input.name || "").trim();
        if (!name || name.length > 80) throw new Error(t("Der Regionsname muss 1 bis 80 Zeichen lang sein."));
        const dimension = Number(input.dimension);
        if (String(input.dimension).trim() === "" || !Number.isInteger(dimension)) throw new Error(t("Wähle eine gültige Dimension."));
        const region = { id: String(input.id), name, dimension };
        for (const axis of ["x", "z", "y"]) {
            const low = String(input[`min_${axis}`] ?? "").trim();
            const high = String(input[`max_${axis}`] ?? "").trim();
            if (axis === "y" && !low && !high) continue;
            if (!low || !high || !Number.isFinite(Number(low)) || !Number.isFinite(Number(high))) {
                throw new Error(t("Trage für jede verwendete Achse zwei gültige Koordinaten ein."));
            }
            if (Number(low) > Number(high)) throw new Error(t("Die kleinste Koordinate darf nicht größer als die größte sein."));
            region[`min_${axis}`] = Number(low);
            region[`max_${axis}`] = Number(high);
        }
        return region;
    }

    function snapshotIsStale(snapshot, context = {}) {
        if (!snapshot?.worldRevision) return false;
        if (snapshot.worldPath !== context.worldPath) return true;
        if (context.serverOnline) return true;
        if (context.guardToken && snapshot.guardToken && context.guardToken !== snapshot.guardToken) return true;
        if (!context.guardToken && Number.isInteger(context.guardEpoch) && context.guardEpoch > snapshot.guardEpoch) return true;
        return Boolean(context.worldRevision && context.worldRevision !== snapshot.worldRevision);
    }

    window.MCBEVillagerModel = { nameChanges, careerTierEditable, careerChanges, careerText, shortId, aliasKey, displayName, dimensionLabel, healthNumber, healthText, isInjured, hasPosition,
        positionText, matchingRegions, regionText, filterRows, sortedRows, pageRows, mapPoints, healthChanges, normalizeRegion, snapshotIsStale, compareText };
}());
