from pymavlink import mavutil
import time
import threading
from logs import log

# Lock for all vehicle.mav calls to prevent packet corruption from concurrent writes
mav_lock = threading.Lock()

# Target values for the offboard streamer
target_vx = 0.0
target_vy = 0.0
target_vz = 0.0
target_yaw_rate = 0.0  # rad/s

# Background thread management
_streamer_thread = None
_streamer_vehicle = None

def _ensure_streamer(vehicle):
    global _streamer_thread, _streamer_vehicle
    _streamer_vehicle = vehicle
    if _streamer_thread is None:
        _streamer_thread = threading.Thread(target=_offboard_streamer_loop, daemon=True)
        _streamer_thread.start()

def _offboard_streamer_loop():
    global _streamer_vehicle, target_vx, target_vy, target_vz, target_yaw_rate
    log("Offboard streamer thread active.")
    count = 0
    while True:
        if _streamer_vehicle is not None:
            try:
                # Send setpoint at 10 Hz (every 0.1 seconds)
                send_offboard_setpoint(_streamer_vehicle, target_vx, target_vy, target_vz, target_yaw_rate)
                
                # Send GCS Heartbeat at 1 Hz (every 10 ticks)
                if count % 10 == 0:
                    send_gcs_heartbeat(_streamer_vehicle)
                count += 1
            except Exception as e:
                log(f"Offboard streamer exception: {e}. Resetting vehicle stream.")
                _streamer_vehicle = None
        time.sleep(0.1)

def send_gcs_heartbeat(vehicle):
    with mav_lock:
        vehicle.mav.heartbeat_send(
            mavutil.mavlink.MAV_TYPE_GCS,
            mavutil.mavlink.MAV_AUTOPILOT_INVALID,
            0, 0, 0
        )

def send_offboard_setpoint(vehicle, vx, vy, vz, yaw_rate):
    with mav_lock:
        vehicle.mav.send(
            mavutil.mavlink.MAVLink_set_position_target_local_ned_message(
                0, # time_boot_ms
                vehicle.target_system,
                vehicle.target_component,
                mavutil.mavlink.MAV_FRAME_BODY_NED, # body frame (forward, right, down)
                0b010111000111, # Bit 10 is 1 (ignore yaw), Bit 11 is 0 (use yaw rate), Bit 9 is 0 (disable FORCE)
                0, 0, 0, # x, y, z position (ignored)
                vx, vy, vz, # velocity m/s
                0, 0, 0, # acceleration (ignored)
                0, # yaw (ignored)
                yaw_rate # yaw_rate (rad/s)
            )
        )

def set_offboard_targets(vx=0.0, vy=0.0, vz=0.0, yaw_rate=0.0):
    global target_vx, target_vy, target_vz, target_yaw_rate
    target_vx = vx
    target_vy = vy
    target_vz = vz
    target_yaw_rate = yaw_rate
    log(f"Offboard target updated: vx={vx:.1f}, yaw_rate={yaw_rate:.2f}")

def reset_offboard_targets():
    global target_vx, target_vy, target_vz, target_yaw_rate
    target_vx = 0.0
    target_vy = 0.0
    target_vz = 0.0
    target_yaw_rate = 0.0
    log("Offboard targets reset to hover.")

def stop_streamer():
    global _streamer_vehicle
    _streamer_vehicle = None
    log("Offboard streamer stopped.")

def arm(vehicle):
    _ensure_streamer(vehicle)
    log("Arming...")
    with mav_lock:
        vehicle.mav.command_long_send( # sends MAVLink command to drone  
            vehicle.target_system,  
            vehicle.target_component,  
            mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
            0,
            1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
        )
    log("Arm command sent!")

def disarm(vehicle):
    _ensure_streamer(vehicle)
    log("Disarming...")
    with mav_lock:
        vehicle.mav.command_long_send(  
            vehicle.target_system,  
            vehicle.target_component,  
            mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
            0,
            0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
        )
    log("Disarm command sent!")

