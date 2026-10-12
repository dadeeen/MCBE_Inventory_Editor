(function () {
    "use strict";

    // Geometry proportions were checked against Mojang's Bedrock Samples
    // (46ba6ea985fb5a92d79a9419198f10dda14c199d, 1.26.50.4):
    // resource_pack/models/entity/{horse_v3,camel}.geo.json and the
    // corresponding client entities. This renderer and its pixel materials
    // are original work; no Mojang texture or model files are redistributed.
    const t = window.t || ((text, params) => String(text).replace(/\{(\w+)\}/g, (match, key) => (params && key in params ? String(params[key]) : match)));
    const escapeHtml = value => window.MCBEHtmlUtils?.escapeHtml(value) ?? String(value).replace(/[&<>"'`]/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;", "`": "&#96;" }[char]));
    const escapeAttr = value => window.MCBEHtmlUtils?.escapeAttr(value) ?? escapeHtml(value);
    const DEFAULT_YAW = 0.58;
    const TILT = 0.22;
    const TURN_STEP = Math.PI / 8;
    const instances = new WeakMap();
    const materialCache = new Map();
    const modelCache = new Map();
    const TYPE_LABELS = {
        "minecraft:horse": "Pferd",
        "minecraft:donkey": "Esel",
        "minecraft:mule": "Maultier",
        "minecraft:camel": "Kamel",
        "minecraft:skeleton_horse": "Skelettpferd",
    };
    const COLORS = ["Weiß", "Creme", "Kastanie", "Braun", "Schwarz", "Grau", "Dunkelbraun"];
    const MARKS = ["Keine", "Weiße Details", "Weiße Felder", "Weiße Punkte", "Schwarze Punkte"];
    // Ordered, small palettes keep adjacent texels coherent. There is no noise
    // or random texture generation, so coat markings stay attached when turned.
    const COATS = [
        { coat: ["#c3c0b6", "#d3d0c5", "#e4e1d5", "#ece9df"], mane: ["#97958a", "#b4b1a2", "#ccc8b6"] },
        { coat: ["#aa8958", "#c29e69", "#d4b27b", "#e0c18d"], mane: ["#ab8a5a", "#ceb37c", "#e3cda2"] },
        { coat: ["#774027", "#8d4e2b", "#a65e32", "#bb7441"], mane: ["#482d20", "#64422b", "#835738"] },
        { coat: ["#573922", "#6c482c", "#805937", "#926b46"], mane: ["#24211d", "#342d23", "#494031"] },
        { coat: ["#242423", "#30312e", "#3e403b", "#4b4e48"], mane: ["#171a17", "#232720", "#34382e"] },
        { coat: ["#646661", "#7d8078", "#999b91", "#adafa4"], mane: ["#32372f", "#464c40", "#646b5d"] },
        { coat: ["#33271f", "#453326", "#59412e", "#6b5039"], mane: ["#191c18", "#282c24", "#3b4034"] },
    ];
    const DONKEY = { coat: ["#635b4d", "#7a6f5e", "#928571", "#a89981"], mane: ["#36352d", "#4d493c", "#635e4d"] };
    const MULE = { coat: ["#4c3524", "#664730", "#7a563b", "#8d6849"], mane: ["#24271f", "#33392c", "#505240"] };
    const CAMEL = { coat: ["#97703a", "#b48645", "#cca35f", "#ddba7a"], mane: ["#876234", "#a57b41", "#c7a263"] };
    const BONE = ["#7d857b", "#a7ada0", "#cbd0c0", "#e3e5d6"];
    const WHITE = ["#c4c0b0", "#d8d4c2", "#ece8d7", "#f4efdf"];
    const HOOF = ["#302b24", "#443b2e", "#5b4e3d"];

    function finiteInteger(value, fallback, maximum) {
        const number = Number(value);
        return Number.isFinite(number) ? Math.max(0, Math.min(maximum, Math.trunc(number))) : fallback;
    }

    function normalize(options = {}) {
        const horseProfile = options.horseProfile || {};
        const mountType = Object.prototype.hasOwnProperty.call(TYPE_LABELS, options.mountType) ? options.mountType : "minecraft:horse";
        const random = mountType === "minecraft:horse" && horseProfile.mode !== "custom";
        return {
            mountType,
            horseProfile,
            mountTamed: options.mountTamed === true,
            random,
            // Keep the random example stable while configuring. It is not a
            // prediction of the random profile that will be generated on save.
            color: random ? 2 : finiteInteger(horseProfile.color, 0, 6),
            mark: random ? 1 : finiteInteger(horseProfile.mark_variant, 0, 4),
        };
    }

    function normalizeYaw(value) {
        const number = Number(value);
        if (!Number.isFinite(number)) return DEFAULT_YAW;
        return ((number + Math.PI) % (Math.PI * 2) + Math.PI * 2) % (Math.PI * 2) - Math.PI;
    }

    function appearance(state) {
        if (state.mountType !== "minecraft:horse") return t(TYPE_LABELS[state.mountType]);
        if (state.random) return t("Beispiel · zufälliges Aussehen");
        return state.mark ? `${t(COLORS[state.color])} · ${t(MARKS[state.mark])}` : t(COLORS[state.color]);
    }

    function box(parts, name, origin, size, material = "coat", rotations = []) {
        parts.push({ name, center: origin.map((value, axis) => value + size[axis] / 2), size, material, rotations });
    }

    function equineModel(type) {
        const parts = [];
        const longEars = type === "minecraft:donkey" || type === "minecraft:mule";
        const skeleton = type === "minecraft:skeleton_horse";
        const neckTurn = [{ axis: 2, pivot: [-8, 17, 0], angle: Math.PI / 6 }];
        // Model coordinates are pixels: X is the animal's length, Y is up.
        // Shared equine body, legs and neck match the modern Bedrock silhouette.
        box(parts, "body", [-11, 11, -5], [22, 10, 10]);
        for (const x of [-11, 7]) for (const z of [-5, 1]) {
            box(parts, `leg-${x < 0 ? "front" : "back"}-${z < 0 ? "right" : "left"}`, [x, 0, z], [4, 11, 4], "leg");
        }
        box(parts, "neck", [-11, 16, -2], [7, 12, 4], "coat", neckTurn);
        box(parts, "head", [-11, 28, -3], [7, 5, 6], "head", neckTurn);
        box(parts, "muzzle", [-16, 28, -2], [5, 5, 4], "muzzle", neckTurn);
        box(parts, "mane", [-3.95, 17, -1], [2, 16, 2], "mane", neckTurn);
        for (const side of [-1, 1]) {
            const height = longEars ? 7 : 3;
            const z = side < 0 ? -3 : 1;
            const spread = { axis: 0, pivot: [-5, 32, side * 2], angle: side * (longEars ? .25 : .09) };
            box(parts, `ear-${side < 0 ? "right" : "left"}`, [-5.01, 32, z], [1, height, 2], "ear", [spread, ...neckTurn]);
        }
        box(parts, "tail", [9, 6, -1.5], [4, 14, 3], "tail", [{ axis: 2, pivot: [11, 20, 0], angle: 25 * Math.PI / 180 }]);
        return { parts, scale: type === "minecraft:donkey" ? .87 : type === "minecraft:mule" ? .92 : 1, skeleton };
    }

    function camelModel() {
        const parts = [];
        box(parts, "body", [-14, 20, -7.5], [27, 12, 15]);
        box(parts, "hump", [-6, 32, -4.5], [11, 5, 9]);
        // The game's camel has an angular, forward-reaching lower neck and
        // tall upright upper neck, plus one rectangular hump.
        box(parts, "neck-lower", [-25, 22, -3.5], [19, 8, 7]);
        box(parts, "neck", [-25, 30, -3.5], [7, 14, 7]);
        box(parts, "muzzle", [-31, 39, -2.5], [6, 5, 5], "camel-muzzle");
        for (const z of [-6, 3]) box(parts, `ear-${z < 0 ? "right" : "left"}`, [-20.5, 42.5, z], [2, 1, 3], "camel-ear");
        for (const x of [-13, 7]) for (const z of [-7.4, 2.4]) {
            box(parts, `leg-${x < 0 ? "front" : "back"}-${z < 0 ? "right" : "left"}`, [x, 0, z], [5, 21, 5], "camel-leg");
        }
        // A two-sided pixel sheet, as in the vanilla geometry's zero-depth tail.
        box(parts, "tail", [13, 15, -1.5], [.12, 14, 3], "camel-tail");
        return { parts, scale: 1, skeleton: false };
    }

    function modelFor(type) {
        if (!modelCache.has(type)) modelCache.set(type, type === "minecraft:camel" ? camelModel() : equineModel(type));
        return modelCache.get(type);
    }

    function rotatePoint(point, rotation, direction = false) {
        const result = [...point];
        const axes = rotation.axis === 0 ? [1, 2] : rotation.axis === 1 ? [2, 0] : [0, 1];
        const [a, b] = axes;
        const pivot = direction ? [0, 0, 0] : rotation.pivot;
        const cosine = Math.cos(rotation.angle);
        const sine = Math.sin(rotation.angle);
        const x = point[a] - pivot[a];
        const y = point[b] - pivot[b];
        result[a] = x * cosine - y * sine + pivot[a];
        result[b] = x * sine + y * cosine + pivot[b];
        return result;
    }

    function transform(point, part, direction = false) {
        let result = point.map((value, axis) => value + (direction ? 0 : part.center[axis]));
        for (const rotation of part.rotations) result = rotatePoint(result, rotation, direction);
        return result;
    }

    function faceDefinitions(part) {
        const [width, height, length] = part.size;
        return [
            ["near", [-width / 2, -height / 2, length / 2], [width, 0, 0], [0, height, 0], [0, 0, 1], width, height],
            ["far", [width / 2, -height / 2, -length / 2], [-width, 0, 0], [0, height, 0], [0, 0, -1], width, height],
            ["front", [-width / 2, -height / 2, -length / 2], [0, 0, length], [0, height, 0], [-1, 0, 0], length, height],
            ["back", [width / 2, -height / 2, length / 2], [0, 0, -length], [0, height, 0], [1, 0, 0], length, height],
            ["top", [-width / 2, height / 2, -length / 2], [width, 0, 0], [0, 0, length], [0, 1, 0], width, length],
            ["bottom", [-width / 2, -height / 2, length / 2], [width, 0, 0], [0, 0, -length], [0, -1, 0], width, length],
        ];
    }

    function pixelIn(x, y, left, bottom, width, height) {
        return x >= left && x < left + width && y >= bottom && y < bottom + height;
    }

    // Sparse, deliberately placed clusters give the flank a pixel-art coat.
    // Their shapes are shared across palettes, not random speckles per frame.
    const FLANK_PATCHES = [
        [1, 5, 4, 2, 3], [2, 7, 5, 1, 3], [6, 6, 3, 1, 3],
        [5, 3, 5, 1, 1], [8, 2, 5, 1, 1], [9, 5, 5, 1, 1],
        [12, 6, 3, 1, 1], [16, 5, 4, 2, 3], [18, 7, 3, 1, 3],
        [17, 3, 4, 1, 1], [2, 2, 2, 1, 1],
    ];
    const WHITE_FIELDS = [
        [3, 1, 4, 6], [4, 7, 3, 2], [7, 3, 2, 4], [9, 4, 1, 2],
        [14, 0, 5, 4], [16, 4, 5, 2], [18, 6, 3, 2], [20, 2, 2, 3],
    ];
    const SPOTS = [[2, 5], [4, 2], [6, 7], [8, 4], [10, 2], [11, 6], [14, 4], [16, 7], [18, 2], [20, 5]];

    function coatTone(part, face, x, y, width, height) {
        if (face === "bottom") return 0;
        if (part.name === "body" && (face === "near" || face === "far")) {
            const px = Math.floor(x * 22 / width);
            const py = Math.floor(y * 10 / height);
            if (py < (px > 5 && px < 16 ? 2 : 1)) return 0;
            for (const [left, bottom, w, h, tone] of FLANK_PATCHES) if (pixelIn(px, py, left, bottom, w, h)) return tone;
            return py === 9 ? 3 : 2;
        }
        if (part.name === "body" && face === "top") {
            return y <= 1 || y >= height - 2 ? 1 : x > width * .3 && x < width * .7 ? 3 : 2;
        }
        if (part.name === "neck" || part.name === "neck-lower") {
            if ((x === width - 2 && y > 1 && y < height - 3) || (x === 1 && y > height * .55)) return 1;
            if (y === 2 && x > 1 && x < width - 1) return 3;
        }
        if (part.name === "hump") return y < 2 ? 1 : x > 1 && x < width - 2 && y >= height - 1 ? 3 : 2;
        return x === width - 1 && face !== "top" ? 1 : 2;
    }

    function horseMark(state, part, face, x, y, width, height) {
        if (state.mountType !== "minecraft:horse" || !state.mark) return false;
        if (part.material === "leg" && state.mark <= 2 && face !== "top") return y >= 2 && y < (part.name.includes("left") ? 5 : 4);
        if ((part.name === "head" || part.name === "muzzle") && state.mark <= 2) {
            if (face === "top") return y >= Math.floor(height / 2) - 1 && y <= Math.floor(height / 2) && x < width - 1;
            if (face === "front") return x >= Math.floor(width / 2) - 1 && x <= Math.floor(width / 2);
        }
        if (part.name !== "body" || !(face === "near" || face === "far")) return false;
        const px = Math.floor(x * 22 / width);
        const py = Math.floor(y * 10 / height);
        if (state.mark === 2) return WHITE_FIELDS.some(([left, bottom, w, h]) => pixelIn(px, py, left, bottom, w, h));
        if (state.mark >= 3) return SPOTS.some(([left, bottom], index) => pixelIn(px, py, left, bottom, index % 3 === 0 ? 2 : 1, index % 2 === 0 ? 2 : 1));
        return false;
    }

    function skeletonPixel(part, face, x, y, width, height) {
        const side = face === "near" || face === "far";
        const horizontal = face === "top" || face === "bottom";
        if (part.name === "body") {
            if (side) {
                const endBone = (x < 3 || x >= width - 3) && (y >= 2 || x % 2 === 0);
                const rib = x >= 5 && x <= width - 5 && (x % 3 === 0 || y === height - 2) && y >= 1 && y <= height - 2;
                if (!endBone && !rib) return null;
                return BONE[y <= 2 || x % 3 === 1 ? 1 : 2];
            }
            if (horizontal) {
                const spine = y >= Math.floor(height / 2) - 1 && y <= Math.floor(height / 2);
                const ribs = x >= 5 && x <= width - 5 && x % 3 === 0;
                if (!spine && !ribs && x >= 3 && x < width - 3) return null;
                return BONE[face === "top" ? 2 : 1];
            }
            if (x >= 3 && x < width - 3 && y < height - 3) return null;
            return BONE[x === 0 || y === 0 ? 1 : 2];
        }
        if (part.material === "leg") {
            if (!horizontal && (x === 0 || x === width - 1) && y > 1 && y !== 5 && y !== 9) return null;
            return BONE[y < 2 || x === 0 ? 1 : 2];
        }
        if (part.material === "mane") {
            if (!side || x === 0 || y < 2 || y >= height - 2 || y % 3 === 0) return null;
            return BONE[1];
        }
        if (part.material === "tail") {
            if (side || (!horizontal && (x !== Math.floor(width / 2) || y % 3 === 0))) return null;
            return BONE[1];
        }
        if (part.name === "neck") {
            if (side && x > 1 && x < width - 2 && y > 1 && y < height - 2 && y % 3 !== 0) return null;
            return BONE[(x + y) % 5 === 0 ? 1 : 2];
        }
        if (part.material === "ear") return BONE[x === 0 ? 1 : 2];
        if (part.material === "head" && side && pixelIn(x, y, 1, 2, 2, 2)) return "#30372f";
        if (part.material === "muzzle") {
            if (face === "front" && y >= 2 && y < 4 && (x === 0 || x === width - 1)) return "#424a3e";
            if (y === 0 && !horizontal && x % 2 === 0) return null;
            return BONE[y === 0 || y === 1 && x % 2 === 0 ? 0 : 2];
        }
        return BONE[y === 0 || x === width - 1 ? 1 : 2];
    }

    function pixelColor(state, part, face, x, y, width, height) {
        // Both side faces use the animal's front-to-back coordinate so facial
        // details and coat patches do not jump to the back of the head.
        if (face === "far") x = width - 1 - x;
        if (state.mountType === "minecraft:skeleton_horse") return skeletonPixel(part, face, x, y, width, height);
        const donkey = state.mountType === "minecraft:donkey";
        const mule = state.mountType === "minecraft:mule";
        const camel = state.mountType === "minecraft:camel";
        const palette = camel ? CAMEL : donkey ? DONKEY : mule ? MULE : COATS[state.color];
        const side = face === "near" || face === "far";
        const horizontal = face === "top" || face === "bottom";
        let tone = coatTone(part, face, x, y, width, height);
        let color = palette.coat[tone];
        if (horseMark(state, part, face, x, y, width, height)) color = state.mark === 4 ? COATS[4].coat[Math.min(3, tone)] : WHITE[tone];
        if (part.material === "mane" || part.material === "tail") {
            const strand = (x + (face === "top" ? y : 0)) % 3;
            color = palette.mane[strand];
            if (donkey && part.material === "tail" && !horizontal && y > 4) color = palette.coat[1];
        }
        if (part.material === "leg" && !horizontal && y < 2) color = HOOF[x % 2 ? 1 : 2];
        if (part.material === "leg" && face === "bottom") color = HOOF[0];
        if (part.material === "leg" && !horizontal && y === 6 && x > 0 && x < width - 1) color = palette.coat[1];
        if (part.material === "head" && side) {
            if (x === 2 && y === 3) color = "#f0e6d1";
            if (x === 1 && y === 3) color = "#201e18";
            if (x === 1 && y === 4) color = palette.coat[0];
        }
        if (part.material === "muzzle") {
            if (donkey || mule) color = ["#978b73", "#b5a68b", "#cbbfa5", "#d8ceb7"][tone];
            else if (!horseMark(state, part, face, x, y, width, height)) color = palette.coat[Math.max(0, tone - 1)];
            if (side && x === 0 && y === 3 || face === "front" && y === 3 && (x === 0 || x === width - 1)) color = "#393125";
            if (y === 0 && !horizontal) color = donkey || mule ? "#80715d" : palette.coat[0];
        }
        if (part.material === "ear" && face === "front" && y > 0 && y < height - 1) color = palette.mane[1];
        if (donkey && part.name === "body" && face === "top" && y === Math.floor(height / 2)) color = palette.mane[1];
        if (camel) {
            if (part.name === "neck" && side) {
                if (x === 2 && y === height - 3) color = "#352d1f";
                if (x === 2 && y === height - 2) color = palette.coat[0];
                if (x === 3 && y === height - 3) color = palette.coat[3];
            }
            if (part.material === "camel-muzzle") {
                color = palette.coat[Math.max(0, tone - 1)];
                if (side && x < 2 && y === 3 || face === "front" && y === 3 && (x === 0 || x === width - 1)) color = "#5a4127";
                if (!horizontal && y === 0) color = "#a57b45";
            }
            if (part.material === "camel-leg" && !horizontal) {
                if (y < 2) color = palette.coat[0];
                else if (y === 10 || y === 11 && x > 0 && x < width - 1) color = palette.coat[1];
                else if (x > 0 && x < width - 1 && y > 2 && y < 9) color = palette.coat[3];
            }
            if (part.material === "camel-ear") color = palette.coat[face === "bottom" ? 0 : 1];
            if (part.material === "camel-tail") {
                if (face !== "front" && face !== "back") return null;
                if (y > 2 && x !== 1) return null;
                color = palette.coat[y < 3 ? 0 : 1];
            }
        }
        return color;
    }

    function textureFor(state, part, face, width, height) {
        const columns = Math.max(1, Math.round(width));
        const rows = Math.max(1, Math.round(height));
        const variant = state.mountType === "minecraft:horse" ? `${state.color}/${state.mark}` : "fixed";
        const key = `${state.mountType}/${variant}/${part.name}/${face}`;
        if (materialCache.has(key)) return materialCache.get(key);
        // Merge equal neighboring texels into horizontal runs, then one path
        // per palette color. This keeps dragging cheap without raster assets.
        const paths = new Map();
        for (let y = 0; y < rows; y += 1) {
            let start = 0;
            let previous = pixelColor(state, part, face, 0, y, columns, rows);
            for (let x = 1; x <= columns; x += 1) {
                const color = x < columns ? pixelColor(state, part, face, x, y, columns, rows) : undefined;
                if (color === previous) continue;
                if (previous) paths.set(previous, (paths.get(previous) || "") + `M${start},${y}h${x - start}v1h${start - x}z`);
                start = x;
                previous = color;
            }
        }
        const texture = { paths: [...paths.entries()], columns, rows };
        materialCache.set(key, texture);
        return texture;
    }

    function framing(model) {
        // Use the same camera for all equines: the 0.87 / 0.92 client scales
        // remain visible. The camel gets a fit appropriate to its taller shape.
        const reference = model === modelFor("minecraft:camel") ? model : modelFor("minecraft:mule");
        let lowX = Infinity;
        let highX = -Infinity;
        let highY = 0;
        const vertices = [];
        for (const part of reference.parts) for (const x of [-.5, .5]) for (const y of [-.5, .5]) for (const z of [-.5, .5]) {
            const point = transform([x * part.size[0], y * part.size[1], z * part.size[2]], part);
            vertices.push(point);
            lowX = Math.min(lowX, point[0]);
            highX = Math.max(highX, point[0]);
            highY = Math.max(highY, point[1]);
        }
        const centerX = (lowX + highX) / 2;
        const radius = Math.max(...vertices.map(([x, , z]) => Math.hypot(x - centerX, z)));
        const vertical = highY * Math.cos(TILT) + 2 * radius * Math.sin(TILT);
        // Fit the full turn inside the existing stage with a small edge inset.
        const zoom = Math.min(6.6, 336 / (radius * 2), 240 / vertical);
        return { centerX, zoom, groundY: 130 + highY * Math.cos(TILT) * zoom / 2, radius };
    }

    function shadeColor(color, normal, yaw, inside) {
        const cameraX = normal[0] * Math.cos(yaw) + normal[2] * Math.sin(yaw);
        const cameraZ = -normal[0] * Math.sin(yaw) + normal[2] * Math.cos(yaw);
        const light = Math.max(0, cameraX * -.32 + normal[1] * .78 + cameraZ * .46);
        const factor = (inside ? .73 : .82) + light * .24;
        return `#${[1, 3, 5].map(start => Math.min(255, Math.round(parseInt(color.slice(start, start + 2), 16) * factor)).toString(16).padStart(2, "0")).join("")}`;
    }

    function scene(state, yaw) {
        const model = modelFor(state.mountType);
        const frame = framing(model);
        const cosine = Math.cos(yaw);
        const sine = Math.sin(yaw);
        const camera = [-sine * Math.cos(TILT), Math.sin(TILT), cosine * Math.cos(TILT)];
        const project = ([x, y, z]) => {
            x = (x - frame.centerX) * model.scale;
            y *= model.scale;
            z *= model.scale;
            return [180 + (x * cosine + z * sine) * frame.zoom, frame.groundY + ((-x * sine + z * cosine) * Math.sin(TILT) - y * Math.cos(TILT)) * frame.zoom];
        };
        const points = vertices => vertices.map(vertex => project(vertex).map(value => value.toFixed(2)).join(",")).join(" ");
        const depth = point => point.reduce((sum, value, axis) => sum + value * camera[axis], 0);
        const surfaces = [];
        for (const part of model.parts) {
            for (const [name, origin, horizontal, vertical, localNormal, width, height] of faceDefinitions(part)) {
                if (width < .2 || height < .2) continue;
                const normal = transform(localNormal, part, true);
                const inside = depth(normal) <= .001;
                if (inside && !model.skeleton && part.material !== "camel-tail") continue;
                const vertex = (u, v) => transform(origin.map((value, axis) => value + u * horizontal[axis] + v * vertical[axis]), part);
                const vertices = [vertex(0, 0), vertex(1, 0), vertex(1, 1), vertex(0, 1)];
                const texture = textureFor(state, part, name, width, height);
                if (!texture.paths.length) continue;
                const [p0, p1, , p3] = vertices.map(project);
                const matrix = [(p1[0] - p0[0]) / texture.columns, (p1[1] - p0[1]) / texture.columns, (p3[0] - p0[0]) / texture.rows, (p3[1] - p0[1]) / texture.rows, ...p0].map(value => value.toFixed(4)).join(" ");
                const painted = texture.paths.map(([color, path]) => `<path d="${path}" fill="${shadeColor(color, normal, yaw, inside)}"/>`).join("");
                const silhouette = model.skeleton || part.material === "camel-tail" ? "" : `<polygon points="${points(vertices)}" fill="${shadeColor(pixelColor(state, part, name, 0, 0, texture.columns, texture.rows), normal, yaw, false)}"/>`;
                surfaces.push({ depth: vertices.reduce((sum, item) => sum + depth(item), 0) / 4, content: `<g data-model-part="${part.name}" data-model-face="${name}">${silhouette}<g class="mount-model-texels" transform="matrix(${matrix})">${painted}</g></g>` });
            }
        }
        surfaces.sort((left, right) => left.depth - right.depth);
        const groundY = frame.groundY.toFixed(2);
        const radius = Math.min(114, frame.radius * frame.zoom * .84).toFixed(2);
        return `<ellipse class="mount-model-ground" cx="180" cy="${groundY}" rx="${radius}" ry="21"/><ellipse cx="180" cy="${groundY}" rx="76" ry="12" fill="#000000" opacity=".12"/><g data-model-scale="${model.scale}" data-model-material="${model.skeleton ? "bone-cutout" : "pixel-coat"}">${surfaces.map(surface => surface.content).join("")}</g>`;
    }

    function control(action, label, path) {
        return `<button type="button" class="mount-model-control" data-model-action="${action}" aria-label="${escapeAttr(t(label))}" title="${escapeAttr(t(label))}"><svg viewBox="0 0 24 24" width="19" height="19" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="${path}"/></svg></button>`;
    }

    function markup(options = {}) {
        const state = normalize(options);
        const yaw = normalizeYaw(options.view?.yaw ?? DEFAULT_YAW);
        const label = t("{mount}: 3D-Modell im Minecraft-Stil", { mount: t(TYPE_LABELS[state.mountType]) });
        return `<section id="mountModelPreview" class="mount-model-card" aria-labelledby="mountModelHeading">
            <div class="mount-model-heading"><h3 id="mountModelHeading">${escapeHtml(t("3D-Ansicht"))}</h3><span>${escapeHtml(t("Minecraft-Stil"))}</span></div>
            <div id="mountModelStage" class="mount-model-stage" tabindex="0" role="group" aria-label="${escapeAttr(label)}" aria-describedby="mountModelHelp" data-yaw="${yaw.toFixed(3)}" data-mount-type="${state.mountType}" data-color="${state.color}" data-mark="${state.mark}" data-random="${state.random}">
                <svg class="mount-model-svg" viewBox="0 0 360 260" role="img" aria-label="${escapeAttr(label)}">${scene(state, yaw)}</svg>
            </div>
            <div class="mount-model-footer"><p class="mount-model-appearance">${escapeHtml(appearance(state))}</p><div class="mount-model-controls">
                ${control("left", "Ansicht nach links drehen", "M7 7H3V3M3.5 7a9 9 0 1 1-0.3 9")}
                ${control("reset", "Ansicht zurücksetzen", "M8 4H4v4m12-4h4v4M4 16v4h4m8 0h4v-4M8 12l4-4 4 4-4 4-4-4")}
                ${control("right", "Ansicht nach rechts drehen", "M17 7h4V3M20.5 7a9 9 0 1 0 .3 9")}
            </div></div>
            <span id="mountModelHelp" class="visually-hidden">${escapeHtml(t("Zum Drehen ziehen oder die Pfeiltasten verwenden. Mit Pos1 die Ansicht zurücksetzen."))}</span>
        </section>`;
    }

    function attach(root, options = {}) {
        const host = root?.matches?.("#mountModelPreview") ? root : root?.querySelector?.("#mountModelPreview");
        if (!host) return null;
        instances.get(host)?.destroy();
        const stage = host.querySelector(".mount-model-stage");
        const svg = host.querySelector(".mount-model-svg");
        const caption = host.querySelector(".mount-model-appearance");
        if (!stage || !svg || !caption) return null;
        let state = normalize(options);
        let yaw = normalizeYaw(options.view?.yaw ?? stage.getAttribute("data-yaw") ?? DEFAULT_YAW);
        let drag = null;
        let destroyed = false;
        const listeners = [];
        const on = (node, event, handler) => {
            node.addEventListener(event, handler);
            listeners.push([node, event, handler]);
        };

        function draw() {
            if (destroyed) return;
            svg.innerHTML = scene(state, yaw);
            const label = t("{mount}: 3D-Modell im Minecraft-Stil", { mount: t(TYPE_LABELS[state.mountType]) });
            svg.setAttribute("aria-label", label);
            stage.setAttribute("aria-label", label);
            for (const [key, value] of Object.entries({ yaw: yaw.toFixed(3), "mount-type": state.mountType, color: state.color, mark: state.mark, random: state.random })) stage.setAttribute(`data-${key}`, String(value));
            caption.textContent = appearance(state);
        }

        function rotate(next) {
            yaw = normalizeYaw(next);
            draw();
        }

        function releasePointer(event) {
            if (event && drag && event.pointerId !== undefined && event.pointerId !== drag.id) return;
            if (drag && stage.hasPointerCapture?.(drag.id)) stage.releasePointerCapture(drag.id);
            drag = null;
            stage.classList.remove("is-dragging");
        }

        on(stage, "keydown", event => {
            if (event.target !== stage || event.altKey || event.ctrlKey || event.metaKey) return;
            if (!["ArrowLeft", "ArrowRight", "Home"].includes(event.key)) return;
            event.preventDefault();
            rotate(event.key === "Home" ? DEFAULT_YAW : yaw + (event.key === "ArrowLeft" ? -TURN_STEP : TURN_STEP));
        });
        on(stage, "pointerdown", event => {
            if (event.isPrimary === false || (event.button !== undefined && event.button !== 0)) return;
            drag = { id: event.pointerId, x: event.clientX, y: event.clientY, yaw, active: false };
        });
        on(stage, "pointermove", event => {
            if (!drag || drag.id !== event.pointerId) return;
            // Before the drag threshold is reached there is no capture, so a
            // mouseup just outside the stage may never reach this element.
            // Re-entering with no held button must not resume that stale drag.
            if (event.pointerType === "mouse" && !(event.buttons & 1)) {
                releasePointer();
                return;
            }
            const dx = event.clientX - drag.x;
            const dy = event.clientY - drag.y;
            if (!drag.active) {
                // A vertical gesture belongs to the page. Capture only once a
                // horizontal intent is clear; touch-action: pan-y handles scroll.
                if (Math.abs(dy) > 6 && Math.abs(dy) > Math.abs(dx)) {
                    releasePointer();
                    return;
                }
                if (Math.abs(dx) < 6) return;
                drag.active = true;
                stage.setPointerCapture?.(drag.id);
                stage.classList.add("is-dragging");
            }
            if (event.cancelable) event.preventDefault();
            rotate(drag.yaw + dx * 0.012);
        });
        on(stage, "pointerup", releasePointer);
        on(stage, "pointercancel", releasePointer);
        on(stage, "lostpointercapture", releasePointer);
        for (const button of host.querySelectorAll("[data-model-action]")) on(button, "click", () => {
            const action = button.getAttribute("data-model-action");
            rotate(action === "reset" ? DEFAULT_YAW : yaw + (action === "left" ? -TURN_STEP : TURN_STEP));
        });

        const controller = {
            update(next = {}) {
                if (destroyed) return;
                state = normalize({ ...state, ...next });
                if (next.view?.yaw !== undefined) yaw = normalizeYaw(next.view.yaw);
                draw();
            },
            getView() { return { yaw }; },
            destroy() {
                if (destroyed) return;
                releasePointer();
                for (const [node, event, handler] of listeners) node.removeEventListener(event, handler);
                destroyed = true;
                if (instances.get(host) === controller) instances.delete(host);
            },
        };
        instances.set(host, controller);
        draw();
        return controller;
    }

    window.MCBEMountModelPreview = { markup, attach };
}());
