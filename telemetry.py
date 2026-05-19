from pymavlink import mavutil

def read_telemetry(vehicle):
    msg = vehicle.recv_match( # listens for specific data types  
        type = ['GLOBAL_POSITION_INT', 'VFR_HUD', 'SYS_STATUS', 'GPS_RAW_INT'],
        blocking = True, # wait until message arrives or until 5 seconds
        timeout = 5
    )

    if not msg:
        print("No message received")
        return

    msg_type = msg.get_type()

    if msg_type == 'GLOBAL_POSITION_INT':
        lat = msg.lat / 1e7
        lon = msg.lon / 1e7
        alt = msg.relative_alt / 1000
        print(f"Position: {lat}, {lon} @ {alt}m")

    elif msg_type == 'VFR_HUD':
        print(f"Speed: {msg.groundspeed:.1f} m/s  Throttle: {msg.throttle}%")

    elif msg_type == 'SYS_STATUS':
        print(f"Battery: {msg.battery_remaining}%")

    elif msg_type == 'GPS_RAW_INT':
        print(f"Satellites: {msg.satellites_visible}  Fix: {msg.fix_type}")