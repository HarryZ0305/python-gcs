# Python MAVLink Ground Control Station (PythonGCS)

A modern, high-performance desktop **Ground Control Station (GCS)** built in Python with **PyQt6** and native **pymavlink**. Engineered for flight controllers running **PX4 Autopilot**, PythonGCS provides situational awareness on par with industry leaders like QGroundControl and Mission Planner: dual-mode aviation Primary Flight Display (PFD), tactical guided flight, aerial survey grid generation, 6-point pre-flight diagnostics, and offline terrain mapping.

Developed and bench-tested against **PX4 SITL** (Gazebo `gz_x500`), targeting a **Holybro S500 / X500** airframe paired with a **Pixhawk 6C** autopilot.

---

## Key Features

### 1. FLY — Situational Awareness & Telemetry
- **Global Mission Flight Ribbon** — QGC-style real-time header displaying vehicle Armed state, Flight Mode, GNSS fix (with satellite count), Battery status & voltage, airborne Flight Timer (`⏱️ MM:SS`), total distance flown (`🚩 m`), emergency `🛑 HOLD`, and master `🔊 VOICE: ON/MUTE`.
- **Aviation Primary Flight Display (PFD) & 3D Attitude** — Switch seamlessly between:
  - **PFD HUD**: Real-time artificial horizon with a pitch ladder (-40° to +40°), bank roll arc with angle pointer, dynamic compass heading tape (with cardinal markers N/E/S/W), airspeed tape, and altitude tape.
  - **3D Model**: Procedural Three.js quadcopter mirroring physical vehicle orientation in radians.
- **Tactical Leaflet Map with Offline Caching** — Embedded vector map featuring:
  - **Directional Drone SVG**: Rotates smoothly with vehicle compass heading.
  - **Live Map Telemetry HUD**: Floating card showing Distance to Home, AGL Altitude, Groundspeed, and Heading.
  - **Home Tracking**: Automatic Home `[H]` marker drop with dynamic bearing line.
  - **Map Tools**: Quick Center on Drone, Auto-Follow toggle (for unrestricted terrain inspection), and Clear Flight Breadcrumbs.
  - **Guided "Fly to Here" Repositioning**: Click anywhere on the map to command a safe reposition setpoint (`MAV_CMD_DO_REPOSITION`) with target pulse marker and altitude confirmation.
  - **⛶ Maximize Map Toggle**: One-click toggle between standard 3-column dashboard and full-width tactical map.
- **Custom Half-Circle Arc Gauges** — High-contrast radial gauges for Altitude (0–120 m), Speed (0–30 m/s), Battery (0–100 %), and GPS Strength (0–20 sats) with adaptive warning colors.
- **Real-Time Historical Trend Plots** — Live strip charts plotting Altitude and Groundspeed over elapsed mission time.
- **6-Point Pre-Flight Safety Verification Modal** — Interactive checklist auditing MAVLink stream health, GNSS 3D fix (min 6 sats), battery power reserve, IMU levelness (±15°), autopilot prearm status, and Home coordinates with a definitive **`GO FOR FLIGHT`** / **`NO-GO`** banner.
- **Emergency Abort / Hold** — Dedicated instant-action hold button that immediately zeroes velocity setpoints and engages `AUTO.LOITER`.
- **Keyboard Flight Controls** — Smooth offboard flying via WASD / QE / IK keys with auto-hover release.
- **3D Google Earth KML & GeoJSON Export** — One-click export of recorded GPS trajectories into 3D extruded ribbons (`.kml`) or GeoJSON for GIS spatial analysis.

### 2. PLAN — Waypoint & Aerial Survey Missions
- **Interactive Waypoint Planning** — Click-to-add waypoints directly on the map connected by dashed flight trajectories.
- **Aerial Survey Grid Generator** — Automatically plans serpentine (lawnmower) flight patterns for photogrammetry, mapping, or search & rescue missions based on custom Width, Height, Lane Spacing, and Altitude.
- **Mission Statistics & Duration Estimator** — Live computation of total planned trajectory distance and estimated flight duration at nominal cruise speed.
- **Configurable Cruising Altitude** — Dedicated altitude spinbox wired directly into the MAVLink mission protocol (`upload_mission`).
- **Import & Export** — Save and load mission plans as `.plan` / `.json` files.

### 3. ANALYTICS – Flight Diagnostics & Sensor Telemetry
- **Dedicated Clean Layout**: Shifted historical telemetry charts and sensor diagnostics from the main dashboard into a focused analytics suite.
- **Real-Time Strip Charts**: Scrolling altitude, groundspeed, and climb rate waveforms.
- **Battery Cell Balance Monitor**: Individual LiPo cell voltages (Cell 1–4) with balance delta tracking.
- **IMU Vibration Clipping**: 3-axis accelerometer and gyro vibration levels with safety thresholds.
- **ESC & Motor Health**: Motor RPM and ESC duty cycle readouts.
- **MAVLink Data Link Diagnostics**: Downlink data rate (kB/s), packet loss percentage, latency, and radio RSSI.

### 4. SETUP — Full Parameter Management
- **Live Parameter Table** — Instant parameter download on connection with real-time text search filtering.
- **Inline Value Editing** — Double-click any value to send a `PARAM_SET` back to the autopilot with automatic integer/float type casting.
- **Backup & Restore** — Save all vehicle parameters to `.param` / `.json` files, or write entire configurations back to the flight controller.

