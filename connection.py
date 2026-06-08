import os
from pymavlink import mavutil

# Easy to override connection string via environment variable or default parameter
DEFAULT_CONNECTION = os.environ.get('MAVLINK_CONNECTION', 'udpin:0.0.0.0:14540')

def connect(connection_string = None):
    if connection_string is None:
        connection_string = DEFAULT_CONNECTION
    print(f"Connecting to vehicle at {connection_string}...")
    vehicle = mavutil.mavlink_connection(connection_string) # opens the connection to the simulator
    vehicle.wait_heartbeat() # pauses until drone confirmed alive # type: ignore
    print(f"Connected! System ID: {vehicle.target_system}") # drone ID # type: ignore
    return vehicle

def request_telemetry(vehicle, rate_hz = 4):
    interval_us = int(1e6 / rate_hz)
    
    # Request message intervals for PX4 using MAV_CMD_SET_MESSAGE_INTERVAL
    message_ids = [
        mavutil.mavlink.MAVLINK_MSG_ID_HEARTBEAT,
        mavutil.mavlink.MAVLINK_MSG_ID_ATTITUDE,
        mavutil.mavlink.MAVLINK_MSG_ID_GLOBAL_POSITION_INT,
        mavutil.mavlink.MAVLINK_MSG_ID_SYS_STATUS,
        mavutil.mavlink.MAVLINK_MSG_ID_GPS_RAW_INT,
        mavutil.mavlink.MAVLINK_MSG_ID_VFR_HUD
    ]
    
    for msg_id in message_ids:
        vehicle.mav.command_long_send(
            vehicle.target_system,
            vehicle.target_component,
            mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL,
            0, # confirmation
            msg_id, # param 1: Message ID
            interval_us, # param 2: Interval in microseconds
            0, 0, 0, 0, 0 # param 3-7: Unused
        )
    print(f"PX4 telemetry message intervals requested at {rate_hz}Hz ({interval_us}us)")