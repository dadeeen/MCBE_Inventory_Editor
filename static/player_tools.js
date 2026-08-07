(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));

    const playerViewModels = window.MCBEPlayerViewModels;
    if (!playerViewModels) throw new Error("MCBEPlayerViewModels must be loaded before MCBEPlayerTools.");
    const {
        copyFromPlayerRequestModel,
        editablePlayers,
        playerByKey,
        playerListStatusHtml,
        playerRowElement,
        playerRowHtml,
        playerRowModel,
        playerToolOptionModels,
        playerToolOptionsHtml,
        snapshotSummaryForComparison,
    } = playerViewModels;

    function isUntransferableRootEquipmentItem(item) {
        const shared = window.MCBESavePayloadLogic?.isReadOnlyRootEquipmentItem;
        if (shared) return shared(item);
        if (!item || typeof item !== "object") return false;
        if (item.root_equipment_read_only === true) return true;
        return ["armor", "offhand"].includes(String(item.source_container || ""));
    }

    function stripUntransferableRootEquipment(inventoryMap = {}) {
        // Read-only Root-Ausrüstung (Armor/Offhand in Legacy-/unbekanntem Shape)
        // ist nur in den Root-Listen des Quellspielers erhaltbar. Beim Kopieren
        // auf einen anderen Spieler würde die Save-Pipeline diese Items still
        // aus dem Payload filtern: Die UI zeigt dann Rüstung, die nie geschrieben
        // wird, und ein Ziel mit schreibbaren Root-Listen würde stattdessen
        // geleert. Deshalb werden solche Items gar nicht erst übernommen.
        const inventory = {};
        let skipped = 0;
        Object.entries(inventoryMap || {}).forEach(([slotKey, item]) => {
            if (isUntransferableRootEquipmentItem(item)) {
                skipped += 1;
                return;
            }
            inventory[slotKey] = item;
        });
        return { inventory, skipped };
    }

    function createPlayerToolsController(deps = {}) {
        const {
            elements = {},
            getPlayers = () => [],
            getCurrentPlayerKey = () => "",
            getWorldPath = () => "",
            getInventory = () => ({}),
            getEnderChestInventory = () => ({}),
            getPlayerStats = () => ({}),
            setInventory = () => {},
            setEnderChestState = () => {},
            setPlayerStats = () => {},
            currentPlayerLabel = () => t("Spieler"),
            withCsrf = () => ({}),
            parseJsonResponse = async response => response.json(),
            buildErrorMessage = (data, fallback = t("Fehler")) => data?.error || fallback,
            itemIsVisiblePresent = item => Boolean(item),
            itemHasRepairableDamage = item => Number(item?.damage || 0) > 0,
            annotateItemOrigins = () => {},
            pushUndo = () => {},
            renderStatsForm = () => {},
            clearSelection = () => {},
            buildGrids = () => {},
            getInventoryViewPreferences = () => null,
            updateGridVisuals = () => {},
            renderPlayerInventorySummary = () => {},
            getIsDirty = () => false,
            writeBlocked = () => false,
            getServerGuardEpoch = () => null,
            getServerGuardToken = () => "",
            getWorldPresenceSessionId = () => "",
            confirmPresenceConflict = async () => false,
            refreshAfterStateTransfer = async () => {},
            setDirty = () => {},
            recordAction = () => {},
            showToast = () => {},
            showConfirmDialog = async () => false,
            showLoading = () => {},
            hideLoading = () => {},
            api = null,
        } = deps;
        const {
            comparePlayerSelect,
            copySourcePlayerSelect,
            copyInventoryArea,
            copyEnderArea,
            copyStatsArea,
            playerToolsPanel,
            compareButton,
            copyButton,
            stateTransferSourcePlayerSelect,
            stateTransferTargetPlayerSelect,
            stateTransferPreview,
            stateTransferPreviewButton,
            stateTransferApplyButton,
            stateTransferSwapButton,
            stateTransferDetailsOpenButton,
            stateTransferDetailsOverlay,
            stateTransferDetailsBody,
            stateTransferDetailsCloseButton,
        } = elements;
        let playerApi = api;
        let compareRequestId = 0;
        let copyRequestId = 0;
        let stateTransferRequestId = 0;
        let currentStateTransferPreview = null;
        let stateTransferBusy = false;

        function updateStateTransferWriteControl() {
            if (stateTransferApplyButton) {
                stateTransferApplyButton.disabled = stateTransferBusy
                    || !currentStateTransferPreview
                    || writeBlocked()
                    || getIsDirty();
            }
        }

        function setStateTransferApplyStatus(status = "ready") {
            if (!stateTransferApplyButton) return;
            const completed = status === "completed";
            stateTransferApplyButton.textContent = t(completed ? "Migration gespeichert" : "Migration speichern");
            stateTransferApplyButton.classList?.toggle("state-transfer-complete", completed);
        }

        function setStateTransferBusy(busy) {
            stateTransferBusy = Boolean(busy);
            [
                stateTransferSourcePlayerSelect,
                stateTransferTargetPlayerSelect,
                stateTransferPreviewButton,
                stateTransferSwapButton,
            ].forEach(element => {
                if (element && stateTransferBusy) element.disabled = true;
            });
            if (stateTransferApplyButton) {
                if (stateTransferBusy) stateTransferApplyButton.setAttribute?.("aria-busy", "true");
                else stateTransferApplyButton.removeAttribute?.("aria-busy");
            }
            if (!stateTransferBusy) renderStateTransferOptions();
            updateStateTransferWriteControl();
        }

        function closeStateTransferDetails({ restoreFocus = true } = {}) {
            if (stateTransferDetailsOverlay) stateTransferDetailsOverlay.style.display = "none";
            stateTransferDetailsOverlay?.setAttribute?.("aria-hidden", "true");
            stateTransferDetailsOpenButton?.setAttribute?.("aria-expanded", "false");
            if (restoreFocus) stateTransferDetailsOpenButton?.focus?.({ preventScroll: true });
        }

        function openStateTransferDetails() {
            if (!stateTransferDetailsOverlay || !stateTransferDetailsBody?.innerHTML) return false;
            stateTransferDetailsOverlay.style.display = "flex";
            stateTransferDetailsOverlay.setAttribute?.("aria-hidden", "false");
            stateTransferDetailsOpenButton?.setAttribute?.("aria-expanded", "true");
            stateTransferDetailsCloseButton?.focus?.({ preventScroll: true });
            return true;
        }

        function clearStateTransferDetails() {
            closeStateTransferDetails({ restoreFocus: false });
            if (stateTransferDetailsBody) stateTransferDetailsBody.innerHTML = "";
            if (stateTransferDetailsOpenButton) stateTransferDetailsOpenButton.style.display = "none";
        }

        const escapeHtml = value => window.MCBEHtmlUtils?.escapeHtml
            ? window.MCBEHtmlUtils.escapeHtml(value)
            : String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
        const escapeAttr = value => window.MCBEHtmlUtils?.escapeAttr ? window.MCBEHtmlUtils.escapeAttr(value) : escapeHtml(value);

        function playerContextIsCurrent(worldPath, playerKey) {
            return getWorldPath() === worldPath && getCurrentPlayerKey() === playerKey;
        }

        function stateTransferSelectionIsCurrent(worldPath, sourcePlayerKey, targetPlayerKey) {
            return getWorldPath() === worldPath
                && stateTransferSourcePlayerSelect?.value === sourcePlayerKey
                && stateTransferTargetPlayerSelect?.value === targetPlayerKey;
        }

        function getPlayerApi() {
            if (!playerApi) {
                if (!window.MCBEPlayerApi?.createPlayerApiClient) {
                    throw new Error("MCBEPlayerApi must be loaded before player tool API calls.");
                }
                playerApi = window.MCBEPlayerApi.createPlayerApiClient({
                    withCsrf,
                    parseJsonResponse,
                    buildErrorMessage,
                });
            }
            return playerApi;
        }

        function renderOptions() {
            const selects = [comparePlayerSelect, copySourcePlayerSelect].filter(Boolean);
            selects.forEach(sel => {
                const model = playerToolOptionModels(getPlayers(), {
                    currentPlayerKey: getCurrentPlayerKey(),
                    previousValue: sel.value,
                });
                sel.innerHTML = playerToolOptionsHtml(model, {
                    disableCurrent: sel === copySourcePlayerSelect,
                });
                if (model.disabled) {
                    sel.disabled = true;
                    return;
                }
                sel.disabled = false;
                sel.value = model.selectedValue;
            });
            renderStateTransferOptions();
        }

        function stateTransferCandidates() {
            return editablePlayers(getPlayers()).filter(player => ["local", "remote"].includes(player.kind));
        }

        function playerOptionsHtml(candidates, selectedValue) {
            return candidates.map(player => {
                const selected = player.player_key === selectedValue ? " selected" : "";
                return `<option value="${escapeAttr(player.player_key || "")}"${selected}>${escapeHtml(player.label || player.player_key || "")}</option>`;
            }).join("");
        }

        function invalidateStateTransferPreview({ keepMessage = false } = {}) {
            currentStateTransferPreview = null;
            setStateTransferApplyStatus();
            clearStateTransferDetails();
            updateStateTransferWriteControl();
            if (!keepMessage && stateTransferPreview) {
                stateTransferPreview.style.display = "none";
                stateTransferPreview.innerHTML = "";
            }
        }

        function renderStateTransferTargetOptions(preferredTarget = "") {
            if (!stateTransferTargetPlayerSelect) return;
            const candidates = stateTransferCandidates();
            const source = candidates.find(player => player.player_key === stateTransferSourcePlayerSelect?.value);
            const targets = source ? candidates.filter(player => player.kind !== source.kind) : [];
            const selected = targets.some(player => player.player_key === preferredTarget)
                ? preferredTarget
                : (targets[0]?.player_key || "");
            stateTransferTargetPlayerSelect.innerHTML = targets.length
                ? playerOptionsHtml(targets, selected)
                : `<option value="">${escapeHtml(t("Kein passender Zielspieler"))}</option>`;
            stateTransferTargetPlayerSelect.disabled = stateTransferBusy || targets.length === 0;
            stateTransferTargetPlayerSelect.value = selected;
        }

        function renderStateTransferOptions() {
            if (!stateTransferSourcePlayerSelect || !stateTransferTargetPlayerSelect) return;
            const previousSource = stateTransferSourcePlayerSelect.value;
            const previousTarget = stateTransferTargetPlayerSelect.value;
            const candidates = stateTransferCandidates();
            const hasBothKinds = candidates.some(player => player.kind === "local") && candidates.some(player => player.kind === "remote");
            if (!hasBothKinds) {
                stateTransferSourcePlayerSelect.innerHTML = `<option value="">${escapeHtml(t("Lokaler und Multiplayer-Spieler erforderlich"))}</option>`;
                stateTransferSourcePlayerSelect.disabled = true;
                renderStateTransferTargetOptions("");
                if (stateTransferPreviewButton) stateTransferPreviewButton.disabled = true;
                if (stateTransferSwapButton) stateTransferSwapButton.disabled = true;
                invalidateStateTransferPreview();
                return;
            }
            const selectedSource = candidates.some(player => player.player_key === previousSource)
                ? previousSource
                : (candidates.find(player => player.kind === "local")?.player_key || candidates[0].player_key);
            stateTransferSourcePlayerSelect.innerHTML = playerOptionsHtml(candidates, selectedSource);
            stateTransferSourcePlayerSelect.disabled = stateTransferBusy;
            stateTransferSourcePlayerSelect.value = selectedSource;
            renderStateTransferTargetOptions(previousTarget);
            if (stateTransferPreviewButton) stateTransferPreviewButton.disabled = stateTransferBusy;
            if (stateTransferSwapButton) stateTransferSwapButton.disabled = stateTransferBusy;
            const token = currentStateTransferPreview?.transfer_token;
            if (token && (
                token.source_player_key !== stateTransferSourcePlayerSelect.value
                || token.target_player_key !== stateTransferTargetPlayerSelect.value
            )) invalidateStateTransferPreview();
        }

        async function fetchSnapshot(playerKey, worldPath = getWorldPath()) {
            if (!worldPath || !playerKey) throw new Error(t("Keine Welt oder kein Spieler ausgewählt."));
            return getPlayerApi().loadPlayerOrThrow(worldPath, playerKey, t("Spieler konnte nicht geladen werden."));
        }

        function snapshotSummary(data) {
            return snapshotSummaryForComparison(data, itemIsVisiblePresent, itemHasRepairableDamage);
        }

        function renderComparison(otherData) {
            if (!playerToolsPanel) return;
            const current = snapshotSummary({
                inventory: getInventory(),
                ender_chest: getEnderChestInventory(),
                stats: getPlayerStats(),
            });
            const other = snapshotSummary(otherData);
            const otherLabel = otherData.player?.label || t("Vergleichsspieler");
            playerToolsPanel.innerHTML = window.MCBEPlayerCompareView.comparisonHtml({
                currentLabel: currentPlayerLabel(),
                current,
                otherLabel,
                other,
            });
        }

        async function compareSelectedPlayer() {
            const requestId = ++compareRequestId;
            const worldPath = getWorldPath();
            const currentKey = getCurrentPlayerKey();
            if (!currentKey) { showToast(t("Lade zuerst einen Spieler."), "warning"); return; }
            const key = comparePlayerSelect?.value;
            if (!key || key === currentKey) { showToast(t("Wähle einen anderen Spieler zum Vergleichen."), "warning"); return; }
            try {
                if (playerToolsPanel) playerToolsPanel.innerHTML = window.MCBEPlayerCompareView.comparisonLoadingHtml();
                const data = await fetchSnapshot(key, worldPath);
                if (requestId !== compareRequestId || !playerContextIsCurrent(worldPath, currentKey)) return false;
                renderComparison(data);
                recordAction(t("Vergleich mit {player} angezeigt", { player: data.player?.label || key }), "compare");
                return true;
            } catch (e) {
                if (requestId !== compareRequestId || !playerContextIsCurrent(worldPath, currentKey)) return false;
                if (playerToolsPanel) playerToolsPanel.innerHTML = window.MCBEPlayerCompareView.comparisonErrorHtml(e.message);
                showToast(e.message || t("Vergleich fehlgeschlagen."), "error");
                return false;
            }
        }

        async function copyFromSelectedPlayer() {
            const requestId = ++copyRequestId;
            const worldPath = getWorldPath();
            const targetPlayerKey = getCurrentPlayerKey();
            const key = copySourcePlayerSelect?.value;
            const useInv = copyInventoryArea?.checked;
            const useEnder = copyEnderArea?.checked;
            const useStats = copyStatsArea?.checked;
            const source = playerByKey(getPlayers(), key);
            const request = copyFromPlayerRequestModel({
                currentPlayerKey: targetPlayerKey,
                sourcePlayerKey: key,
                useInventory: useInv,
                useEnder,
                useStats,
                sourceLabel: source?.label || "",
                targetLabel: currentPlayerLabel(),
            });
            if (!request.valid) { showToast(request.message, "warning"); return; }
            const ok = await showConfirmDialog(request.confirmationText);
            if (!ok) return;
            if (requestId !== copyRequestId || !playerContextIsCurrent(worldPath, targetPlayerKey)) {
                showToast(t("Übernahme abgebrochen: Welt oder Zielspieler wurde inzwischen gewechselt."), "warning");
                return false;
            }
            showLoading(t("Spielerdaten werden für die Übernahme geladen..."));
            try {
                const data = await fetchSnapshot(key, worldPath);
                if (requestId !== copyRequestId || !playerContextIsCurrent(worldPath, targetPlayerKey)) {
                    showToast(t("Übernahme abgebrochen: Welt oder Zielspieler wurde inzwischen gewechselt."), "warning");
                    return false;
                }
                pushUndo();
                if (useInv) {
                    const copied = stripUntransferableRootEquipment(JSON.parse(JSON.stringify(data.inventory || {})));
                    annotateItemOrigins(copied.inventory, key, "inventory");
                    setInventory(copied.inventory);
                    if (copied.skipped > 0) {
                        showToast(
                            t("{count} Ausrüstungs-Slot(s) des Quellspielers wurden nicht übernommen: read-only Root-Ausrüstung kann nur beim Quellspieler erhalten bleiben.", { count: copied.skipped }),
                            "warning",
                            5200,
                        );
                    }
                }
                if (useEnder) {
                    const nextEnderChest = JSON.parse(JSON.stringify(data.ender_chest || {}));
                    annotateItemOrigins(nextEnderChest, key, "ender_chest");
                    setEnderChestState({
                        inventory: nextEnderChest,
                        hasEnderChest: Boolean(data.has_ender_chest || Object.keys(nextEnderChest).length),
                        createRequiresConfirmation: !Boolean(data.player?.has_ender_chest_tag),
                    });
                }
                if (useStats) {
                    setPlayerStats(JSON.parse(JSON.stringify(data.stats || getPlayerStats())));
                    renderStatsForm();
                }
                clearSelection();
                buildGrids();
                getInventoryViewPreferences()?.applyInventoryViewPreferences?.();
                getInventoryViewPreferences()?.applyEnderChestVisibility?.();
                updateGridVisuals();
                renderPlayerInventorySummary();
                setDirty(true);
                recordAction(t("Daten von {player} übernommen", { player: data.player?.label || key }), "copy");
                showToast(t("Daten lokal übernommen. Prüfe die Änderungen vor dem Speichern."), "success");
                return true;
            } catch (e) {
                if (requestId !== copyRequestId || !playerContextIsCurrent(worldPath, targetPlayerKey)) return false;
                showToast(e.message || t("Übernahme fehlgeschlagen."), "error");
                return false;
            } finally {
                hideLoading();
            }
        }

        function renderStateTransferPreview(data) {
            if (!stateTransferPreview) return;
            const plan = data?.plan || {};
            const groups = (plan.groups || []).filter(group => Number(group.change_count || 0) > 0);
            const structured = plan.structured_fields || {};
            const abilities = structured.abilities || {};
            const attributes = structured.attributes || {};
            const recipes = structured.recipe_unlocking || {};
            const groupSummaryText = {
                inventory: "Inventar, Ausrüstung und Enderchest werden übernommen.",
                location: "Position, Spawnpunkt und letzter Todesort werden abgeglichen.",
                vitals: "Gesundheit, Hunger, Erschöpfung und aktive Effekte werden übernommen.",
                progress: "Erfahrung und Fortschritt werden übernommen.",
                gameplay: "Spielmodus und freigegebene Fähigkeiten werden übernommen.",
            };
            const summaryItems = groups.map(group => {
                const text = groupSummaryText[group.id] || "{area} wird übernommen.";
                const message = text === "{area} wird übernommen."
                    ? t(text, { area: t(group.label || group.id || "Bereich") })
                    : t(text);
                return `<li class="state-transfer-summary-item"><span aria-hidden="true">✓</span><span>${escapeHtml(message)}</span></li>`;
            }).join("");
            const addedRecipeCount = Number(recipes.added_recipe_count || 0);
            const sourceRecipeCount = Number(recipes.source_recipe_count || 0);
            let recipeSummaryText = "";
            if (recipes.source_present === true) {
                if (addedRecipeCount === 1) {
                    recipeSummaryText = t("1 fehlende Rezeptfreischaltung wird ergänzt; vorhandene Zielrezepte bleiben erhalten.");
                } else if (addedRecipeCount > 1) {
                    recipeSummaryText = t("{count} fehlende Rezeptfreischaltungen werden ergänzt; vorhandene Zielrezepte bleiben erhalten.", {
                        count: addedRecipeCount,
                    });
                } else if (sourceRecipeCount > 0) {
                    recipeSummaryText = t("Alle Rezeptfreischaltungen der Quelle sind am Ziel bereits vorhanden.");
                } else {
                    recipeSummaryText = t("Die Quelle enthält keine freigeschalteten Rezepte; vorhandene Zielrezepte bleiben erhalten.");
                }
            }
            const recipeSummaryItem = recipeSummaryText
                ? `<li class="state-transfer-summary-item"><span aria-hidden="true">✓</span><span>${escapeHtml(recipeSummaryText)}</span></li>`
                : "";
            const allSummaryItems = summaryItems + recipeSummaryItem;

            const abilityLabels = {
                flySpeed: "Fluggeschwindigkeit",
                walkSpeed: "Laufgeschwindigkeit",
                mayfly: "Fliegen erlaubt",
                flying: "Flugstatus",
                invulnerable: "Unverwundbar",
                mayBuild: "Bauen erlaubt",
                maybuild: "Bauen erlaubt",
                instabuild: "Sofort bauen",
            };
            const attributeLabels = {
                "minecraft:health": "Gesundheit",
                "minecraft:player.level": "Spieler-Level",
                "minecraft:player.experience": "Erfahrung",
                "minecraft:player.hunger": "Spieler-Hunger",
                "minecraft:player.saturation": "Sättigung",
                "minecraft:player.exhaustion": "Erschöpfung",
                "minecraft:follow_range": "Sichtweite",
                "minecraft:knockback_resistance": "Rückstoßresistenz",
                "minecraft:movement": "Bewegungsgeschwindigkeit",
                "minecraft:underwater_movement": "Unterwasserbewegung",
                "minecraft:lava_movement": "Lavabewegung",
                "minecraft:attack_damage": "Angriffsschaden",
                "minecraft:absorption": "Absorptionsleben",
                "minecraft:luck": "Glück",
                "minecraft:friction_modifier": "Reibungsmodifikator",
                "minecraft:bounciness": "Sprungfaktor",
                "minecraft:air_drag_modifier": "Luftwiderstandsmodifikator",
            };
            const recipeLabels = {
                unlocked_recipes: "Rezeptfreischaltungen",
                used_contexts: "Verwendete Rezeptkontexte",
            };
            const rootFieldLabels = {
                HasDiedBefore: "Vorheriger Tod vorhanden",
                DeathDimension: "Dimension des letzten Todes",
                DeathPositionX: "Letzter Todesort X",
                DeathPositionY: "Letzter Todesort Y",
                DeathPositionZ: "Letzter Todesort Z",
                TimeSinceRest: "Zeit seit der letzten Ruhe",
            };
            const groupLabelByField = {};
            (plan.groups || []).forEach(group => {
                [...(group.copied_fields || []), ...(group.cleared_fields || [])].forEach(field => {
                    groupLabelByField[field] = group.label || group.id || "Bereich";
                });
            });
            const describeField = (field, kind = "root") => {
                const technical = kind === "ability"
                    ? `abilities.${field}`
                    : kind === "recipe"
                        ? `recipe_unlocking.${field}`
                        : String(field);
                if (kind === "ability") {
                    return { label: t(abilityLabels[field] || "Fähigkeit"), technical };
                }
                if (kind === "recipe") {
                    return { label: t(recipeLabels[field] || "Rezeptstatus"), technical };
                }
                const attributeMatch = technical.match(/^Attributes\[(.+)\]$/);
                if (attributeMatch) {
                    return {
                        label: t(attributeLabels[attributeMatch[1]] || "Attribut"),
                        technical,
                    };
                }
                return {
                    label: t(rootFieldLabels[technical] || groupLabelByField[technical] || (
                        kind === "preserved" ? "Zielgebundenes oder unbekanntes Feld" : "Zustandsfeld"
                    )),
                    technical,
                };
            };
            const rootCopied = groups.flatMap(group => (group.copied_fields || []).map(field => describeField(field)));
            const rootCleared = groups.flatMap(group => (group.cleared_fields || []).map(field => describeField(field)));
            const copied = [
                ...rootCopied,
                ...(abilities.copied_fields || []).map(field => describeField(field, "ability")),
                ...(attributes.copied_fields || []).map(field => describeField(field, "attribute")),
                ...(recipes.copied_fields || []).map(field => describeField(field, "recipe")),
            ];
            const cleared = [
                ...rootCleared,
                ...(abilities.cleared_fields || []).map(field => describeField(field, "ability")),
                ...(attributes.cleared_fields || []).map(field => describeField(field, "attribute")),
                ...(recipes.cleared_fields || []).map(field => describeField(field, "recipe")),
            ];
            const preserved = [
                ...(plan.preserved_target_fields || []).map(field => describeField(field, "preserved")),
                ...(abilities.preserved_target_fields || []).map(field => describeField(field, "ability")),
                ...(attributes.preserved_target_fields || []).map(field => describeField(field, "attribute")),
                ...(recipes.preserved_target_fields || []).map(field => describeField(field, "recipe")),
            ];
            const skipped = [
                ...(plan.skipped_source_fields || []).map(field => describeField(field)),
                ...(abilities.skipped_source_fields || []).map(field => describeField(field, "ability")),
                ...(attributes.skipped_source_fields || []).map(field => describeField(field, "attribute")),
                ...(recipes.skipped_source_fields || []).map(field => describeField(field, "recipe")),
            ];
            const detailSection = (title, entries) => {
                if (!entries.length) return "";
                const uniqueEntries = entries.filter((entry, index, all) => (
                    all.findIndex(candidate => candidate.technical === entry.technical) === index
                ));
                return `
                    <section class="state-transfer-detail-section">
                        <h4>${escapeHtml(t(title))} <span>${uniqueEntries.length}</span></h4>
                        <ul class="state-transfer-detail-list">${uniqueEntries.map(entry => (
                            `<li><span>${escapeHtml(entry.label)}</span><code>${escapeHtml(entry.technical)}</code></li>`
                        )).join("")}</ul>
                    </section>`;
            };
            const technicalDetailsHtml = [
                detailSection("Übernommen", copied),
                detailSection("Am Ziel entfernt", cleared),
                detailSection("Am Ziel erhalten", preserved),
                detailSection("Aus der Quelle nicht übernommen", skipped),
            ].join("");
            const warningItems = cleared.slice(0, 3).map(entry => (
                `<li>${escapeHtml(entry.label)} <code>${escapeHtml(entry.technical)}</code></li>`
            )).join("");
            const warningMore = cleared.length > 3
                ? `<div>${escapeHtml(t("Weitere entfernte Werte stehen in den technischen Details."))}</div>`
                : "";
            const warning = cleared.length
                ? `<aside class="state-transfer-warning">
                    <strong>${escapeHtml(cleared.length === 1
                        ? t("1 vorhandener Zielwert wird entfernt.")
                        : t("{count} vorhandene Zielwerte werden entfernt.", { count: cleared.length }))}</strong>
                    <ul>${warningItems}</ul>
                    ${warningMore}
                </aside>`
                : "";
            stateTransferPreview.innerHTML = `
                <div class="state-transfer-summary">
                    <strong>${escapeHtml(data.source_player?.label || t("Quelle"))} → ${escapeHtml(data.target_player?.label || t("Ziel"))}</strong>
                    <ul>${allSummaryItems || `<li>${escapeHtml(t("Keine freigegebenen Zustandsfelder vorhanden."))}</li>`}</ul>
                    <div class="state-transfer-summary-item"><span aria-hidden="true">✓</span><span>${escapeHtml(t("Zielidentität und nicht freigegebene Zielwerte bleiben erhalten."))}</span></div>
                </div>
                ${warning}
                <p>${escapeHtml(t("Der Quelldatensatz bleibt unverändert. Vor dem Schreiben wird ein geprüftes Backup erstellt."))}</p>
                <p>${escapeHtml(t("Haustier- und andere Entity-Besitzbeziehungen werden nicht automatisch übertragen."))}</p>`;
            if (stateTransferDetailsBody) {
                stateTransferDetailsBody.innerHTML = technicalDetailsHtml || `<div class="no-backups">${escapeHtml(t("Keine technischen Änderungen vorhanden."))}</div>`;
            }
            if (stateTransferDetailsOpenButton) stateTransferDetailsOpenButton.style.display = "inline-flex";
            stateTransferPreview.style.display = "block";
        }

        function renderStateTransferError(message) {
            if (!stateTransferPreview) return;
            stateTransferPreview.innerHTML = `<div class="error">${escapeHtml(message || t("Migration fehlgeschlagen."))}</div>`;
            stateTransferPreview.style.display = "block";
        }

        function renderStateTransferSuccess(data) {
            if (!stateTransferPreview) return;
            clearStateTransferDetails();
            const transferredCount = Number(data.validation?.transferred_field_count || 0);
            const addedRecipeCount = Number(data.plan?.structured_fields?.recipe_unlocking?.added_recipe_count || 0);
            const recipeResult = addedRecipeCount > 0
                ? `<div>${escapeHtml(addedRecipeCount === 1
                    ? t("1 Rezeptfreischaltung wurde ergänzt; vorhandene Zielrezepte blieben erhalten.")
                    : t("{count} Rezeptfreischaltungen wurden ergänzt; vorhandene Zielrezepte blieben erhalten.", { count: addedRecipeCount }))}</div>`
                : "";
            const backupFile = data.backup_file || t("Backup erstellt");
            const backupLabel = t("Sicherungsbackup: {backup}", { backup: "" }).trim();
            stateTransferPreview.innerHTML = `
                <strong>${escapeHtml(t("Migration validiert"))}</strong>
                <div>${escapeHtml(t("{count} Zustandsfelder wurden übertragen. Der Quelldatensatz blieb unverändert und die Zielidentität wurde erhalten.", { count: transferredCount }))}</div>
                ${recipeResult}
                <div class="state-transfer-result-path">
                    <span>${escapeHtml(backupLabel)}</span>
                    <code title="${escapeAttr(backupFile)}">${escapeHtml(backupFile)}</code>
                </div>`;
            stateTransferPreview.style.display = "block";
            setStateTransferApplyStatus("completed");
        }

        async function previewStateTransfer() {
            const requestId = ++stateTransferRequestId;
            const worldPath = getWorldPath();
            const sourcePlayerKey = stateTransferSourcePlayerSelect?.value || "";
            const targetPlayerKey = stateTransferTargetPlayerSelect?.value || "";
            invalidateStateTransferPreview();
            if (!worldPath || !sourcePlayerKey || !targetPlayerKey) {
                showToast(t("Wähle Quelle und Ziel für die Migration."), "warning");
                return false;
            }
            if (sourcePlayerKey === targetPlayerKey) {
                showToast(t("Quelle und Ziel müssen unterschiedliche Spieler sein."), "warning");
                return false;
            }
            try {
                if (stateTransferPreview) {
                    stateTransferPreview.innerHTML = `<div>${escapeHtml(t("Migration wird geprüft..."))}</div>`;
                    stateTransferPreview.style.display = "block";
                }
                const data = await getPlayerApi().previewStateTransfer(worldPath, sourcePlayerKey, targetPlayerKey);
                if (requestId !== stateTransferRequestId || !stateTransferSelectionIsCurrent(worldPath, sourcePlayerKey, targetPlayerKey)) return false;
                if (!data.success) {
                    const error = new Error(buildErrorMessage(data, t("Migration konnte nicht geprüft werden.")));
                    Object.assign(error, data);
                    throw error;
                }
                currentStateTransferPreview = data;
                renderStateTransferPreview(data);
                updateStateTransferWriteControl();
                recordAction(t("Spielermigration geprüft"), "player-transfer-preview");
                return true;
            } catch (error) {
                if (requestId !== stateTransferRequestId || !stateTransferSelectionIsCurrent(worldPath, sourcePlayerKey, targetPlayerKey)) return false;
                invalidateStateTransferPreview({ keepMessage: true });
                const message = error?.message || t("Migration konnte nicht geprüft werden.");
                renderStateTransferError(message);
                showToast(message, "error");
                return false;
            }
        }

        function swapStateTransferDirection() {
            const source = stateTransferSourcePlayerSelect?.value || "";
            const target = stateTransferTargetPlayerSelect?.value || "";
            if (!source || !target) return;
            stateTransferSourcePlayerSelect.value = target;
            renderStateTransferTargetOptions(source);
            invalidateStateTransferPreview();
        }

        async function applyStateTransfer() {
            if (stateTransferBusy) return false;
            const preview = currentStateTransferPreview;
            const worldPath = getWorldPath();
            const sourcePlayerKey = stateTransferSourcePlayerSelect?.value || "";
            const targetPlayerKey = stateTransferTargetPlayerSelect?.value || "";
            if (!preview) {
                showToast(t("Prüfe zuerst die Migrationsvorschau."), "warning");
                return false;
            }
            if (getIsDirty()) {
                showToast(t("Speichere oder verwirf zuerst die offenen Editor-Änderungen."), "warning");
                return false;
            }
            if (writeBlocked()) {
                showToast(t("Migration ist derzeit durch die Schreibschutzprüfung blockiert."), "warning");
                return false;
            }
            if (
                preview.transfer_token?.source_player_key !== sourcePlayerKey
                || preview.transfer_token?.target_player_key !== targetPlayerKey
            ) {
                invalidateStateTransferPreview();
                showToast(t("Quelle oder Ziel wurde geändert. Prüfe die Migration erneut."), "warning");
                return false;
            }
            setStateTransferBusy(true);
            let requestId = null;
            let loadingVisible = false;
            try {
                const confirmed = await showConfirmDialog(
                    t("Spielerzustand von {source} nach {target} in der ausgewählten Welt übertragen? Vorher wird automatisch ein Backup erstellt; Zielidentität und Quelldatensatz bleiben erhalten.", {
                        source: preview.source_player?.label || t("Quelle"),
                        target: preview.target_player?.label || t("Ziel"),
                    }),
                );
                if (!confirmed) return false;
                if (
                    currentStateTransferPreview !== preview
                    || !stateTransferSelectionIsCurrent(worldPath, sourcePlayerKey, targetPlayerKey)
                ) {
                    invalidateStateTransferPreview();
                    showToast(t("Welt, Quelle oder Ziel wurde während der Bestätigung geändert. Prüfe die Migration erneut."), "warning");
                    return false;
                }
                if (getIsDirty()) {
                    showToast(t("Speichere oder verwirf zuerst die offenen Editor-Änderungen."), "warning");
                    return false;
                }
                if (writeBlocked()) {
                    showToast(t("Migration ist derzeit durch die Schreibschutzprüfung blockiert."), "warning");
                    return false;
                }

                requestId = ++stateTransferRequestId;
                showLoading(t("Spielermigration läuft: Backup erstellen, Ziel schreiben und Ergebnis prüfen..."));
                loadingVisible = true;
                const request = confirmConflict => getPlayerApi().applyStateTransfer({
                    worldPath,
                    sourcePlayerKey,
                    targetPlayerKey,
                    transferToken: preview.transfer_token,
                    serverGuardEpoch: preview.server_guard_epoch ?? getServerGuardEpoch(),
                    serverGuardToken: preview.server_guard_token || getServerGuardToken(),
                    sessionId: getWorldPresenceSessionId(),
                    confirmPresenceConflict: confirmConflict,
                });
                let data = await request(false);
                if (requestId !== stateTransferRequestId || getWorldPath() !== worldPath) return false;
                if (!data.success && data.presence_conflict) {
                    const proceed = await confirmPresenceConflict(data);
                    if (!proceed) {
                        const message = t("Migration wegen Bearbeitungskonflikt abgebrochen.");
                        renderStateTransferError(message);
                        updateStateTransferWriteControl();
                        showToast(message, "warning", 4500);
                        return false;
                    }
                    if (requestId !== stateTransferRequestId || getWorldPath() !== worldPath) return false;
                    if (
                        currentStateTransferPreview !== preview
                        || !stateTransferSelectionIsCurrent(worldPath, sourcePlayerKey, targetPlayerKey)
                    ) {
                        invalidateStateTransferPreview();
                        showToast(t("Welt, Quelle oder Ziel wurde während der Bestätigung geändert. Prüfe die Migration erneut."), "warning");
                        return false;
                    }
                    if (getIsDirty()) {
                        showToast(t("Speichere oder verwirf zuerst die offenen Editor-Änderungen."), "warning");
                        return false;
                    }
                    if (writeBlocked()) {
                        showToast(t("Migration ist derzeit durch die Schreibschutzprüfung blockiert."), "warning");
                        return false;
                    }
                    data = await request(true);
                }
                if (requestId !== stateTransferRequestId || getWorldPath() !== worldPath) return false;
                if (!data.success) {
                    const error = new Error(buildErrorMessage(data, t("Migration fehlgeschlagen.")));
                    Object.assign(error, data);
                    throw error;
                }
                showLoading(t("Migration geschrieben. Spieleransicht wird aktualisiert..."));
                try {
                    await refreshAfterStateTransfer();
                } catch (refreshError) {
                    showToast(
                        refreshError?.message || t("Migration wurde gespeichert, aber die Spieleransicht konnte nicht aktualisiert werden. Lade die Spieler erneut."),
                        "warning",
                        6500,
                    );
                }
                currentStateTransferPreview = null;
                updateStateTransferWriteControl();
                renderStateTransferSuccess(data);
                recordAction(t("Spielermigration gespeichert"), "player-transfer");
                showToast(t("Migration gespeichert und nachvalidiert."), "success", 5000);
                if (data.cleanup_warning) showToast(data.cleanup_warning, "warning", 6500);
                return true;
            } catch (error) {
                if (requestId !== null && (requestId !== stateTransferRequestId || getWorldPath() !== worldPath)) return false;
                const message = error?.message || t("Migration fehlgeschlagen.");
                const targetStateMayHaveChanged = error?.write_committed === true;
                renderStateTransferError(message);
                if (error?.preview_stale || targetStateMayHaveChanged) invalidateStateTransferPreview({ keepMessage: true });
                else updateStateTransferWriteControl();
                if (targetStateMayHaveChanged) {
                    let refreshWarning = "";
                    try {
                        await refreshAfterStateTransfer();
                    } catch (refreshError) {
                        refreshWarning = refreshError?.message
                            ? t("Der Zielzustand ist nach dem fehlgeschlagenen Migrations-Rollback unsicher und konnte nicht neu geladen werden: {error}", { error: refreshError.message })
                            : t("Der Zielzustand ist nach dem fehlgeschlagenen Migrations-Rollback unsicher und konnte nicht neu geladen werden. Lade die Spieler erneut.");
                    }
                    if (requestId !== stateTransferRequestId || getWorldPath() !== worldPath) return false;
                    // Reloading player data can re-render the tools panel. Keep
                    // the backend's rollback error visible afterwards.
                    renderStateTransferError(message);
                    if (refreshWarning) showToast(refreshWarning, "warning", 8000);
                }
                showToast(message, "error", 6000);
                if (error?.cleanup_warning) showToast(error.cleanup_warning, "warning", 8000);
                return false;
            } finally {
                setStateTransferBusy(false);
                if (loadingVisible) hideLoading();
            }
        }

        function wire() {
            compareButton?.addEventListener("click", compareSelectedPlayer);
            copyButton?.addEventListener("click", copyFromSelectedPlayer);
            stateTransferSourcePlayerSelect?.addEventListener("change", () => {
                renderStateTransferTargetOptions("");
                invalidateStateTransferPreview();
            });
            stateTransferTargetPlayerSelect?.addEventListener("change", () => invalidateStateTransferPreview());
            stateTransferPreviewButton?.addEventListener("click", previewStateTransfer);
            stateTransferApplyButton?.addEventListener("click", applyStateTransfer);
            stateTransferSwapButton?.addEventListener("click", swapStateTransferDirection);
            stateTransferDetailsOpenButton?.addEventListener("click", openStateTransferDetails);
            stateTransferDetailsCloseButton?.addEventListener("click", () => closeStateTransferDetails());
            stateTransferDetailsOverlay?.addEventListener("click", event => {
                if (event.target === event.currentTarget) closeStateTransferDetails();
            });
            stateTransferDetailsOverlay?.addEventListener("keydown", event => {
                if (event.key === "Escape") {
                    event.preventDefault?.();
                    closeStateTransferDetails();
                } else if (event.key === "Tab") {
                    event.preventDefault?.();
                    stateTransferDetailsCloseButton?.focus?.({ preventScroll: true });
                }
            });
        }

        return {
            applyStateTransfer,
            compareSelectedPlayer,
            closeStateTransferDetails,
            copyFromSelectedPlayer,
            fetchSnapshot,
            invalidateStateTransferPreview,
            openStateTransferDetails,
            previewStateTransfer,
            renderComparison,
            renderOptions,
            snapshotSummary,
            swapStateTransferDirection,
            updateStateTransferWriteControl,
            wire,
        };
    }
    function collectPlayerToolsElements(doc = document) {
        return {
            comparePlayerSelect: doc.getElementById("comparePlayerSelect"),
            copySourcePlayerSelect: doc.getElementById("copySourcePlayerSelect"),
            copyInventoryArea: doc.getElementById("copyInventoryArea"),
            copyEnderArea: doc.getElementById("copyEnderArea"),
            copyStatsArea: doc.getElementById("copyStatsArea"),
            playerToolsPanel: doc.getElementById("playerToolsPanel"),
            compareButton: doc.getElementById("btnComparePlayer"),
            copyButton: doc.getElementById("btnCopyFromPlayer"),
            stateTransferSourcePlayerSelect: doc.getElementById("stateTransferSourcePlayerSelect"),
            stateTransferTargetPlayerSelect: doc.getElementById("stateTransferTargetPlayerSelect"),
            stateTransferPreview: doc.getElementById("stateTransferPreview"),
            stateTransferPreviewButton: doc.getElementById("btnPreviewStateTransfer"),
            stateTransferApplyButton: doc.getElementById("btnApplyStateTransfer"),
            stateTransferSwapButton: doc.getElementById("btnSwapStateTransfer"),
            stateTransferDetailsOpenButton: doc.getElementById("btnOpenStateTransferDetails"),
            stateTransferDetailsOverlay: doc.getElementById("stateTransferDetailsOverlay"),
            stateTransferDetailsBody: doc.getElementById("stateTransferDetailsBody"),
            stateTransferDetailsCloseButton: doc.getElementById("btnCloseStateTransferDetails"),
        };
    }

    function createInventoryPlayerToolsController({ doc = document, ...deps } = {}) {
        return createPlayerToolsController({
            ...deps,
            elements: collectPlayerToolsElements(doc),
        });
    }

    function requirePlayerLoadController() {
        const controller = window.MCBEPlayerLoadController;
        if (!controller) throw new Error("MCBEPlayerLoadController must be loaded before using player-load helpers.");
        return controller;
    }

    function collectPlayerLoadElements(...args) {
        return requirePlayerLoadController().collectPlayerLoadElements(...args);
    }

    function createInventoryPlayerLoadController(...args) {
        return requirePlayerLoadController().createInventoryPlayerLoadController(...args);
    }

    function createPlayerLoadController(...args) {
        return requirePlayerLoadController().createPlayerLoadController(...args);
    }

    window.MCBEPlayerTools = {
        editablePlayers,
        collectPlayerToolsElements,
        createInventoryPlayerToolsController,
        collectPlayerLoadElements,
        createInventoryPlayerLoadController,
        copyFromPlayerRequestModel,
        playerByKey,
        playerListStatusHtml,
        playerRowElement,
        playerRowHtml,
        playerRowModel,
        playerToolOptionModels,
        playerToolOptionsHtml,
        snapshotSummaryForComparison,
        stripUntransferableRootEquipment,
        createPlayerToolsController,
        createPlayerLoadController,
    };
}());
