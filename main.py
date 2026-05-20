from connection import connect, request_telemetry
from commands import arm, disarm
import time

vehicle = connect()
request_telemetry(vehicle)

arm(vehicle)
time.sleep(3)
disarm(vehicle)