import time
import math
import threading
from typing import Tuple, Optional, List, Dict, Any
from pymavlink import mavutil
from gcs.logs import log
from gcs.params import encode_param_value, decode_param_value, PARAM_TYPE_REAL32, PARAM_TYPE_INT32
from gcs.command_manager import command_manager, CommandAlreadyPendingError

mav_lock = threading.Lock()
upload_lock = threading.Lock()

class OffboardController:
    """
    Thread-safe, rate-controlled offboard streamer for PX4.
    Adheres strictly to PX4 offboard requirements:
    1. Stream setpoints at >=2Hz (using 10Hz) before switching to OFFBOARD.
    2. Maintain continuous stream while OFFBOARD is active.
    3. Dead-man timeout: if user inputs stop for >500ms, auto-zero velocities to hover.
    4. Synchronized resets on mode change, key release, focus loss, or emergency hold.
    """
    def __init__(self):
        self._lock = threading.Lock()
        self.vehicle = None
        self.target_vx = 0.0
        self.target_vy = 0.0
        self.target_vz = 0.0
        self.target_yaw_rate = 0.0
        self.last_command_time = 0.0
        self.dead_man_timeout = 0.5 # seconds
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self, vehicle):
        with self._lock:
            self.vehicle = vehicle
            self._stop_event.clear()
            self.target_vx = 0.0
            self.target_vy = 0.0
            self.target_vz = 0.0
            self.target_yaw_rate = 0.0
            self.last_command_time = time.monotonic()
            
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._stream_loop, daemon=True)
                self._thread.start()
        log("OffboardController: Streamer thread started.")

    def stop(self):
        with self._lock:
            self._stop_event.set()
            self.vehicle = None
            self.target_vx = 0.0
            self.target_vy = 0.0
            self.target_vz = 0.0
            self.target_yaw_rate = 0.0
        log("OffboardController: Streamer stopped.")

    def set_velocity(self, vx: float = 0.0, vy: float = 0.0, vz: float = 0.0, yaw_rate: float = 0.0):
        with self._lock:
            self.target_vx = float(vx)
            self.target_vy = float(vy)
            self.target_vz = float(vz)
            self.target_yaw_rate = float(yaw_rate)
            self.last_command_time = time.monotonic()

    def reset_to_hover(self):
        with self._lock:
            self.target_vx = 0.0
            self.target_vy = 0.0
            self.target_vz = 0.0
            self.target_yaw_rate = 0.0
            self.last_command_time = time.monotonic()
        log("OffboardController: Velocity targets reset to hover (0 m/s).")

    def apply_movement_if_confirmed(self, vx: float = 0.0, vy: float = 0.0, vz: float = 0.0, yaw_rate: float = 0.0) -> bool:
        """Applies velocity setpoints ONLY if the vehicle is confirmed in OFFBOARD mode."""
        from gcs.telemetry import telemetry_data
        curr_mode = telemetry_data.get('mode', '').upper().replace("AUTO.", "")
        if curr_mode != 'OFFBOARD':
            log(f"OffboardController: Movement rejected - mode '{curr_mode}' is not confirmed OFFBOARD.")
            self.reset_to_hover()
            return False
        self.set_velocity(vx, vy, vz, yaw_rate)
        return True

    def warmup(self, duration_sec: float = 0.8) -> bool:
        """Stream zero-velocity setpoints for duration_sec so PX4 will accept OFFBOARD mode."""
        self.reset_to_hover()
        start = time.monotonic()
        while time.monotonic() - start < duration_sec:
            if self._stop_event.is_set() or self.vehicle is None:
                return False
            time.sleep(0.1)
        return True

    def _stream_loop(self):
        count = 0
        while not self._stop_event.is_set():
            v = self.vehicle
            if v is not None:
                # Check dead-man timeout
                with self._lock:
                    now = time.monotonic()
                    is_active = (self.target_vx != 0.0 or self.target_vy != 0.0 or 
                                 self.target_vz != 0.0 or self.target_yaw_rate != 0.0)
                    if is_active and (now - self.last_command_time > self.dead_man_timeout):
                        self.target_vx = 0.0
                        self.target_vy = 0.0
                        self.target_vz = 0.0
                        self.target_yaw_rate = 0.0
                        log("OffboardController: Dead-man timeout fired. Zeroed velocity setpoints.")

                    vx, vy, vz, yaw_r = self.target_vx, self.target_vy, self.target_vz, self.target_yaw_rate

                try:
                    # Send 10 Hz setpoint
                    send_offboard_setpoint(v, vx, vy, vz, yaw_r)
                    
                    # Send 1 Hz GCS Heartbeat (every 10 ticks)
                    if count % 10 == 0:
                        send_gcs_heartbeat(v)
                    count += 1
                except Exception as e:
                    log(f"OffboardController stream error: {e}")
            time.sleep(0.1)

