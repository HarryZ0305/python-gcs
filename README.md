# Python GCS — Professional Autonomous Ground Control Station for PX4

A modern, high-performance desktop Ground Control Station (GCS) engineered natively for **PX4 Autopilot** and MAVLink multirotors. Built with **Python 3**, **PyQt6**, **pyqtgraph**, and raw **pymavlink**, PythonGCS provides a responsive, flight-safety-first pilot interface targeting PX4 SITL (`gz_x500`) and Holybro S500 / Pixhawk 6C platforms.

---

## Architecture & Workspaces

PythonGCS organizes tactical workflows into five dedicated, purpose-built workspaces:

### 1. FLY — Tactical Operations & Picture-in-Picture Workspace
- **Aviation-Grade Primary Flight Display (PFD)**: High-performance 2D PFD rendered at 30 Hz via native `QPainter` with artificial horizon, pitch ladder, roll bank pointer, rolling airspeed/altitude tapes, heading compass ribbon, vertical speed/climb rate indicator, and 1-click toggle to 3D CAD visualization.
- **Picture-in-Picture (PiP) Workspace**: Dominant tactical map with floating live video feed. Supports instant 1-click swap (video primary / map inset), double-click maximize, and minimize.
- **Off-Thread Video Pipeline**: Dedicated background capture worker (`VideoCaptureWorker`) keeping RTSP, UDP, HTTP, USB, and synthetic test streams off the Qt GUI thread. Includes honest stream states (`DISCONNECTED`, `CONNECTING`, `LIVE`, `STALE`, `FAILED`, `TEST_PATTERN`), watchdog freeze detection, and OSD telemetry HUD overlays.
- **Per-Stream Telemetry Freshness**: Monotonic receipt timestamp tracking per stream (`GPS`, `ATTITUDE`, `BATTERY`, `VFR`). Stale or unavailable streams display explicit `--` or warning badges rather than deceptive zeroes. Active heartbeats never mask frozen sensor streams.
- **Contextual Control Safeguards**: Dynamic per-action evaluation. Airborne disarm protection blocks ordinary motor cutoff while in flight; deliberate two-step confirmation required for in-flight emergency cutoff.
- **Opt-In Keyboard Flying Safeguards**: Rate-controlled 10 Hz setpoint streaming in `BODY_NED` with zero-velocity warmup. Accidental input is blocked by comprehensive focus checks (typing in textboxes, spinboxes, or dialogs never commands motion), window deactivation zeroing, and dead-man timeout (0.5s auto-hover).
- **Evidence-Based Pre-Flight Checklist**: Strict verification of GNSS 3D fix, telemetry freshness, sensor health bits (`SYS_STATUS`), battery voltage, and home lock. Distinguishes `PASS`, `FAIL`, and `UNKNOWN` (missing evidence never yields "GO FOR FLIGHT").

### 2. PLAN — Synchronized Autonomous Mission Planner
- **Synchronized Map & Table Editor**: Add, select, drag, reorder (Move Up / Down), and delete mission items with visual waypoint selection.
- **Local Edit Undo / Redo**: 30-step historical undo/redo stack for local mission drafts.
- **QGroundControl `.plan` Compatibility**: Bi-directional import and export adhering to published QGC schema (v1.0 schema / mission v2). Accurately reports and preserves unsupported commands without silent corruption.
- **Mission Statistics & Energy Estimator**: Accurate 3D trajectory distance calculation, flight time estimation at nominal cruise speed, and battery energy draw (Wh) with explicit assumptions.
- **Verifiable Vehicle Synchronization**: Differentiates `LOCAL DRAFT`, `UNSAVED CHANGES`, `UPLOADING TO FCU`, `FCU MISSION VERIFIED`, and `LOCAL / FCU MISMATCH`. Clearing a local draft is strictly separated from clearing the vehicle's onboard mission.
- **Survey Grid Generator**: Auto-generates photogrammetry serpentine lawnmower flight lines from width, height, lane spacing, and altitude parameters.

### 3. VEHICLE SETUP — Live PX4 Parameter Management
- **Type-Safe Wire Encoding**: Encodes and decodes PX4 `INT32` parameters using bit-wise packing in the 32-bit float wire field (`struct.unpack('<i', struct.pack('<f', wire_val))[0]`), preserving integer bits without float loss.
- **Live Search & Filter**: Real-time parameter search across all onboard flight controller parameters.
- **Readback Confirmation**: Edits are marked `PENDING` until confirmed by a matching `PARAM_VALUE` readback from the flight controller. Reverts on timeout or rejection.
- **Backup & Restore with Difference Preview**: Save complete vehicle configurations to JSON or `.param` files. Restoring displays a visual difference preview (Current FCU vs File Target) before writing.

