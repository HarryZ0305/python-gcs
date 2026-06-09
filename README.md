# Custom Python MAVLink Ground Control Station (GCS)

A modern, high-performance desktop Ground Control Station (GCS) built in Python using PyQt6 and raw `pymavlink`. It connects to flight controllers running the PX4 Autopilot firmware, supporting real-time telemetry updates, interactive waypoint-based mission planning, and parameters management.

---

## Key Features

### 1. Telemetry and Flight View (FLY Tab)
- **Vibrant HUD & Instrument Panel**: Live updates for Battery state, system voltage, GPS lock type, satellites count, Groundspeed, Altitude, Pitch, Roll, and Heading.
- **Interactive Leaflet Map**: Embeds a Leaflet-based OpenStreetMap inside a `QWebEngineView`, tracking the drone's coordinates and drawing its flight trail.
- **3D Attitude Widget**: A custom 3D projection rendering pitch and roll changes in real time.
- **Dual Camera Widgets**: Placeholder grids layout representing Front and Bottom perspective feeds.
- **Command Acknowledgment Log**: Intercepts `COMMAND_ACK` MAVLink messages and translates their integer response codes (e.g., `ACCEPTED`, `TEMPORARILY_REJECTED`, `DENIED`, `FAILED`) into logs on the screen, removing "blind command syndrome".

### 2. Asynchronous Connection Panel
- **Non-Blocking GUI**: Establishes connections in a background `QThread` (`ConnectionWorker`) to keep the PyQt main event loop responsive.
- **Configurable Connection Input**: Custom input string (defaults to `udpin:0.0.0.0:14540` for local UDP port connections).
- **Status Indicators**: Visual connection state indicators ("CONNECTED" in green, "CONNECTING..." in yellow, "DISCONNECTED" in red).
- **Safety Lockouts**: Disables flight commands, takeoff actions, and parameter grids when offline, enabling them dynamically once a verified connection handshake occurs.

### 3. Mission Planning (PLAN Tab)
- **Click-to-Add Flight Paths**: Click directly on the map to define waypoints, drawing a yellow dashed path representation.
- **Sync Map**: Synchronize waypoints from the Leaflet javascript context into the GCS PyQt widget state.
- **Upload Protocol**: Uploads coordinates to the autopilot using the MAVLink mission protocol transaction sequence, automatically mapping `seq=0` to the Home position and shifting path points to `seq=1..N`.

### 4. Parameter Management (SETUP Tab)
- **Live Search & Filter**: Instant search filter to query parameters from the autopilot.
- **Inline Table Editing**: Double-click any value to change a parameter. The GCS parses the type (real, integer) and sends the `PARAM_SET` message back to the drone.
- **Signal Protection**: Blocks internal change triggers during programmatic table refreshes to prevent infinite parameter loops.

---

## Directory Structure

```
python-gcs/
│
├── main.py              # Application entry point, launches the GUI
├── connection.py        # MAVLink socket utilities (connect, rate configuration)
├── commands.py          # Autopilot control commands (Arm, Modes, Missions, Parameters)
├── telemetry.py         # Threaded loop for intercepting and sorting incoming MAVLink packets
├── logs.py              # Global GCS log buffer utility
├── requirements.txt     # Python module dependencies
│
└── ui/                  # PyQt6 Desktop Widgets
    ├── gui.py           # Main Window container, tabs structure, layouts and callbacks
    ├── map_view.py      # Leaflet OpenStreetMap integrations
    ├── attitude_view.py # Heading & pitch/roll indicator
    ├── setup_view.py    # Setup tab: parameter management QTableWidget
    ├── camera_view.py   # Telemetry video feed layouts
    └── console_view.py  # System warning log console widget
```

---

## Installation & Setup

### Prerequisites
- Python 3.9+
- A PX4 SITL environment (running in Gazebo/WSL/Docker) OR the included mock simulator script.

### Install Dependencies
Install PyQt6 and pymavlink dependencies:
```bash
pip install -r requirements.txt
```

---

## Quick Start & Usage

### 1. Launch a Simulator
To run the custom GCS, you need a MAVLink source broadcasting heartbeats. 

#### Option A: Running the Mock Simulator (Headless)
If you do not have Gazebo or a real drone configured, you can run the mock simulator script which creates a simulated drone locally on port 14540:
```bash
python .gemini/antigravity-ide/brain/6078a24e-7960-45f3-88ba-4f4629fc7379/scratch/mock_sim.py
```

#### Option B: Running PX4 Gazebo SITL
Launch your local PX4 SITL simulation. It will automatically broadcast telemetry packets over UDP port `14540`.

### 2. Launch the Ground Control Station
Run the main script:
```bash
python main.py
```

### 3. Flight Sequence
Once the GCS window is open:
1. Input `udpin:0.0.0.0:14540` (or your target port) and click **CONNECT**. The connection status will update to green `CONNECTED`.
2. Wait until the **GPS Fix** status says `3D` (usually takes 15-30 seconds for simulation GPS filters to lock).
3. Set your target altitude (e.g. `10`) in the spinbox and click **TAKEOFF**. The console will report:
   - `Command 400 ACK: ACCEPTED` (Arm command accepted)
   - `Command 22 ACK: ACCEPTED` (Takeoff command accepted)
4. Watch the Altitude telemetry rise to 10m.
5. In the Mode dropdown, select **OFFBOARD** and click **SET MODE**.
6. Use the manual control buttons (**FORWARD**, **YAW L**, **YAW R**) to send body-frame offboard velocity vector commands to the drone.
7. Click **RTL** (Return to Launch) or **LAND** to retrieve the vehicle.
