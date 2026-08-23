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


def test_frontend_save_controller_preserves_save_orchestration_contract() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");
            const code = fs.readFileSync("static/save_controller.js", "utf8");
            const context = { window: {}, console };
            vm.runInNewContext(code, context, { filename: "static/save_controller.js" });

            function makeController(overrides = {}) {
                const state = {
                    worldPath: "C:/World",
                    currentPlayerKey: "local_player",
                    isDirty: true,
                    writeBlockedValue: false,
                    guardResults: null,
                    guardCalls: 0,
                    currentWriteGate: { reason: "blocked" },
                    createFlags: { inventory: false, enderChest: false, effects: false, abilities: false },
                    payload: {
                        world_path: "C:/World",
                        player_key: "local_player",
                        session_id: "presence-1",
                        base_revision: "rev-1",
                        stats: {},
                        inventory: [{ slot: 0, name: "minecraft:stone", count: 1 }],
                    },
                    payloadHasChanges: true,
                    pendingMounts: [],
                    committedMounts: 0,
                    confirmResponses: [],
                    reviewResponse: true,
                    presenceResponse: true,
                    validation: { errors: 0 },
                    postResponses: [{
                        success: true,
                        backup_file: "backup.zip",
                        player_revision: "rev-2",
                        item_source_digests: { inventory: { 0: "a".repeat(64) }, ender_chest: {} },
                    }],
                    postSavePayloadOverride: null,
                    posts: [],
                    statuses: [],
                    toasts: [],
                    actions: [],
                    loading: [],
                    primaryDisabled: [],
                    reviewDisabled: [],
                    createdPayload: null,
                    revision: "",
                    reloadRequiredReason: "",
                    cleanCount: 0,
                    presenceUpdates: 0,
                    backupsLoaded: 0,
                    normalized: 0,
                    normalizedDigests: null,
                    flashed: 0,
                    writeControlsUpdated: 0,
                    renderedWriteGates: [],
                    ...overrides,
                };
                const controller = context.window.MCBESaveController.createSaveController({
                    applyCreatedTagState: payload => {
                        state.createdPayload = { ...payload };
                    },
                    buildChangeSummary: () => ({ total: 1 }),
                    buildSavePayload: () => state.payload,
                    finalizePendingMounts: (results, options = {}) => {
                        state.finalizeOptions = options;
                        if (state.finalizeThrows) {
                            throw new Error("finalizePendingMounts kaputt");
                        }
                        state.committedMounts += results.length;
                        state.pendingMounts = [];
                        return state.finalizeResult;
                    },
                    confirmPresenceConflict: async () => state.presenceResponse,
                    currentPlayerLabel: () => "Steve",
                    flashSaveButton: () => {
                        state.flashed += 1;
                    },
                    getCreateRequiresConfirmation: () => state.createFlags,
                    getCurrentPlayerKey: () => state.currentPlayerKey,
                    getCurrentWriteGate: () => state.currentWriteGate,
                    getIsDirty: () => state.isDirty,
                    getPendingMounts: () => state.pendingMounts,
                    getWorldPath: () => state.worldPath,
                    hideLoading: () => state.loading.push("hide"),
                    loadBackupsList: () => {
                        state.backupsLoaded += 1;
                    },
                    logStatus: (message, type, options) => state.statuses.push({ message, type, options }),
                    markReloadRequired: reason => {
                        state.reloadRequiredReason = reason;
                    },
                    markCleanState: () => {
                        state.cleanCount += 1;
                        state.isDirty = false;
                    },
                    normalizeOriginsToCurrentSavedState: digests => {
                        state.normalized += 1;
                        state.normalizedDigests = digests;
                    },
                    openSaveReview: async () => state.reviewResponse,
                    payloadContainsUserChanges: () => state.payloadHasChanges,
                    postSavePayload: async payload => {
                        state.posts.push({ ...payload });
                        if (state.postSavePayloadOverride) return await state.postSavePayloadOverride(payload);
                        return state.postResponses.shift();
                    },
                    recordAction: (message, type) => state.actions.push({ message, type }),
                    renderWriteGate: gate => state.renderedWriteGates.push(gate),
                    setPrimarySaveDisabled: disabled => state.primaryDisabled.push(disabled),
                    setReviewConfirmDisabled: disabled => state.reviewDisabled.push(disabled),
                    showConfirmDialog: async message => {
                        state.statuses.push({ message, type: "confirm" });
                        return state.confirmResponses.shift();
                    },
                    showLoading: message => state.loading.push(message),
                    showToast: (message, type, duration) => state.toasts.push({ message, type, duration }),
                    updateCurrentPlayerRevision: revision => {
                        state.revision = revision || state.revision;
                    },
                    updateWorldPresence: async () => {
                        state.presenceUpdates += 1;
                        if (state.presenceThrows) {
                            throw new Error("updateWorldPresence kaputt");
                        }
                    },
                    updateWriteControls: () => {
                        state.writeControlsUpdated += 1;
                    },
                    validateInventoryState: () => state.validation,
                    writeBlocked: () => state.writeBlockedValue,
                    guardWorldWriteAction: state.guardResults
                        ? () => {
                            state.guardCalls += 1;
                            return state.guardResults.shift() === true;
                        }
                        : null,
                });
                return { controller, state };
            }

            (async () => {
                {
                    const { controller, state } = makeController({ payloadHasChanges: false });
                    await controller.saveCurrentPlayer();
                    assert.strictEqual(state.posts.length, 0);
                    assert.strictEqual(state.cleanCount, 1);
                    assert.strictEqual(state.statuses.at(-1).type, "warning");
                }

                {
                    const { controller, state } = makeController({
                        postResponses: [{
                            success: false,
                            error: "Schreibprüfung blockiert",
                            cleanup_warning: "Zusätzliches Backup blieb zurück",
                        }],
                    });
                    await controller.saveCurrentPlayer({ skipReview: true });
                    assert.ok(state.toasts.some(entry => entry.type === "warning" && entry.message.includes("Zusätzliches Backup")));
                    assert.ok(state.toasts.some(entry => entry.type === "error" && entry.message.includes("Schreibprüfung blockiert")));
                    assert.strictEqual(state.statuses.at(-1).type, "error");
                    assert.ok(state.statuses.at(-1).message.includes("Zusätzliches Backup"));
                    assert.strictEqual(state.cleanCount, 0);
                    assert.strictEqual(state.isDirty, true);
                }

                {
                    const { controller, state } = makeController({
                        postResponses: [{
                            success: true,
                            backup_file: "workspace.zip",
                            player_revision: "rev-cleanup",
                            cleanup_warning: "Zusätzliches Backup blieb zurück",
                            item_source_digests: { inventory: {}, ender_chest: {} },
                        }],
                    });
                    await controller.saveCurrentPlayer({ skipReview: true });
                    assert.strictEqual(state.statuses.at(-1).type, "warning");
                    assert.ok(state.statuses.at(-1).message.includes("Änderungen gespeichert"));
                    assert.ok(state.statuses.at(-1).message.includes("Zusätzliches Backup blieb zurück"));
                }

                {
                    const { controller, state } = makeController({
                        payloadHasChanges: false,
                        pendingMounts: [{ id: "mount-1", mountLabel: "Pferd" }],
                        postResponses: [{ success: true, backup_file: "workspace.zip", mounts: [{ mount_type: "minecraft:horse" }] }],
                    });
                    await controller.saveCurrentPlayer({ skipReview: true });
                    assert.strictEqual(state.posts.length, 1);
                    assert.strictEqual(state.committedMounts, 1);
                    assert.strictEqual(state.cleanCount, 1);
                    assert.ok(state.toasts.at(-1).message.includes("1 Mount erzeugt"));
                }

                {
                    const { controller, state } = makeController({
                        pendingMounts: [{ id: "mount-1", mountLabel: "Pferd" }],
                        postResponses: [{
                            success: false,
                            write_committed: true,
                            validation_failed: true,
                            error: "Workspace geschrieben; Nachvalidierung fehlgeschlagen.",
                            backup_file: "workspace.zip",
                            player_revision: "rev-partial",
                            mounts: [{ mount_type: "minecraft:horse", post_create_validation: { ok: false } }],
                        }],
                    });
                    await controller.saveCurrentPlayer({ skipReview: true });
                    assert.strictEqual(state.posts.length, 1);
                    assert.strictEqual(state.committedMounts, 1);
                    assert.strictEqual(state.finalizeOptions.validationFailed, true);
                    assert.strictEqual(state.pendingMounts.length, 0);
                    assert.strictEqual(state.cleanCount, 1);
                    assert.strictEqual(state.revision, "rev-partial");
                    assert.strictEqual(state.normalized, 1);
                    assert.strictEqual(state.presenceUpdates, 1);
                    assert.strictEqual(state.backupsLoaded, 1);
                    assert.strictEqual(state.statuses.at(-1).type, "error");
                    assert.strictEqual(state.toasts.at(-1).type, "error");
                    assert.ok(state.toasts.at(-1).message.includes("Nachvalidierung fehlgeschlagen"));
                    assert.strictEqual(state.primaryDisabled.at(-1), true);
                }

                {
                    const { controller, state } = makeController({
                        createFlags: { inventory: true, enderChest: false, effects: false, abilities: false },
                        confirmResponses: [true],
                    });
                    await controller.saveCurrentPlayer({ skipReview: true });
                    assert.ok(state.loading.includes("Speichern läuft: Backup erstellen, Änderung schreiben, Datenbankverbindung schließen..."));
                    assert.ok(state.loading.includes("Speichern abschließen: Antwort prüfen und UI aktualisieren..."));
                    assert.ok(!state.loading.includes("1/3 Backup erstellen..."));
                    assert.ok(!state.loading.includes("2/3 Spieler speichern..."));
                    assert.strictEqual(state.posts.length, 1);
                    assert.strictEqual(state.posts[0].allow_create_inventory, true);
                    assert.strictEqual(state.createdPayload.allow_create_inventory, true);
                    assert.strictEqual(state.revision, "rev-2");
                    assert.strictEqual(state.cleanCount, 1);
                    assert.strictEqual(state.presenceUpdates, 1);
                    assert.strictEqual(state.normalizedDigests.inventory[0], "a".repeat(64));
                    const saveStatuses = state.statuses.filter(entry => entry.options?.key === "player-save");
                    assert.strictEqual(saveStatuses[0].type, "running");
                    assert.strictEqual(saveStatuses.at(-1).type, "success");
                }

                {
                    const noOpDigests = {
                        inventory: { 0: "b".repeat(64) },
                        ender_chest: {},
                    };
                    const { controller, state } = makeController({
                        postResponses: [{
                            success: true,
                            no_op: true,
                            backup_file: null,
                            player_revision: "rev-1",
                            item_source_digests: noOpDigests,
                        }],
                    });
                    await controller.saveCurrentPlayer({ skipReview: true });
                    assert.strictEqual(state.cleanCount, 1);
                    assert.strictEqual(state.normalized, 1);
                    assert.deepStrictEqual(state.normalizedDigests, noOpDigests);
                    assert.strictEqual(state.createdPayload, null);
                    assert.strictEqual(state.flashed, 0);
                }

                {
                    const { controller, state } = makeController({
                        createFlags: { inventory: false, enderChest: true, effects: true, abilities: true },
                        payload: {
                            world_path: "C:/World",
                            player_key: "local_player",
                            session_id: "presence-1",
                            base_revision: "rev-1",
                            stats: {},
                            ender_chest: [{ slot: 1, name: "minecraft:diamond", count: 1 }],
                            effects: [{ id: 1, amplifier: 0 }],
                            abilities: { mayfly: true },
                        },
                        confirmResponses: [true, true, true],
                    });
                    await controller.saveCurrentPlayer({ skipReview: true });
                    assert.strictEqual(state.posts.length, 1);
                    assert.strictEqual(state.statuses.filter(entry => entry.type === "confirm").length, 3);
                    assert.strictEqual(state.posts[0].allow_create_ender_chest, true);
                    assert.strictEqual(state.posts[0].allow_create_effects, true);
                    assert.strictEqual(state.posts[0].allow_create_abilities, true);
                }

                {
                    const { controller, state } = makeController({
                        createFlags: { inventory: true, enderChest: true, effects: true, abilities: true },
                        payload: {
                            world_path: "C:/World",
                            player_key: "local_player",
                            session_id: "presence-1",
                            base_revision: "rev-1",
                            stats: {},
                            inventory: [],
                            ender_chest: [],
                            effects: [],
                            abilities: { _opaque: false },
                        },
                        confirmResponses: [],
                    });
                    await controller.saveCurrentPlayer({ skipReview: true });
                    assert.strictEqual(state.posts.length, 1);
                    assert.strictEqual(state.statuses.filter(entry => entry.type === "confirm").length, 0);
                    assert.strictEqual(state.posts[0].allow_create_inventory, undefined);
                    assert.strictEqual(state.posts[0].allow_create_ender_chest, undefined);
                    assert.strictEqual(state.posts[0].allow_create_effects, undefined);
                    assert.strictEqual(state.posts[0].allow_create_abilities, undefined);
                }

                {
                    const { controller, state } = makeController({
                        createFlags: { inventory: true, enderChest: false, effects: false, abilities: false },
                        confirmResponses: [false],
                    });
                    await controller.saveCurrentPlayer({ skipReview: true });
                    assert.strictEqual(state.posts.length, 0);
                    assert.strictEqual(state.statuses.at(-1).type, "warning");
                }

                {
                    const { controller, state } = makeController({
                        postResponses: [
                            { success: false, presence_conflict: { sessions: [] } },
                            { success: true, backup_file: "backup.zip", player_revision: "rev-3" },
                        ],
                        presenceResponse: true,
                    });
                    await controller.saveCurrentPlayer({ skipReview: true });
                    assert.strictEqual(state.posts.length, 2);
                    assert.strictEqual(state.posts[0].confirm_presence_conflict, undefined);
                    assert.strictEqual(state.posts[1].confirm_presence_conflict, true);
                    assert.strictEqual(state.revision, "rev-3");
                }

                {
                    const { controller, state } = makeController({
                        postResponses: [{ success: false, presence_conflict: { sessions: [] } }],
                        presenceResponse: false,
                    });
                    await controller.saveCurrentPlayer({ skipReview: true });
                    assert.strictEqual(state.posts.length, 1);
                    assert.strictEqual(state.cleanCount, 0);
                    assert.strictEqual(state.isDirty, true);
                    assert.strictEqual(state.primaryDisabled.at(-1), false);
                }

                {
                    const { controller, state } = makeController({ writeBlockedValue: true });
                    await controller.saveCurrentPlayer({ skipReview: true });
                    assert.strictEqual(state.posts.length, 0);
                    assert.strictEqual(state.cleanCount, 0);
                    assert.strictEqual(state.statuses.at(-1).message, "blocked");
                    assert.strictEqual(state.statuses.at(-1).type, "error");
                    assert.strictEqual(state.statuses.at(-1).options.key, "player-save");
                    assert.deepStrictEqual(state.toasts.at(-1), { message: "blocked", type: "error", duration: 5000 });
                }

                {
                    const { controller, state } = makeController({ guardResults: [false, true] });
                    await controller.saveCurrentPlayer({ skipReview: false });
                    assert.strictEqual(state.posts.length, 0);
                    assert.strictEqual(state.guardCalls, 2);
                }

                {
                    const { controller, state } = makeController({
                        guardResults: [false, false, true],
                        postResponses: [{ success: false, presence_conflict: { sessions: [] } }],
                        presenceResponse: true,
                    });
                    await controller.saveCurrentPlayer({ skipReview: true });
                    assert.strictEqual(state.posts.length, 1);
                    assert.strictEqual(state.guardCalls, 3);
                    assert.strictEqual(state.cleanCount, 0);
                }

                {
                    const { controller, state } = makeController({
                        guardResults: [false, false, true],
                        confirmResponses: [true],
                        postResponses: [{
                            success: false,
                            write_gate: {
                                requires_unknown_server_confirmation: true,
                                reason: "Serverstatus unbekannt",
                                server_status: { status: "unknown" },
                            },
                        }],
                    });
                    await controller.saveCurrentPlayer({ skipReview: true });
                    assert.strictEqual(state.posts.length, 1);
                    assert.strictEqual(state.guardCalls, 3);
                    assert.strictEqual(state.cleanCount, 0);
                }

                {
                    let resolveSave;
                    const response = new Promise(resolve => { resolveSave = resolve; });
                    const { controller, state } = makeController({
                        postSavePayloadOverride: async () => response,
                    });
                    const saving = controller.saveCurrentPlayer({ skipReview: true });
                    await Promise.resolve();
                    state.currentPlayerKey = "other_player";
                    resolveSave({ success: true, backup_file: "backup.zip", player_revision: "rev-stale" });
                    await saving;
                    assert.strictEqual(state.cleanCount, 0);
                    assert.strictEqual(state.revision, "");
                    assert.strictEqual(state.normalized, 0);
                    assert.ok(state.toasts.some(entry => entry.type === "warning" && entry.message.includes("aktuelle Ansicht")));
                }

                {
                    let resolveSave;
                    const response = new Promise(resolve => { resolveSave = resolve; });
                    const { controller, state } = makeController({
                        postSavePayloadOverride: async () => response,
                    });
                    const saving = controller.saveCurrentPlayer({ skipReview: true });
                    await Promise.resolve();
                    state.currentPlayerKey = "other_player";
                    resolveSave({ success: false, error: "Schreibprüfung abgelehnt" });
                    await saving;
                    assert.strictEqual(state.statuses[0].type, "running");
                    assert.strictEqual(state.statuses.at(-1).type, "error");
                    assert.ok(state.statuses.at(-1).message.includes("Schreibprüfung abgelehnt"));
                    assert.ok(!state.statuses.some((entry, index) => index === state.statuses.length - 1 && entry.type === "running"));
                }

                {
                    // Committed-but-invalid response where finalizePendingMounts throws
                    // (e.g. mismatched mount count). The commit is confirmed, so the UI
                    // must stay non-repeatable: clean state applied, button not re-enabled.
                    const { controller, state } = makeController({
                        finalizeThrows: true,
                        pendingMounts: [{ id: "mount-1", mountLabel: "Pferd" }],
                        postResponses: [{
                            success: false,
                            write_committed: true,
                            validation_failed: true,
                            error: "Workspace geschrieben; Nachvalidierung fehlgeschlagen.",
                            backup_file: "workspace.zip",
                            player_revision: "rev-partial",
                            mounts: [{ mount_type: "minecraft:horse", post_create_validation: { ok: false } }],
                        }],
                    });
                    await controller.saveCurrentPlayer({ skipReview: true });
                    assert.strictEqual(state.cleanCount, 1);
                    assert.strictEqual(state.revision, "rev-partial");
                    assert.ok(state.reloadRequiredReason.includes("Nachvalidierung fehlgeschlagen"));
                    assert.ok(!state.primaryDisabled.includes(false));
                    assert.strictEqual(state.primaryDisabled.at(-1), true);
                }

                {
                    // A committed write where a later post-processing step throws must
                    // not re-enable the save button via the generic catch.
                    const { controller, state } = makeController({
                        presenceThrows: true,
                        postResponses: [{ success: true, backup_file: "backup.zip", player_revision: "rev-9" }],
                    });
                    await controller.saveCurrentPlayer({ skipReview: true });
                    assert.strictEqual(state.cleanCount, 1);
                    assert.ok(!state.primaryDisabled.includes(false));
                    assert.ok(state.toasts.some(entry => entry.type === "error" && entry.message.includes("Nicht erneut speichern")));
                }

                {
                    // A successful server no-op did not commit anything. If the
                    // following presence refresh fails, the generic pre-commit error
                    // path must remain active instead of forcing a reload lockout.
                    const { controller, state } = makeController({
                        presenceThrows: true,
                        postResponses: [{
                            success: true,
                            no_op: true,
                            message: "Keine Änderungen erkannt. Es wurde nichts geschrieben.",
                            player_revision: "rev-1",
                        }],
                    });
                    await controller.saveCurrentPlayer({ skipReview: true });
                    assert.strictEqual(state.cleanCount, 1);
                    assert.strictEqual(state.reloadRequiredReason, "");
                    assert.ok(state.primaryDisabled.includes(false));
                    assert.ok(state.toasts.some(entry => entry.type === "error" && entry.message.includes("updateWorldPresence kaputt")));
                    assert.ok(!state.toasts.some(entry => entry.message.includes("Nicht erneut speichern")));
                }

                {
                    // The mount controller has detected an incomplete response after a
                    // successful atomic commit. The save controller must honor the
                    // structured reload requirement and must not continue with its
                    // normal success UI.
                    const { controller, state } = makeController({
                        pendingMounts: [
                            { id: "mount-1", mountLabel: "Pferd 1" },
                            { id: "mount-2", mountLabel: "Pferd 2" },
                        ],
                        finalizeResult: {
                            complete: false,
                            reloadRequired: true,
                            committedCount: 1,
                            expected: 2,
                            reason: "count_mismatch",
                        },
                        postResponses: [{
                            success: true,
                            backup_file: "workspace.zip",
                            player_revision: "rev-incomplete-mounts",
                            mounts: [{ mount_type: "minecraft:horse", post_create_validation: { ok: true } }],
                        }],
                    });
                    await controller.saveCurrentPlayer({ skipReview: true });
                    assert.strictEqual(state.cleanCount, 1);
                    assert.strictEqual(state.revision, "rev-incomplete-mounts");
                    assert.ok(state.reloadRequiredReason.includes("Mount-Antwort"));
                    assert.strictEqual(state.flashed, 0);
                    assert.ok(!state.toasts.some(entry => entry.type === "success"));
                    assert.ok(state.toasts.some(entry => (
                        entry.type === "error"
                        && entry.message.includes("Mount-Antwort")
                        && entry.message.includes("Welt neu laden")
                    )));
                    assert.ok(!state.statuses.some(entry => entry.type === "success" && entry.message.startsWith("Änderungen gespeichert")));
                    assert.ok(state.actions.some(entry => entry.type === "error" && entry.message.includes("Neuladen erforderlich")));
                    assert.ok(!state.primaryDisabled.includes(false));
                }

                {
                    // Even an unexpected exception while finalizing optional mount
                    // details is a post-commit/reload-required state, never a success.
                    const { controller, state } = makeController({
                        finalizeThrows: true,
                        pendingMounts: [{ id: "mount-1", mountLabel: "Pferd" }],
                        postResponses: [{
                            success: true,
                            backup_file: "workspace.zip",
                            player_revision: "rev-finalize-error",
                            mounts: [{ mount_type: "minecraft:horse", post_create_validation: { ok: true } }],
                        }],
                    });
                    await controller.saveCurrentPlayer({ skipReview: true });
                    assert.strictEqual(state.cleanCount, 1);
                    assert.ok(state.reloadRequiredReason.includes("Mount-Nachbearbeitung"));
                    assert.strictEqual(state.flashed, 0);
                    assert.ok(!state.toasts.some(entry => entry.type === "success"));
                    assert.ok(state.toasts.some(entry => entry.type === "error" && entry.message.includes("Mount-Nachbearbeitung")));
                    assert.ok(!state.primaryDisabled.includes(false));
                }

                {
                    // Ohne auswertbare Antwort ist bei einem Mount-Batch unbekannt,
                    // ob der Server bereits committed hat. Der Batch darf deshalb
                    // nicht erneut angeboten werden.
                    const { controller, state } = makeController({
                        payloadHasChanges: false,
                        pendingMounts: [{ id: "mount-1", mountLabel: "Pferd" }],
                        postSavePayloadOverride: async () => {
                            throw new Error("Verbindung abgebrochen");
                        },
                    });
                    await controller.saveCurrentPlayer({ skipReview: true });
                    assert.ok(state.reloadRequiredReason.includes("unbekannt"));
                    assert.ok(state.toasts.some(entry => entry.type === "error" && entry.message.includes("Nicht erneut speichern")));
                    assert.ok(!state.primaryDisabled.includes(false));
                }

                {
                    let resolvePost;
                    const deferredPost = new Promise(resolve => {
                        resolvePost = resolve;
                    });
                    const { controller, state } = makeController({
                        postSavePayloadOverride: async () => await deferredPost,
                    });

                    const firstSave = controller.saveCurrentPlayer({ skipReview: true });
                    const secondSave = controller.saveCurrentPlayer({ skipReview: true });
                    assert.strictEqual(firstSave, secondSave, "parallele Aufrufe müssen denselben Speicherversuch teilen");
                    await Promise.resolve();
                    await Promise.resolve();
                    assert.strictEqual(state.posts.length, 1);

                    resolvePost({
                        success: true,
                        backup_file: "single-save.zip",
                        player_revision: "rev-single",
                        item_source_digests: { inventory: {}, ender_chest: {} },
                    });
                    await Promise.all([firstSave, secondSave]);
                    assert.strictEqual(state.posts.length, 1, "es darf nur ein Schreibrequest entstehen");
                }

                {
                    const { controller, state } = makeController({
                        payloadHasChanges: false,
                        pendingMounts: [{ id: "mount-foreign", worldPath: "C:/World", playerKey: "other_player" }],
                    });
                    await controller.saveCurrentPlayer({ skipReview: true });
                    assert.strictEqual(state.posts.length, 0);
                    assert.ok(state.reloadRequiredReason.includes("anderen Spieler"));
                    assert.ok(state.toasts.some(entry => entry.type === "error" && entry.message.includes("blockiert")));
                }
            })().catch(error => {
                console.error(error);
                process.exit(1);
            });
            """
        )
    )


def test_configured_save_controller_uses_atomic_workspace_endpoint_for_mounts() -> None:
    source = (ROOT / "static" / "save_controller.js").read_text(encoding="utf-8")

    assert 'pendingMounts.length ? "/api/workspace/save" : "/api/player/save"' in source
    assert "requestPayload.mounts = pendingMounts.map" in source
    assert "finalizeCommittedMountResults(mountResults)" in source
    assert "finalizeCommittedMountResults(mountResults, { validationFailed: true })" in source
    assert "mountFinalization.reloadRequired === true" in source
    assert "markReloadRequired" in source


def test_app_wiring_forwards_finalize_options_to_mount_controller() -> None:
    # Regression for the real app.js wiring: the second (options) argument must
    # reach the mount controller, not be dropped. app.js cannot be loaded in
    # isolation, so extract the wiring arrow and execute it against a spy.
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const code = fs.readFileSync("static/app.js", "utf8");
            const match = code.match(
                /finalizePendingMounts:\s*(\([^)]*\)\s*=>\s*getMountController\(\)\.finalizePendingMounts\([^)]*\))/
            );
            assert.ok(match, "finalizePendingMounts wiring not found in app.js");

            const calls = [];
            const getMountController = () => ({
                finalizePendingMounts: (...args) => calls.push(args),
            });
            const wired = eval(match[1]);
            wired([{ mount_type: "minecraft:horse" }], { validationFailed: true });

            assert.strictEqual(calls.length, 1);
            assert.deepStrictEqual(calls[0][0], [{ mount_type: "minecraft:horse" }]);
            assert.deepStrictEqual(
                calls[0][1],
                { validationFailed: true },
                "options argument must be forwarded to the mount controller"
            );
            assert.ok(
                code.includes("markReloadRequired: reason => { currentPlayerStaleReason = reason; }"),
                "reload-required state must be persisted through the app write gate"
            );
            """
        )
    )


def test_app_wiring_forwards_item_source_digests_to_origin_controller() -> None:
    _run_node(
        textwrap.dedent(
            r"""
            const assert = require("assert");
            const fs = require("fs");
            const code = fs.readFileSync("static/app.js", "utf8");
            const match = code.match(new RegExp(
                "function normalizeOriginsToCurrentSavedState\\([^)]*\\)\\s*\\{\\s*" +
                "return inventoryOriginController\\.normalizeOriginsToCurrentSavedState\\([^;]*\\);\\s*\\}"
            ));
            assert.ok(match, "normalizeOriginsToCurrentSavedState wiring not found in app.js");

            const calls = [];
            const inventoryOriginController = {
                normalizeOriginsToCurrentSavedState: (...args) => calls.push(args),
            };
            const wired = eval(`(${match[0]})`);
            const digests = {
                inventory: { 8: "d".repeat(64) },
                ender_chest: {},
            };
            wired(digests);

            assert.strictEqual(calls.length, 1);
            assert.strictEqual(calls[0].length, 1);
            assert.strictEqual(calls[0][0], digests);
            """
        )
    )
