import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { test } from "node:test";

const source = fs.readFileSync("static/world_status_view.js", "utf8");
const template = fs.readFileSync("templates/index.html", "utf8");
const css = fs.readFileSync("static/layout_variants.css", "utf8");
const english = JSON.parse(fs.readFileSync("static/i18n/en.json", "utf8"));

function viewForLanguage(language) {
  const t = (text) => language === "en" ? english[text] ?? text : text;
  const context = { window: { t } };
  vm.runInNewContext(source, context, { filename: "static/world_status_view.js" });
  return context.window.MCBEWorldStatusView;
}

function nodes() {
  const bar = {
    style: { display: "none" },
    classes: new Set(["is-empty"]),
  };
  bar.classList = {
    toggle(value, enabled) {
      if (enabled) bar.classes.add(value);
      else bar.classes.delete(value);
    },
  };
  return {
    bar,
    kicker: { textContent: "" },
    name: { textContent: "" },
    path: { textContent: "", title: "" },
    safetyNote: { textContent: "old", style: { display: "inline-flex" } },
    loadButton: { disabled: false },
    copyButton: { disabled: false },
    openButton: { disabled: false, title: "" },
  };
}

test("Studio has a localized, non-interactive selection placeholder from first render", () => {
  assert.match(template, /class="selected-world-bar is-empty" id="selectedWorldBar"/);
  assert.match(template, /id="selectedWorldName"[^>]*>\{\{ t\("Keine Welt ausgewählt"\) \}\}/);
  assert.match(template, /id="selectedWorldPath"[^>]*>\{\{ t\("Wähle unten eine Welt aus, um sie zu laden\."\) \}\}/);
  assert.match(template, /id="btnLoad"[^>]*disabled/);
  assert.match(template, /id="btnCopySelectedWorldPath"[^>]*disabled/);
  assert.match(template, /id="btnOpenSelectedWorld"[^>]*disabled/);
  assert.match(css, /:root\[data-layout="studio"\] body\[data-workflow-view="world"\] #selectedWorldBar \{\s*display: flex !important;/);
  assert.doesNotMatch(css, /:root\[data-layout="focus"\] body\[data-workflow-view="world"\] #selectedWorldBar \{\s*display: flex !important;/);
});

for (const language of ["de", "en"]) {
  test(`World selection updates content, state and actions without replacing nodes (${language})`, () => {
    const view = viewForLanguage(language);
    const ui = nodes();
    const empty = view.selectedWorldBarModel({selectedWorld: null});
    assert.equal(empty.visible, false);
    assert.equal(empty.loadDisabled, true);
    assert.equal(empty.copyDisabled, true);
    assert.equal(empty.openDisabled, true);
    assert.equal(empty.name, language === "de" ? "Keine Welt ausgewählt" : "No world selected");
    assert.equal(empty.pathText, language === "de" ? "Wähle unten eine Welt aus, um sie zu laden." : "Select a world below to load it.");
    assert.equal(view.applySelectedWorldBarModel(ui, empty), false);
    assert.equal(ui.bar.style.display, "none"); // Classic/Focus stay hidden
    assert.equal(ui.bar.classes.has("is-empty"), true); // Studio uses the CSS override
    assert.equal(ui.loadButton.disabled, true);
    assert.equal(ui.copyButton.disabled, true);
    assert.equal(ui.openButton.disabled, true);
    assert.equal(ui.kicker.textContent, language === "de" ? "Welt auswählen" : "Choose world");
    const selected = view.selectedWorldBarModel({selectedWorld: {name: "Survival", folder: "world123", path: "C:/world123"}});
    assert.equal(view.applySelectedWorldBarModel(ui, selected), true);
    assert.equal(ui.bar.style.display, "flex");
    assert.equal(ui.bar.classes.has("is-empty"), false);
    assert.equal(ui.loadButton.disabled, false);
    assert.equal(ui.copyButton.disabled, false);
    assert.equal(ui.openButton.disabled, false);
    assert.equal(ui.name.textContent, "Survival");
    assert.equal(ui.path.textContent, (language === "de" ? "Suchergebnis" : "Search result") + " · world123");
    assert.equal(ui.kicker.textContent, language === "de" ? "Ausgewählt" : "Selected");
    const docker = view.selectedWorldBarModel({selectedWorld: {name: "Survival", path: "/srv/world123"}, isDocker: true});
    view.applySelectedWorldBarModel(ui, docker);
    assert.equal(ui.loadButton.disabled, false);
    assert.equal(ui.openButton.disabled, true);
    view.applySelectedWorldBarModel(ui, empty);
    assert.equal(ui.bar.classes.has("is-empty"), true);
    assert.equal(ui.loadButton.disabled, true);
    assert.equal(ui.copyButton.disabled, true);
    assert.equal(ui.openButton.disabled, true);
    assert.equal(ui.name.textContent, empty.name);
    assert.equal(ui.safetyNote.textContent, "");
  });
}
