from connection import connect, request_telemetry
from telemetry import read_telemetry

vehicle = connect()
request_telemetry(vehicle)

print("Reading telemetry...")
while True:
    read_telemetry(vehicle)