from pymavlink import mavutil

def connect(connection_string='tcp:127.0.0.1:5760'):
    print("Connecting to vehicle...")
    vehicle = mavutil.mavlink_connection(connection_string) # type: ignore
    vehicle.wait_heartbeat() # type: ignore
    print(f"Connected! System ID: {vehicle.target_system}") # type: ignore
    return vehicle