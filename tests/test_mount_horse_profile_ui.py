from __future__ import annotations

import json
import re
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


def _view_harness(body: str) -> str:
    return textwrap.dedent(
        rf"""
        const assert = require("assert");
        const fs = require("fs");
        const vm = require("vm");
        const escapeHtml = value => String(value)
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#39;");
        const context = {{ window: {{
            t: (value, params) => String(value).replace(/\{{(\w+)\}}/g, (match, key) =>
                params && key in params ? String(params[key]) : match),
            MCBEHtmlUtils: {{ escapeHtml, escapeAttr: escapeHtml }},
        }} }};
        vm.runInNewContext(fs.readFileSync("static/mount_view.js", "utf8"), context, {{
            filename: "static/mount_view.js",
        }});
        const view = context.window.MCBEMountView;
        {body}
        """
    )


def test_mount_numeric_helpers_handle_empty_and_valid_values() -> None:
    _run_node(
        _view_harness(
            r"""
            assert.strictEqual(view.finiteInput(""), null);
            assert.strictEqual(view.finiteInput("invalid"), null);
            assert.strictEqual(view.finiteInput("0.175"), 0.175);
            assert.ok(Math.abs(view.movementBlocksPerSecond(0.175) - 7.378) < 0.001);
            assert.ok(Number.isFinite(view.jumpHeightBlocks(0.5)));
            assert.strictEqual(view.positionText({ x: 1, y: 2.5, z: -3 }), "X 1 · Y 2.50 · Z -3");
            """
        )
    )


def test_mount_options_render_controls_for_the_selected_mount_type() -> None:
    _run_node(
        _view_harness(
            r"""
            const customHorse = view.optionsHtml(
                "minecraft:horse",
                undefined,
                true,
                9,
                { mode: "custom", health: 27, movement: 0.2, jump_strength: 0.7, color: 3, mark_variant: 4 },
            );
            assert.ok(customHorse.includes('id="mountTypeSelect"'));
            assert.ok(customHorse.includes('id="mountPlacementRadiusInput"'));
            assert.ok(customHorse.includes('value="9"'));
            assert.ok(customHorse.includes('id="mountHorseProfileMode"'));
            assert.ok(customHorse.includes('id="mountHorseHealthInput"'));
            assert.ok(customHorse.includes('value="27"'));
            assert.ok(!customHorse.match(/id="btnMountCreate"[^>]*disabled/));

            const donkey = view.optionsHtml("minecraft:donkey", undefined, false, 6, undefined, { health: 24 }, true);
            assert.ok(donkey.includes('id="mountStatHealthInput"'));
            assert.ok(donkey.includes('data-stat-key="health"'));
            assert.ok(donkey.includes('id="mountStatTamedCheckbox"'));
            assert.ok(donkey.match(/id="mountStatTamedCheckbox"[^>]*checked/));
            assert.ok(donkey.match(/id="btnMountCreate"[^>]*disabled/));

            const skeleton = view.optionsHtml("minecraft:skeleton_horse", undefined, true, 6, undefined, { jump_strength: 0.8 });
            assert.ok(skeleton.includes('id="mountStatJumpInput"'));
            assert.ok(skeleton.includes('data-stat-key="jump_strength"'));
            assert.ok(!skeleton.includes('id="mountStatTamedCheckbox"'));

            const camel = view.optionsHtml("minecraft:camel");
            assert.ok(!camel.includes('class="input-field mount-stat-field"'));
            assert.ok(!camel.includes('id="mountStatTamedCheckbox"'));
            """
        )
    )


def test_horse_temper_is_editable_in_custom_mode_and_rolled_otherwise() -> None:
    _run_node(
        _view_harness(
            r"""
            const optionsFor = profile => view.optionsHtml("minecraft:horse", undefined, true, 6, profile);

            assert.strictEqual(view.DEFAULT_HORSE_PROFILE.temper, 62);

            const custom = optionsFor({ mode: "custom", temper: 7 });
            assert.ok(custom.includes('id="mountHorseTemperInput"'), "Temper-Feld fehlt im Manuell-Modus");
            assert.ok(custom.includes('min="0"') && custom.includes('max="99"'), "Vanilla-Bereich 0-99 fehlt");
            assert.ok(/mountHorseTemperInput[^>]*value="7"/.test(custom), "gesetzter Wert wird nicht angezeigt");

            const fallback = optionsFor({ mode: "custom" });
            assert.ok(/mountHorseTemperInput[^>]*value="62"/.test(fallback), "Default 62 fehlt");

            const random = optionsFor({ mode: "random_like_game" });
            assert.ok(!random.includes('id="mountHorseTemperInput"'), "Zufallsmodus darf kein Eingabefeld zeigen");
            assert.ok(random.includes("0–99"), "Bereich wird im Zufallsmodus nicht angekuendigt");
            """
        )
    )


