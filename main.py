from connection import connect, request_telemetry
from commands import arm, disarm, set_mode, takeoff, goto
from telemetry import read_telemetry, telemetry_data, wait_for_altitude, wait_for_arm, wait_for_gps
from ui.gui import launch_gui     
import time
import threading

SIMULATION = False

from logs import log

def flight_sequence(vehicle):
    if wait_for_gps():
        log("Simulation sequence: Initiating takeoff...")
        takeoff(vehicle, 10)
        if wait_for_altitude(10):
            log("Simulation sequence: Target altitude reached. Holding position in LOITER.")
            set_mode(vehicle, 'AUTO.LOITER')
        else:
            log("Simulation sequence aborted: Failed to reach target altitude.")
    else:
        log("Simulation sequence aborted: Could not acquire GPS fix.")

vehicle = connect()
request_telemetry(vehicle)

# Start telemetry reading in background first before GUI
telemetry_thread = threading.Thread(target = read_telemetry, args = (vehicle,)) # runs read_telemetry at the same time as the rest of the code
telemetry_thread.daemon = True # thread will automatically stop when the main program exits
telemetry_thread.start()

# start flight logic in background thread before GUI takes over the main thread
if SIMULATION:
    flight_thread = threading.Thread(target = flight_sequence, args = (vehicle,))
    flight_thread.daemon = True # dies automatically when main program exits
    flight_thread.start()

launch_gui(vehicle)