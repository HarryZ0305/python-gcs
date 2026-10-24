import {
  HOME,
  DEFAULT_ROUTE,
  createModel,
  advance,
  arm,
  takeoff,
  hold,
  land,
  returnHome,
  startMission,
  cutoff,
  survey,
  exportPlan,
  importPlan,
  validatePoints,
  bounded,
} from "./demo-model.js?v=3";
import { geographicViews, attitudeModel } from "./flight-views.js?v=6";
const $ = (id) => document.getElementById(id),
  clone = (x) => structuredClone(x);
const query = new URLSearchParams(location.search),
  monitor = query.get("monitor") === "1",
  session = query.get("session") || crypto.randomUUID();
const channel =
  "BroadcastChannel" in window
    ? new BroadcastChannel(`pythongcs-demo-${session}`)
    : null;
let model = createModel(),
  active = "fly",
  draft = clone(DEFAULT_ROUTE),
  applied = clone(DEFAULT_ROUTE),
  undo = [],
  redo = [],
  history = [],
  review = null,
  events = [],
  showTrail = true,
  video = false,
  lastSample = 0,
  lastMonitor = 0,
  mapTransform = null,
  keys = new Set();
let preferences = { theme: "light", cruise: 5, batteryWarning: 25 };
try {
  const saved = JSON.parse(
    localStorage.getItem("pythongcs-demo-preferences") || "{}",
  );
  if (["light", "dark"].includes(saved.theme)) preferences.theme = saved.theme;
  if (Number.isFinite(saved.cruise))
    preferences.cruise = bounded(saved.cruise, 2, 12);
  if (Number.isFinite(saved.batteryWarning))
    preferences.batteryWarning = bounded(saved.batteryWarning, 10, 50);
} catch {}
document.documentElement.dataset.theme = preferences.theme;
model.cruise = preferences.cruise;
$("theme").value = preferences.theme;
$("cruise-speed").value = preferences.cruise;
$("battery-warning").value = preferences.batteryWarning;
const parameters = [
  ["MPC_XY_CRUISE", "5.0", "REAL32", "Cruise speed"],
  ["MPC_Z_VEL_MAX_UP", "3.0", "REAL32", "Maximum climb speed"],
  ["MPC_Z_VEL_MAX_DN", "1.5", "REAL32", "Maximum descent speed"],
  ["RTL_RETURN_ALT", "30.0", "REAL32", "Return altitude"],
  ["COM_DISARM_LAND", "2.0", "REAL32", "Disarm delay after landing"],
  ["SYS_AUTOSTART", "4001", "INT32", "Airframe configuration"],
];
function message(text, error = false) {
  $("status-message").textContent = text;
  $("status-message").style.color = error ? "var(--danger)" : "";
}
function log(category, text) {
  events.unshift({ time: new Date().toLocaleTimeString(), category, text });
  events = events.slice(0, 200);
  renderLog();
  renderEvents();
}
function run(action) {
  if (monitor) return;
  try {
    action();
    render();
  } catch (error) {
    message(error.message, true);
  }
}
function savePreferences() {
  try {
    localStorage.setItem(
      "pythongcs-demo-preferences",
      JSON.stringify(preferences),
    );
  } catch {
    message(
      "Preferences apply to this session; browser storage is unavailable.",
    );
  }
}
function tab(name) {
  if (
    !["fly", "plan", "vehicle", "analyze", "settings", "diagnostics"].includes(
      name,
    )
  )
    return;
  if (monitor && name !== "diagnostics") return;
  if (name !== "fly") stopKeys();
  active = name;
  document
    .querySelectorAll("[role=tabpanel]")
    .forEach((p) => (p.hidden = p.id !== `view-${name}`));
  document.querySelectorAll("[data-tab]").forEach((b) => {
    b.setAttribute("aria-selected", String(b.dataset.tab === name));
    b.tabIndex = b.dataset.tab === name ? 0 : -1;
  });
  if (!monitor) location.hash = name;
  render();
  if (name === "analyze") drawGraphs();
}
document.querySelectorAll("[data-tab]").forEach((button) => {
  button.addEventListener("click", () => tab(button.dataset.tab));
  button.addEventListener("keydown", (e) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) return;
    e.preventDefault();
    const buttons = [...document.querySelectorAll("[data-tab]")],
      i = buttons.indexOf(button),
      index =
        e.key === "Home"
          ? 0
          : e.key === "End"
            ? buttons.length - 1
            : (i + (e.key === "ArrowRight" ? 1 : -1) + buttons.length) %
              buttons.length;
    tab(buttons[index].dataset.tab);
    buttons[index].focus();
  });
});
document
  .querySelectorAll("[data-tab-link]")
  .forEach((b) => b.addEventListener("click", () => tab(b.dataset.tabLink)));
