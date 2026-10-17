"""Operator status and per-action availability, independent of Qt widgets."""
from dataclasses import dataclass
from typing import Dict, List, Optional

from gcs.telemetry import battery_config, get_stream_freshness


@dataclass(frozen=True)
class ActionState:
    enabled: bool
    reason: str


@dataclass(frozen=True)
class FlightAlert:
    severity: str
    title: str
    detail: str


def flight_status(data: dict, connected: bool, mission_verified: bool = False,
                  now: Optional[float] = None) -> dict:
    fresh = get_stream_freshness(now, data)
    live = connected and fresh['link_state'] in ('HEALTHY', 'DEGRADED')
    armed = bool(data.get('armed'))
    grounded = fresh['landed_valid'] and data.get('landed_state') == 1
    airborne = fresh['landed_valid'] and data.get('landed_state') in (2, 3, 4)
    navigation = fresh['gps_valid'] and fresh['attitude_valid']
    home = bool(data.get('has_home'))
    prearm = data.get('prearm_fail', '')
    batt = data.get('battery', -1)
    volts = data.get('voltage', 0.0)
    cells = max(1, battery_config['cells'])
    critical = fresh['battery_valid'] and (
        0 <= batt <= battery_config['crit_pct'] or
        0 < volts <= cells * battery_config['crit_volt_per_cell'])
    low = fresh['battery_valid'] and (
        0 <= batt <= battery_config['warn_pct'] or
        0 < volts <= cells * battery_config['warn_volt_per_cell'])

    def action(requirements, success):
        for valid, reason in [(live, 'Waiting for a fresh autopilot heartbeat.'), *requirements]:
            if not valid:
                return ActionState(False, reason)
        return ActionState(True, success)

    nav_checks = [(navigation, 'Fresh position, GPS health and attitude are required.')]
    actions: Dict[str, ActionState] = {
        'arm': action([(grounded, 'Fresh confirmation that the vehicle is on the ground is required.'),
                       (not prearm or armed, f'Autopilot prearm: {prearm}'),
                       (fresh['battery_valid'] or armed, 'Battery telemetry is unavailable.'),
                       (not critical or armed, 'Battery is below the critical threshold.')],
                      'Request grounded disarm.' if armed else 'Request arm; autopilot checks still apply.'),
        'takeoff': action([(grounded, 'Takeoff requires confirmed ground state.'), *nav_checks,
                           (fresh['battery_valid'] and not critical, 'Fresh, non-critical battery telemetry is required.'),
                           (not prearm, f'Autopilot prearm: {prearm}')], 'Start takeoff to the selected home-relative altitude.'),
        'hold': action([(armed, 'Vehicle is disarmed.')], 'Request PX4 Hold; acceptance depends on onboard estimates.'),
        'land': action([(armed, 'Vehicle is disarmed.')], 'Request PX4 Land.'),
        'rtl': action([(armed, 'Vehicle is disarmed.'), (home, 'No vehicle-reported home position.'), *nav_checks], 'Request return to vehicle home.'),
        'mode': action([], 'Request selected mode; autopilot validates its prerequisites.'),
        'start': action([(mission_verified, 'Upload and verify this draft on the current vehicle first.'), *nav_checks,
                         (fresh['battery_valid'] and not critical, 'Fresh, non-critical battery telemetry is required.')], 'Request mission start.'),
        'goto': action([(armed, 'Vehicle is disarmed.'), *nav_checks], 'Request reposition to the selected coordinates.'),
        'keyboard': action([(armed, 'Arm the vehicle before enabling keyboard control.'), *nav_checks], 'Opt in to keyboard control.'),
        'cutoff': action([(armed, 'Vehicle is disarmed.')], 'Emergency motor cutoff requires deliberate confirmation.'),
    }
    alerts: List[FlightAlert] = []
    if not connected:
        alerts.append(FlightAlert('neutral', 'Connect a vehicle', 'Choose a MAVLink profile, then connect. Flight actions remain inhibited.'))
    else:
        if not live:
            alerts.append(FlightAlert('danger', 'Vehicle state unconfirmed', 'No fresh autopilot heartbeat. Displayed values are last known; commands are inhibited.'))
        if critical:
            alerts.append(FlightAlert('danger', 'Critical battery', 'Power is below the configured critical threshold. Review landing options.'))
        elif low:
            alerts.append(FlightAlert('warning', 'Low battery', 'Power is below the configured warning threshold.'))
        if prearm:
            alerts.append(FlightAlert('warning', 'Autopilot readiness', prearm))
        for key, title in [('attitude_valid', 'Attitude unavailable'), ('gps_valid', 'Navigation unconfirmed'), ('battery_valid', 'Battery unavailable')]:
            if not fresh[key]:
                alerts.append(FlightAlert('warning', title, 'Required telemetry is missing, invalid or stale. Inspect stream health.'))
        if fresh['link_state'] == 'DEGRADED':
            alerts.append(FlightAlert('warning', 'Telemetry link degraded', 'Heartbeat delay, low receive rate or packet loss detected.'))
        if not alerts:
            alerts.append(FlightAlert('success', 'Telemetry current', 'Review the preflight checklist before flight. Autopilot checks still apply.'))
    return {'freshness': fresh, 'actions': actions, 'alerts': alerts,
            'grounded': grounded, 'airborne': airborne, 'live': live}
