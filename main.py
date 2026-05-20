from connection import connect, request_telemetry
from commands import arm, disarm, set_mode, takeoff, goto
from telemetry import read_telemetry, telemetry_data, wait_for_altitude, wait_for_arm, wait_for_gps
import time
import threading

vehicle = connect()
request_telemetry(vehicle)

# Start telemetry reading in background
telemetry_thread = threading.Thread(target = read_telemetry, args = (vehicle,)) # runs read_telemetry at the same time as the rest of the code
telemetry_thread.daemon = True # thread will automatically stop when the main program exits
telemetry_thread.start()

if wait_for_gps(): # waits for 3D fix 
    set_mode(vehicle, 'GUIDED')
    time.sleep(1)                           
    arm(vehicle)
    if wait_for_arm(): # if drone arms successfully within timeout, takeoff
        takeoff(vehicle, 10)
        if wait_for_altitude(10): # if drone reaches target altitude within timeout, goto target location
            goto(vehicle, 32.7160, -117.1610, 10)
        else:
            print("Aborting: Failed to reach target altitude.")
    else:
        print("Aborting: Drone failed to arm.")
else:
    print("Aborting: Could not acquire GPS fix.")