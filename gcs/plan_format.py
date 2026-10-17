import json
import math
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

    try:
        if isinstance(data, dict) and data.get('fileType') == 'Plan':
            if data.get('version', 1) != 1 or data.get('mission', {}).get('version', 2) != 2:
                raise ValueError('Unsupported QGC plan/mission version.')
            fence = data.get('geoFence', {})
            if fence.get('circles') or fence.get('polygons') or data.get('rallyPoints', {}).get('points'):
                raise ValueError('This editor cannot preserve geofences or rally points. Import cancelled.')
            wps, takeoff, landing, alt = decode_supported_items(data.get('mission', {}).get('items', []))
            return True, wps, takeoff, landing, alt, f'Imported supported QGC mission ({len(wps)} waypoints).'
        if isinstance(data, dict) and 'waypoints' in data:
            wps = [validate_coordinates(wp) for wp in data['waypoints']]
            takeoff = validate_coordinates(data['takeoff']) if data.get('takeoff') else None
            landing = validate_coordinates(data['landing']) if data.get('landing') else None
            if landing and landing[2] != 0:
                raise ValueError('Landing altitude must be zero relative to home in this editor.')
            return True, wps, takeoff, landing, wps[0][2] if wps else 10.0, f'Imported Legacy Plan ({len(wps)} waypoints)'
        raise ValueError('Unrecognized plan file schema.')
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError) as error:
        return False, [], None, None, 10.0, f'Import cancelled: {error}'


def validate_coordinates(coord):
    if not isinstance(coord, (list, tuple)) or len(coord) not in (2, 3):
        raise ValueError('Each mission coordinate must contain latitude, longitude and optional altitude.')
    if any(isinstance(value, bool) for value in coord):
        raise ValueError('Coordinates must be numeric, not boolean.')
    lat, lon = float(coord[0]), float(coord[1])
    alt = float(coord[2]) if len(coord) == 3 else 10.0
    if not all(math.isfinite(value) for value in (lat, lon, alt)):
        raise ValueError('Mission coordinates and altitude must be finite.')
    if not -90 <= lat <= 90 or not -180 <= lon <= 180 or not 0 <= alt <= 150:
        raise ValueError('Latitude/longitude out of range or altitude outside the editor limit (0–150 m relative to home).')
    return [lat, lon, alt]


def decode_supported_items(items):
    """Reject missions whose meaning the simple editor cannot preserve."""
    if not isinstance(items, list):
        raise ValueError('Mission items must be a list.')
    wps, takeoff, landing, default_alt = [], None, None, 10.0
    for index, item in enumerate(items):
        if not isinstance(item, dict) or item.get('type', 'SimpleItem') != 'SimpleItem':
            raise ValueError(f'Item {index + 1}: complex items are unsupported; no items were imported.')
        command = item.get('command')
        if command not in (16, 21, 22):
            raise ValueError(f'Item {index + 1}: unsupported command {command}; no items were skipped.')
        if item.get('frame') not in (3, 6):
            raise ValueError(f'Item {index + 1}: only home-relative altitude frames are supported.')
        params = item.get('params', [])
        if not isinstance(params, list) or len(params) != 7:
            raise ValueError(f'Item {index + 1}: expected seven MAVLink parameters.')
        if item.get('autoContinue', True) is not True and item.get('autoContinue') != 1:
            raise ValueError(f'Item {index + 1}: manual continuation is unsupported.')
        # Holding, custom yaw, acceptance/turn radii and pitch cannot be edited
        # losslessly by the coordinate-only mission model.
        if any(float(params[i] or 0) != 0 for i in (0, 2)):
            raise ValueError(f'Item {index + 1}: custom hold/pitch/turn parameters are unsupported.')
        if float(params[1] or 0) not in ((0, 2) if command == 16 else (0,)):
            raise ValueError(f'Item {index + 1}: custom acceptance radius is unsupported.')
        if params[3] is not None and not math.isnan(float(params[3])):
            raise ValueError(f'Item {index + 1}: explicit yaw cannot be preserved by this editor.')
        coord = validate_coordinates(params[4:7])
        if command == 22:
            if index != 0:
                raise ValueError('Takeoff is supported only as the first mission item.')
            takeoff = coord
        elif command == 21:
            if index != len(items) - 1 or coord[2] != 0:
                raise ValueError('Landing must be the final item at zero home-relative altitude.')
            landing = coord
        else:
            wps.append(coord)
            default_alt = coord[2]
    return wps, takeoff, landing, default_alt


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
