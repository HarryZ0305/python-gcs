import test from "node:test";
import assert from "node:assert/strict";
import {
  createModel,
  advance,
  arm,
  takeoff,
  hold,
  land,
  returnHome,
  startMission,
  survey,
  exportPlan,
  importPlan,
  DEFAULT_ROUTE,
} from "../assets/demo-model.js";

function tick(model, seconds) {
  for (let i = 0; i < seconds * 5; i++) advance(model, 0.2);
}

test("disarmed aircraft stays on the ground", () => {
  const model = createModel();
  tick(model, 60);
  assert.deepEqual(
    [model.x, model.y, model.alt, model.armed],
    [0, 0, 0, false],
  );
});
test("takeoff holds the requested altitude and airborne disarm is rejected", () => {
  const model = createModel();
  takeoff(model, 18);
  tick(model, 10);
  assert.equal(model.stage, "hold");
  assert.equal(model.alt, 18);
  assert.throws(() => arm(model), /Land/);
  tick(model, 10);
  assert.equal(model.alt, 18);
});
test("Hold interrupts mission motion and landing disarms", () => {
  const model = createModel();
  startMission(model, DEFAULT_ROUTE);
  tick(model, 12);
  hold(model);
  const position = [model.x, model.y, model.alt];
  tick(model, 5);
  assert.deepEqual([model.x, model.y, model.alt], position);
  land(model);
  tick(model, 15);
  assert.equal(model.alt, 0);
  assert.equal(model.armed, false);
});
test("Return flies home then lands", () => {
  const model = createModel();
  startMission(model, DEFAULT_ROUTE);
  tick(model, 15);
  assert.ok(model.x > 20);
  returnHome(model);
  tick(model, 45);
  assert.ok(Math.hypot(model.x, model.y) < 0.5);
  assert.equal(model.armed, false);
  assert.equal(model.alt, 0);
});
test("complete sample route ends with touchdown", () => {
  const model = createModel();
  startMission(model, DEFAULT_ROUTE);
  tick(model, 100);
  assert.equal(model.routeIndex, DEFAULT_ROUTE.length);
  assert.equal(model.stage, "ground");
  assert.equal(model.armed, false);
});
test("mission reaches waypoint altitude before advancing", () => {
  const model = createModel();
  startMission(model, [
    { x: 0, y: 0, alt: 2 },
    { x: 0, y: 0, alt: 50 },
  ]);
  tick(model, 3);
  assert.equal(model.routeIndex, 1);
  assert.equal(model.stage, "route");
  tick(model, 20);
  assert.equal(model.stage, "land");
});
test("invalid mission preserves existing flight state", () => {
  const model = createModel();
  startMission(model, DEFAULT_ROUTE);
  tick(model, 2);
  const before = structuredClone(model);
  assert.throws(() => startMission(model, [{ x: NaN, y: 0, alt: 20 }]));
  assert.deepEqual(model, before);
});
test("survey alternates direction and rejects excessive or invalid grids", () => {
  const route = survey(80, 80, 20, 20);
  assert.equal(route.length, 10);
  assert.deepEqual(
    route.slice(0, 4).map((p) => p.x),
    [0, 80, 80, 0],
  );
  assert.throws(() => survey(500, 500, 5, 20), /200 waypoints/);
  assert.throws(() => survey(80, 80, 0, 20));
});
test("supported plan round trip preserves route within millimeter tolerance", () => {
  const actual = importPlan(exportPlan(DEFAULT_ROUTE));
  actual.forEach((p, i) => {
    assert.ok(Math.abs(p.x - DEFAULT_ROUTE[i].x) < 0.001);
    assert.ok(Math.abs(p.y - DEFAULT_ROUTE[i].y) < 0.001);
    assert.equal(p.alt, DEFAULT_ROUTE[i].alt);
  });
});
test("import rejects semantics the model cannot reproduce", () => {
  const mutations = [
    (p) => {
      p.mission.items[0].params[6] = 40;
    },
    (p) => {
      p.mission.items.at(-1).params[4] += 0.001;
    },
    (p) => {
      p.mission.items[1].params[3] = 0;
    },
    (p) => {
      p.mission.items[1].frame = 0;
    },
    (p) => {
      p.mission.items[1].autoContinue = false;
    },
    (p) => {
      p.geoFence.polygons.push({});
    },
    (p) => {
      p.mission.plannedHomePosition = [];
    },
    (p) => {
      p.mission.items[0].command = 16;
    },
  ];
  mutations.forEach((mutate) => {
    const plan = exportPlan(DEFAULT_ROUTE);
    mutate(plan);
    assert.throws(() => importPlan(plan));
  });
});
