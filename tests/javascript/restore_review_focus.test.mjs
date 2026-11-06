import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

for (const earlyFocus of ["outside", "input", "confirm", "cancel", "close"]) {
  test(`restore autofocus preserves an early ${earlyFocus} focus choice`, async () => {
    const document = new EventTarget();
    const controls = Object.fromEntries(["outside", "input", "confirm", "cancel", "close"].map(name => {
      const control = new EventTarget();
      control.focus = () => { document.activeElement = control; };
      return [name, control];
    }));
    controls.outside.focus();
    const overlay = new EventTarget();
    overlay.style = {};
    overlay.contains = element => Object.entries(controls).some(([name, control]) => name !== "outside" && element === control);
    const timers = new Map();
    const context = {
      window: {}, document,
      setTimeout(callback) { timers.set(1, callback); return 1; },
      clearTimeout(id) { timers.delete(id); },
    };
    vm.runInNewContext(fs.readFileSync("static/backup_restore_logic.js", "utf8"), context);
    const controller = context.window.MCBEBackupRestoreLogic.createBackupRestoreController({
      elements: {
        overlay, confirmInput: controls.input, confirmButton: controls.confirm,
        cancelButton: controls.cancel, closeButton: controls.close,
      },
    });
    const result = controller.openRestoreReview({}, "synthetic.zip");
    controls.input.value = "WIEDERHERSTELLEN";
    controls.input.dispatchEvent(new Event("input"));
    controls[earlyFocus].focus();
    assert.equal(timers.size, 1);
    timers.get(1)();
    assert.equal(document.activeElement, controls[earlyFocus === "outside" ? "input" : earlyFocus]);
    controls.cancel.dispatchEvent(new Event("click"));
    assert.equal(await result, false);
    assert.equal(timers.size, 0);
  });
}
