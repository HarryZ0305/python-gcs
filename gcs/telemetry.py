import time
import queue
import threading
import uuid
import struct
import math
from typing import Optional, Dict, Any, Set, Tuple
from pymavlink import mavutil
from gcs.logs import log
from gcs.params import decode_param_value, PARAM_TYPE_NAMES, PARAM_TYPE_REAL32
from gcs.command_manager import command_manager

HEARTBEAT_TIMEOUT_SEC = 3.0

mission_queue = queue.Queue()

parameters_lock = threading.Lock()
parameters_data: Dict[str, dict] = {} # {param_name: {'value': val, 'raw_value': raw, 'type': type, 'index': idx, 'count': count, 'status': str}}
param_download_stats = {
    'total_count': 0,
    'received_indices': set(),
    'missing_indices': set(),
    'is_complete': False,
    'last_request_time': 0.0
}

class TelemetrySession:
    """Manages lifecycle of a telemetry connection session to prevent stale thread races."""
    def __init__(self, session_id: Optional[str] = None):
        self.session_id = session_id or str(uuid.uuid4())
        self.is_active = True

    def cancel(self):
        self.is_active = False

_active_session_obj: Optional[TelemetrySession] = None
_active_session_id: Optional[str] = None
_session_lock = threading.Lock()

battery_config = {
    'cells': 4,
    'warn_volt_per_cell': 3.5,
    'crit_volt_per_cell': 3.3,
    'warn_pct': 25,
    'crit_pct': 15
}

telemetry_data = {
    'sysid': 1,
    'compid': 1,
    'lat': 0.0,
    'lon': 0.0,
    'alt': 0.0,               # Altitude relative to home/launch (meters)
    'alt_amsl': 0.0,          # Altitude above mean sea level (meters)
    'groundspeed': 0.0,
    'throttle': 0,
    'battery': -1,            # -1 indicates unknown/uninitialized
    'voltage': 0.0,
    'satellites': 0,
    'fix_type': 0,
    'eph': 9999,
    'armed': False,
    'roll': 0.0,              # Radians
    'pitch': 0.0,             # Radians
    'yaw': 0.0,               # Radians
    'mode': 'UNKNOWN',
    'wp_current': -1,
    'last_heartbeat_time': 0.0, # Wall time for UI display
    'last_heartbeat_monotonic': 0.0, # Monotonic time for safety checks
    'prearm_fail': '',
    'system_status': 0,       # 0: UNINIT, 1: BOOT, 2: CALIBRATING, 3: STANDBY, 4: ACTIVE, etc.
    'landed_state': 0,        # 0: Undefined, 1: On ground, 2: In air, 3: Takeoff, 4: Landing
    'has_home': False,
    'home_lat': 0.0,
    'home_lon': 0.0,
    'home_alt': 0.0,
    'sensors_present': 0,
    'sensors_enabled': 0,
    'sensors_health': 0,
    'battery_cells': [],
    'vibration': (0.0, 0.0, 0.0),
    'clipping': (0, 0, 0),
    'packet_loss_pct': 0.0,
    'message_rate_hz': 0.0,
    'packets_received': 0,
    'packets_lost': 0,
    'autopilot_version': 'Unknown'
}

# Link statistics tracking
link_stats = {
    'last_seq': None,
    'packets_received': 0,
    'packets_dropped': 0,
    'packet_loss_pct': 0.0,
    'rate_timer': 0.0,
    'rate_count': 0,
    'message_rate_hz': 0.0,
}

# Per-source sequence tracking: (sys_id, comp_id) -> stats
_source_seq_trackers: Dict[Tuple[int, int], dict] = {}

def start_telemetry_session() -> TelemetrySession:
    global _active_session_obj, _active_session_id
    with _session_lock:
        if _active_session_obj is not None:
            _active_session_obj.cancel()
        _active_session_obj = TelemetrySession()
        _active_session_id = _active_session_obj.session_id
        reset_telemetry_data()
        return _active_session_obj

def create_new_session() -> str:
    session = start_telemetry_session()
    return session.session_id

def is_session_active(session_id: str) -> bool:
    with _session_lock:
        if _active_session_obj and _active_session_obj.session_id == session_id:
            return _active_session_obj.is_active
        return _active_session_id == session_id

def cancel_current_session():
    global _active_session_obj, _active_session_id
    with _session_lock:
        if _active_session_obj is not None:
            _active_session_obj.cancel()
            _active_session_obj = None
        _active_session_id = None
        reset_telemetry_data()

