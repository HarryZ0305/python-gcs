from pymavlink import mavutil

telemetry_data = { # dictionary that  holds the latest values from the drone
    'lat': 0.0,
    'lon': 0.0,
    'alt': 0.0,
    'groundspeed': 0.0,
    'throttle': 0,
    'battery': 0,
    'satellites': 0,
    'fix_type': 0
}

def read_telemetry(vehicle):
    while True: # constantly updating the dictionary
        msg = vehicle.recv_match(  # type: ignore
            type=['GLOBAL_POSITION_INT', 'VFR_HUD', 'SYS_STATUS', 'GPS_RAW_INT'],
            blocking=True,
            timeout=5
        )

        if not msg:
            continue

        msg_type = msg.get_type()

        if msg_type == 'GLOBAL_POSITION_INT':
            telemetry_data['lat'] = msg.lat / 1e7
            telemetry_data['lon'] = msg.lon / 1e7
            telemetry_data['alt'] = msg.relative_alt / 1000

        elif msg_type == 'VFR_HUD':
            telemetry_data['groundspeed'] = msg.groundspeed
            telemetry_data['throttle'] = msg.throttle

        elif msg_type == 'SYS_STATUS':
            telemetry_data['battery'] = msg.battery_remaining

        elif msg_type == 'GPS_RAW_INT':
            telemetry_data['satellites'] = msg.satellites_visible
            telemetry_data['fix_type'] = msg.fix_type