def set_mode(vehicle, mode_name):
    _ensure_streamer(vehicle)
    log(f"Setting mode to {mode_name}...")
    
    timeout = time.time() + 2
    while not vehicle.mode_mapping() and time.time() < timeout:
        time.sleep(0.1)

    if not vehicle.mode_mapping():
        log("Error: Flight controller has not transmitted mode mapping yet.")
        return

    # Normalize mode name for PX4 mapping
    lookup_name = mode_name.upper()
    if lookup_name == "STABILIZE":
        lookup_name = "STABILIZED"

    # Hybrid lookup strategy: try exact match first, then strip "AUTO." prefix if not found
    mapped_name = lookup_name
    if mapped_name not in vehicle.mode_mapping() and mapped_name.startswith("AUTO."):
        mapped_name = mapped_name.replace("AUTO.", "")

    if mapped_name not in vehicle.mode_mapping(): # returns a dictionary of all available modes  
        log(f"Unknown mode: {mode_name} (resolved to: {lookup_name})")
        log(f"Available modes: {list(vehicle.mode_mapping().keys())}")  
        return

    mode_id = vehicle.mode_mapping()[mapped_name] # MAVLink number or tuple for the mode
    
    # PX4 custom mode consists of base_mode, main_mode, and sub_mode in px4_map 3-tuple
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
    
    # Send using MAV_CMD_DO_SET_MODE command.
    with mav_lock:
        vehicle.mav.command_long_send(
            vehicle.target_system,
            vehicle.target_component,
            mavutil.mavlink.MAV_CMD_DO_SET_MODE,
            0, # confirmation
            float(base_mode), # param 1: base_mode
            float(main_mode), # param 2: custom main mode
            float(sub_mode),  # param 3: custom sub mode
            0.0, 0.0, 0.0, 0.0 # param 4-7
        )
    log(f"Mode {mode_name} set!")

def takeoff(vehicle, altitude_m):
    _ensure_streamer(vehicle)
    from telemetry import telemetry_data, wait_for_arm
    
    # PX4 takeoff flow: Arm the vehicle first if not already armed
    if not telemetry_data['armed']:
        log("Takeoff initiated: Arming vehicle...")
        with mav_lock:
            vehicle.mav.command_long_send(
                vehicle.target_system,
                vehicle.target_component,
                mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
                0,
                1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
            )
        log("Arm command sent, waiting for confirmation...")
        # Note: PX4 preflight checks (EKF/GPS) may block arming until the sim has a position fix
        if not wait_for_arm(timeout=10):
            log("Takeoff aborted: Drone failed to arm. EKF/GPS preflight checks may be blocking arming.")
            return False
            
    log(f"Taking off to {altitude_m}m...")
    nan = float('nan')
    with mav_lock:
        vehicle.mav.command_long_send(
            vehicle.target_system,
            vehicle.target_component,
            mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,
            0,
            0.0,       # param 1: pitch
            0.0,       # param 2: empty
            0.0,       # param 3: empty
            nan,       # param 4: yaw (NaN uses current heading)
            nan,       # param 5: latitude (NaN uses current position)
            nan,       # param 6: longitude (NaN uses current position)
            float(altitude_m) # param 7: altitude
        )
    log("Takeoff command sent!")
    return True

def goto(vehicle, lat, lon, alt):
    _ensure_streamer(vehicle)
    log(f"Flying to {lat}, {lon} @ {alt}m...")
    with mav_lock:
        vehicle.mav.send(  
            mavutil.mavlink.MAVLink_set_position_target_global_int_message( # drone's target position
                0,
                vehicle.target_system,  
                vehicle.target_component,  
                mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT, # drone's relative height to launch point
                0b0000111111111000, # bitmask for position
                int(lat * 1e7),
                int(lon * 1e7),
                alt,
                0, 0, 0,
                0, 0, 0,
                0, 0
            )
        )
    log("Goto command sent!")