def is_heartbeat_stale(timeout_sec: float = HEARTBEAT_TIMEOUT_SEC) -> bool:
    last_mono = telemetry_data.get('last_heartbeat_monotonic', 0.0)
    if last_mono <= 0.0:
        return True
    return (time.monotonic() - last_mono) > timeout_sec

def reset_telemetry_data():
    telemetry_data['armed'] = False
    telemetry_data['mode'] = 'DISCONNECTED'
    telemetry_data['last_heartbeat_time'] = 0.0
    telemetry_data['last_heartbeat_monotonic'] = 0.0
    telemetry_data['prearm_fail'] = ''
    telemetry_data['system_status'] = 0
    telemetry_data['landed_state'] = 0
    telemetry_data['battery'] = -1
    telemetry_data['voltage'] = 0.0
    telemetry_data['satellites'] = 0
    telemetry_data['fix_type'] = 0
    telemetry_data['has_home'] = False
    telemetry_data['home_lat'] = 0.0
    telemetry_data['home_lon'] = 0.0
    telemetry_data['home_alt'] = 0.0
    telemetry_data['packet_loss_pct'] = 0.0
    telemetry_data['message_rate_hz'] = 0.0
    telemetry_data['packets_received'] = 0
    telemetry_data['packets_lost'] = 0

    link_stats['last_seq'] = None
    link_stats['packets_received'] = 0
    link_stats['packets_dropped'] = 0
    link_stats['packet_loss_pct'] = 0.0
    link_stats['rate_timer'] = 0.0
    link_stats['rate_count'] = 0
    link_stats['message_rate_hz'] = 0.0

    _source_seq_trackers.clear()
    
    with parameters_lock:
        parameters_data.clear()
        param_download_stats['total_count'] = 0
        param_download_stats['received_indices'].clear()
        param_download_stats['missing_indices'].clear()
        param_download_stats['is_complete'] = False

    while not mission_queue.empty():
        try:
            mission_queue.get_nowait()
        except queue.Empty:
            break

    command_manager.clear()

def is_vehicle_airborne() -> bool:
    landed_state = telemetry_data.get('landed_state', 0)
    if landed_state in (2, 3): # IN_AIR or TAKEOFF
        return True
    if landed_state == 1:      # Confirmed ON_GROUND
        return False
    # Fallback heuristic: armed with altitude > 0.8m
    if telemetry_data.get('armed', False) and telemetry_data.get('alt', 0.0) > 0.8:
        return True
    return False

