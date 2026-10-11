import json
from typing import List, Optional, Tuple, Dict, Any

MAV_CMD_NAV_WAYPOINT = 16
MAV_CMD_NAV_TAKEOFF = 22
MAV_CMD_NAV_LAND = 21
MAV_FRAME_GLOBAL_RELATIVE_ALT = 3

# Published QGroundControl Plan Schema constants
QGC_PLAN_VERSION = 1
QGC_MISSION_VERSION = 2
QGC_GEOFENCE_VERSION = 2
QGC_RALLY_VERSION = 2
QGC_ALTITUDE_MODE_RELATIVE = 1

def export_qgc_plan(
    filename: str,
    waypoints: List[List[float]],
    takeoff_point: Optional[List[float]] = None,
    landing_point: Optional[List[float]] = None,
    target_alt: float = 10.0,
    cruise_speed: float = 5.0,
    planned_home: Optional[List[float]] = None
) -> bool:
    """
    Exports a plan adhering strictly to published QGroundControl .plan schema (v1.0 / mission v2).
    Includes all mandatory schema attributes:
    - Top level: fileType, version, groundStation, mission, geoFence, rallyPoints
    - Mission: version, cruiseSpeed, hoverSpeed, plannedHomePosition, vehicleType, globalPlanAltitudeMode, items
    - SimpleItem: command, frame, params (7 fields), autoContinue, type, doJumpId, Altitude, AltitudeMode, AMSLAltAboveTerrain
    """
    items = []
    do_jump_id = 1

    # Home position
    home_coord = planned_home or (takeoff_point[:2] if takeoff_point else (waypoints[0][:2] if waypoints else [0.0, 0.0]))
    home_alt = 0.0

    # 1. Takeoff item if present
    if takeoff_point:
        t_alt = float(takeoff_point[2] if len(takeoff_point) > 2 else target_alt)
        items.append({
            "autoContinue": True,
            "command": MAV_CMD_NAV_TAKEOFF,
            "frame": MAV_FRAME_GLOBAL_RELATIVE_ALT,
            "params": [0.0, 0.0, 0.0, None, float(takeoff_point[0]), float(takeoff_point[1]), t_alt],
            "type": "SimpleItem",
            "doJumpId": do_jump_id,
            "Altitude": t_alt,
            "AltitudeMode": QGC_ALTITUDE_MODE_RELATIVE,
            "AMSLAltAboveTerrain": None
        })
        do_jump_id += 1

    # 2. Waypoints
    for wp in waypoints:
        w_alt = float(wp[2] if len(wp) > 2 else target_alt)
        items.append({
            "autoContinue": True,
            "command": MAV_CMD_NAV_WAYPOINT,
            "frame": MAV_FRAME_GLOBAL_RELATIVE_ALT,
            "params": [0.0, 2.0, 0.0, None, float(wp[0]), float(wp[1]), w_alt],
            "type": "SimpleItem",
            "doJumpId": do_jump_id,
            "Altitude": w_alt,
            "AltitudeMode": QGC_ALTITUDE_MODE_RELATIVE,
            "AMSLAltAboveTerrain": None
        })
        do_jump_id += 1

    # 3. Landing item if present
    if landing_point:
        items.append({
            "autoContinue": True,
            "command": MAV_CMD_NAV_LAND,
            "frame": MAV_FRAME_GLOBAL_RELATIVE_ALT,
            "params": [0.0, 0.0, 0.0, None, float(landing_point[0]), float(landing_point[1]), 0.0],
            "type": "SimpleItem",
            "doJumpId": do_jump_id,
            "Altitude": 0.0,
            "AltitudeMode": QGC_ALTITUDE_MODE_RELATIVE,
            "AMSLAltAboveTerrain": None
        })
        do_jump_id += 1

    plan_obj = {
        "fileType": "Plan",
        "version": QGC_PLAN_VERSION,
        "groundStation": "PythonGCS",
        "mission": {
            "version": QGC_MISSION_VERSION,
            "cruiseSpeed": float(cruise_speed),
            "hoverSpeed": 3.0,
            "globalPlanAltitudeMode": QGC_ALTITUDE_MODE_RELATIVE,
            "plannedHomePosition": [float(home_coord[0]), float(home_coord[1]), float(home_alt)],
            "vehicleType": 2, # MAV_TYPE_QUADROTOR
            "items": items
        },
        "geoFence": {
            "circles": [],
            "polygons": [],
            "version": QGC_GEOFENCE_VERSION
        },
        "rallyPoints": {
            "points": [],
            "version": QGC_RALLY_VERSION
        }
    }

    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(plan_obj, f, indent=2)
    return True

