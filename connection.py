from pymavlink import mavutil

def connect(connection_string = 'tcp:127.0.0.1:5760'):
    print("Connecting to vehicle...")
    vehicle = mavutil.mavlink_connection(connection_string) 
    vehicle.wait_heartbeat() # type: ignore
    print(f"Connected! System ID: {vehicle.target_system}") # type: ignore
    return vehicle

def request_telemetry(vehicle, rate_hz = 4):
    vehicle.mav.request_data_stream_send(  
        vehicle.target_system,  
        vehicle.target_component,  
        mavutil.mavlink.MAV_DATA_STREAM_ALL,
        rate_hz,
        1
    )
    print(f"Telemetry streams requested at {rate_hz}Hz")