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

        function previewContextKey() {
            return `${getWorldPath()}\n${getCurrentPlayerKey()}`;
        }

        function clearPreview() {
            lastPreview = null;
            lastPreviewContext = "";
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
            const stats = {};
            doc.querySelectorAll(".mount-stat-field[data-stat-key]").forEach(input => {
                const key = input.getAttribute("data-stat-key");
                if (!key) return;
                const value = statNumberFromInput(input);
                if (value !== null) stats[key] = value;
            });
            selectedMountStats = stats;
            const tamedCheckbox = elements().statTamedCheckbox;
            if (tamedCheckbox) selectedMountTamed = tamedCheckbox.checked === true;
            return stats;
        }

        function mountStatsForCreate() {
            const stats = updateMountStatsFromDom();
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

        function previewSafetySummary(preview = {}) {
            const search = preview?.placement_search || {};
            const safe = Number(search.placement_safe_count || 0);
            const unsafe = Number(search.placement_unsafe_count || 0);
            const unchecked = Number(search.placement_unchecked_count || 0);
            if (safe || unsafe || unchecked) {
                return t("{safe} sicher, {unsafe} nicht sicher, {unchecked} ungeprüft", { safe, unsafe, unchecked });
            }
            return t("Blockfreiheit ist noch nicht geprüft");
        }

        function candidateSelectionMessage(candidate = {}) {
            const safety = candidate.safe_to_place === true ? t("sicher geprüft") : t("ungeprüft");
            return candidate?.id ? t("Kandidat gewählt: {id} · {safety}", { id: candidate.id, safety }) : t("Kandidat gewählt.");
        }

        // Ein Re-Render ersetzt das Panel-Markup vollständig, also auch die
        // <details>-Zustände. Ohne das hier klappt eine gelesene Hinweisliste
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

        function renderIdle(message = "", status = "info") {
            ensureSelectableCandidate();
            const el = elements();
            const reopen = openDisclosureKeys();
            render.applyMountPanelState({
                previewPanel: el.previewPanel,
                optionsPanel: el.optionsPanel,
                statusPanel: el.statusPanel,
                preview: lastPreview,
                message,
                status: message ? status : "",
                selectedMountType,
                selectedPlacementRadius,
                horseProfile: selectedHorseProfile,
                mountStats: selectedMountStats,
                mountTamed: selectedMountTamed,
                pendingMounts,
            });
            restoreOpenDisclosures(reopen);
            wireButtons();
            // Das Optionspanel wird vollständig ersetzt. Neue Edit-Controls
            // müssen noch im selben synchronen Render-Schritt den aktuellen
            // Write-Gate-Zustand erhalten.
            syncEditControls();
        }

        async function loadPreview() {
            if (!apiClient) return;
            if (!hasReferencePlayer()) {
                showToast(t("Lade zuerst einen Spieler."), "warning");
                renderIdle(t("Lade zuerst eine Welt und einen Spieler."));
                return;
            }
            const mountType = updateSelectedMountTypeFromDom();
            const placementRadius = updateSelectedPlacementRadiusFromDom();
            const requestId = ++previewRequestId;
            const requestedContext = previewContextKey();
            updateHorseProfileFromDom();
            updateMountStatsFromDom();
            const el = elements();
            if (el.statusPanel) {
                el.statusPanel.className = "mount-create-status loading";
                el.statusPanel.textContent = t("Mount-Vorschau wird geladen...");
            }
            try {
                const preview = await apiClient.previewMountOrThrow({
                    worldPath: getWorldPath(),
                    playerKey: getCurrentPlayerKey(),
                    mountType,
                    placementRadius,
                });
                if (requestId !== previewRequestId || requestedContext !== previewContextKey()) return false;
                lastPreview = preview;
                lastPreviewContext = requestedContext;
                selectedMountType = lastPreview?.mount_type || mountType;
                selectedPlacementRadius = lastPreview?.placement_search?.radius || placementRadius;
                ensureSelectableCandidate();
                const msg = lastPreview?.can_create
                    ? t("Vorschau geladen. Kandidaten im Umkreis von {radius} Blöcken. {summary}.", { radius: selectedPlacementRadius, summary: previewSafetySummary(lastPreview) })
                    : t("Vorschau geladen. Create ist für diesen Mount-Typ oder diese Dimension deaktiviert.");
                renderIdle(msg, lastPreview?.can_create ? "warning" : "info");
                logStatus(t("Mount-Vorschau geladen"), "success");
                return true;
            } catch (error) {
                if (requestId !== previewRequestId || requestedContext !== previewContextKey()) return false;
                const message = error?.message || t("Mount-Vorschau konnte nicht geladen werden.");
                renderIdle(message, "error");
                showToast(message, "error");
                return false;
            }
        }

        async function queueMount() {
            if (guardEditingAction()) return false;
            if (!hasReferencePlayer()) {
                showToast(t("Lade zuerst einen Spieler."), "warning");
                renderIdle(t("Lade zuerst eine Welt und einen Spieler."));
                return;
            }
            if (!lastPreview || !lastPreview.can_create || lastPreviewContext !== previewContextKey()) {
                clearPreview();
                showToast(t("Lade zuerst eine Mount-Vorschau mit aktivem Create."), "warning");
                renderIdle(t("Lade zuerst eine Mount-Vorschau mit aktivem Create."));
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
                const confirmed = confirmUncheckedCreate(
                    t("Diese Position konnte nicht sicher geprüft werden. Mount ({label}) trotzdem als ungespeicherte Änderung vormerken? Vor dem Speichern wird die Position erneut geprüft.", { label: mountLabel })
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
            renderIdle(t("{label} vorgemerkt. Noch nicht in die Welt geschrieben.", { label: mountLabel }), "warning");
            showToast(t("{label} als ungespeicherte Änderung vorgemerkt.", { label: mountLabel }), "success");
            logStatus(t("Mount vorgemerkt"), "warning");
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
            renderIdle(committed.length === 1 ? t("1 Mount atomar gespeichert. Direkte Validierung: OK.") : t("{count} Mounts atomar gespeichert. Direkte Validierung: OK.", { count: committed.length }), "success");
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
                renderIdle(t("Pferd-Eigenschaften geändert."));
            }, { once: true });
            doc.querySelectorAll(".mount-horse-profile-field").forEach(input => {
                input.addEventListener("change", () => {
                    updateHorseProfileFromDom();
                    refreshMountIcons();
                    const currentClass = elements().statusPanel?.className || "mount-create-status info";
                    if (elements().statusPanel && !currentClass.includes("error")) {
                        elements().statusPanel.className = "mount-create-status info";
                        elements().statusPanel.textContent = t("Pferd-Eigenschaften geändert.");
                    }
                });
            });
        }

        function wireMountStatsControls() {
            doc.querySelectorAll(".mount-stat-field").forEach(input => {
                input.addEventListener("change", () => updateMountStatsFromDom());
            });
            // Neu rendern: Zähmen entfernt das Temper-Tag, also verschwindet auch
            // das Eingabefeld, statt einen Wert anzubieten, den der Server verwirft.
            elements().statTamedCheckbox?.addEventListener("change", () => {
                updateMountStatsFromDom();
                renderIdle(selectedMountTamed ? t("Wird gezähmt erzeugt.") : t("Wird wild erzeugt."));
            }, { once: true });
        }

        function wireCandidateMap() {
            doc.querySelectorAll(".mount-map-point").forEach(button => {
                button.addEventListener("click", () => {
                    if (button.disabled) return;
                    const candidate = rememberSelectedCandidate(button.getAttribute("data-candidate-id") || "");
                    if (!candidate) return;
                    renderIdle(candidateSelectionMessage(candidate));
                }, { once: true });
            });
        }

        function wireTechOverlay() {
            const el = elements();
            const closeOverlay = () => {
                const current = elements();
                current.techOverlay?.classList.remove("open");
                current.techDetailsButton?.focus();
            };
            el.techDetailsButton?.addEventListener("click", () => {
                const current = elements();
                current.techOverlay?.classList.add("open");
                current.techCloseButton?.focus();
            });
            el.techCloseButton?.addEventListener("click", closeOverlay);
            el.techOverlay?.addEventListener("click", event => {
                if (event.target === elements().techOverlay) closeOverlay();
            });
            el.techOverlay?.addEventListener("keydown", event => {
                if (event.key === "Escape") closeOverlay();
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
                renderIdle(t("Mount-Typ geändert. Lade eine neue Vorschau."));
            }, { once: true });
            el.placementRadiusInput?.addEventListener("change", () => {
                updateSelectedPlacementRadiusFromDom();
                updateHorseProfileFromDom();
                updateMountStatsFromDom();
                clearPreview();
                renderIdle(t("Suchradius geändert. Lade eine neue Vorschau."));
            }, { once: true });
            el.previewButton?.addEventListener("click", loadPreview, { once: true });
            doc.querySelectorAll("[data-remove-pending-mount]").forEach(button => {
                button.addEventListener("click", () => removePendingMount(button.getAttribute("data-remove-pending-mount") || ""), { once: true });
            });
            doc.getElementById("btnMountDiscardPending")?.addEventListener("click", () => clearPendingMounts({ recordUndo: true }), { once: true });
            doc.getElementById("btnMountReviewPending")?.addEventListener("click", onReviewRequested, { once: true });
            if (el.createButton) {
                const enabled = Boolean(lastPreview?.can_create && lastPreviewContext === previewContextKey() && hasSelectableCandidate());
                const selectedCandidate = enabled ? selectedCandidateFromDom() : null;
                const unchecked = Boolean(selectedCandidate && candidateIsUnchecked(selectedCandidate));
                el.createButton.disabled = !enabled;
                el.createButton.textContent = unchecked ? t("Mount vormerken (ungeprüft)") : t("Mount vormerken");
                el.createButton.title = !enabled
                    ? t("Create ist nur nach einer Vorschau mit auswählbarem Kandidaten verfügbar.")
                    : unchecked
                        ? t("Position wurde nicht sicher geprüft. Vor dem Vormerken musst du bestätigen.")
                        : t("Merkt das gewählte Mount als ungespeicherte Änderung vor.");
                if (enabled) el.createButton.addEventListener("click", queueMount, { once: true });
            }
        }

        function refresh() {
            clearPreview();
            if (!hasReferencePlayer()) {
                renderIdle(t("Lade zuerst eine Welt und einen Spieler."));
                return;
            }
            renderIdle(t("Bereit für eine Mount-Vorschau."));
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
