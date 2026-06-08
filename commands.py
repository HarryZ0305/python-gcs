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
    if _streamer_thread is None:
        _streamer_vehicle = vehicle
        _streamer_thread = threading.Thread(target=_offboard_streamer_loop, daemon=True)
        _streamer_thread.start()

def _offboard_streamer_loop():
    global _streamer_vehicle, target_vx, target_vy, target_vz, target_yaw_rate
    log("Offboard streamer thread active.")
    count = 0
    while True:
        if _streamer_vehicle is not None:
            # Send setpoint at 10 Hz (every 0.1 seconds)
            send_offboard_setpoint(_streamer_vehicle, target_vx, target_vy, target_vz, target_yaw_rate)
            
            # Send GCS Heartbeat at 1 Hz (every 10 ticks)
            if count % 10 == 0:
                send_gcs_heartbeat(_streamer_vehicle)
            count += 1
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
                0b0000010111000111, # use velocity and yaw rate; ignore pos, accel, and absolute yaw
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

    if lookup_name not in vehicle.mode_mapping(): # returns a dictionary of all available modes  
        log(f"Unknown mode: {mode_name} (resolved to: {lookup_name})")
        log(f"Available modes: {list(vehicle.mode_mapping().keys())}")  
        return

    mode_id = vehicle.mode_mapping()[lookup_name] # MAVLink number or tuple for the mode
    
    # PX4 custom mode consists of main_mode and sub_mode
    if isinstance(mode_id, tuple):
        main_mode = mode_id[0]
        sub_mode = mode_id[1]
    else:
        main_mode = mode_id
        sub_mode = 0
        
    # Send using MAV_CMD_DO_SET_MODE command.
    with mav_lock:
        vehicle.mav.command_long_send(
            vehicle.target_system,
            vehicle.target_component,
            mavutil.mavlink.MAV_CMD_DO_SET_MODE,
            0, # confirmation
            float(mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED), # param 1: base_mode
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
            return
            
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