offboard_controller = OffboardController()

def send_gcs_heartbeat(vehicle):
    with mav_lock:
        vehicle.mav.heartbeat_send(
            mavutil.mavlink.MAV_TYPE_GCS,
            mavutil.mavlink.MAV_AUTOPILOT_INVALID,
            0, 0, 0
        )

def send_offboard_setpoint(vehicle, vx: float, vy: float, vz: float, yaw_rate: float):
    """
    Sends SET_POSITION_TARGET_LOCAL_NED in BODY_NED frame.
    vx: Forward (+) / Backward (-) m/s
    vy: Right (+) / Left (-) m/s
    vz: Down (+) / Climb (-) m/s
    yaw_rate: Clockwise (+) / Counter-clockwise (-) rad/s
    type_mask: 0b010111000111 (0x0DC7: ignore pos, acc, force, yaw; use vel and yaw_rate)
    """
    with mav_lock:
        vehicle.mav.send(
            mavutil.mavlink.MAVLink_set_position_target_local_ned_message(
                0, # time_boot_ms
                vehicle.target_system,
                vehicle.target_component,
                mavutil.mavlink.MAV_FRAME_BODY_NED,
                0b010111000111,
                0, 0, 0, # pos (ignored)
                float(vx), float(vy), float(vz), # vel m/s
                0, 0, 0, # acc (ignored)
                0, # yaw (ignored)
                float(yaw_rate) # yaw_rate rad/s
            )
        )

def set_offboard_targets(vx: float = 0.0, vy: float = 0.0, vz: float = 0.0, yaw_rate: float = 0.0):
    offboard_controller.set_velocity(vx, vy, vz, yaw_rate)

def reset_offboard_targets():
    offboard_controller.reset_to_hover()

def stop_streamer():
    offboard_controller.stop()

def _ensure_streamer(vehicle):
    if offboard_controller.vehicle is not vehicle:
        offboard_controller.start(vehicle)

def arm(vehicle) -> Tuple[bool, str]:
    _ensure_streamer(vehicle)
    from gcs.telemetry import telemetry_data, wait_for_arm
    
    if telemetry_data.get('armed', False):
        return True, "Vehicle is already armed"

    log("Arming vehicle...")
    try:
        pending = command_manager.register(
            mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
            vehicle.target_system,
            vehicle.target_component,
            timeout=3.0
        )
    except CommandAlreadyPendingError as e:
        return False, str(e)

    with mav_lock:
        vehicle.mav.command_long_send(
            vehicle.target_system,
            vehicle.target_component,
            mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
            0,
            1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
        )

    ack_ok, ack_str, code = pending.wait()
    if not ack_ok:
        err = f"Arm rejected by flight controller: {ack_str}"
        log(err)
        return False, err

    # Wait for telemetry armed confirmation
    start_t = time.monotonic()
    while time.monotonic() - start_t < 4.0:
        if telemetry_data.get('armed', False):
            log("Arm confirmed via telemetry HEARTBEAT.")
            return True, "Vehicle successfully armed"
        time.sleep(0.2)

    return True, "Arm command accepted"

