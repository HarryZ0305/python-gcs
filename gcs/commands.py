import time
import math
import threading
from typing import Tuple, Optional, List, Dict, Any
from pymavlink import mavutil
from gcs.logs import log
from gcs.params import encode_param_value, decode_param_value, PARAM_TYPE_REAL32, PARAM_TYPE_INT32
from gcs.command_manager import command_manager

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
    pending = command_manager.register(
        mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
        vehicle.target_system,
        vehicle.target_component,
        timeout=3.0
    )
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

    # Wait for heartbeat armed state confirmation
    if wait_for_arm(timeout=5):
        log("Arm confirmed via telemetry HEARTBEAT.")
        return True, "Vehicle successfully armed"
    else:
        err = "Arm ACK received, but telemetry armed state did not confirm within timeout"
        log(err)
        return False, err

def disarm(vehicle, force: bool = False) -> Tuple[bool, str]:
    _ensure_streamer(vehicle)
    from gcs.telemetry import telemetry_data, is_vehicle_airborne

    if not telemetry_data.get('armed', False):
        return True, "Vehicle is already disarmed"

    # In-flight safety guard
    if is_vehicle_airborne() and not force:
        err = "DISARM BLOCKED: Vehicle is currently airborne. Use LAND or RTL, or confirm emergency stop."
        log(err)
        return False, err

    log("Disarming vehicle...")
    pending = command_manager.register(
        mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
        vehicle.target_system,
        vehicle.target_component,
        timeout=3.0
    )
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

def set_mode(vehicle, mode_name: str) -> Tuple[bool, str]:
    _ensure_streamer(vehicle)
    from gcs.telemetry import telemetry_data
    log(f"Setting mode to {mode_name}...")

    # For OFFBOARD mode: warm up stream with zero setpoints first
    if mode_name.upper() == 'OFFBOARD':
        log("OFFBOARD mode requested: Warming up setpoint stream at 10Hz...")
        offboard_controller.warmup(duration_sec=0.8)

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
            sub_mode = mode_id[1]
    else:
        base_mode = mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED
        main_mode = mode_id
        sub_mode = 0

    base_mode |= mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED

    pending = command_manager.register(
        mavutil.mavlink.MAV_CMD_DO_SET_MODE,
        vehicle.target_system,
        vehicle.target_component,
        timeout=3.0
    )
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
    while time.monotonic() - start_t < 3.0:
        curr_mode = telemetry_data.get('mode', '').upper().replace("AUTO.", "")
        if curr_mode == target_clean:
            log(f"Mode change to {mode_name} confirmed via HEARTBEAT.")
            return True, f"Mode set to {mode_name}"
        time.sleep(0.2)

    return True, f"Mode switch accepted ({ack_str})"

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
            return False, f"Takeoff aborted: Arm failed ({arm_msg})"

    log(f"Dispatching takeoff command to {altitude_m:.1f}m...")
    pending = command_manager.register(
        mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,
        vehicle.target_system,
        vehicle.target_component,
        timeout=4.0
    )
    nan = float('nan')
    with mav_lock:
        vehicle.mav.command_long_send(
            vehicle.target_system,
            vehicle.target_component,
            mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,
            0,
            0.0, 0.0, 0.0, nan, nan, nan,
            float(altitude_m)
        )

    ack_ok, ack_str, code = pending.wait()
    if not ack_ok:
        err = f"Takeoff command rejected by flight controller: {ack_str}"
        log(err)
        return False, err

    log(f"Takeoff command ACCEPTED by vehicle! Climbing to {altitude_m:.1f}m...")
    return True, f"Takeoff accepted (target: {altitude_m:.1f}m)"

def goto(vehicle, lat: float, lon: float, alt: float) -> Tuple[bool, str]:
    _ensure_streamer(vehicle)
    from gcs.telemetry import telemetry_data, is_vehicle_airborne

    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
        err = f"Invalid coordinates for goto: {lat}, {lon}"
        log(err)
        return False, err

    if alt < 1.0 or alt > 150.0:
        err = f"Invalid goto altitude: {alt}m (allowed: 1-150m)"
        log(err)
        return False, err

    if not telemetry_data.get('armed', False) or not is_vehicle_airborne():
        err = "Goto rejected: Vehicle must be armed and airborne to reposition"
        log(err)
        return False, err

    now = time.monotonic()
    if now - telemetry_data.get('last_heartbeat_monotonic', 0.0) > 3.0:
        err = "Goto rejected: Telemetry link is stale or disconnected"
        log(err)
        return False, err

    log(f"Guided Goto: Navigating to {lat:.6f}, {lon:.6f} @ {alt:.1f}m (Launch Rel)...")
    pending = command_manager.register(
        mavutil.mavlink.MAV_CMD_DO_REPOSITION,
        vehicle.target_system,
        vehicle.target_component,
        timeout=3.0
    )
    
    nan = float('nan')
    with mav_lock:
        try:
            # Use COMMAND_INT with 1e7 scaled coordinates for centimeter precision
            vehicle.mav.command_int_send(
                vehicle.target_system,
                vehicle.target_component,
                mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT,
                mavutil.mavlink.MAV_CMD_DO_REPOSITION,
                0, 0,
                -1.0, # ground speed (-1 default)
                mavutil.mavlink.MAV_DO_REPOSITION_FLAGS_CHANGE_MODE, # auto-switch to hold/loiter
                0.0,
                nan,
                int(lat * 1e7),
                int(lon * 1e7),
                float(alt)
            )
        except Exception:
            # Fallback to command_long if command_int not supported
            vehicle.mav.command_long_send(
                vehicle.target_system,
                vehicle.target_component,
                mavutil.mavlink.MAV_CMD_DO_REPOSITION,
                0,
                -1.0,
                float(mavutil.mavlink.MAV_DO_REPOSITION_FLAGS_CHANGE_MODE),
                0.0,
                nan,
                float(lat),
                float(lon),
                float(alt)
            )

    ack_ok, ack_str, code = pending.wait()
    if not ack_ok:
        err = f"Goto reposition rejected: {ack_str}"
        log(err)
        return False, err

    log(f"Goto reposition command ACCEPTED by vehicle!")
    return True, "Goto reposition accepted"

