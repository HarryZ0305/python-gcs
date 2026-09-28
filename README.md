# Python GCS — Professional Autonomous Ground Control Station for PX4

A modern, high-performance desktop Ground Control Station (GCS) engineered natively for **PX4 Autopilot** and MAVLink multirotors. Built with **Python 3**, **PyQt6**, and raw **pymavlink**, PythonGCS provides a responsive, flight-safety-first pilot interface targeting PX4 SITL (`gz_x500`) and Holybro S500 / Pixhawk 6C platforms.

![PythonGCS Screenshot](design/GCS%20Prototype%201.png)

---

## Key Capabilities

### 1. FLY — Tactical Operations & Manual/Offboard Flight
- **Connection Profiles**: Instant switching between PX4 SITL UDP (`udpin:0.0.0.0:14540`), QGroundControl UDP (`udpin:0.0.0.0:14550`), TCP (`tcp:127.0.0.1:5760`), and Serial Radio (`com3:57600`).
- **Interactive Leaflet Tactical Map**: Real-time GPS positioning, heading orientation, home position marker, deduplicated trajectory trail, and follow-drone mode.
- **Guided Fly-To (Reposition)**: Click anywhere on the map to dispatch verified `MAV_CMD_DO_REPOSITION` commands with launch-relative altitude hold.
- **Offboard & Keyboard Flying**: Rate-controlled 10 Hz setpoint streaming in `BODY_NED` with zero-velocity warmup, dead-man freshness timeout (0.5s auto-hover), and instant zeroing on focus loss or key release.
- **Airborne Disarm Guard**: Ordinary disarm is blocked while the vehicle is in flight (`landed_state` check); deliberate two-step confirmation required for in-flight emergency cutoff.
- **Emergency Abort / Hold**: One-click instant loiter (`AUTO.LOITER`) that immediately halts all velocity targets.
- **3D Attitude Visualizer**: Real-time 3D quadcopter view powered by Three.js with roll, pitch, and yaw readouts.
- **Evidence-Based Pre-Flight Checklist**: Strict verification of GNSS 3D fix, telemetry age/rate, `SYS_STATUS` sensor health bits (Gyro, Accel, Mag, Baro), power voltage thresholds, and confirmed home lock. Distinguishes PASS, FAIL, and UNKNOWN (UNKNOWN never yields "GO FOR FLIGHT").
- **Flight Trail Export**: One-click export of recorded trajectories to standard Google Earth 3D `.kml` or GeoJSON `.geojson` with truthful launch-relative altitude references.

### 2. PLAN — Autonomous Missions & Survey Grids
- **Standard QGroundControl `.plan` Support**: Full bidirectional import and export compatibility with QGC `.plan` (v1.0 schema) and legacy JSON plans.
- **Interactive Waypoint Editor**: Add, reorder (Move Up / Down), edit altitude per waypoint, or delete waypoints.
- **Aerial Survey Grid Generator**: Auto-generates serpentine lawnmower photogrammetry flight lines from Width, Height, Lane Spacing, and Altitude parameters without duplicating takeoff/landing points.
- **PX4 Mission Protocol Compliance**: Sequence index 0 represents the first actual mission item (no fake Home waypoint). Uses `MISSION_COUNT` transactions without premature clear, handling retransmissions and readback verification.
- **Mission Statistics & Duration Estimator**: Real-time calculation of total flight trajectory length and estimated mission duration at nominal cruise speed.

### 3. ANALYTICS — Flight Telemetry & Diagnostics
- **Real-Time Scrolling Strip Charts**: Live altitude and groundspeed waveforms plotted at high frequency.
- **MAVLink Link Quality Diagnostics**: Downlink telemetry rate (Hz), measured packet loss percentage (tracked from MAVLink sequence counters), and total packets received/lost.
- **Power Telemetry**: Total battery voltage, remaining percentage, throttle percentage, and individual cell balance readouts (when `BATTERY_STATUS` telemetry is broadcast by the vehicle).
- **Sensor Health Readouts**: `SYS_STATUS` subsystem health and 3-axis vibration/clipping monitors (when `VIBRATION` telemetry is broadcast).

