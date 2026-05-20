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