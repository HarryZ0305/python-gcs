import time
import queue
import threading
from pymavlink import mavutil
from logs import log

mission_queue = queue.Queue()

parameters_lock = threading.Lock()
parameters_data = {} # {param_name: {'value': val, 'type': type, 'index': idx, 'count': count}}

telemetry_data = { # dictionary that holds the latest values from the drone
    'lat': 0.0,
    'lon': 0.0,
    'alt': 0.0,
    'groundspeed': 0.0,
    'throttle': 0,
    'battery': 0,
    'satellites': 0,
    'fix_type': 0,
    'armed': False, # tracks whether drone is armed, updated by HEARTBEAT messages from the drone
    'voltage': 0.0, # battery voltage
    'roll': 0.0,      
    'pitch': 0.0,     
    'yaw': 0.0
}

def read_telemetry(vehicle):
    while True: # constantly updating the dictionary
        try:
            msg = vehicle.recv_match(  # type: ignore
                type = ['GLOBAL_POSITION_INT', 'VFR_HUD', 'SYS_STATUS', 'GPS_RAW_INT', 'HEARTBEAT', 'STATUSTEXT', 'ATTITUDE', 'MISSION_REQUEST', 'MISSION_REQUEST_INT', 'MISSION_ACK', 'PARAM_VALUE'],
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
                telemetry_data['voltage'] = msg.voltage_battery / 1000

            elif msg_type == 'GPS_RAW_INT':
                telemetry_data['satellites'] = msg.satellites_visible
                telemetry_data['fix_type'] = msg.fix_type

            elif msg_type == 'HEARTBEAT':
                telemetry_data['armed'] = bool(
                    msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED # bitmask check that isolates the arm bit
                )
            
            elif msg_type == 'STATUSTEXT': # error logs
                log(f"FCU: {msg.text}")
            
            elif msg_type == 'ATTITUDE':
                telemetry_data['roll'] = msg.roll
                telemetry_data['pitch'] = msg.pitch
                telemetry_data['yaw'] = msg.yaw
            
            elif msg_type == 'PARAM_VALUE':
                param_id = msg.param_id
                if isinstance(param_id, bytes):
                    param_id = param_id.decode('utf-8', errors='ignore')
                param_name = param_id.split('\x00')[0]
                
                with parameters_lock:
                    parameters_data[param_name] = {
                        'value': msg.param_value,
                        'type': msg.param_type,
                        'index': msg.param_index,
                        'count': msg.param_count
                    }
            
            elif msg_type in ['MISSION_REQUEST', 'MISSION_REQUEST_INT', 'MISSION_ACK']:
                mission_queue.put(msg)
        except Exception as e:
            log(f"Telemetry error: {e}")
            time.sleep(1)

def wait_for_arm(timeout = 10):
    print("Waiting for drone to arm...")
    start_time = time.time()

    while True:
        if telemetry_data['armed']:
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

def wait_for_gps(timeout = 60): # waits for valid 3D GPS fix              
    print("Waiting for 3D GPS fix...")
    start_time = time.time()

    while True:
        if telemetry_data['fix_type'] >= 3:
            print("3D GPS fix acquired!")
            return True

        if time.time() - start_time > timeout:
            print("Timeout! Could not acquire GPS fix.")
            return False

        time.sleep(0.5)