def emergency_hold(vehicle) -> Tuple[bool, str]:
    reset_offboard_targets()
    log("EMERGENCY HOLD triggered: Zeroing velocity setpoints and switching to AUTO.LOITER...")
    return set_mode(vehicle, 'AUTO.LOITER')

def request_all_parameters(vehicle):
    log("Parameter protocol: Requesting all parameters...")
    with mav_lock:
        vehicle.mav.param_request_list_send(
            vehicle.target_system,
            vehicle.target_component
        )

def request_parameter(vehicle, param_id_or_index):
    with mav_lock:
        if isinstance(param_id_or_index, int):
            vehicle.mav.param_request_read_send(
                vehicle.target_system,
                vehicle.target_component,
                b'',
                param_id_or_index
            )
        else:
            name_bytes = param_id_or_index.encode('utf-8')[:16].ljust(16, b'\x00')
            vehicle.mav.param_request_read_send(
                vehicle.target_system,
                vehicle.target_component,
                name_bytes,
                -1
            )

def set_parameter(vehicle, param_id: str, param_value: Any, param_type: int) -> float:
    wire_float = encode_param_value(param_value, param_type)
    if isinstance(param_id, str):
        param_id_bytes = param_id.encode('utf-8')
    else:
        param_id_bytes = param_id
    param_id_bytes = param_id_bytes[:16].ljust(16, b'\x00')
    
    log(f"Parameter protocol: Sending PARAM_SET {param_id} = {param_value} (type={param_type}, wire_float={wire_float})...")
    with mav_lock:
        vehicle.mav.param_set_send(
            vehicle.target_system,
            vehicle.target_component,
            param_id_bytes,
            wire_float,
            int(param_type)
        )
    return wire_float

def upload_mission(
    vehicle,
    waypoints: List[List[float]],
    takeoff_point: Optional[List[float]] = None,
    landing_point: Optional[List[float]] = None,
    target_alt: float = 10.0
) -> Tuple[bool, str]:
    """
    Robust MAVLink mission upload protocol for PX4.
    Adheres strictly to PX4 mission specification:
    - Sequence 0 is the first uploaded plan item (TAKEOFF or first WAYPOINT). Do NOT insert Home as seq 0!
    - Does NOT clear the mission beforehand with mission_clear_all_send; MISSION_COUNT transaction
      atomically replaces the vehicle mission only on accepted completion.
    - Handles MISSION_REQUEST_INT and MISSION_REQUEST.
    - Handles repeated requests and retries.
    - Verifies uploaded count upon completion.
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

        # Clear stale messages from mission queue
        while not mission_queue.empty():
            try:
                mission_queue.get_nowait()
            except queue.Empty:
                break

        items = []
        seq = 0

        # Item 0: Takeoff if provided
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

        # Intermediate waypoints
        for wp in waypoints:
            w_alt = wp[2] if len(wp) > 2 else target_alt
            items.append({
                'seq': seq,
                'frame': mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT,
                'command': mavutil.mavlink.MAV_CMD_NAV_WAYPOINT,
                'current': 0,
                'autocontinue': 1,
                'param1': 0.0,
                'param2': 2.0, # 2m acceptance radius
                'param3': 0.0,
                'param4': 0.0,
                'x': int(wp[0] * 1e7),
                'y': int(wp[1] * 1e7),
                'z': float(w_alt)
            })
            seq += 1

        # Landing point if provided
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

        # Step 1: Send MISSION_COUNT
        with mav_lock:
            vehicle.mav.mission_count_send(
                vehicle.target_system,
                vehicle.target_component,
                total_count,
                mavutil.mavlink.MAV_MISSION_TYPE_MISSION
            )

        # Step 2: Handle requests for each item
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

        # Step 3: Wait for final MISSION_ACK
        try:
            ack_msg = mission_queue.get(timeout=3.0)
            if ack_msg.get_type() == 'MISSION_ACK':
                if ack_msg.type == mavutil.mavlink.MAV_MISSION_ACCEPTED:
                    log(f"Mission upload SUCCESSFUL! {total_count} items verified by vehicle.")
                    return True, f"Mission successfully uploaded ({total_count} items)"
                else:
                    return False, f"Mission upload rejected by vehicle with ACK type {ack_msg.type}"
            else:
                return False, f"Mission upload error: Unexpected message {ack_msg.get_type()} waiting for ACK"
        except queue.Empty:
            return False, "Mission upload timeout waiting for final MISSION_ACK"

    finally:
        upload_lock.release()