def disarm(vehicle, force: bool = False) -> Tuple[bool, str]:
    from gcs.telemetry import telemetry_data, is_vehicle_airborne

    if not telemetry_data.get('armed', False):
        return True, "Vehicle is already disarmed"

    # In-flight safety guard
    if is_vehicle_airborne() and not force:
        err = "DISARM BLOCKED: Vehicle is currently airborne. Use LAND or RTL, or use Emergency Motor Stop."
        log(err)
        return False, err

    log("Disarming vehicle...")
    try:
        pending = command_manager.register(
            mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
            vehicle.target_system,
            vehicle.target_component,
            timeout=3.0
        )
    except CommandAlreadyPendingError as e:
        return False, str(e)

    param2 = 21196.0 if force else 0.0 # PX4 force disarm magic number only if explicit force
    with mav_lock:
        vehicle.mav.command_long_send(
            vehicle.target_system,
            vehicle.target_component,
            mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
            0,
            0.0, param2, 0.0, 0.0, 0.0, 0.0, 0.0
        )

    ack_ok, ack_str, code = pending.wait()
    if not ack_ok:
        err = f"Disarm rejected by flight controller: {ack_str}"
        log(err)
        return False, err

    # Wait for telemetry disarmed confirmation
    start_t = time.monotonic()
    while time.monotonic() - start_t < 4.0:
        if not telemetry_data.get('armed', False):
            log("Disarm confirmed via telemetry HEARTBEAT.")
            return True, "Vehicle successfully disarmed"
        time.sleep(0.2)

    return True, "Disarm command accepted"

def emergency_motor_stop(vehicle) -> Tuple[bool, str]:
    """
    CRITICAL EMERGENCY ACTION:
    Immediately cuts motor power in flight using PX4 magic parameter 21196.0.
    Must be separate from normal disarm.
    """
    log("CRITICAL: Issuing EMERGENCY MOTOR STOP to vehicle!")
    try:
        pending = command_manager.register(
            mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
            vehicle.target_system,
            vehicle.target_component,
            timeout=2.0
        )
    except CommandAlreadyPendingError:
        pending = None

    with mav_lock:
        vehicle.mav.command_long_send(
            vehicle.target_system,
            vehicle.target_component,
            mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
            0,
            0.0, 21196.0, 0.0, 0.0, 0.0, 0.0, 0.0
        )

    if pending:
        ack_ok, ack_str, code = pending.wait()
        if not ack_ok:
            return False, f"Emergency motor stop rejected: {ack_str}"

    return True, "Emergency motor cutoff command dispatched"

def set_mode(vehicle, mode_name: str, confirm_timeout: float = 3.0, warmup_sec: float = 0.8) -> Tuple[bool, str]:
    _ensure_streamer(vehicle)
    from gcs.telemetry import telemetry_data
    log(f"Setting mode to {mode_name}...")

    # For OFFBOARD mode: warm up stream with zero setpoints first
    if mode_name.upper() == 'OFFBOARD' and warmup_sec > 0.0:
        log(f"OFFBOARD mode requested: Warming up setpoint stream for {warmup_sec}s at 10Hz...")
        offboard_controller.warmup(duration_sec=warmup_sec)

    timeout = time.monotonic() + 2.0
    while not vehicle.mode_mapping() and time.monotonic() < timeout:
        time.sleep(0.1)

    if not vehicle.mode_mapping():
        err = "Flight controller mode mapping not available yet"
        log(f"Error: {err}")
        return False, err

    lookup_name = mode_name.upper()
    if lookup_name == "STABILIZE":
        lookup_name = "STABILIZED"
    elif lookup_name in ("HOLD", "AUTO.HOLD", "AUTO.LOITER"):
        lookup_name = "LOITER"

    mapped_name = lookup_name
    if mapped_name not in vehicle.mode_mapping() and mapped_name.startswith("AUTO."):
        mapped_name = mapped_name.replace("AUTO.", "")

    if mapped_name not in vehicle.mode_mapping():
        err = f"Unknown mode: {mode_name} (resolved: {lookup_name})"
        log(err)
        return False, err

    mode_id = vehicle.mode_mapping()[mapped_name]
    if isinstance(mode_id, tuple):
        if len(mode_id) == 3:
            base_mode = mode_id[0]
            main_mode = mode_id[1]
            sub_mode = mode_id[2]
        else:
            base_mode = mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED
            main_mode = mode_id[0]
            sub_mode = mode_id[1] if len(mode_id) > 1 else 0
    else:
        base_mode = mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED
        main_mode = mode_id
        sub_mode = 0

    base_mode |= mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED

    try:
        pending = command_manager.register(
            mavutil.mavlink.MAV_CMD_DO_SET_MODE,
            vehicle.target_system,
            vehicle.target_component,
            timeout=3.0
        )
    except CommandAlreadyPendingError as e:
        return False, str(e)

    with mav_lock:
        vehicle.mav.command_long_send(
            vehicle.target_system,
            vehicle.target_component,
            mavutil.mavlink.MAV_CMD_DO_SET_MODE,
            0,
            float(base_mode),
            float(main_mode),
            float(sub_mode),
            0.0, 0.0, 0.0, 0.0
        )

    ack_ok, ack_str, code = pending.wait()
    if not ack_ok:
        err = f"Mode switch to {mode_name} rejected: {ack_str}"
        log(err)
        return False, err

    # Confirm mode change via telemetry
    start_t = time.monotonic()
    target_clean = mode_name.upper().replace("AUTO.", "")
    confirmed = False
    while time.monotonic() - start_t < confirm_timeout:
        curr_mode = telemetry_data.get('mode', '').upper().replace("AUTO.", "")
        if curr_mode == target_clean or (target_clean in ("HOLD", "LOITER") and curr_mode in ("HOLD", "LOITER")):
            log(f"Mode change to {mode_name} confirmed via HEARTBEAT.")
            confirmed = True
            break
        time.sleep(0.1)

    if not confirmed:
        err = f"Mode switch to {mode_name} unconfirmed by telemetry (current mode: {telemetry_data.get('mode')})"
        log(f"Warning: {err}")
        return False, err

    return True, f"Mode set to {mode_name}"

