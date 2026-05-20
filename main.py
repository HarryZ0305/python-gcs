from connection import connect, request_telemetry
from commands import arm, disarm, set_mode, takeoff, goto
from telemetry import read_telemetry, telemetry_data
import time
import threading

vehicle = connect()
request_telemetry(vehicle)

# Start telemetry reading in background
telemetry_thread = threading.Thread(target = read_telemetry, args = (vehicle,)) # runs read_telemetry at the same time as the rest of the code
telemetry_thread.daemon = True # thread will automatically stop when the main program exits
telemetry_thread.start()

print("Telemetry running in background...")
time.sleep(2)
print(f"Current altitude: {telemetry_data['alt']}m")