from pymavlink import mavutil
import time
from logs import log

def arm(vehicle):
    log("Arming...")
    vehicle.mav.command_long_send( # sends MAVLink command to drone  
        vehicle.target_system,  
        vehicle.target_component,  
        mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
        0,
        1, 0, 0, 0, 0, 0, 0
    )
    log("Arm command sent!")

def disarm(vehicle):
    log("Disarming...")
    vehicle.mav.command_long_send(  
        vehicle.target_system,  
        vehicle.target_component,  
        mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
        0,
        0, 0, 0, 0, 0, 0, 0
    )
    log("Disarm command sent!")

def set_mode(vehicle, mode_name):
    log(f"Setting mode to {mode_name}...")
    
    timeout = time.time() + 2
    while not vehicle.mode_mapping() and time.time() < timeout:
        time.sleep(0.1)

    if not vehicle.mode_mapping():
        log("Error: Flight controller has not transmitted mode mapping yet.")
        return

    if mode_name not in vehicle.mode_mapping(): # returns a dictionary of all available modes  
        log(f"Unknown mode: {mode_name}")
        log(f"Available modes: {list(vehicle.mode_mapping().keys())}")  
        return

    mode_id = vehicle.mode_mapping()[mode_name] # MAVLink number for the mode
    vehicle.mav.set_mode_send(  
        vehicle.target_system, 
        mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED, # Custom flight mode flag
        mode_id
    )
    log(f"Mode {mode_name} set!")

def takeoff(vehicle, altitude_m):
    log(f"Taking off to {altitude_m}m...")
    vehicle.mav.command_long_send(  
        vehicle.target_system,  
        vehicle.target_component,  
        mavutil.mavlink.MAV_CMD_NAV_TAKEOFF, # MAVLink command for takeoff, altitude_m is the target height in meters
        0,
        0, 0, 0, 0, 0, 0,
        altitude_m
    )
    log("Takeoff command sent!")

def goto(vehicle, lat, lon, alt):
    log(f"Flying to {lat}, {lon} @ {alt}m...")
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

def move_body(vehicle, vx=0.0, vy=0.0, vz=0.0, duration=3.0, rate_hz=5):
    """Body-frame velocity setpoint (m/s) held for `duration` seconds.

    x = forward, y = right, z = down. ArduCopter in GUIDED stops if it
    doesn't receive a fresh setpoint within ~3s, so we resend at rate_hz.
    Drone must be ARMED, in GUIDED, and airborne for this to do anything.
    """
    log(f"Moving body vx={vx} vy={vy} vz={vz} for {duration}s...")
    interval = 1.0 / rate_hz
    end = time.time() + duration
    while time.time() < end:
        vehicle.mav.send(
            mavutil.mavlink.MAVLink_set_position_target_local_ned_message(
                0,
                vehicle.target_system,
                vehicle.target_component,
                mavutil.mavlink.MAV_FRAME_BODY_NED,
                0b0000111111000111,   # velocity only; ignore pos/accel/yaw
                0, 0, 0,              # x, y, z position (ignored)
                vx, vy, vz,           # velocity m/s, body frame
                0, 0, 0,              # acceleration (ignored)
                0, 0                  # yaw, yaw_rate (ignored)
            )
        )
        time.sleep(interval)
    # one zero-velocity setpoint so it stops cleanly instead of drifting
    vehicle.mav.send(
        mavutil.mavlink.MAVLink_set_position_target_local_ned_message(
            0, vehicle.target_system, vehicle.target_component,
            mavutil.mavlink.MAV_FRAME_BODY_NED,
            0b0000111111000111,
            0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
        )
    )
    log("Move complete.")


def condition_yaw(vehicle, angle_deg=30, speed_deg_s=25, direction=1):
    """Rotate heading by angle_deg relative to current, via CONDITION_YAW.

    direction: 1 = clockwise / right, -1 = counter-clockwise / left.
    Works in GUIDED while airborne; reliable across ArduCopter versions.
    """
    log(f"Yaw {'right' if direction > 0 else 'left'} {angle_deg} deg...")
    vehicle.mav.command_long_send(
        vehicle.target_system,
        vehicle.target_component,
        mavutil.mavlink.MAV_CMD_CONDITION_YAW,
        0,
        angle_deg,      # param1: angle (deg)
        speed_deg_s,    # param2: yaw speed (deg/s)
        direction,      # param3: 1 = CW, -1 = CCW
        1,              # param4: 1 = relative to current heading
        0, 0, 0
    )
    log("Yaw command sent!")