def takeoff(vehicle, altitude_m: float) -> Tuple[bool, str]:
    _ensure_streamer(vehicle)
    from gcs.telemetry import telemetry_data, wait_for_arm

    if altitude_m < 1.0 or altitude_m > 120.0:
        err = f"Invalid takeoff altitude: {altitude_m}m (allowed: 1-120m)"
        log(err)
        return False, err

    if not telemetry_data.get('armed', False):
        log("Takeoff initiated: Vehicle not armed, requesting arm first...")
        arm_ok, arm_msg = arm(vehicle)
        if not arm_ok:
            return False, f"Takeoff aborted: Arming failed ({arm_msg})"
        time.sleep(0.5)

    log(f"Dispatching takeoff command to {altitude_m:.1f}m...")
    try:
        pending = command_manager.register(
            mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,
            vehicle.target_system,
            vehicle.target_component,
            timeout=4.0
        )
    except CommandAlreadyPendingError as e:
        return False, str(e)

    with mav_lock:
        vehicle.mav.command_long_send(
            vehicle.target_system,
            vehicle.target_component,
            mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,
            0,
            0.0, 0.0, 0.0, float('nan'),
            float('nan'), float('nan'),
            float(altitude_m)
        )

    ack_ok, ack_str, code = pending.wait()
    if not ack_ok:
        err = f"Takeoff rejected by flight controller: {ack_str}"
        log(err)
        return False, err

    return True, f"Takeoff initiated to {altitude_m:.1f}m ({ack_str})"

def land(vehicle) -> Tuple[bool, str]:
    return set_mode(vehicle, 'LAND')

def rtl(vehicle) -> Tuple[bool, str]:
    return set_mode(vehicle, 'RTL')

def hold(vehicle) -> Tuple[bool, str]:
    offboard_controller.reset_to_hover()
    return set_mode(vehicle, 'HOLD')

emergency_hold = hold

def goto(vehicle, lat: float, lon: float, alt: float) -> Tuple[bool, str]:
    _ensure_streamer(vehicle)
    from gcs.telemetry import telemetry_data, is_vehicle_airborne

    if not telemetry_data.get('armed', False) or not is_vehicle_airborne():
        return False, "Guided goto rejected: Vehicle must be armed and airborne"

    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
        return False, f"Guided goto rejected: Coordinates ({lat}, {lon}) out of bounds"

    if alt < 1.0 or alt > 150.0:
        return False, f"Guided goto rejected: Altitude {alt}m out of bounds (1-150m)"

    log(f"Guided Goto: Navigating to {lat:.6f}, {lon:.6f} @ {alt:.1f}m (Launch Rel)...")
    try:
        pending = command_manager.register(
            mavutil.mavlink.MAV_CMD_DO_REPOSITION,
            vehicle.target_system,
            vehicle.target_component,
            timeout=3.0
        )
    except CommandAlreadyPendingError as e:
        return False, str(e)

    lat_int = int(lat * 1e7)
    lon_int = int(lon * 1e7)

    with mav_lock:
        vehicle.mav.command_int_send(
            vehicle.target_system,
            vehicle.target_component,
            mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT,
            mavutil.mavlink.MAV_CMD_DO_REPOSITION,
            0,
            0,
            -1.0, # Groundspeed (-1: default)
            mavutil.mavlink.MAV_DO_REPOSITION_FLAGS_CHANGE_MODE, # Automatically switch to Reposition mode
            0.0,
            0.0,
            lat_int,
            lon_int,
            float(alt)
        )

    ack_ok, ack_str, code = pending.wait()
    if not ack_ok:
        err = f"Guided goto rejected by flight controller: {ack_str}"
        log(err)
        return False, err

    return True, f"Guided goto accepted to ({lat:.4f}, {lon:.4f}) @ {alt:.1f}m"

