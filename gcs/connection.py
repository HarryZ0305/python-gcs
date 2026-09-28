import os
import time
from pymavlink import mavutil
from gcs.logs import log

# Easy to override connection string via environment variable or default parameter
DEFAULT_CONNECTION = os.environ.get('MAVLINK_CONNECTION', 'udpin:0.0.0.0:14540')

def connect(connection_string=None, timeout=None):
    if connection_string is None:
        connection_string = DEFAULT_CONNECTION
    log(f"Connecting to vehicle at {connection_string}...")
    vehicle = mavutil.mavlink_connection(connection_string)
    
    start_t = time.monotonic()
    msg = None

    autopilot_comps = (mavutil.mavlink.MAV_COMP_ID_AUTOPILOT1, 1)
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

    if timeout is not None:
        while time.monotonic() - start_t < timeout:
            msg = vehicle.wait_heartbeat(timeout=min(1.0, max(0.1, timeout - (time.monotonic() - start_t))))
            if msg is not None:
                is_ap = (
                    (msg.get_srcComponent() in autopilot_comps or getattr(msg, 'autopilot', 0) == mavutil.mavlink.MAV_AUTOPILOT_PX4)
                    and (msg.type in autopilot_types or msg.type != mavutil.mavlink.MAV_TYPE_GCS)
                )
                if is_ap:
                    break
                msg = None
        if msg is None:
            log("Connection timeout: No autopilot heartbeat received. Closing connection.")
            try:
                vehicle.close()
            except Exception:
                pass
            return None
    else:
        while True:
            msg = vehicle.wait_heartbeat()
            if msg is not None:
                is_ap = (
                    (msg.get_srcComponent() in autopilot_comps or getattr(msg, 'autopilot', 0) == mavutil.mavlink.MAV_AUTOPILOT_PX4)
                    and (msg.type in autopilot_types or msg.type != mavutil.mavlink.MAV_TYPE_GCS)
                )
                if is_ap:
                    break

    vehicle.target_system = msg.get_srcSystem()
    vehicle.target_component = msg.get_srcComponent()
    log(f"Connected! Autopilot System ID: {vehicle.target_system}, Component ID: {vehicle.target_component}")
    return vehicle

def request_telemetry(vehicle, rate_hz=4):
    from gcs.commands import mav_lock
    interval_us = int(1e6 / rate_hz)
    
    # Request message intervals for PX4 using MAV_CMD_SET_MESSAGE_INTERVAL
    message_ids = [
        mavutil.mavlink.MAVLINK_MSG_ID_HEARTBEAT,
        mavutil.mavlink.MAVLINK_MSG_ID_ATTITUDE,
        mavutil.mavlink.MAVLINK_MSG_ID_GLOBAL_POSITION_INT,
        mavutil.mavlink.MAVLINK_MSG_ID_SYS_STATUS,
        mavutil.mavlink.MAVLINK_MSG_ID_GPS_RAW_INT,
        mavutil.mavlink.MAVLINK_MSG_ID_VFR_HUD,
        mavutil.mavlink.MAVLINK_MSG_ID_EXTENDED_SYS_STATE,
        mavutil.mavlink.MAVLINK_MSG_ID_HOME_POSITION,
        mavutil.mavlink.MAVLINK_MSG_ID_BATTERY_STATUS,
        mavutil.mavlink.MAVLINK_MSG_ID_VIBRATION
    ]
    
    with mav_lock:
        for msg_id in message_ids:
            try:
                vehicle.mav.command_long_send(
                    vehicle.target_system,
                    vehicle.target_component,
                    mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL,
                    0, # confirmation
                    msg_id, # param 1: Message ID
                    interval_us, # param 2: Interval in microseconds
                    0, 0, 0, 0, 0 # param 3-7: Unused
                )
            except Exception as e:
                log(f"Error requesting message {msg_id}: {e}")
                
    log(f"PX4 telemetry message intervals requested at {rate_hz}Hz ({interval_us}us)")
