import json
from typing import List, Optional, Tuple, Dict, Any

MAV_CMD_NAV_WAYPOINT = 16
MAV_CMD_NAV_TAKEOFF = 22
MAV_CMD_NAV_LAND = 21
MAV_FRAME_GLOBAL_RELATIVE_ALT = 3

def export_qgc_plan(
    filename: str,
    waypoints: List[List[float]],
    takeoff_point: Optional[List[float]] = None,
    landing_point: Optional[List[float]] = None,
    target_alt: float = 10.0,
    cruise_speed: float = 5.0,
    planned_home: Optional[List[float]] = None
) -> bool:
    """Exports a plan to standard QGroundControl .plan (v1.0 JSON format)."""
    items = []

    # Home position
    home_coord = planned_home or (takeoff_point[:2] if takeoff_point else (waypoints[0][:2] if waypoints else [0.0, 0.0]))
    home_alt = 0.0

    # 1. Takeoff item if present
    if takeoff_point:
        t_alt = takeoff_point[2] if len(takeoff_point) > 2 else target_alt
        items.append({
            "autoContinue": True,
            "command": MAV_CMD_NAV_TAKEOFF,
            "frame": MAV_FRAME_GLOBAL_RELATIVE_ALT,
            "params": [0.0, 0.0, 0.0, None, takeoff_point[0], takeoff_point[1], float(t_alt)],
            "type": "SimpleItem"
        })

    # 2. Waypoints
    for wp in waypoints:
        w_alt = wp[2] if len(wp) > 2 else target_alt
        items.append({
            "autoContinue": True,
            "command": MAV_CMD_NAV_WAYPOINT,
            "frame": MAV_FRAME_GLOBAL_RELATIVE_ALT,
            "params": [0.0, 2.0, 0.0, None, wp[0], wp[1], float(w_alt)],
            "type": "SimpleItem"
        })

    # 3. Landing item if present
    if landing_point:
        items.append({
            "autoContinue": True,
            "command": MAV_CMD_NAV_LAND,
            "frame": MAV_FRAME_GLOBAL_RELATIVE_ALT,
            "params": [0.0, 0.0, 0.0, None, landing_point[0], landing_point[1], 0.0],
            "type": "SimpleItem"
        })

    plan_obj = {
        "fileType": "Plan",
        "version": 1,
        "groundStation": "PythonGCS",
        "mission": {
            "cruiseSpeed": float(cruise_speed),
            "hoverSpeed": 3.0,
            "items": items,
            "plannedHomePosition": [float(home_coord[0]), float(home_coord[1]), float(home_alt)],
            "vehicleType": 2 # MAV_TYPE_QUADROTOR
        },
        "geoFence": {"circles": [], "polygons": [], "version": 2},
        "rallyPoints": {"points": [], "version": 2}
    }

    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(plan_obj, f, indent=2)
    return True

def import_plan_file(filename: str) -> Tuple[bool, List[List[float]], Optional[List[float]], Optional[List[float]], float, str]:
    """
    Imports a mission plan from either QGC .plan format or legacy PythonGCS format.
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

        for item in raw_items:
            cmd = item.get("command")
            params = item.get("params", [])
            if len(params) >= 7:
                lat = params[4]
                lon = params[5]
                alt = params[6] if params[6] is not None else 10.0

                if lat is None or lon is None:
                    continue

                detected_alt = float(alt)
                if cmd == MAV_CMD_NAV_TAKEOFF and takeoff is None and not wps:
                    takeoff = [float(lat), float(lon), float(alt)]
                elif cmd == MAV_CMD_NAV_LAND:
                    landing = [float(lat), float(lon), float(alt)]
                elif cmd in (MAV_CMD_NAV_WAYPOINT, MAV_CMD_NAV_TAKEOFF):
                    wps.append([float(lat), float(lon), float(alt)])

        return True, wps, takeoff, landing, detected_alt, f"Imported QGC Plan ({len(wps)} waypoints)"

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