def start_mission(vehicle) -> Tuple[bool, str]:
    _ensure_streamer(vehicle)
    log("Starting mission execution...")
    try:
        pending = command_manager.register(
            mavutil.mavlink.MAV_CMD_MISSION_START,
            vehicle.target_system,
            vehicle.target_component,
            timeout=3.0
        )
    except CommandAlreadyPendingError as e:
        return False, str(e)

    with mav_lock:
        vehicle.mav.command_long_send(
            vehicle.target_system,
            vehicle.target_component,
            mavutil.mavlink.MAV_CMD_MISSION_START,
            0,
            0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
        )

    ack_ok, ack_str, code = pending.wait()
    if not ack_ok:
        err = f"Mission start rejected by flight controller: {ack_str}"
        log(err)
        return False, err

    return True, "Mission started"

def set_parameter(vehicle, param_name: str, value: Any, param_type: int) -> Tuple[bool, str]:
    _ensure_streamer(vehicle)
    encoded_val = encode_param_value(value, param_type)
    if isinstance(param_name, str):
        param_bytes = param_name.encode('utf-8')
    else:
        param_bytes = param_name

    log(f"Setting parameter {param_name} = {value} (type: {param_type})...")
    with mav_lock:
        vehicle.mav.param_set_send(
            vehicle.target_system,
            vehicle.target_component,
            param_bytes,
            encoded_val,
            param_type
        )
    return True, f"Parameter write sent: {param_name}"

def request_all_parameters(vehicle):
    _ensure_streamer(vehicle)
    log("Requesting complete parameter list from flight controller...")
    with mav_lock:
        vehicle.mav.param_request_list_send(
            vehicle.target_system,
            vehicle.target_component
        )

def request_parameter(vehicle, param_name: str):
    _ensure_streamer(vehicle)
    if isinstance(param_name, str):
        param_bytes = param_name.encode('utf-8')
    else:
        param_bytes = param_name
    log(f"Requesting parameter {param_name}...")
    with mav_lock:
        vehicle.mav.param_request_read_send(
            vehicle.target_system,
            vehicle.target_component,
            param_bytes,
            -1
        )

def download_mission(vehicle, timeout: float = 5.0) -> Tuple[bool, List[dict], str]:
    """
    Downloads the active mission from the vehicle and returns a list of items for verification.
    """
    from gcs.telemetry import mission_queue
    import queue

    while not mission_queue.empty():
        try:
            mission_queue.get_nowait()
        except queue.Empty:
            break

    log("Downloading mission from vehicle for verification...")
    with mav_lock:
        vehicle.mav.mission_request_list_send(
            vehicle.target_system,
            vehicle.target_component,
            mavutil.mavlink.MAV_MISSION_TYPE_MISSION
        )

    start_t = time.monotonic()
    count = None
    while time.monotonic() - start_t < timeout:
        try:
            msg = mission_queue.get(timeout=0.5)
            if msg.get_type() == 'MISSION_COUNT':
                count = msg.count
                break
        except queue.Empty:
            continue

    if count is None:
        return False, [], "Download error: Timeout waiting for MISSION_COUNT from vehicle"

    if count == 0:
        return True, [], "Vehicle has 0 mission items"

    downloaded = []
    for seq in range(count):
        with mav_lock:
            vehicle.mav.mission_request_int_send(
                vehicle.target_system,
                vehicle.target_component,
                seq,
                mavutil.mavlink.MAV_MISSION_TYPE_MISSION
            )

        item_msg = None
        item_start = time.monotonic()
        while time.monotonic() - item_start < 2.5:
            try:
                msg = mission_queue.get(timeout=0.5)
                mtype = msg.get_type()
                if mtype in ['MISSION_ITEM_INT', 'MISSION_ITEM'] and msg.seq == seq:
                    item_msg = msg
                    break
            except queue.Empty:
                continue

        if not item_msg:
            return False, [], f"Download error: Timeout waiting for item {seq}"

        if item_msg.get_type() == 'MISSION_ITEM_INT':
            lat = item_msg.x / 1e7
            lon = item_msg.y / 1e7
            alt = item_msg.z
        else:
            lat = item_msg.x
            lon = item_msg.y
            alt = item_msg.z

        downloaded.append({
            'seq': item_msg.seq,
            'command': item_msg.command,
            'frame': item_msg.frame,
            'lat': lat,
            'lon': lon,
            'alt': alt
        })

    with mav_lock:
        vehicle.mav.mission_ack_send(
            vehicle.target_system,
            vehicle.target_component,
            mavutil.mavlink.MAV_MISSION_ACCEPTED,
            mavutil.mavlink.MAV_MISSION_TYPE_MISSION
        )

    return True, downloaded, f"Successfully downloaded {count} items"

