(function () {
    "use strict";

    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (m, k) => (params && k in params ? String(params[k]) : m)));

    const html = () => window.MCBEHtmlUtils;

    const MOUNT_TYPE_OPTIONS = [
        { id: "minecraft:horse", label: t("Pferd") },
        { id: "minecraft:donkey", label: t("Esel") },
        { id: "minecraft:mule", label: t("Maultier") },
        { id: "minecraft:camel", label: t("Kamel") },
        { id: "minecraft:skeleton_horse", label: t("Skelettpferd") },
    ];

    const DEFAULT_HORSE_PROFILE = {
        mode: "random_like_game",
        health: 25,
        movement: 0.175,
        jump_strength: 0.5,
        color: 0,
        mark_variant: 1,
        temper: 62,
    };

    const HORSE_COLOR_OPTIONS = [[0, t("Weiß")], [1, t("Creme")], [2, t("Kastanie")], [3, t("Braun")], [4, t("Schwarz")], [5, t("Grau")], [6, t("Dunkelbraun")]];
    const HORSE_MARK_OPTIONS = [[0, t("Keine")], [1, t("Weiße Details")], [2, t("Weiße Felder")], [3, t("Weiße Punkte")], [4, t("Schwarze Punkte")]];

    function normalizedHorseProfile(profile = {}) {
        return { ...DEFAULT_HORSE_PROFILE, ...(profile || {}) };
    }

    function formatCoord(value) {
        const num = Number(value);
        if (!Number.isFinite(num)) return "?";
        return num.toFixed(2).replace(/\.00$/, "");
    }

    // Umrechnung des Bedrock-Bewegungsattributs in ungefähre Blöcke pro Sekunde
    // (Faktor ~42,16 laut Minecraft-Wiki für Pferde-Reitgeschwindigkeit).
    const MOVEMENT_TO_BLOCKS_PER_SECOND = 42.16;

    function finiteInput(value) {
        if (value === null || value === undefined) return null;
        if (typeof value === "string" && value.trim() === "") return null;
        const num = Number(value);
        return Number.isFinite(num) ? num : null;
    }

    function movementBlocksPerSecond(movement) {
        const value = finiteInput(movement);
        if (value === null || value < 0.1125 || value > 0.3375) return null;
        return value * MOVEMENT_TO_BLOCKS_PER_SECOND;
    }

    // Kubische Näherung der Sprunghöhe in Blöcken aus horse.jump_strength
    // (Minecraft-Wiki: 0,4 ≈ 1,1 Blöcke · 0,5 ≈ 1,6 · 1,0 ≈ 5,3).
    function jumpHeightBlocks(jumpStrength) {
        const x = finiteInput(jumpStrength);
        if (x === null || x < 0.4 || x > 1) return null;
        return (-0.1817584952 * x * x * x) + (3.689713992 * x * x) + (2.128599134 * x) - 0.343930367;
    }

    function formatGermanNumber(value, digits = 1) {
        if (!Number.isFinite(Number(value))) return "?";
        return window.MCBEI18n?.formatNumber?.(value, { minimumFractionDigits: digits, maximumFractionDigits: digits })
            || Number(value).toFixed(digits);
    }

    function movementHintText(movement) {
        const speed = movementBlocksPerSecond(movement);
        return speed === null ? "" : t("≈ {value} Blöcke/s", { value: formatGermanNumber(speed) });
    }

    function jumpHintText(jumpStrength) {
        const height = jumpHeightBlocks(jumpStrength);
        return height === null ? "" : t("≈ {value} Blöcke Sprunghöhe", { value: formatGermanNumber(height) });
    }

    // Bedrock zähmt bei Temper 100. Der Startwert sagt also, wie viel Weg noch
    // fehlt; das Spiel würfelt ihn pro Tier.
    function temperHintText(temper) {
        const value = finiteInput(temper);
        if (value === null || !Number.isInteger(value) || value < 0 || value > 99) return "";
        if (value >= 90) return t("fast gezähmt");
        if (value >= 60) return t("gut vorgezähmt");
        if (value >= 30) return t("etwas vorgezähmt");
        return t("praktisch ungezähmt");
    }

    function numberInputError(input, badInput = false) {
        const value = finiteInput(input.value);
        if (badInput || input.validity?.badInput || value === null && (input.required || input.value !== "")) return t("Bitte eine gültige Zahl eingeben.");
        if (value === null) return "";
        const format = value => window.MCBEI18n?.formatNumber?.(value, { maximumFractionDigits: 4 }) || String(value);
        const minimum = Number(input.min), maximum = Number(input.max);
        if (value < minimum || value > maximum) return t("Zulässig: {min} bis {max}.", { min: format(minimum), max: format(maximum) });
        if (input.validity?.stepMismatch) return Number(input.step) === 1 ? t("Bitte eine ganze Zahl eingeben.") : t("Schrittweite: {step}.", { step: format(Number(input.step)) });
        return "";
    }

    function positionText(position = {}) {
        return `X ${formatCoord(position.x)} · Y ${formatCoord(position.y)} · Z ${formatCoord(position.z)}`;
    }

    // Contextual notes sit beside the search results. Blocking reasons remain
    // visible in the main panel; neither needs a second disclosure or counter.
    function warningListHtml(warnings = [], { blocked = false } = {}) {
        const rows = (warnings || []).filter(Boolean);
        if (!rows.length) return "";
        if (!blocked) return rows.map(warning => `<p class="mount-tech-note">${html().escapeHtml(t(warning))}</p>`).join("");
        const content = rows.length === 1
            ? `<p>${html().escapeHtml(t(rows[0]))}</p>`
            : `<ul>${rows.map(warning => `<li>${html().escapeHtml(t(warning))}</li>`).join("")}</ul>`;
        return `
            <div class="mount-warning-list status-note warning">${content}</div>
        `;
    }

    function placementSafetyInfo(candidate = {}) {
        if (candidate.safe_to_place === true) return { status: "safe", label: t("Sicher platzierbar"), pillClass: "success", marker: "✓" };
        if (candidate.safe_to_place === false) return { status: "unsafe", label: t("Nicht sicher platzierbar"), pillClass: "error", marker: "!" };
        return { status: "unchecked", label: t("Platzierung ungeprüft"), pillClass: "warning", marker: "?" };
    }

    function shortBlockName(name) {
        if (!name) return "?";
        return String(name).replace(/^minecraft:/, "");
    }

    function directionKeyFromCandidateId(id = "") {
        const text = String(id || "");
        const match = text.match(/^(.+)_(-?\d+)$/);
        if (match) return match[1];
        return text || "?";
    }

    function readableCandidateName(candidate = {}) {
        const id = String(candidate.id || t("Kandidat"));
        const direction = directionKeyFromCandidateId(id);
        const distance = Number.isFinite(Number(candidate.distance)) ? t("{value} Blöcke", { value: formatCoord(candidate.distance) }) : "?";
        let label = id;
        if (id.startsWith("blickrichtung_")) label = t("Vor dir");
        else if (id.startsWith("rechts_")) label = t("Rechts");
        else if (id.startsWith("links_")) label = t("Links");
        else if (id.startsWith("hinter_dir_")) label = t("Hinter dir");
        else if (id.startsWith("east_")) label = t("Osten");
        else if (id.startsWith("west_")) label = t("Westen");
        else if (id.startsWith("south_")) label = t("Süden");
        else if (id.startsWith("north_")) label = t("Norden");
        else if (id === "preferred_offset") label = t("Gewählte Position");
        return { label, direction, distance, rawId: id };
    }

    function placementMessage(candidate = {}) {
        const footprint = candidate.chunk_probe?.footprint_check;
        const placement = candidate.chunk_probe?.placement_check;
        return footprint?.message || placement?.message || candidate.warning || t("Position noch nicht bewertet.");
    }

    function placementIssues(candidate = {}) {
        if (candidate.safe_to_place === true || candidate.safe_to_place === false) return [];
        return Array.isArray(candidate.placement_issues) ? candidate.placement_issues.filter(issue => issue?.message) : [];
    }

    function uncheckedPlacementHtml(candidate) {
        const issues = placementIssues(candidate);
        const message = issues[0]?.message || placementMessage(candidate);
        const hint = issues[0]?.hint || t("Prüfdetails öffnen oder die Vorschau erneut prüfen.");
        return `<div class="mount-placement-explanation">
            <p class="mount-placement-reason" id="mountUncheckedReason">${html().escapeHtml(message)}</p>
            <p class="mount-placement-note">${html().escapeHtml(hint)}</p>
            ${issues.length > 1 ? `<p class="mount-placement-note">${t("Weitere Gründe in den Prüfdetails: {count}.", { count: issues.length - 1 })}</p>` : ""}
        </div>`;
    }

    function placementIssuesHtml(candidate) {
        const issues = placementIssues(candidate);
        if (!issues.length) return "";
        const items = issues.map(issue => {
            const chunks = Array.isArray(issue.chunks) ? issue.chunks : [];
            const where = chunks.map(chunk => t("Chunk X {x} · Z {z}", { x: chunk.x, z: chunk.z })).join("; ");
            const block = issue.sample_block;
            const sample = block && [block.x, block.y, block.z].every(Number.isFinite)
                ? t("Betroffene Blöcke: {count}. Beispiel: X {x} · Y {y} · Z {z}.", { count: issue.block_count, ...block }) : "";
            return `<li><p class="mount-placement-reason">${html().escapeHtml(issue.message)}</p>
                ${issue.hint ? `<p class="mount-tech-note">${html().escapeHtml(issue.hint)}</p>` : ""}
                ${where ? `<p class="mount-tech-note">${html().escapeHtml(where)}</p>` : ""}
                ${sample ? `<p class="mount-tech-note">${html().escapeHtml(sample)}</p>` : ""}</li>`;
        }).join("");
        return `<section class="mount-tech-section mount-placement-issues"><h3 class="mount-tech-label">${t("Warum ungeprüft?")}</h3><ul>${items}</ul></section>`;
    }

    function blockColor(name) {
        const n = String(name || "").toLowerCase();
        if (!n || n === "?") return null;
        if (["air", "minecraft:air", "minecraft:cave_air", "minecraft:void_air"].includes(n)) return "air";
        if (n.includes("leaves")) return "#3f6b4c";
        if (n.includes("grass_block") || n.includes("moss") || n.includes("mycelium") || n === "minecraft:grass_path" || n.includes("grass_path")) return "#5c8a3a";
        if (n.includes("grass") || n.includes("fern")) return "#6f9a44";
        if (n.includes("dirt") || n.includes("podzol") || n.includes("mud") || n.includes("farmland") || n.includes("clay") || n.includes("soul")) return "#7c5a39";
        if (n.includes("sand")) return "#cdb27a";
        if (n.includes("log") || n.includes("planks") || n.includes("wood") || n.includes("stem")) return "#8a6b3f";
        if (n.includes("water")) return "#3a6ea5";
        if (n.includes("lava") || n.includes("magma")) return "#c1440e";
        if (n.includes("snow") || n.includes("ice")) return "#cfe0ea";
        if (n.includes("stone") || n.includes("cobble") || n.includes("andesite") || n.includes("granite") || n.includes("diorite") || n.includes("deepslate") || n.includes("tuff") || n.includes("gravel") || n.includes("bedrock") || n.includes("ore")) return "#80808a";
        return "#6b7280";
    }

    function blockTile(name) {
        const color = blockColor(name);
        if (color === null) return `<span class="mount-block-tile unknown" title="${t("ungelesen")}"></span>`;
        if (color === "air") return `<span class="mount-block-tile air" title="${t("frei (air)")}"></span>`;
        return `<span class="mount-block-tile" style="background:${color}" title="${html().escapeAttr(shortBlockName(name))}"></span>`;
    }

    // Eigene Pixel-Art-Silhouetten (keine Spiel-Texturen). Ein 16x16-Raster,
    // Seitenansicht nach links; Pferdefarben folgen dem Bedrock-Color-Byte.
    const HORSE_ICON_PALETTES = [
        { body: "#dcd9d2", mane: "#a8a49b" },
        { body: "#d5b078", mane: "#a37f4b" },
        { body: "#96502d", mane: "#6e3a1f" },
        { body: "#6f4a2a", mane: "#4c2f1a" },
        { body: "#35322f", mane: "#191715" },
        { body: "#8d8d8d", mane: "#5f5f5f" },
        { body: "#4a3120", mane: "#2e1d12" },
    ];

    function mountIconRects(mountType, palette) {
        const body = palette.body;
        const mane = palette.mane;
        const eye = "#14120f";
        const base = [
            [1, 2, 3, 3, body],
            [0, 3, 1, 2, body],
            [3, 3, 3, 4, body],
            [4, 6, 9, 4, body],
            [4, 10, 2, 4, body],
            [11, 10, 2, 4, body],
            [2, 3, 1, 1, eye],
        ];
        if (mountType === "minecraft:camel") {
            return [
                [1, 1, 3, 3, body],
                [0, 2, 1, 2, body],
                [3, 2, 2, 5, body],
                [4, 7, 9, 3, body],
                [6, 4, 4, 3, body],
                [4, 10, 2, 4, body],
                [11, 10, 2, 4, body],
                [13, 7, 1, 3, mane],
                [2, 2, 1, 1, eye],
            ];
        }
        const rects = [...base, [5, 2, 1, 5, mane], [13, 5, 2, 5, mane]];
        if (mountType === "minecraft:donkey" || mountType === "minecraft:mule") {
            rects.push([1, 0, 1, 2, body], [3, 0, 1, 2, body]);
        } else {
            rects.push([2, 1, 1, 1, body], [4, 2, 1, 1, body]);
        }
        if (mountType === "minecraft:skeleton_horse") {
            rects.push([6, 7, 1, 2, mane], [8, 7, 1, 2, mane], [10, 7, 1, 2, mane]);
        }
        return rects;
    }

    function mountIconPalette(mountType, colorIndex = 0) {
        if (mountType === "minecraft:donkey") return { body: "#8b7d6b", mane: "#5f5546" };
        if (mountType === "minecraft:mule") return { body: "#71513a", mane: "#4a3526" };
        if (mountType === "minecraft:camel") return { body: "#c9a36a", mane: "#96733f" };
        if (mountType === "minecraft:skeleton_horse") return { body: "#dfe3e4", mane: "#9aa6a8" };
        const index = Number.isInteger(Number(colorIndex)) ? Math.max(0, Math.min(HORSE_ICON_PALETTES.length - 1, Number(colorIndex))) : 0;
        return HORSE_ICON_PALETTES[index];
    }

    function mountIconSvg(mountType = "minecraft:horse", colorIndex = 0, size = 36) {
        const palette = mountIconPalette(mountType, colorIndex);
        const rects = mountIconRects(mountType, palette)
            .map(([x, y, w, h, fill]) => `<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="${fill}"/>`)
            .join("");
        return `<span class="mount-icon" aria-hidden="true"><svg width="${size}" height="${size}" viewBox="0 0 16 16" shape-rendering="crispEdges" role="img">${rects}</svg></span>`;
    }

    function selectedCandidate(preview = {}) {
        const candidates = Array.isArray(preview.candidate_positions) ? preview.candidate_positions : [];
        if (!candidates.length) return null;
        return candidates.find(candidate => candidate && candidate.id === preview.selected_candidate_id)
            || candidates.find(candidate => candidate && candidate.safe_to_place === true)
            || candidates.find(candidate => candidate && candidate.safe_to_place !== false)
            || candidates[0];
    }

    function candidateBlockNames(candidate = {}) {
        const columns = candidate.chunk_probe?.footprint_check?.columns;
        const center = Array.isArray(columns) ? columns.find(column => column?.center) : null;
        const names = center?.block_names || candidate.chunk_probe?.placement_check?.block_names || {};
        const body = Object.keys(names)
            .filter(key => /^body_\d+$/.test(key))
            .sort((left, right) => Number(left.slice(5)) - Number(right.slice(5)))
            .map(key => ({ level: Number(key.slice(5)) + 1, name: names[key] || null }));
        return { floor: names.floor || null, feet: names.feet || null, head: names.head || null, body };
    }

    function placementTargetHtml(candidate = null) {
        if (!candidate) return "";
        const names = readableCandidateName(candidate);
        const safety = placementSafetyInfo(candidate);
        return `
            <div class="mount-placement-target">
                <div class="mount-target-head">
                    <div class="mount-target-id">
                        <span class="summary-kicker">${t("Gewählter Standplatz")}</span>
                        <strong>${html().escapeHtml(names.label)} · ${html().escapeHtml(names.distance)}</strong>
                        <small>${html().escapeHtml(positionText(candidate))}</small>
                    </div>
                </div>
                <span class="status-pill ${safety.pillClass}"${safety.status === "unchecked" ? ' aria-describedby="mountUncheckedReason"' : ""}>${html().escapeHtml(safety.label)}</span>
                ${safety.status === "unchecked" ? uncheckedPlacementHtml(candidate) : ""}
                <div class="mount-target-actions">
                    <button type="button" class="btn btn-secondary btn-sm mount-tech-open" id="btnMountTechDetails" aria-haspopup="dialog">${t("Prüfdetails")}</button>
                </div>
            </div>
        `;
    }

    function footprintColumns(candidate = {}) {
        const columns = candidate?.chunk_probe?.footprint_check?.columns;
        if (!Array.isArray(columns)) return [];
        return columns.filter(column => column && Number.isFinite(Number(column.block_x)) && Number.isFinite(Number(column.block_z)));
    }

    function footprintCellHtml(column) {
        if (!column) return `<div class="mount-fp-cell unknown" title="${t("keine Daten")}"></div>`;
        const names = column.block_names || {};
        const floor = names.floor || null;
        const color = blockColor(floor);
        const center = column.center ? " center" : "";
        const title = t("{x}/{z}: Boden {name}", { x: column.block_x, z: column.block_z, name: floor ? shortBlockName(floor) : t("ungelesen") });
        // A column's isolated placement flag cannot label the full footprint:
        // edge overhangs may be allowed, and taller mounts require more layers.
        // Show floor data here; the backend's overall assessment gives safety.
        if (color === null) return `<div class="mount-fp-cell unknown${center}" title="${html().escapeAttr(title)}"></div>`;
        if (color === "air") return `<div class="mount-fp-cell air${center}" title="${html().escapeAttr(title)}"></div>`;
        return `<div class="mount-fp-cell${center}" style="background:${color}" title="${html().escapeAttr(title)}"></div>`;
    }

    function footprintGridHtml(candidate = null) {
        const columns = candidate ? footprintColumns(candidate) : [];
        const footprint = candidate?.chunk_probe?.footprint_check || {};
        if (!columns.length) {
            // Specific diagnostic issues already explain the missing data and
            // the next step. Do not add a second, generic retry instruction.
            if (candidate && placementIssues(candidate).length) return "";
            return `
                <div class="mount-footprint">
                    <div class="mount-footprint-head"><strong>${t("Boden unter dem Mount")}</strong><small>${t("Boden noch nicht geprüft")}</small></div>
                    <p class="mount-fp-caption">${t("Für diese Auswahl liegen noch keine Footprint-Spalten vor. Lade eine neue Vorschau oder wähle eine geprüfte Richtung.")}</p>
                </div>
            `;
        }
        const xs = columns.map(column => Number(column.block_x));
        const zs = columns.map(column => Number(column.block_z));
        const minX = Math.min(...xs);
        const maxX = Math.max(...xs);
        const minZ = Math.min(...zs);
        const maxZ = Math.max(...zs);
        const width = maxX - minX + 1;
        const depth = maxZ - minZ + 1;
        const cells = [];
        for (let z = minZ; z <= maxZ; z += 1) {
            for (let x = minX; x <= maxX; x += 1) {
                cells.push(footprintCellHtml(columns.find(column => Number(column.block_x) === x && Number(column.block_z) === z)));
            }
        }
        const caption = placementIssues(candidate).length ? ""
            : candidate.safe_to_place !== true ? placementMessage(candidate)
                : Number(footprint.edge_overhang_count) > 0 ? footprint.message : "";
        const dimensions = t("{width}×{depth} Felder (X×Z) · {count} Spalten", { width, depth, count: columns.length });
        const x = finiteInput(candidate.x);
        const z = finiteInput(candidate.z);
        const half = finiteInput(footprint.half_width);
        // The collision footprint is square in world X/Z coordinates. Showing
        // its exact overlap explains why a square can touch a 3×2 block grid.
        const hasBounds = x !== null && z !== null && half !== null && half > 0
            && x - half >= minX - 0.000001 && x + half <= maxX + 1.000001
            && z - half >= minZ - 0.000001 && z + half <= maxZ + 1.000001;
        const percent = value => Number(value.toFixed(5));
        const bounds = hasBounds ? `
            <span class="mount-fp-bounds" data-width-blocks="${half * 2}" style="left:${percent((x - half - minX) / width * 100)}%;top:${percent((z - half - minZ) / depth * 100)}%;width:${percent(half * 2 / width * 100)}%;height:${percent(half * 2 / depth * 100)}%" aria-hidden="true"></span>
            <span class="mount-fp-position" style="left:${percent((x - minX) / width * 100)}%;top:${percent((z - minZ) / depth * 100)}%" aria-hidden="true"></span>` : "";
        const sizeText = hasBounds ? t("Kollisionsfläche: {size}×{size} Blöcke", { size: formatGermanNumber(half * 2) }) : "";
        const clearance = finiteInput(footprint.clearance_blocks);
        const clearanceText = clearance !== null && clearance > 0 ? t("Körperraum: {count} Blockebenen", { count: clearance }) : "";
        const measured = [sizeText, clearanceText].filter(Boolean).join(" · ");
        const diagramLabel = [dimensions, sizeText, hasBounds ? t("Grüner Rahmen: Kollisionsfläche. Punkt: Mount-Position.") : ""].filter(Boolean).join(". ");
        return `
            <div class="mount-footprint">
                <div class="mount-footprint-head"><strong>${t("Boden unter dem Mount")}</strong><small>${html().escapeHtml(dimensions)}</small></div>
                <div class="mount-fp-board${hasBounds ? " has-bounds" : ""}" data-grid-width="${width}" data-grid-depth="${depth}" role="img" aria-label="${html().escapeAttr(diagramLabel)}">
                    <div class="mount-fp-grid" style="grid-template-columns:repeat(${width},36px)" aria-hidden="true">${cells.join("")}</div>${bounds}
                </div>
                <div class="mount-fp-legend">${hasBounds ? `<span><i class="mount-fp-key" aria-hidden="true"></i>${t("Kollisionsfläche")}</span>` : ""}<span>${blockTile("minecraft:air")} ${t("Überhang/frei")}</span><span>${blockTile("?")} ${t("ungelesen")}</span></div>
                ${measured ? `<p class="mount-fp-size">${html().escapeHtml(measured)}</p>` : ""}
                ${caption ? `<p class="mount-fp-caption">${html().escapeHtml(caption)}</p>` : ""}
            </div>
        `;
    }

    function mapSlotForCandidate(candidate = {}, index = 0, total = 1) {
        const id = String(candidate.id || "");
        if (id.startsWith("blickrichtung_") || id.startsWith("north_")) return { left: 50, top: 18, labelTop: 8, labelLeft: 50 };
        if (id.startsWith("rechts_") || id.startsWith("east_")) return { left: 82, top: 50, labelTop: 40, labelLeft: 88 };
        if (id.startsWith("links_") || id.startsWith("west_")) return { left: 18, top: 50, labelTop: 40, labelLeft: 12 };
        if (id.startsWith("hinter_dir_") || id.startsWith("south_")) return { left: 50, top: 82, labelTop: 92, labelLeft: 50 };
        const offset = candidate?.offset || {};
        const maxOffset = Math.max(2, Math.abs(Number(offset.x) || 0), Math.abs(Number(offset.z) || 0), Number(candidate?.distance) || 0);
        if (maxOffset > 0 && (Number(offset.x) || Number(offset.z))) {
            return {
                left: Math.max(16, Math.min(84, 50 + ((Number(offset.x) || 0) / maxOffset) * 30)),
                top: Math.max(16, Math.min(84, 50 + ((Number(offset.z) || 0) / maxOffset) * 30)),
                labelLeft: 50,
                labelTop: 90,
            };
        }
        const angle = (Math.PI * 2 * index) / Math.max(1, total) - Math.PI / 2;
        return { left: 50 + Math.cos(angle) * 30, top: 50 + Math.sin(angle) * 30, labelLeft: 50, labelTop: 90 };
    }

    function placementSketchHtml(preview = {}) {
        const candidates = Array.isArray(preview.candidate_positions) ? preview.candidate_positions : [];
        if (!candidates.length) return "";
        const selectedId = selectedCandidate(preview)?.id || "";
        const points = candidates.map((candidate, index) => {
            const safety = placementSafetyInfo(candidate);
            const slot = mapSlotForCandidate(candidate, index, candidates.length);
            const active = candidate?.id === selectedId;
            const disabled = safety.status === "unsafe";
            const names = readableCandidateName(candidate);
            const title = `${names.label}: ${safety.label} · ${placementMessage(candidate)}`;
            return `<button type="button" class="mount-map-point ${safety.status} ${active ? "active" : ""}" data-candidate-id="${html().escapeAttr(candidate?.id || "")}" style="left:${slot.left}%;top:${slot.top}%;" title="${html().escapeAttr(title)}" aria-label="${html().escapeAttr(`${names.label} · ${names.distance} · ${safety.label}`)}" aria-pressed="${active}" ${disabled ? "disabled" : ""}>
                    <span class="mp-label">${html().escapeHtml(names.label)}</span>
                    <span class="mp-meta"><span class="mp-status" aria-hidden="true">${safety.marker}</span>${html().escapeHtml(names.distance)}</span>
                </button>`;
        }).join("");
        return `
            <div class="mount-placement-map" role="group" aria-label="${t("Standplatz wählen")}">
                <div class="mount-map-board"><span class="mount-map-axis"></span><span class="mount-map-center">${t("Spieler")}</span>${points}</div>
            </div>
        `;
    }

    function attemptStatusLabel(attempt = {}) {
        if (attempt.status === "safe" || attempt.safe_to_place === true) return t("sicher");
        if (attempt.status === "unsafe" || attempt.safe_to_place === false) return t("nicht möglich");
        return t("ungeprüft");
    }

    function attemptStatusClass(attempt = {}) {
        if (attempt.status === "safe" || attempt.safe_to_place === true) return "safe";
        if (attempt.status === "unsafe" || attempt.safe_to_place === false) return "unsafe";
        return "unchecked";
    }

    function scanLadderHtml(candidate = {}) {
        const attempts = Array.isArray(candidate.radius_scan_attempts) ? candidate.radius_scan_attempts : [];
        if (!attempts.length) return `<p class="mount-tech-note">${t("Keine Distanzversuche protokolliert.")}</p>`;
        const chips = attempts.map((attempt, index) => {
            const distance = Number.isFinite(Number(attempt.distance)) ? t("{value} Blöcke", { value: formatCoord(attempt.distance) }) : t("Versuch {n}", { n: index + 1 });
            return `<span class="mount-scan-chip ${attemptStatusClass(attempt)}" title="${html().escapeAttr(attempt.warning || "")}">${html().escapeHtml(distance)} · ${html().escapeHtml(attemptStatusLabel(attempt))}</span>`;
        }).join("");
        const adjustment = candidate.radius_scan_adjusted ? `<p class="mount-tech-note">${t("Abstand innerhalb des Radius angepasst")}</p>` : "";
        return `<div class="mount-scan-ladder">${chips}</div>${adjustment}`;
    }

    function technicalOverlayHtml(candidate = null, warnings = []) {
        let inner;
        if (candidate) {
            const names = readableCandidateName(candidate);
            const safety = placementSafetyInfo(candidate);
            const blocks = candidateBlockNames(candidate);
            const blockRow = (label, name) => `<tr><th scope="row">${html().escapeHtml(label)}</th><td>${blockTile(name)} ${name ? html().escapeHtml(shortBlockName(name)) : t("ungelesen")}</td></tr>`;
            const upperBlocks = blocks.body.slice().reverse().map(block => blockRow(t("Körperraum Ebene {level}", { level: block.level }), block.name)).join("");
            inner = `
                <div class="mount-tech-head">
                    <strong id="mountTechTitle" tabindex="-1">${t("Prüfdetails")} · ${html().escapeHtml(names.label)}</strong>
                    <button type="button" class="mount-tech-close" id="btnMountTechClose" aria-label="${t("Schließen")}">✕</button>
                </div>
                <p class="mount-tech-note mount-tech-position"><span class="status-pill ${safety.pillClass}">${html().escapeHtml(safety.label)}</span><span>${html().escapeHtml(positionText(candidate))}</span></p>
                ${placementIssuesHtml(candidate)}
                ${footprintGridHtml(candidate)}
                <div class="mount-tech-section"><div class="mount-tech-label">${t("Distanzsuche")}</div>${scanLadderHtml(candidate)}<p class="mount-tech-note">${t("Die Suche folgt vier Richtungslinien. An jedem Standplatz wird die gesamte Kollisionsfläche geprüft.")}</p>${warningListHtml(warnings)}</div>
                <details class="mount-probe-details" data-disclosure="block-probe"><summary>${t("Blockdaten am Mittelpunkt")}</summary><table class="mount-tech-blocks">${upperBlocks}${blockRow(t("Kopfraum"), blocks.head)}${blockRow(t("Fußraum"), blocks.feet)}${blockRow(t("Boden"), blocks.floor)}</table></details>
            `;
        } else {
            inner = `
                <div class="mount-tech-head">
                    <strong id="mountTechTitle" tabindex="-1">${t("Prüfdetails")}</strong>
                    <button type="button" class="mount-tech-close" id="btnMountTechClose" aria-label="${t("Schließen")}">✕</button>
                </div>
                <p class="mount-tech-note">${t("Keine auswertbare Auswahl vorhanden.")}</p>
                ${warningListHtml(warnings)}
            `;
        }
        return `<dialog class="mount-tech-overlay" id="mountTechOverlay" aria-labelledby="mountTechTitle"><div class="mount-tech-modal">${inner}</div></dialog>`;
    }

    function mountOptionHtml(option = {}, selectedMountType = "minecraft:horse") {
        const id = option.id || "";
        const label = t(option.label || id || "Mount");
        return `<option value="${html().escapeAttr(id)}" ${id === selectedMountType ? "selected" : ""}>${html().escapeHtml(label)}</option>`;
    }

    function optionRows(options, selectedValue) {
        return options.map(([value, label]) => `<option value="${html().escapeAttr(String(value))}" ${Number(selectedValue) === Number(value) ? "selected" : ""}>${html().escapeHtml(label)}</option>`).join("");
    }

    // Die Chips beschreiben nur, welche Bereiche das Spiel würfelt -- einmal
    // gelesen, danach dauerhaft 244 px. Deshalb hinter eine Zeile gelegt.
    function randomHorseProfileSummaryHtml() {
        return `
            <details class="mount-profile-ranges-disclosure" data-disclosure="profile-ranges">
                <summary>${t("Welche Bereiche gewürfelt werden")}</summary>
                <div id="mountHorseRangeSummary" class="mount-horse-profile-ranges">
                    <div class="mount-profile-chip"><strong>${t("Leben")}</strong><span>${t("15–30 zufällig")}</span><small>${t("7,5–15 Herzen")}</small></div>
                    <div class="mount-profile-chip"><strong>${t("Bewegung")}</strong><span>${t("0,1125–0,3375")}</span><small>${t("≈ {min}–{max} Blöcke/s", { min: formatGermanNumber(movementBlocksPerSecond(0.1125)), max: formatGermanNumber(movementBlocksPerSecond(0.3375)) })}</small></div>
                    <div class="mount-profile-chip"><strong>${t("Sprung")}</strong><span>${t("0,4–1,0")}</span><small>${t("≈ {min}–{max} Blöcke hoch", { min: formatGermanNumber(jumpHeightBlocks(0.4)), max: formatGermanNumber(jumpHeightBlocks(1.0)) })}</small></div>
                    <div class="mount-profile-chip"><strong>${t("Farbe")}</strong><span>${t("7 Varianten")}</span></div>
                    <div class="mount-profile-chip"><strong>${t("Markierung")}</strong><span>${t("5 Varianten")}</span></div>
                    <div class="mount-profile-chip"><strong>${t("Zähmfortschritt")}</strong><span>${t("0–99 zufällig")}</span><small>${t("wie ein wildes Tier")}</small></div>
                </div>
            </details>
        `;
    }

    function customHorseProfileFieldsHtml(profile) {
        return `
            <div class="mount-horse-appearance-grid">
                <div class="field-group"><label for="mountHorseColorSelect">${t("Farbe")}</label><select id="mountHorseColorSelect" class="select-field mount-horse-profile-field">${optionRows(HORSE_COLOR_OPTIONS, profile.color)}</select></div>
                <div class="field-group"><label for="mountHorseMarkSelect">${t("Markierung")}</label><select id="mountHorseMarkSelect" class="select-field mount-horse-profile-field">${optionRows(HORSE_MARK_OPTIONS, profile.mark_variant)}</select></div>
            </div>
            <details class="mount-advanced-options" data-disclosure="horse-stats">
                <summary>${t("Werte anpassen")}</summary>
                <div class="mount-horse-profile-grid custom">
                    <div class="field-group"><label for="mountHorseHealthInput">${t("Leben")}</label><input id="mountHorseHealthInput" class="input-field mount-horse-profile-field" type="number" min="15" max="30" step="1" required value="${html().escapeAttr(String(profile.health))}" aria-describedby="mountHorseHealthHint" /><small id="mountHorseHealthHint" class="field-note">${t("15–30 Leben · 7,5–15 Herzen")}</small></div>
                    <div class="field-group"><label for="mountHorseMovementInput">${t("Geschwindigkeit")}</label><input id="mountHorseMovementInput" class="input-field mount-horse-profile-field" type="number" min="0.1125" max="0.3375" step="0.0001" required data-number-hint="movement" value="${html().escapeAttr(String(profile.movement))}" aria-describedby="mountHorseMovementHint" /><small id="mountHorseMovementHint" class="field-note mount-conversion-hint">${html().escapeHtml(movementHintText(profile.movement))}</small></div>
                    <div class="field-group"><label for="mountHorseJumpInput">${t("Sprungstärke")}</label><input id="mountHorseJumpInput" class="input-field mount-horse-profile-field" type="number" min="0.4" max="1" step="0.01" required data-number-hint="jump_strength" value="${html().escapeAttr(String(profile.jump_strength))}" aria-describedby="mountHorseJumpHint" /><small id="mountHorseJumpHint" class="field-note mount-conversion-hint">${html().escapeHtml(jumpHintText(profile.jump_strength))}</small></div>
                    <div class="field-group"><label for="mountHorseTemperInput">${t("Zähmfortschritt")}</label><input id="mountHorseTemperInput" class="input-field mount-horse-profile-field" type="number" min="0" max="99" step="1" required data-number-hint="temper" value="${html().escapeAttr(String(profile.temper))}" aria-describedby="mountHorseTemperHint" /><small id="mountHorseTemperHint" class="field-note mount-conversion-hint">${html().escapeHtml(temperHintText(profile.temper))}</small></div>
                </div>
            </details>
        `;
    }

    function horseProfileHtml(horseProfile = DEFAULT_HORSE_PROFILE) {
        const profile = normalizedHorseProfile(horseProfile);
        const isCustom = profile.mode === "custom";
        return `
            <div class="mount-horse-profile-card">
                <div class="field-group mount-horse-profile-header">
                    <label for="mountHorseProfileMode">${t("Eigenschaften")}</label>
                    <select id="mountHorseProfileMode" class="select-field"><option value="random_like_game" ${isCustom ? "" : "selected"}>${t("Zufällig wie im Spiel")}</option><option value="custom" ${isCustom ? "selected" : ""}>${t("Selbst festlegen")}</option></select>
                </div>
                ${isCustom ? customHorseProfileFieldsHtml(profile) : randomHorseProfileSummaryHtml()}
            </div>
        `;
    }

    // Editierbare Werte pro Mount-Typ: nur Felder, die das Vanilla-Spiel selbst
    // pro Exemplar würfelt (Evidenz-Reports 2026-07-10). Alles andere bleibt fix.
    const HEALTH_STAT_FIELD = { id: "mountStatHealthInput", key: "health", label: t("Leben"), min: 15, max: 30, step: 1, note: t("Vanilla-Bereich: 15 bis 30.") };
    // wildOnly: Zähmen entfernt das Temper-Tag komplett, das Feld verschwindet
    // deshalb mit gesetztem Haken statt einen verworfenen Wert anzubieten.
    const TEMPER_STAT_FIELD = {
        id: "mountStatTemperInput",
        key: "temper",
        label: t("Zähmfortschritt"),
        min: 0,
        max: 99,
        step: 1,
        note: t("Vanilla-Bereich: 0 bis 99."),
        wildOnly: true,
    };
    const MOUNT_STATS_FIELDS = {
        "minecraft:donkey": [HEALTH_STAT_FIELD, TEMPER_STAT_FIELD],
        "minecraft:mule": [HEALTH_STAT_FIELD, TEMPER_STAT_FIELD],
        "minecraft:skeleton_horse": [
            { id: "mountStatJumpInput", key: "jump_strength", label: t("Sprungstärke"), min: 0.4, max: 1, step: 0.01, note: t("Vanilla-Bereich: 0,4 bis 1,0.") },
        ],
    };

    function statFieldHtml(field, mountStats = {}) {
        const statValue = finiteInput(mountStats?.[field.key]);
        const hintText = field.key === "jump_strength" ? jumpHintText(statValue) : field.key === "temper" ? temperHintText(statValue) : "";
        const hintId = field.id.replace(/Input$/, "Hint");
        const hint = hintText ? ` ${hintText}` : "";
        return `<div class="field-group"><label for="${field.id}">${field.label}</label><input id="${field.id}" class="input-field mount-stat-field" data-stat-key="${field.key}" data-number-hint="${field.key}" data-number-note="${html().escapeAttr(field.note)}" type="number" min="${field.min}" max="${field.max}" step="${field.step}" placeholder="${t("zufällig")}" value="${statValue !== null ? html().escapeAttr(String(statValue)) : ""}" aria-describedby="${hintId}" /><small id="${hintId}" class="field-note">${html().escapeHtml(field.note + hint)}</small></div>`;
    }

    function mountStatsHtml(selectedMountType, mountLabel = "Mount", mountStats = {}, mountTamed = false) {
        if (selectedMountType === "minecraft:camel") {
            return `<p class="mount-fixed-profile">${t("32 Leben · feste Eigenschaften · bereits zahm")}</p>`;
        }
        const fields = MOUNT_STATS_FIELDS[selectedMountType];
        if (!fields || !fields.length) return "";
        const tameable = selectedMountType === "minecraft:donkey" || selectedMountType === "minecraft:mule";
        const tamed = tameable && mountTamed === true;
        const statFields = fields.filter(field => !(field.wildOnly && tamed)).map(field => statFieldHtml(field, mountStats)).join("");
        const tamedField = tameable
            ? `<div class="mount-tamed-field"><label class="mount-tamed-toggle" for="mountStatTamedCheckbox"><input id="mountStatTamedCheckbox" type="checkbox" ${tamed ? 'checked aria-describedby="mountTamedHint" ' : ""}/> ${t("Gezähmt erzeugen")}</label>${tamed ? `<small id="mountTamedHint" class="field-note">${t("Gehört dem ausgewählten Spieler.")}</small>` : ""}</div>`
            : "";
        return `
            <div class="mount-horse-profile-card">
                <div class="mount-horse-profile-header"><strong>${t("Eigenschaften")}</strong><small class="field-note">${t("Leere Felder bleiben zufällig.")}${selectedMountType === "minecraft:skeleton_horse" ? ` ${t("Spawnt immer zahm.")}` : ""}</small></div>
                <div class="mount-horse-profile-grid custom">${statFields}</div>
                ${tamedField}
            </div>
        `;
    }

    function previewHtml(preview = null, { hasReferencePlayer = true } = {}) {
        if (!preview) return emptyStateHtml(hasReferencePlayer);
        const candidate = selectedCandidate(preview);
        const selected = candidate && candidate.safe_to_place !== false ? candidate : null;
        const canCreate = Boolean(preview.can_create && selected);
        const playerLabel = preview.player_reference?.player_label || t("Spieler");
        const blockingReasons = (preview.warnings || []).filter(Boolean);
        if (!preview.can_create && !blockingReasons.length) blockingReasons.push(t("Dieses Mount kann hier nicht erzeugt werden."));
        return `
            <div class="mount-placement-context">${t("In der Nähe von {player}", { player: html().escapeHtml(playerLabel) })}</div>
            <div class="mount-placement-results">
                ${placementSketchHtml(preview)}
                ${selected ? placementTargetHtml(selected) : `<div class="mount-placement-unavailable"><strong>${preview.can_create ? t("Kein Standplatz verfügbar") : t("Erzeugung nicht verfügbar")}</strong>${preview.can_create ? `<p>${t("Kein geeigneter Standplatz gefunden. Ändere den Suchabstand und prüfe erneut.")}</p>` : warningListHtml(blockingReasons, { blocked: true })}${candidate ? `<button type="button" class="btn btn-secondary btn-sm mount-tech-open" id="btnMountTechDetails" aria-haspopup="dialog">${t("Prüfdetails")}</button>` : ""}</div>`}
            </div>
            ${!preview.can_create && selected ? warningListHtml(blockingReasons, { blocked: true }) : ""}
            <div class="mount-queue-actions">
                <button id="btnMountCreate" class="btn btn-save" type="button" ${canCreate ? "" : "disabled"} title="${html().escapeAttr(canCreate ? t("Merkt das gewählte Mount als ungespeicherte Änderung vor.") : queueDisabledReason(preview))}">${t("Mount vormerken")}</button>
            </div>
            ${technicalOverlayHtml(candidate, preview.can_create ? preview.warnings : [])}
        `;
    }

    function queueDisabledReason(preview) {
        if (preview && !preview.can_create) {
            return (preview.warnings || []).filter(Boolean).join(" ") || t("Dieses Mount kann hier nicht erzeugt werden.");
        }
        return t("Prüfe zuerst einen geeigneten Standplatz.");
    }

    function optionsHtml(selectedMountType = "minecraft:horse", mountOptions = MOUNT_TYPE_OPTIONS, selectedPlacementRadius = 6, horseProfile = DEFAULT_HORSE_PROFILE, mountStats = {}, mountTamed = false) {
        const options = Array.isArray(mountOptions) && mountOptions.length ? mountOptions : MOUNT_TYPE_OPTIONS;
        const model = window.MCBEMountModelPreview?.markup({ mountType: selectedMountType, horseProfile, mountTamed }) || "";
        return `
            <div class="mount-config-grid">
                <div class="mount-options-card">
                    <h3 class="mount-section-title">${t("Mount konfigurieren")}</h3>
                    <div class="field-group"><label for="mountTypeSelect">${t("Mount-Typ")}</label><div class="mount-type-row">${mountIconSvg(selectedMountType, normalizedHorseProfile(horseProfile).color, 34)}<select id="mountTypeSelect" class="select-field">${options.map(option => mountOptionHtml(option, selectedMountType)).join("")}</select></div></div>
                    ${selectedMountType === "minecraft:horse" ? horseProfileHtml(horseProfile) : mountStatsHtml(selectedMountType, t(options.find(option => option.id === selectedMountType)?.label || "Mount"), mountStats, mountTamed)}
                </div>
                ${model}
            </div>
            <div class="mount-placement-toolbar">
                <h3 class="mount-section-title">${t("Standplatz wählen")}</h3>
                <div class="mount-scan-controls">
                    <div class="field-group mount-radius-field"><label for="mountPlacementRadiusInput">${t("Suchabstand (Blöcke)")}</label><input id="mountPlacementRadiusInput" class="input-field" type="number" min="2" max="16" step="1" value="${html().escapeAttr(String(selectedPlacementRadius || 6))}" /></div>
                    <button id="btnMountPreview" class="btn btn-primary" type="button">${t("Standplätze prüfen")}</button>
                </div>
            </div>
        `;
    }

    function pendingMountsHtml(pendingMounts = []) {
        const mounts = Array.isArray(pendingMounts) ? pendingMounts : [];
        if (!mounts.length) return "";
        const cards = mounts.map(mount => {
            const position = mount.selectedPosition || {};
            const safety = mount.safetyStatus === "safe" ? t("Sicher geprüft") : t("Ungeprüfte Position");
            const safetyClass = mount.safetyStatus === "safe" ? "" : " warning";
            const details = [];
            if (mount.horseProfile?.mode === "custom") {
                const color = HORSE_COLOR_OPTIONS.find(([value]) => value === mount.horseProfile.color)?.[1];
                const mark = HORSE_MARK_OPTIONS.find(([value]) => value === mount.horseProfile.mark_variant && value > 0)?.[1];
                details.push(...[color, mark].filter(Boolean));
                details.push(
                    t("{value} Leben", { value: mount.horseProfile.health }),
                    t("Bewegung {value}", { value: mount.horseProfile.movement }),
                    t("Sprung {value}", { value: mount.horseProfile.jump_strength }),
                    t("Zähmfortschritt {value}", { value: mount.horseProfile.temper })
                );
            } else if (mount.mountStats && typeof mount.mountStats === "object") {
                if (mount.mountStats.health != null) details.push(t("{value} Leben", { value: mount.mountStats.health }));
                if (mount.mountStats.jump_strength != null) details.push(t("Sprung {value}", { value: mount.mountStats.jump_strength }));
                if (mount.mountStats.temper != null) details.push(t("Zähmfortschritt {value}", { value: mount.mountStats.temper }));
            } else {
                details.push(t("Zufällige Eigenschaften wie im Spiel"));
            }
            if (mount.tamed) details.push(t("Gezähmt · gehört dem aktuellen Spieler"));
            return `
                <article class="pending-mount-card" data-pending-mount-id="${html().escapeAttr(mount.id || "")}">
                    <span class="pending-mount-icon">${mountIconSvg(mount.mountType, mount.horseProfile?.color || 0, 40)}</span>
                    <div class="pending-mount-copy">
                        <div><span class="status-pill changed">${t("Neu")}</span><strong>${html().escapeHtml(t(mount.mountLabel || mount.mountType || "Mount"))}</strong></div>
                        <small>${html().escapeHtml(positionText(position))} · <span class="pending-mount-safety${safetyClass}">${html().escapeHtml(safety)}</span></small>
                        <details class="pending-mount-details" data-disclosure="pending-${html().escapeAttr(mount.id || "")}"><summary>${t("Eigenschaften")}</summary><small>${html().escapeHtml(details.join(" · "))}</small></details>
                    </div>
                    <button class="btn btn-danger-soft btn-sm pending-mount-remove" type="button" data-remove-pending-mount="${html().escapeAttr(mount.id || "")}">${t("Entfernen")}</button>
                </article>
            `;
        }).join("");
        return `
            <section class="pending-mounts-panel">
                <div class="pending-mounts-header">
                    <div><span class="summary-kicker">${t("Ungespeicherte Änderungen")}</span><strong>${mounts.length === 1 ? t("1 Mount vorgemerkt") : t("{count} Mounts vorgemerkt", { count: mounts.length })}</strong></div>
                    <div class="pending-mounts-actions">
                        <button id="btnMountReviewPending" class="btn btn-secondary btn-sm" type="button">${t("Speichern prüfen")}</button>
                        <button id="btnMountDiscardPending" class="btn btn-danger-soft btn-sm" type="button">${t("Alle verwerfen")}</button>
                    </div>
                </div>
                <div class="pending-mount-list">${cards}</div>
            </section>
        `;
    }

    function emptyStateHtml(hasReferencePlayer = false) {
        return `<div class="mount-empty-state">${hasReferencePlayer ? t("Prüfe die Umgebung, um einen Standplatz auszuwählen.") : t("Lade zuerst eine Welt und einen Spieler.")}</div>`;
    }

    function applyMountPanelState({ previewPanel = null, optionsPanel = null, pendingPanel = null, statusPanel = null, preview = null, pendingMounts = [], message = "", status = "info", selectedMountType = "minecraft:horse", selectedPlacementRadius = 6, horseProfile = DEFAULT_HORSE_PROFILE, mountStats = {}, mountTamed = false, hasReferencePlayer = false } = {}) {
        if (previewPanel) previewPanel.innerHTML = previewHtml(preview, { hasReferencePlayer });
        if (optionsPanel) optionsPanel.innerHTML = optionsHtml(selectedMountType, preview?.mount_options, selectedPlacementRadius, horseProfile, mountStats, mountTamed);
        if (pendingPanel) pendingPanel.innerHTML = pendingMountsHtml(pendingMounts);
        if (statusPanel) {
            statusPanel.className = `mount-create-status ${status}`;
            statusPanel.textContent = message || "";
        }
    }

    window.MCBEMountView = {
        DEFAULT_HORSE_PROFILE,
        applyMountPanelState,
        emptyStateHtml,
        finiteInput,
        jumpHeightBlocks,
        jumpHintText,
        mountIconSvg,
        mountStatsHtml,
        movementBlocksPerSecond,
        movementHintText,
        numberInputError,
        optionsHtml,
        pendingMountsHtml,
        positionText,
        previewHtml,
        queueDisabledReason,
        temperHintText,
        warningListHtml,
    };
}());
