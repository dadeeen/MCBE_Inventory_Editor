import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const load = (context, name) => vm.runInNewContext(readFileSync(`static/${name}.js`, "utf8"), context, { filename: name });
const plain = value => JSON.parse(JSON.stringify(value));
const context = { window: {}, AbortController, Date, setTimeout, clearTimeout };
load(context, "villager_model");
load(context, "villager_map");
load(context, "villager_controller");
const { fitCamera, zoomCamera } = context.window.MCBEVillagerMap;
const position = (x, z) => ({ position: { x, y: 64, z }, dimension: 0 });
const worldAt = (camera, anchor) => ({ x: camera.x + (anchor.x - .5) * camera.span, z: camera.z + (anchor.z - .5) * camera.span });
const close = (actual, expected) => assert.ok(Math.abs(actual - expected) <= 1e-12 * Math.max(1, Math.abs(expected)), `${actual} differs from ${expected}`);

test("camera fitting provides useful finite views for empty and coincident positions", () => {
    const empty = fitCamera([]);
    assert.ok(Object.values(empty).every(Number.isFinite));
    assert.ok(empty.span >= 4);
    const single = fitCamera([position(-120, 84), position(-120, 84)]);
    assert.equal(single.x, -120);
    assert.equal(single.z, 84);
    assert.ok(single.span >= 4);
});

test("camera fits every point with padding and uses the same scale on both axes", () => {
    const rows = [position(-100, 25), position(300, 75), position(150, -25)];
    const camera = fitCamera(rows);
    assert.equal(camera.x, 100);
    assert.equal(camera.z, 25);
    for (const { position: point } of rows) for (const axis of ["x", "z"]) {
        const screen = .5 + (point[axis] - camera[axis]) / camera.span;
        assert.ok(screen >= .079999 && screen <= .920001);
    }
    const swapped = fitCamera(rows.map(({ position: point }) => position(point.z, point.x)));
    assert.equal(swapped.span, camera.span);
    assert.equal(swapped.x, camera.z);
    assert.equal(swapped.z, camera.x);
});

test("opposite supported coordinate extremes remain finite and fit in view", () => {
    const extent = 2 ** 35;
    const camera = fitCamera([position(-extent, extent), position(extent, -extent)]);
    assert.ok(Object.values(camera).every(Number.isFinite));
    assert.equal(camera.x, 0);
    assert.equal(camera.z, 0);
    assert.ok(camera.span > extent * 2);
    assert.ok(camera.span < 2 ** 39);
});

for (const factor of [2, .25, 1e300, 1e-300]) {
    test(`zoom preserves the world coordinate under the pointer, including clamps (factor ${factor})`, () => {
        const original = { x: -1500, z: 700, span: 400 };
        for (const anchor of [{ x: .5, z: .5 }, { x: 0, z: 1 }, { x: .84, z: .17 }]) {
            const before = worldAt(original, anchor);
            const zoomed = zoomCamera(original, factor, anchor, 6400);
            const after = worldAt(zoomed, anchor);
            close(after.x, before.x); close(after.z, before.z);
            assert.ok(zoomed.span >= 4 && zoomed.span <= 6400);
            assert.ok(Object.values(zoomed).every(Number.isFinite));
        }
        assert.deepEqual(original, { x: -1500, z: 700, span: 400 });
    });
}

test("centered zoom reverses without drift and repeated zoom respects both limits", () => {
    const original = { x: 2 ** 35, z: -(2 ** 35), span: 64 };
    const zoomed = zoomCamera(original, 1.5);
    const restored = zoomCamera(zoomed, 1 / 1.5);
    close(restored.x, original.x); close(restored.z, original.z); close(restored.span, original.span);
    let smallest = original, largest = original;
    for (let i = 0; i < 100; i += 1) {
        smallest = zoomCamera(smallest, 2, undefined, 1024);
        largest = zoomCamera(largest, .5, undefined, 1024);
    }
    assert.equal(smallest.span, 4);
    assert.equal(largest.span, 1024);
});

function controllerHarness() {
    const world = { path: "world-A", selected: "player-A", markers: [{ player_key: "player-A", label: "A", ...position(10, 20) }] };
    const response = () => ({ success: true, villagers: [], world_revision: "revision-A", map_players: plain(world.markers) });
    const api = { scan: async () => response() };
    const controller = context.window.MCBEVillagerController.createVillagerController({
        doc: {}, api,
        view: { element: () => null, render: () => ({ page: 1 }), renderDetail() {} },
        getWorldPath: () => world.path, getSelectedPlayerKey: () => world.selected,
    });
    return { world, api, response, controller };
}

test("each successful scan replaces map positions and absent marker data never reuses older positions", async () => {
    const h = controllerHarness();
    assert.equal(await h.controller.scan(), true);
    assert.deepEqual(plain(h.controller.getState().mapPlayers), h.world.markers);
    h.world.markers = [{ player_key: "player-A", label: "A", ...position(100, 200) }];
    assert.equal(await h.controller.scan(), true);
    assert.deepEqual(plain(h.controller.getState().mapPlayers), h.world.markers);
    h.api.scan = async () => ({ success: true, villagers: [], world_revision: "revision-B" });
    assert.equal(await h.controller.scan(), true);
    assert.deepEqual(plain(h.controller.getState().mapPlayers), []);
});

test("world changes clear saved map markers and ignore a late response from the previous world", async () => {
    const h = controllerHarness();
    await h.controller.scan();
    let finish;
    let signal;
    h.api.scan = async (_world, options) => {
        signal = options.signal;
        return new Promise(resolve => { finish = resolve; });
    };
    const pending = h.controller.scan();
    const oldResponse = h.response();
    h.world.path = "world-B";
    h.controller.updateContext();
    assert.equal(signal.aborted, true);
    assert.deepEqual(plain(h.controller.getState().mapPlayers), []);
    finish(oldResponse);
    assert.equal(await pending, false);
    assert.equal(h.controller.getState().worldPath, "world-B");
    assert.deepEqual(plain(h.controller.getState().mapPlayers), []);
});

test("player selection changes only the selected key and retains saved snapshot positions", async () => {
    const h = controllerHarness();
    await h.controller.scan();
    assert.equal(h.controller.getState().selectedPlayerKey, "player-A");
    h.world.selected = "player-B";
    h.controller.updateContext();
    assert.equal(h.controller.getState().selectedPlayerKey, "player-B");
    assert.deepEqual(plain(h.controller.getState().mapPlayers), h.world.markers);
});