def handle_mavlink_message(msg, vehicle=None, target_system: int = 1):
    """
    Process a single MAVLink message, updating telemetry_data, parameters, command acks, etc.
    Calculates packet loss per source (src_sys, src_comp) to prevent multi-source sequence corruption.
    """
    if not msg:
        return False

    src_sys = msg.get_srcSystem() if hasattr(msg, 'get_srcSystem') else getattr(msg, '_header', {}).srcSystem
    src_comp = msg.get_srcComponent() if hasattr(msg, 'get_srcComponent') else getattr(msg, '_header', {}).srcComponent

    # Filter messages from other systems if target is known
    target_sys = telemetry_data.get('sysid', target_system)
    if target_sys != 0 and src_sys != 0 and src_sys != target_sys:
        return False

    # Track sequence loss strictly PER SOURCE
    seq = None
    if hasattr(msg, 'get_seq'):
        seq = msg.get_seq()
    elif hasattr(msg, '_header') and hasattr(msg._header, 'seq'):
        seq = msg._header.seq

    now_mono = time.monotonic()

    if seq is not None:
        src_key = (src_sys, src_comp)
        if src_key not in _source_seq_trackers:
            _source_seq_trackers[src_key] = {
                'last_seq': None,
                'packets_received': 0,
                'packets_dropped': 0,
                'packet_loss_pct': 0.0
            }
        tracker = _source_seq_trackers[src_key]

        last_seq = tracker['last_seq']
        if last_seq is not None:
            expected = (last_seq + 1) % 256
            diff = (seq - expected) % 256
            if 0 < diff < 50:
                tracker['packets_dropped'] += diff
        tracker['last_seq'] = seq
        tracker['packets_received'] += 1

        total = tracker['packets_received'] + tracker['packets_dropped']
        if total > 0:
            tracker['packet_loss_pct'] = (tracker['packets_dropped'] / total) * 100.0

        # Update active autopilot stats
        autopilot_comps = (mavutil.mavlink.MAV_COMP_ID_AUTOPILOT1, 1)
        if src_comp in autopilot_comps:
            link_stats['last_seq'] = tracker['last_seq']
            link_stats['packets_received'] = tracker['packets_received']
            link_stats['packets_dropped'] = tracker['packets_dropped']
            link_stats['packet_loss_pct'] = tracker['packet_loss_pct']
            telemetry_data['packet_loss_pct'] = tracker['packet_loss_pct']
            telemetry_data['packets_received'] = tracker['packets_received']
            telemetry_data['packets_lost'] = tracker['packets_dropped']

        link_stats['rate_count'] += 1
        if link_stats['rate_timer'] == 0.0:
            link_stats['rate_timer'] = now_mono
        elif now_mono - link_stats['rate_timer'] >= 1.0:
            dt = now_mono - link_stats['rate_timer']
            link_stats['message_rate_hz'] = link_stats['rate_count'] / dt
            telemetry_data['message_rate_hz'] = link_stats['message_rate_hz']
            link_stats['rate_timer'] = now_mono
            link_stats['rate_count'] = 0

    msg_type = msg.get_type()

    if msg_type == 'HEARTBEAT':
        # Ignore heartbeats from non-autopilot components (e.g. comp_id 197 companion, 200 camera)
        autopilot_comps = (mavutil.mavlink.MAV_COMP_ID_AUTOPILOT1, 1)
        if src_comp not in autopilot_comps and getattr(msg, 'autopilot', 0) == 0:
            return False

        autopilot_types = (
            getattr(mavutil.mavlink, 'MAV_TYPE_QUADROTOR', 2),
            getattr(mavutil.mavlink, 'MAV_TYPE_HEXAROTOR', 13),
            getattr(mavutil.mavlink, 'MAV_TYPE_OCTOROTOR', 14),
            getattr(mavutil.mavlink, 'MAV_TYPE_GENERIC', 0),
            getattr(mavutil.mavlink, 'MAV_TYPE_FIXED_WING', 1),
            getattr(mavutil.mavlink, 'MAV_TYPE_VTOL_TAILSITTER_DUOROTOR', 19),
            getattr(mavutil.mavlink, 'MAV_TYPE_VTOL_TAILSITTER_QUADROTOR', 20),
            getattr(mavutil.mavlink, 'MAV_TYPE_VTOL_TILTROTOR', 21)
        )
        if getattr(msg, 'type', 0) in autopilot_types or getattr(msg, 'autopilot', 0) == mavutil.mavlink.MAV_AUTOPILOT_PX4 or src_comp in autopilot_comps:
            telemetry_data['last_heartbeat_time'] = time.time()
            telemetry_data['last_heartbeat_monotonic'] = now_mono
            telemetry_data['system_status'] = getattr(msg, 'system_status', 0)
            telemetry_data['armed'] = bool(
                msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED
            )
            if telemetry_data['armed']:
                telemetry_data['prearm_fail'] = ''
            # Decode flight mode: Support PX4 custom modes directly
            custom_mode = getattr(msg, 'custom_mode', 0)
            main_mode = (custom_mode >> 16) & 0xFF
            sub_mode = (custom_mode >> 24) & 0xFF

            mode_str = None
            if vehicle and hasattr(vehicle, 'mode_mapping'):
                mapping = vehicle.mode_mapping()
                if mapping:
                    for name, mid in mapping.items():
                        if isinstance(mid, tuple) and len(mid) == 3:
                            if mid[1] == main_mode and mid[2] == sub_mode:
                                mode_str = name
                                break
                        elif isinstance(mid, int) and mid == main_mode and sub_mode == 0:
                            mode_str = name
                            break

            if not mode_str:
                px4_modes = {
                    (1, 0): 'MANUAL',
                    (2, 0): 'ALTCTL',
                    (3, 0): 'POSCTL',
                    (4, 1): 'AUTO.READY',
                    (4, 2): 'TAKEOFF',
                    (4, 3): 'LOITER',
                    (4, 4): 'MISSION',
                    (4, 5): 'RTL',
                    (4, 6): 'LAND',
                    (4, 7): 'RTGS',
                    (4, 8): 'FOLLOWME',
                    (4, 9): 'PRECLAND',
                    (5, 0): 'ACRO',
                    (6, 0): 'OFFBOARD',
                    (7, 0): 'STABILIZED',
                    (8, 0): 'RATTITUDE'
                }
                mode_str = px4_modes.get((main_mode, sub_mode))

            if mode_str:
                telemetry_data['mode'] = mode_str
            elif vehicle and hasattr(vehicle, 'flightmode') and vehicle.flightmode != 'UNKNOWN':
                telemetry_data['mode'] = vehicle.flightmode

    elif msg_type == 'GLOBAL_POSITION_INT':
        telemetry_data['lat'] = msg.lat / 1e7
        telemetry_data['lon'] = msg.lon / 1e7
        telemetry_data['alt'] = msg.relative_alt / 1000.0   # Relative to home
        telemetry_data['alt_amsl'] = msg.alt / 1000.0      # AMSL

    elif msg_type == 'VFR_HUD':
        telemetry_data['groundspeed'] = msg.groundspeed
        telemetry_data['throttle'] = msg.throttle

    elif msg_type == 'SYS_STATUS':
        batt_rem = msg.battery_remaining
        if batt_rem < 0 or batt_rem > 100:
            telemetry_data['battery'] = -1
        else:
            telemetry_data['battery'] = batt_rem

        volt_raw = msg.voltage_battery
        if volt_raw == 65535 or volt_raw <= 0:
            telemetry_data['voltage'] = 0.0
        else:
            telemetry_data['voltage'] = volt_raw / 1000.0

        telemetry_data['sensors_present'] = msg.onboard_control_sensors_present
        telemetry_data['sensors_enabled'] = msg.onboard_control_sensors_enabled
        telemetry_data['sensors_health'] = msg.onboard_control_sensors_health

    elif msg_type == 'BATTERY_STATUS':
        voltages = getattr(msg, 'voltages', [])
        valid_cells = [v / 1000.0 for v in voltages if v > 0 and v != 65535]
        if valid_cells:
            telemetry_data['battery_cells'] = valid_cells

    elif msg_type == 'VIBRATION':
        telemetry_data['vibration'] = (
            getattr(msg, 'vibration_x', 0.0),
            getattr(msg, 'vibration_y', 0.0),
            getattr(msg, 'vibration_z', 0.0)
        )
        telemetry_data['clipping'] = (
            getattr(msg, 'clipping_0', 0),
            getattr(msg, 'clipping_1', 0),
            getattr(msg, 'clipping_2', 0)
        )

    elif msg_type == 'AUTOPILOT_VERSION':
        fw_ver = getattr(msg, 'flight_sw_version', 0)
        major = (fw_ver >> 24) & 0xFF
        minor = (fw_ver >> 16) & 0xFF
        patch = (fw_ver >> 8) & 0xFF
        telemetry_data['autopilot_version'] = f"v{major}.{minor}.{patch}"

    elif msg_type == 'GPS_RAW_INT':
        telemetry_data['satellites'] = msg.satellites_visible
        telemetry_data['fix_type'] = msg.fix_type
        telemetry_data['eph'] = msg.eph

    elif msg_type == 'ATTITUDE':
        telemetry_data['roll'] = msg.roll
        telemetry_data['pitch'] = msg.pitch
        telemetry_data['yaw'] = msg.yaw

    elif msg_type == 'EXTENDED_SYS_STATE':
        telemetry_data['landed_state'] = getattr(msg, 'landed_state', 0)

    elif msg_type == 'HOME_POSITION':
        telemetry_data['has_home'] = True
        telemetry_data['home_lat'] = msg.latitude / 1e7
        telemetry_data['home_lon'] = msg.longitude / 1e7
        telemetry_data['home_alt'] = msg.altitude / 1000.0

    elif msg_type == 'STATUSTEXT':
        text_bytes = getattr(msg, 'text', b'')
        if isinstance(text_bytes, bytes):
            txt = text_bytes.decode('utf-8', errors='ignore').strip('\x00').strip()
        else:
            txt = str(text_bytes).strip()
        log(f"FCU: {txt}")
        txt_upper = txt.upper()
        if "PREFLIGHT FAIL" in txt_upper or "ARMING DENIED" in txt_upper or (not telemetry_data['armed'] and ("FAIL" in txt_upper or "ERROR" in txt_upper or "REJECTED" in txt_upper)):
            reason = txt
            if "Preflight Fail:" in reason:
                reason = reason.replace("Preflight Fail:", "").strip()
            telemetry_data['prearm_fail'] = reason

    elif msg_type == 'PARAM_VALUE':
        param_id = msg.param_id
        if isinstance(param_id, bytes):
            param_id = param_id.decode('utf-8', errors='ignore')
        param_name = param_id.split('\x00')[0]

        decoded_val = decode_param_value(msg.param_value, msg.param_type)
        
        with parameters_lock:
            parameters_data[param_name] = {
                'value': decoded_val,
                'raw_value': msg.param_value,
                'type': msg.param_type,
                'type_name': PARAM_TYPE_NAMES.get(msg.param_type, f"TYPE_{msg.param_type}"),
                'index': msg.param_index,
                'count': msg.param_count,
                'status': 'confirmed',
                'timestamp': now_mono
            }
            param_download_stats['total_count'] = msg.param_count
            param_download_stats['received_indices'].add(msg.param_index)
            if len(param_download_stats['received_indices']) >= msg.param_count and msg.param_count > 0:
                param_download_stats['is_complete'] = True

    elif msg_type in ['MISSION_REQUEST', 'MISSION_REQUEST_INT', 'MISSION_ACK', 'MISSION_COUNT', 'MISSION_ITEM_INT', 'MISSION_ITEM']:
        mission_queue.put(msg)

    elif msg_type == 'COMMAND_ACK':
        command_manager.handle_ack(msg)

    elif msg_type == 'MISSION_CURRENT':
        if telemetry_data.get('wp_current') != msg.seq:
            telemetry_data['wp_current'] = msg.seq
            log(f"Active waypoint updated: WP {msg.seq}")

    return True

