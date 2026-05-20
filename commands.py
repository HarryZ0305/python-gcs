from pymavlink import mavutil

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