### 4. ANALYZE — Flight Telemetry & Diagnostics
- **Multi-Signal Telemetry Plots**: High-frequency pyqtgraph waveforms with user-selectable signals (Altitude, Groundspeed, Climb Rate, Battery Voltage, Packet Loss).
- **Synchronized Flight Event Timeline**: Flight mode transitions, arm/disarm actions, and MAVLink command outcomes timestamped and aligned with telemetry.
- **Flight Data Export**: One-click export to CSV for post-flight analysis.
- **Protected Flight Replay**: Log playback mode clearly badged as REPLAY with vehicle command dispatch strictly locked out for operator safety.

### 5. SETTINGS — Ground Station Preferences
- **Appearance & Themes**: Instant toggle between Cockpit Dark Mode (field-optimized) and Aviation Light Mode (direct sunlight).
- **Video Stream Configuration**: Configurable RTSP, UDP, HTTP, USB camera index, or test pattern stream.
- **Battery Chemistry Presets**: Configurable LiPo cell count (1S through 12S) and per-cell warning/critical voltage thresholds.
- **Offline Maps & MBTiles**: Browse and mount offline `.mbtiles` raster packages or reset to cached OpenStreetMap.

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Language** | Python 3.9+ |
| **GUI Framework** | PyQt6 (+ PyQt6-WebEngine for Tactical Leaflet Map) |
| **Telemetry & Commands** | Raw `pymavlink` (thread-safe serialization with `mav_lock`) |
| **Flight Instruments** | Native 2D `QPainter` (30 Hz PFD) + Three.js (Optional 3D CAD) |
| **Video Stream Pipeline** | OpenCV (`cv2`) in background worker thread with OSD HUD |
| **Tactical Map** | Leaflet / OpenStreetMap + Local Offline HTTP Tile Server / MBTiles |
| **Plotting & Analytics** | `pyqtgraph` |
| **Packaging** | PyInstaller (Standalone Windows `.exe`) |
| **Target Firmware** | PX4 Autopilot (v1.14+) |
| **Simulation Airframe** | PX4 SITL Gazebo Harmonic (`gz_x500`) |
| **Target Hardware** | Holybro S500 / X500 + Pixhawk 6C |

---

## Getting Started

### 1. Prerequisites
- Python 3.9+
- PX4 Autopilot simulator (**PX4 SITL**) or physical PX4 flight controller (**Pixhawk 6C**).

### 2. Installation
```bash
git clone https://github.com/HarryZ0305/python-gcs.git
cd python-gcs
pip install -r requirements.txt
```

### 3. Launch PX4 SITL Simulator
From a built [PX4-Autopilot](https://github.com/PX4/PX4-Autopilot) source tree:
```bash
make px4_sitl gz_x500
```
Or run headless via Docker:
```bash
docker run --rm -it -p 14540:14540/udp jonasvautherin/px4-gazebo-headless:1.16.1
```
*PX4 exposes MAVLink on UDP port **14540** (offboard/API port) and **14550** (QGroundControl).*

### 4. Run PythonGCS
```bash
python main.py
```
Leave the connection profile at default (`PX4 SITL (UDP 14540)`) and click **CONNECT**. The ribbon status pills, cockpit PFD, and tactical map will populate immediately.

---

## Keyboard Flight Controls

When **Enable Keyboard Flight Control** is checked on the FLY tab:

| Key | Action | Velocity Target |
|---|---|---|
| `W` / `S` | Move Forward / Backward | $v_x = \pm 2.0\text{ m/s}$ |
| `A` / `D` | Move Left / Right | $v_y = \mp 2.0\text{ m/s}$ |
| `Q` / `E` | Yaw Rotate Left / Right | $r = \mp 0.5\text{ rad/s}$ |
| `I` / `K` | Climb Up / Descend Down | $v_z = \mp 1.0\text{ m/s}$ (NED: $-1.0$ is climb) |
| `Space` or `H` | Zero velocities and **HOVER** | $v_x = 0, v_y = 0, v_z = 0, r = 0$ |

*Safety Safeguards: Dead-man timer ceases velocity commands if key releases for >0.5s. Typing in input fields or dialogs never commands motion. Focus loss or window deactivation instantly commands zero velocity.*

---

## Standalone Windows Executable

To compile a standalone zero-dependency Windows executable:
```bash
pip install -r requirements-dev.txt
pyinstaller PythonGCS.spec
```
The compiled binary will be placed in `dist/PythonGCS/PythonGCS.exe`.

---

## Automated Test Suite

Run the full automated test suite using `pytest`:
```bash
pytest tests/ -v
```

---

## License

Released under the [MIT License](LICENSE).
