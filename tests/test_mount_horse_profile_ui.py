from __future__ import annotations

import textwrap

from tests.node_runner import run_node


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
    run_node(
        _view_harness(
            r"""
            assert.strictEqual(view.finiteInput(""), null);
            assert.strictEqual(view.finiteInput("invalid"), null);
            assert.strictEqual(view.finiteInput("0.175"), 0.175);
            assert.ok(Math.abs(view.movementBlocksPerSecond(0.175) - 7.378) < 0.001);
            assert.ok(Number.isFinite(view.jumpHeightBlocks(0.5)));
            for (const value of [100, -1, NaN, Infinity]) {
                assert.strictEqual(view.movementHintText(value), "");
                assert.strictEqual(view.jumpHintText(value), "");
                assert.strictEqual(view.temperHintText(value), "");
            }
            assert.strictEqual(view.temperHintText(3.5), "");
            assert.strictEqual(view.positionText({ x: 1, y: 2.5, z: -3 }), "X 1 · Y 2.50 · Z -3");
            """
        )
    )


def test_mount_options_render_controls_for_the_selected_mount_type() -> None:
    run_node(
        _view_harness(
            r"""
            const customHorse = view.optionsHtml(
                "minecraft:horse",
                undefined,
                9,
                { mode: "custom", health: 27, movement: 0.2, jump_strength: 0.7, color: 3, mark_variant: 4 },
            );
            assert.ok(customHorse.includes('id="mountTypeSelect"'));
            assert.ok(customHorse.includes('id="mountPlacementRadiusInput"'));
            assert.ok(customHorse.includes('value="9"'));
            assert.ok(customHorse.includes('id="mountHorseProfileMode"'));
            assert.ok(customHorse.includes('id="mountHorseHealthInput"'));
            assert.ok(customHorse.includes('value="27"'));
            assert.ok(!customHorse.includes('id="btnMountCreate"'), "Staging belongs after the placement results");

            const donkey = view.optionsHtml("minecraft:donkey", undefined, 6, undefined, { health: 24 }, true);
            assert.ok(donkey.includes('id="mountStatHealthInput"'));
            assert.ok(donkey.includes('data-stat-key="health"'));
            assert.ok(donkey.includes('id="mountStatTamedCheckbox"'));
            assert.ok(donkey.match(/id="mountStatTamedCheckbox"[^>]*checked/));
            assert.ok(!donkey.includes('id="btnMountCreate"'));

            const skeleton = view.optionsHtml("minecraft:skeleton_horse", undefined, 6, undefined, { jump_strength: 0.8 });
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
    run_node(
        _view_harness(
            r"""
            const optionsFor = profile => view.optionsHtml("minecraft:horse", undefined, 6, profile);

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
    run_node(
        _view_harness(
            r"""
            const hints = [[3, "praktisch ungez"], [40, "etwas vorgez"], [70, "gut vorgez"], [95, "fast gez"]];
            for (const [value, expected] of hints) {
                const markup = view.optionsHtml("minecraft:horse", undefined, 6, { mode: "custom", temper: value });
                assert.ok(markup.includes(expected), `Hinweis fuer Temper ${value} fehlt: erwartet ${expected}`);
            }
            """
        )
    )


def test_every_editable_stat_has_an_associated_live_hint() -> None:
    run_node(
        _view_harness(
            r"""
            const variants = [
                view.optionsHtml("minecraft:horse", undefined, 6, { mode: "custom", temper: 40 }),
                view.optionsHtml("minecraft:donkey", undefined, 6, undefined, { health: 20, temper: 40 }, false),
                view.optionsHtml("minecraft:donkey", undefined, 6, undefined, { health: 20 }, true),
                view.optionsHtml("minecraft:skeleton_horse", undefined, 6, undefined, { jump_strength: 0.7 }, false),
            ];
            for (const markup of variants) {
                const inputs = [...markup.matchAll(/<input\b[^>]*>/g)]
                    .map(match => match[0]).filter(input => /mount-(horse-profile|stat)-field/.test(input));
                assert.ok(inputs.length);
                for (const input of inputs) {
                    const hint = input.match(/aria-describedby="([^"]+)"/);
                    assert.ok(hint, `Missing associated hint: ${input}`);
                    assert.ok(markup.includes(`id="${hint[1]}"`), `Missing live hint: ${hint[1]}`);
                }
            }
            """
        )
    )


def test_stat_validation_distinguishes_ranges_empty_values_and_integer_fields() -> None:
    run_node(
        _view_harness(
            r"""
            const input = {value: "25", min: "15", max: "30", required: true, step: "1"};
            assert.strictEqual(view.numberInputError(input), "");
            assert.strictEqual(view.numberInputError({...input, value: "100"}), "Zulässig: 15 bis 30.");
            assert.strictEqual(view.numberInputError({...input, value: ""}), "Bitte eine gültige Zahl eingeben.");
            assert.strictEqual(view.numberInputError({...input, value: "", required: false}), "");
            assert.strictEqual(view.numberInputError({...input, value: "", required: false}, true), "Bitte eine gültige Zahl eingeben.");
            assert.strictEqual(view.numberInputError({...input, value: "NaN"}), "Bitte eine gültige Zahl eingeben.");
            assert.strictEqual(view.numberInputError({...input, value: "20.5", validity: {stepMismatch: true}}), "Bitte eine ganze Zahl eingeben.");
            for (const [min, max] of [[15,30],[0.1125,0.3375],[0.4,1],[0,99]]) {
                for (const value of [min,max]) assert.strictEqual(view.numberInputError({...input, min, max, value}), "");
                for (const value of [min-1,max+1,100]) assert.match(view.numberInputError({...input, min, max, value}), /Zulässig:/);
            }
            """
        )
    )


def test_donkey_and_mule_expose_temper_but_only_on_the_wild_variant() -> None:
    run_node(
        _view_harness(
            r"""
            for (const mountType of ["minecraft:donkey", "minecraft:mule"]) {
                const wild = view.optionsHtml(mountType, undefined, 6, undefined, { health: 24, temper: 33 }, false);
                assert.ok(wild.includes('id="mountStatTemperInput"'), `${mountType}: Temper-Feld fehlt`);
                assert.ok(wild.includes('data-stat-key="temper"'), `${mountType}: data-stat-key fehlt`);
                assert.ok(/mountStatTemperInput[^>]*value="33"/.test(wild), `${mountType}: Wert wird nicht angezeigt`);
                assert.ok(/mountStatTemperInput[^>]*min="0"[^>]*max="99"/.test(wild), `${mountType}: Vanilla-Bereich 0-99 fehlt`);
                assert.ok(wild.includes("etwas vorgez"), `${mountType}: Klartext-Hinweis fehlt`);
                assert.ok(!wild.includes("Gehört dem ausgewählten Spieler."), `${mountType}: wildes Tier darf keinen Besitzer versprechen`);
                assert.ok(!wild.includes('aria-describedby="mountTamedHint"'), `${mountType}: Verweis auf unsichtbaren Hinweis`);
                // Das Leben-Feld darf durch das zweite Feld nicht verdraengt werden.
                assert.ok(wild.includes('id="mountStatHealthInput"'), `${mountType}: Leben-Feld fehlt`);
                assert.ok(/mountStatHealthInput[^>]*value="24"/.test(wild), `${mountType}: Leben-Wert fehlt`);

                // Zaehmen entfernt das Temper-Tag; dann darf es auch kein Feld geben.
                const tamed = view.optionsHtml(mountType, undefined, 6, undefined, { health: 24, temper: 33 }, true);
                assert.ok(!tamed.includes('id="mountStatTemperInput"'), `${mountType}: gezaehmt darf kein Temper-Feld zeigen`);
                assert.ok(tamed.includes('id="mountStatHealthInput"'), `${mountType}: Leben bleibt auch gezaehmt einstellbar`);
                assert.ok(tamed.includes("Gehört dem ausgewählten Spieler."), `${mountType}: Besitzer fehlt beim gezähmten Tier`);
                assert.ok(tamed.includes('aria-describedby="mountTamedHint"'));
            }

            // Typen ohne Temper-Tag bieten es auch nicht an.
            const skeleton = view.optionsHtml("minecraft:skeleton_horse", undefined, 6, undefined, { jump_strength: 0.8 });
            assert.ok(!skeleton.includes('id="mountStatTemperInput"'));
            assert.ok(!view.optionsHtml("minecraft:camel").includes('id="mountStatTemperInput"'));
            """
        )
    )


def test_preview_notes_need_no_group_and_blocking_reasons_stay_visible() -> None:

    run_node(
        _view_harness(
            r"""
            const base = {
                mount_type: "minecraft:horse", mount_label: "Pferd",
                player_reference: { player_label: "Alex" }, player_position: { x: 0, y: 64, z: 0 },
                dimension_id: 0, placement_search: { radius: 6 },
                warnings: ["Erster Hinweis", "Zweiter Hinweis", "Dritter Hinweis"],
                candidate_positions: [],
            };

            const regular = view.previewHtml({ ...base, warnings: [], can_create: true });
            assert.ok(!regular.includes('class="mount-warning-list'), "Leere Vorschauhinweise bleiben sichtbar");
            assert.ok(!regular.includes('data-disclosure="preview-notes"'), "Überflüssige Hinweisgruppe bleibt erhalten");
            const ok = view.previewHtml({ ...base, can_create: true });
            assert.ok(ok.includes('<p class="mount-tech-note">Zweiter Hinweis</p>'));
            assert.ok(!ok.includes('data-disclosure="preview-notes"'), "Konkreter Hinweis braucht keinen Aufklapper");

            const blocked = view.previewHtml({ ...base, can_create: false });
            assert.ok(blocked.includes('<div class="mount-warning-list status-note warning">'));
            assert.ok(!blocked.includes('data-disclosure="preview-notes"'));
            assert.ok(blocked.indexOf('Zweiter Hinweis') < blocked.indexOf('<dialog'), "Blockierender Grund ist nur im Dialog sichtbar");
            assert.ok(blocked.includes("Erzeugung nicht verfügbar"));
            assert.ok(!blocked.includes("Kein Standplatz verfügbar"), "Erzeugungsbeschränkung als fehlender Standplatz ausgegeben");
            assert.strictEqual(view.queueDisabledReason({...base, can_create:false}), base.warnings.join(" "));
            const missingReason = view.previewHtml({...base, warnings:[], can_create:false});
            assert.ok(missingReason.includes('<p>Dieses Mount kann hier nicht erzeugt werden.</p>'), "Fehlende Begründung braucht einen sichtbaren Fallback");
            const single = view.warningListHtml(['Nur in der Oberwelt.'], {blocked:true});
            assert.ok(single.includes('<p>Nur in der Oberwelt.</p>') && !single.includes('<ul>'));
            assert.strictEqual(view.warningListHtml([]), "", "leere Liste erzeugt weiter nichts");
            """
        )
    )


def test_placement_details_keep_exceptions_without_repeating_success() -> None:
    run_node(
        _view_harness(
            r"""
            const candidate = {id:'east_2', x:2, y:65, z:0, distance:2, safe_to_place:true,
                radius_scan_adjusted:true, radius_scan_checked_count:2,
                radius_scan_attempts:[{distance:3,safe_to_place:false},{distance:2,safe_to_place:true}],
                chunk_probe:{footprint_check:{edge_overhang_count:0, message:'Boden und Körperraum geprüft.',
                    columns:[{block_x:2,block_z:0,center:true,block_names:{floor:'minecraft:stone',feet:'minecraft:air',head:'minecraft:air'}}]}}};
            const details = item => view.previewHtml({can_create:true,selected_candidate_id:item.id,candidate_positions:[item]})
                .split('<dialog')[1];
            const regular = details(candidate);
            assert.ok(regular.includes('Sicher platzierbar'));
            assert.ok(!regular.includes('Boden und Körperraum geprüft.'), 'Sicheres Ergebnis braucht keinen zweiten Absatz');
            assert.ok(regular.includes('Abstand innerhalb des Radius angepasst'), 'Abstandsanpassung ging verloren');
            assert.ok(regular.includes('3 Blöcke · nicht möglich'));
            assert.ok(regular.includes('2 Blöcke · sicher'));

            const footprint = candidate.chunk_probe.footprint_check;
            const edge = details({...candidate,chunk_probe:{footprint_check:{...footprint,
                edge_overhang_count:1,message:'Eine Randspalte ohne Boden wird toleriert.'}}});
            assert.ok(edge.includes('Eine Randspalte ohne Boden wird toleriert.'), 'Tolerierter Überhang muss erklärt bleiben');
            for (const verdict of [false, null]) {
                const issue = details({...candidate,safe_to_place:verdict,chunk_probe:{footprint_check:{...footprint,
                    message:'Konkretes Prüfproblem <img src=x>'}}});
                assert.ok(issue.includes('<p class="mount-fp-caption">Konkretes Prüfproblem &lt;img src=x&gt;</p>'),
                    'Konkretes Problem darf ohne strukturierte Diagnose nicht verschwinden');
                assert.ok(!issue.includes('<img src=x>'));
            }
            """
        )
    )


def test_center_block_rows_follow_vertical_order_and_keep_their_values() -> None:
    run_node(
        _view_harness(
            r"""
            const names = {floor:'minecraft:polished_andesite', feet:'minecraft:water', head:'minecraft:air'};
            const candidate = {id:'east_2', x:2, y:65, z:0, distance:2, safe_to_place:false,
                chunk_probe:{placement_check:{block_names:names, blocks:{
                    floor:{block_name:names.floor},feet:{block_name:names.feet},head:{block_name:names.head}
                }}}};
            const render = () => view.previewHtml({can_create:true,selected_candidate_id:'east_2',candidate_positions:[candidate]});
            const rows = markup => [...markup.matchAll(/<tr><th scope="row">([^<]+)<\/th><td>(.*?)<\/td><\/tr>/gs)]
                .map(match=>({label:match[1],value:match[2]}));
            const normal = render();
            const normalRows = rows(normal);
            assert.deepStrictEqual(normalRows.map(row=>row.label), ['Kopfraum','Fußraum','Boden']);
            assert.ok(normalRows[0].value.includes('air'));
            assert.ok(normalRows[1].value.includes('water'));
            assert.ok(normalRows[2].value.includes('polished_andesite'));
            assert.ok(!normal.includes('Blockprobe:') && !normal.includes('(floor)'));

            // Additional body levels sit above head/feet and use the actual
            // footprint center, even when the legacy probe disagrees.
            candidate.chunk_probe.footprint_check = {columns:[{center:true,block_x:2,block_z:0,
                block_names:{...names, floor:'minecraft:stone',body_2:'minecraft:glass',body_3:'minecraft:snow'}}]};
            const tallRows = rows(render());
            assert.deepStrictEqual(tallRows.map(row=>row.label), ['Körperraum Ebene 4','Körperraum Ebene 3','Kopfraum','Fußraum','Boden']);
            assert.ok(tallRows[0].value.includes('snow'));
            assert.ok(tallRows[1].value.includes('glass'));
            assert.ok(tallRows[4].value.includes('stone'));
            """
        )
    )


def test_random_profile_ranges_are_behind_a_disclosure() -> None:
    run_node(
        _view_harness(
            r"""
            const random = view.optionsHtml("minecraft:horse", undefined, 6, { mode: "random_like_game" });
            assert.ok(random.includes("mount-profile-ranges-disclosure"), "Bereichs-Chips sind nicht aufklappbar");
            assert.ok(!/mount-profile-ranges-disclosure[^>]*\sopen/.test(random), "Chips starten aufgeklappt");
            assert.ok(random.includes("Welche Bereiche gewürfelt werden"));
            // Inhalt bleibt vorhanden, nur eingeklappt.
            assert.ok(random.includes('id="mountHorseRangeSummary"'));
            assert.ok(random.includes("15–30 zufällig") && random.includes("0–99 zufällig"));

            // Im Manuell-Modus gibt es keine Bereichs-Chips, also auch keinen Aufklapper.
            const custom = view.optionsHtml("minecraft:horse", undefined, 6, { mode: "custom", temper: 20 });
            assert.ok(!custom.includes("mount-profile-ranges-disclosure"));
            assert.ok(custom.includes('id="mountHorseTemperInput"'));
            """
        )
    )


def test_mount_preview_exposes_selectable_and_blocked_candidates_safely() -> None:
    run_node(
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
    run_node(
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


def test_unchecked_placement_explains_cause_action_and_affected_chunks():
    run_node(
        _view_harness(
            r"""
            const candidate = {
                id: "east_2", x: 15.5, y: 65, z: 8.5, distance: 2, safe_to_place: null,
                warning: "Legacy fallback",
                placement_issues: [
                    {message: "Chunk-Daten fehlen <img src=x onerror=bad>", hint: "Welt speichern und neu laden.",
                     chunks: [{x:1,z:-2}], block_count:9, sample_block:{x:16,y:64,z:-17}},
                    {message: "Blockformat nicht unterstützt.", hint: "Anderen Standplatz wählen."},
                ],
            };
            const preview = {can_create:true, selected_candidate_id:"east_2", candidate_positions:[candidate]};
            const markup = view.previewHtml(preview);
            const summary = markup.match(/<p class="mount-placement-reason" id="mountUncheckedReason">(.*?)<\/p>/s)[1];
            assert.ok(summary.includes("Chunk-Daten fehlen &lt;img"), "Reason must appear outside the details dialog");
            assert.ok(!markup.includes("<img src=x"));
            assert.ok(markup.includes('aria-describedby="mountUncheckedReason"'));
            assert.ok(markup.includes("Welt speichern und neu laden."));
            assert.ok(markup.includes("Weitere Gründe in den Prüfdetails: 1."));
            assert.ok(markup.includes("Warum ungeprüft?"));
            assert.ok(markup.includes("Chunk X 1 · Z -2"));
            assert.ok(markup.includes("Betroffene Blöcke: 9. Beispiel: X 16 · Y 64 · Z -17."));
            assert.ok(markup.includes("Blockformat nicht unterstützt."));
            const dialog = markup.split('<dialog')[1];
            assert.ok(!dialog.includes('Lade eine neue Vorschau'), "Spezifische Diagnose wird von pauschalem Rat überlagert");

            const footprint = {columns:[{block_x:15,block_z:8,center:true}], message:"Chunk-Daten fehlen <img src=x onerror=bad>"};
            const withGrid = view.previewHtml({...preview, candidate_positions:[{...candidate,chunk_probe:{footprint_check:footprint}}]});
            assert.ok(!withGrid.split('<dialog')[1].includes('class="mount-fp-caption"'), "Strukturierte Diagnose wird unter dem Raster wiederholt");

            // Rechecking successfully must remove the previous explanation.
            for (const verdict of [true, false]) {
                const checked = view.previewHtml({...preview, candidate_positions:[{...candidate,safe_to_place:verdict}]});
                assert.ok(!checked.includes('id="mountUncheckedReason"'));
                assert.ok(!checked.includes("Warum ungeprüft?"));
            }
            const fallback = view.previewHtml({...preview, candidate_positions:[{...candidate,placement_issues:[]} ]});
            assert.ok(fallback.includes('id="mountUncheckedReason">Legacy fallback</p>'));
            """
        )
    )


def test_pending_mount_card_shows_every_value_that_will_be_written() -> None:
    """A staged value the card omits looks like it was not applied."""

    run_node(
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
                horseProfile: { mode: "custom", health: 27, movement: 0.2, jump_strength: 0.7, temper: 12, color: 4, mark_variant: 3 },
            }]);
            assert.ok(horse.includes("Zähmfortschritt 12"), "Pferd zeigt den Zähmfortschritt nicht");
            assert.ok(horse.includes("Schwarz") && horse.includes("Weiße Punkte"), "Vorgemerktes Aussehen fehlt");
            """
        )
    )


def test_mount_icons_are_decorative_and_scale_to_the_requested_size() -> None:
    run_node(
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
