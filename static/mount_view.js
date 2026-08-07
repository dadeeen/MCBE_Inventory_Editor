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
    const DIRECTION_LINE_SUMMARY_LABEL = t("Richtungslinien:");

    function injectMountViewStyles() {
        if (typeof document === "undefined" || document.getElementById("mountViewDynamicStyles")) return;
        const style = document.createElement("style");
        style.id = "mountViewDynamicStyles";
        style.textContent = `
            .mounts-panel{--m-accent-text:#bae6fd;--m-accent-strong:#38bdf8;--m-accent-border:rgba(56,189,248,.45);--m-accent-bg:rgba(56,189,248,.14);--m-accent-glow:rgba(56,189,248,.10);--m-grid-line:rgba(255,255,255,.045);--m-node-bg:rgba(15,23,42,.80)}
            :root[data-theme="light"] .mounts-panel{--m-accent-text:#075985;--m-accent-strong:#0284c7;--m-accent-border:rgba(2,132,199,.45);--m-accent-bg:rgba(14,165,233,.12);--m-accent-glow:rgba(14,165,233,.10);--m-grid-line:rgba(15,23,42,.06);--m-node-bg:rgba(255,255,255,.92)}
            @media(prefers-color-scheme:light){:root[data-theme="system"] .mounts-panel{--m-accent-text:#075985;--m-accent-strong:#0284c7;--m-accent-border:rgba(2,132,199,.45);--m-accent-bg:rgba(14,165,233,.12);--m-accent-glow:rgba(14,165,233,.10);--m-grid-line:rgba(15,23,42,.06);--m-node-bg:rgba(255,255,255,.92)}}
            .mount-preview-summary,.mount-options-card,.mount-horse-profile-card{border:1px solid var(--border-color);border-radius:14px;background:var(--surface-strong)}
            .mount-preview-summary .summary-kicker{display:block}
            .mount-horse-profile-card{margin:14px 0 12px;padding:12px}.mount-horse-profile-header{display:grid;grid-template-columns:minmax(0,1fr) minmax(220px,.36fr);gap:12px;align-items:end;margin-bottom:10px}.mount-horse-profile-header strong,.mount-horse-profile-header small{display:block}.mount-horse-profile-header small{margin-top:3px;color:var(--text-secondary);font-size:.76rem;line-height:1.35}
            .mount-horse-profile-ranges{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;margin-top:8px}.mount-profile-chip{padding:10px 11px;border-radius:12px;border:1px solid var(--warning-border);background:var(--warning-bg)}.mount-profile-chip strong,.mount-profile-chip span,.mount-profile-chip small{display:block}.mount-profile-chip strong{color:var(--warning-text);font-size:.72rem;letter-spacing:.05em;text-transform:uppercase}.mount-profile-chip span{margin-top:3px;color:var(--text-primary);font-size:.88rem;font-weight:700}.mount-profile-chip small{margin-top:2px;color:var(--text-secondary);font-size:.72rem}.mount-profile-mode-note{display:block;margin-top:8px}.mount-conversion-hint{color:var(--text-primary);font-weight:700;white-space:nowrap}
            .mount-icon{display:inline-block;flex:none}.mount-icon svg{display:block}.mount-type-row{display:flex;align-items:center;gap:10px}.mount-summary-icon{display:inline-flex;align-items:center;gap:10px}
            .mount-placement-target{display:grid;gap:12px;margin:12px 0;padding:14px;border:1px solid var(--m-accent-border);border-radius:14px;background:var(--surface-strong)}.mount-target-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;flex-wrap:wrap}.mount-target-id{display:grid;gap:3px}.mount-target-id .summary-kicker{color:var(--m-accent-text)}.mount-target-id strong{font-size:1.15rem;color:var(--text-primary)}.mount-target-id small{color:var(--text-secondary);font-size:.8rem}.mount-block-stack{display:grid;gap:6px;max-width:340px}.mount-block-row{display:flex;align-items:center;gap:8px;font-size:.82rem;color:var(--text-secondary)}.mount-block-row b{margin-left:auto;color:var(--text-primary);font-weight:700}.mount-block-tile{display:inline-block;width:16px;height:16px;border-radius:4px;border:1px solid var(--control-border);flex:none;vertical-align:-3px}.mount-block-tile.air{background:transparent;border-style:dashed}.mount-block-tile.unknown{background:var(--warning-bg);border-style:dashed;border-color:var(--warning-border)}.mount-target-actions{display:flex;gap:8px;flex-wrap:wrap}.mount-tech-open{padding:7px 12px;border-radius:10px;border:1px solid var(--control-border);background:var(--surface-soft);color:var(--text-primary);font-size:.8rem;font-weight:700;cursor:pointer}.mount-tech-open:hover{border-color:var(--m-accent-border);background:var(--m-accent-bg)}
            .mount-placement-map{display:grid;gap:10px;margin:12px 0;padding:12px;border:1px solid var(--border-color);border-radius:14px;background:var(--surface-strong)}.mount-map-header{display:flex;justify-content:space-between;gap:10px;align-items:baseline}.mount-map-header strong{font-size:.88rem}.mount-map-header small,.mount-map-legend{color:var(--text-secondary);font-size:.74rem}.mount-map-board{position:relative;min-height:236px;border-radius:14px;border:1px solid var(--border-color);background-image:linear-gradient(var(--m-grid-line) 1px,transparent 1px),linear-gradient(90deg,var(--m-grid-line) 1px,transparent 1px),radial-gradient(circle at 50% 50%,var(--m-accent-glow),transparent 34%);background-size:32px 32px,32px 32px,auto}.mount-map-axis{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);width:56%;height:56%;border:1px dashed var(--m-grid-line);border-radius:999px;pointer-events:none}.mount-map-axis::before,.mount-map-axis::after{content:"";position:absolute;background:var(--m-grid-line)}.mount-map-axis::before{left:50%;top:-18%;bottom:-18%;width:1px}.mount-map-axis::after{top:50%;left:-18%;right:-18%;height:1px}.mount-map-center{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);display:inline-grid;place-items:center;width:48px;height:48px;border-radius:999px;font-weight:900;font-size:.74rem;border:1px solid var(--m-accent-border);background:var(--m-accent-bg);color:var(--m-accent-text);z-index:2}.mount-map-point{position:absolute;transform:translate(-50%,-50%);display:grid;gap:3px;justify-items:center;width:92px;padding:7px 6px;border-radius:11px;border:1.5px solid var(--control-border);background:var(--m-node-bg);color:var(--text-primary);font:inherit;cursor:pointer;z-index:3;text-align:center}.mount-map-point .mp-label{font-size:.76rem;font-weight:700;line-height:1.1}.mount-map-point .mp-meta{display:flex;align-items:center;gap:5px;font-size:.7rem;color:var(--text-secondary)}.mount-map-point.safe{border-color:var(--success)}.mount-map-point.unchecked{border-color:var(--warning)}.mount-map-point.unsafe{border-color:var(--danger);cursor:not-allowed;opacity:.85}.mount-map-point.active{outline:2px solid var(--m-accent-strong);outline-offset:2px}.mount-map-point:hover:not(.unsafe){transform:translate(-50%,-50%) translateY(-1px)}.mount-map-point:focus-visible{outline:2px solid var(--m-accent-strong);outline-offset:2px}.mount-map-legend{display:flex;gap:10px;flex-wrap:wrap}.mount-map-legend span::before{content:"";display:inline-block;width:8px;height:8px;margin-right:5px;border-radius:999px;background:currentColor}.mount-map-legend .safe{color:var(--success-text)}.mount-map-legend .unchecked{color:var(--warning-text)}.mount-map-legend .unsafe{color:var(--danger-text)}
            .mount-footprint{margin:12px 0;padding:12px;border:1px solid var(--border-color);border-radius:14px;background:var(--surface-strong)}.mount-footprint-head{display:flex;justify-content:space-between;gap:10px;align-items:baseline;margin-bottom:8px}.mount-footprint-head strong{font-size:.85rem}.mount-footprint-head small{color:var(--text-secondary);font-size:.72rem}.mount-fp-grid{display:grid;gap:4px;width:max-content;max-width:100%}.mount-fp-cell{width:34px;height:34px;border-radius:6px;border:1px solid var(--control-border);background:var(--surface-soft)}.mount-fp-cell.center{outline:2px solid var(--m-accent-strong);outline-offset:1px}.mount-fp-cell.blocked{box-shadow:0 0 0 2px var(--danger) inset}.mount-fp-cell.air{background:transparent;border-style:dashed}.mount-fp-cell.unknown{background:var(--warning-bg);border-style:dashed;border-color:var(--warning-border)}.mount-fp-caption{margin:8px 0 0;color:var(--text-secondary);font-size:.76rem;line-height:1.4}.mount-fp-legend{display:flex;gap:12px;flex-wrap:wrap;margin-top:6px;color:var(--text-secondary);font-size:.72rem}
            .mount-tech-overlay{position:fixed;inset:0;z-index:20000;display:none;align-items:center;justify-content:center;padding:20px;background:rgba(0,0,0,.6);backdrop-filter:blur(6px)}.mount-tech-overlay.open{display:flex}.mount-tech-modal{width:100%;max-width:520px;max-height:88vh;overflow:auto;padding:18px;border-radius:16px;border:1px solid var(--border-color);background:var(--card-bg);backdrop-filter:blur(16px);color:var(--text-primary);box-shadow:var(--shadow-main)}.mount-tech-head{display:flex;justify-content:space-between;gap:12px;align-items:center}.mount-tech-head strong{font-size:1rem}.mount-tech-close{width:30px;height:30px;border-radius:8px;border:1px solid var(--control-border);background:transparent;color:var(--text-primary);cursor:pointer;font-size:.9rem}.mount-tech-close:hover{border-color:var(--danger-border);color:var(--danger-text)}.mount-tech-section{margin-top:14px}.mount-tech-label{font-size:.7rem;letter-spacing:.05em;text-transform:uppercase;color:var(--text-secondary);margin-bottom:6px}.mount-scan-ladder{display:flex;gap:6px;flex-wrap:wrap;margin:6px 0}.mount-scan-chip{display:inline-flex;align-items:center;gap:4px;font-size:.72rem;padding:3px 8px;border-radius:8px;border:1px solid var(--control-border)}.mount-scan-chip.safe{border-color:var(--success-border);background:var(--success-bg);color:var(--success-text)}.mount-scan-chip.unchecked{border-color:var(--warning-border);background:var(--warning-bg);color:var(--warning-text)}.mount-scan-chip.unsafe{border-color:var(--danger-border);background:var(--danger-bg);color:var(--danger-text)}.mount-tech-note{margin:6px 0 0;color:var(--text-secondary);font-size:.76rem;line-height:1.4}.mount-tech-blocks{width:100%;font-size:.78rem;border-collapse:collapse}.mount-tech-blocks td{padding:4px 0;vertical-align:middle}.mount-tech-blocks td:last-child{text-align:right;color:var(--text-primary)}
            @media(max-width:980px){.mount-horse-profile-header{grid-template-columns:1fr}}@media(max-width:620px){.mount-horse-profile-ranges{grid-template-columns:1fr}.mount-map-board{min-height:206px}.mount-map-point{width:80px}}
        `;
        document.head.appendChild(style);
    }

    injectMountViewStyles();

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
        if (value === null) return null;
        return value * MOVEMENT_TO_BLOCKS_PER_SECOND;
    }

    // Kubische Näherung der Sprunghöhe in Blöcken aus horse.jump_strength
    // (Minecraft-Wiki: 0,4 ≈ 1,1 Blöcke · 0,5 ≈ 1,6 · 1,0 ≈ 5,3).
    function jumpHeightBlocks(jumpStrength) {
        const x = finiteInput(jumpStrength);
        if (x === null) return null;
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
        if (value === null) return "";
        if (value >= 90) return t("fast gezähmt");
        if (value >= 60) return t("gut vorgezähmt");
        if (value >= 30) return t("etwas vorgezähmt");
        return t("praktisch ungezähmt");
    }

    function positionText(position = {}) {
        return `X ${formatCoord(position.x)} · Y ${formatCoord(position.y)} · Z ${formatCoord(position.z)}`;
    }

    // Zugeklappt, weil der Text sich nie ändert und die Liste sonst zwischen
    // Kopf und Skizze alles nach unten schiebt. Blockiert etwas das Erzeugen,
    // steht der Grund in dieser Liste -- dann wird aufgeklappt gestartet.
    function warningListHtml(warnings = [], { expanded = false } = {}) {
        const rows = (warnings || []).filter(Boolean);
        if (!rows.length) return "";
        return `
            <details class="mount-warning-list status-note warning" data-disclosure="preview-notes"${expanded ? " open" : ""}>
                <summary>${t("Hinweise zur Vorschau ({count})", { count: rows.length })}</summary>
                <ul>${rows.map(warning => `<li>${html().escapeHtml(t(warning))}</li>`).join("")}</ul>
            </details>
        `;
    }

    function placementSafetyInfo(candidate = {}) {
        if (candidate.safe_to_place === true) return { status: "safe", label: t("Sicher platzierbar"), pillClass: "success", marker: "OK" };
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

    function blockColor(name) {
        const n = String(name || "").toLowerCase();
        if (!n || n === "?") return null;
        if (n.includes("air")) return "air";
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

    function blockStackRowHtml(label, name) {
        const short = name ? html().escapeHtml(shortBlockName(name)) : t("ungelesen");
        return `<div class="mount-block-row">${blockTile(name)}<span>${label}</span><b>${short}</b></div>`;
    }

    function placementTargetHtml(candidate = null) {
        if (!candidate) return "";
        const names = readableCandidateName(candidate);
        const safety = placementSafetyInfo(candidate);
        const blocks = candidateBlockNames(candidate);
        return `
            <div class="mount-placement-target">
                <div class="mount-target-head">
                    <div class="mount-target-id">
                        <span class="summary-kicker">${t("Platzierungsziel")}</span>
                        <strong>${html().escapeHtml(names.label)} · ${html().escapeHtml(names.distance)}</strong>
                        <small>${html().escapeHtml(positionText(candidate))}</small>
                    </div>
                    <span class="status-pill ${safety.pillClass}">${html().escapeHtml(safety.label)}</span>
                </div>
                <div class="mount-block-stack">
                    ${blocks.body.slice().reverse().map(block => blockStackRowHtml(t("Körperraum Ebene {level}", { level: block.level }), block.name)).join("")}
                    ${blockStackRowHtml(t("Kopfraum"), blocks.head)}
                    ${blockStackRowHtml(t("Fußraum"), blocks.feet)}
                    ${blockStackRowHtml(t("Boden"), blocks.floor)}
                </div>
                <div class="mount-target-actions">
                    <button type="button" class="mount-tech-open" id="btnMountTechDetails">${t("Technische Details ansehen")}</button>
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
        const blocked = column.safe_to_place === false ? " blocked" : "";
        const title = t("{x}/{z}: Boden {name}", { x: column.block_x, z: column.block_z, name: floor ? shortBlockName(floor) : t("ungelesen") });
        if (color === null) return `<div class="mount-fp-cell unknown${center}${blocked}" title="${html().escapeAttr(title)}"></div>`;
        if (color === "air") return `<div class="mount-fp-cell air${center}${blocked}" title="${html().escapeAttr(title)}"></div>`;
        return `<div class="mount-fp-cell${center}${blocked}" style="background:${color}" title="${html().escapeAttr(title)}"></div>`;
    }

    function footprintGridHtml(candidate = null) {
        const columns = candidate ? footprintColumns(candidate) : [];
        const footprint = candidate?.chunk_probe?.footprint_check || {};
        if (!columns.length) {
            return `
                <div class="mount-footprint">
                    <div class="mount-footprint-head"><strong>${t("Tatsächliche Steine")}</strong><small>${t("Boden noch nicht geprüft")}</small></div>
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
        const cells = [];
        for (let z = minZ; z <= maxZ; z += 1) {
            for (let x = minX; x <= maxX; x += 1) {
                cells.push(footprintCellHtml(columns.find(column => Number(column.block_x) === x && Number(column.block_z) === z)));
            }
        }
        const caption = footprint.message || t("Boden-Spalten unter dem gewählten Standplatz.");
        return `
            <div class="mount-footprint">
                <div class="mount-footprint-head"><strong>${t("Tatsächliche Steine")}</strong><small>${t("Boden {width}×{height} unter der Auswahl", { width, height: maxZ - minZ + 1 })}</small></div>
                <div class="mount-fp-grid" style="grid-template-columns:repeat(${width},34px)">${cells.join("")}</div>
                <p class="mount-fp-caption">${html().escapeHtml(caption)}</p>
                <div class="mount-fp-legend"><span>${blockTile("minecraft:grass_block")} ${t("tragender Boden")}</span><span>${blockTile("minecraft:air")} ${t("Überhang/frei")}</span><span>${blockTile("?")} ${t("ungelesen")}</span></div>
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
        const selectedId = preview.selected_candidate_id || "";
        const points = candidates.map((candidate, index) => {
            const safety = placementSafetyInfo(candidate);
            const slot = mapSlotForCandidate(candidate, index, candidates.length);
            const active = candidate?.id === selectedId;
            const disabled = safety.status === "unsafe";
            const names = readableCandidateName(candidate);
            const blocks = candidateBlockNames(candidate);
            const title = `${names.label}: ${safety.label} · ${placementMessage(candidate)}`;
            return `<button type="button" class="mount-map-point ${safety.status} ${active ? "active" : ""}" data-candidate-id="${html().escapeAttr(candidate?.id || "")}" style="left:${slot.left}%;top:${slot.top}%;" title="${html().escapeAttr(title)}" ${disabled ? "disabled" : ""}>
                    <span class="mp-label">${html().escapeHtml(names.label)}</span>
                    <span class="mp-meta">${blockTile(blocks.floor)}<span>${html().escapeHtml(names.distance)}</span></span>
                </button>`;
        }).join("");
        return `
            <div class="mount-placement-map" aria-label="${t("Richtungsscan-Skizze")}">
                <div class="mount-map-header"><strong>${t("Richtungsscan-Skizze")}</strong><small>${t("4 Richtungslinien · noch kein vollständiger Flächenscan")}</small></div>
                <div class="mount-map-board"><span class="mount-map-axis"></span><span class="mount-map-center">${t("Spieler")}</span>${points}</div>
                <div class="mount-map-legend"><span class="safe">${t("sicher")}</span><span class="unchecked">${t("ungeprüft")}</span><span class="unsafe">${t("nicht platzierbar")}</span></div>
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

    function scanSummaryText(candidate = {}) {
        const checked = Number(candidate.radius_scan_checked_count || 0);
        if (!Number.isFinite(checked) || checked <= 0) return "";
        const safe = Number(candidate.radius_scan_safe_count || 0);
        const unchecked = Number(candidate.radius_scan_unchecked_count || 0);
        const unsafe = Number(candidate.radius_scan_unsafe_count || 0);
        const adjusted = candidate.radius_scan_adjusted ? ` · ${t("Abstand innerhalb des Radius angepasst")}` : "";
        return `${DIRECTION_LINE_SUMMARY_LABEL} ${t("{checked} Distanzversuche · {safe} sicher · {unchecked} ungeprüft · {unsafe} nicht möglich", { checked, safe, unchecked, unsafe })}${adjusted}.`;
    }

    function scanLadderHtml(candidate = {}) {
        const attempts = Array.isArray(candidate.radius_scan_attempts) ? candidate.radius_scan_attempts : [];
        if (!attempts.length) return `<p class="mount-tech-note">${t("Keine Distanzversuche protokolliert.")}</p>`;
        const chips = attempts.map((attempt, index) => {
            const distance = Number.isFinite(Number(attempt.distance)) ? t("{value} Blöcke", { value: formatCoord(attempt.distance) }) : t("Versuch {n}", { n: index + 1 });
            return `<span class="mount-scan-chip ${attemptStatusClass(attempt)}" title="${html().escapeAttr(attempt.warning || "")}">${html().escapeHtml(distance)} · ${html().escapeHtml(attemptStatusLabel(attempt))}</span>`;
        }).join("");
        const summary = scanSummaryText(candidate);
        return `<div class="mount-scan-ladder">${chips}</div>${summary ? `<p class="mount-tech-note">${html().escapeHtml(summary)}</p>` : ""}`;
    }

    function blockProbeReason(block = {}) {
        if (block.block_name) return block.block_name;
        if (block.reason) return block.reason;
        if (block.target_block?.reason) return block.target_block.reason;
        return "?";
    }

    function blockProbeReasonText(candidate = {}) {
        const blocks = candidate.chunk_probe?.placement_check?.blocks || {};
        if (!blocks.floor && !blocks.feet && !blocks.head) return "";
        return t("Blockprobe: floor={floor} · feet={feet} · head={head}", { floor: blockProbeReason(blocks.floor || {}), feet: blockProbeReason(blocks.feet || {}), head: blockProbeReason(blocks.head || {}) });
    }

    function technicalOverlayHtml(candidate = null) {
        let inner;
        if (candidate) {
            const names = readableCandidateName(candidate);
            const safety = placementSafetyInfo(candidate);
            const blocks = candidateBlockNames(candidate);
            const footprint = candidate.chunk_probe?.footprint_check || {};
            const probe = blockProbeReasonText(candidate);
            const blockRow = (label, name) => `<tr><td style="color:var(--text-secondary)">${label}</td><td>${blockTile(name)} ${name ? html().escapeHtml(shortBlockName(name)) : t("ungelesen")}</td></tr>`;
            const footprintDetail = Number.isFinite(Number(footprint.column_count))
                ? `<p class="mount-tech-note">${t("{columns} Spalten geprüft · {overhangs} Randüberhänge toleriert · Halbbreite {half} Blöcke.", { columns: Number(footprint.column_count), overhangs: Number(footprint.edge_overhang_count || 0), half: html().escapeHtml(String(footprint.half_width ?? "?")) })}</p>`
                : "";
            inner = `
                <div class="mount-tech-head">
                    <strong>${t("Technische Details")} — ${html().escapeHtml(names.label)}</strong>
                    <button type="button" class="mount-tech-close" id="btnMountTechClose" aria-label="${t("Schließen")}">✕</button>
                </div>
                <p class="mount-tech-note"><span class="status-pill ${safety.pillClass}">${html().escapeHtml(safety.label)}</span> ${html().escapeHtml(names.rawId)} · ${html().escapeHtml(positionText(candidate))}</p>
                <div class="mount-tech-section"><div class="mount-tech-label">${t("Distanzsuche")}</div>${scanLadderHtml(candidate)}</div>
                <div class="mount-tech-section"><div class="mount-tech-label">Footprint</div><p class="mount-tech-note">${html().escapeHtml(footprint.message || t("Footprint noch nicht geprüft."))}</p>${footprintDetail}</div>
                <div class="mount-tech-section"><div class="mount-tech-label">${t("Blockprobe")}</div><table class="mount-tech-blocks">${blockRow(t("Boden (floor)"), blocks.floor)}${blockRow(t("Fußraum (feet)"), blocks.feet)}${blockRow(t("Kopfraum (head)"), blocks.head)}${blocks.body.map(block => blockRow(t("Körperraum Ebene {level}", { level: block.level }), block.name)).join("")}</table>${probe ? `<p class="mount-tech-note">${html().escapeHtml(probe)}</p>` : ""}</div>
            `;
        } else {
            inner = `
                <div class="mount-tech-head">
                    <strong>${t("Technische Details")}</strong>
                    <button type="button" class="mount-tech-close" id="btnMountTechClose" aria-label="${t("Schließen")}">✕</button>
                </div>
                <p class="mount-tech-note">${t("Keine auswertbare Auswahl vorhanden.")}</p>
            `;
        }
        return `<div class="mount-tech-overlay" id="mountTechOverlay"><div class="mount-tech-modal" role="dialog" aria-modal="true" aria-label="${t("Technische Details zur Platzierung")}">${inner}</div></div>`;
    }

    function placementSafetySummary(preview = {}) {
        const search = preview.placement_search || {};
        const safe = Number(search.placement_safe_count || 0);
        const unsafe = Number(search.placement_unsafe_count || 0);
        const unchecked = Number(search.placement_unchecked_count || 0);
        const shape = search.full_area_scan === false ? t("Richtungslinien") : t("Blockprüfung");
        if (safe || unsafe || unchecked) return `${shape}: ${t("{safe} sicher · {unsafe} nicht sicher · {unchecked} ungeprüft", { safe, unsafe, unchecked })}`;
        if (search.block_check === "chunk_probe") return `${shape}: ${t("Chunk-/Blockprobe aktiv, noch ohne vollständige Bewertung")}`;
        return `${shape}: ${t("noch nicht aktiv")}`;
    }

    function mountOptionHtml(option = {}, selectedMountType = "minecraft:horse") {
        const id = option.id || "";
        const label = t(option.label || id || "Mount");
        const suffix = option.create_available ? " · Create" : "";
        return `<option value="${html().escapeAttr(id)}" ${id === selectedMountType ? "selected" : ""}>${html().escapeHtml(label + suffix)}</option>`;
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
            <small class="field-note mount-profile-mode-note">${t("Es werden keine sichtbaren Beispielwerte übernommen; beim Erzeugen wird ein neues Zufallsprofil innerhalb dieser Bereiche geschrieben.")}</small>
        `;
    }

    function customHorseProfileFieldsHtml(profile) {
        return `
            <div class="row mount-horse-profile-grid custom">
                <div class="field-group col"><label for="mountHorseHealthInput">${t("Leben")}</label><input id="mountHorseHealthInput" class="input-field mount-horse-profile-field" type="number" min="15" max="30" step="1" value="${html().escapeAttr(String(profile.health))}" /><small class="field-note">${t("Vanilla-Bereich: 15 bis 30.")}</small></div>
                <div class="field-group col"><label for="mountHorseMovementInput">${t("Bewegung")}</label><input id="mountHorseMovementInput" class="input-field mount-horse-profile-field" type="number" min="0.1125" max="0.3375" step="0.0001" value="${html().escapeAttr(String(profile.movement))}" /><small class="field-note">${t("Attribut minecraft:movement.")} <b id="mountHorseMovementHint" class="mount-conversion-hint">${html().escapeHtml(movementHintText(profile.movement))}</b></small></div>
                <div class="field-group col"><label for="mountHorseJumpInput">${t("Sprungstärke")}</label><input id="mountHorseJumpInput" class="input-field mount-horse-profile-field" type="number" min="0.4" max="1" step="0.01" value="${html().escapeAttr(String(profile.jump_strength))}" /><small class="field-note">${t("Attribut horse.jump_strength.")} <b id="mountHorseJumpHint" class="mount-conversion-hint">${html().escapeHtml(jumpHintText(profile.jump_strength))}</b></small></div>
                <div class="field-group col"><label for="mountHorseColorSelect">${t("Farbe")}</label><select id="mountHorseColorSelect" class="select-field mount-horse-profile-field">${optionRows(HORSE_COLOR_OPTIONS, profile.color)}</select><small class="field-note">${t("Bedrock Color 0 bis 6.")}</small></div>
                <div class="field-group col"><label for="mountHorseMarkSelect">${t("Markierung")}</label><select id="mountHorseMarkSelect" class="select-field mount-horse-profile-field">${optionRows(HORSE_MARK_OPTIONS, profile.mark_variant)}</select><small class="field-note">${t("Bedrock MarkVariant 0 bis 4.")}</small></div>
                <div class="field-group col"><label for="mountHorseTemperInput">${t("Zähmfortschritt")}</label><input id="mountHorseTemperInput" class="input-field mount-horse-profile-field" type="number" min="0" max="99" step="1" value="${html().escapeAttr(String(profile.temper))}" /><small class="field-note">${t("Bedrock Temper 0 bis 99.")} <b id="mountHorseTemperHint" class="mount-conversion-hint">${html().escapeHtml(temperHintText(profile.temper))}</b></small></div>
            </div>
            <small class="field-note">${t("Diese Werte werden beim Erzeugen exakt ins Horse-NBT geschrieben.")}</small>
        `;
    }

    function horseProfileHtml(horseProfile = DEFAULT_HORSE_PROFILE) {
        const profile = normalizedHorseProfile(horseProfile);
        const isCustom = profile.mode === "custom";
        return `
            <div class="mount-horse-profile-card">
                <div class="mount-horse-profile-header">
                    <div><strong>${t("Pferd-Eigenschaften")}</strong><small>${isCustom ? t("Manuelle Werte werden exakt geschrieben.") : t("Neue Werte werden beim Erzeugen zufällig innerhalb der Bereiche gewählt.")}</small></div>
                    <select id="mountHorseProfileMode" class="select-field"><option value="random_like_game" ${profile.mode === "random_like_game" ? "selected" : ""}>${t("Zufällig wie im Spiel")}</option><option value="custom" ${profile.mode === "custom" ? "selected" : ""}>${t("Manuell")}</option></select>
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
        const hintId = field.key === "jump_strength" ? "mountStatJumpHint" : field.key === "temper" ? "mountStatTemperHint" : "";
        const hint = hintId ? ` <b id="${hintId}" class="mount-conversion-hint">${html().escapeHtml(statValue !== null ? hintText : "")}</b>` : "";
        return `<div class="field-group col"><label for="${field.id}">${field.label}</label><input id="${field.id}" class="input-field mount-stat-field" data-stat-key="${field.key}" type="number" min="${field.min}" max="${field.max}" step="${field.step}" placeholder="${t("zufällig")}" value="${statValue !== null ? html().escapeAttr(String(statValue)) : ""}" /><small class="field-note">${field.note} ${t("Leer = zufällig wie im Spiel.")}${hint}</small></div>`;
    }

    function mountStatsHtml(selectedMountType, mountLabel = "Mount", mountStats = {}, mountTamed = false) {
        if (selectedMountType === "minecraft:camel") {
            return `
            <div class="mount-horse-profile-card">
                <div class="mount-horse-profile-header"><div><strong>${t("Kamel-Eigenschaften")}</strong><small>${t("Im Spiel fix: 32 Leben · Tempo 0,09 (≈ 3,8 Blöcke/s) · kein Sprungattribut. Nichts einzustellen.")}</small></div></div>
            </div>
        `;
        }
        const fields = MOUNT_STATS_FIELDS[selectedMountType];
        if (!fields || !fields.length) return "";
        // Gezähmt-Variante ist nur für Esel/Maultier belegt (wild-vs-gezähmt-Dumps);
        // Skelettpferd und Kamel spawnen ohnehin zahm.
        const tameable = selectedMountType === "minecraft:donkey" || selectedMountType === "minecraft:mule";
        const tamed = tameable && mountTamed === true;
        // Zustand übersteht Re-Renders (Kandidaten-Klick etc.): Werte und Haken
        // kommen aus dem Controller-State, analog zum Pferd-Profil.
        const statFields = fields.filter(field => !(field.wildOnly && tamed)).map(field => statFieldHtml(field, mountStats)).join("");
        const tamedField = tameable
            ? `<div class="field-group col"><label for="mountStatTamedCheckbox">${t("Zähmung")}</label><label class="mount-tamed-toggle"><input id="mountStatTamedCheckbox" type="checkbox" ${tamed ? "checked " : ""}/> ${t("Gezähmt erzeugen")}</label><small class="field-note">${t("Gehört dann dir (OwnerNew), sofort reitbar, mit Inventar – wie im Spiel gezähmt.")}${tamed ? ` ${t("Ein gezähmtes Tier hat keinen Zähmfortschritt mehr.")}` : ""}</small></div>`
            : "";
        const tamedNote = selectedMountType === "minecraft:skeleton_horse" ? ` ${t("Spawnt immer zahm.")}` : "";
        return `
            <div class="mount-horse-profile-card">
                <div class="mount-horse-profile-header"><div><strong>${t("{label}-Eigenschaften", { label: html().escapeHtml(mountLabel) })}</strong><small>${t("Nur Werte, die das Spiel selbst variiert; leer = zufällig wie im Spiel.")}${tamedNote}</small></div></div>
                <div class="row mount-horse-profile-grid custom">
                    ${statFields}
                    ${tamedField}
                </div>
            </div>
        `;
    }

    function previewHtml(preview = null, horseProfile = DEFAULT_HORSE_PROFILE) {
        if (!preview) return `<div class="no-backups">${t("Lade eine Vorschau, um Kandidaten nahe beim Spieler zu sehen.")}</div>`;
        const selected = selectedCandidate(preview);
        const profile = normalizedHorseProfile(horseProfile);
        const playerLabel = preview.player_reference?.player_label || t("Spieler");
        const mountLabel = t(preview.mount_label || preview.mount_type || "Mount");
        const dimensionLabel = Number.isInteger(preview.dimension_id) ? String(preview.dimension_id) : t("noch nicht gelesen");
        const radius = preview.placement_search?.radius || "?";
        const directionHint = preview.placement_search?.prefers_view_direction ? ` · ${t("Blickrichtung bevorzugt")}` : "";
        const badgeText = preview.can_create
            ? t("{label} · Erzeugung experimentell", { label: mountLabel })
            : t("{label} · Nur Vorschau", { label: mountLabel });
        return `
            <div class="mount-preview-summary"><div><span class="summary-kicker">${t("Referenzspieler")}</span><strong>${html().escapeHtml(playerLabel)}</strong><small>${html().escapeHtml(positionText(preview.player_position || {}))} · Dimension: ${html().escapeHtml(dimensionLabel)}</small><small>${t("Richtungsscan bis {radius} Blöcke", { radius: html().escapeHtml(radius) })}${html().escapeHtml(directionHint)} · ${html().escapeHtml(placementSafetySummary(preview))}</small></div><span class="mount-summary-icon">${mountIconSvg(preview.mount_type, profile.color, 44)}<span class="status-pill warning">${html().escapeHtml(badgeText)}</span></span></div>
            ${warningListHtml(preview.warnings, { expanded: preview.can_create !== true })}
            ${placementTargetHtml(selected)}
            ${placementSketchHtml(preview)}
            ${footprintGridHtml(selected)}
            ${technicalOverlayHtml(selected)}
        `;
    }

    function optionsHtml(selectedMountType = "minecraft:horse", mountOptions = MOUNT_TYPE_OPTIONS, canCreate = false, selectedPlacementRadius = 6, horseProfile = DEFAULT_HORSE_PROFILE, mountStats = {}, mountTamed = false) {
        const options = Array.isArray(mountOptions) && mountOptions.length ? mountOptions : MOUNT_TYPE_OPTIONS;
        return `
            <div class="mount-options-card">
                <div class="row mount-options-row">
                    <div class="field-group col"><label for="mountTypeSelect">${t("Mount-Typ")}</label><div class="mount-type-row">${mountIconSvg(selectedMountType, normalizedHorseProfile(horseProfile).color, 34)}<select id="mountTypeSelect" class="select-field">${options.map(option => mountOptionHtml(option, selectedMountType)).join("")}</select></div><small class="field-note">${t("Alle Mount-Typen sind experimentell. Teste die Erzeugung zuerst an einer Weltkopie.")}</small></div>
                    <div class="field-group col"><label for="mountPlacementRadiusInput">${t("Richtungsscan bis Abstand")}</label><input id="mountPlacementRadiusInput" class="input-field" type="number" min="2" max="16" step="1" value="${html().escapeAttr(String(selectedPlacementRadius || 6))}" /><small class="field-note">${t("Scant vier Richtungslinien ab Distanz 2; kein vollständiger Flächenscan.")}</small></div>
                </div>
                ${selectedMountType === "minecraft:horse" ? horseProfileHtml(horseProfile) : mountStatsHtml(selectedMountType, t(options.find(option => option.id === selectedMountType)?.label || "Mount"), mountStats, mountTamed)}
                <button id="btnMountPreview" class="btn btn-primary" type="button">${t("Vorschau laden")}</button>
                <button id="btnMountCreate" class="btn btn-save" type="button" ${canCreate ? "" : "disabled"} title="${canCreate ? t("Merkt das gewählte Mount als ungespeicherte Änderung vor.") : t("Vormerken ist nur nach einer Vorschau mit auswählbarem Kandidaten verfügbar.")}">${t("Mount vormerken")}</button>
            </div>
        `;
    }

    function pendingMountsHtml(pendingMounts = []) {
        const mounts = Array.isArray(pendingMounts) ? pendingMounts : [];
        if (!mounts.length) return "";
        const cards = mounts.map(mount => {
            const position = mount.selectedPosition || {};
            const safety = mount.safetyStatus === "safe" ? t("Sicher geprüft") : t("Ungeprüfte Position");
            const safetyClass = mount.safetyStatus === "safe" ? "ok" : "warning";
            const details = [];
            if (mount.horseProfile?.mode === "custom") {
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
                        <small>${html().escapeHtml(positionText(position))} · ${html().escapeHtml(safety)}</small>
                        <small>${html().escapeHtml(details.join(" · "))}</small>
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

    function emptyStateHtml() {
        return `<div class="no-backups">${t("Mounts sind experimentell. Lade zuerst eine Welt und einen Spieler, dann kannst du eine Vorschau berechnen.")}</div>`;
    }

    function applyMountPanelState({ previewPanel = null, optionsPanel = null, pendingPanel = null, statusPanel = null, preview = null, pendingMounts = [], message = "", status = "info", selectedMountType = "minecraft:horse", selectedPlacementRadius = 6, horseProfile = DEFAULT_HORSE_PROFILE, mountStats = {}, mountTamed = false } = {}) {
        if (previewPanel) previewPanel.innerHTML = preview ? previewHtml(preview, horseProfile) : emptyStateHtml();
        if (optionsPanel) optionsPanel.innerHTML = optionsHtml(selectedMountType, preview?.mount_options, Boolean(preview?.can_create), selectedPlacementRadius, horseProfile, mountStats, mountTamed);
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
        optionsHtml,
        pendingMountsHtml,
        positionText,
        previewHtml,
        temperHintText,
        warningListHtml,
    };
}());
