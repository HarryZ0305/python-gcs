from pymavlink import mavutil

def connect(connection_string = 'tcp:127.0.0.1:5760'):
    print("Connecting to vehicle...")
    vehicle = mavutil.mavlink_connection(connection_string) # opens the connection to the simulator
    vehicle.wait_heartbeat() # pauses until drone confirmed alive # type: ignore
    print(f"Connected! System ID: {vehicle.target_system}") # drone ID # type: ignore
    return vehicle

def request_telemetry(vehicle, rate_hz = 4):
    vehicle.mav.request_data_stream_send( # sends MAVLink message to send data 
        vehicle.target_system,  
        vehicle.target_component,  
        mavutil.mavlink.MAV_DATA_STREAM_ALL, # requests all available data streams (GPS, battery, speed, attitude, etc.)
        rate_hz, # how many times per second the drone sends updates
        1 #start streaming
    )
    print(f"Telemetry streams requested at {rate_hz}Hz")