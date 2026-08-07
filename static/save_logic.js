(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));

    function cloneComparableItem(item) {
        if (!item || !item.name || item.name === "minecraft:air") return null;
        const cloned = JSON.parse(JSON.stringify(item));
        delete cloned.source_player_key;
        delete cloned.source_container;
        delete cloned.source_world_path;
        delete cloned.source_slot;
        return cloned;
    }

    function createSaveLogic(deps) {
        const {
            buildChangedStatsPayload,
            currentPlayerLabel,
            getCleanSnapshot = () => null,
            getCreateRequiresConfirmation,
            getCurrentWriteGate,
            getEnchantmentsDb = () => ({}),
            getEnderChestInventory,
            getHasEnderChest,
            getHiddenUnknownSlots,
            getInventory,
            getPendingMounts = () => [],
            getPlayerAbilities,
            getPlayerEffects,
            getProtectedKnownSlots,
            getProtectedNbt,
            getWorldLabel,
            getMaxDamage,
            getMaxStack,
            hasMeaningfulObjectKeys,
            itemDisplayName,
            itemIsVisiblePresent,
            isKnownItemId,
            isValidItemId,
            maxBedrockStackCount,
            sectionChanged,
            slotDisplayName,
            takeSnapshot,
            writeBlocked,
        } = deps;

        function normalizedComparableItem(item) {
            return cloneComparableItem(item);
        }

        function sameComparableItem(a, b) {
            return JSON.stringify(normalizedComparableItem(a)) === JSON.stringify(normalizedComparableItem(b));
        }

        function normalizedItemName(value) {
            return String(value || "").trim().toLowerCase();
        }

        function originalItemForValidation(item, slot, containerName) {
            const cleanSnapshot = getCleanSnapshot();
            if (!cleanSnapshot || !item || typeof item !== "object") return null;
            const requestedSourceContainer = String(item.source_container || "");
            const sourceContainer = requestedSourceContainer === "inventory" || requestedSourceContainer === "ender_chest"
                ? requestedSourceContainer
                : containerName;
            const hasRequestedSourceSlot = item.source_slot !== undefined
                && item.source_slot !== null
                && item.source_slot !== "";
            const requestedSourceSlot = hasRequestedSourceSlot ? Number(item.source_slot) : Number.NaN;
            const sourceSlot = Number.isInteger(requestedSourceSlot) ? requestedSourceSlot : Number(slot);
            const sourceMap = sourceContainer === "ender_chest" ? cleanSnapshot.ec : cleanSnapshot.inv;
            const original = sourceMap?.[sourceSlot] ?? null;
            if (normalizedItemName(original?.name) !== normalizedItemName(item.name)) return null;
            return original;
        }

        function collectItemChanges(beforeItems = {}, afterItems = {}, containerName = "inventory") {
            const changes = [];
            const slots = new Set([...Object.keys(beforeItems || {}), ...Object.keys(afterItems || {})]);
            [...slots].map(Number).filter(Number.isFinite).sort((a, b) => a - b).forEach(slot => {
                const before = beforeItems[String(slot)] || beforeItems[slot] || null;
                const after = afterItems[String(slot)] || afterItems[slot] || null;
                if (sameComparableItem(before, after)) return;
                const beforeEmpty = !normalizedComparableItem(before);
                const afterEmpty = !normalizedComparableItem(after);
                let kind = "changed";
                if (beforeEmpty && !afterEmpty) kind = "added";
                else if (!beforeEmpty && afterEmpty) kind = "removed";
                changes.push({
                    type: "item",
                    kind,
                    container: containerName,
                    slot,
                    label: `${slotDisplayName(slot, containerName)}: ${itemDisplayName(before)} → ${itemDisplayName(after)}`,
                });
            });
            return changes;
        }

        function buildChangeSummary({ limit = 12, includeSections = true } = {}) {
            const before = getCleanSnapshot() || { inv: {}, ec: {}, stats: {}, effects: [], abilities: {} };
            const current = takeSnapshot();
            const changes = [
                ...collectItemChanges(before.inv, current.inv, "inventory"),
                ...collectItemChanges(before.ec, current.ec, "ender_chest"),
            ];
            if (includeSections && sectionChanged(before.stats, current.stats)) {
                changes.push({ type: "section", kind: "changed", label: t("Spieler-Stats/Standort wurden geändert.") });
            }
            if (includeSections && sectionChanged(before.effects, current.effects)) {
                changes.push({ type: "section", kind: "changed", label: t("Aktive Effekte wurden geändert.") });
            }
            if (includeSections && sectionChanged(before.abilities, current.abilities)) {
                changes.push({ type: "section", kind: "changed", label: t("Fähigkeiten wurden geändert.") });
            }
            getPendingMounts().forEach(mount => {
                const position = mount.selectedPosition || {};
                const coordinates = [position.x, position.y, position.z].map(value => Number.isFinite(Number(value)) ? Number(value) : "?").join(" / ");
                const safety = mount.safetyStatus === "safe" ? t("sicher geprüft") : t("ungeprüft");
                changes.push({
                    type: "mount",
                    kind: "added",
                    label: t("{mount} wird bei {coordinates} erzeugt ({safety}).", { mount: mount.mountLabel || mount.mountType || "Mount", coordinates, safety }),
                });
            });
            return {
                total: changes.length,
                shown: changes.slice(0, limit),
                hidden: Math.max(0, changes.length - limit),
            };
        }

        function changeKindLabel(kind) {
            if (kind === "added") return t("Neu");
            if (kind === "removed") return t("Entfernt");
            return t("Geändert");
        }

        function hasVisibleItemsInMap(source) {
            return Object.values(source || {}).some(itemIsVisiblePresent);
        }

        function writePlanRows() {
            const before = getCleanSnapshot() || { inv: {}, ec: {}, stats: {}, effects: [], abilities: {} };
            const current = takeSnapshot();
            const statsPayload = buildChangedStatsPayload();
            const protectedNbt = getProtectedNbt();
            const inventory = getInventory();
            const enderChestInventory = getEnderChestInventory();
            const playerEffects = getPlayerEffects();
            const playerAbilities = getPlayerAbilities();
            const createFlags = getCreateRequiresConfirmation();
            const rows = [];
            const add = (section, status, reason, severity = "ok") => rows.push({ section, status, reason, severity });
            const invChanged = sectionChanged(before.inv, current.inv);
            const ecChanged = sectionChanged(before.ec, current.ec);
            const effectsChanged = sectionChanged(before.effects, current.effects);
            const abilitiesChanged = sectionChanged(before.abilities, current.abilities);

            if (protectedNbt.inventory_opaque) add(t("Inventar"), t("blockiert/geschützt"), t("Inventory-Tag hat einen unbekannten NBT-Typ und wird nicht ersetzt."), "warning");
            else if (invChanged && createFlags.inventory && hasVisibleItemsInMap(inventory)) add(t("Inventar"), t("Bestätigung nötig"), t("Der Spieler hatte keinen Inventory-Tag; ein neuer Tag wird nur nach expliziter Bestätigung angelegt."), "warning");
            else if (invChanged) add(t("Inventar"), t("wird geschrieben"), t("Container wurde geändert; sichtbarer Containerzustand wird gesendet, hidden/future NBT bleibt serverseitig erhalten."), "changed");
            else add(t("Inventar"), t("unangetastet"), t("Keine Änderung erkannt; Feld wird im Save-Payload ausgelassen."), "ok");

            if (protectedNbt.ender_chest_opaque) add(t("Enderchest"), t("blockiert/geschützt"), t("EnderChestInventory hat einen unbekannten NBT-Typ und wird nicht ersetzt."), "warning");
            else if (ecChanged && createFlags.enderChest && hasVisibleItemsInMap(enderChestInventory)) add(t("Enderchest"), t("Bestätigung nötig"), t("Der Spieler hatte keinen EnderChestInventory-Tag; eine neue Liste wird nur nach expliziter Bestätigung angelegt."), "warning");
            else if (ecChanged) add(t("Enderchest"), t("wird geschrieben"), t("Container wurde geändert; sichtbarer Containerzustand wird gesendet, hidden/future NBT bleibt serverseitig erhalten."), "changed");
            else add(t("Enderchest"), t("unangetastet"), t("Keine Änderung erkannt; Feld wird im Save-Payload ausgelassen."), "ok");

            const locationChanged = Object.prototype.hasOwnProperty.call(statsPayload || {}, "pos");
            const dimensionChanged = Object.prototype.hasOwnProperty.call(statsPayload || {}, "dimension_id");
            if (locationChanged || dimensionChanged) {
                add(
                    t("Standort"),
                    t("wird geschrieben"),
                    t("Dimension und Position werden gemeinsam geschrieben. Die Zielposition wurde nicht im Spiel auf freien, sicheren Untergrund geprüft."),
                    "warning",
                );
            } else if (Object.keys(statsPayload || {}).length) {
                add(t("Stats/Standort"), t("wird geschrieben"), t("Geänderte Felder: {fields}. Geschützte Stats werden ausgelassen.", { fields: Object.keys(statsPayload).join(", ") }), "changed");
            } else {
                add(t("Stats/Standort"), t("unangetastet"), t("Keine speicherbare Stats-/Standortänderung erkannt."), "ok");
            }

            if (protectedNbt.active_effects_opaque) add(t("Effekte"), t("blockiert/geschützt"), t("ActiveEffects hat einen unbekannten NBT-Typ und wird nicht ersetzt."), "warning");
            else if (effectsChanged && createFlags.effects && Array.isArray(playerEffects) && playerEffects.some(eff => eff && eff.opaque !== true)) add(t("Effekte"), t("Bestätigung nötig"), t("Der Spieler hatte keinen ActiveEffects-Tag; eine neue Liste wird nur nach expliziter Bestätigung angelegt."), "warning");
            else if (effectsChanged) add(t("Effekte"), t("wird geschrieben"), t("Aktive Effekte wurden geändert und werden als geänderter Abschnitt gesendet."), "changed");
            else add(t("Effekte"), t("unangetastet"), t("Keine Änderung erkannt; ActiveEffects wird nicht gesendet."), "ok");

            if (protectedNbt.abilities_opaque || playerAbilities?._opaque) add(t("Fähigkeiten"), t("blockiert/geschützt"), t("abilities hat einen unbekannten NBT-Typ und wird nicht ersetzt."), "warning");
            else if (abilitiesChanged && createFlags.abilities && hasMeaningfulObjectKeys(playerAbilities)) add(t("Fähigkeiten"), t("Bestätigung nötig"), t("Der Spieler hatte keinen abilities-Tag; ein neuer Compound wird nur nach expliziter Bestätigung angelegt."), "warning");
            else if (abilitiesChanged) add(t("Fähigkeiten"), t("wird geschrieben"), t("Fähigkeiten wurden geändert und werden als geänderter Abschnitt gesendet."), "changed");
            else add(t("Fähigkeiten"), t("unangetastet"), t("Keine Änderung erkannt; abilities wird nicht gesendet."), "ok");
            return rows;
        }

        function collectEditorDecisionDetails(summary = buildChangeSummary({ limit: 100, includeSections: true }), validation = validateInventoryState({ limit: 100 })) {
            const protectedKnownSlots = getProtectedKnownSlots();
            const hiddenUnknownSlots = getHiddenUnknownSlots();
            const protectedVisible = (Array.isArray(protectedKnownSlots?.inventory) ? protectedKnownSlots.inventory.length : 0) + (Array.isArray(protectedKnownSlots?.ender_chest) ? protectedKnownSlots.ender_chest.length : 0);
            const hiddenProtected = Number(hiddenUnknownSlots?.inventory || 0) + Number(hiddenUnknownSlots?.ender_chest || 0) + Number(hiddenUnknownSlots?.inventory_protected_known || 0) + Number(hiddenUnknownSlots?.ender_chest_protected_known || 0);
            const currentWriteGate = getCurrentWriteGate();
            const blocked = writeBlocked();
            const writeGateText = blocked
                ? (currentWriteGate.reason || t("Schreibaktion ist blockiert."))
                : (currentWriteGate.reason || t("Schreibaktion ist erlaubt."));
            const rows = [
                { severity: blocked ? "error" : "ok", title: blocked ? t("Schreibsperre") : t("Schreibfreigabe"), text: writeGateText },
                { severity: "ok", title: t("Save-Strategie"), text: t("Delta-Save: Unveränderte Abschnitte fehlen im Payload und bedeuten serverseitig 'nicht anfassen'. Geänderte Container werden vollständig sichtbar gesendet, damit Slot-Löschungen eindeutig sind.") },
                { severity: "ok", title: t("Backup"), text: t("Vor jedem tatsächlichen Save wird automatisch ein ZIP-Backup erstellt. Bei No-op-Saves wird kein Backup erzeugt.") },
                { severity: validation.errors > 0 ? "error" : validation.warnings > 0 ? "warning" : "ok", title: t("Validierung"), text: t("{errors} Fehler, {warnings} Warnungen, {infos} Hinweise.", { errors: validation.errors, warnings: validation.warnings, infos: validation.infos }) + " " + (validation.errors > 0 ? t("Fehler blockieren den Save.") : t("Keine blockierenden Validierungsfehler.")) },
            ];
            const pendingMounts = getPendingMounts();
            rows.push({
                severity: pendingMounts.length ? "changed" : "ok",
                title: pendingMounts.length ? t("Mounts: werden erzeugt") : t("Mounts: unangetastet"),
                text: pendingMounts.length
                    ? (pendingMounts.length === 1
                        ? t("1 vorgemerkte Mount-Erzeugung wird beim bestätigten Speichern geschrieben und direkt validiert.")
                        : t("{count} vorgemerkte Mount-Erzeugungen werden beim bestätigten Speichern geschrieben und jeweils direkt validiert.", { count: pendingMounts.length }))
                    : t("Keine Mount-Erzeugung vorgemerkt."),
            });
            if (summary.total > 0) rows.push({ severity: "changed", title: t("Änderungen"), text: t("{count} Änderung(en) erkannt. Der Schreibplan unten zeigt, welche Sektionen tatsächlich gesendet werden.", { count: summary.total }) });
            else rows.push({ severity: "ok", title: t("Änderungen"), text: t("Keine sichtbaren Änderungen erkannt. Speichern bleibt deaktiviert oder wird als No-op behandelt.") });
            writePlanRows().forEach(row => rows.push({ severity: row.severity, title: row.section + ": " + row.status, text: row.reason }));
            if (protectedVisible || hiddenProtected) {
                rows.push({ severity: "warning", title: t("Geschützte NBT-Daten"), text: t("{visible} geschützte bekannte Slot(s), {hidden} hidden/future Eintrag/Einträge. Diese Daten werden erhalten und nicht verlustbehaftet neu aufgebaut.", { visible: protectedVisible, hidden: hiddenProtected }) });
            } else {
                rows.push({ severity: "ok", title: t("Geschützte NBT-Daten"), text: t("Keine geschützten Slot-Einträge im aktuellen Spielerstand gemeldet.") });
            }
            const createFlags = getCreateRequiresConfirmation();
            if (createFlags.inventory || createFlags.enderChest || createFlags.effects || createFlags.abilities) {
                const tags = [];
                if (createFlags.inventory) tags.push("Inventory");
                if (createFlags.enderChest) tags.push("EnderChestInventory");
                if (createFlags.effects) tags.push("ActiveEffects");
                if (createFlags.abilities) tags.push("abilities");
                rows.push({ severity: "warning", title: t("Erst-Erzeugung möglich"), text: t("{tags} fehlten beim Laden. Neue Tags werden nur erzeugt, wenn du entsprechende Inhalte wirklich speicherst und die Bestätigung akzeptierst.", { tags: tags.join(", ") }) });
            }
            return rows;
        }

        function decisionLogText(summary = buildChangeSummary({ limit: 100, includeSections: true }), validation = validateInventoryState({ limit: 100 })) {
            const lines = [t("Diagnose-Schreibplan (technische Details)")];
            collectEditorDecisionDetails(summary, validation).forEach(row => lines.push(`- ${row.title}: ${row.text}`));
            return lines.join("\n");
        }

        function buildChangeSummaryText(summary = buildChangeSummary({ limit: 100, includeSections: true }), validation = validateInventoryState({ limit: 100 })) {
            const lines = [
                t("Änderungsübersicht"),
                t("Welt: {world}", { world: getWorldLabel() }),
                t("Spieler: {player}", { player: currentPlayerLabel() }),
                t("Änderungen: {count}", { count: summary.total }),
                "",
            ];
            if (!summary.total) {
                lines.push(t("Keine sichtbaren Slot-Änderungen erkannt."));
            } else {
                summary.shown.forEach(change => {
                    lines.push(`- ${changeKindLabel(change.kind)}: ${change.label}`);
                });
                if (summary.hidden > 0) lines.push(`- ... ${t("{count} weitere Änderung(en)", { count: summary.hidden })}`);
            }
            lines.push("", t("Vor dem Speichern wird automatisch ein ZIP-Backup erstellt."));
            lines.push("", buildValidationText(validation));
            return lines.join("\n");
        }

        function validateItemInSlot(item, slot, containerName) {
            const issues = [];
            if (!item || !item.name || item.name === "minecraft:air") return issues;
            const label = slotDisplayName(slot, containerName);
            const count = Number(item.count ?? 1);
            const damage = Number(item.damage ?? 0);
            const maxStack = getMaxStack(item.name);
            const maxDmg = getMaxDamage(item.name);
            const itemSlot = Number(item.slot);
            const technicalId = String(item.name || "").trim();
            const originalItem = originalItemForValidation(item, slot, containerName);
            const preservesOriginalCount = Number.isFinite(count)
                && Number(originalItem?.count) === count;
            const preservesOriginalDamage = Number.isFinite(damage)
                && Number(originalItem?.damage) === damage;

            if (item.origin_world_mismatch === true) {
                issues.push({
                    level: "error",
                    label: `${label}: ${t("Item stammt aus einer anderen Welt. Bitte in der aktuellen Welt erneut kopieren; weltübergreifende Clipboard-Herkunft wird zum Schutz der NBT-Daten nicht gespeichert.")}`,
                });
            }
            if (!isValidItemId(technicalId)) {
                issues.push({ level: "error", label: `${label}: ${t("ungültige Item-ID '{id}'.", { id: technicalId || t("leer") })}` });
            } else if (!isKnownItemId(technicalId)) {
                issues.push({ level: "warning", label: `${label}: ${t("unbekannte Item-ID '{id}', wird als future/modded Item erhalten.", { id: technicalId })}` });
            }
            if (!Number.isFinite(count) || count < 1 || count > maxBedrockStackCount) {
                issues.push({ level: "error", label: `${label}: ${t("ungültige Menge {count}; erlaubt sind 1 bis {max}.", { count: item.count, max: maxBedrockStackCount })}` });
            } else if (count > maxStack && !preservesOriginalCount) {
                issues.push({ level: "error", label: `${label}: ${t("Menge {count} überschreitet das speicherbare Stacklimit {max} für {id}.", { count, max: maxStack, id: technicalId })}` });
            }
            if (!Number.isFinite(damage) || (damage < 0 && !preservesOriginalDamage)) {
                issues.push({ level: "error", label: `${label}: ${t("ungültige Abnutzung bzw. ungültiger Datenwert {damage}.", { damage: item.damage })}` });
            } else if (damage > maxDmg && maxDmg > 0 && !preservesOriginalDamage) {
                issues.push({ level: "error", label: `${label}: ${t("Abnutzung/Datenwert {damage} überschreitet den speicherbaren Maximalwert {max} für {id}.", { damage, max: maxDmg, id: technicalId })}` });
            }
            const enchantments = item.enchantments ?? [];
            const hasVisibleItemMetadata = Boolean(
                String(item.display_name || "").trim()
                || Array.isArray(item.lore) && item.lore.length
                || Array.isArray(enchantments) && enchantments.length
            );
            if (item.item_tag_opaque === true && hasVisibleItemMetadata) {
                issues.push({
                    level: "error",
                    label: `${label}: ${t("Item-Metadaten können nicht bearbeitet werden, weil der vorhandene Item-tag einen unbekannten NBT-Typ verwendet.")}`,
                });
            }
            if (!Array.isArray(enchantments)) {
                issues.push({ level: "error", label: `${label}: ${t("Verzauberungen in Slot {slot} müssen eine Liste sein.", { slot })}` });
            } else {
                const enchantmentsDb = getEnchantmentsDb() || {};
                const hasEnchantmentDb = Object.keys(enchantmentsDb).length > 0;
                const seenEnchantmentIds = new Set();
                enchantments.forEach(enchantment => {
                    const enchantmentId = Number(enchantment?.id);
                    const enchantmentLevel = Number(enchantment?.lvl);
                    const info = enchantmentsDb[enchantmentId] ?? enchantmentsDb[String(enchantmentId)];
                    const maxLevel = Number(info?.max_lvl ?? info?.[2]);
                    const invalidShape = !Number.isInteger(enchantmentId) || !Number.isInteger(enchantmentLevel);
                    const duplicate = Number.isInteger(enchantmentId) && seenEnchantmentIds.has(enchantmentId);
                    const unknown = hasEnchantmentDb && !info;
                    if (Number.isInteger(enchantmentId)) seenEnchantmentIds.add(enchantmentId);
                    if (invalidShape || duplicate || unknown) {
                        issues.push({ level: "error", label: `${label}: ${t("Ungültige Verzauberung in Slot {slot}.", { slot })}` });
                    } else if (enchantmentLevel < 1 || (Number.isFinite(maxLevel) && enchantmentLevel > maxLevel)) {
                        issues.push({
                            level: "error",
                            label: `${label}: ${t("Ungültiges Verzauberungslevel in Slot {slot}: {level}", { slot, level: enchantmentLevel })}`,
                        });
                    }
                });
            }
            if (Number.isFinite(itemSlot) && itemSlot !== Number(slot)) {
                issues.push({ level: "warning", label: `${label}: ${t("interne Slotnummer {from} wird beim Speichern auf {to} normalisiert.", { from: itemSlot, to: slot })}` });
            }
            if (item.has_protected_nbt === true) {
                issues.push({ level: "info", category: "protected_nbt_preserved", label: `${label}: ${t("enthält geschützte Zusatz-NBT-Daten, die unverändert erhalten bleiben.")}` });
                if (!item.source_player_key || !item.source_container || item.source_slot === undefined || item.source_slot === null) {
                    issues.push({ level: "warning", label: `${label}: ${t("geschützte Zusatz-NBT hat keine sichere Originalquelle; Speichern wird serverseitig blockiert, falls diese Quelle nicht auflösbar ist.")}` });
                }
            } else if (item.has_preserved_nbt === true) {
                issues.push({ level: "info", category: "preserved_nbt_preserved", label: `${label}: ${t("enthält bekannte Zusatz-NBT-Daten, die unverändert erhalten bleiben.")}` });
                if (!item.source_player_key || !item.source_container || item.source_slot === undefined || item.source_slot === null) {
                    issues.push({ level: "warning", label: `${label}: ${t("Zusatz-NBT hat keine sichere Originalquelle; Speichern wird serverseitig blockiert, falls diese Quelle nicht auflösbar ist.")}` });
                }
            }
            if (item.protected_nbt_dropped === true) {
                const previousName = item.previous_name ? ` (${item.previous_name} -> ${item.name})` : "";
                issues.push({ level: "warning", label: `${label}: ${t("Itemtyp wurde geändert{previous}; Zusatz-NBT vom vorherigen Item wird nicht übernommen.", { previous: previousName })}` });
            }
            if (item.special_nbt_defaulted === true) {
                const requirement = item.special_nbt_requirement ? ` (${item.special_nbt_requirement})` : "";
                issues.push({ level: "warning", label: `${label}: ${t("Spezialitem wird ohne spezifische Zusatz-NBT erstellt{requirement}; es entsteht nur ein Basis-/Leerzustand.", { requirement })}` });
            }
            if (item.has_unknown_enchantments === true) {
                issues.push({ level: "info", label: `${label}: ${t("enthält unbekannte/future Verzauberungen, die unverändert erhalten bleiben.")}` });
                if (!item.source_player_key || !item.source_container || item.source_slot === undefined || item.source_slot === null) {
                    issues.push({ level: "warning", label: `${label}: ${t("unbekannte Verzauberungen haben keine sichere Originalquelle; Speichern wird serverseitig blockiert, falls diese Quelle nicht auflösbar ist.")}` });
                }
            }
            return issues;
        }

        function validateInventoryState({ limit = 12 } = {}) {
            const issues = [];
            const scan = (items, containerName) => {
                Object.entries(items || {}).forEach(([slotKey, item]) => {
                    const slot = Number(slotKey);
                    if (!Number.isFinite(slot)) {
                        issues.push({ level: "error", label: `${containerName}: ${t("nicht numerischer Slot '{slot}'.", { slot: slotKey })}` });
                        return;
                    }
                    issues.push(...validateItemInSlot(item, slot, containerName));
                });
            };
            const inventory = getInventory();
            const enderChestInventory = getEnderChestInventory();
            scan(inventory, "inventory");
            scan(enderChestInventory, "ender_chest");
            const enderHasVisibleItems = Object.values(enderChestInventory || {}).some(itemIsVisiblePresent);
            if (!getHasEnderChest() && enderHasVisibleItems) {
                issues.push({
                    level: "info",
                    label: t("Enderchest: Für diesen Spieler war bisher kein EnderChestInventory-Tag vorhanden; eine neue Enderchest-Liste wird nur nach ausdrücklicher Bestätigung angelegt."),
                });
            }
            const createFlags = getCreateRequiresConfirmation();
            const playerEffects = getPlayerEffects();
            const playerAbilities = getPlayerAbilities();
            if (createFlags.effects && Array.isArray(playerEffects) && playerEffects.some(eff => eff && eff.opaque !== true)) {
                issues.push({
                    level: "info",
                    label: t("Effekte: Für diesen Spieler war bisher kein ActiveEffects-Tag vorhanden; eine neue Effektliste wird nur nach ausdrücklicher Bestätigung angelegt."),
                });
            }
            if (createFlags.abilities && hasMeaningfulObjectKeys(playerAbilities)) {
                issues.push({
                    level: "info",
                    label: t("Fähigkeiten: Für diesen Spieler war bisher kein abilities-Tag vorhanden; ein neuer Compound wird nur nach ausdrücklicher Bestätigung angelegt."),
                });
            }
            const pendingMounts = getPendingMounts();
            const statsPayload = buildChangedStatsPayload();
            if (pendingMounts.length && (Object.prototype.hasOwnProperty.call(statsPayload, "pos") || Object.prototype.hasOwnProperty.call(statsPayload, "dimension_id"))) {
                issues.push({
                    level: "error",
                    label: t("Standortänderung und Mount-Erzeugung können nicht gemeinsam gespeichert werden. Speichere zuerst den Standort, lade den Spieler neu und erstelle danach eine neue Mount-Vorschau."),
                });
            }
            pendingMounts.forEach(mount => {
                const position = mount.selectedPosition || {};
                const hasValidPosition = [position.x, position.y, position.z].every(value => Number.isFinite(Number(value)));
                if (!hasValidPosition) {
                    issues.push({ level: "error", label: `${mount.mountLabel || mount.mountType || "Mount"}: ${t("Die vorgemerkte Position ist ungültig.")}` });
                } else if (mount.safetyStatus !== "safe") {
                    issues.push({ level: "warning", label: `${mount.mountLabel || mount.mountType || "Mount"}: ${t("Die vorgemerkte Position ist ungeprüft und wird vor dem Schreiben erneut serverseitig bewertet.")}` });
                } else {
                    issues.push({ level: "info", label: `${mount.mountLabel || mount.mountType || "Mount"}: ${t("Neue Entity wird beim Speichern erzeugt und anschließend direkt validiert.")}` });
                }
            });
            const protectedNbtInfos = issues.filter(issue => issue.category === "protected_nbt_preserved" || issue.category === "preserved_nbt_preserved");
            const visibleIssues = issues.filter(issue => issue.category !== "protected_nbt_preserved" && issue.category !== "preserved_nbt_preserved");
            if (protectedNbtInfos.length) {
                visibleIssues.push({
                    level: "info",
                    category: "protected_nbt_summary",
                    label: protectedNbtInfos.length === 1
                        ? t("1 Slot enthält Zusatz-NBT-Daten. Diese Daten bleiben beim Speichern unverändert erhalten.")
                        : t("{count} Slots enthalten Zusatz-NBT-Daten. Diese Daten bleiben beim Speichern unverändert erhalten.", { count: protectedNbtInfos.length }),
                });
            }
            const errors = visibleIssues.filter(i => i.level === "error").length;
            const warnings = visibleIssues.filter(i => i.level === "warning").length;
            const infos = visibleIssues.filter(i => i.level === "info").length;
            return {
                total: visibleIssues.length,
                errors,
                warnings,
                infos,
                shown: visibleIssues.slice(0, limit),
                hidden: Math.max(0, visibleIssues.length - limit),
            };
        }

        function buildValidationText(validation = validateInventoryState({ limit: 100 })) {
            const lines = [
                t("Speicherprüfung"),
                t("Fehler: {count}", { count: validation.errors }),
                t("Warnungen: {count}", { count: validation.warnings }),
                t("Hinweise: {count}", { count: validation.infos }),
                "",
            ];
            if (!validation.total) lines.push(t("Keine Probleme erkannt."));
            else validation.shown.forEach(issue => lines.push(`- ${issue.level.toUpperCase()}: ${issue.label}`));
            if (validation.hidden > 0) lines.push(`- ... ${t("{count} weitere Meldung(en)", { count: validation.hidden })}`);
            return lines.join("\n");
        }

        return {
            buildChangeSummary,
            buildChangeSummaryText,
            buildValidationText,
            changeKindLabel,
            collectEditorDecisionDetails,
            collectItemChanges,
            decisionLogText,
            hasVisibleItemsInMap,
            normalizedComparableItem,
            sameComparableItem,
            validateInventoryState,
            validateItemInSlot,
            writePlanRows,
        };
    }

    window.MCBESaveLogic = {
        createSaveLogic,
    };
}());
