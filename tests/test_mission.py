"""
Unit tests for PX4 mission validation, QGroundControl .plan round-trip,
and atomic mission upload protocol.
"""
import os
import time
import json
import tempfile
import threading
import pytest
from unittest.mock import MagicMock
from pymavlink import mavutil
from gcs.plan_format import export_qgc_plan, import_plan_file
from gcs.commands import upload_mission
from gcs.telemetry import mission_queue

class FakeMissionMsg:
    def __init__(self, msg_type, **kwargs):
        self._type = msg_type
        for k, v in kwargs.items():
            setattr(self, k, v)

    def get_type(self):
        return self._type


def test_waypoint_validation_failures():
    mock_vehicle = MagicMock()
    mock_vehicle.target_system = 1
    mock_vehicle.target_component = 1

    # Empty mission
    ok, msg = upload_mission(mock_vehicle, [], None, None)
    assert ok is False
    assert "No mission items" in msg

    # Invalid latitude (> 90)
    bad_coords = [[95.0, 8.5455, 15.0]]
    ok, msg = upload_mission(mock_vehicle, bad_coords, None, None)
    assert ok is False
    assert "Validation error" in msg

    # Invalid altitude (< 1.0m)
    bad_alt = [[47.3977, 8.5455, 0.5]]
    ok, msg = upload_mission(mock_vehicle, bad_alt, None, None)
    assert ok is False
    assert "altitude out of range" in msg

    # Ensure no MAVLink messages were dispatched
    assert mock_vehicle.mav.mission_count_send.call_count == 0


def test_qgc_plan_export_and_import():
    takeoff = [47.397742, 8.545594, 10.0]
    waypoints = [
        [47.398000, 8.546000, 15.0],
        [47.398500, 8.546500, 20.0],
    ]
    landing = [47.397742, 8.545594, 0.0]

    with tempfile.NamedTemporaryFile(suffix=".plan", delete=False) as tf:
        plan_path = tf.name

    try:
        ok = export_qgc_plan(
            plan_path,
            waypoints=waypoints,
            takeoff_point=takeoff,
            landing_point=landing,
            target_alt=15.0,
            cruise_speed=6.0
        )
        assert ok is True

        # Verify QGC JSON structure
        with open(plan_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        assert data.get("fileType") == "Plan"
        assert data.get("version") == 1
        items = data["mission"]["items"]
        assert len(items) == 4 # Takeoff + 2 WPs + Land
        assert items[0]["command"] == 22 # MAV_CMD_NAV_TAKEOFF
        assert items[1]["command"] == 16 # MAV_CMD_NAV_WAYPOINT
        assert items[2]["command"] == 16
        assert items[3]["command"] == 21 # MAV_CMD_NAV_LAND

        # Import back
        imp_ok, imp_wps, imp_to, imp_land, imp_alt, msg = import_plan_file(plan_path)
        assert imp_ok is True
        assert len(imp_wps) == 2
        assert abs(imp_to[0] - takeoff[0]) < 1e-5
        assert abs(imp_to[1] - takeoff[1]) < 1e-5
        assert abs(imp_land[0] - landing[0]) < 1e-5
        assert abs(imp_wps[0][0] - waypoints[0][0]) < 1e-5
        assert abs(imp_wps[0][2] - 15.0) < 1e-3
    finally:
        if os.path.exists(plan_path):
            os.remove(plan_path)


def test_upload_mission_px4_protocol():
    mock_vehicle = MagicMock()
    mock_vehicle.target_system = 1
    mock_vehicle.target_component = 1

    takeoff = [47.3977, 8.5455, 10.0]
    waypoints = [[47.3980, 8.5460, 15.0]]

    # Simulated vehicle response thread
    def simulated_autopilot():
        time.sleep(0.05)
        # Sequence 0 requested
        mission_queue.put(FakeMissionMsg('MISSION_REQUEST_INT', seq=0))
        time.sleep(0.05)
        # Repeated sequence 0 requested (test repeat tolerance)
        mission_queue.put(FakeMissionMsg('MISSION_REQUEST_INT', seq=0))
        time.sleep(0.05)
        # Sequence 1 requested
        mission_queue.put(FakeMissionMsg('MISSION_REQUEST_INT', seq=1))
        time.sleep(0.05)
        # Mission accepted
        mission_queue.put(FakeMissionMsg('MISSION_ACK', type=mavutil.mavlink.MAV_MISSION_ACCEPTED))

    t = threading.Thread(target=simulated_autopilot, daemon=True)
    t.start()

    ok, msg = upload_mission(mock_vehicle, waypoints, takeoff, None, target_alt=10.0)
    t.join(timeout=2.0)

    assert ok is True
    assert "successfully uploaded" in msg

    # Verify MISSION_COUNT was sent with 2 items
    mock_vehicle.mav.mission_count_send.assert_called_once_with(
        1, 1, 2, mavutil.mavlink.MAV_MISSION_TYPE_MISSION
    )

    # Verify item 0 sent was Takeoff (command 22), NOT a fake Home
    calls = mock_vehicle.mav.mission_item_int_send.call_args_list
    assert len(calls) >= 2
    # First call: seq=0, command=22
    assert calls[0][0][2] == 0 # seq
    assert calls[0][0][4] == mavutil.mavlink.MAV_CMD_NAV_TAKEOFF
    # Third call (seq=1): seq=1, command=16
    assert calls[-1][0][2] == 1 # seq
    assert calls[-1][0][4] == mavutil.mavlink.MAV_CMD_NAV_WAYPOINT
