import subprocess
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run_node(source: str) -> None:
    result = subprocess.run(
        ["node", "-e", source],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout


def test_frontend_effects_view_list_state_html_formats_empty_and_protected_states() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/effects_view.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/effects_view.js" });

            const view = context.window.MCBEEffectsView;
            assert.strictEqual(
                view.effectsListStateHtml({ protectedActiveEffects: true, hasEffects: true }),
                '<div class="no-backups warning">ActiveEffects hat einen unbekannten NBT-Typ und wird geschützt erhalten.</div>',
            );
            assert.strictEqual(
                view.effectsListStateHtml({ hasEffects: false }),
                '<div class="no-backups">Keine aktiven Effekte.</div>',
            );
            assert.strictEqual(view.effectsListStateHtml({ hasEffects: true }), "");
            """
        )
    )


def test_frontend_effects_view_row_model_and_html_preserve_unknown_effects() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/effects_view.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/effects_view.js" });

            const view = context.window.MCBEEffectsView;
            const model = view.effectRowModel({
                id: 999,
                amplifier: 2,
                duration: 400,
                show_particles: false,
            }, 3, {});
            const html = view.effectRowHtml(model);

            assert.strictEqual(model.isProtectedEffect, true);
            assert.strictEqual(model.className, "effect-row unknown-effect");
            assert.strictEqual(model.level, 3);
            assert.strictEqual(model.durationSeconds, 20);
            assert.ok(html.includes("Unbekannter Effekt (999)"));
            assert.ok(html.includes("Unknown/future effect"));
            assert.ok(html.includes("data-index=\"3\""));
            assert.ok(html.includes("disabled"));
            assert.ok(!html.includes("checked"));
            """
        )
    )


def test_frontend_effects_view_translates_labels_and_explains_particles() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/effects_view.js", "utf8");
            const catalog = {
                "Stufe": "Level",
                "Dauer (s)": "Duration (s)",
                "Partikel": "Particles",
                "Partikel anzeigen": "Show particles",
                "Effekt entfernen": "Remove effect",
            };
            const context = {
                window: {
                    t(text) { return catalog[text] || text; },
                },
            };
            vm.runInNewContext(code, context, { filename: "static/effects_view.js" });

            const html = context.window.MCBEEffectsView.effectRowHtml({
                index: 0,
                isProtectedEffect: false,
                nameDe: "Speed",
                nameEn: "Tempo",
                desc: "",
                level: 2,
                durationSeconds: 30,
                showParticles: true,
            });

            assert.ok(html.includes("<label>Level</label>"));
            assert.ok(html.includes("<label>Duration (s)</label>"));
            assert.ok(html.includes(">Particles</span>"));
            assert.ok(html.includes('aria-label="Show particles"'));
            assert.ok(html.includes('aria-label="Remove effect"'));
            assert.ok(!html.includes("<label>Stufe</label>"));
            """
        )
    )


def test_frontend_effects_view_localizes_bilingual_descriptions() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/effects_view.js", "utf8");
            const context = { window: { MCBEI18n: {
                localizedPair: (de, en) => ({ primary: en || "", secondary: "" }),
            } } };
            vm.runInNewContext(code, context, { filename: "static/effects_view.js" });

            const model = context.window.MCBEEffectsView.effectRowModel(
                { id: 1, amplifier: 0, duration: 20 },
                0,
                { 1: ["Geschwindigkeit", "Speed", "Deutscher Text.", "English text."] },
            );

            assert.strictEqual(model.nameDe, "Speed");
            assert.strictEqual(model.desc, "English text.");

            const missingEnglish = context.window.MCBEEffectsView.effectRowModel(
                { id: 2, amplifier: 0, duration: 20 },
                0,
                { 2: ["Nur Deutsch", "", "Nur deutsche Beschreibung.", ""] },
            );
            assert.strictEqual(missingEnglish.nameDe, "2");
            assert.strictEqual(missingEnglish.nameEn, "");
            assert.strictEqual(missingEnglish.desc, "");
            """
        )
    )