document.querySelectorAll("[data-open]").forEach((button) =>
  button.addEventListener("click", () => {
    stopKeys();
    $(button.dataset.open).showModal();
  }),
);
document
  .querySelectorAll("[data-close]")
  .forEach((button) =>
    button.addEventListener("click", () => button.closest("dialog").close()),
  );
document.querySelectorAll("dialog").forEach((dialog) =>
  dialog.addEventListener("click", (e) => {
    if (e.target === dialog) {
      const r = dialog.getBoundingClientRect();
      if (
        e.clientX < r.left ||
        e.clientX > r.right ||
        e.clientY < r.top ||
        e.clientY > r.bottom
      )
        dialog.close();
    }
  }),
);
const actions = {
  arm: () => {
    arm(model);
    log(
      "flight",
      model.armed ? "Demo aircraft armed." : "Demo aircraft disarmed.",
    );
  },
  takeoff: () => {
    takeoff(model, Number($("takeoff-alt").value));
    log(
      "flight",
      `Demo takeoff to ${model.targetAltitude} m relative to home.`,
    );
  },
  hold: () => {
    hold(model);
    log("flight", "Hold: simulated motion stopped.");
  },
  return: () => {
    returnHome(model);
    log("flight", "Returning the simulated aircraft to home.");
  },
  land: () => {
    land(model);
    log("flight", "Landing the simulated aircraft.");
  },
  mission: () => {
    startMission(model, applied);
    log(
      "flight",
      `Started the local demo route with ${applied.length} waypoints.`,
    );
  },
};
document.querySelectorAll("[data-action]").forEach((button) =>
  button.addEventListener("click", () =>
    run(() => {
      actions[button.dataset.action]();
      message("Simulation only. No aircraft command was sent.");
    }),
  ),
);
$("apply-mode").addEventListener("click", () =>
  run(() => {
    actions[$("demo-mode").value]();
    $("pilot-dialog").close();
  }),
);
$("confirm-cutoff").addEventListener("click", () =>
  run(() => {
    cutoff(model);
    stopKeys();
    $("emergency-dialog").close();
    log(
      "flight",
      "Emergency stop: demo motors stopped; model reset to ground.",
    );
    message("Demo emergency stop complete.");
  }),
);
function canvasContext(canvas) {
  const rect = canvas.getBoundingClientRect();
  if (!rect.width || !rect.height) return null;
  const ratio = Math.min(devicePixelRatio || 1, 2),
    w = Math.round(rect.width * ratio),
    h = Math.round(rect.height * ratio);
  if (canvas.width !== w || canvas.height !== h) {
    canvas.width = w;
    canvas.height = h;
  }
  const c = canvas.getContext("2d");
  c.setTransform(ratio, 0, 0, ratio, 0, 0);
  return { c, w: rect.width, h: rect.height };
}
function horizon(canvas, test = false) {
  const ctx = canvasContext(canvas);
  if (!ctx) return;
  const { c, w, h } = ctx;
  c.clearRect(0, 0, w, h);
  c.save();
  c.translate(w / 2, h / 2 + model.pitch * 2);
  c.rotate((-model.roll * Math.PI) / 180);
  c.fillStyle = "#637b80";
  c.fillRect(-w * 2, -h * 3, w * 4, h * 3);
  c.fillStyle = "#89745f";
  c.fillRect(-w * 2, 0, w * 4, h * 3);
  c.strokeStyle = "#eee9d7";
  c.lineWidth = 1;
  c.beginPath();
  c.moveTo(-w * 2, 0);
  c.lineTo(w * 2, 0);
  c.stroke();
  if (test) {
    c.strokeStyle = "#b7b49d";
    for (let x = -w * 3; x < w * 3; x += 60) {
      c.beginPath();
      c.moveTo(0, 0);
      c.lineTo(x, h * 2);
      c.stroke();
    }
    for (let y = 20; y < h * 2; y += 35) {
      c.beginPath();
      c.moveTo(-w * 2, y);
      c.lineTo(w * 2, y);
      c.stroke();
    }
  } else {
    for (let y = -60; y <= 60; y += 20) {
      if (!y) continue;
      c.beginPath();
      c.moveTo(-24, y);
      c.lineTo(24, y);
      c.stroke();
    }
  }
  c.restore();
  c.strokeStyle = "#f1dfad";
  c.lineWidth = 2;
  c.beginPath();
  c.moveTo(w / 2 - 35, h / 2);
  c.lineTo(w / 2 - 12, h / 2);
  c.lineTo(w / 2 - 12, h / 2 + 6);
  c.moveTo(w / 2 + 35, h / 2);
  c.lineTo(w / 2 + 12, h / 2);
  c.lineTo(w / 2 + 12, h / 2 + 6);
  c.stroke();
  c.fillStyle = "#faf9f5";
  c.font = "11px Segoe UI, sans-serif";
  c.fillText(
    test
      ? "GENERATED · NOT CAMERA FOOTAGE"
      : `${Math.round(model.heading).toString().padStart(3, "0")}°`,
    10,
    h - 12,
  );
}
function mapSVG(svg, points, planning = false) {
  const all = [{ x: 0, y: 0 }, ...points, { x: model.x, y: model.y }],
    xs = all.map((p) => p.x),
    ys = all.map((p) => p.y),
    minX = Math.min(...xs),
    maxX = Math.max(...xs),
    minY = Math.min(...ys),
    maxY = Math.max(...ys),
    span = Math.max(140, maxX - minX, maxY - minY) * 1.3,
    scale = 430 / span,
    cx = (maxX + minX) / 2,
    cy = (maxY + minY) / 2;
  const pos = (p) => [450 + (p.x - cx) * scale, 260 - (p.y - cy) * scale],
    pair = (p) =>
      pos(p)
        .map((n) => n.toFixed(2))
        .join(",");
  if (planning) mapTransform = { scale, cx, cy };
  let grid = "";
  const gridStep = span > 600 ? 100 : 20;
  for (
    let i = Math.floor((cx - span) / gridStep) * gridStep;
    i <= cx + span;
    i += gridStep
  ) {
    const [x] = pos({ x: i, y: 0 });
    grid += `<path d="M${x} 0V520"/>`;
  }
  for (
    let i = Math.floor((cy - span) / gridStep) * gridStep;
    i <= cy + span;
    i += gridStep
  ) {
    const [, y] = pos({ x: 0, y: i });
    grid += `<path d="M0 ${y}H900"/>`;
  }
  const home = pos({ x: 0, y: 0 }),
    air = pos(model);
  svg.innerHTML = `<rect width="900" height="520" fill="var(--raised)"/><g stroke="var(--line)" stroke-width=".7">${grid}</g><polyline points="${[{ x: 0, y: 0 }, ...points, { x: 0, y: 0 }].map(pair).join(" ")}" fill="none" stroke="#9d8b65" stroke-width="2" stroke-dasharray="7 6"/>${!planning && showTrail ? `<polyline points="${model.trail.map(pair).join(" ")}" fill="none" stroke="var(--accent)" stroke-width="2.5"/>` : ""}<circle cx="${home[0]}" cy="${home[1]}" r="13" fill="var(--surface)" stroke="var(--accent)"/><text x="${home[0]}" y="${home[1] + 4}" text-anchor="middle" fill="var(--accent)" font-size="11" font-family="Segoe UI,sans-serif">H</text>${points
    .map((p, i) => {
      const [x, y] = pos(p);
      return `<circle cx="${x}" cy="${y}" r="5" fill="var(--surface)" stroke="#9d8b65" stroke-width="2"/><text x="${x + 9}" y="${y - 10}" fill="var(--muted)" font-size="11" font-family="Segoe UI,sans-serif">${i + 1}</text>`;
    })
    .join(
      "",
    )}${!planning ? `<g transform="translate(${air[0]} ${air[1]}) rotate(${model.heading})"><path d="M0 -16L11 11 0 5 -11 11Z" fill="var(--accent)" stroke="var(--surface)" stroke-width="2"/></g>` : ""}<text x="856" y="37" fill="var(--accent)" font-family="Segoe UI,sans-serif" font-weight="600" font-size="13">N ↑</text><path d="M730 475h${40 * scale}" stroke="var(--muted)"/><text x="730" y="465" fill="var(--muted)" font-size="11" font-family="Segoe UI,sans-serif">40 m</text>`;
}
function toggleVideo(value) {
  video = value;
  $("video-inset").hidden = !value;
  $("video-toggle").textContent = value ? "Hide test video" : "Show test video";
  $("video-toggle").setAttribute("aria-pressed", String(value));
  $("video-setting").checked = value;
  if (value) horizon($("test-video"), true);
}
$("video-toggle").addEventListener("click", () => toggleVideo(!video));
$("video-setting").addEventListener("change", (e) =>
  toggleVideo(e.target.checked),
);
$("toggle-trail").addEventListener("click", () => {
  showTrail = !showTrail;
  $("toggle-trail").textContent = showTrail ? "Trail on" : "Trail off";
  $("toggle-trail").setAttribute("aria-pressed", String(showTrail));
  render();
});
$("fit-map").addEventListener("click", () => {
  geographic?.fit(
    model.armed && model.route.length ? model.route : applied,
    model,
  );
  mapSVG($("flight-map"), applied);
  message("Map fitted to the demo route and aircraft.");
});
function changeDraft(next) {
  const valid = next.length ? validatePoints(next) : [];
  undo.push(clone(draft));
  undo = undo.slice(-30);
  redo = [];
  draft = valid;
  renderPlan();
}
function draftMatches() {
  // Draft equality is independent of the selected map renderer.
  return JSON.stringify(draft) === JSON.stringify(applied);
}
const geographic = geographicViews(HOME, (p) =>
  run(() =>
    changeDraft([
      ...draft,
      { ...p, alt: Number($("takeoff-alt").value) || 20 },
    ]),
  ),
);
const droneModel = attitudeModel($("attitude-model"));
for (const mode of ["2d", "3d"])
  $(`attitude-${mode}`).addEventListener("click", () => {
    $("attitude").hidden = mode !== "2d";
    $("attitude-model").hidden = mode !== "3d";
    $("attitude-2d").setAttribute("aria-pressed", String(mode === "2d"));
    $("attitude-3d").setAttribute("aria-pressed", String(mode === "3d"));
    if (mode === "3d") droneModel?.resize();
    render();
  });
