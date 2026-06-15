# Python MAVLink Ground Control Station

A desktop **Ground Control Station (GCS)** built in Python with **PyQt6** and raw **pymavlink**. It connects to flight controllers running **PX4 Autopilot**, with live telemetry, an interactive map, a real-time 3D attitude view, manual offboard control, waypoint mission planning, and full parameter management.

Developed and tested against **PX4 SITL** (Gazebo `gz_x500`), targeting a **Holybro S500** airframe with a **Pixhawk 6C** flight controller.

---

## Features

### FLY — telemetry & flight control
- **Aerospace Dashboard Layout** — A clean 3-column aerospace-themed dashboard containing control systems, large map display, gauges, and attitude metrics.
- **Custom Arc Gauges** — Beautiful custom half-circle gauges visualizing Altitude (0-120 m), Speed (0-30 m/s), Battery (0-100 %), and GPS Strength (0-20 satellites). They adaptively flash/change colors to warn of low battery or connection issues.
- **Aircraft Status panel** — Instant text metrics reporting Pitch, Roll, Yaw, Mode, and Throttle.
- **Interactive map** — An expanded Leaflet/OpenStreetMap view embedded in `QWebEngineView` that tracks the vehicle's position live.
- **3D attitude viewer** — A procedural three.js quadcopter that mirrors the vehicle's real-time orientation.
- **Command controls** — ARM / DISARM, flight-mode selector (PX4 modes), TAKEOFF, RTL, and LAND.
- **Manual flight controls** — FORWARD / YAW LEFT / YAW RIGHT / HOVER, driven by a continuous PX4 **OFFBOARD** setpoint stream.
- **Console acknowledgement log** — Decodes `COMMAND_ACK` and `STATUSTEXT` messages into plain-English console output (`ACCEPTED`, `DENIED`, `FAILED`, plus autopilot status text) inside a dedicated horizontal console strip.

### CAMERAS — camera feeds
- **Dedicated cameras panel** — Displays placeholder Front View and Bottom View camera feeds, isolated into their own tab to optimize flight telemetry space.

### PLAN — mission planning
- **Click-to-add waypoints** directly on the map, drawn as a dashed flight path.
- **Sync** waypoints from the map into the GCS, then **upload** them to the vehicle using the MAVLink mission protocol (home mapped to `seq 0`, waypoints `seq 1..N`).

### SETUP — parameters
- **Live parameter table** with instant name filtering.
- **Inline editing** — double-click a value to send a `PARAM_SET` back to the autopilot, with type handling for integer and real parameters.

### Connection
- **Non-blocking** connect/disconnect handled on a background `QThread`, so the UI never freezes.
- **Configurable connection string** (defaults to `udpin:0.0.0.0:14540`).
- **Safety lockout** — flight commands stay disabled until a connection is verified.
- **Thread-safe transmits** — all MAVLink writes are serialized behind a single lock to prevent packet corruption from concurrent commands and the offboard stream.

---

## Tech stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3 |
| GUI | PyQt6 (+ QtWebEngine) |
| MAVLink | pymavlink (raw) |
| Map | Leaflet / OpenStreetMap |
| 3D | three.js |
| Firmware target | PX4 Autopilot |
| Simulator | PX4 SITL (Gazebo `gz_x500`) |

---

## Project structure

```
python-gcs/
├── main.py              # Entry point — launches the GUI
├── requirements.txt
└── gcs/
    ├── connection.py    # connect() + telemetry stream setup (SET_MESSAGE_INTERVAL)
    ├── telemetry.py     # MAVLink receive loop, telemetry_data store, mission/param queues
    ├── commands.py      # Flight commands + OFFBOARD setpoint streamer + mission/param protocols
    ├── logs.py          # Shared timestamped log buffer
    └── ui/
        ├── gui.py       # Main window, layout, tabs, button handlers
        ├── gauge.py     # Custom radial ArcGauge widget
        ├── map_view.py  # Leaflet map widget
        ├── attitude_view.py # three.js 3D attitude widget
        ├── console_view.py  # Live log console
        ├── camera_view.py   # Camera feed placeholders
        └── setup_view.py    # Parameter management table
```

---

## Getting started

### 1. Prerequisites
- Python 3.10+
- A running PX4 instance — either **PX4 SITL** (for simulation) or a real PX4 flight controller.

### 2. Install
```bash
git clone https://github.com/HarryZ0305/python-gcs.git
cd python-gcs
pip install -r requirements.txt
```

### 3. Run the PX4 simulator
From a built [PX4-Autopilot](https://github.com/PX4/PX4-Autopilot) source tree:
```bash
make px4_sitl gz_x500          # add HEADLESS=1 in front to skip the Gazebo window
```
PX4 exposes MAVLink on UDP **14540** (developer/offboard API) and **14550** (ground stations).

> **Windows + WSL2 note:** PX4 SITL runs inside WSL2, which by default isolates its network from Windows — the GCS will sit on "connecting" with no heartbeat. Fix it by enabling mirrored networking: create `C:\Users\<you>\.wslconfig` containing
> ```
> [wsl2]
> networkingMode=mirrored
> ```
> then run `wsl --shutdown`, restart Ubuntu, and relaunch the sim. (Requires Windows 11 and a recent WSL; run `wsl --update` if needed.)

### 4. Launch the GCS
```bash
python main.py
```
Enter your connection string (default `udpin:0.0.0.0:14540`) and click **CONNECT**. The panels should populate within a few seconds.

---

## Quick flight (simulation)

1. **Connect** and wait for the GPS fix to reach 3D and the panels to fill in.
2. **ARM**, then **TAKEOFF** promptly — PX4 auto-disarms if you arm without taking off within ~10 seconds.
3. Select **OFFBOARD** and click **FORWARD** / **YAW** — watch the drone move in Gazebo and the 3D viewer mirror its attitude. **HOVER** zeroes the velocity.
4. **RTL** or **LAND** to bring it home.

Keep the console panel visible throughout — it reports every command's acknowledgement and any autopilot status messages.

---

## Firmware & hardware

This GCS targets **PX4** (it was originally prototyped against ArduCopter SITL and then ported). Movement uses PX4 **OFFBOARD** mode with a continuously streamed body-frame velocity setpoint, and flight modes use PX4 names (`POSCTL`, `OFFBOARD`, `AUTO.RTL`, `AUTO.LAND`, etc.).

The intended hardware platform is a **Holybro S500** quadcopter with a **Pixhawk 6C**, which ships with PX4 firmware.

---

## Roadmap

- [ ] **Execute missions** — a "Start Mission" button (AUTO.MISSION) with live waypoint-progress feedback to complete the PLAN tab.
- [ ] **Live video** — real camera/FPV feed into the placeholder camera panels.
- [ ] **Health & failsafe indicators** — battery-low, EKF, and RC-link warnings surfaced in the HUD.
- [ ] **Flight logging** — GCS-side telemetry recording and replay.
- [ ] **Hardware bring-up** — verified flight on the physical S500 / Pixhawk 6C.
- [ ] **Cleanup** — drop legacy dependencies (e.g. `dronekit-sitl`) now that the project runs on PX4 SITL.

---

## License

See [LICENSE](LICENSE).