### 4. SETUP — Live PX4 Parameter Management
- **Type-Safe Wire Encoding**: Encodes and decodes PX4 `INT32` parameters using bit-wise packing in the 32-bit float wire field (`struct.unpack('<i', struct.pack('<f', wire_val))[0]`), preserving integer bits without float loss.
- **Live Search & Filter**: Real-time parameter search across all onboard flight controller parameters.
- **Readback Confirmation**: Edits are marked `PENDING` until confirmed by a matching `PARAM_VALUE` readback from the flight controller. Reverts on timeout or rejection.
- **Backup & Restore with Difference Preview**: Save complete vehicle configurations to JSON or `.param` files. Restoring displays a visual difference preview (Current FCU vs File Target) before writing.
- **Missing Parameter Recovery**: Identifies unreceived parameter indices and requests missing entries.

### 5. CONSOLE — Decoded MAVLink Stream
- **Decoded Command Acknowledgments**: Translates `COMMAND_ACK` into plain-English notifications (`ACCEPTED`, `TEMPORARILY_REJECTED`, `DENIED`, `FAILED`, `IN_PROGRESS`).
- **Autopilot Notifications**: Captures and categorizes `STATUSTEXT` messages from the autopilot.
- **Search & Categorization**: Filter logs by keyword or category buttons (**ALL**, **ERRORS**, **ACKS**).

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Language** | Python 3.9+ |
| **GUI Framework** | PyQt6 (+ PyQt6-WebEngine) |
| **Telemetry & Commands** | Raw `pymavlink` (thread-safe serialization with `mav_lock`) |
| **Tactical Map** | Leaflet / OpenStreetMap + Local Offline HTTP Tile Server / MBTiles |
| **Attitude View** | Three.js (3D Quad) |
| **Packaging** | PyInstaller (Standalone Windows `.exe`) |
| **Target Firmware** | PX4 Autopilot (v1.14+) |
| **Simulation Airframe** | PX4 SITL Gazebo Harmonic (`gz_x500`) |
| **Target Hardware** | Holybro S500 / X500 + Pixhawk 6C |

---

## Getting Started

### 1. Prerequisites
- Python 3.9+
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
make px4_sitl gz_x500
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
Leave the connection profile at default (`PX4 SITL (UDP 14540)`) and click **CONNECT**. The ribbon pills, gauges, and tactical map will populate within seconds.

---

## Keyboard Flight Controls

When **Enable Keyboard Flight** is checked on the FLY tab:

| Key | Action | Velocity Target |
|---|---|---|
| `W` / `S` | Move Forward / Backward | $v_x = \pm 2.0\text{ m/s}$ |
| `A` / `D` | Move Left / Right | $v_y = \mp 2.0\text{ m/s}$ |
| `Q` / `E` | Yaw Rotate Left / Right | $r = \mp 0.5\text{ rad/s}$ |
| `I` / `K` | Climb Up / Descend Down | $v_z = \mp 1.5\text{ m/s}$ (NED: $-1.5$ is climb) |
| `Space` or `H` | Zero velocities and **HOVER** | $v_x = 0, v_y = 0, v_z = 0, r = 0$ |

*Safety Dead-Man Timer: If key updates cease for >0.5 seconds, or if the window loses focus, velocities automatically reset to zero (hover).*

---

## Offline Map Tile System & MBTiles

- **On-Demand Caching**: As you pan and zoom while connected to the internet, map tiles are automatically cached on disk at `~/.python-gcs/tile_cache/`.
- **Policy Compliance**: In adherence with the [OpenStreetMap Foundation Tile Usage Policy](https://operations.osmfoundation.org/policies/tiles/), automated bulk scraping/prefetching of OSM tile servers is disabled.
- **MBTiles Support**: For 100% offline field deployments without internet access, click **LOAD OFFLINE MBTILES** to load pre-generated `.mbtiles` raster map packages (e.g. from OpenMapTiles, TileMill, or QGIS).

---

## Standalone Windows Executable

To compile a standalone zero-dependency Windows `.exe`:
```bash
pip install -r requirements-dev.txt
pyinstaller PythonGCS.spec
```
The compiled executable will be located in `dist/PythonGCS/PythonGCS.exe`.

---

## Automated Test Suite

Run the full automated test suite using `pytest`:
```bash
pytest tests/ -v
```

---

## License

Released under the [MIT License](LICENSE).