### 4. CONSOLE — Pro MAVLink Engineering Log
- **Decoded Acknowledgment Stream** — Decodes `COMMAND_ACK` and `STATUSTEXT` into plain-English notifications (`ACCEPTED`, `DENIED`, `FAILED`).
- **Search & Categorization** — Filter logs by keyword or category buttons (**`ALL`**, **`ERRORS`**, **`ACKS`**).
- **Color-Coded Feedback** — Red for critical errors, Green for command acks, Sky Blue for autopilot text, and Purple for pilot commands.
- **Auto-Scroll & Clear** — Built-in controls for live mission monitoring.

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Language** | Python 3.10+ |
| **GUI Framework** | PyQt6 (+ PyQt6-WebEngine) |
| **Telemetry & Commands** | Raw `pymavlink` (thread-safe serialization) |
| **Tactical Map** | Leaflet / OpenStreetMap + Offline Tile HTTP Server |
| **Flight Instruments** | HTML5 Canvas (PFD HUD) + Three.js (3D Quad) |
| **Packaging** | PyInstaller (Standalone Windows `.exe`) |
| **Target Firmware** | PX4 Autopilot (v1.14+) |
| **Simulation Airframe** | PX4 SITL Gazebo Harmonic (`gz_x500`) |
| **Target Hardware** | Holybro S500 / X500 + Pixhawk 6C |

---

## Project Structure

```
python-gcs/
├── main.py                     # Entry point: initializes tile server, Qt app, and GUI
├── requirements.txt            # Runtime dependencies
├── requirements-dev.txt        # Development dependencies (PyInstaller)
├── PythonGCS.spec              # PyInstaller Windows packaging specification
├── index.html                  # Product landing and distribution website
└── gcs/
    ├── connection.py           # Non-blocking MAVLink connect worker & telemetry setup
    ├── telemetry.py            # Centralized telemetry store & packet receive loop
    ├── telemetry_logger.py     # Background CSV telemetry logging & trajectory recorder
    ├── commands.py             # Flight commands, guided reposition, offboard streamer, mission protocol
    ├── logs.py                 # Timestamped log buffer
    ├── paths.py                # Asset and font resolution helper
    └── ui/
        ├── gui.py              # Main window, flight ribbon, dialogs, keyboard flight handlers
        ├── gauge.py            # Custom vector half-circle ArcGauge widgets
        ├── map_view.py         # Leaflet tactical map widget (HUD, guided go-to, follow mode)
        ├── tile_server.py      # Local offline tile HTTP server and downloader
        ├── attitude_view.py    # Dual-mode widget: Three.js 3D Quad & Aviation PFD HUD
        ├── console_view.py     # Searchable, categorized MAVLink engineering console
        ├── camera_view.py      # Dual camera feed panels (Front and Bottom view)
        └── setup_view.py       # Live parameter viewer and editor
```

---

## Getting Started

### 1. Prerequisites
- Python 3.10+
- PX4 Autopilot simulator (**PX4 SITL**) or a physical PX4 flight controller (**Pixhawk 6C**).

### 2. Installation
```bash
git clone https://github.com/HarryZ0305/python-gcs.git
cd python-gcs
pip install -r requirements.txt
```

### 3. Launch the Simulator
From a built [PX4-Autopilot](https://github.com/PX4/PX4-Autopilot) source tree:
```bash
make px4_sitl gz_x500          # Add HEADLESS=1 to run without the Gazebo window
```
Or run headless via Docker:
```bash
docker run --rm -it -p 14540:14540/udp jonasvautherin/px4-gazebo-headless:1.16.1
```
*PX4 exposes MAVLink on UDP **14540** (offboard/API port) and **14550** (QGroundControl).*

### 4. Run the GCS
```bash
python main.py
```
Leave the connection string at default (`udpin:0.0.0.0:14540`) and click **CONNECT**. The ribbon, gauges, and map will populate within seconds.

---

## Keyboard Flight Controls

When **Enable Keyboard Flight** is checked on the FLY tab:

| Key | Action |
|---|---|
| `W` / `S` | Move Forward / Backward (vx ±2.0 m/s) |
| `A` / `D` | Move Left / Right (vy ∓2.0 m/s) |
| `Q` / `E` | Yaw Rotate Left / Right (yaw_rate ∓0.5 rad/s) |
| `I` / `K` | Climb Up / Descend Down (vz ∓1.5 m/s) |
| `Space` or `H` | Zero velocities and **HOVER** in place |

---

## Pre-Flight & Guided Flight Workflow

1. **Connect**: Click **CONNECT** to establish MAVLink heartbeat.
2. **Pre-Flight Verification**: Click **📋 PRE-FLIGHT CHECKLIST** in the left panel to verify telemetry rate, GPS 3D fix, battery power, and attitude horizon.
3. **Arm & Takeoff**: Click **ARM**, choose your altitude preset (e.g., `5m` or `10m`), and click **TAKEOFF**.
4. **Guided Go-To**: On the map, click **FLY TO HERE**, click anywhere on the satellite view, and confirm the dialog to have the vehicle navigate and hold at that target coordinate.
5. **Aviation PFD**: In the attitude card, toggle between **3D MODEL** and **PFD HUD** to monitor bank angle, pitch ladder, and compass ribbon.
6. **Return Home**: Click **RTL** to bring the drone back to launch coordinates, or **HOLD** for immediate loiter.
7. **Export Log**: In the map toolbar, click **🌐 EXPORT FLIGHT TRAIL** to save your flight trajectory as a Google Earth 3D `.kml` or `.geojson` file.

---

## Standalone Windows Executable

To compile a standalone zero-dependency Windows `.exe`:
```bash
pip install -r requirements-dev.txt
pyinstaller PythonGCS.spec
```
The compiled executable will be located in `dist/PythonGCS/PythonGCS.exe`.

---

## License

Released under the [MIT License](LICENSE).
