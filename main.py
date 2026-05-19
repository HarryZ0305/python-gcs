from connection import connect, request_telemetry

vehicle = connect()
request_telemetry(vehicle)