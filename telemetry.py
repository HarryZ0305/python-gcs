import time
from pymavlink import mavutil

telemetry_data = { # dictionary that holds the latest values from the drone
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
            blocking = True,
            timeout = 5
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

def wait_for_arm(vehicle, timeout = 10):
    print("Waiting for drone to arm...")
    start_time = time.time()
    
    while True:
        msg = vehicle.recv_match(type = 'HEARTBEAT', blocking = True, timeout = 3)  
        
        if msg:
            armed = bool(msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
            if armed:
                print("Drone is armed!")
                return True
        
        if time.time() - start_time > timeout:
            print("Timeout! Drone did not arm")
            return False
        
        time.sleep(0.5)

def wait_for_altitude(target_alt, tolerance = 0.95, timeout = 30): # tolerance = 0.95 rather than 1 since drone might hover slightly below
    print(f"Waiting to reach {target_alt}m...")
    start_time = time.time()
    
    while True:
        current_alt = telemetry_data['alt']
        print(f"Current altitude: {current_alt:.1f}m / {target_alt}m")
        
        if current_alt >= target_alt * tolerance:
            print(f"Target altitude reached!")
            return True
        
        if time.time() - start_time > timeout: # timeout check
            print("Timeout! Could not reach target altitude")
            return False
        
        time.sleep(0.5)