def test_frontend_effects_view_row_element_uses_model_class_dataset_and_html() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/effects_view.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/effects_view.js" });

            const view = context.window.MCBEEffectsView;
            const created = [];
            const doc = {
                createElement(tagName) {
                    const el = { tagName, className: "", dataset: {}, innerHTML: "" };
                    created.push(el);
                    return el;
                },
            };
            const model = view.effectRowModel({ id: 1, amplifier: 0, duration: 100 }, 4, {
                1: ["Tempo", "Speed", "Schneller"],
            });
            const row = view.effectRowElement(model, doc);

            assert.strictEqual(created.length, 1);
            assert.strictEqual(row.tagName, "div");
            assert.strictEqual(row.className, "effect-row");
            assert.strictEqual(row.dataset.index, "4");
            assert.ok(row.innerHTML.includes("Tempo"));
            assert.ok(row.innerHTML.includes("data-index=\"4\""));
            """
        )
    )


def test_frontend_effects_view_reads_row_values_and_builds_patch() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/effects_view.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/effects_view.js" });

            const view = context.window.MCBEEffectsView;
            const fields = {
                ".eff-level": { value: "300" },
                ".eff-duration": { value: "10" },
                ".eff-particles": { checked: false },
            };
            const row = {
                querySelector(selector) {
                    return fields[selector] || null;
                },
            };

            const values = view.readEffectRowValues(row);
            assert.strictEqual(values.levelValue, "300");
            assert.strictEqual(values.durationSecondsValue, "10");
            assert.strictEqual(values.showParticles, false);

            const patch = view.effectPatchFromRowValues(values);
            assert.strictEqual(patch.amplifier, 255);
            assert.strictEqual(patch.duration, 200);
            assert.strictEqual(patch.show_particles, false);

            const fallbackPatch = view.effectPatchFromRowValues({ levelValue: "-5", durationSecondsValue: "-1" });
            assert.strictEqual(fallbackPatch.amplifier, 0);
            assert.strictEqual(fallbackPatch.duration, 0);
            assert.strictEqual(fallbackPatch.show_particles, true);
            """
        )
    )


def test_frontend_effects_view_list_model_returns_state_or_rows() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/effects_view.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/effects_view.js" });

            const view = context.window.MCBEEffectsView;
            const protectedList = view.effectsListModel({
                protectedActiveEffects: true,
                effects: [{ id: 1 }],
                effectsDb: { 1: ["Tempo", "Speed", "Schneller"] },
            });
            assert.ok(protectedList.listStateHtml.includes("ActiveEffects"));
            assert.strictEqual(protectedList.rowModels.length, 0);

            const rows = view.effectsListModel({
                effects: [{ id: 1, amplifier: 1, duration: 40 }],
                effectsDb: { 1: ["Tempo", "Speed", "Schneller"] },
            });
            assert.strictEqual(rows.listStateHtml, "");
            assert.strictEqual(rows.rowModels.length, 1);
            assert.strictEqual(rows.rowModels[0].nameDe, "Tempo");
            assert.strictEqual(rows.rowModels[0].durationSeconds, 2);
            """
        )
    )


def test_frontend_effects_view_keeps_exact_duration_when_the_seconds_field_is_unchanged() -> None:
    """Ein Save ohne Effektänderung darf keine Ticks verlieren.

    Der Save-Aufbau synchronisiert die Effektzeilen bereits, sobald ein
    ActiveEffects-Tag vorhanden ist -- nicht erst bei einer Effektänderung. Weil
    die Anzeige auf ganze Sekunden abrundet, würde ein Roundtrip sonst bis zu 19
    Ticks abschneiden und einen Effekt mit unter 20 Ticks ganz beenden.
    """

    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/effects_view.js", "utf8");
            const context = { window: {} };
            vm.runInNewContext(code, context, { filename: "static/effects_view.js" });

            const view = context.window.MCBEEffectsView;
            const row = seconds => ({ levelValue: "1", durationSecondsValue: String(seconds), showParticles: true });

            for (const ticks of [1, 19, 21, 599, 601]) {
                const shown = Math.floor(ticks / 20);
                const patch = view.effectPatchFromRowValues(row(shown), { duration: ticks, amplifier: 0 });
                assert.strictEqual(patch.duration, ticks, `${ticks} Ticks muessen erhalten bleiben`);
            }

            // Eine echte Änderung des Sekundenfeldes wird weiterhin übernommen.
            assert.strictEqual(view.effectPatchFromRowValues(row(31), { duration: 601, amplifier: 0 }).duration, 620);

            // Ein neuer Effekt ohne Ausgangswert rechnet weiterhin Sekunden in Ticks um.
            assert.strictEqual(view.effectPatchFromRowValues(row(30), null).duration, 600);
            assert.strictEqual(view.effectPatchFromRowValues(row(30)).duration, 600);
            """
        )
    )
