(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));

    function createScanPathsController({
        elements = {},
        fetchImpl = fetch,
        parseJsonResponse,
        withCsrf,
        scanPathsHtml,
        updateAutoPathHint = () => {},
        scanWorlds = async () => {},
        consoleObj = console,
    } = {}) {
        const {
            panel,
            list,
            openButton,
            closeButton,
            browseButton,
            inputButton,
            confirmButton,
            textInput,
            manualInput,
            status,
        } = elements;

        async function postJson(url, body = {}) {
            const res = await fetchImpl(url, {
                method: "POST",
                headers: withCsrf(),
                body: JSON.stringify(body),
            });
            return await parseJsonResponse(res);
        }

        async function refreshAfterChange(message = "") {
            if (status) status.textContent = message;
            await loadScanPaths();
            await scanWorlds();
        }

        async function loadScanPaths() {
            try {
                const res = await fetchImpl("/api/scan_paths");
                const data = await parseJsonResponse(res);
                if (!data.success) return false;
                renderScanPaths(data);
                if (data.default_path) {
                    updateAutoPathHint(t("Standardordner erkannt: {path}", { path: data.default_path }), "success");
                } else if (Array.isArray(data.default_candidates) && data.default_candidates.length) {
                    updateAutoPathHint(t("Standardordner noch nicht vorhanden oder nicht lesbar"), "warning");
                }
                return true;
            } catch (e) {
                consoleObj.error("loadScanPaths:", e);
                return false;
            }
        }

        function renderScanPaths(data) {
            if (!list) return;
            list.innerHTML = scanPathsHtml(data);
            list.querySelectorAll("[data-scan-path-toggle]").forEach(checkbox => {
                checkbox.addEventListener("change", async () => {
                    const result = await postJson("/api/scan_paths/set_enabled", {
                        path: checkbox.dataset.path || "",
                        enabled: checkbox.checked,
                    });
                    if (!result.success) {
                        if (status) status.textContent = t("Fehler: {error}", { error: result.error || t("Unbekannter Fehler") });
                        checkbox.checked = !checkbox.checked;
                        return;
                    }
                    await refreshAfterChange(checkbox.checked ? t("Suchbereich aktiviert.") : t("Suchbereich deaktiviert."));
                });
            });
            list.querySelectorAll("[data-scan-path-remove]").forEach(remove => {
                remove.addEventListener("click", async () => {
                    const result = await postJson("/api/scan_paths/remove", { path: remove.dataset.path || "" });
                    if (!result.success) {
                        if (status) status.textContent = t("Fehler: {error}", { error: result.error || t("Suchbereich konnte nicht entfernt werden.") });
                        return;
                    }
                    await refreshAfterChange(t("Suchbereich entfernt."));
                });
            });
        }

        function setPanelOpen(open) {
            if (!panel) return;
            panel.style.display = open ? "block" : "none";
            openButton?.setAttribute("aria-expanded", String(open));
            openButton?.classList.toggle("active", open);
            if (!open) {
                if (manualInput) manualInput.style.display = "none";
                if (status) status.textContent = "";
            }
        }

        function wire() {
            openButton?.addEventListener("click", async () => {
                const willOpen = panel?.style.display === "none" || !panel?.style.display;
                setPanelOpen(willOpen);
                if (willOpen) await loadScanPaths();
            });
            closeButton?.addEventListener("click", () => setPanelOpen(false));
            browseButton?.addEventListener("click", async () => {
                try {
                    const res = await fetchImpl("/api/pick_folder", { method: "POST", headers: withCsrf() });
                    const data = await parseJsonResponse(res);
                    if (data.success && data.path) {
                        await postJson("/api/scan_paths/add", { path: data.path });
                        await refreshAfterChange("");
                    } else if (data.error && status) {
                        status.textContent = t("Fehler: {error}", { error: data.error });
                    }
                } catch (e) {
                    consoleObj.error("btnAddScanPathBrowse:", e);
                }
            });
            inputButton?.addEventListener("click", () => {
                if (manualInput) manualInput.style.display = "flex";
                textInput?.focus();
            });
            if (typeof textInput?.addEventListener === "function") {
                textInput.addEventListener("keydown", event => {
                    if (event.key === "Enter") {
                        event.preventDefault();
                        confirmButton?.click();
                    }
                });
            }
            confirmButton?.addEventListener("click", async () => {
                const path = String(textInput?.value || "").trim();
                if (!path) return;
                const data = await postJson("/api/scan_paths/add", { path });
                if (data.success) {
                    if (textInput) textInput.value = "";
                    if (manualInput) manualInput.style.display = "none";
                    await refreshAfterChange("");
                } else if (status) {
                    status.textContent = t("Fehler: {error}", { error: data.error || t("Unbekannter Fehler") });
                }
            });
        }

        return {
            loadScanPaths,
            renderScanPaths,
            setPanelOpen,
            wire,
        };
    }

    function collectScanPathsElements(doc = document) {
        return {
            panel: doc.getElementById("scanPathsPanel"),
            list: doc.getElementById("scanPathsList"),
            openButton: doc.getElementById("btnScanPaths"),
            closeButton: doc.getElementById("btnCloseScanPaths"),
            browseButton: doc.getElementById("btnAddScanPathBrowse"),
            inputButton: doc.getElementById("btnAddScanPathInput"),
            confirmButton: doc.getElementById("btnAddScanPathConfirm"),
            textInput: doc.getElementById("scanPathText"),
            manualInput: doc.getElementById("scanPathManualInput"),
            status: doc.getElementById("scanPathStatus"),
        };
    }

    function createInventoryScanPathsController({
        doc = document,
        api = {},
        scanPathsHtml = window.MCBEScanPathsView?.scanPathsHtml,
        updateAutoPathHint = () => {},
        scanWorlds = async () => {},
    } = {}) {
        return createScanPathsController({
            elements: collectScanPathsElements(doc),
            parseJsonResponse: api.parseJsonResponse,
            withCsrf: api.withCsrf,
            scanPathsHtml,
            updateAutoPathHint,
            scanWorlds,
        });
    }


    window.MCBEScanPathsController = {
        collectScanPathsElements,
        createInventoryScanPathsController,
        createScanPathsController,
    };
}());
