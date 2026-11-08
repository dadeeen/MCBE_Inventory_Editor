(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => params && k in params ? String(params[k]) : m));
    const model = window.MCBEVillagerModel;
    const LIMIT = 1000;
    const valid = row => model.hasPosition(row) && Number.isInteger(row.dimension)
        && Math.abs(row.position.x) <= 2 ** 35 && Math.abs(row.position.z) <= 2 ** 35;

    function fitCamera(rows) {
        if (!rows.length) return { x: 0, z: 0, span: 32 };
        let minX = Infinity, minZ = Infinity, maxX = -Infinity, maxZ = -Infinity;
        for (const { position: p } of rows) {
            minX = Math.min(minX, p.x); maxX = Math.max(maxX, p.x);
            minZ = Math.min(minZ, p.z); maxZ = Math.max(maxZ, p.z);
        }
        return { x: (minX + maxX) / 2, z: (minZ + maxZ) / 2, span: Math.max(32, (maxX - minX) / .84, (maxZ - minZ) / .84) };
    }

    function zoomCamera(camera, factor, anchor = { x: .5, z: .5 }, maxSpan = 2 ** 39) {
        const span = Math.max(4, Math.min(maxSpan, camera.span / factor));
        return { x: camera.x + (anchor.x - .5) * (camera.span - span),
            z: camera.z + (anchor.z - .5) * (camera.span - span), span };
    }

    function createVillagerMap({ doc = document } = {}) {
        const el = id => doc.getElementById(id);
        const map = el("villagerMap"), layer = el("villagerMapMarkers");
        let camera = fitCamera([]), fitted = camera, state = null, rows = [], players = [];
        let resetKey = "", sourceRows = null, nodes = new Map(), suppressClickUntil = 0, renderVersion = 0, inspectedPlayerKey = "";
        const pointers = new Map();
        let gesture = null;

        function text(id, value) { const node = el(id); if (node && node.textContent !== value) node.textContent = value; }
        function anchor(clientX, clientY) {
            const rect = map.getBoundingClientRect();
            return { x: (clientX - rect.left) / rect.width, z: (clientY - rect.top) / rect.height };
        }
        function fit() { camera = { ...fitted }; draw(); }
        function zoom(factor, point) { camera = zoomCamera(camera, factor, point, Math.min(2 ** 39, fitted.span * 16)); draw(); }
        function translate(dx, dz) {
            camera = { ...camera, x: Math.max(-(2 ** 36), Math.min(2 ** 36, camera.x + dx)),
                z: Math.max(-(2 ** 36), Math.min(2 ** 36, camera.z + dz)) };
        }
        function marker(row, kind, x, z) {
            const key = `${kind}:${kind === "player" ? row.player_key : row.id}`;
            let node = nodes.get(key);
            if (!node) {
                node = doc.createElement("button"); node.type = "button";
                if (kind === "villager") { node.dataset.id = row.id; node.dataset.action = "map-detail"; }
                else node.dataset.playerKey = row.player_key;
                nodes.set(key, node); layer.append(node);
            }
            // Pan/zoom changes only coordinates; avoid repeatedly formatting
            // thousands of accessible labels during each pointer movement.
            if (node.mapRenderVersion !== renderVersion) {
                const isPlayer = kind === "player", active = isPlayer ? row.player_key === state.selectedPlayerKey : row.id === state.activeId;
                node.className = isPlayer ? `villager-map-player${active ? " active" : ""}`
                    : `villager-map-point${model.isInjured(row) ? " injured" : ""}${active ? " active" : ""}${state.selected.has(row.id) ? " selected" : ""}`;
                const name = isPlayer ? row.label || t("Spieler") : model.displayName(row, state.preferences.aliases);
                const label = `${name} · ${model.positionText(row)}${isPlayer ? ` · ${t("Zuletzt gespeicherte Position")}` : ""}`;
                node.title = label; node.setAttribute("aria-label", label); node.mapRenderVersion = renderVersion;
            }
            node.style.left = `${x * 100}%`; node.style.top = `${z * 100}%`;
            return key;
        }
        function draw() {
            if (!state) return;
            const kept = new Set();
            let visible = 0, shown = 0;
            // Keep the inspected villager reachable even in a dense cluster.
            const ordered = state.activeId ? [...rows.filter(row => row.id === state.activeId), ...rows.filter(row => row.id !== state.activeId)] : rows;
            for (const row of ordered) {
                const x = .5 + (row.position.x - camera.x) / camera.span, z = .5 + (row.position.z - camera.z) / camera.span;
                if (x < 0 || x > 1 || z < 0 || z > 1) continue;
                visible += 1;
                if (shown++ < LIMIT) kept.add(marker(row, "villager", x, z));
            }
            for (const row of players) {
                const x = .5 + (row.position.x - camera.x) / camera.span, z = .5 + (row.position.z - camera.z) / camera.span;
                if (x >= 0 && x <= 1 && z >= 0 && z <= 1) kept.add(marker(row, "player", x, z));
            }
            for (const [key, node] of nodes) if (!kept.has(key)) {
                if (doc.activeElement === node) map.focus({ preventScroll: true });
                node.remove(); nodes.delete(key);
            }
            // A world-aligned grid moves and changes scale with the camera.
            const target = camera.span / 8, power = 10 ** Math.floor(Math.log10(target));
            const step = [1, 2, 5, 10].map(n => n * power).find(n => n >= target);
            const size = step / camera.span * 100;
            const gridX = ((.5 - camera.x / camera.span) * 100 % size + size) % size;
            const gridZ = ((.5 - camera.z / camera.span) * 100 % size + size) % size;
            map.style.backgroundSize = `${size}% ${size}%`;
            // CSS percentage positions use the remaining image area; pixel
            // offsets keep grid intersections attached to world coordinates.
            map.style.backgroundPosition = `${gridX / 100 * map.clientWidth}px ${gridZ / 100 * map.clientHeight}px`;
            el("villagerMapEmpty").hidden = rows.length > 0 || players.length > 0;
            const caption = t("{count} Bewohner · {visible} im Ausschnitt", { count: rows.length, visible });
            text("villagerMapCaption", caption + (visible > LIMIT ? ` · ${t("{count} weitere Punkte: näher heranzoomen oder filtern.", { count: visible - LIMIT })}` : ""));
            text("villagerMapScale", t("Raster: {blocks} Blöcke", { blocks: model.healthNumber(step) }));
            text("villagerMapCoordinates", `X ${model.healthNumber(camera.x - camera.span / 2)} … ${model.healthNumber(camera.x + camera.span / 2)} · Z ${model.healthNumber(camera.z - camera.span / 2)} … ${model.healthNumber(camera.z + camera.span / 2)}`);
            text("villagerMapZoom", `${model.healthNumber(fitted.span / camera.span * 100)} %`);
            el("villagerMapZoomIn").disabled = camera.span <= 4;
            el("villagerMapZoomOut").disabled = camera.span >= Math.min(2 ** 39, fitted.span * 16);
        }

        function render(nextState, info) {
            state = nextState;
            renderVersion += 1;
            rows = info.filtered.filter(row => valid(row) && row.dimension === Number(state.mapDimension));
            const allPlayers = (state.mapPlayers || []).filter(valid);
            players = state.staleReason || state.mapPlayerMode === "none" ? [] : allPlayers.filter(row => row.dimension === Number(state.mapDimension)
                && (state.mapPlayerMode === "all" || row.player_key === state.selectedPlayerKey));
            el("villagerMapPlayers").value = state.mapPlayerMode;
            const selected = allPlayers.find(row => row.player_key === state.selectedPlayerKey);
            text("villagerMapPlayerHint", state.staleReason ? t("Spielerpositionen sind veraltet. Bitte neu scannen.")
                : state.mapPlayerMode === "none" ? ""
                : state.mapPlayerMode === "selected" && !selected ? t("Kein ausgewählter Spieler mit gespeicherter Position. Wähle einen Spieler oder „Alle Spieler“.")
                : state.mapPlayerMode === "selected" && selected.dimension !== Number(state.mapDimension) ? t("Der ausgewählte Spieler ist in einer anderen Dimension.")
                : !players.length ? t("Keine gespeicherten Spielerpositionen in dieser Dimension.") : t("Blaue Rauten: Spieler · zuletzt gespeicherte Position, keine Live-Anzeige."));
            const key = JSON.stringify([state.worldPath, state.mapDimension, state.filters, state.mapPlayerMode, players]);
            fitted = fitCamera([...rows, ...players]);
            if (key !== resetKey || sourceRows !== state.rows) {
                resetKey = key; sourceRows = state.rows; camera = { ...fitted }; pointers.clear(); gesture = null;
            }
            showPlayerInfo();
            draw();
        }

        function showPlayerInfo() {
            const player = players.find(row => row.player_key === inspectedPlayerKey)
                || players.find(row => row.player_key === state.selectedPlayerKey);
            text("villagerMapPlayerInfo", player ? `${player.label || t("Spieler")} · ${model.positionText(player)} · ${t("Zuletzt gespeicherte Position")}` : "");
            el("villagerMapPlayerInfo").hidden = !player;
        }
        function inspectPlayer(event) {
            const button = event.target.closest?.(".villager-map-player");
            if (!button) return;
            inspectedPlayerKey = button.dataset.playerKey; showPlayerInfo();
        }
        map.addEventListener("focusin", inspectPlayer);
        map.addEventListener("click", inspectPlayer);

        map.addEventListener("wheel", event => {
            event.preventDefault();
            const delta = event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? map.clientHeight : 1);
            zoom(Math.exp(-Math.max(-300, Math.min(300, delta)) * .003), anchor(event.clientX, event.clientY));
        }, { passive: false });
        map.addEventListener("keydown", event => {
            if (event.ctrlKey || event.metaKey || event.altKey) return;
            const steps = { ArrowLeft: [-.1, 0], ArrowRight: [.1, 0], ArrowUp: [0, -.1], ArrowDown: [0, .1] };
            if (event.key === "+" || event.key === "=") zoom(1.5);
            else if (event.key === "-") zoom(1 / 1.5);
            else if (event.key === "Home") fit();
            else if (steps[event.key]) { translate(steps[event.key][0] * camera.span, steps[event.key][1] * camera.span); draw(); }
            else return;
            event.preventDefault(); event.stopPropagation();
        });
        function currentGesture() {
            const points = [...pointers.values()];
            if (!points.length) return null;
            const [a, b] = points;
            return { x: b ? (a.x + b.x) / 2 : a.x, y: b ? (a.y + b.y) / 2 : a.y,
                distance: b ? Math.hypot(b.x - a.x, b.y - a.y) : 0, count: points.length };
        }
        map.addEventListener("pointerdown", event => {
            if (event.button !== 0 || pointers.size >= 2) return;
            if (!pointers.size) suppressClickUntil = 0;
            pointers.set(event.pointerId, { x: event.clientX, y: event.clientY, startX: event.clientX, startY: event.clientY, type: event.pointerType, moved: false });
            event.target.setPointerCapture(event.pointerId);
            gesture = currentGesture();
            if (pointers.size === 2) { for (const point of pointers.values()) point.moved = true; suppressClickUntil = Date.now() + 500; }
        });
        map.addEventListener("pointermove", event => {
            const point = pointers.get(event.pointerId);
            if (!point) return;
            point.x = event.clientX; point.y = event.clientY;
            const next = currentGesture();
            const moved = Math.hypot(point.x - point.startX, point.y - point.startY) > 5;
            if (moved) point.moved = true;
            if (gesture && (pointers.size === 2 || point.type !== "touch") && (point.moved || pointers.size === 2)) {
                // Keep capture on the stable viewport once markers can leave
                // its bounds and be removed by viewport culling.
                for (const pointerId of pointers.keys()) map.setPointerCapture(pointerId);
                const rect = map.getBoundingClientRect();
                const previousSpan = camera.span;
                if (next.distance > 1 && gesture.distance > 1) camera = zoomCamera(camera, next.distance / gesture.distance,
                    anchor(gesture.x, gesture.y), Math.min(2 ** 39, fitted.span * 16));
                translate(-(next.x - gesture.x) / rect.width * camera.span, -(next.y - gesture.y) / rect.height * camera.span);
                // Avoid page gestures and accidental opens after dragging a point.
                event.preventDefault(); suppressClickUntil = Date.now() + 500;
                map.classList.add("panning");
                if (previousSpan !== camera.span || next.x !== gesture.x || next.y !== gesture.y) draw();
            }
            gesture = next;
        });
        function endPointer(event) {
            if (event.type === "lostpointercapture" && map.hasPointerCapture(event.pointerId)) return;
            const point = pointers.get(event.pointerId);
            if (point?.moved) suppressClickUntil = Date.now() + 500;
            pointers.delete(event.pointerId); gesture = currentGesture();
            if (!pointers.size) map.classList.remove("panning");
        }
        for (const event of ["pointerup", "pointercancel", "lostpointercapture"]) map.addEventListener(event, endPointer);
        map.addEventListener("click", event => {
            if (event.detail && Date.now() < suppressClickUntil) { event.preventDefault(); event.stopPropagation(); suppressClickUntil = 0; }
        }, true);
        el("villagerMapZoomIn").addEventListener("click", () => zoom(1.5));
        el("villagerMapZoomOut").addEventListener("click", () => zoom(1 / 1.5));
        el("villagerMapFit").addEventListener("click", fit);
        // Resize changes only screen geometry, not the user's chosen camera.
        if (typeof ResizeObserver !== "undefined") new ResizeObserver(() => draw()).observe(map);
        return { render };
    }

    window.MCBEVillagerMap = { createVillagerMap, fitCamera, zoomCamera };
}());