def test_horse_temper_input_explains_the_value_in_plain_language() -> None:
    _run_node(
        _view_harness(
            r"""
            const hints = [[3, "praktisch ungez"], [40, "etwas vorgez"], [70, "gut vorgez"], [95, "fast gez"]];
            for (const [value, expected] of hints) {
                const markup = view.optionsHtml("minecraft:horse", undefined, true, 6, { mode: "custom", temper: value });
                assert.ok(markup.includes(expected), `Hinweis fuer Temper ${value} fehlt: erwartet ${expected}`);
            }
            """
        )
    )


def test_every_live_hint_the_controller_updates_exists_in_the_rendered_markup() -> None:
    """Der Controller schreibt Hinweistexte per getElementById nach - fehlt die id,
    friert der Hinweis auf dem Startwert ein, ohne dass irgendetwas auffaellt.

    Genau so war es beim Zaehmfortschritt des Pferdes: der Text stimmte beim
    ersten Zeichnen und blieb danach stehen. Die ids entstehen erst beim Rendern
    (statFieldHtml baut sie aus einem Feld-Descriptor), deshalb prueft dieser Test
    die erzeugte Ausgabe und nicht den Quelltext.
    """

    controller = (ROOT / "static" / "mount_controller.js").read_text(encoding="utf-8")
    hint_ids = sorted({match for match in re.findall(r'getElementById\("(\w+Hint)"\)', controller)})
    assert hint_ids == sorted(
        {
            "mountHorseJumpHint",
            "mountHorseMovementHint",
            "mountHorseTemperHint",
            "mountStatJumpHint",
            "mountStatTemperHint",
        }
    ), "Die vollständige Menge der Live-Hinweise muss explizit verdrahtet bleiben."

    _run_node(
        _view_harness(
            f"const wanted = {json.dumps(hint_ids)};"
            + r"""
            // Jede Variante, die eigene Felder rendert: Pferd (eigenes Profil),
            // Esel wild (Zaehmfortschritt) und Esel gezaehmt (ohne).
            const markup = [
                view.optionsHtml("minecraft:horse", undefined, true, 6, { mode: "custom", temper: 40 }),
                view.optionsHtml("minecraft:donkey", undefined, true, 6, undefined, { health: 20, temper: 40 }, false),
                view.optionsHtml("minecraft:donkey", undefined, true, 6, undefined, { health: 20 }, true),
                view.optionsHtml("minecraft:skeleton_horse", undefined, true, 6, undefined, { jump_strength: 0.7 }, false),
            ].join("\n");
            const missing = wanted.filter(id => !markup.includes(`id="${id}"`));
            assert.deepStrictEqual(missing, [], `Hinweis-Elemente fehlen im Markup: ${missing.join(", ")}`);
            """
        )
    )