def upload_mission(vehicle, waypoints, takeoff_point=None, landing_point=None, target_alt=10.0):
    log("Mission upload: Starting transaction...")
    from telemetry import mission_queue, telemetry_data
    import queue

    # Clear queue of any stale messages first
    while not mission_queue.empty():
        try:
            mission_queue.get_nowait()
        except queue.Empty:
            break

    # Step 1: Clear existing mission
    log("Mission upload: Clearing existing mission...")
    with mav_lock:
        vehicle.mav.mission_clear_all_send(
            vehicle.target_system,
            vehicle.target_component
        )

    try:
        msg = mission_queue.get(timeout=2.0)
        if msg.get_type() != 'MISSION_ACK':
            log(f"Mission upload failed: Expected MISSION_ACK, got {msg.get_type()}")
            return False
        if msg.type != mavutil.mavlink.MAV_MISSION_ACCEPTED:
            log(f"Mission upload failed: MAV_CMD_MISSION_CLEAR_ALL rejected with type {msg.type}")
            return False
    except queue.Empty:
        log("Mission upload failed: Timeout waiting for MISSION_ACK during clear.")
        return False

    log("Mission upload: Previous mission cleared.")

    # PX4 expects waypoint 0 to be the home position.
    home_lat = telemetry_data['lat']
    home_lon = telemetry_data['lon']
    if home_lat == 0.0 or home_lon == 0.0:
        if takeoff_point:
            home_lat = takeoff_point[0]
            home_lon = takeoff_point[1]
        elif waypoints:
            home_lat = waypoints[0][0]
            home_lon = waypoints[0][1]
        elif landing_point:
            home_lat = landing_point[0]
            home_lon = landing_point[1]

    items = []
    seq_counter = 0

    # Add home item (seq 0)
    items.append({
        'seq': seq_counter,
        'frame': mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT,
        'command': mavutil.mavlink.MAV_CMD_NAV_WAYPOINT,
        'current': 0,
        'autocontinue': 1,
        'param1': 0.0,
        'param2': 0.0,
        'param3': 0.0,
        'param4': 0.0,
        'x': int(home_lat * 1e7),
        'y': int(home_lon * 1e7),
        'z': 0.0
    })
    seq_counter += 1

    # Add Takeoff item (MAV_CMD_NAV_TAKEOFF) if specified
    if takeoff_point:
        items.append({
            'seq': seq_counter,
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
            'z': float(target_alt)
        })
        seq_counter += 1

    # Add waypoints (MAV_CMD_NAV_WAYPOINT)
    for wp in waypoints:
        items.append({
            'seq': seq_counter,
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
            'z': float(target_alt)
        })
        seq_counter += 1

    # Add Land item (MAV_CMD_NAV_LAND) if specified
    if landing_point:
        items.append({
            'seq': seq_counter,
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
        seq_counter += 1

    total_count = len(items)
    log(f"Mission upload: Sending count ({total_count} items)...")
    with mav_lock:
        vehicle.mav.mission_count_send(
            vehicle.target_system,
            vehicle.target_component,
            total_count
        )

    for i in range(total_count):
        try:
            msg = mission_queue.get(timeout=2.0)
            msg_type = msg.get_type()
            if msg_type not in ['MISSION_REQUEST', 'MISSION_REQUEST_INT']:
                log(f"Mission upload failed: Unexpected message {msg_type} (expected request)")
                return False
            
            requested_seq = msg.seq
            if requested_seq < 0 or requested_seq >= total_count:
                log(f"Mission upload failed: Requested invalid sequence number {requested_seq}")
                return False

            item = items[requested_seq]
            log(f"Mission upload: Sending item {requested_seq}/{total_count-1}...")
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
                    item['z']
                )
        except queue.Empty:
            log(f"Mission upload failed: Timeout waiting for request for item {i}.")
            return False

    try:
        msg = mission_queue.get(timeout=2.0)
        if msg.get_type() != 'MISSION_ACK':
            log(f"Mission upload failed: Expected final MISSION_ACK, got {msg.get_type()}")
            return False
        if msg.type == mavutil.mavlink.MAV_MISSION_ACCEPTED:
            log("Mission upload SUCCESSFUL! Mission accepted by vehicle.")
            return True
        else:
            log(f"Mission upload failed: Mission rejected with ACK type {msg.type}")
            return False
    except queue.Empty:
        log("Mission upload failed: Timeout waiting for final MISSION_ACK.")
        return False

def request_all_parameters(vehicle):
    log("Parameter protocol: Requesting all parameters...")
    with mav_lock:
        vehicle.mav.param_request_list_send(
            vehicle.target_system,
            vehicle.target_component
        )

def set_parameter(vehicle, param_id, param_value, param_type):
    log(f"Parameter protocol: Setting parameter {param_id} = {param_value}...")
    if isinstance(param_id, str):
        param_id_bytes = param_id.encode('utf-8')
    else:
        param_id_bytes = param_id
    param_id_bytes = param_id_bytes[:16].ljust(16, b'\x00')
    with mav_lock:
        vehicle.mav.param_set_send(
            vehicle.target_system,
            vehicle.target_component,
            param_id_bytes,
            float(param_value),
            int(param_type)
        )