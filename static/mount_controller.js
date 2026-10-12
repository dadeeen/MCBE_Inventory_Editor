(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));

    const DEFAULT_CREATE_MODE = "synthetic_full";
    const DEFAULT_HORSE_PROFILE = {
        mode: "random_like_game",
        health: 25,
        movement: 0.175,
        jump_strength: 0.5,
        color: 0,
        mark_variant: 1,
    };

    function createMountController({
        doc = document,
        apiClient = null,
        getWorldPath = () => "",
        getCurrentPlayerKey = () => "",
        getCurrentPlayer = () => null,
        showToast = () => {},
        logStatus = () => {},
        onPendingChanged = () => {},
        onReviewRequested = () => {},
        pushUndo = () => {},
        guardEditingAction = () => false,
        syncEditControls = () => {},
        confirmUncheckedCreate = message => window.confirm(message),
        confirmUnknownServerWrite = message => window.confirm(message),
        render = window.MCBEMountView,
    } = {}) {
        let lastPreview = null;
        let selectedMountType = "minecraft:horse";
        let selectedPlacementRadius = 6;
        let selectedHorseProfile = { ...(render?.DEFAULT_HORSE_PROFILE || DEFAULT_HORSE_PROFILE) };
        // Wie das Pferd-Profil: Werte überleben Re-Renders (Kandidaten-Klick etc.).
        let selectedMountStats = {};
        let selectedMountTamed = false;
        let pendingMounts = [];
        let previewRequestId = 0;
        let lastPreviewContext = "";
        let previewLoading = false;
        let modelPreview = null;
        let modelView = null;

        function previewContextKey() {
            return `${getWorldPath()}\n${getCurrentPlayerKey()}`;
        }

        function clearPreview() {
            lastPreview = null;
            lastPreviewContext = "";
            previewLoading = false;
            previewRequestId += 1;
        }

        function elements() {
            return {
                panel: doc.getElementById("mountsPanel"),
                previewPanel: doc.getElementById("mountPreviewPanel"),
                optionsPanel: doc.getElementById("mountOptionsPanel"),
                pendingPanel: doc.getElementById("mountPendingPanel"),
                statusPanel: doc.getElementById("mountCreateStatus"),
                previewButton: doc.getElementById("btnMountPreview"),
                createButton: doc.getElementById("btnMountCreate"),
                mountTypeSelect: doc.getElementById("mountTypeSelect"),
                placementRadiusInput: doc.getElementById("mountPlacementRadiusInput"),
                horseProfileMode: doc.getElementById("mountHorseProfileMode"),
                horseHealthInput: doc.getElementById("mountHorseHealthInput"),
                horseMovementInput: doc.getElementById("mountHorseMovementInput"),
                horseJumpInput: doc.getElementById("mountHorseJumpInput"),
                horseColorSelect: doc.getElementById("mountHorseColorSelect"),
                horseMarkSelect: doc.getElementById("mountHorseMarkSelect"),
                horseTemperInput: doc.getElementById("mountHorseTemperInput"),
                // Werte werden generisch über .mount-stat-field gelesen; hier stehen
                // nur Felder mit eigener Verdrahtung (Live-Hinweis, Haken).
                statJumpInput: doc.getElementById("mountStatJumpInput"),
                statTemperInput: doc.getElementById("mountStatTemperInput"),
                statTamedCheckbox: doc.getElementById("mountStatTamedCheckbox"),
                techOverlay: doc.getElementById("mountTechOverlay"),
                techDetailsButton: doc.getElementById("btnMountTechDetails"),
                techCloseButton: doc.getElementById("btnMountTechClose"),
            };
        }

        function hasReferencePlayer() {
            return Boolean(getWorldPath() && getCurrentPlayerKey() && getCurrentPlayer());
        }

        function updateSelectedMountTypeFromDom() {
            const value = elements().mountTypeSelect?.value;
            if (value) selectedMountType = value;
            return selectedMountType;
        }

        function updateSelectedPlacementRadiusFromDom() {
            const raw = elements().placementRadiusInput?.value;
            const parsed = Number.parseInt(raw, 10);
            if (Number.isFinite(parsed)) selectedPlacementRadius = Math.max(2, Math.min(16, parsed));
            return selectedPlacementRadius;
        }

        function numberFromDom(element, fallback, minimum, maximum) {
            const parsed = Number.parseFloat(element?.value);
            if (!Number.isFinite(parsed)) return fallback;
            return Math.max(minimum, Math.min(maximum, parsed));
        }

        function intFromDom(element, fallback, minimum, maximum) {
            const parsed = Number.parseInt(element?.value, 10);
            if (!Number.isFinite(parsed)) return fallback;
            return Math.max(minimum, Math.min(maximum, parsed));
        }

        function updateHorseProfileFromDom() {
            const el = elements();
            // A different species has no horse controls. Keep its last profile.
            if (!el.horseProfileMode) return selectedHorseProfile;
            const mode = el.horseProfileMode?.value === "custom" ? "custom" : "random_like_game";
            selectedHorseProfile = {
                mode,
                health: numberFromDom(el.horseHealthInput, selectedHorseProfile.health ?? DEFAULT_HORSE_PROFILE.health, 15, 30),
                movement: numberFromDom(el.horseMovementInput, selectedHorseProfile.movement ?? DEFAULT_HORSE_PROFILE.movement, 0.1125, 0.3375),
                jump_strength: numberFromDom(el.horseJumpInput, selectedHorseProfile.jump_strength ?? DEFAULT_HORSE_PROFILE.jump_strength, 0.4, 1),
                color: intFromDom(el.horseColorSelect, selectedHorseProfile.color ?? DEFAULT_HORSE_PROFILE.color, 0, 6),
                mark_variant: intFromDom(el.horseMarkSelect, selectedHorseProfile.mark_variant ?? DEFAULT_HORSE_PROFILE.mark_variant, 0, 4),
                temper: intFromDom(el.horseTemperInput, selectedHorseProfile.temper ?? DEFAULT_HORSE_PROFILE.temper, 0, 99),
            };
            return selectedHorseProfile;
        }

        function horseProfileForCreate() {
            const profile = updateHorseProfileFromDom();
            if (profile.mode !== "custom") {
                return {
                    mode: "random_like_game",
                    seed: `${Date.now()}-${Math.random()}`,
                };
            }
            return {
                mode: "custom",
                health: profile.health,
                movement: profile.movement,
                jump_strength: profile.jump_strength,
                color: profile.color,
                mark_variant: profile.mark_variant,
                temper: profile.temper,
            };
        }

        function finiteOrNull(value) {
            if (typeof render?.finiteInput === "function") return render.finiteInput(value);
            return value == null || value === "" || !Number.isFinite(Number(value)) ? null : Number(value);
        }

        function statNumberFromInput(input) {
            // Grenzen kommen aus den min/max-Attributen des Inputs (eine Quelle:
            // MOUNT_STATS_FIELDS in der View); der Server validiert autoritativ.
            if (!input) return null;
            const value = finiteOrNull(input.value);
            if (value === null) return null;
            const min = Number(input.min);
            const max = Number(input.max);
            return Math.min(Number.isFinite(max) ? max : value, Math.max(Number.isFinite(min) ? min : value, value));
        }

        function updateMountStatsFromDom() {
            // Nur Vanilla-variable Felder; leere Eingaben bleiben "zufällig wie im Spiel".
            // Die Feldliste steht allein in MOUNT_STATS_FIELDS (View); hier wird
            // generisch über data-stat-key gelesen, damit ein neues Feld nicht an
            // zwei Stellen nachgezogen werden muss.
            // A temporarily hidden wild-only field keeps its draft value.
            const stats = { ...selectedMountStats };
            doc.querySelectorAll(".mount-stat-field[data-stat-key]").forEach(input => {
                const key = input.getAttribute("data-stat-key");
                if (!key) return;
                const value = statNumberFromInput(input);
                if (value !== null) stats[key] = value;
                else delete stats[key];
            });
            selectedMountStats = stats;
            const tamedCheckbox = elements().statTamedCheckbox;
            if (tamedCheckbox) selectedMountTamed = tamedCheckbox.checked === true;
            return stats;
        }

        function mountStatsForCreate() {
            const stats = { ...updateMountStatsFromDom() };
            if (selectedMountTamed) delete stats.temper;
            return Object.keys(stats).length ? stats : null;
        }

        function mountTamedForCreate() {
            updateMountStatsFromDom();
            return selectedMountTamed === true;
        }

        function hasNumericProfileValues(profile = {}) {
            return [profile.health, profile.movement, profile.jump_strength, profile.color, profile.mark_variant]
                .every(value => Number.isFinite(Number(value)));
        }

        function conversionSuffix(profile = {}) {
            const speed = typeof render?.movementHintText === "function" ? render.movementHintText(profile.movement) : "";
            const jump = typeof render?.jumpHintText === "function" ? render.jumpHintText(profile.jump_strength) : "";
            if (!speed && !jump) return "";
            return ` [${[speed, jump].filter(Boolean).join(", ")}]`;
        }

        function horseProfileStatusLabel(profile = selectedHorseProfile) {
            if (profile.mode === "custom") {
                return ` ${t("Profil: manuell ({health} Leben, Bewegung {movement}, Sprung {jump})", { health: profile.health, movement: profile.movement, jump: profile.jump_strength })}${conversionSuffix(profile)}`;
            }
            if (hasNumericProfileValues(profile)) {
                return ` ${t("Profil: zufällig geschrieben ({health} Leben, Bewegung {movement}, Sprung {jump}, Farbe {color}, Markierung {mark})", { health: profile.health, movement: Number(profile.movement).toFixed(4), jump: Number(profile.jump_strength).toFixed(3), color: profile.color, mark: profile.mark_variant })}${conversionSuffix(profile)}`;
            }
            return ` ${t("Profil: zufällig wie im Spiel")}`;
        }

        function unknownServerWriteMessage(writeGate = {}) {
            const status = writeGate.server_status || {};
            return [
                t("Serverstatus konnte nicht sicher geprüft werden."),
                writeGate.reason || "",
                status.message ? t("Status: {message}", { message: status.message }) : "",
                status.server_host ? `Server: ${status.server_host}:${status.server_port || "?"}` : "",
                t("Nur fortfahren, wenn der Bedrock-Server sicher gestoppt ist. Mount trotzdem schreiben?"),
            ].filter(Boolean).join("\n");
        }

        function candidateIsUnsafe(candidate = {}) {
            return candidate?.safe_to_place === false;
        }

        function candidateIsUnchecked(candidate = {}) {
            return candidate?.safe_to_place !== true && !candidateIsUnsafe(candidate);
        }

        function selectableCandidates() {
            const candidates = Array.isArray(lastPreview?.candidate_positions) ? lastPreview.candidate_positions : [];
            return candidates.filter(candidate => candidate && !candidateIsUnsafe(candidate));
        }

        function hasSelectableCandidate() {
            return selectableCandidates().length > 0;
        }

        function rememberSelectedCandidate(candidateId = "") {
            if (!lastPreview || !candidateId) return null;
            const candidates = Array.isArray(lastPreview.candidate_positions) ? lastPreview.candidate_positions : [];
            const candidate = candidates.find(item => item?.id === candidateId) || null;
            if (!candidate || candidateIsUnsafe(candidate)) return null;
            lastPreview = {
                ...lastPreview,
                selected_candidate_id: candidateId,
                selected_position: {
                    x: candidate.x,
                    y: candidate.y,
                    z: candidate.z,
                },
            };
            return candidate;
        }

        function ensureSelectableCandidate() {
            if (!lastPreview) return null;
            const candidates = Array.isArray(lastPreview.candidate_positions) ? lastPreview.candidate_positions : [];
            const selected = candidates.find(candidate => candidate?.id === lastPreview?.selected_candidate_id) || null;
            if (selected && !candidateIsUnsafe(selected)) return rememberSelectedCandidate(selected.id);
            const preferred = candidates.find(candidate => candidate?.safe_to_place === true) || candidates.find(candidate => !candidateIsUnsafe(candidate)) || null;
            if (!preferred) return null;
            return rememberSelectedCandidate(preferred.id);
        }

        function selectedCandidateFromDom() {
            const selectedId = lastPreview?.selected_candidate_id || "";
            const candidates = Array.isArray(lastPreview?.candidate_positions) ? lastPreview.candidate_positions : [];
            const candidate = candidates.find(item => item?.id === selectedId) || null;
            if (candidate && !candidateIsUnsafe(candidate)) return candidate;
            return ensureSelectableCandidate();
        }

        function selectedPreferredOffsetFromDom() {
            const candidate = selectedCandidateFromDom();
            const offset = candidate?.offset;
            if (!offset) return null;
            return {
                x: Number(offset.x) || 0,
                y: Number(offset.y) || 0,
                z: Number(offset.z) || 0,
            };
        }

        function placementSafetyLabel(result = {}) {
            const safety = result?.placement_safety;
            if (!safety) return "";
            if (safety.status === "safe") return ` ${t("Platzierung: sicher geprüft")}`;
            if (safety.status === "unsafe") return ` ${t("Platzierung: nicht sicher")}`;
            return ` ${t("Platzierung: ungeprüft")}`;
        }

        // Ein Re-Render ersetzt das Panel-Markup vollständig, also auch die
        // <details>-Zustände. Ohne das hier klappen geöffnete Blockdaten
        // beim nächsten Kandidatenklick wieder zu.
        // Auf das Mount-Panel begrenzt: die App hat noch andere <details>, und
        // dieser Controller hat kein Recht, fremde Aufklapper anzufassen.
        function disclosureNodes() {
            const panel = elements().panel;
            return panel ? panel.querySelectorAll("details[data-disclosure]") : [];
        }

        function openDisclosureKeys() {
            const keys = new Set();
            disclosureNodes().forEach(node => {
                if (node.open) keys.add(node.getAttribute("data-disclosure"));
            });
            return keys;
        }

        function restoreOpenDisclosures(keys) {
            if (!keys || !keys.size) return;
            disclosureNodes().forEach(node => {
                // Nur öffnen, nie schließen: ein frisch gerendertes "offen"
                // (z. B. blockiertes Erzeugen) darf nicht überschrieben werden.
                if (keys.has(node.getAttribute("data-disclosure"))) node.open = true;
            });
        }

        function captureFocus() {
            const active = doc.activeElement;
            if (!active || !elements().panel?.contains?.(active)) return null;
            return {
                id: active.id,
                candidateId: active.getAttribute?.("data-candidate-id"),
                modelAction: active.getAttribute?.("data-model-action"),
                disclosure: active.tagName === "SUMMARY" ? active.parentElement?.getAttribute("data-disclosure") : null,
                pendingId: active.getAttribute?.("data-remove-pending-mount"),
                pendingIndex: Array.from(doc.querySelectorAll("[data-remove-pending-mount]")).indexOf(active),
            };
        }

        function restoreFocus(focus) {
            if (!focus) return;
            let target = focus.id ? doc.getElementById(focus.id) : null;
            if (!target && focus.candidateId) {
                target = Array.from(doc.querySelectorAll(".mount-map-point")).find(node => node.getAttribute("data-candidate-id") === focus.candidateId);
            }
            if (!target && focus.modelAction) {
                target = Array.from(doc.querySelectorAll("[data-model-action]")).find(node => node.getAttribute("data-model-action") === focus.modelAction);
            }
            if (!target && focus.disclosure) {
                const disclosure = Array.from(disclosureNodes()).find(node => node.getAttribute("data-disclosure") === focus.disclosure);
                target = disclosure?.querySelector("summary");
            }
            if (!target && focus.pendingId) {
                const buttons = Array.from(doc.querySelectorAll("[data-remove-pending-mount]"));
                target = buttons.find(node => node.getAttribute("data-remove-pending-mount") === focus.pendingId)
                    || buttons[Math.min(focus.pendingIndex, buttons.length - 1)]
                    || doc.getElementById("btnMountCreate") || doc.getElementById("btnMountPreview");
            }
            if (!target && focus.id === "btnMountDiscardPending") {
                target = doc.getElementById("btnMountCreate") || doc.getElementById("btnMountPreview");
            }
            if (target && !target.disabled) target.focus({ preventScroll: true });
        }

        function renderIdle(message = "", status = "info") {
            ensureSelectableCandidate();
            const el = elements();
            const reopen = openDisclosureKeys();
            const focus = captureFocus();
            if (modelPreview) {
                modelView = modelPreview.getView();
                modelPreview.destroy();
                modelPreview = null;
            }
            render.applyMountPanelState({
                previewPanel: el.previewPanel,
                optionsPanel: el.optionsPanel,
                pendingPanel: el.pendingPanel,
                statusPanel: el.statusPanel,
                preview: lastPreview,
                message: previewLoading ? t("Standplätze werden geprüft…") : message,
                status: previewLoading ? "loading" : message ? status : "",
                selectedMountType,
                selectedPlacementRadius,
                horseProfile: selectedHorseProfile,
                mountStats: selectedMountStats,
                mountTamed: selectedMountTamed,
                pendingMounts,
                hasReferencePlayer: hasReferencePlayer(),
            });
            restoreOpenDisclosures(reopen);
            const modelRoot = doc.getElementById("mountModelPreview");
            if (modelRoot && window.MCBEMountModelPreview) {
                modelPreview = window.MCBEMountModelPreview.attach(modelRoot, {
                    mountType: selectedMountType,
                    horseProfile: selectedHorseProfile,
                    mountTamed: selectedMountTamed,
                    view: modelView,
                });
            }
            el.previewPanel?.setAttribute?.("aria-busy", String(previewLoading));
            wireButtons();
            // Das Optionspanel wird vollständig ersetzt. Neue Edit-Controls
            // müssen noch im selben synchronen Render-Schritt den aktuellen
            // Write-Gate-Zustand erhalten.
            syncEditControls();
            restoreFocus(focus);
        }

        async function loadPreview() {
            if (!apiClient) return;
            if (!hasReferencePlayer()) {
                showToast(t("Lade zuerst einen Spieler."), "warning");
                renderIdle();
                return;
            }
            const mountType = updateSelectedMountTypeFromDom();
            const placementRadius = updateSelectedPlacementRadiusFromDom();
            let returnFocusToPreview = doc.activeElement?.id === "btnMountPreview";
            const cancelFocusReturn = () => { returnFocusToPreview = false; };
            const focusEvents = ["pointerdown", "keydown", "focusin"];
            const requestId = ++previewRequestId;
            const requestedContext = previewContextKey();
            updateHorseProfileFromDom();
            updateMountStatsFromDom();
            // Keep the old view visible during the request, but invalidate its
            // write context immediately. Even a failed refresh cannot stage it.
            lastPreviewContext = "";
            previewLoading = true;
            renderIdle();
            // Disabling and replacing the initiating button drops native focus.
            // Return it on completion only if the user did not move on meanwhile.
            focusEvents.forEach(name => doc.addEventListener?.(name, cancelFocusReturn));
            try {
                const preview = await apiClient.previewMountOrThrow({
                    worldPath: getWorldPath(),
                    playerKey: getCurrentPlayerKey(),
                    mountType,
                    placementRadius,
                });
                if (requestId !== previewRequestId || requestedContext !== previewContextKey()) return false;
                updateHorseProfileFromDom();
                updateMountStatsFromDom();
                previewLoading = false;
                lastPreview = preview;
                lastPreviewContext = requestedContext;
                selectedMountType = lastPreview?.mount_type || mountType;
                selectedPlacementRadius = lastPreview?.placement_search?.radius || placementRadius;
                ensureSelectableCandidate();
                renderIdle();
                logStatus(t("Mount-Vorschau geladen"), "success");
                return true;
            } catch (error) {
                if (requestId !== previewRequestId || requestedContext !== previewContextKey()) return false;
                const message = error?.message || t("Mount-Vorschau konnte nicht geladen werden.");
                updateHorseProfileFromDom();
                updateMountStatsFromDom();
                lastPreview = null;
                lastPreviewContext = "";
                previewLoading = false;
                renderIdle(message, "error");
                showToast(message, "error");
                return false;
            } finally {
                focusEvents.forEach(name => doc.removeEventListener?.(name, cancelFocusReturn));
                if (returnFocusToPreview && requestId === previewRequestId && requestedContext === previewContextKey()
                    && (!doc.activeElement || doc.activeElement === doc.body)) {
                    elements().previewButton?.focus({ preventScroll: true });
                }
            }
        }

        async function queueMount() {
            if (previewLoading) return false;
            if (guardEditingAction()) return false;
            if (!hasReferencePlayer()) {
                showToast(t("Lade zuerst einen Spieler."), "warning");
                renderIdle();
                return;
            }
            if (!lastPreview || !lastPreview.can_create || lastPreviewContext !== previewContextKey()) {
                clearPreview();
                showToast(t("Prüfe zuerst einen geeigneten Standplatz."), "warning");
                renderIdle(t("Prüfe zuerst einen geeigneten Standplatz."));
                return;
            }
            const isHorse = lastPreview.mount_type === "minecraft:horse";
            const mountLabel = t(lastPreview.mount_label || "Mount");
            const placementRadius = updateSelectedPlacementRadiusFromDom();
            const horseProfile = isHorse ? horseProfileForCreate() : null;
            const mountStats = isHorse ? null : mountStatsForCreate();
            const tamed = isHorse ? false : mountTamedForCreate();
            const chosenCandidate = selectedCandidateFromDom();
            if (!chosenCandidate) {
                const message = t("Kein sicher oder ungeprüft auswählbarer Kandidat vorhanden.");
                renderIdle(message, "error");
                showToast(message, "error");
                return;
            }
            if (candidateIsUnsafe(chosenCandidate)) {
                const message = chosenCandidate.warning || t("Dieser Kandidat ist nicht sicher platzierbar.");
                renderIdle(message, "error");
                showToast(message, "error");
                return;
            }
            const allowUncheckedPlacement = candidateIsUnchecked(chosenCandidate);
            if (allowUncheckedPlacement) {
                const reason = chosenCandidate.warning || t("Position noch nicht bewertet.");
                const confirmed = confirmUncheckedCreate(
                    `${reason}\n\n${t("Diese Position konnte nicht sicher geprüft werden. Mount ({label}) trotzdem als ungespeicherte Änderung vormerken? Vor dem Speichern wird die Position erneut geprüft.", { label: mountLabel })}`
                );
                if (!confirmed) {
                    renderIdle(t("Erzeugen abgebrochen: Position war ungeprüft."), "info");
                    return;
                }
            }
            if (chosenCandidate?.id) rememberSelectedCandidate(chosenCandidate.id);
            const preferredOffset = selectedPreferredOffsetFromDom();
            const selectedPosition = { ...(lastPreview.selected_position || {}) };
            pushUndo(t("{label} vormerken", { label: mountLabel }));
            pendingMounts.push({
                id: `mount-${Date.now()}-${Math.random().toString(16).slice(2)}`,
                worldPath: getWorldPath(),
                playerKey: getCurrentPlayerKey(),
                mountType: lastPreview.mount_type,
                mountLabel,
                createMode: DEFAULT_CREATE_MODE,
                placementRadius,
                preferredOffset,
                selectedPosition,
                horseProfile,
                mountStats,
                tamed,
                allowUncheckedPlacement,
                safetyStatus: chosenCandidate.safe_to_place === true ? "safe" : "unchecked",
                serverGuardEpoch: lastPreview.server_guard_epoch,
            });
            onPendingChanged(getPendingMounts());
            const status = allowUncheckedPlacement ? "warning" : "success";
            renderIdle();
            showToast(t("{label} als ungespeicherte Änderung vorgemerkt.", { label: mountLabel }), "success");
            logStatus(t("Mount vorgemerkt"), status);
        }

        function getPendingMounts() {
            return pendingMounts.map(mount => JSON.parse(JSON.stringify(mount)));
        }

        function removePendingMount(id) {
            const before = pendingMounts.length;
            const next = pendingMounts.filter(mount => mount.id !== id);
            if (next.length === before) return;
            pushUndo(t("Vorgemerkten Mount entfernen"));
            pendingMounts = next;
            onPendingChanged(getPendingMounts());
            renderIdle(t("Vorgemerkten Mount entfernt."), "info");
        }

        function setPendingMounts(mounts = [], { renderPanel = true, notify = true } = {}) {
            pendingMounts = Array.isArray(mounts) ? mounts.map(mount => JSON.parse(JSON.stringify(mount))) : [];
            if (notify) onPendingChanged(getPendingMounts());
            if (renderPanel) renderIdle(pendingMounts.length ? t("Vorgemerkte Mounts aus Verlauf wiederhergestellt.") : t("Keine Mounts vorgemerkt."), "info");
        }

        function clearPendingMounts({ renderPanel = true, recordUndo = false } = {}) {
            if (!pendingMounts.length) return;
            if (recordUndo) pushUndo(t("Alle vorgemerkten Mounts verwerfen"));
            pendingMounts = [];
            onPendingChanged([]);
            if (renderPanel) renderIdle(t("Vorgemerkte Mounts verworfen."), "info");
        }

        function finalizePendingMounts(results = [], { validationFailed = false } = {}) {
            const committed = Array.isArray(results) ? results : [];
            const expected = pendingMounts.length;
            // Diese Funktion wird ausschließlich nach einem bestätigten Schreibvorgang
            // aufgerufen. Die Vormerkungen sind damit verbraucht und werden immer
            // geleert – auch bei abweichender Ergebnisanzahl. Ein Wurf würde den
            // Speichern-Button fälschlich wieder freigeben und ein erneutes Schreiben
            // desselben committeten Batches erlauben.
            pendingMounts = [];
            onPendingChanged([]);
            const countMismatch = committed.length !== expected;
            const validationBroken = committed.some(result => result?.post_create_validation?.ok !== true);
            // Der Batch ist committed. Bei unvollständiger Antwort oder fehlgeschlagener
            // Validierung ist ein Neuladen nötig; der Aufrufer darf dann keinen normalen
            // Erfolg mehr anzeigen. Das Ergebnis signalisiert diesen Zustand strukturiert.
            const reloadRequired = validationFailed || countMismatch || validationBroken;
            if (reloadRequired) {
                const message = countMismatch
                    ? t("Mounts wurden geschrieben, aber die Serverantwort ist unvollständig ({count} von {expected} bestätigt). Nicht erneut speichern; Welt neu laden und Backup prüfen.", { count: committed.length, expected })
                    : committed.length === 1
                        ? t("1 Mount wurde geschrieben, aber die Nachvalidierung ist fehlgeschlagen. Nicht erneut speichern; Backup prüfen.")
                        : t("{count} Mounts wurden geschrieben, aber die Nachvalidierung ist fehlgeschlagen. Nicht erneut speichern; Backup prüfen.", { count: committed.length });
                renderIdle(message, "error");
                return { complete: false, reloadRequired: true, committedCount: committed.length, expected, reason: countMismatch ? "count_mismatch" : "validation_failed" };
            }
            renderIdle(committed.length === 1 ? t("1 Mount gespeichert und geprüft.") : t("{count} Mounts gespeichert und geprüft.", { count: committed.length }), "success");
            return { complete: true, reloadRequired: false, committedCount: committed.length, expected };
        }

        function wireConversionHints() {
            const el = elements();
            el.horseMovementInput?.addEventListener("input", () => {
                const hint = doc.getElementById("mountHorseMovementHint");
                if (hint && typeof render?.movementHintText === "function") hint.textContent = render.movementHintText(elements().horseMovementInput?.value);
            });
            el.statJumpInput?.addEventListener("input", () => {
                const hint = doc.getElementById("mountStatJumpHint");
                if (hint && typeof render?.jumpHintText === "function") hint.textContent = render.jumpHintText(elements().statJumpInput?.value);
            });
            el.horseJumpInput?.addEventListener("input", () => {
                const hint = doc.getElementById("mountHorseJumpHint");
                if (hint && typeof render?.jumpHintText === "function") hint.textContent = render.jumpHintText(elements().horseJumpInput?.value);
            });
            el.statTemperInput?.addEventListener("input", () => {
                const hint = doc.getElementById("mountStatTemperHint");
                if (hint && typeof render?.temperHintText === "function") hint.textContent = render.temperHintText(elements().statTemperInput?.value);
            });
            el.horseTemperInput?.addEventListener("input", () => {
                const hint = doc.getElementById("mountHorseTemperHint");
                if (hint && typeof render?.temperHintText === "function") hint.textContent = render.temperHintText(elements().horseTemperInput?.value);
            });
        }

        function refreshMountIcons() {
            modelPreview?.update({ mountType: selectedMountType, horseProfile: selectedHorseProfile, mountTamed: selectedMountTamed });
            if (typeof render?.mountIconSvg !== "function") return;
            const color = selectedHorseProfile?.color ?? 0;
            doc.querySelectorAll(".mount-type-row .mount-icon").forEach(node => {
                node.outerHTML = render.mountIconSvg(selectedMountType, color, 34);
            });
            doc.querySelectorAll(".mount-summary-icon .mount-icon").forEach(node => {
                node.outerHTML = render.mountIconSvg(lastPreview?.mount_type || selectedMountType, color, 44);
            });
        }

        function wireHorseProfileControls() {
            const el = elements();
            wireConversionHints();
            el.horseProfileMode?.addEventListener("change", () => {
                updateHorseProfileFromDom();
                renderIdle();
            }, { once: true });
            doc.querySelectorAll(".mount-horse-profile-field").forEach(input => {
                const update = () => {
                    updateHorseProfileFromDom();
                    refreshMountIcons();
                };
                input.addEventListener("input", update);
                input.addEventListener("change", update);
            });
        }

        function wireMountStatsControls() {
            doc.querySelectorAll(".mount-stat-field").forEach(input => {
                input.addEventListener("input", () => updateMountStatsFromDom());
                input.addEventListener("change", () => updateMountStatsFromDom());
            });
            // Neu rendern: Zähmen entfernt das Temper-Tag, also verschwindet auch
            // das Eingabefeld, statt einen Wert anzubieten, den der Server verwirft.
            elements().statTamedCheckbox?.addEventListener("change", () => {
                updateMountStatsFromDom();
                renderIdle();
            }, { once: true });
        }

        function wireCandidateMap() {
            doc.querySelectorAll(".mount-map-point").forEach(button => {
                if (previewLoading) button.disabled = true;
                button.addEventListener("click", () => {
                    if (button.disabled) return;
                    const candidate = rememberSelectedCandidate(button.getAttribute("data-candidate-id") || "");
                    if (!candidate) return;
                    updateHorseProfileFromDom();
                    updateMountStatsFromDom();
                    renderIdle();
                }, { once: true });
            });
        }

        function wireTechOverlay() {
            const el = elements();
            const closeOverlay = () => el.techOverlay?.close();
            el.techDetailsButton?.addEventListener("click", () => {
                el.techOverlay?.showModal();
                doc.getElementById("mountTechTitle")?.focus();
            });
            el.techCloseButton?.addEventListener("click", closeOverlay);
            el.techOverlay?.addEventListener("close", () => elements().techDetailsButton?.focus({ preventScroll: true }));
            el.techOverlay?.addEventListener("click", event => {
                if (event.target === el.techOverlay) closeOverlay();
            });
            el.techOverlay?.addEventListener("keydown", event => {
                if (event.key !== "Tab") return;
                const nodes = Array.from(el.techOverlay.querySelectorAll("button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), summary, [tabindex='0']"))
                    .filter(node => node.getClientRects().length > 0);
                const first = nodes[0];
                const last = nodes[nodes.length - 1];
                if (first && ((!nodes.includes(doc.activeElement)) || (event.shiftKey && doc.activeElement === first) || (!event.shiftKey && doc.activeElement === last))) {
                    event.preventDefault();
                    (event.shiftKey ? last : first).focus();
                }
            });
        }

        function wireButtons() {
            const el = elements();
            wireHorseProfileControls();
            wireMountStatsControls();
            wireCandidateMap();
            wireTechOverlay();
            el.mountTypeSelect?.addEventListener("change", () => {
                updateSelectedMountTypeFromDom();
                updateHorseProfileFromDom();
                // Andere Typen haben andere Felder; alte Werte nicht mitnehmen.
                selectedMountStats = {};
                selectedMountTamed = false;
                clearPreview();
                renderIdle();
            }, { once: true });
            el.placementRadiusInput?.addEventListener("change", () => {
                updateSelectedPlacementRadiusFromDom();
                updateHorseProfileFromDom();
                updateMountStatsFromDom();
                clearPreview();
                renderIdle();
            }, { once: true });
            if (el.previewButton) {
                el.previewButton.disabled = previewLoading || !hasReferencePlayer();
                el.previewButton.textContent = previewLoading ? t("Wird geprüft…") : lastPreview ? t("Erneut prüfen") : t("Standplätze prüfen");
                el.previewButton.className = `btn ${lastPreview ? "btn-secondary" : "btn-primary"}`;
                el.previewButton.addEventListener("click", loadPreview, { once: true });
            }
            doc.querySelectorAll("[data-remove-pending-mount]").forEach(button => {
                button.addEventListener("click", () => removePendingMount(button.getAttribute("data-remove-pending-mount") || ""), { once: true });
            });
            doc.getElementById("btnMountDiscardPending")?.addEventListener("click", () => clearPendingMounts({ recordUndo: true }), { once: true });
            doc.getElementById("btnMountReviewPending")?.addEventListener("click", onReviewRequested, { once: true });
            if (el.createButton) {
                const enabled = Boolean(!previewLoading && lastPreview?.can_create && lastPreviewContext === previewContextKey() && hasSelectableCandidate());
                const selectedCandidate = enabled ? selectedCandidateFromDom() : null;
                const unchecked = Boolean(selectedCandidate && candidateIsUnchecked(selectedCandidate));
                el.createButton.disabled = !enabled;
                el.createButton.textContent = unchecked ? t("Mount vormerken (ungeprüft)") : t("Mount vormerken");
                el.createButton.title = !enabled
                    ? (render.queueDisabledReason?.(lastPreview) || t("Prüfe zuerst einen geeigneten Standplatz."))
                    : unchecked
                        ? t("Position wurde nicht sicher geprüft. Vor dem Vormerken musst du bestätigen.")
                        : t("Merkt das gewählte Mount als ungespeicherte Änderung vor.");
                if (enabled) el.createButton.addEventListener("click", queueMount, { once: true });
            }
        }

        function refresh() {
            clearPreview();
            if (!hasReferencePlayer()) {
                renderIdle();
                return;
            }
            renderIdle();
        }

        return {
            clearPendingMounts,
            finalizePendingMounts,
            getPendingMounts,
            loadPreview,
            queueMount,
            refresh,
            setPendingMounts,
        };
    }

    window.MCBEMountController = {
        createMountController,
    };
}());
