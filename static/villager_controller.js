(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));
    const model = window.MCBEVillagerModel;
    const STALE_CODES = new Set(["villager_snapshot_stale", "villager_preview_stale", "world_changed_while_reading", "server_guard_stale"]);

    function initialState() {
        return { worldPath: "", worldLabel: "", worldRevision: "", guardEpoch: 0, guardToken: "", loadedAt: 0,
            rows: [], selected: new Set(), activeId: "", detail: null, loaded: false, scanning: false,
            busy: false, saving: false, preferencesBusy: false, readOnly: false, blockedReason: "", staleReason: "",
            message: "", messageKind: "", progress: "", diagnostics: [], preferences: { revision: "", aliases: {}, regions: [] },
            filters: { query: "", profession: "", tier: "", dimension: "", region: "", injured: false, editable: false },
            sort: "name", direction: "asc", page: 1, pageSize: 50, mapDimension: "0", mapOpen: false, regionsOpen: false,
            mapPlayers: [], mapPlayerMode: "selected", selectedPlayerKey: "",
            pending: [], preview: null, previewSource: "", previewNotice: "", previewNoticeKind: "",
            detailDirty: false, nameDirty: false, inventoryDirty: false, batchDirty: false, aliasDirty: false, regionDirty: false };
    }

    function createVillagerController({ doc = document, api, view = window.MCBEVillagerView.createVillagerView({ doc }),
        getWorldPath = () => "", getWorldLabel = () => "", getWriteGate = () => ({}), getServerGuard = () => ({}),
        getReadOnly = () => false, getIsBusy = () => false, getSessionId = () => "", getActiveView = () => "villagers",
        getSelectedPlayerKey = () => "",
        showToast = () => {}, showConfirmDialog = async () => false, buildErrorMessage = data => data?.error || t("Fehler"),
        copyTextToClipboard = async () => {}, confirmPresenceConflict = async () => false,
        onReviewRequested = () => {}, onPendingChanged = () => {}, onBusyChanged = () => {}, onDraftChanged = () => {}, onWorldWritten = () => {}, onWriteGate = () => {},
    } = {}) {
        let state = initialState();
        let scanRequest = null, detailRequest = null, previewRequest = null;
        let generation = 0;
        let wired = false;
        let rowIndexSource = null, rowIndex = new Map();
        let regionBaseline = "";
        let detailOpener = null;
        let previewOpener = null;
        let refreshAfterCommit = false;
        const el = id => view.element(id);
        const value = id => el(id)?.value ?? "";
        const checked = id => el(id)?.checked === true;
        const rowById = id => {
            if (rowIndexSource !== state.rows) {
                rowIndexSource = state.rows;
                rowIndex = new Map(state.rows.map(row => [row.id, row]));
            }
            return rowIndex.get(id);
        };
        const current = (request, slot) => request === slot && request.generation === generation && request.worldPath === getWorldPath();
        const regionFields = { Id: "id", Name: "name", Dimension: "dimension", MinX: "min_x", MaxX: "max_x", MinZ: "min_z", MaxZ: "max_z", MinY: "min_y", MaxY: "max_y" };
        const filterControls = { query: "villagerSearch", profession: "villagerProfession", tier: "villagerTier", dimension: "villagerDimension",
            region: "villagerRegion", injured: "villagerOnlyInjured", editable: "villagerOnlyEditable" };

        function message(text, kind = "") { state.message = text; state.messageKind = kind; }

        function readContext() {
            const gate = getWriteGate() || {};
            state.readOnly = getReadOnly() === true;
            state.blockedReason = state.readOnly ? t("Read-Only-Modus: Namen, Gesundheit, Vorräte, Regionen und Aliase können nicht gespeichert werden.")
                : getIsBusy() ? t("Eine andere Lade- oder Speicheraktion läuft. Warte, bis sie abgeschlossen ist.")
                : gate.allowed === false && gate.requires_unknown_server_confirmation !== true
                    ? gate.reason || t("Schreiben ist aktuell gesperrt.") : "";
        }

        function render() {
            readContext();
            state.selectedPlayerKey = getSelectedPlayerKey();
            const page = view.render(state);
            state.page = page.page;
        }

        function inputDiffers(id, original) {
            const input = el(id);
            if (input?.validity?.badInput) return true;
            const raw = String(input?.value ?? "").trim();
            // A cleared value means "unchanged", just as in the preview API.
            return raw !== "" && (!Number.isFinite(Number(raw)) || Number(raw) !== original);
        }

        function updateHealthDirty(single) {
            if (!single) {
                state.batchDirty = checked("villagerBatchHeal") || ["villagerBatchMax", "villagerBatchCurrent"]
                    .some(id => el(id)?.validity?.badInput || String(value(id)).trim() !== "");
                return;
            }
            const health = state.detail?.health;
            if (!health) { state.detailDirty = false; return; }
            const maxChanged = health.max_editable !== false && inputDiffers("villagerDetailMax", health.max);
            const maxInput = String(value("villagerDetailMax")).trim();
            const maximum = health.max_editable !== false && maxInput ? Number(maxInput) : health.max;
            state.detailDirty = maxChanged || (checked("villagerDetailHeal")
                ? maximum !== health.current : inputDiffers("villagerDetailCurrent", health.current));
        }

        function updateNameDirty() {
            const original = state.detail?.name || "", draft = value("villagerName");
            state.nameDirty = !!state.detail?.name_editable && draft !== original && draft.trim() !== original;
        }

        function setNameDraft(name) {
            if (state.busy || state.scanning || state.preferencesBusy || state.blockedReason || state.staleReason || !state.detail?.name_editable) return;
            if (el("villagerName")) el("villagerName").value = name;
            updateNameDirty(); invalidatePreview(); render(); onDraftChanged();
            el("villagerName")?.focus();
        }

        function updateAliasDirty() {
            const key = model.aliasKey(state.detail || rowById(state.activeId));
            state.aliasDirty = !!state.activeId && !!key && String(value("villagerAlias")).trim() !== (state.preferences.aliases[key] || "");
        }

        function inventoryDrafts() {
            return Object.fromEntries((state.detail?.inventory?.slots || []).filter(slot => slot.editable).map(slot => [slot.slot, {
                name: value(`villagerStockItem${slot.slot}`), count: value(`villagerStockCount${slot.slot}`),
                invalid: el(`villagerStockCount${slot.slot}`)?.validity?.badInput === true,
            }]));
        }

        function updateInventoryDirty() {
            const inventory = state.detail?.inventory;
            const drafts = inventoryDrafts();
            state.inventoryDirty = !!inventory?.editable && (inventory.slots || [])
                .some(slot => window.MCBEVillagerInventory.slotDiffers(slot, drafts[slot.slot]));
        }

        function resetInventory() {
            if (state.saving || state.scanning || !state.detail?.inventory) return;
            invalidatePreview();
            for (const slot of state.detail.inventory.slots || []) {
                if (el(`villagerStockItem${slot.slot}`)) el(`villagerStockItem${slot.slot}`).value = slot.item?.name || "";
                if (el(`villagerStockCount${slot.slot}`)) el(`villagerStockCount${slot.slot}`).value = String(slot.item?.count || 0);
            }
            state.inventoryDirty = false;
            render(); onDraftChanged();
        }

        function regionSignature(region = null) {
            return JSON.stringify(Object.entries(regionFields).map(([control, key]) => {
                const node = el(`villagerRegion${control}`);
                const raw = String(region ? region[key] ?? "" : node?.value ?? "").trim();
                const numeric = control !== "Id" && control !== "Name";
                return [key, numeric && raw && Number.isFinite(Number(raw)) ? Number(raw) : raw,
                    !region && numeric && node?.validity?.badInput === true];
            }));
        }

        function updateRegionDirty() { state.regionDirty = regionSignature() !== regionBaseline; }

        function focusBookmark() {
            const target = doc.activeElement;
            if (!el("villagerDetail")?.contains?.(target)) return null;
            return { id: target?.id, action: target?.dataset?.action, start: target?.selectionStart, end: target?.selectionEnd };
        }

        function restoreDetailFocus(bookmark) {
            if (!bookmark || getActiveView() !== "villagers" || modalOpen()) return;
            const box = el("villagerDetail");
            const target = bookmark.id ? el(bookmark.id)
                : [...(box?.querySelectorAll?.("[data-action]") || [])].find(node => node.dataset.action === bookmark.action);
            const destination = target && box?.contains?.(target) ? target : el("villagerDetailTitle");
            destination?.focus?.({ preventScroll: true });
            if (Number.isInteger(bookmark.start) && typeof destination?.setSelectionRange === "function") {
                try { destination.setSelectionRange(bookmark.start, bookmark.end); } catch { /* Numeric fields have no caret API. */ }
            }
        }

        function focusListOpener(id) {
            if (getActiveView() !== "villagers") return;
            const rowButton = [...(el("villagerRows")?.querySelectorAll?.('[data-action="detail"]') || [])].find(node => node.dataset.id === id);
            const mapButton = detailOpener?.fromMap && state.mapOpen
                ? [...(el("villagerMap")?.querySelectorAll?.('[data-action="map-detail"]') || [])].find(node => node.dataset.id === id) : null;
            const original = detailOpener?.element;
            const stillVisible = original?.isConnected !== false && !original?.closest?.("[hidden], [inert]")
                && (!original?.getClientRects || original.getClientRects().length > 0);
            (mapButton || rowButton || (stillVisible ? original : null) || el("villagerSearch") || el("villagersTitle"))?.focus?.();
            detailOpener = null;
        }

        function canReceiveFocus(target) {
            return target && target !== doc.body && target !== doc.documentElement && target.isConnected !== false
                && !target.disabled && !target.matches?.(":disabled") && !target.hidden && !target.closest?.("[hidden], [inert]")
                && (!target.getClientRects || target.getClientRects().length > 0) && typeof target.focus === "function";
        }

        function restorePreviewFocus(bookmark, { afterSave = false } = {}) {
            if (!bookmark || bookmark.worldPath !== getWorldPath() || bookmark.worldPath !== state.worldPath
                || bookmark.generation !== generation || getActiveView() !== "villagers" || modalOpen()
                || (bookmark.single && bookmark.activeId !== state.activeId)) return;
            // A save includes an asynchronous rescan. Never overwrite a focus
            // position the user has chosen while that refresh was running.
            if (afterSave && canReceiveFocus(doc.activeElement) && !el("villagerPreviewDialog")?.contains?.(doc.activeElement)) return;
            const original = [bookmark.element, bookmark.id ? el(bookmark.id) : null].find(canReceiveFocus);
            const rowButton = [...(el("villagerRows")?.querySelectorAll?.('[data-action="detail"]') || [])]
                .find(node => node.dataset.id === bookmark.rowId);
            const candidates = afterSave
                ? [state.activeId ? el("villagerDetailTitle") : null, rowButton, el("villagerSearch")]
                : [original, el(bookmark.single ? "villagerDetailCurrent" : "villagerBatchMax"),
                    state.activeId ? el("villagerDetailTitle") : null, el("villagerSearch")];
            candidates.find(canReceiveFocus)?.focus({ preventScroll: true });
        }

        function dismissPreview(event) {
            event?.preventDefault?.();
            if (state.saving) return;
            const bookmark = el("villagerPreviewDialog")?.open ? previewOpener : null;
            invalidatePreview(); onDraftChanged(); render();
            restorePreviewFocus(bookmark);
        }

        function captureDetailDraft() {
            const inputs = [];
            if (state.detailDirty && state.detail?.health) {
                const health = state.detail.health;
                if (health.max_editable !== false && inputDiffers("villagerDetailMax", health.max)) inputs.push("villagerDetailMax");
                if (checked("villagerDetailHeal")) inputs.push("villagerDetailHeal");
                else if (inputDiffers("villagerDetailCurrent", health.current)) inputs.push("villagerDetailCurrent");
            }
            if (state.nameDirty) inputs.push("villagerName");
            if (state.aliasDirty) inputs.push("villagerAlias");
            if (state.inventoryDirty) {
                const drafts = inventoryDrafts();
                for (const slot of state.detail?.inventory?.slots || []) {
                    if (window.MCBEVillagerInventory.slotDiffers(slot, drafts[slot.slot])) inputs.push(`villagerStockItem${slot.slot}`, `villagerStockCount${slot.slot}`);
                }
            }
            // Retaining the actual input also preserves unfinished number text
            // (e.g. a leading minus), which input.value does not expose.
            return inputs.map(id => ({ id, node: el(id), value: value(id), checked: checked(id) }));
        }

        function restoreDetailDraft(inputs) {
            for (const input of inputs) {
                const target = el(input.id);
                if (!target) continue;
                if (input.node && target !== input.node && typeof target.replaceWith === "function") target.replaceWith(input.node);
                else { target.value = input.value; target.checked = input.checked; }
            }
            updateHealthDirty(true);
            updateNameDirty();
            updateAliasDirty();
            updateInventoryDirty();
        }

        async function refreshOpenDetail(request, retainedDraft, row) {
            const previousId = state.activeId;
            if (!previousId) return;
            if (!row) throw new Error(t("Der geöffnete Dorfbewohner ist im neuen Weltstand nicht mehr vorhanden. Deine offenen Eingaben bleiben erhalten; bitte erneut scannen."));
            const id = row.id;
            const data = await api.detail({ world_path: state.worldPath, id, revision: row.revision, world_revision: state.worldRevision }, { signal: request.controller.signal });
            if (!current(request, scanRequest) || request.controller.signal.aborted || state.activeId !== previousId) return;
            requireSuccess(data, t("Dorfbewohnerdetails konnten nicht geladen werden."));
            if (data.villager?.id !== id || data.villager?.revision !== row.revision) throw new Error(t("Die Detailantwort gehört nicht zum geladenen Dorfbewohner."));
            const draft = retainedDraft?.id === previousId ? retainedDraft.inputs : captureDetailDraft(), focus = focusBookmark();
            if (draft.some(input => input.id.startsWith("villagerStock")
                && !data.villager.inventory?.slots?.find(slot => slot.slot === Number(input.id.match(/\d+$/)?.[0]))?.editable)) {
                throw new Error(t("Ein geänderter Vorratsplatz ist im neuen Weltstand geschützt. Deine Eingaben bleiben erhalten; bitte erneut scannen."));
            }
            if (draft.some(input => input.id === "villagerName") && !data.villager.name_editable) {
                throw new Error(t("Der Name ist im neuen Weltstand geschützt. Deine Eingabe bleibt erhalten; bitte erneut scannen."));
            }
            state.activeId = id;
            state.detail = data.villager;
            view.renderDetail(data.villager, state);
            restoreDetailDraft(draft);
            render();
            restoreDetailFocus(focus);
        }

        function invalidatePreview() {
            const interrupted = !!previewRequest;
            previewRequest?.controller.abort(); previewRequest = null;
            if (interrupted && !state.saving) { state.busy = false; message(""); }
            if (state.preview || el("villagerPreviewDialog")?.open) {
                state.preview = null;
                if (!state.saving) el("villagerPreviewDialog")?.close();
            }
            state.previewSource = "";
            state.previewNotice = "";
            previewOpener = null;
            return interrupted;
        }

        function deactivate() {
            if (state.saving || (!previewRequest && !state.preview && !el("villagerPreviewDialog")?.open)) return;
            invalidatePreview(); render(); onDraftChanged();
        }

        function invalidate(reason) {
            if (!state.loaded || state.staleReason) return;
            state.staleReason = reason;
            state.pending.forEach(entry => { entry.staleReason = reason; });
            detailRequest?.controller.abort(); detailRequest = null;
            invalidatePreview();
            state.busy = false;
            render();
        }

        function resetWorld(worldPath) {
            scanRequest?.controller.abort(); scanRequest = null;
            detailRequest?.controller.abort(); detailRequest = null;
            previewRequest?.controller.abort(); previewRequest = null;
            generation += 1;
            rowIndexSource = null; rowIndex.clear(); detailOpener = null; previewOpener = null;
            el("villagerPreviewDialog")?.close();
            state = initialState();
            state.worldPath = worldPath;
            state.worldLabel = getWorldLabel();
            for (const id of ["villagerSearch", "villagerBatchMax", "villagerBatchCurrent"]) if (el(id)) el(id).value = "";
            for (const id of ["villagerOnlyInjured", "villagerOnlyEditable", "villagerBatchHeal"]) if (el(id)) el(id).checked = false;
            resetRegionForm();
            view.renderDetail(null, state);
        }

        function updateContext({ reset = false } = {}) {
            const worldPath = getWorldPath() || "";
            if (reset || worldPath !== state.worldPath) resetWorld(worldPath);
            state.worldLabel = getWorldLabel();
            const guard = getServerGuard() || {};
            const gate = getWriteGate() || {};
            if (!state.saving && model.snapshotIsStale(state, { worldPath, guardToken: guard.token, guardEpoch: guard.epoch,
                serverOnline: gate.server_status?.status === "online" })) {
                invalidate(t("Der Serverzustand hat sich geändert. Die Dorfbewohnerliste ist veraltet. Stoppe den Server und scanne erneut."));
            }
            render();
        }

        function observeWorldStatus(data, { worldPath, startedAt } = {}) {
            // A poll started before this snapshot may legitimately return the
            // previous fingerprint after a save/rescan has already completed.
            if (!state.loaded || state.scanning || state.saving || worldPath !== state.worldPath
                || !Number.isFinite(startedAt) || startedAt < state.loadedAt) return;
            if (model.snapshotIsStale(state, { worldPath, worldRevision: data?.world_fingerprint })) {
                invalidate(t("Die Welt wurde seit dem Scan verändert. Scanne die Dorfbewohner erneut, bevor du Details lädst oder Änderungen speicherst."));
            }
        }

        function hasPendingChanges() {
            return Boolean(state.pending.length || state.preview || state.detailDirty || state.nameDirty || state.inventoryDirty || state.batchDirty || state.aliasDirty || state.regionDirty);
        }

        function reportError(error, fallback) {
            if (error?.name === "AbortError") return;
            const data = error?.data;
            const text = data ? buildErrorMessage(data, fallback) : error?.message || fallback;
            if (data?.write_gate) onWriteGate(data.write_gate);
            if (STALE_CODES.has(data?.code)) invalidate(text);
            message(text, "error");
            showToast(text, "error", 6500);
        }

        function requireSuccess(data, fallback) {
            if (data?.success) return data;
            const error = new Error(buildErrorMessage(data, fallback));
            error.data = data;
            throw error;
        }

        async function scan({ discard = false, keepMessage = false, keepEdits = false, retainedDraft = null } = {}) {
            updateContext();
            if (!state.worldPath || state.scanning || state.saving || state.preferencesBusy || getIsBusy()) return false;
            const worldPath = state.worldPath;
            if (!discard && hasPendingChanges()) {
                const confirmed = await showConfirmDialog(t("Beim erneuten Scan werden alle Vormerkungen und offenen Eingaben in diesem Reiter verworfen. Jetzt neu scannen?"));
                if (!confirmed || worldPath !== getWorldPath()) return false;
            }
            invalidatePreview();
            detailRequest?.controller.abort(); detailRequest = null;
            if (!keepEdits) {
                state.pending = []; onPendingChanged();
                state.detailDirty = false; state.nameDirty = false; state.inventoryDirty = false; state.batchDirty = false; state.aliasDirty = false;
                state.selected.clear(); state.activeId = ""; state.detail = null; detailOpener = null;
                clearBatchFields();
                resetRegionForm();
                view.renderDetail(null, state);
            }
            if (!keepMessage) message("");
            const previousSelection = keepEdits ? [...state.selected].map(rowById).filter(Boolean) : [];
            const previousDetail = keepEdits ? state.detail || rowById(state.activeId) : null;
            state.scanning = true; state.busy = false; state.progress = "";
            const request = { worldPath, generation, controller: new AbortController() };
            scanRequest = request;
            render(); onDraftChanged();
            try {
                const data = await api.scan(worldPath, { signal: request.controller.signal,
                    onProgress: progress => {
                        if (!current(request, scanRequest)) return;
                        state.progress = t("Gespeicherte Kreaturen werden gelesen … {count} Datensätze geprüft", { count: Number(progress.current) || 0 });
                        render();
                    },
                });
                if (!current(request, scanRequest) || request.controller.signal.aborted) return false;
                requireSuccess(data, t("Dorfbewohner konnten nicht geladen werden."));
                if (!Array.isArray(data.villagers) || typeof data.world_revision !== "string" || !data.world_revision) throw new Error(t("Die Scan-Antwort ist unvollständig. Bitte erneut scannen."));
                state.rows = data.villagers;
                state.mapPlayers = Array.isArray(data.map_players) ? data.map_players : [];
                state.worldRevision = data.world_revision;
                state.guardEpoch = data.server_guard_epoch ?? 0;
                state.guardToken = data.server_guard_token || "";
                const preferences = { revision: data.preferences?.revision || "", aliases: data.preferences?.aliases || {}, regions: data.preferences?.regions || [] };
                if (keepEdits && (state.aliasDirty || state.regionDirty) && preferences.revision !== state.preferences.revision) {
                    // Do not silently bless a settings draft against a newer
                    // revision from another editor session. Its original
                    // optimistic-concurrency guard remains authoritative.
                    message([state.message, t("Die Editor-Einstellungen wurden zwischenzeitlich geändert. Deine offenen Alias- und Regionseingaben bleiben erhalten; lade die Einstellungen vor dem Speichern neu.")].filter(Boolean).join("\n"), "warning");
                } else {
                    state.preferences = preferences;
                }
                if (keepEdits && !state.regionDirty && value("villagerRegionId")) {
                    const region = state.preferences.regions.find(item => item.id === value("villagerRegionId"));
                    if (region) fillRegionForm(region); else resetRegionForm();
                }
                state.diagnostics = data.diagnostics || [];
                state.loaded = true; if (!keepEdits) state.staleReason = "";
                state.page = keepEdits ? state.page : 1; state.loadedAt = Date.now();
                if (state.filters.region && state.filters.region !== "none" && !state.preferences.regions.some(region => region.id === state.filters.region)) state.filters.region = "";
                if (keepEdits) {
                    // Chunk-list positions can be reused or move after another
                    // record disappears. Drafts and selections follow identity,
                    // never whichever villager now occupies the old row ID.
                    const identities = new Map();
                    for (const row of state.rows) {
                        const key = model.aliasKey(row);
                        if (key) identities.set(key, identities.has(key) ? null : row);
                    }
                    const refreshedRow = previous => {
                        if (!previous) return null;
                        const key = model.aliasKey(previous);
                        if (key) return identities.get(key) || null;
                        const candidate = rowById(previous.id);
                        return candidate?.revision === previous.revision ? candidate : null;
                    };
                    state.selected = new Set(previousSelection.map(refreshedRow).filter(Boolean).map(row => row.id));
                    // Health and settings drafts belong to independent forms.
                    // Only a fresh detail snapshot can safely supply untouched
                    // values after another form has committed its change.
                    await refreshOpenDetail(request, retainedDraft, refreshedRow(previousDetail));
                    if (!current(request, scanRequest) || request.controller.signal.aborted) return false;
                    state.staleReason = "";
                }
                return true;
            } catch (error) {
                if (current(request, scanRequest)) {
                    if (keepEdits) state.staleReason = t("Der neue Weltstand konnte nicht vollständig geladen werden. Deine offenen Eingaben bleiben erhalten. Bitte erneut scannen, bevor du Änderungen speicherst.");
                    reportError(error, t("Dorfbewohner konnten nicht geladen werden."));
                }
                return false;
            } finally {
                if (current(request, scanRequest)) {
                    scanRequest = null; state.scanning = false;
                    updateContext(); onDraftChanged();
                }
            }
        }

        function cancelScan() {
            scanRequest?.controller.abort(); scanRequest = null;
            state.scanning = false;
            message(t("Suche abgebrochen. Du kannst jederzeit einen neuen Scan starten."));
            render();
        }

        async function openDetail(id, { fromMap = false, trigger = null } = {}) {
            updateContext();
            if (state.saving || state.scanning || state.busy || state.staleReason) return;
            const row = rowById(id);
            if (!row) return;
            const worldPath = state.worldPath, previousId = state.activeId, requestGeneration = generation;
            if ((state.detailDirty || state.nameDirty || state.inventoryDirty || state.aliasDirty) && state.activeId !== id) {
                const confirmed = await showConfirmDialog(t("Die offenen Eingaben dieses Dorfbewohners verwerfen und einen anderen öffnen?"));
                if (!confirmed || worldPath !== getWorldPath() || requestGeneration !== generation || state.activeId !== previousId) return;
            }
            if (state.activeId === id && state.detail) { el("villagerDetailTitle")?.focus(); return; }
            if (state.activeId === id && detailRequest) return;
            detailOpener = { id, element: trigger || doc.activeElement, fromMap };
            invalidatePreview();
            detailRequest?.controller.abort();
            state.activeId = id; state.detail = null; state.detailDirty = false; state.nameDirty = false; state.inventoryDirty = false; state.aliasDirty = false;
            if (fromMap) {
                const filtered = model.sortedRows(model.filterRows(state.rows, state.filters, state.preferences), state.sort, state.direction, state.preferences);
                const index = filtered.findIndex(item => item.id === id);
                if (index >= 0) state.page = Math.floor(index / state.pageSize) + 1;
            }
            const request = { worldPath, generation, id, controller: new AbortController() };
            detailRequest = request;
            view.renderDetail(row, state, { loading: true }); render();
            if (getActiveView() === "villagers" && !modalOpen()) {
                el("villagerDetailTitle")?.focus({ preventScroll: true });
                if (doc.defaultView?.innerWidth <= 1100) el("villagerDetail")?.scrollIntoView({ behavior: "auto", block: "start" });
            }
            try {
                const data = await api.detail({ world_path: worldPath, id, revision: row.revision, world_revision: state.worldRevision }, { signal: request.controller.signal });
                if (!current(request, detailRequest) || state.activeId !== id || request.controller.signal.aborted) return;
                requireSuccess(data, t("Dorfbewohnerdetails konnten nicht geladen werden."));
                if (data.villager?.id !== id || data.villager?.revision !== row.revision) throw new Error(t("Die Detailantwort gehört nicht zum geladenen Dorfbewohner."));
                const focus = focusBookmark();
                state.detail = data.villager;
                view.renderDetail(data.villager, state); render();
                // A slow response must not steal focus from a search or filter
                // the user has already moved on to in the meantime.
                restoreDetailFocus(focus);
            } catch (error) {
                if (current(request, detailRequest)) {
                    const focus = focusBookmark();
                    reportError(error, t("Dorfbewohnerdetails konnten nicht geladen werden."));
                    view.renderDetail(row, state, { error: error.message }); render();
                    restoreDetailFocus(focus);
                }
            } finally { if (detailRequest === request) detailRequest = null; }
        }

        async function closeDetail() {
            if (state.saving) return;
            const worldPath = state.worldPath, id = state.activeId;
            if (state.detailDirty || state.nameDirty || state.inventoryDirty || state.aliasDirty) {
                const confirmed = await showConfirmDialog(t("Offene Eingaben dieses Dorfbewohners verwerfen?"));
                if (!confirmed || worldPath !== getWorldPath() || state.activeId !== id) return;
            }
            detailRequest?.controller.abort(); detailRequest = null;
            if (previewRequest?.single || ["detail", "inventory", "name"].includes(state.previewSource)) invalidatePreview();
            state.activeId = ""; state.detail = null; state.detailDirty = false; state.nameDirty = false; state.inventoryDirty = false; state.aliasDirty = false;
            render(); onDraftChanged();
            focusListOpener(id);
        }

        function clearBatchFields() {
            for (const id of ["villagerBatchMax", "villagerBatchCurrent"]) if (el(id)) el(id).value = "";
            if (el("villagerBatchHeal")) el("villagerBatchHeal").checked = false;
            state.batchDirty = false;
        }

        function resetBatch() {
            if (state.saving || state.scanning) return;
            invalidatePreview();
            clearBatchFields();
            render(); onDraftChanged();
            [state.selected.size ? el("villagerBatchMax") : null, el("villagerSelectFiltered"), el("villagerSearch"), el("villagersTitle")]
                .find(canReceiveFocus)?.focus();
        }

        function resetDetail() {
            if (state.saving || state.scanning || !state.detail) return;
            invalidatePreview();
            if (el("villagerDetailMax")) el("villagerDetailMax").value = String(state.detail.health?.max ?? "");
            if (el("villagerDetailCurrent")) el("villagerDetailCurrent").value = String(state.detail.health?.current ?? "");
            if (el("villagerDetailHeal")) el("villagerDetailHeal").checked = false;
            state.detailDirty = false;
            render(); onDraftChanged();
            [el("villagerDetailCurrent"), el("villagerDetailTitle")].find(canReceiveFocus)?.focus();
        }

        function healDetail() {
            updateContext();
            if (!state.detail?.editable || state.busy || state.scanning || state.preferencesBusy || state.blockedReason || state.staleReason) return;
            if (el("villagerDetailHeal")) el("villagerDetailHeal").checked = true;
            updateHealthDirty(true);
            invalidatePreview(); render(); onDraftChanged();
            return preview(true);
        }

        function healthInput(single) {
            const prefix = single ? "villagerDetail" : "villagerBatch";
            const maximumEditable = !single || state.detail?.health?.max_editable !== false;
            const heal = checked(`${prefix}Heal`);
            // Number inputs expose unfinished text ("-", "1e", …) as an empty
            // value. Keyboard shortcuts and the heal action bypass native form
            // submission, so check badInput before interpreting empty as unchanged.
            const inputs = [...(maximumEditable ? [`${prefix}Max`] : []), ...(!heal ? [`${prefix}Current`] : [])];
            if (inputs.some(id => el(id)?.validity?.badInput)) throw new Error(t("Lebenspunkte müssen zwischen 1 und 2048 liegen."));
            // A detail form is prefilled. Only changed fields belong in the
            // patch; an untouched original may be below the minimum for new
            // input (e.g. a living villager with 0.5 health).
            return model.healthChanges({
                max: maximumEditable && (!single || inputDiffers(`${prefix}Max`, state.detail?.health?.max)) ? value(`${prefix}Max`) : "",
                current: !single || inputDiffers(`${prefix}Current`, state.detail?.health?.current) ? value(`${prefix}Current`) : "",
                heal,
            });
        }

        async function preview(single = false, kind = "health") {
            updateContext();
            if (kind === "inventory" || kind === "name") single = true;
            if (getActiveView() !== "villagers" || state.busy || state.scanning || state.preferencesBusy || state.blockedReason || state.staleReason || !state.loaded) return;
            const selected = single ? [state.activeId] : [...state.selected];
            if (!selected.length || selected.some(id => !rowById(id))) return;
            let changes;
            try {
                if (kind === "name" && !state.detail?.name_editable) return;
                changes = kind === "name" ? model.nameChanges(value("villagerName")) : kind === "inventory"
                    ? { inventory: window.MCBEVillagerInventory.changes(state.detail?.inventory, inventoryDrafts()) } : healthInput(single);
            } catch (error) { reportError(error); render(); return; }
            // Busy rendering disables the submit control before showModal(), so
            // the native dialog cannot reliably remember its original focus.
            const opener = { element: doc.activeElement, id: doc.activeElement?.id, worldPath: state.worldPath,
                generation, single, activeId: state.activeId, rowId: selected[0] };
            const request = { worldPath: state.worldPath, generation, single, controller: new AbortController() };
            previewRequest?.controller.abort(); previewRequest = request;
            state.busy = true; state.previewNotice = "";
            message(kind === "name" ? t("Namensänderung wird geprüft …") : kind === "inventory" ? t("Vorratsänderungen werden geprüft …") : t("Gesundheitsänderungen werden geprüft …")); render();
            try {
                const data = await api.preview({ world_path: state.worldPath, world_revision: state.worldRevision,
                    selection: selected.map(id => ({ id, revision: rowById(id).revision })), changes,
                    server_guard_epoch: state.guardEpoch, server_guard_token: state.guardToken,
                }, { signal: request.controller.signal });
                if (!current(request, previewRequest) || request.controller.signal.aborted) return;
                if (getActiveView() !== "villagers" || (single && state.activeId !== selected[0])) { message(""); return; }
                requireSuccess(data, t("Die Änderungsvorschau konnte nicht erstellt werden."));
                // A confirmation or another loading dialog may have opened
                // while this read was in flight. Keep its decision and focus
                // intact; the unchanged draft can be previewed again afterwards.
                if (modalOpen()) { message(""); return; }
                state.preview = data; state.previewSource = kind !== "health" ? kind : single ? "detail" : "batch"; state.previewNotice = "";
                previewOpener = opener;
                view.renderPreview(data, state);
                message("");
                el("villagerPreviewDialog")?.showModal();
                el("villagerPreviewCancel")?.focus();
                onDraftChanged();
            } catch (error) {
                if (current(request, previewRequest)) reportError(error, t("Die Änderungsvorschau konnte nicht erstellt werden."));
            } finally {
                if (previewRequest === request) { previewRequest = null; state.busy = false; render(); }
            }
        }

        function save() {
            updateContext();
            const preview = state.preview;
            if (!preview?.preview_token || !preview.change_count || state.busy || state.blockedReason || state.staleReason) return;
            const rows = (preview.rows || []).filter(row => row.status === "changed").map(row => ({ ...row,
                label: model.displayName(rowById(row.id) || row, state.preferences.aliases) }));
            const overlap = state.pending.some(entry => entry.rows.some(old => rows.some(row => row.id === old.id && row.kind === old.kind)));
            if (overlap || state.pending.length >= 64) {
                const text = overlap ? t("Dieser Bereich ist bereits vorgemerkt. Entferne zuerst die ältere Vormerkung.")
                    : t("Höchstens 64 Dorfbewohner-Vorschauen können gemeinsam vorgemerkt werden.");
                state.previewNotice = text; state.previewNoticeKind = "error";
                view.renderPreview(preview, state); return;
            }
            const source = state.previewSource;
            const retained = captureDetailDraft().filter(input => source === "detail" ? !input.id.startsWith("villagerDetail")
                : source === "inventory" ? !input.id.startsWith("villagerStock") : source === "name" ? input.id !== "villagerName" : true);
            state.pending.push({ token: preview.preview_token, worldPath: state.worldPath, rows,
                itemLabels: Object.fromEntries((state.detail?.inventory?.allowed_items || []).map(item => [item.name, item.label])),
                guardEpoch: state.guardEpoch, guardToken: state.guardToken,
                expiresAt: Date.now() + (preview.expires_in || 600) * 1000 });
            if (source === "detail") state.detailDirty = false;
            else if (source === "inventory") state.inventoryDirty = false;
            else if (source === "name") state.nameDirty = false;
            else { clearBatchFields(); state.selected.clear(); }
            invalidatePreview();
            if (state.detail) { view.renderDetail(state.detail, state); restoreDetailDraft(retained); }
            message(t("Änderungen vorgemerkt."));
            render(); onDraftChanged(); onPendingChanged();
            el("villagerReviewPending")?.focus();
        }

        function removePending(index) {
            if (getIsBusy() || !Number.isInteger(index) || index < 0 || index >= state.pending.length) return;
            state.pending.splice(index, 1);
            render(); onDraftChanged(); onPendingChanged();
        }

        function clearPending() {
            state.pending = [];
            render(); onDraftChanged(); onPendingChanged();
        }

        function finalizePending(result = {}) {
            state.pending = [];
            refreshAfterCommit = result.success === true && result.validation_failed !== true;
            if (refreshAfterCommit) message(t("Dorfbewohner gemeinsam gespeichert. Backup: {backup}", { backup: result.backup_file || "—" }));
            invalidate(t("Die Welt wurde gespeichert. Scanne die Dorfbewohner erneut, um den gespeicherten Stand zu sehen."));
            onPendingChanged();
        }

        async function refreshAfterSave() {
            if (!refreshAfterCommit || getIsBusy()) return;
            refreshAfterCommit = false;
            await scan({ discard: true, keepMessage: true, keepEdits: true });
        }

        function rejectPending(result) {
            if (STALE_CODES.has(result?.code)) invalidate(buildErrorMessage(result, t("Die Dorfbewohner-Vorschau ist veraltet.")));
        }

        async function savePreferences(preferences, afterSave = () => {}) {
            updateContext();
            if (!state.loaded || state.busy || state.preferencesBusy || state.readOnly || state.saving || state.scanning || getIsBusy()) return;
            const worldPath = state.worldPath, requestGeneration = generation;
            state.preferencesBusy = true; render();
            try {
                const data = await api.savePreferences({ world_path: worldPath, revision: state.preferences.revision,
                    aliases: preferences.aliases, regions: preferences.regions });
                if (worldPath !== getWorldPath() || requestGeneration !== generation) return;
                requireSuccess(data, t("Editor-Einstellungen konnten nicht gespeichert werden."));
                state.preferences = data.preferences;
                afterSave();
                message(t("Editor-Einstellungen gespeichert."));
                onDraftChanged();
            } catch (error) {
                if (worldPath === getWorldPath() && requestGeneration === generation) reportError(error, t("Editor-Einstellungen konnten nicht gespeichert werden."));
            } finally {
                if (worldPath === getWorldPath() && requestGeneration === generation) { state.preferencesBusy = false; render(); }
            }
        }

        function saveAlias() {
            const key = model.aliasKey(state.detail || rowById(state.activeId));
            if (!state.activeId || !key) return;
            const aliases = { ...state.preferences.aliases };
            const alias = value("villagerAlias").trim();
            if (alias) aliases[key] = alias; else delete aliases[key];
            return savePreferences({ ...state.preferences, aliases }, () => {
                if (state.detail && model.aliasKey(state.detail) === key) {
                    // Reopening this detail while the save is pending renders
                    // the previous alias. Refresh that clean form, but retain
                    // any actual draft and let an in-flight detail render itself.
                    if (!state.aliasDirty && el("villagerAlias")) el("villagerAlias").value = state.preferences.aliases[key] || "";
                    updateAliasDirty();
                }
            });
        }

        function regionInputs() {
            return { id: value("villagerRegionId") || `region-${window.crypto?.randomUUID?.() || `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`}`,
                name: value("villagerRegionName"), dimension: value("villagerRegionDimension"),
                min_x: value("villagerRegionMinX"), max_x: value("villagerRegionMaxX"),
                min_z: value("villagerRegionMinZ"), max_z: value("villagerRegionMaxZ"),
                min_y: value("villagerRegionMinY"), max_y: value("villagerRegionMaxY") };
        }

        function resetRegionForm() {
            el("villagerRegionForm")?.reset();
            if (el("villagerRegionId")) el("villagerRegionId").value = "";
            regionBaseline = regionSignature();
            state.regionDirty = false;
        }

        function fillRegionForm(region) {
            for (const [control, key] of Object.entries(regionFields)) {
                if (el(`villagerRegion${control}`)) el(`villagerRegion${control}`).value = String(region[key] ?? "");
            }
            regionBaseline = regionSignature();
            state.regionDirty = false;
        }

        async function confirmRegionDiscard() {
            if (!state.regionDirty) return true;
            const worldPath = state.worldPath, requestGeneration = generation, signature = regionSignature();
            const confirmed = await showConfirmDialog(t("Offene Regionseingaben verwerfen?"));
            return confirmed && worldPath === getWorldPath() && requestGeneration === generation && signature === regionSignature();
        }

        async function resetRegion() {
            const worldPath = state.worldPath, requestGeneration = generation;
            if (state.preferencesBusy || state.saving || state.scanning || !await confirmRegionDiscard()) return;
            if (worldPath !== getWorldPath() || requestGeneration !== generation) return;
            resetRegionForm();
            render(); onDraftChanged();
            el("villagerRegionName")?.focus();
        }

        function saveRegion() {
            try {
                if (["MinX", "MaxX", "MinZ", "MaxZ", "MinY", "MaxY"].some(field => el(`villagerRegion${field}`)?.validity?.badInput)) {
                    throw new Error(t("Trage für jede verwendete Achse zwei gültige Koordinaten ein."));
                }
                const region = model.normalizeRegion(regionInputs());
                const regions = [...state.preferences.regions.filter(item => item.id !== region.id), region];
                const submitted = regionSignature();
                return savePreferences({ ...state.preferences, regions }, () => {
                    if (regionSignature() === submitted) resetRegionForm();
                    else if (value("villagerRegionId") === region.id) {
                        regionBaseline = regionSignature(region);
                        updateRegionDirty();
                    }
                });
            } catch (error) { reportError(error); render(); }
        }

        async function editRegion(id) {
            const region = state.preferences.regions.find(item => item.id === id);
            const worldPath = state.worldPath, requestGeneration = generation;
            if (!region || state.preferencesBusy || state.saving || state.scanning) return;
            if (value("villagerRegionId") === id) {
                state.regionsOpen = true; render(); el("villagerRegionName")?.focus(); return;
            }
            if (!await confirmRegionDiscard()) return;
            if (worldPath !== getWorldPath() || requestGeneration !== generation) return;
            fillRegionForm(region);
            state.regionsOpen = true;
            render(); onDraftChanged();
            el("villagerRegionName")?.focus();
        }

        async function deleteRegion(id) {
            const region = state.preferences.regions.find(item => item.id === id);
            if (!region) return;
            const worldPath = state.worldPath, requestGeneration = generation;
            const confirmed = await showConfirmDialog(t("Region „{name}“ aus dem Editor entfernen?", { name: region.name }));
            if (!confirmed || worldPath !== getWorldPath() || requestGeneration !== generation) return;
            return savePreferences({ ...state.preferences, regions: state.preferences.regions.filter(item => item.id !== id) }, () => {
                if (state.filters.region === id) state.filters.region = "";
                if (value("villagerRegionId") === id) resetRegionForm();
            });
        }

        function regionFromSelection() {
            const rows = state.rows.filter(row => state.selected.has(row.id));
            if (!rows.length || rows.some(row => !model.hasPosition(row) || !Number.isInteger(row.dimension)) || new Set(rows.map(row => row.dimension)).size !== 1) {
                message(t("Markiere Bewohner mit bekannten Koordinaten in derselben Dimension."), "warning"); render(); return;
            }
            for (const axis of ["x", "z"]) {
                const coords = rows.map(row => row.position[axis]);
                el(`villagerRegionMin${axis.toUpperCase()}`).value = Math.floor(Math.min(...coords));
                el(`villagerRegionMax${axis.toUpperCase()}`).value = Math.ceil(Math.max(...coords));
            }
            el("villagerRegionDimension").value = String(rows[0].dimension);
            updateRegionDirty(); render(); onDraftChanged();
            el("villagerRegionName")?.focus();
        }

        function filteredRows() { return model.sortedRows(model.filterRows(state.rows, state.filters, state.preferences), state.sort, state.direction, state.preferences); }
        function changeSelection(ids, selected) {
            if (state.busy) return;
            const next = new Set(state.selected);
            for (const id of ids) if (rowById(id)) { if (selected) next.add(id); else next.delete(id); }
            if (next.size > 1000) {
                message(t("Pro Bearbeitung sind höchstens 1000 Dorfbewohner möglich. Grenze die Liste mit Filtern ein."), "warning"); render(); return;
            }
            state.selected = next;
            invalidatePreview(); render();
        }

        function resetFilters() {
            state.filters = initialState().filters; state.page = 1;
            for (const [key, id] of Object.entries(filterControls)) {
                if (!el(id)) continue;
                if (typeof state.filters[key] === "boolean") el(id).checked = false;
                else el(id).value = "";
            }
            render();
            el("villagerSearch")?.focus();
        }

        function removeFilter(key, trigger) {
            if (!Object.hasOwn(filterControls, key)) return;
            const restoreFocus = doc.activeElement === trigger || trigger?.contains?.(doc.activeElement);
            const control = el(filterControls[key]);
            if (typeof state.filters[key] === "boolean") { state.filters[key] = false; if (control) control.checked = false; }
            else { state.filters[key] = ""; if (control) control.value = ""; }
            state.page = 1;
            render();
            if (restoreFocus) {
                const advanced = ["tier", "dimension", "editable"].includes(key) && !el("villagerMoreFilters")?.open;
                (advanced ? el("villagerMoreFilters")?.querySelector?.("summary") || el("villagerSearch") : control)?.focus();
            }
        }

        function modalOpen() {
            return Boolean(el("villagerPreviewDialog")?.open || doc.querySelector?.("dialog[open]")
                || [...(doc.querySelectorAll?.(".modal-overlay, .loading-overlay") || [])].some(node => node.getClientRects?.().length > 0));
        }

        function wire() {
            if (wired) return;
            wired = true;
            const on = (id, type, handler) => el(id)?.addEventListener(type, handler);
            on("villagerScan", "click", () => scan());
            on("villagerCancelScan", "click", cancelScan);
            on("villagerSearch", "input", () => { state.filters.query = value("villagerSearch"); state.page = 1; render(); });
            for (const [id, key] of [["villagerProfession", "profession"], ["villagerTier", "tier"], ["villagerDimension", "dimension"], ["villagerRegion", "region"]]) {
                on(id, "change", () => {
                    state.filters[key] = value(id); state.page = 1;
                    if (key === "dimension" && state.filters.dimension !== "" && Number.isInteger(Number(state.filters.dimension))) state.mapDimension = state.filters.dimension;
                    render();
                });
            }
            for (const [id, key] of [["villagerOnlyInjured", "injured"], ["villagerOnlyEditable", "editable"]]) on(id, "change", () => { state.filters[key] = checked(id); state.page = 1; render(); });
            on("villagerResetFilters", "click", resetFilters);
            on("villagerSort", "change", () => { state.sort = value("villagerSort"); state.direction = "asc"; state.page = 1; render(); });
            on("villagerSortDirection", "click", () => { state.direction = state.direction === "asc" ? "desc" : "asc"; state.page = 1; render(); });
            on("villagerPreviousPage", "click", () => { state.page -= 1; render(); });
            on("villagerNextPage", "click", () => { state.page += 1; render(); });
            on("villagerSelectPage", "change", () => changeSelection(model.pageRows(filteredRows(), state.page, state.pageSize).rows.map(row => row.id), checked("villagerSelectPage")));
            on("villagerSelectFiltered", "click", () => changeSelection(filteredRows().map(row => row.id), true));
            on("villagerClearSelection", "click", () => changeSelection([...state.selected], false));
            on("villagerMapDimension", "change", () => { state.mapDimension = value("villagerMapDimension"); render(); });
            on("villagerMapPlayers", "change", () => { state.mapPlayerMode = value("villagerMapPlayers"); render(); });
            on("villagerMapToggle", "click", () => { state.mapOpen = !state.mapOpen; render(); });
            on("villagerRegionsToggle", "click", () => { state.regionsOpen = !state.regionsOpen; render(); });
            on("villagerRegionForm", "submit", event => { event.preventDefault(); saveRegion(); });
            on("villagerRegionReset", "click", resetRegion);
            on("villagerRegionUseSelection", "click", regionFromSelection);
            on("villagerBatchForm", "submit", event => { event.preventDefault(); preview(false); });
            on("villagerBatchReset", "click", resetBatch);
            on("villagerSave", "click", save);
            on("villagerReviewPending", "click", onReviewRequested);
            on("villagerPendingRows", "click", event => {
                const button = event.target.closest("[data-remove-pending]");
                if (button) removePending(Number(button.dataset.removePending));
            });
            for (const id of ["villagerPreviewCancel", "villagerPreviewClose"]) on(id, "click", dismissPreview);
            on("villagerPreviewDialog", "cancel", dismissPreview);
            on("villagersPanel", "submit", event => {
                if (event.target.id === "villagerDetailHealthForm") { event.preventDefault(); preview(true); }
                if (event.target.id === "villagerInventoryForm") { event.preventDefault(); preview(true, "inventory"); }
                if (event.target.id === "villagerNameForm") { event.preventDefault(); preview(true, "name"); }
                if (event.target.id === "villagerAliasForm") { event.preventDefault(); saveAlias(); }
            });
            on("villagersPanel", "input", event => {
                const id = event.target.id || "";
                if (["villagerDetailMax", "villagerDetailCurrent", "villagerDetailHeal"].includes(id)) updateHealthDirty(true);
                else if (event.target.closest?.("#villagerInventoryForm")) {
                    if (id.startsWith("villagerStockItem")) {
                        const count = el(`villagerStockCount${event.target.dataset.stockSlot}`);
                        if (count && !event.target.value) count.value = "0";
                        else if (count && !(Number(count.value) > 0)) count.value = "1";
                    }
                    updateInventoryDirty();
                }
                else if (["villagerBatchMax", "villagerBatchCurrent", "villagerBatchHeal"].includes(id)) updateHealthDirty(false);
                else if (id === "villagerName") updateNameDirty();
                else if (id === "villagerAlias") updateAliasDirty();
                else if (event.target.closest?.("#villagerRegionForm")) updateRegionDirty();
                else return;
                invalidatePreview(); render(); onDraftChanged();
            });
            on("villagersPanel", "change", event => {
                if (event.target.dataset.action === "select") changeSelection([event.target.dataset.id], event.target.checked);
            });
            on("villagersPanel", "click", event => {
                const button = event.target.closest?.("button");
                if (button) {
                    if (button.disabled) return;
                    const id = button.dataset?.id, action = button.dataset?.action;
                    if (action === "sort" && ["name", "profession", "tier", "health", "region", "dimension"].includes(button.dataset.sort)) {
                        state.direction = state.sort === button.dataset.sort && state.direction === "asc" ? "desc" : "asc";
                        state.sort = button.dataset.sort; state.page = 1; render();
                    }
                    if (button.id === "villagerNameRemove") setNameDraft("");
                    if (button.id === "villagerNameReset") setNameDraft(state.detail?.name || "");
                    if (button.id === "villagerDetailReset") resetDetail();
                    if (button.id === "villagerInventoryReset") resetInventory();
                    if (button.id === "villagerDetailHealAction") healDetail();
                    if (action === "detail" || action === "map-detail") openDetail(id, { fromMap: action === "map-detail", trigger: button });
                    if (action === "close-detail") closeDetail();
                    if (action === "copy-position" && model.hasPosition(state.detail || {})) copyTextToClipboard(`${model.dimensionLabel(state.detail.dimension)}: ${["x", "y", "z"].map(axis => state.detail.position[axis]).join(" ")}`);
                    if (action === "edit-region") editRegion(id);
                    if (action === "delete-region") deleteRegion(id);
                    if (action === "remove-filter") removeFilter(button.dataset.filter, button);
                    if (action === "reset-filters") resetFilters();
                    return;
                }
                if (event.target.closest?.("input, select, textarea, label, a, summary, [contenteditable='true']")) return;
                const row = event.target.closest?.("tr[data-villager-id]");
                if (!row || !el("villagerRows")?.contains?.(row)) return;
                const selection = doc.getSelection?.();
                if (selection && !selection.isCollapsed && String(selection)) return;
                openDetail(row.dataset.villagerId, { trigger: row.querySelector?.('[data-action="detail"]') });
            });
        }

        function handleKeyboard(event) {
            if (getActiveView() !== "villagers") return false;
            const key = event.key.toLowerCase();
            if (modalOpen()) {
                if ((event.ctrlKey || event.metaKey) && key === "s") event.preventDefault();
                return true;
            }
            if ((event.ctrlKey || event.metaKey) && key === "s") {
                event.preventDefault();
                if (event.target?.closest?.("#villagerAliasForm")) { if (state.aliasDirty) saveAlias(); }
                else if (event.target?.closest?.("#villagerRegionForm")) { if (state.regionDirty) saveRegion(); }
                else if (event.target?.closest?.("#villagerBatchForm")) { if (state.batchDirty && state.selected.size) preview(false); }
                else if (event.target?.closest?.("#villagerDetailHealthForm")) { if (state.detailDirty && state.activeId) preview(true); }
                else if (event.target?.closest?.("#villagerInventoryForm")) { if (state.inventoryDirty && state.activeId) preview(true, "inventory"); }
                else if (event.target?.closest?.("#villagerNameForm")) { if (state.nameDirty && state.activeId) preview(true, "name"); }
                else if (state.nameDirty && state.activeId) preview(true, "name");
                else if (state.detailDirty && state.activeId) preview(true);
                else if (state.inventoryDirty && state.activeId) preview(true, "inventory");
                else if (state.batchDirty && state.selected.size) preview(false);
                return true;
            }
            if ((event.ctrlKey || event.metaKey) && key === "f" && !event.target?.matches?.("input, textarea, select, [contenteditable='true']")) {
                event.preventDefault(); el("villagerSearch")?.focus(); return true;
            }
            const editingText = event.target?.matches?.("input:not([type='checkbox']):not([type='radio']):not([type='button']):not([type='submit']), textarea, select, [contenteditable='true']")
                || event.target?.isContentEditable;
            if (key === "escape" && state.activeId && !editingText) { event.preventDefault(); closeDetail(); }
            // Inventory undo and clipboard shortcuts must never edit a hidden
            // player while the world-level editor has keyboard focus.
            return true;
        }

        async function activate() { wire(); updateContext(); if (!state.loaded && !state.scanning) await scan(); }
        return { getPendingChanges: () => state.pending, clearPending, removePending, finalizePending, refreshAfterSave, rejectPending, activate, deactivate, updateContext, observeWorldStatus, scan, cancelScan, openDetail, closeDetail, preview, save, savePreferences,
            resetBatch, resetDetail, resetInventory, healDetail,
            hasPendingChanges, isSaving: () => state.saving, hasScan: () => state.loaded && !state.staleReason,
            handleKeyboard, wire, getState: () => state };
    }

    window.MCBEVillagerController = { createVillagerController, initialState };
}());
