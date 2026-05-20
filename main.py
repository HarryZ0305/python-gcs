from connection import connect, request_telemetry
from commands import arm, disarm, set_mode, takeoff, goto
from telemetry import read_telemetry, telemetry_data, wait_for_altitude, wait_for_arm
import time
import threading

vehicle = connect()
request_telemetry(vehicle)

# Start telemetry reading in background
telemetry_thread = threading.Thread(target = read_telemetry, args = (vehicle,)) # runs read_telemetry at the same time as the rest of the code
telemetry_thread.daemon = True # thread will automatically stop when the main program exits
telemetry_thread.start()

time.sleep(2)

set_mode(vehicle, 'GUIDED')
time.sleep(2)
arm(vehicle)
wait_for_arm(vehicle)
takeoff(vehicle, 10)
wait_for_altitude(10)
goto(vehicle, 32.7160, -117.1610, 10)