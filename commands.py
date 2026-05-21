from pymavlink import mavutil
import time

def arm(vehicle):
    print("Arming...")
    vehicle.mav.command_long_send( # sends MAVLink command to drone  
        vehicle.target_system,  
        vehicle.target_component,  
        mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
        0,
        1, 0, 0, 0, 0, 0, 0
    )
    print("Arm command sent!")

def disarm(vehicle):
    print("Disarming...")
    vehicle.mav.command_long_send(  
        vehicle.target_system,  
        vehicle.target_component,  
        mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
        0,
        0, 0, 0, 0, 0, 0, 0
    )
    print("Disarm command sent!")

def set_mode(vehicle, mode_name):
    print(f"Setting mode to {mode_name}...")
    
    timeout = time.time() + 2
    while not vehicle.mode_mapping() and time.time() < timeout:
        time.sleep(0.1)

    if not vehicle.mode_mapping():
        print("Error: Flight controller has not transmitted mode mapping yet.")
        return

    if mode_name not in vehicle.mode_mapping(): # returns a dictionary of all available modes  
        print(f"Unknown mode: {mode_name}")
        print(f"Available modes: {list(vehicle.mode_mapping().keys())}")  
        return

    mode_id = vehicle.mode_mapping()[mode_name] # MAVLink number for the mode
    vehicle.mav.set_mode_send(  
        vehicle.target_system, 
        mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED, # Custom flight mode flag
        mode_id
    )
    print(f"Mode {mode_name} set!")

def takeoff(vehicle, altitude_m):
    print(f"Taking off to {altitude_m}m...")
    vehicle.mav.command_long_send(  
        vehicle.target_system,  
        vehicle.target_component,  
        mavutil.mavlink.MAV_CMD_NAV_TAKEOFF, # MAVLink command for takeoff, altitude_m is the target height in meters
        0,
        0, 0, 0, 0, 0, 0,
        altitude_m
    )
    print("Takeoff command sent!")

def goto(vehicle, lat, lon, alt):
    print(f"Flying to {lat}, {lon} @ {alt}m...")
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
    print("Goto command sent!")