def read_telemetry(vehicle, session_id: Optional[str] = None):
    if session_id is None:
        session = start_telemetry_session()
        session_id = session.session_id

    target_system = getattr(vehicle, 'target_system', 1)
    target_component = getattr(vehicle, 'target_component', 1)

    log(f"Telemetry reader started for session {session_id[:8]} (Target Sys: {target_system}, Comp: {target_component})")

    while is_session_active(session_id):
        try:
            msg = vehicle.recv_match(
                type=[
                    'GLOBAL_POSITION_INT', 'VFR_HUD', 'SYS_STATUS', 'GPS_RAW_INT',
                    'HEARTBEAT', 'STATUSTEXT', 'ATTITUDE', 'MISSION_REQUEST',
                    'MISSION_REQUEST_INT', 'MISSION_ACK', 'PARAM_VALUE',
                    'COMMAND_ACK', 'MISSION_CURRENT', 'EXTENDED_SYS_STATE',
                    'HOME_POSITION', 'AUTOPILOT_VERSION', 'BATTERY_STATUS', 'VIBRATION',
                    'MISSION_COUNT', 'MISSION_ITEM_INT', 'MISSION_ITEM'
                ],
                blocking=True,
                timeout=2.0
            )

            if not is_session_active(session_id):
                break

            if not msg:
                if is_heartbeat_stale(3.0):
                    if telemetry_data['mode'] != 'LINK LOST':
                        log("Warning: Heartbeat timeout (>3s). Link degraded.")
                continue

            handle_mavlink_message(msg, vehicle=vehicle, target_system=target_system)

        except Exception as e:
            if not is_session_active(session_id):
                break
            log(f"Telemetry error: {e}")
            time.sleep(0.5)

    log(f"Telemetry reader stopped for session {session_id[:8]}")

