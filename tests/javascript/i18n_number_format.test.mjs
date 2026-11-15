import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

function harness(locale = "de") {
    let constructions = 0;
    const trackedIntl = Object.create(Intl);
    trackedIntl.NumberFormat = function (...args) {
        constructions += 1;
        return new Intl.NumberFormat(...args);
    };
    const context = vm.createContext({ window: {}, Intl: trackedIntl,
        document: { documentElement: { lang: locale }, readyState: "complete", getElementById: () => null } });
    for (const path of ["static/i18n.js", "static/villager_model.js"]) {
        vm.runInContext(readFileSync(path, "utf8"), context, { filename: path });
    }
    return { i18n: context.window.MCBEI18n, model: context.window.MCBEVillagerModel,
        constructions: () => constructions };
}

for (const [locale, position, health] of [
    ["de", "1.234,57 / 64 / -125,75", "12,35"],
    ["en", "1,234.57 / 64 / -125.75", "12.35"],
]) {
    test(`coordinates and health reuse one decimal formatter in ${locale}`, () => {
        const h = harness(locale);
        assert.equal(h.constructions(), 0, "construct only when needed");
        for (let index = 0; index < 10; index += 1) {
            assert.equal(h.model.positionText({ position: { x: 1234.567, y: 64, z: -125.75 } }), position);
            assert.equal(h.model.healthNumber(12.3456), health);
        }
        assert.equal(h.constructions(), 1);
    });

    test(`decimal reuse preserves tiny, extreme and signed-zero output in ${locale}`, () => {
        const h = harness(locale);
        const values = [-0, 0, 0.000000123456, -0.0098765, 0.01, 1.234567, -123456.789, 1e12, 1e12 + 1, 1e308];
        const rows = values.map(x => ({ position: { x, y: 64, z: -x } }));
        const positions = rows.map(h.model.positionText);
        const health = values.map(h.model.healthNumber);
        delete h.i18n.formatDecimal;
        assert.deepEqual(positions, rows.map(h.model.positionText));
        assert.deepEqual(health, values.map(h.model.healthNumber));
        assert.notEqual(h.model.healthNumber(values[2]), "0");
    });
}

test("non-finite decimal values retain their fallback without constructing a formatter", () => {
    const h = harness();
    for (const [value, expected] of [[NaN, "NaN"], [Infinity, "Infinity"], [undefined, ""], ["invalid", "invalid"]]) {
        assert.equal(h.i18n.formatDecimal(value), expected);
    }
    assert.equal(h.constructions(), 0);
});
