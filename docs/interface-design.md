# Focused flight workspace

The desktop interface prioritizes flying and monitoring. Configuration, detailed
telemetry and analysis have their own views. The default palette uses ivory,
warm gray and sage with distinct caution and emergency colors.

## Established ground station comparison

| Reference pattern | PythonGCS implementation |
| --- | --- |
| QGroundControl: map and essential flight information dominate Fly | A narrow attitude/action rail, four primary readouts, and a large map |
| QGroundControl: additional flight actions are contextual | Mode selection, keyboard opt-in and voice controls open from **More flight controls** |
| QGroundControl: video is an optional flight view | Video starts hidden; **Show video** reveals it, and selecting a source opens it automatically |
| Mission Planner: detailed status and tuning are secondary | **Diagnostics** contains stream health, live plots and command acknowledgements |
| Mission Planner: secondary windows support another display | Diagnostics can detach into a second window; closing it restores the same widgets and their history |

References: [QGroundControl Fly View](https://docs.qgroundcontrol.com/Stable_V4.4/en/qgc-user-guide/fly_view/fly_view.html)
and [Mission Planner Flight Data](https://ardupilot.org/planner/docs/mission-planner-ground-control-station.html).
These are interface references, not a claim of feature parity or certification.

## Navigation

| View | Purpose |
| --- | --- |
| Fly | Attitude, altitude, speed, climb, home distance, map and essential commands |
| Plan | Mission editing, survey generation, transfer and readback verification |
| Vehicle | Live parameter search, edits and configuration backup/restore |
| Analyze | Telemetry trends, event timeline and CSV review/export |
| Settings | Appearance, camera source, offline maps and battery alert preferences |
| Diagnostics | Stream freshness, vehicle/session details, plots, ACK log and trail export |

Connection profiles and raw transport addresses open in **Connection…**. A
disconnected Fly workspace provides a direct **Connect vehicle** action.
Preflight is always available in the header. Positive routine status stays in
the header; warning and danger banners remain visible above all workspaces.

Hold, Return, Land and the confirmed emergency motor stop remain directly
accessible in Fly. Layout changes do not bypass command availability checks,
mission verification, airborne disarm protection or keyboard focus safeguards.
Leaving Fly clears keyboard input as before.

## Validation

- 81 regression tests pass, including navigation ownership, restoring detached
  diagnostics, and restoring the map when video is hidden.
- The native Windows interface was rendered and inspected at 1366 × 768 and
  1920 × 1080 logical pixels, plus its separate diagnostics window.
- Screenshots show the actual disconnected UI; they do not represent a live flight.
- [Fly screenshot](../design/fly-workspace.png) and
  [Diagnostics screenshot](../design/diagnostics-workspace.png).

This finalizes the desktop design pass. Operational acceptance and the remaining
protocol/flight limitations are documented in [desktop-upgrade.md](desktop-upgrade.md).
