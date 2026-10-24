// Desktop's bundled libraries and original X-frame attitude-model geometry.
export function geographicViews(home, addWaypoint) {
  if (!window.L) return null;
  const ll = (p) => [
      home[0] + p.y / 111320,
      home[1] + p.x / (111320 * Math.cos((home[0] * Math.PI) / 180)),
    ],
    maps = {};
  for (const name of ["flight", "plan"]) {
    const map = L.map(`${name}-osm`, { zoomControl: false }).setView(home, 18);
    L.control.zoom({ position: "topright" }).addTo(map);
    const tiles = L.tileLayer(
      "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
      {
        maxZoom: 19,
        attribution:
          '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      },
    ).addTo(map);
    const layer = L.layerGroup().addTo(map);
    maps[name] = { map, layer, visible: true, signature: "" };
    let failures = 0;
    tiles.on("tileerror", () => {
      if (++failures > 2)
        document.getElementById("status-message").textContent =
          "OpenStreetMap tiles unavailable on this connection. Use the OpenStreetMap button to switch to the local grid.";
    });
    L.circleMarker(home, {
      radius: 7,
      color: "#536b57",
      fillColor: "#faf9f5",
      fillOpacity: 1,
    })
      .bindTooltip("Home")
      .addTo(map);
    document.getElementById(`${name}-map`).setAttribute("hidden", "");
    document
      .getElementById(`${name}-map-mode`)
      .addEventListener("click", () => {
        const item = maps[name];
        item.visible = !item.visible;
        document.getElementById(`${name}-osm`).hidden = !item.visible;
        document
          .getElementById(`${name}-map`)
          .toggleAttribute("hidden", item.visible);
        const button = document.getElementById(`${name}-map-mode`);
        button.textContent = item.visible ? "OpenStreetMap" : "Local grid";
        button.setAttribute("aria-pressed", String(item.visible));
        if (name === "flight")
          document.getElementById("flight-map-caption").textContent =
            item.visible
              ? "OpenStreetMap · Generated demo aircraft"
              : "Local grid · Generated demo aircraft";
        if (item.visible) item.map.invalidateSize();
      });
    if (name === "plan")
      map.on("click", (e) =>
        addWaypoint({
          x: Math.round(
            (e.latlng.lng - home[1]) *
              111320 *
              Math.cos((home[0] * Math.PI) / 180),
          ),
          y: Math.round((e.latlng.lat - home[0]) * 111320),
        }),
      );
    else {
      maps[name].aircraft = L.marker(home, {
        icon: L.divIcon({
          className: "aircraft-marker",
          html: "<span>▲</span>",
          iconSize: [28, 28],
          iconAnchor: [14, 14],
        }),
      }).addTo(map);
      maps[name].trail = L.polyline([], { color: "#536b57", weight: 3 }).addTo(
        map,
      );
    }
  }
  return {
    update(name, points, state, trailVisible = true) {
      const item = maps[name];
      if (item.visible) item.map.invalidateSize({ pan: false });
      const signature = JSON.stringify(points);
      if (signature !== item.signature) {
        item.signature = signature;
        item.layer.clearLayers();
        L.polyline([home, ...points.map(ll), home], {
          color: "#9d8b65",
          weight: 2,
          dashArray: "7 6",
        }).addTo(item.layer);
        points.forEach((p, i) =>
          L.circleMarker(ll(p), {
            radius: 5,
            color: "#9d8b65",
            fillColor: "#faf9f5",
            fillOpacity: 1,
          })
            .bindTooltip(String(i + 1), { permanent: true, direction: "top" })
            .addTo(item.layer),
        );
      }
      if (item.aircraft) {
        item.aircraft.setLatLng(ll(state));
        const element = item.aircraft.getElement()?.querySelector("span");
        if (element) element.style.transform = `rotate(${state.heading}deg)`;
        item.trail.setLatLngs(trailVisible ? state.trail.map(ll) : []);
      }
    },
    fit(points, state) {
      maps.flight.map.fitBounds(
        L.latLngBounds([home, ...points.map(ll), ll(state)]).pad(0.4),
        { maxZoom: 19 },
      );
    },
  };
}

export function attitudeModel(container) {
  const status = document.getElementById("attitude-model-status");
  if (!window.THREE) {
    status.textContent = "3D library unavailable. Select 2D to use the PFD.";
    return null;
  }
  try {
    const scene = new THREE.Scene(),
      camera = new THREE.PerspectiveCamera(50, 1, 0.1, 1000);
    let orbitX = 0.52,
      orbitY = 0.35,
      zoom = 6.95,
      drag = null,
      lastTime = performance.now(),
      armed = false;
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    renderer.domElement.setAttribute("aria-label", "Rendered 3D drone model");
    container.append(renderer.domElement);
    scene.add(new THREE.AmbientLight(0xffffff, 0.7));
    const light = new THREE.DirectionalLight(0xffffff, 0.9);
    light.position.set(5, 10, 7);
    scene.add(light);
    const fill = new THREE.DirectionalLight(0x38bdf8, 0.4);
    fill.position.set(-5, -5, -5);
    scene.add(fill);
    const grid = new THREE.GridHelper(20, 20, 0x536b57, 0xc3c8ba);
    grid.position.y = -1.5;
    scene.add(grid);
    const drone = new THREE.Group(),
      rotors = [];
    scene.add(drone);
    drone.add(
      new THREE.Mesh(
        new THREE.BoxGeometry(1, 0.3, 1),
        new THREE.MeshStandardMaterial({
          color: 0xffffff,
          roughness: 0.3,
          metalness: 0.8,
        }),
      ),
    );
    for (const a of [
      { x: 1.3, z: 1.3, front: true },
      { x: -1.3, z: 1.3, front: true },
      { x: 1.3, z: -1.3, front: false },
      { x: -1.3, z: -1.3, front: false },
    ]) {
      const arm = new THREE.Mesh(
        new THREE.BoxGeometry(0.15, 0.1, 0.15),
        new THREE.MeshStandardMaterial({ color: 0x94a3b8, metalness: 0.5 }),
      );
      arm.scale.z = Math.hypot(a.x, a.z) * 5;
      arm.position.set(a.x / 2, 0, a.z / 2);
      arm.lookAt(0, 0, 0);
      drone.add(arm);
      const color = a.front ? 0x0b57d0 : 0x0f9d58,
        rotor = new THREE.Mesh(
          new THREE.CylinderGeometry(0.5, 0.5, 0.05, 24),
          new THREE.MeshStandardMaterial({
            color,
            emissive: color,
            emissiveIntensity: 0.5,
            transparent: true,
            opacity: 0.85,
          }),
        );
      rotor.position.set(a.x, 0.15, a.z);
      drone.add(rotor);
      rotors.push(rotor);
    }
    const resize = () => {
      const r = container.getBoundingClientRect();
      if (!r.width || !r.height) return;
      camera.aspect = r.width / r.height;
      camera.updateProjectionMatrix();
      renderer.setSize(r.width, r.height);
    };
    new ResizeObserver(resize).observe(container);
    container.addEventListener("pointerdown", (e) => {
      drag = { x: e.clientX, y: e.clientY };
      container.setPointerCapture(e.pointerId);
    });
    container.addEventListener("pointermove", (e) => {
      if (!drag) return;
      orbitY -= (e.clientX - drag.x) * 0.01;
      orbitX = Math.max(
        -1.2,
        Math.min(1.2, orbitX + (e.clientY - drag.y) * 0.01),
      );
      drag = { x: e.clientX, y: e.clientY };
    });
    container.addEventListener("pointerup", () => (drag = null));
    container.addEventListener(
      "wheel",
      (e) => {
        e.preventDefault();
        zoom = Math.max(4, Math.min(14, zoom + e.deltaY * 0.01));
      },
      { passive: false },
    );
    container.addEventListener("dblclick", () => {
      orbitX = 0.52;
      orbitY = 0.35;
      zoom = 6.95;
    });
    function frame(now) {
      requestAnimationFrame(frame);
      if (container.hidden || !container.getClientRects().length) return;
      const dt = Math.min(0.05, (now - lastTime) / 1000);
      lastTime = now;
      camera.position.set(
        zoom * Math.sin(orbitY) * Math.cos(orbitX),
        zoom * Math.sin(orbitX),
        zoom * Math.cos(orbitY) * Math.cos(orbitX),
      );
      camera.lookAt(0, 0, 0);
      if (armed)
        rotors.forEach((r, i) => (r.rotation.y += (i % 2 ? 1 : -1) * dt * 12));
      renderer.render(scene, camera);
    }
    requestAnimationFrame(frame);
    resize();
    status.textContent = "";
    return {
      update(state) {
        drone.rotation.order = "YXZ";
        drone.rotation.y = (-state.heading * Math.PI) / 180;
        drone.rotation.x = (state.pitch * Math.PI) / 180;
        drone.rotation.z = (-state.roll * Math.PI) / 180;
        armed = state.armed;
      },
      resize,
    };
  } catch (error) {
    status.textContent =
      "WebGL is unavailable in this browser. Select 2D; the 3D model remains available on the desktop and WebGL-enabled browsers.";
    return null;
  }
}
