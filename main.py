from connection import connect, request_telemetry
from commands import arm, disarm, set_mode, takeoff, goto
import time

vehicle = connect()
request_telemetry(vehicle)

set_mode(vehicle, 'GUIDED')
time.sleep(2)
arm(vehicle)
time.sleep(3)
takeoff(vehicle, 10)
time.sleep(5)
goto(vehicle, 32.7160, -117.1610, 10)
time.sleep(5)
disarm(vehicle)