def test_donkey_and_mule_expose_temper_but_only_on_the_wild_variant() -> None:
    _run_node(
        _view_harness(
            r"""
            for (const mountType of ["minecraft:donkey", "minecraft:mule"]) {
                const wild = view.optionsHtml(mountType, undefined, false, 6, undefined, { health: 24, temper: 33 }, false);
                assert.ok(wild.includes('id="mountStatTemperInput"'), `${mountType}: Temper-Feld fehlt`);
                assert.ok(wild.includes('data-stat-key="temper"'), `${mountType}: data-stat-key fehlt`);
                assert.ok(/mountStatTemperInput[^>]*value="33"/.test(wild), `${mountType}: Wert wird nicht angezeigt`);
                assert.ok(/mountStatTemperInput[^>]*min="0"[^>]*max="99"/.test(wild), `${mountType}: Vanilla-Bereich 0-99 fehlt`);
                assert.ok(wild.includes("etwas vorgez"), `${mountType}: Klartext-Hinweis fehlt`);
                // Das Leben-Feld darf durch das zweite Feld nicht verdraengt werden.
                assert.ok(wild.includes('id="mountStatHealthInput"'), `${mountType}: Leben-Feld fehlt`);
                assert.ok(/mountStatHealthInput[^>]*value="24"/.test(wild), `${mountType}: Leben-Wert fehlt`);

                // Zaehmen entfernt das Temper-Tag; dann darf es auch kein Feld geben.
                const tamed = view.optionsHtml(mountType, undefined, false, 6, undefined, { health: 24, temper: 33 }, true);
                assert.ok(!tamed.includes('id="mountStatTemperInput"'), `${mountType}: gezaehmt darf kein Temper-Feld zeigen`);
                assert.ok(tamed.includes('id="mountStatHealthInput"'), `${mountType}: Leben bleibt auch gezaehmt einstellbar`);
                assert.ok(tamed.includes("keinen Zähmfortschritt mehr"), `${mountType}: Erklaerung zum Wegfall fehlt`);
            }

            // Typen ohne Temper-Tag bieten es auch nicht an.
            const skeleton = view.optionsHtml("minecraft:skeleton_horse", undefined, true, 6, undefined, { jump_strength: 0.8 });
            assert.ok(!skeleton.includes('id="mountStatTemperInput"'));
            assert.ok(!view.optionsHtml("minecraft:camel").includes('id="mountStatTemperInput"'));
            """
        )
    )


def test_preview_notes_stay_collapsed_unless_something_blocks_creating() -> None:
    """The list sits above the sketch, so leaving it open pushes everything down.

    Its content is static explanation -- except when creation is blocked, and
    then the reason is in there and must not be hidden.
    """

    _run_node(
        _view_harness(
            r"""
            const base = {
                mount_type: "minecraft:horse", mount_label: "Pferd",
                player_reference: { player_label: "Alex" }, player_position: { x: 0, y: 64, z: 0 },
                dimension_id: 0, placement_search: { radius: 6 },
                warnings: ["Erster Hinweis", "Zweiter Hinweis", "Dritter Hinweis"],
                candidate_positions: [],
            };

            const ok = view.previewHtml({ ...base, can_create: true });
            assert.ok(ok.includes("<details"), "Hinweise sind kein Aufklapp-Element");
            assert.ok(!/<details[^>]*class="mount-warning-list[^"]*"[^>]*\sopen/.test(ok), "Hinweise starten aufgeklappt");
            assert.ok(ok.includes("Hinweise zur Vorschau (3)"), "Anzahl fehlt in der Zusammenfassung");
            // Zugeklappt heißt nicht entfernt: der Text bleibt im Markup lesbar.
            assert.ok(ok.includes("Zweiter Hinweis"));

            // Blockiert das Erzeugen, steht der Grund in dieser Liste.
            const blocked = view.previewHtml({ ...base, can_create: false });
            assert.ok(/<details[^>]*class="mount-warning-list[^"]*"[^>]*\sopen/.test(blocked), "Grund für blockiertes Erzeugen bleibt verborgen");

            assert.strictEqual(view.warningListHtml([]), "", "leere Liste erzeugt weiter nichts");
            """
        )
    )


def test_random_profile_ranges_are_behind_a_disclosure() -> None:
    _run_node(
        _view_harness(
            r"""
            const random = view.optionsHtml("minecraft:horse", undefined, true, 6, { mode: "random_like_game" });
            assert.ok(random.includes("mount-profile-ranges-disclosure"), "Bereichs-Chips sind nicht aufklappbar");
            assert.ok(!/mount-profile-ranges-disclosure[^>]*\sopen/.test(random), "Chips starten aufgeklappt");
            assert.ok(random.includes("Welche Bereiche gewürfelt werden"));
            // Inhalt bleibt vorhanden, nur eingeklappt.
            assert.ok(random.includes('id="mountHorseRangeSummary"'));
            assert.ok(random.includes("15–30 zufällig") && random.includes("0–99 zufällig"));

            // Im Manuell-Modus gibt es keine Bereichs-Chips, also auch keinen Aufklapper.
            const custom = view.optionsHtml("minecraft:horse", undefined, true, 6, { mode: "custom", temper: 20 });
            assert.ok(!custom.includes("mount-profile-ranges-disclosure"));
            assert.ok(custom.includes('id="mountHorseTemperInput"'));
            """
        )
    )


