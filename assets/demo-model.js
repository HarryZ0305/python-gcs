export const HOME = [47.3977, 8.5455];
export const DEFAULT_ROUTE = [
  { x: 60, y: 0, alt: 20 },
  { x: 60, y: 60, alt: 20 },
  { x: 0, y: 60, alt: 20 },
  { x: 0, y: 0, alt: 20 },
];
export const bounded = (n, min, max) => Math.max(min, Math.min(max, n));
export function validatePoints(points) {
  if (!Array.isArray(points) || !points.length || points.length > 200)
    throw Error("Use between 1 and 200 waypoints.");
  return points.map((p) => {
    const q = { x: Number(p.x), y: Number(p.y), alt: Number(p.alt) };
    if (
      !Object.values(q).every(Number.isFinite) ||
      Math.abs(q.x) > 2000 ||
      Math.abs(q.y) > 2000 ||
      q.alt < 2 ||
      q.alt > 80
    )
      throw Error(
        "Demo waypoints must be within 2 km, with altitude between 2 and 80 m.",
      );
    return q;
  });
}
export function createModel() {
  return {
    time: 0,
    flightTime: 0,
    armed: false,
    x: 0,
    y: 0,
    alt: 0,
    speed: 0,
    climb: 0,
    heading: 0,
    roll: 0,
    pitch: 0,
    battery: 100,
    mode: "Ground",
    stage: "ground",
    targetAltitude: 20,
    cruise: 5,
    route: [],
    routeIndex: 0,
    next: "hold",
    trail: [],
  };
}
export function takeoff(s, alt = 20) {
  if (s.alt > 0.8) throw Error("The demo aircraft is already airborne.");
  if (!Number.isFinite(Number(alt))) throw Error("Enter a valid altitude.");
  s.targetAltitude = bounded(Number(alt), 2, 80);
  s.armed = true;
  s.stage = "takeoff";
  s.mode = "Takeoff";
  s.next = "hold";
}
export function startMission(s, points) {
  const route = validatePoints(points);
  s.route = route;
  s.routeIndex = 0;
  s.targetAltitude = route[0].alt;
  s.armed = true;
  s.stage = "takeoff";
  s.mode = "Mission";
  s.next = "route";
}
export function hold(s) {
  s.stage = s.armed ? "hold" : "ground";
  s.mode = s.armed ? "Hold" : "Ground";
  s.speed = s.climb = s.roll = s.pitch = 0;
  s.targetAltitude = s.alt;
}
export function land(s) {
  if (!s.armed) return;
  s.stage = "land";
  s.mode = "Land";
  s.speed = 0;
}
export function returnHome(s) {
  if (!s.armed) return;
  s.stage = "return";
  s.mode = "Return";
  s.targetAltitude = Math.max(12, s.alt);
}
export function arm(s) {
  if (s.armed) {
    if (s.alt > 0.8) throw Error("Land the demo aircraft before disarming.");
    s.armed = false;
    s.stage = "ground";
    s.mode = "Ground";
  } else {
    s.armed = true;
    s.stage = "hold";
    s.mode = "Armed";
  }
}
export function cutoff(s) {
  s.armed = false;
  s.stage = "ground";
  s.mode = "Emergency stop";
  s.alt = s.speed = s.climb = s.roll = s.pitch = 0;
}
function vertical(s, target, dt, rate = 3) {
  const old = s.alt;
  s.alt += bounded(target - s.alt, -rate * dt, rate * dt);
  s.alt = Math.max(0, s.alt);
  s.climb = (s.alt - old) / dt;
}
function travel(s, target, dt) {
  const dx = target.x - s.x,
    dy = target.y - s.y,
    dist = Math.hypot(dx, dy),
    step = Math.min(dist, s.cruise * dt);
  if (dist > 0.01) {
    s.x += (dx / dist) * step;
    s.y += (dy / dist) * step;
    s.heading = ((Math.atan2(dx, dy) * 180) / Math.PI + 360) % 360;
  }
  s.speed = step / dt;
  s.pitch = s.speed > 0 ? -4 : 0;
  s.roll = s.speed > 0 ? 3 * Math.sin(s.time) : 0;
  return dist < 0.5;
}
export function advance(s, seconds) {
  const dt = bounded(seconds, 0.001, 0.25);
  s.time += dt;
  if (!s.armed) {
    s.speed = s.climb = 0;
    return s;
  }
  s.flightTime += dt;
  s.battery = Math.max(5, 100 - s.flightTime / 120);
  s.speed = s.climb = 0;
  if (s.stage === "takeoff") {
    vertical(s, s.targetAltitude, dt);
    if (Math.abs(s.alt - s.targetAltitude) < 0.05) {
      s.stage = s.next;
      s.mode = s.next === "route" ? "Mission" : "Hold";
    }
  } else if (s.stage === "route") {
    const target = s.route[s.routeIndex];
    if (!target) {
      land(s);
      return s;
    }
    vertical(s, target.alt, dt);
    if (travel(s, target, dt) && Math.abs(s.alt - target.alt) < 0.05) {
      s.routeIndex++;
      if (s.routeIndex >= s.route.length) land(s);
    }
  } else if (s.stage === "return") {
    vertical(s, s.targetAltitude, dt);
    if (travel(s, { x: 0, y: 0 }, dt)) land(s);
  } else if (s.stage === "land") {
    vertical(s, 0, dt, 2);
    s.roll = s.pitch = 0;
    if (s.alt < 0.02) {
      s.alt = 0;
      s.armed = false;
      s.stage = "ground";
      s.mode = "Ground";
      s.climb = 0;
    }
  } else {
    s.roll = s.pitch = 0;
  }
  const last = s.trail.at(-1);
  if (s.alt > 0 && (!last || Math.hypot(last.x - s.x, last.y - s.y) > 0.4)) {
    s.trail.push({ x: s.x, y: s.y });
    if (s.trail.length > 800) s.trail.shift();
  }
  return s;
}
export function survey(width, height, spacing, alt) {
  [width, height, spacing, alt] = [width, height, spacing, alt].map(Number);
  if (
    ![width, height, spacing, alt].every(Number.isFinite) ||
    width < 20 ||
    width > 500 ||
    height < 20 ||
    height > 500 ||
    spacing < 5 ||
    spacing > height ||
    alt < 2 ||
    alt > 80
  )
    throw Error(
      "Use an area of 20–500 m, valid lane spacing, and altitude of 2–80 m.",
    );
  const points = [];
  for (let y = 0, i = 0; y <= height; y += spacing, i++) {
    points.push(
      { x: i % 2 ? width : 0, y, alt },
      { x: i % 2 ? 0 : width, y, alt },
    );
  }
  return validatePoints(points);
}
export function exportPlan(points) {
  const route = validatePoints(points),
    latitude = HOME[0],
    longitude = HOME[1];
  let items = [
    { command: 22, x: 0, y: 0, alt: route[0].alt },
    ...route.map((p) => ({ command: 16, ...p })),
    { command: 21, x: 0, y: 0, alt: 0 },
  ].map((p, i) => ({
    autoContinue: true,
    command: p.command,
    doJumpId: i + 1,
    frame: 3,
    params: [
      0,
      p.command === 16 ? 2 : 0,
      0,
      null,
      latitude + p.y / 111320,
      longitude + p.x / (111320 * Math.cos((latitude * Math.PI) / 180)),
      p.alt,
    ],
    type: "SimpleItem",
  }));
  return {
    fileType: "Plan",
    version: 1,
    groundStation: "PythonGCS",
    geoFence: { circles: [], polygons: [], version: 2 },
    rallyPoints: { points: [], version: 2 },
    mission: {
      version: 2,
      firmwareType: 12,
      vehicleType: 2,
      cruiseSpeed: 5,
      hoverSpeed: 5,
      plannedHomePosition: [latitude, longitude, 0],
      items,
    },
  };
}
export function importPlan(data) {
  const items = data?.mission?.items;
  if (
    data?.fileType !== "Plan" ||
    !Array.isArray(items) ||
    items.length < 3 ||
    items.length > 202
  )
    throw Error("Choose a supported QGroundControl .plan file.");
  if (
    data.geoFence?.polygons?.length ||
    data.geoFence?.circles?.length ||
    data.rallyPoints?.points?.length
  )
    throw Error("This demo does not support fences or rally points.");
  const origin = data.mission.plannedHomePosition;
  if (
    !Array.isArray(origin) ||
    origin.length < 2 ||
    !origin.slice(0, 2).every(Number.isFinite) ||
    Math.abs(origin[0]) > 90 ||
    Math.abs(origin[1]) > 180
  )
    throw Error("A valid planned home position is required.");
  const points = [];
  for (const [index, item] of items.entries()) {
    const command = index === 0 ? 22 : index === items.length - 1 ? 21 : 16;
    if (
      item.type !== "SimpleItem" ||
      item.frame !== 3 ||
      item.command !== command ||
      item.autoContinue !== true
    )
      throw Error(
        "Use a home takeoff, waypoints, then a home landing, all auto-continuing in relative-altitude frame.",
      );
    const p = item.params;
    if (
      !Array.isArray(p) ||
      p.length !== 7 ||
      !p.slice(4, 7).every(Number.isFinite) ||
      Math.abs(p[4]) > 90 ||
      Math.abs(p[5]) > 180
    )
      throw Error("Invalid mission coordinates.");
    if (
      p[0] !== 0 ||
      p[2] !== 0 ||
      p[3] !== null ||
      p[1] !== (command === 16 ? 2 : 0)
    )
      throw Error(
        "This demo cannot preserve the custom command parameters in this plan.",
      );
    const x =
      (p[5] - origin[1]) * 111320 * Math.cos((origin[0] * Math.PI) / 180);
    const y = (p[4] - origin[0]) * 111320;
    if (command === 16) points.push({ x, y, alt: p[6] });
    else if (Math.hypot(x, y) > 0.1 || (command === 21 && p[6] !== 0))
      throw Error(
        "The demo requires takeoff and landing at the planned home position.",
      );
  }
  const route = validatePoints(points);
  if (Math.abs(items[0].params[6] - route[0].alt) > 0.001)
    throw Error(
      "The demo requires takeoff altitude to match the first waypoint.",
    );
  return route;
}