def import_plan_file(filename: str) -> Tuple[bool, List[List[float]], Optional[List[float]], Optional[List[float]], float, str]:
    """
    Imports a mission plan from either QGC .plan format (v1.0 schema) or legacy PythonGCS format.
    Returns (success, waypoints, takeoff_point, landing_point, default_alt, message).
    """
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        return False, [], None, None, 10.0, f"Failed to parse file: {e}"

    # Format 1: QGroundControl .plan
    if isinstance(data, dict) and data.get("fileType") == "Plan":
        mission = data.get("mission", {})
        raw_items = mission.get("items", [])
        wps = []
        takeoff = None
        landing = None
        detected_alt = 10.0

        unsupported_cmds = []
        for item in raw_items:
            cmd = item.get("command")
            params = item.get("params", [])
            item_alt = item.get("Altitude")
            if len(params) >= 7:
                lat = params[4]
                lon = params[5]
                alt = params[6] if params[6] is not None else item_alt

                if lat is None or lon is None:
                    continue

                if alt is not None:
                    detected_alt = float(alt)
                else:
                    alt = detected_alt

                if cmd == MAV_CMD_NAV_TAKEOFF and takeoff is None and not wps:
                    takeoff = [float(lat), float(lon), float(alt)]
                elif cmd == MAV_CMD_NAV_LAND:
                    landing = [float(lat), float(lon), float(alt)]
                elif cmd in (MAV_CMD_NAV_WAYPOINT, MAV_CMD_NAV_TAKEOFF):
                    wps.append([float(lat), float(lon), float(alt)])
                else:
                    unsupported_cmds.append(cmd)

        msg = f"Imported QGC Plan ({len(wps)} waypoints)"
        if unsupported_cmds:
            msg += f". Note: {len(unsupported_cmds)} unsupported command(s) skipped: {set(unsupported_cmds)}"

        return True, wps, takeoff, landing, detected_alt, msg

    # Format 2: Legacy PythonGCS {takeoff, waypoints, landing}
    if isinstance(data, dict) and "waypoints" in data:
        wps = data.get("waypoints", [])
        takeoff = data.get("takeoff")
        landing = data.get("landing")
        alt = 10.0
        if wps and len(wps[0]) > 2:
            alt = wps[0][2]
        return True, wps, takeoff, landing, float(alt), f"Imported Legacy Plan ({len(wps)} waypoints)"

    return False, [], None, None, 10.0, "Unrecognized plan file schema"


def calculate_mission_stats(
    waypoints: List[List[float]],
    takeoff_point: Optional[List[float]] = None,
    landing_point: Optional[List[float]] = None,
    cruise_speed: float = 5.0
) -> Dict[str, Any]:
    """
    Calculates 3D distance, estimated flight time, and energy requirements.
    Explicitly provides the estimation assumptions to avoid operator confusion.
    """
    import math
    from gcs.telemetry_logger import haversine_distance

    coords = []
    if takeoff_point:
        coords.append(takeoff_point)
    coords.extend(waypoints)
    if landing_point:
        coords.append(landing_point)

    if not coords:
        return {
            'item_count': 0,
            'total_distance_m': 0.0,
            'est_flight_time_s': 0.0,
            'est_energy_wh': 0.0,
            'max_altitude_m': 0.0,
            'assumptions': "No mission items"
        }

    total_dist = 0.0
    for i in range(len(coords) - 1):
        c1, c2 = coords[i], coords[i + 1]
        h_dist = haversine_distance(c1[0], c1[1], c2[0], c2[1])
        alt1 = c1[2] if len(c1) > 2 else 10.0
        alt2 = c2[2] if len(c2) > 2 else 10.0
        v_dist = abs(alt2 - alt1)
        total_dist += math.sqrt(h_dist ** 2 + v_dist ** 2)

    cruise_speed = max(1.0, float(cruise_speed))
    est_flight_time = total_dist / cruise_speed
    # Estimate energy (150 W nominal draw for standard 4S multirotor)
    est_energy_wh = (est_flight_time / 3600.0) * 150.0
    max_alt = max([c[2] if len(c) > 2 else 10.0 for c in coords])

    return {
        'item_count': len(coords),
        'total_distance_m': total_dist,
        'est_flight_time_s': est_flight_time,
        'est_energy_wh': est_energy_wh,
        'max_altitude_m': max_alt,
        'assumptions': f"Assumes {cruise_speed:.1f} m/s cruise and 150W avg electrical draw"
    }
