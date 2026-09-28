"""
Unit tests for PX4 mission validation, published QGroundControl .plan schema compliance,
atomic mission upload, and readback download verification.
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
from gcs.commands import upload_mission, download_mission
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


def test_qgc_plan_published_schema_compliance():
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

        with open(plan_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # 1. Top level QGC required fields
        assert data.get("fileType") == "Plan"
        assert data.get("version") == 1
        assert "groundStation" in data
        assert "mission" in data
        assert "geoFence" in data
        assert "rallyPoints" in data

        # 2. Mission object required fields
        m = data["mission"]
        assert m.get("version") == 2
        assert m.get("vehicleType") == 2
        assert m.get("globalPlanAltitudeMode") == 1
        assert m.get("cruiseSpeed") == 6.0
        assert len(m.get("plannedHomePosition", [])) == 3

        # 3. SimpleItem required fields
        items = m["items"]
        assert len(items) == 4 # Takeoff + 2 WPs + Land
        for idx, it in enumerate(items, 1):
            assert it.get("type") == "SimpleItem"
            assert it.get("doJumpId") == idx
            assert it.get("AltitudeMode") == 1
            assert "Altitude" in it
            assert it.get("Altitude") == it["params"][6]
            assert it.get("AMSLAltAboveTerrain") is None
            assert len(it.get("params", [])) == 7
            assert it.get("autoContinue") is True
            assert it.get("frame") == 3

        # 4. geoFence and rallyPoints schema
        assert data["geoFence"].get("version") == 2
        assert data["rallyPoints"].get("version") == 2

        # 5. Import back round trip
        imp_ok, imp_wps, imp_to, imp_land, imp_alt, msg = import_plan_file(plan_path)
        assert imp_ok is True
        assert len(imp_wps) == 2
        assert abs(imp_to[0] - takeoff[0]) < 1e-5
        assert abs(imp_land[0] - landing[0]) < 1e-5
    finally:
        if os.path.exists(plan_path):
            os.remove(plan_path)


def test_upload_mission_with_verification():
    mock_vehicle = MagicMock()
    mock_vehicle.target_system = 1
    mock_vehicle.target_component = 1

    takeoff = [47.3977, 8.5455, 10.0]
    waypoints = [[47.3980, 8.5460, 15.0]]

    # Simulated vehicle response thread (upload + readback download)
    def simulated_autopilot():
        time.sleep(0.05)
        # Upload phase: request seq 0, seq 1, then ACK
        mission_queue.put(FakeMissionMsg('MISSION_REQUEST_INT', seq=0))
        time.sleep(0.03)
        mission_queue.put(FakeMissionMsg('MISSION_REQUEST_INT', seq=1))
        time.sleep(0.03)
        mission_queue.put(FakeMissionMsg('MISSION_ACK', type=mavutil.mavlink.MAV_MISSION_ACCEPTED))

        # Verification download phase: vehicle responds to MISSION_REQUEST_LIST
        time.sleep(0.05)
        mission_queue.put(FakeMissionMsg('MISSION_COUNT', count=2))
        time.sleep(0.03)
        # Sequence 0 download
        mission_queue.put(FakeMissionMsg(
            'MISSION_ITEM_INT', seq=0, command=mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,
            frame=mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT,
            x=int(takeoff[0] * 1e7), y=int(takeoff[1] * 1e7), z=10.0
        ))
        time.sleep(0.03)
        # Sequence 1 download
        mission_queue.put(FakeMissionMsg(
            'MISSION_ITEM_INT', seq=1, command=mavutil.mavlink.MAV_CMD_NAV_WAYPOINT,
            frame=mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT,
            x=int(waypoints[0][0] * 1e7), y=int(waypoints[0][1] * 1e7), z=15.0
        ))

    t = threading.Thread(target=simulated_autopilot, daemon=True)
    t.start()

    ok, msg = upload_mission(mock_vehicle, waypoints, takeoff, None, target_alt=10.0, verify_after_upload=True)
    t.join(timeout=2.0)

    assert ok is True
    assert "verified" in msg.lower()


def test_upload_mission_corrupted_readback_fails_verification():
    mock_vehicle = MagicMock()
    mock_vehicle.target_system = 1
    mock_vehicle.target_component = 1

    takeoff = [47.3977, 8.5455, 10.0]
    waypoints = [[47.3980, 8.5460, 15.0]]

    # Simulated vehicle returning mismatched item count during download
    def simulated_autopilot_corrupt():
        time.sleep(0.05)
        mission_queue.put(FakeMissionMsg('MISSION_REQUEST_INT', seq=0))
        time.sleep(0.03)
        mission_queue.put(FakeMissionMsg('MISSION_REQUEST_INT', seq=1))
        time.sleep(0.03)
        mission_queue.put(FakeMissionMsg('MISSION_ACK', type=mavutil.mavlink.MAV_MISSION_ACCEPTED))

        # Vehicle claims it only saved 1 item!
        time.sleep(0.05)
        mission_queue.put(FakeMissionMsg('MISSION_COUNT', count=1))
        time.sleep(0.03)
        mission_queue.put(FakeMissionMsg(
            'MISSION_ITEM_INT', seq=0, command=mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,
            frame=mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT,
            x=int(takeoff[0] * 1e7), y=int(takeoff[1] * 1e7), z=10.0
        ))

    t = threading.Thread(target=simulated_autopilot_corrupt, daemon=True)
    t.start()

    ok, msg = upload_mission(mock_vehicle, waypoints, takeoff, None, target_alt=10.0, verify_after_upload=True)
    t.join(timeout=2.0)

    assert ok is False
    assert "verification failed" in msg.lower()