if (!geographic) {
  document
    .querySelectorAll(".geographic-map")
    .forEach((e) => (e.hidden = true));
  document.querySelectorAll('[id$="-map-mode"]').forEach((b) => {
    b.disabled = true;
    b.textContent = "Local grid";
  });
}
function renderPlan() {
  const body = $("waypoint-list");
  body.replaceChildren();
  draft.forEach((point, i) => {
    const row = document.createElement("tr");
    const number = document.createElement("td");
    number.textContent = i + 1;
    const coords = document.createElement("td");
    coords.textContent = `${point.x.toFixed(0)} / ${point.y.toFixed(0)} m`;
    const altitude = document.createElement("td"),
      input = document.createElement("input");
    input.type = "number";
    input.min = "2";
    input.max = "80";
    input.value = point.alt;
    input.setAttribute("aria-label", `Waypoint ${i + 1} altitude`);
    input.addEventListener("change", () =>
      run(() => {
        const next = clone(draft);
        next[i].alt = Number(input.value);
        try {
          changeDraft(next);
        } catch (error) {
          input.value = point.alt;
          throw error;
        }
      }),
    );
    altitude.append(input);
    const edit = document.createElement("td");
    [
      [
        "↑",
        "Move waypoint up",
        () => {
          if (i > 0) {
            const next = clone(draft);
            [next[i], next[i - 1]] = [next[i - 1], next[i]];
            changeDraft(next);
          }
        },
      ],
      [
        "×",
        "Delete waypoint",
        () => changeDraft(draft.filter((_, j) => i !== j)),
      ],
    ].forEach(([text, title, action]) => {
      const b = document.createElement("button");
      b.textContent = text;
      b.setAttribute("aria-label", `${title} ${i + 1}`);
      b.addEventListener("click", () => run(action));
      edit.append(b);
    });
    row.append(number, coords, altitude, edit);
    body.append(row);
  });
  if (!draft.length) {
    const row = document.createElement("tr"),
      cell = document.createElement("td");
    cell.colSpan = 4;
    cell.className = "empty";
    cell.textContent = "Add a waypoint or generate a survey grid.";
    row.append(cell);
    body.append(row);
  }
  let distance = 0,
    last = { x: 0, y: 0 };
  for (const p of [...draft, { x: 0, y: 0 }]) {
    distance += Math.hypot(p.x - last.x, p.y - last.y);
    last = p;
  }
  $("mission-stats").textContent =
    `${draft.length} waypoints · ${Math.round(distance)} m route · ~${Math.ceil(distance / model.cruise)} s cruising`;
  $("plan-state").textContent = draftMatches()
    ? "Demo plan ready"
    : "Local demo draft";
  $("undo-plan").disabled = !undo.length;
  $("redo-plan").disabled = !redo.length;
  $("apply-plan").disabled = !draft.length || draftMatches();
  $("export-plan").disabled = !draft.length;
  mapSVG($("plan-map"), draft, true);
  geographic?.update("plan", draft, model);
}
$("undo-plan").addEventListener("click", () =>
  run(() => {
    if (undo.length) {
      redo.push(clone(draft));
      draft = undo.pop();
      renderPlan();
    }
  }),
);
$("redo-plan").addEventListener("click", () =>
  run(() => {
    if (redo.length) {
      undo.push(clone(draft));
      draft = redo.pop();
      renderPlan();
    }
  }),
);
$("clear-plan").addEventListener("click", () => changeDraft([]));
$("add-waypoint").addEventListener("click", () =>
  run(() => {
    const p = draft.at(-1) || { x: 0, y: 0 };
    changeDraft([...draft, { x: p.x + 20, y: p.y + 20, alt: 20 }]);
  }),
);
$("plan-map").addEventListener("click", (e) =>
  run(() => {
    if (!mapTransform) return;
    const p = new DOMPoint(e.clientX, e.clientY).matrixTransform(
        $("plan-map").getScreenCTM().inverse(),
      ),
      { scale, cx, cy } = mapTransform;
    changeDraft([
      ...draft,
      {
        x: Math.round(cx + (p.x - 450) / scale),
        y: Math.round(cy - (p.y - 260) / scale),
        alt: Number($("takeoff-alt").value) || 20,
      },
    ]);
  }),
);
$("plan-map").addEventListener("keydown", (e) => {
  if (e.key === "Enter") $("add-waypoint").click();
});
$("apply-plan").addEventListener("click", () =>
  run(() => {
    applied = validatePoints(draft);
    renderPlan();
    log(
      "plan",
      `Applied ${applied.length} waypoints to the local demo. No controller upload.`,
    );
    message("Demo plan ready. Return to Fly to run it.");
  }),
);
$("survey-form").addEventListener("submit", (e) => {
  e.preventDefault();
  try {
    changeDraft(
      survey(
        ...[
          "survey-width",
          "survey-height",
          "survey-spacing",
          "survey-alt",
        ].map((id) => Number($(id).value)),
      ),
    );
    $("survey-error").textContent = "";
    $("survey-dialog").close();
    log(
      "plan",
      `Generated a local survey draft with ${draft.length} waypoints.`,
    );
  } catch (error) {
    $("survey-error").textContent = error.message;
  }
});
function download(name, contents, type) {
  const blob = new Blob([contents], { type }),
    url = URL.createObjectURL(blob),
    link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
$("export-plan").addEventListener("click", () =>
  run(() =>
    download(
      "pythongcs-demo.plan",
      JSON.stringify(exportPlan(draft), null, 2),
      "application/json",
    ),
  ),
);
$("import-plan-button").addEventListener("click", () =>
  $("import-plan").click(),
);
$("import-plan").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  try {
    if (file.size > 2 * 1024 * 1024)
      throw Error("Choose a plan smaller than 2 MB.");
    const next = importPlan(JSON.parse(await file.text()));
    changeDraft(next);
    log("plan", "Imported a supported .plan file into the local draft.");
    message("Plan imported. Review it before using it in the demo.");
  } catch (error) {
    message(error.message, true);
  } finally {
    e.target.value = "";
  }
});
function renderParameters() {
  const q = $("parameter-search").value.toLowerCase(),
    body = $("parameter-list");
  body.replaceChildren();
  parameters
    .filter((row) => row.join(" ").toLowerCase().includes(q))
    .forEach((row) => {
      const tr = document.createElement("tr");
      row.forEach((value) => {
        const td = document.createElement("td");
        td.textContent = value;
        tr.append(td);
      });
      body.append(tr);
    });
  if (!body.children.length) {
    const tr = document.createElement("tr"),
      td = document.createElement("td");
    td.colSpan = 4;
    td.className = "empty";
    td.textContent = "No matching example parameters.";
    tr.append(td);
    body.append(tr);
  }
}
$("parameter-search").addEventListener("input", renderParameters);
$("backup-params").addEventListener("click", () =>
  download(
    "example-parameters.json",
    JSON.stringify(
      {
        source: "Illustrative values only; not a vehicle backup",
        parameters: parameters.map(([name, value, type]) => ({
          name,
          value: Number(value),
          type,
        })),
      },
      null,
      2,
    ),
    "application/json",
  ),
);
function chart(canvas, rows, key) {
  const ctx = canvasContext(canvas);
  if (!ctx) return;
  const { c, w, h } = ctx;
  c.clearRect(0, 0, w, h);
  const color = getComputedStyle(document.documentElement)
    .getPropertyValue(key === "alt" ? "--accent" : "--warning")
    .trim();
  c.strokeStyle = getComputedStyle(document.documentElement).getPropertyValue(
    "--line",
  );
  c.lineWidth = 1;
  for (let i = 0; i < 5; i++) {
    c.beginPath();
    c.moveTo(32, 12 + (i * (h - 42)) / 4);
    c.lineTo(w - 12, 12 + (i * (h - 42)) / 4);
    c.stroke();
  }
  c.fillStyle = getComputedStyle(document.documentElement).getPropertyValue(
    "--muted",
  );
  c.font = "10px Segoe UI,sans-serif";
  if (rows.length < 2) {
    c.fillText("Run a sample flight to populate this chart.", 40, h / 2);
    return;
  }
  const max = Math.max(2, ...rows.map((r) => r[key])) * 1.15,
    minTime = rows[0].time,
    maxTime = Math.max(minTime + 1, rows.at(-1).time);
  c.strokeStyle = color;
  c.lineWidth = 2;
  c.beginPath();
  rows.forEach((r, i) => {
    const x = 32 + ((r.time - minTime) / (maxTime - minTime)) * (w - 48),
      y = h - 30 - (r[key] / max) * (h - 48);
    if (i) c.lineTo(x, y);
    else c.moveTo(x, y);
  });
  c.stroke();
  c.fillText(max.toFixed(1), 4, 18);
  c.fillText("0", 14, h - 30);
  c.fillText(`${minTime.toFixed(0)} s`, 32, h - 8);
  c.fillText(`${maxTime.toFixed(0)} s`, w - 55, h - 8);
}
function drawGraphs() {
  const data = review || history;
  chart($("altitude-chart"), data, "alt");
  chart($("speed-chart"), data, "speed");
}
function renderEvents() {
  const body = $("event-table");
  body.replaceChildren();
  for (const event of events.slice(0, 12)) {
    const tr = document.createElement("tr");
    [event.time, event.category, event.text].forEach((value) => {
      const td = document.createElement("td");
      td.textContent = value;
      tr.append(td);
    });
    body.append(tr);
  }
  if (!events.length) {
    const tr = document.createElement("tr"),
      td = document.createElement("td");
    td.colSpan = 3;
    td.className = "empty";
    td.textContent = "Flight events will appear here.";
    tr.append(td);
    body.append(tr);
  }
}
function renderLog() {
  const q = $("log-filter").value.toLowerCase(),
    category = $("log-category").value,
    box = $("log-list");
  box.replaceChildren();
  events
    .filter(
      (e) =>
        (category === "all" || e.category === category) &&
        e.text.toLowerCase().includes(q),
    )
    .forEach((e) => {
      const div = document.createElement("div");
      div.className = "log-row";
      const t = document.createElement("time"),
        cat = document.createElement("span"),
        text = document.createElement("span");
      t.textContent = e.time;
      cat.className = "category";
      cat.textContent = e.category;
      text.textContent = e.text;
      div.append(t, cat, text);
      box.append(div);
    });
  if (!box.children.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "No matching simulation events.";
    box.append(empty);
  }
}
$("log-filter").addEventListener("input", renderLog);
$("log-category").addEventListener("change", renderLog);
$("clear-log").addEventListener("click", () => {
  events = [];
  renderLog();
  renderEvents();
});
$("export-csv").addEventListener("click", () => {
  const data = review || history;
  if (!data.length) {
    message("Run a sample flight or load a CSV before exporting.", true);
    return;
  }
  download(
    "pythongcs-demo.csv",
    "Time_Sec,Alt_Rel_m,Groundspeed_ms\n" +
      data
        .map((r) =>
          [r.time, r.alt, r.speed].map((v) => Number(v).toFixed(3)).join(","),
        )
        .join("\n"),
    "text/csv",
  );
});
$("clear-history").addEventListener("click", () => {
  history = [];
  review = null;
  $("exit-review").hidden = true;
  $("analysis-source").textContent =
    "Plots and events generated by this browser simulation.";
  drawGraphs();
});
$("load-csv-button").addEventListener("click", () => $("load-csv").click());
$("load-csv").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  try {
    if (file.size > 2 * 1024 * 1024)
      throw Error("Choose a CSV smaller than 2 MB.");
    const lines = (await file.text())
        .trim()
        .replace(/^\uFEFF/, "")
        .split(/\r?\n/),
      columns = lines
        .shift()
        .split(",")
        .map((s) => s.trim()),
      indices = ["Time_Sec", "Alt_Rel_m", "Groundspeed_ms"].map((k) =>
        columns.indexOf(k),
      );
    if (indices.some((i) => i < 0))
      throw Error(
        "CSV requires Time_Sec, Alt_Rel_m and Groundspeed_ms columns.",
      );
    if (lines.length > 5000) throw Error("Use no more than 5000 rows.");
    const rows = lines.map((line) => {
      const values = line.split(","),
        [time, alt, speed] = indices.map((i) => Number(values[i]));
      if (
        indices.some((i) => !values[i]?.trim()) ||
        ![time, alt, speed].every(Number.isFinite) ||
        time < 0 ||
        alt < 0 ||
        speed < 0
      )
        throw Error("CSV contains invalid numeric data.");
      return { time, alt, speed };
    });
    if (rows.length < 2 || rows.some((r, i) => i && r.time < rows[i - 1].time))
      throw Error("CSV needs at least two rows in time order.");
    review = rows;
    $("exit-review").hidden = false;
    $("analysis-source").textContent =
      `Historical CSV review: ${file.name}. These plots do not control the simulated aircraft.`;
    drawGraphs();
    message("Historical CSV loaded.");
  } catch (error) {
    message(error.message, true);
  } finally {
    e.target.value = "";
  }
});
$("exit-review").addEventListener("click", () => {
  review = null;
  $("exit-review").hidden = true;
  $("analysis-source").textContent =
    "Plots and events generated by this browser simulation.";
  drawGraphs();
});
$("theme").addEventListener("change", (e) => {
  preferences.theme = e.target.value;
  document.documentElement.dataset.theme = preferences.theme;
  savePreferences();
  render();
});
$("cruise-speed").addEventListener("change", (e) => {
  const value = Number(e.target.value);
  if (!Number.isFinite(value)) return;
  preferences.cruise = model.cruise = bounded(value, 2, 12);
  e.target.value = preferences.cruise;
  savePreferences();
  renderPlan();
});
$("battery-warning").addEventListener("change", (e) => {
  const value = Number(e.target.value);
  if (!Number.isFinite(value)) return;
  preferences.batteryWarning = bounded(value, 10, 50);
  e.target.value = preferences.batteryWarning;
  savePreferences();
});
function stopKeys() {
  keys.clear();
  $("keyboard-control").checked = false;
}
window.addEventListener("blur", stopKeys);
document.addEventListener("visibilitychange", () => {
  if (document.hidden) stopKeys();
});
window.addEventListener("keyup", (e) => keys.delete(e.key.toLowerCase()));
window.addEventListener("keydown", (e) => {
  if (
    active !== "fly" ||
    !$("keyboard-control").checked ||
    !model.armed ||
    model.alt < 1 ||
    document.querySelector("dialog[open]") ||
    e.target.matches("input,select,textarea,[contenteditable=true]")
  )
    return;
  const key = e.key.toLowerCase();
  if (key === " " && e.target.matches("button,a")) return;
  if ("wasdq eik".replaceAll(" ", "").includes(key) || key === " ") {
    e.preventDefault();
    if (key === " ") {
      hold(model);
      keys.clear();
    } else {
      keys.add(key);
      model.stage = "hold";
      model.mode = "Keyboard";
    }
  }
});
function keyboardStep(dt) {
  if (!keys.size) return;
  const forward = (keys.has("w") ? 1 : 0) - (keys.has("s") ? 1 : 0),
    right = (keys.has("d") ? 1 : 0) - (keys.has("a") ? 1 : 0),
    up = (keys.has("i") ? 1 : 0) - (keys.has("k") ? 1 : 0);
  model.heading =
    (model.heading +
      ((keys.has("e") ? 1 : 0) - (keys.has("q") ? 1 : 0)) * 35 * dt +
      360) %
    360;
  const h = (model.heading * Math.PI) / 180;
  model.x = bounded(
    model.x + (forward * Math.sin(h) + right * Math.cos(h)) * 3 * dt,
    -1900,
    1900,
  );
  model.y = bounded(
    model.y + (forward * Math.cos(h) - right * Math.sin(h)) * 3 * dt,
    -1900,
    1900,
  );
  model.alt = bounded(model.alt + up * 2 * dt, 1, 80);
  model.speed = Math.hypot(forward, right) * 3;
  model.climb = up * 2;
}
function render() {
  const state = model;
  $("state-arm").textContent = state.armed ? "Armed" : "Disarmed";
  $("state-mode").textContent = state.mode;
  $("state-battery").textContent = `${state.battery.toFixed(0)}%`;
  $("metric-alt").textContent = `${state.alt.toFixed(1)} m`;
  $("metric-speed").textContent = `${state.speed.toFixed(1)} m/s`;
  $("metric-climb").textContent = `${state.climb.toFixed(1)} m/s`;
  $("metric-home").textContent = `${Math.hypot(state.x, state.y).toFixed(0)} m`;
  $("arm-button").textContent = state.armed ? "Disarm" : "Arm";
  $("arm-button").disabled = state.alt > 0.8;
  $("takeoff-button").disabled = state.alt > 0.8;
  document
    .querySelectorAll("[data-needs-arm]")
    .forEach((b) => (b.disabled = !state.armed));
  $("demo-welcome").hidden =
    state.time > 0 && (state.armed || state.flightTime > 0);
  $("heading-readout").textContent =
    `Heading ${Math.round(state.heading).toString().padStart(3, "0")}° · Simulated`;
  $("battery-alert").hidden = state.battery > preferences.batteryWarning;
  $("diag-mode").textContent = state.mode;
  $("diag-time").textContent =
    `${String(Math.floor(state.flightTime / 60)).padStart(2, "0")}:${String(Math.floor(state.flightTime % 60)).padStart(2, "0")}`;
  $("diag-position").textContent =
    `${state.x.toFixed(1)} m / ${state.y.toFixed(1)} m`;
  $("diag-mission").textContent =
    state.stage === "route"
      ? `${state.routeIndex + 1} of ${state.route.length}`
      : state.stage === "takeoff"
        ? "Climbing"
        : state.stage === "land"
          ? "Landing"
          : "Not running";
  $("diag-update").textContent = monitor
    ? Date.now() - lastMonitor > 4000
      ? "Main demo disconnected"
      : "Receiving main demo state"
    : "Generated in this browser";
  if (active === "fly") {
    mapSVG(
      $("flight-map"),
      model.armed && model.route.length ? model.route : applied,
    );
    horizon($("attitude"));
    droneModel?.update(state);
    geographic?.update(
      "flight",
      model.armed && model.route.length ? model.route : applied,
      state,
      showTrail,
    );
    if (video) horizon($("test-video"), true);
  }
  if (active === "plan") {
    mapSVG($("plan-map"), draft, true);
    geographic?.update("plan", draft, state);
  }
  if (active === "analyze") drawGraphs();
}
if (monitor) {
  document.body.classList.add("monitor-mode");
  $("detach-monitor").hidden = true;
  $("monitor-link").hidden = true;
  $("clear-log").hidden = true;
  document
    .querySelectorAll("[data-action]")
    .forEach((b) => (b.disabled = true));
  $("monitor-description").textContent =
    "Read-only monitor of the main browser simulation. Close this window to return to the main view.";
  events = [];
  if (channel)
    channel.onmessage = (e) => {
      if (e.data.type !== "state") return;
      model = e.data.model;
      events = e.data.events;
      lastMonitor = Date.now();
      renderLog();
      renderEvents();
      render();
    };
  tab("diagnostics");
  setInterval(render, 500);
} else {
  $("detach-monitor").addEventListener("click", () => {
    if (!channel) {
      message(
        "Live second-window monitoring is unavailable in this browser. Use this tab instead.",
        true,
      );
      return;
    }
    const url = new URL("web_gcs.html", location.href);
    url.search = `?monitor=1&session=${encodeURIComponent(session)}`;
    $("monitor-link").href = url.href;
    $("monitor-link").hidden = false;
    const windowRef = window.open(
      url,
      "pythongcs-demo-monitor",
      "popup,width=1100,height=800",
    );
    if (!windowRef)
      message(
        "The monitor was blocked. Allow this site’s popup to open a second diagnostics window.",
        true,
      );
    else
      log(
        "system",
        "Requested the read-only diagnostics monitor. Use Open monitor tab if a window did not appear.",
      );
  });
  let previous = performance.now(),
    previousStage = model.stage;
  setInterval(() => {
    const now = performance.now(),
      dt = (now - previous) / 1000;
    previous = now;
    advance(model, dt);
    keyboardStep(Math.min(dt, 0.25));
    if (previousStage !== model.stage) {
      if (model.stage === "ground")
        log("flight", "Demo touchdown complete; motors disarmed.");
      else if (model.stage === "route")
        log("flight", "Demo takeoff complete; following the route.");
      else if (model.stage === "land") log("flight", "Demo landing started.");
      previousStage = model.stage;
    }
    if (model.time - lastSample > 0.5) {
      lastSample = model.time;
      history.push({
        time: model.time,
        alt: model.alt,
        speed: model.speed,
        climb: model.climb,
        voltage: 13.6 + (model.battery / 100) * 3.2,
      });
      history = history.slice(-600);
      if (channel)
        channel.postMessage({
          type: "state",
          model: clone(model),
          events: clone(events),
        });
    }
    render();
  }, 200);
  log(
    "system",
    "Browser demo ready. All motion and readings are generated locally.",
  );
  tab(location.hash.slice(1) || "fly");
}
renderPlan();
renderParameters();
renderEvents();
renderLog();
render();
window.addEventListener("resize", render);

window.addEventListener("hashchange", () => {
  if (location.hash.slice(1) !== active) tab(location.hash.slice(1));
});