def upload_mission(
    vehicle,
    waypoints: List[List[float]],
    takeoff_point: Optional[List[float]] = None,
    landing_point: Optional[List[float]] = None,
    target_alt: float = 10.0,
    verify_after_upload: bool = True
) -> Tuple[bool, str]:
    """
    Robust MAVLink mission upload protocol for PX4.
    Adheres strictly to PX4 mission specification:
    - Sequence 0 is the first uploaded plan item (TAKEOFF or first WAYPOINT). Do NOT insert Home as seq 0!
    - Does NOT clear the mission beforehand; MISSION_COUNT transaction atomically replaces it.
    - Handles MISSION_REQUEST_INT and MISSION_REQUEST with repeats and retries.
    - Verifies uploaded count and items via readback download if verify_after_upload=True.
    """
    if not waypoints and not takeoff_point and not landing_point:
        return False, "Validation error: No mission items provided"

    # Pre-upload validation
    for i, wp in enumerate(waypoints):
        lat, lon = wp[0], wp[1]
        alt = wp[2] if len(wp) > 2 else target_alt
        if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
            return False, f"Validation error: Waypoint {i+1} coordinates out of range ({lat}, {lon})"
        if alt < 1.0 or alt > 200.0:
            return False, f"Validation error: Waypoint {i+1} altitude out of range ({alt}m)"

    if not upload_lock.acquire(blocking=False):
        return False, "Mission upload error: Another upload transaction is already in progress"

    try:
        from gcs.telemetry import mission_queue
        import queue

        while not mission_queue.empty():
            try:
                mission_queue.get_nowait()
            except queue.Empty:
                break

        items = []
        seq = 0

        if takeoff_point:
            t_alt = takeoff_point[2] if len(takeoff_point) > 2 else target_alt
            items.append({
                'seq': seq,
                'frame': mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT,
                'command': mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,
                'current': 0,
                'autocontinue': 1,
                'param1': 0.0,
                'param2': 0.0,
                'param3': 0.0,
                'param4': 0.0,
                'x': int(takeoff_point[0] * 1e7),
                'y': int(takeoff_point[1] * 1e7),
                'z': float(t_alt)
            })
            seq += 1

        for wp in waypoints:
            w_alt = wp[2] if len(wp) > 2 else target_alt
            items.append({
                'seq': seq,
                'frame': mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT,
                'command': mavutil.mavlink.MAV_CMD_NAV_WAYPOINT,
                'current': 0,
                'autocontinue': 1,
                'param1': 0.0,
                'param2': 2.0,
                'param3': 0.0,
                'param4': 0.0,
                'x': int(wp[0] * 1e7),
                'y': int(wp[1] * 1e7),
                'z': float(w_alt)
            })
            seq += 1

        if landing_point:
            items.append({
                'seq': seq,
                'frame': mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT,
                'command': mavutil.mavlink.MAV_CMD_NAV_LAND,
                'current': 0,
                'autocontinue': 1,
                'param1': 0.0,
                'param2': 0.0,
                'param3': 0.0,
                'param4': 0.0,
                'x': int(landing_point[0] * 1e7),
                'y': int(landing_point[1] * 1e7),
                'z': 0.0
            })
            seq += 1

        total_count = len(items)
        log(f"Mission upload: Initiating transaction for {total_count} items (PX4 seq 0={items[0]['command']})...")

        with mav_lock:
            vehicle.mav.mission_count_send(
                vehicle.target_system,
                vehicle.target_component,
                total_count,
                mavutil.mavlink.MAV_MISSION_TYPE_MISSION
            )

        sent_items = set()
        retries = 0
        max_retries = 3

        while len(sent_items) < total_count and retries < max_retries:
            try:
                msg = mission_queue.get(timeout=2.0)
                msg_type = msg.get_type()
                if msg_type in ['MISSION_REQUEST', 'MISSION_REQUEST_INT']:
                    req_seq = msg.seq
                    if 0 <= req_seq < total_count:
                        item = items[req_seq]
                        log(f"Mission upload: Sending item {req_seq}/{total_count-1} (cmd {item['command']})...")
                        with mav_lock:
                            vehicle.mav.mission_item_int_send(
                                vehicle.target_system,
                                vehicle.target_component,
                                item['seq'],
                                item['frame'],
                                item['command'],
                                item['current'],
                                item['autocontinue'],
                                item['param1'],
                                item['param2'],
                                item['param3'],
                                item['param4'],
                                item['x'],
                                item['y'],
                                item['z'],
                                mavutil.mavlink.MAV_MISSION_TYPE_MISSION
                            )
                        sent_items.add(req_seq)
                        retries = 0
                    else:
                        return False, f"Mission upload error: Invalid requested sequence {req_seq}"
                elif msg_type == 'MISSION_ACK':
                    if msg.type == mavutil.mavlink.MAV_MISSION_ACCEPTED and len(sent_items) == total_count:
                        break
                    else:
                        return False, f"Mission upload rejected early with ACK type {msg.type}"
            except queue.Empty:
                retries += 1
                log(f"Mission upload: Request timeout. Retry {retries}/{max_retries}...")
                with mav_lock:
                    vehicle.mav.mission_count_send(
                        vehicle.target_system,
                        vehicle.target_component,
                        total_count,
                        mavutil.mavlink.MAV_MISSION_TYPE_MISSION
                    )

        if len(sent_items) < total_count:
            return False, "Mission upload failed: Timeout waiting for vehicle item requests"

        try:
            ack_msg = mission_queue.get(timeout=3.0)
            if ack_msg.get_type() == 'MISSION_ACK':
                if ack_msg.type != mavutil.mavlink.MAV_MISSION_ACCEPTED:
                    return False, f"Mission upload rejected by vehicle with ACK type {ack_msg.type}"
            else:
                return False, f"Mission upload error: Unexpected message {ack_msg.get_type()} waiting for ACK"
        except queue.Empty:
            return False, "Mission upload timeout waiting for final MISSION_ACK"

        # Verification step: readback download and comparison
        if verify_after_upload:
            log("Mission upload: Verifying mission via readback download...")
            dl_ok, dl_items, dl_msg = download_mission(vehicle, timeout=4.0)
            if not dl_ok:
                return False, f"Upload completed but verification download failed: {dl_msg}"

            if len(dl_items) != total_count:
                return False, f"Mission verification failed: count mismatch (uploaded {total_count}, vehicle has {len(dl_items)})"

            for i, up_item in enumerate(items):
                down = dl_items[i]
                if down['command'] != up_item['command']:
                    return False, f"Mission verification failed at seq {i}: command mismatch"
                up_lat = up_item['x'] / 1e7
                up_lon = up_item['y'] / 1e7
                if abs(down['lat'] - up_lat) > 1e-4 or abs(down['lon'] - up_lon) > 1e-4:
                    return False, f"Mission verification failed at seq {i}: coordinate mismatch"
                if abs(down['alt'] - up_item['z']) > 1.0:
                    return False, f"Mission verification failed at seq {i}: altitude mismatch"

            log(f"Mission upload and readback verification SUCCESS: {total_count} items verified.")
            return True, f"Mission successfully uploaded and verified ({total_count} items)"

        return True, f"Mission successfully uploaded ({total_count} items)"

    finally:
        upload_lock.release()
