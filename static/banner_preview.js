(function () {
    "use strict";

    // RGB multiplication preserves the texture's cloth shading. Alpha remains
    // independent, including partial coverage around motifs and gradients.
    function tintPixels(source, hex) {
        if (!/^#[0-9a-f]{6}$/i.test(hex)) throw new Error("Invalid banner dye");
        const rgb = [1, 3, 5].map(start => parseInt(hex.slice(start, start + 2), 16));
        const result = new Uint8ClampedArray(source);
        for (let offset = 0; offset < result.length; offset += 4) {
            for (let channel = 0; channel < 3; channel++) {
                result[offset + channel] = Math.round(source[offset + channel] * rgb[channel] / 255);
            }
        }
        return result;
    }

    function createRenderer(doc) {
        const textures = new Map();
        function load(url) {
            const parsed = new URL(url, doc.baseURI);
            if (parsed.origin !== new URL(doc.baseURI).origin || !parsed.pathname.startsWith("/api/icons/")) {
                return Promise.reject(new Error("Invalid banner texture URL"));
            }
            if (textures.has(url)) return textures.get(url);
            const pending = new Promise((resolve, reject) => {
                const image = new doc.defaultView.Image();
                const timeout = setTimeout(() => { image.src = ""; reject(new Error("Banner texture timeout")); }, 15000);
                image.onload = () => {
                    clearTimeout(timeout);
                    try {
                        const scale = image.naturalWidth / 20;
                        if (!Number.isInteger(scale) || scale < 1 || scale > 8 || image.naturalHeight !== 40 * scale) {
                            throw new Error("Invalid banner texture size");
                        }
                        const canvas = doc.createElement("canvas");
                        canvas.width = image.naturalWidth; canvas.height = image.naturalHeight;
                        const ctx = canvas.getContext("2d");
                        ctx.drawImage(image, 0, 0);
                        resolve(ctx.getImageData(0, 0, canvas.width, canvas.height));
                    } catch (error) { reject(error); }
                };
                image.onerror = () => { clearTimeout(timeout); reject(new Error("Banner texture unavailable")); };
                image.src = url;
            });
            // Bound retained image data across cache publications. Failures can
            // be retried; an old rejection cannot evict a newer request.
            if (textures.size >= 64) textures.delete(textures.keys().next().value);
            textures.set(url, pending);
            pending.catch(() => { if (textures.get(url) === pending) textures.delete(url); });
            return pending;
        }

        async function render(baseColor, patterns, assets, colors, type = 0) {
            const layers = [type === 1 ? { pattern: "illager", color: null } : { pattern: "base", color: baseColor },
                ...patterns.map(({ pattern, color }) => ({ pattern, color }))];
            if (layers.some(layer => !assets[layer.pattern]?.url)) return null;
            const images = await Promise.all(layers.map(layer => load(assets[layer.pattern].url)));
            const canvas = doc.createElement("canvas");
            canvas.width = Math.max(...images.map(image => image.width)); canvas.height = canvas.width * 2;
            const ctx = canvas.getContext("2d"); ctx.imageSmoothingEnabled = false;
            const overlay = doc.createElement("canvas");
            images.forEach((image, index) => {
                overlay.width = image.width; overlay.height = image.height;
                const overlayCtx = overlay.getContext("2d");
                const tinted = overlayCtx.createImageData(image.width, image.height);
                tinted.data.set(layers[index].color === null ? image.data : tintPixels(image.data, colors[layers[index].color]));
                overlayCtx.putImageData(tinted, 0, 0);
                ctx.drawImage(overlay, 0, 0, canvas.width, canvas.height);
            });
            return canvas;
        }
        return { render };
    }
    function bannerData(item) {
        if (item?.name !== "minecraft:banner") return null;
        const data = item.special_edit?.kind === "banner" ? item.special_edit.data
            : item.special_item?.kind === "banner" ? item.special_item.data : null;
        return { type: data?.type === 1 ? 1 : 0, patterns: data?.patterns || [], color: Number(item.damage ?? 0) };
    }
    function createIconProvider(doc, getAssets, colors) {
        const renderer = createRenderer(doc);
        const cache = new Map();
        let sequence = 0;
        return item => {
            const data = bannerData(item);
            if (!data) return null;
            const assets = getAssets();
            const key = JSON.stringify([data, assets, item.special_item?.editable === false]);
            if (cache.has(key)) return cache.get(key);
            const color = /^#[0-9a-f]{6}$/i.test(colors[data.color]) ? colors[data.color] : "#777777";
            // A colored cloth is useful before textures are available. The
            // question mark makes an unavailable motif explicit.
            const unknown = data.type === 1 || data.patterns.length || item.special_item?.editable === false;
            const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="32" height="48" viewBox="0 0 32 48"><metadata>${++sequence}</metadata><path fill="#8c6940" d="M14 2h3v46h-3zM4 3h23v3H4z"/><path fill="${color}" stroke="#777" d="M5 5h21v37H5z"/>${unknown ? '<text x="16" y="29" text-anchor="middle" font-size="19" fill="white" stroke="black" stroke-width=".5">?</text>' : ""}</svg>`;
            const pendingUrl = `data:image/svg+xml,${encodeURIComponent(svg)}`;
            const result = { url: pendingUrl };
            if (cache.size >= 128) cache.delete(cache.keys().next().value);
            cache.set(key, result);
            if (item.special_item?.editable === false && !item.special_edit) return result;
            renderer.render(data.color, data.patterns, assets, colors, data.type).then(cloth => {
                if (!cloth || cache.get(key) !== result) return;
                const canvas = doc.createElement("canvas"); canvas.width = 32; canvas.height = 48;
                const ctx = canvas.getContext("2d"); ctx.imageSmoothingEnabled = false;
                ctx.fillStyle = "#8c6940"; ctx.fillRect(14, 2, 3, 46); ctx.fillRect(4, 3, 23, 3);
                ctx.drawImage(cloth, 5, 5, 21, 37);
                result.url = canvas.toDataURL("image/png");
                // Replace only matching pictures. Never re-render a form or
                // update an image that has since switched to another draft.
                doc.querySelectorAll("img").forEach(img => { if (img.getAttribute("src") === pendingUrl) img.src = result.url; });
            }).catch(() => { if (cache.get(key) === result) cache.delete(key); });
            return result;
        };
    }
    window.MCBEBannerPreview = { createRenderer, tintPixels, bannerData, createIconProvider };
}());
