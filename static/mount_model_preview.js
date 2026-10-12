(function () {
    "use strict";

    // Proportions, coat families and marking coverage were checked against
    // Mojang's Bedrock Samples
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
    const geometryCache = new WeakMap();
    const TYPE_LABELS = {
        "minecraft:horse": "Pferd",
        "minecraft:donkey": "Esel",
        "minecraft:mule": "Maultier",
        "minecraft:camel": "Kamel",
        "minecraft:skeleton_horse": "Skelettpferd",
    };
    const COLORS = ["Weiß", "Creme", "Kastanie", "Braun", "Schwarz", "Grau", "Dunkelbraun"];
    const MARKS = ["Keine", "Weiße Details", "Weiße Felder", "Weiße Punkte", "Schwarze Punkte"];
    // Independently painted palettes and patterns, not decoded vanilla texels.
    // The coat families retain their characteristic mane/tail colors.
    const COATS = [
        { coat: ["#959798", "#b4b6b8", "#bfc1c2", "#ced0d1"], mane: ["#a0a3a5", "#babdc0", "#d0d2d4"] },
        { coat: ["#4c2d14", "#734920", "#805326", "#8c5e2d"], mane: ["#100d0b", "#211811", "#36261a"] },
        { coat: ["#3c1b11", "#632a19", "#73301d", "#81401f"], mane: ["#ad8453", "#c79c67", "#dcc092"] },
        { coat: ["#2c150b", "#45220e", "#512812", "#5d3117"], mane: ["#130f0d", "#231813", "#352219"] },
        { coat: ["#0b0d11", "#1a1d23", "#202329", "#272a32"], mane: ["#0b0e12", "#15181d", "#242932"] },
        { coat: ["#303234", "#46494b", "#505355", "#5b5e60"], mane: ["#2f3234", "#44484a", "#585b5d"] },
        { coat: ["#100b08", "#26160f", "#301b13", "#3a2319"], mane: ["#0c0b0b", "#1b1310", "#2c1e15"] },
    ];
    const DONKEY = { coat: ["#504638", "#706152", "#7b6b5a", "#877565"], mane: ["#252323", "#383331", "#504942"] };
    const MULE = { coat: ["#271810", "#3d281c", "#492d1e", "#523524"], mane: ["#171415", "#241d1b", "#3b2b22"] };
    const CAMEL = { coat: ["#ba8236", "#dfa34d", "#e9ae56", "#f2bb66"], mane: ["#a77535", "#ca9144", "#e2ae60"] };
    const BONE = ["#777d82", "#a5a9ad", "#d1d3d5", "#e4e5e6"];
    const WHITE = ["#bbbdc0", "#d0d2d4", "#e4e5e6", "#f1f1ed"];
    const BLACK_MARK = ["#070809", "#101112", "#151618", "#1b1c1e"];
    const HOOF = ["#242426", "#363336", "#4b4140"];

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
            const z = side < 0 ? (longEars ? -3 : -1.5) : (longEars ? 1 : -.5);
            // Short ears fan out from the head instead of standing parallel.
            const spread = { axis: 0, pivot: longEars ? [-5, 32, side * 2] : [-8, 17, 0], angle: side * (longEars ? .25 : .09) };
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

    const dot = (left, right) => left.reduce((sum, value, axis) => sum + value * right[axis], 0);

    function partitionSurfaces(polygons) {
        if (!polygons.length) return null;
        const normal = polygons[0].face.normal;
        const offset = dot(normal, polygons[0].vertices[0]);
        const front = [], back = [], coplanar = [];
        const epsilon = 1e-6;
        for (const polygon of polygons) {
            const distances = polygon.vertices.map(vertex => dot(normal, vertex) - offset);
            const hasFront = distances.some(distance => distance > epsilon);
            const hasBack = distances.some(distance => distance < -epsilon);
            if (!hasFront && !hasBack) coplanar.push(polygon);
            else if (!hasBack) front.push(polygon);
            else if (!hasFront) back.push(polygon);
            else {
                // Split intersecting faces at the actual plane. Sorting whole
                // face centers cannot order the neck where it enters the body.
                const positive = [], negative = [];
                polygon.vertices.forEach((vertex, index) => {
                    const next = (index + 1) % polygon.vertices.length;
                    const distance = distances[index];
                    if (distance >= -epsilon) positive.push(vertex);
                    if (distance <= epsilon) negative.push(vertex);
                    if (distance > epsilon && distances[next] < -epsilon || distance < -epsilon && distances[next] > epsilon) {
                        const fraction = distance / (distance - distances[next]);
                        const crossing = vertex.map((value, axis) => value + fraction * (polygon.vertices[next][axis] - value));
                        positive.push(crossing);
                        negative.push(crossing);
                    }
                });
                front.push({ face: polygon.face, vertices: positive, clipped: true });
                back.push({ face: polygon.face, vertices: negative, clipped: true });
            }
        }
        return { normal, coplanar, front: partitionSurfaces(front), back: partitionSurfaces(back) };
    }

    function geometryFor(model) {
        if (geometryCache.has(model)) return geometryCache.get(model);
        const faces = [];
        for (const part of model.parts) {
            for (const [name, origin, horizontal, vertical, localNormal, width, height] of faceDefinitions(part)) {
                if (width < .2 || height < .2) continue;
                const vertex = (u, v) => transform(origin.map((value, axis) => value + u * horizontal[axis] + v * vertical[axis]), part);
                faces.push({ part, name, width, height, normal: transform(localNormal, part, true),
                    vertices: [vertex(0, 0), vertex(1, 0), vertex(1, 1), vertex(0, 1)] });
            }
        }
        // The geometry is fixed while dragging or choosing coats. Build the
        // partition once; only traversal and projection depend on the camera.
        const geometry = { faces, tree: partitionSurfaces(faces.map(face => ({ face, vertices: face.vertices, clipped: false }))) };
        geometryCache.set(model, geometry);
        return geometry;
    }

    function orderedSurfaces(tree, camera, result = []) {
        if (!tree) return result;
        const frontFacing = dot(tree.normal, camera) >= 0;
        orderedSurfaces(frontFacing ? tree.back : tree.front, camera, result);
        result.push(...tree.coplanar);
        orderedSurfaces(frontFacing ? tree.front : tree.back, camera, result);
        return result;
    }

    function pixelIn(x, y, left, bottom, width, height) {
        return x >= left && x < left + width && y >= bottom && y < bottom + height;
    }

    // Small hand-painted clusters avoid long wood-like stripes. The pattern
    // is stable in model coordinates and shared by the independently drawn coats.
    const COAT_GRAIN = [
        "22232212", "23322211", "22321222", "12211232",
        "21222233", "22123222", "32233122", "23222212",
    ];
    // Own patch outlines: a shoulder field and rising flank field, with
    // different edges on either side. These are not sampled texture masks.
    const WHITE_FIELDS = {
        near: [[3, 7, 3, 3], [6, 8, 5, 2], [5, 6, 2, 2], [12, 0, 5, 2], [16, 1, 6, 3], [19, 3, 3, 2]],
        far: [[2, 8, 6, 2], [4, 6, 3, 3], [7, 7, 3, 2], [14, 0, 6, 2], [18, 1, 4, 4]],
    };
    const WHITE_SPOTS = [[0, 7, 2, 3], [3, 4, 2, 3], [5, 8, 3, 2], [7, 1, 2, 2], [8, 5, 2, 2], [11, 7, 2, 3], [12, 3, 2, 2], [15, 5, 2, 3], [17, 8, 3, 2], [18, 1, 2, 2], [20, 4, 2, 3]];

    function inPatches(x, y, patches) {
        return patches.some(([left, bottom, width, height]) => pixelIn(x, y, left, bottom, width, height));
    }

    function fleck(x, y, seed, density) {
        let hash = Math.imul(x + 1, 374761393) ^ Math.imul(y + 1, 668265263) ^ seed;
        hash = Math.imul(hash ^ hash >>> 13, 1274126177);
        return ((hash ^ hash >>> 16) >>> 0) % 100 < density;
    }

    function foreheadMark(mark, part, face, x, y, width, height) {
        const head = part.name === "head", muzzle = part.name === "muzzle";
        if (!head && !muzzle) return false;
        // A tapered forehead blaze ends above the nose. It must not turn
        // into the same white outline around every variant's muzzle.
        const center = Math.floor(height / 2);
        if (face === "top") {
            if (mark === 1) return head
                ? x < 6 && (y === center - 1 || y === center && x < 5 || x === 4 && y === center + 1)
                : x >= width - 2 && y === center - 1;
            if (mark === 2) return head
                ? x < 5 && y >= center - 1 && y <= center + (x < 3 ? 0 : 1)
                : x >= 2 && (y === center - 1 || y === center && x > 2);
            if (mark === 3) return head
                ? pixelIn(x, y, 1, center - 1, 3, 2) || pixelIn(x, y, 4, center, 2, 2)
                : pixelIn(x, y, 0, center - 1, 2, 2) || x === 3 && y === center;
        }
        if (mark === 2 && head && face === "front") return y >= height - 2 && x > 0 && x < width - 2;
        if (mark === 2 && face === "far") return y >= height - 2 && (head ? x === 0 : x >= width - 2);
        return false;
    }

    function grain(x, y) {
        return Number(COAT_GRAIN[y % 8][x % 8]);
    }

    function coatTone(part, face, x, y, width, height) {
        if (face === "bottom") return 0;
        if (part.name === "body" && (face === "near" || face === "far")) {
            const px = Math.floor(x * 22 / width);
            const py = Math.floor(y * 10 / height);
            const tone = grain(px, py);
            if (py < (px > 5 && px < 16 ? 2 : 1)) return Math.max(0, tone - 1);
            return py === 9 ? Math.max(2, tone) : tone;
        }
        if (part.name === "body" && face === "top") {
            return Math.max(2, grain(x, y));
        }
        if (part.name === "neck" || part.name === "neck-lower") {
            return x === width - 1 ? 1 : grain(x + 3, y + 1);
        }
        if (part.name === "hump") return Math.max(y < 2 ? 1 : 2, grain(x + 2, y));
        return grain(x + 1, y + 2);
    }

    function horseMark(state, part, face, x, y, width, height) {
        if (state.mountType !== "minecraft:horse" || !state.mark) return false;
        if (part.material === "leg" && !["top", "bottom"].includes(face)) {
            if (state.mark === 1) return y >= 3 && y < 7 + (x === 0 ? 1 : 0);
            if (state.mark === 3) return y >= height - 4 && fleck(x, y, part.name.includes("back") ? 83 : 41, 28);
            if (state.mark === 4) return y >= 3 && fleck(x, y, part.name.includes("right") ? 113 : 67, 24);
        }
        if (foreheadMark(state.mark, part, face, x, y, width, height)) return true;
        const side = face === "near" || face === "far";
        if (state.mark === 3 && part.name === "neck") {
            if (side) return inPatches(x, y, face === "near" ? [[2, 1, 2, 2], [4, 3, 2, 3]] : [[0, 2, 2, 3], [2, 6, 3, 2], [4, 9, 2, 3], [5, 2, 2, 2]]);
            if (face === "back") return y > 2 && fleck(x, y, 31, 32);
        }
        if (part.name !== "body") return false;
        if (face === "top") {
            if (state.mark === 2) return inPatches(x, y, [[3, 0, 5, 4], [5, 3, 6, 3], [13, 6, 5, 4], [16, 4, 3, 3]]);
            if (state.mark === 3) return inPatches(x, y, WHITE_SPOTS) || pixelIn(x, y, 10, 0, 3, 2);
            if (state.mark === 4) return fleck(x, y, 97, 57);
        }
        if (state.mark === 2 && face === "back") return y < 3 + (x < 3 ? 2 : 0);
        if (face === "front" || face === "back") {
            if (state.mark === 3) return inPatches(x, y, [[1, 6, 2, 2], [5, 2, 2, 3]]);
            if (state.mark === 4) return fleck(x, y, 139, face === "front" ? 19 : 54);
        }
        if (!side) return false;
        const px = Math.floor(x * 22 / width);
        const py = Math.floor(y * 10 / height);
        if (state.mark === 2) return inPatches(px, py, WHITE_FIELDS[face]);
        if (state.mark === 3) return inPatches(face === "far" ? 21 - px : px, py, WHITE_SPOTS);
        if (state.mark === 4) return fleck(px, py, face === "far" ? 173 : 53, px < 4 && py > 4 ? 25 : 57);
        return false;
    }

    function skeletonPixel(part, face, x, y, width, height) {
        const side = face === "near" || face === "far";
        const horizontal = face === "top" || face === "bottom";
        if (part.name === "body") {
            if (side) {
                const endBone = (x < 3 || x >= width - 3) && (y >= 2 || x % 2 === 0);
                const rib = x >= 4 && x <= width - 4 && (x % 3 !== 0 || y === height - 2) && y >= 1 && y <= height - 2;
                if (!endBone && !rib) return null;
                return BONE[y <= 2 ? 1 : grain(x, y)];
            }
            if (horizontal) {
                const spine = y >= Math.floor(height / 2) - 1 && y <= Math.floor(height / 2);
                const ribs = x >= 4 && x <= width - 4 && x % 3 !== 0;
                if (!spine && !ribs && x >= 3 && x < width - 3) return null;
                return BONE[face === "top" ? 2 : 1];
            }
            if (x >= 3 && x < width - 3 && y < height - 3) return null;
            return BONE[x === 0 || y === 0 ? 1 : 2];
        }
        if (part.material === "leg") {
            if (face === "bottom" || !horizontal && y < 2) return HOOF[x % 2];
            if (!horizontal && x > 0 && x < width - 1 && y > 2 && y < 8 && y !== 5) return null;
            return BONE[grain(x + 2, y)];
        }
        if (part.material === "mane") {
            if (!side || x === 0 || y < 2 || y >= height - 2 || y % 3 === 0) return null;
            return BONE[1];
        }
        if (part.material === "tail") {
            return null;
        }
        if (part.name === "neck") {
            if (side && x >= 3 && x < width - 1 && y > 3 && y < height - 1) return null;
            return BONE[grain(x, y)];
        }
        if (part.material === "ear") return BONE[x === 0 ? 1 : 2];
        if (part.material === "head" && side && pixelIn(x, y, 1, 2, 2, 2)) return "#2c2f33";
        if (part.material === "muzzle") {
            if (face === "front" && y >= 2 && y < 4 && (x === 0 || x === width - 1)) return "#44484c";
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
        const creamDetails = state.mountType === "minecraft:horse" && state.color === 1;
        const whiteBase = creamDetails && (part.material === "leg" && !horizontal && (y === 2 || y === 4)
            || foreheadMark(1, part, face, x, y, width, height));
        const marked = horseMark(state, part, face, x, y, width, height);
        if (whiteBase) color = WHITE[tone];
        if (marked) color = state.mark === 4 ? BLACK_MARK[tone] : WHITE[state.mark === 3 ? Math.max(0, tone - 1) : tone];
        if (part.material === "mane" || part.material === "tail") {
            // Uneven tips are transparent texels, rather than a solid slab.
            if (part.material === "tail" && !horizontal && y < [1, 0, 2][x % 3]) return null;
            if (part.material === "mane" && side && x === width - 1 && y % 4 === 0) return null;
            const strand = (x + (face === "top" ? y : 0)) % 3;
            color = palette.mane[strand];
        }
        if (part.material === "leg" && !horizontal && y < 2) color = HOOF[x % 2 ? 1 : 2];
        if (part.material === "leg" && face === "bottom") color = HOOF[0];
        if (part.material === "leg" && !horizontal && y === 6 && x > 0 && x < width - 1 && !marked) color = palette.coat[1];
        if (part.material === "head" && side) {
            if (x === 2 && y === 3) color = "#e1e1dc";
            if (x === 1 && y === 3) color = "#18191b";
            if (x === 1 && y === 4) color = palette.coat[0];
        }
        if (part.material === "muzzle") {
            if (donkey || mule) color = ["#696764", "#83807b", "#a3a09a", "#bdbbb4"][tone];
            else if (!marked && !whiteBase) color = palette.coat[face === "front" || side && x < 2 ? 0 : Math.max(0, tone - 1)];
            if (side && x === 0 && y === 3 || face === "front" && y === 3 && (x === 0 || x === width - 1)) color = "#393125";
            if (y === 0 && !horizontal) color = donkey || mule ? "#575452" : palette.coat[0];
        }
        if (part.material === "ear" && face === "front" && y > 0 && y < height - 1) color = palette.mane[1];
        if (donkey && part.name === "body" && face === "top" && y === Math.floor(height / 2)) color = palette.mane[1];
        if (camel) {
            if (part.name === "neck" && side) {
                if (pixelIn(x, y, 1, height - 3, 3, 1)) color = "#413323";
                if (x === 2 && y === height - 2) color = palette.coat[1];
            }
            if (part.material === "camel-muzzle") {
                color = palette.coat[tone];
                if (side && x < 2 && y === 3 || face === "front" && y === 3 && (x === 0 || x === width - 1)) color = "#5c4930";
                if (!horizontal && y === 1) color = "#8b6334";
                if (!horizontal && y === 0) color = palette.coat[3];
            }
            if (part.material === "camel-leg" && !horizontal) {
                if (y < 2) color = ["#635e52", "#79715e", "#8c8066"][x % 3];
                else if (y === 10 || y === 11 && x > 0 && x < width - 1) color = palette.coat[1];
            }
            if (part.material === "camel-leg" && face === "bottom") color = "#635e52";
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
        let opaque = true;
        for (let y = 0; y < rows; y += 1) {
            let start = 0;
            let previous = pixelColor(state, part, face, 0, y, columns, rows);
            if (!previous) opaque = false;
            for (let x = 1; x <= columns; x += 1) {
                const color = x < columns ? pixelColor(state, part, face, x, y, columns, rows) : undefined;
                if (x < columns && !color) opaque = false;
                if (color === previous) continue;
                if (previous) paths.set(previous, (paths.get(previous) || "") + `M${start},${y}h${x - start}v1h${start - x}z`);
                start = x;
                previous = color;
            }
        }
        const texture = { paths: [...paths.entries()], columns, rows, opaque };
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
        const geometry = geometryFor(model);
        const paintedFaces = new Map();
        for (const face of geometry.faces) {
            const { part, name, normal, width, height, vertices } = face;
            const inside = dot(normal, camera) <= .001;
            const texture = textureFor(state, part, name, width, height);
            if (!texture.paths.length || inside && texture.opaque && !model.skeleton) continue;
            const [p0, p1, , p3] = vertices.map(project);
            const matrix = [(p1[0] - p0[0]) / texture.columns, (p1[1] - p0[1]) / texture.columns, (p3[0] - p0[0]) / texture.rows, (p3[1] - p0[1]) / texture.rows, ...p0].map(value => value.toFixed(4)).join(" ");
            // A slight overlap prevents antialiasing seams between texels.
            const painted = texture.paths.map(([color, path]) => {
                const shaded = shadeColor(color, normal, yaw, inside);
                return `<path d="${path}" fill="${shaded}" stroke="${shaded}" stroke-width=".12" stroke-linejoin="miter"/>`;
            }).join("");
            const silhouette = !texture.opaque || model.skeleton ? "" : `<polygon points="${points(vertices)}" fill="${shadeColor(pixelColor(state, part, name, 0, 0, texture.columns, texture.rows), normal, yaw, false)}"/>`;
            paintedFaces.set(face, `<g data-model-part="${part.name}" data-model-face="${name}">${silhouette}<g class="mount-model-texels" transform="matrix(${matrix})">${painted}</g></g>`);
        }
        const surfaces = orderedSurfaces(geometry.tree, camera).map(polygon => {
            const content = paintedFaces.get(polygon.face);
            if (!content) return "";
            if (!polygon.clipped) return content;
            const clip = polygon.vertices.map(vertex => project(vertex).map(value => `${value.toFixed(4)}px`).join(" ")).join(",");
            // SVG user coordinates, independent of each group's bounding box
            // and the CSS size of the responsive stage; no document-wide IDs.
            return `<g style="clip-path:polygon(${clip}) view-box">${content}</g>`;
        });
        const groundY = frame.groundY.toFixed(2);
        const radius = Math.min(114, frame.radius * frame.zoom * .84).toFixed(2);
        return `<ellipse class="mount-model-ground" cx="180" cy="${groundY}" rx="${radius}" ry="21"/><ellipse cx="180" cy="${groundY}" rx="76" ry="12" fill="#000000" opacity=".12"/><g data-model-scale="${model.scale}" data-model-material="${model.skeleton ? "bone-cutout" : "pixel-coat"}">${surfaces.join("")}</g>`;
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
            <div id="mountModelStage" class="mount-model-stage" tabindex="0" role="group" aria-label="${escapeAttr(label)}" aria-describedby="mountModelHelp" data-yaw="${yaw.toFixed(3)}" data-mount-type="${escapeAttr(state.mountType)}" data-color="${state.color}" data-mark="${state.mark}" data-random="${state.random}">
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