def test_mount_preview_exposes_selectable_and_blocked_candidates_safely() -> None:
    _run_node(
        _view_harness(
            r"""
            const markup = view.previewHtml({
                mount_type: "minecraft:horse",
                mount_label: "Horse",
                player_reference: { player_label: "Alex" },
                player_position: { x: 0, y: 64, z: 0 },
                dimension_id: 0,
                can_create: true,
                selected_candidate_id: "east_2",
                placement_search: { radius: 6, prefers_view_direction: true },
                warnings: ["Unsafe <script>alert(1)</script>"],
                candidate_positions: [
                    { id: "east_2", x: 2, y: 64, z: 0, distance: 2, safe_to_place: true },
                    { id: "west_2", x: -2, y: 64, z: 0, distance: 2, safe_to_place: false },
                ],
            });

            assert.ok(markup.includes('class="mount-map-point safe active"'));
            assert.ok(markup.includes('data-candidate-id="east_2"'));
            assert.ok(markup.match(/data-candidate-id="west_2"[^>]*disabled/));
            assert.ok(markup.includes('class="mount-placement-target"'));
            assert.ok(markup.includes('class="mount-tech-overlay"'));
            assert.ok(markup.includes("Unsafe &lt;script&gt;alert(1)&lt;/script&gt;"));
            assert.ok(!markup.includes("Unsafe <script>"));
            """
        )
    )


def test_pending_mounts_render_actionable_drafts_and_escape_data() -> None:
    _run_node(
        _view_harness(
            r"""
            assert.strictEqual(view.pendingMountsHtml([]), "");
            const markup = view.pendingMountsHtml([{
                id: 'draft" onclick="bad',
                mountType: "minecraft:donkey",
                mountLabel: "Donkey <unsafe>",
                selectedPosition: { x: 1, y: 2, z: 3 },
                safetyStatus: "safe",
                mountStats: { health: 20 },
                tamed: true,
            }]);

            assert.ok(markup.includes('class="pending-mount-card"'));
            assert.ok(markup.includes('id="btnMountReviewPending"'));
            assert.ok(markup.includes('id="btnMountDiscardPending"'));
            assert.ok(markup.includes('data-remove-pending-mount="draft&quot; onclick=&quot;bad"'));
            assert.ok(markup.includes("Donkey &lt;unsafe&gt;"));
            assert.ok(!markup.includes("Donkey <unsafe>"));
            """
        )
    )


def test_pending_mount_card_shows_every_value_that_will_be_written() -> None:
    """A staged value the card omits looks like it was not applied."""

    _run_node(
        _view_harness(
            r"""
            const card = mount => view.pendingMountsHtml([{ id: "d1", mountType: "minecraft:donkey", mountLabel: "Esel", ...mount }]);

            const donkey = card({ mountStats: { health: 24, temper: 77 } });
            assert.ok(donkey.includes("24 Leben"), "Leben fehlt auf der Karte");
            assert.ok(donkey.includes("Zähmfortschritt 77"), "Zähmfortschritt fehlt auf der Karte");

            // Nicht gesetzt heißt "wie im Spiel gewuerfelt" und darf nichts vortaeuschen.
            assert.ok(!card({ mountStats: { health: 24 } }).includes("Zähmfortschritt"));
            // Gezaehmt: das Tag existiert nicht, also auch keine Zeile dafuer.
            assert.ok(!card({ mountStats: { health: 24, temper: null }, tamed: true }).includes("Zähmfortschritt"));

            const horse = view.pendingMountsHtml([{
                id: "h1",
                mountType: "minecraft:horse",
                mountLabel: "Pferd",
                horseProfile: { mode: "custom", health: 27, movement: 0.2, jump_strength: 0.7, temper: 12 },
            }]);
            assert.ok(horse.includes("Zähmfortschritt 12"), "Pferd zeigt den Zähmfortschritt nicht");
            """
        )
    )


def test_mount_icons_are_decorative_and_scale_to_the_requested_size() -> None:
    _run_node(
        _view_harness(
            r"""
            for (const mountType of [
                "minecraft:horse",
                "minecraft:donkey",
                "minecraft:mule",
                "minecraft:camel",
                "minecraft:skeleton_horse",
            ]) {
                const icon = view.mountIconSvg(mountType, 2, 48);
                assert.ok(icon.includes('aria-hidden="true"'));
                assert.ok(icon.includes('width="48" height="48"'));
                assert.ok(icon.includes('viewBox="0 0 16 16"'));
                assert.ok(icon.includes("<rect"));
            }
            """
        )
    )
