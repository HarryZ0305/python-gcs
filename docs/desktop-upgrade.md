# Desktop workspace and reliability upgrade

## Implementation

The desktop app now separates connection controls from vehicle status. A persistent
preflight entry, larger home-relative readouts, a scrollable action rail, independent
stream-health indicators and a collapsed diagnostics drawer preserve map space.
Video starts disconnected; the test feed is explicitly selected in Settings. The
optional 3D view loads on demand. Appearance, connection preferences and validated
battery alert limits persist with QSettings.

`gcs/flight_state.py` supplies both button availability and command-handler guards.
Missing heartbeats inhibit actions even when the last state was armed and airborne.
Hold and Land remain available on a live link when GPS stops; the autopilot decides
whether it can accept them. Grounded disarm requires fresh landed-state telemetry.
Battery alerts evaluate both voltage and percentage. Vehicle home comes only from
HOME_POSITION. Reposition requests require explicit target confirmation.

GPS receiver health and fused vehicle position have separate timestamps. Reconnect
clears every telemetry field, including identity, coordinates, sensor bits and cells.
Receive handlers validate their session under the lock used to replace it; UI reads
use snapshots. GCS heartbeats run independently of Offboard setpoint streaming.

Mission workers return results to the Qt thread. Results belong to a specific vehicle
generation and draft signature. Editing a verified draft immediately inhibits start;
disconnect invalidates verification. Readback verifies command parameters, frame,
continuation, coordinates and altitude. Unspecified yaw is sent as NaN instead of
silently commanding north. An ACK is labelled acknowledged, not physical completion.

The simple editor supports home-relative takeoff/waypoint/landing missions. Complex
items, unsupported commands/frames, custom yaw, fences and rally points cancel import
atomically. Landing stays at zero relative altitude. The unused AMSL selector was
removed and the table is read-only; its altitude editor updates the real model.
Mission duration/energy estimates expose their assumptions in a tooltip.

Camera source changes are asynchronous, discard old-source results, and retain workers
until completion. Network decoding uses bounded FFmpeg open/read timeouts. OpenCV is
optional; actual codec/backend compatibility still needs testing. Analytics keeps
all signal arrays aligned when its bounded history rolls over. Historical plots are
labelled log review, separate from live vehicle controls.

## Run and test

```powershell
python -m pip install -r requirements.txt -r requirements-dev.txt
python main.py
```

The app opens disconnected. Optional camera decoding requires `opencv-python` in the
same environment. The existing `PythonGCS.spec` includes the new modules through normal
imports and preserves bundled map assets.

Baseline: 46 tests passed at commit `8ed81eb`. The final local suite passes **78 tests**
on Windows with Python 3.9. Compilation and whitespace checks also pass. New regressions cover link loss,
individually frozen streams, cancelled commands, old-session packets, nondefault
vehicle IDs, mission semantics, editing during upload, Qt-thread download application,
settings persistence, camera replacement and analytics rollover.

The UDP integration test sends real encoded MAVLink heartbeat, position, GPS and
attitude packets from system ID 42 through `connect()` and `read_telemetry()`.
This is protocol integration coverage, **not PX4 simulation**. Local UDP sockets must
be permitted; restricted execution environments may require a network-enabled test run.

```powershell
$env:QT_QPA_PLATFORM='offscreen'
$env:QTWEBENGINE_CHROMIUM_FLAGS='--no-sandbox --disable-gpu'
$env:QTWEBENGINE_DISABLE_SANDBOX='1'
python -m pytest tests -q
python -m compileall -q gcs tools
```

These flags are for headless testing, not normal flight operation. Windows CI runs
the regression suite in `.github/workflows/tests.yml`.

## Visual verification

```powershell
python tools/capture_workspace.py --output artifacts/preview
```

This portable utility replaces the previous script's hardcoded Antigravity output
directory. It renders the actual Qt app in disconnected, labelled read-only sample,
stale-stream, planning and settings states without creating a vehicle transport.
Samples are layout fixtures, not flight evidence. Use native Windows Qt for font
inspection: its offscreen plugin exposes no font database.

In this restricted host, the native WebEngine GPU compositor produced blank regions
in widget captures even when JavaScript confirmed Leaflet and the map initialized.
Map/video visual acceptance therefore remains necessary in a normal graphics session.
Leaflet JS/CSS is bundled inline so essential map initialization has no external-script
or local-HTTP dependency. Basemap imagery still requires cached tiles or MBTiles.

## Remaining flight acceptance

PX4 SITL/Gazebo and hardware flight behavior were not validated in this session.
Before hardware use, verify on the intended PX4 release:

1. Connect/reconnect/reboot, vehicle identity, HOME_POSITION and stream freshness.
2. Prearm failures, arm, takeoff, Hold, RTL, Land and confirmed grounded disarm.
3. Keyboard opt-in, focus/tab changes, key release, and Offboard-loss failsafe.
4. Mission transfer/readback/execution, modified drafts and reconnect.
5. Delayed/missing ACKs, partial telemetry failures, low battery and link recovery.
6. Actual RTSP/USB start, source replacement and shutdown with installed codecs.
7. Offline MBTiles, Windows DPI scaling, theme changes and packaged startup.

This change does not implement terrain following, geofence editing, calibration
wizards, full QGC ComplexItem support or complete flight-log replay. The existing
trajectory recording/export path still needs an end-to-end recording audit. GCS
battery alert settings do not configure PX4 failsafes. Tests and sample screenshots
do not establish flight readiness.

## Protocol references

- [MAVLink ACK semantics](https://mavlink.io/en/services/command.html)
- [MAVLink messages and mission parameters](https://mavlink.io/en/messages/common.html)
- [QGroundControl Fly](https://docs.qgroundcontrol.com/Stable_V5.1/en/qgc-user-guide/fly_view/fly_view.html)
- [QGroundControl Plan](https://docs.qgroundcontrol.com/Stable_V5.1/en/qgc-user-guide/plan_view/plan_view.html)
- [PX4 Offboard](https://docs.px4.io/main/en/flight_modes/offboard.html)