def wait_for_arm(timeout=10):
    log("Waiting for drone to arm...")
    start_time = time.monotonic()
    while True:
        if telemetry_data['armed']:
            log("Drone is armed!")
            return True
        if time.monotonic() - start_time > timeout:
            log("Timeout! Drone did not arm")
            return False
        time.sleep(0.2)

def wait_for_altitude(target_alt, tolerance=0.95, timeout=30):
    log(f"Waiting to reach {target_alt}m...")
    start_time = time.monotonic()
    while True:
        current_alt = telemetry_data['alt']
        if current_alt >= target_alt * tolerance:
            log(f"Target altitude reached ({current_alt:.1f}m)!")
            return True
        if time.monotonic() - start_time > timeout:
            log("Timeout! Could not reach target altitude")
            return False
        time.sleep(0.5)

def wait_for_gps(timeout=60):
    log("Waiting for 3D GPS fix...")
    start_time = time.monotonic()
    while True:
        if telemetry_data['fix_type'] >= 3 and telemetry_data['satellites'] >= 6:
            sats = telemetry_data['satellites']
            log(f"3D GPS fix acquired ({sats} satellites)!")
            return True
        if time.monotonic() - start_time > timeout:
            log("Timeout! Could not acquire GPS fix.")
            return False
        time.sleep(0.5)
