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

        async function render(baseColor, patterns, assets, colors) {
            const layers = [{ pattern: "base", color: baseColor }, ...patterns.map(({ pattern, color }) => ({ pattern, color }))];
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
                tinted.data.set(tintPixels(image.data, colors[layers[index].color]));
                overlayCtx.putImageData(tinted, 0, 0);
                ctx.drawImage(overlay, 0, 0, canvas.width, canvas.height);
            });
            return canvas;
        }
        return { render };
    }
    window.MCBEBannerPreview = { createRenderer, tintPixels };
}());
