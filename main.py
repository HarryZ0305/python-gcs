from connection import connect, request_telemetry
from commands import arm, disarm, set_mode
import time

vehicle = connect()
request_telemetry(vehicle)

set_mode(vehicle, 'GUIDED')
time.sleep(2)
arm(vehicle)
time.sleep(3)
disarm(vehicle)