import json
import tempfile
import os
import sys
import pytest
from PyQt6.QtWidgets import QApplication
from gcs.plan_format import export_qgc_plan, import_plan_file, calculate_mission_stats
from gcs.ui.plan_view import PlanView
from gcs.ui.flight_instruments import PrimaryFlightDisplay
from gcs.ui.camera_view import VideoCaptureWorker, CameraView


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def test_plan_unsupported_commands_detection():
    # Construct a QGC plan containing an unsupported complex command (e.g. 999)
    plan_data = {
        "fileType": "Plan",
        "version": 1,
        "groundStation": "QGroundControl",
        "mission": {
            "version": 2,
            "cruiseSpeed": 5.0,
            "hoverSpeed": 3.0,
            "items": [
                {
                    "autoContinue": True,
                    "command": 22,
                    "frame": 3,
                    "params": [0, 0, 0, None, 47.3977, 8.5455, 10.0],
                    "type": "SimpleItem"
                },
                {
                    "autoContinue": True,
                    "command": 16,
                    "frame": 3,
                    "params": [0, 2.0, 0, None, 47.3980, 8.5460, 15.0],
                    "type": "SimpleItem"
                },
                {
                    "autoContinue": True,
                    "command": 999,  # Unsupported command
                    "frame": 3,
                    "params": [0, 0, 0, None, 47.3990, 8.5470, 20.0],
                    "type": "SimpleItem"
                }
            ]
        }
    }

    with tempfile.NamedTemporaryFile("w", suffix=".plan", delete=False) as f:
        json.dump(plan_data, f)
        temp_path = f.name

    try:
        ok, wps, takeoff, landing, alt, msg = import_plan_file(temp_path)
        assert ok is True
        assert len(wps) >= 1
        # The message must explicitly warn the operator about unsupported command 999
        assert "unsupported command" in msg.lower()
        assert "999" in msg
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def test_mission_stats_calculation():
    waypoints = [
        [47.398742, 8.545594, 20.0],
        [47.398742, 8.547594, 20.0],
    ]
    takeoff = [47.397742, 8.545594, 10.0]
    landing = [47.397742, 8.545594, 0.0]

    stats = calculate_mission_stats(waypoints, takeoff_point=takeoff, landing_point=landing, cruise_speed=5.0)
    assert stats["item_count"] == 4
    assert stats["total_distance_m"] > 100.0
    assert stats["est_flight_time_s"] > 20.0
    assert stats["est_energy_wh"] > 0.5
    assert "assumptions" in stats
    assert "5.0 m/s" in stats["assumptions"]


def test_plan_empty_stats():
    stats = calculate_mission_stats([])
    assert stats["item_count"] == 0
    assert stats["total_distance_m"] == 0.0
    assert stats["est_flight_time_s"] == 0.0


from PyQt6.QtCore import QObject, pyqtSignal

class MockMapView(QObject):
    waypoint_added = pyqtSignal(float, float)
    takeoff_added = pyqtSignal(float, float)
    landing_added = pyqtSignal(float, float)

    def set_waypoints(self, *args, **kwargs):
        pass


def test_plan_view_undo_redo_and_table(qapp):
    mock_map = MockMapView()
    plan_view = PlanView(map_view=mock_map)
    assert plan_view.table.rowCount() == 0

    # Add waypoint 1
    plan_view.add_waypoint(47.3977, 8.5455, 15.0)
    assert plan_view.table.rowCount() == 1
    assert len(plan_view.waypoints) == 1
    assert "UNSAVED CHANGES" in plan_view.sync_badge.text()

    # Add waypoint 2
    plan_view.add_waypoint(47.3980, 8.5460, 20.0)
    assert plan_view.table.rowCount() == 2
    assert len(plan_view.waypoints) == 2

    # Undo
    plan_view.undo()
    assert plan_view.table.rowCount() == 1
    assert len(plan_view.waypoints) == 1

    # Redo
    plan_view.redo()
    assert plan_view.table.rowCount() == 2
    assert len(plan_view.waypoints) == 2

    # Clear draft
    plan_view.clear_plan()
    assert plan_view.table.rowCount() == 0
    assert len(plan_view.waypoints) == 0


def test_pfd_instrument_attitude_update(qapp):
    pfd = PrimaryFlightDisplay()
    pfd.set_telemetry(roll=-15.2, pitch=10.5, yaw=180.0, alt=50.0, groundspeed=12.0, climb_rate=1.5, is_stale=False)
    assert pfd.pitch == 10.5
    assert pfd.roll == -15.2
    assert pfd.yaw == 180.0
    assert pfd.is_stale is False

    # Stale telemetry flag
    pfd.set_telemetry(roll=-15.2, pitch=10.5, yaw=180.0, alt=50.0, groundspeed=12.0, climb_rate=1.5, is_stale=True)
    assert pfd.is_stale is True


def test_camera_view_initial_and_stale_state(qapp):
    cam = CameraView()
    assert cam.stream_state == "DISCONNECTED"

    # Simulate fresh frame
    import time
    cam.last_frame_time = time.monotonic()
    cam._check_freshness()
    # If not connected and no frames, remains disconnected
    assert cam.stream_state == "DISCONNECTED"

    # Set LIVE then simulate age > 2.0s
    cam.stream_state = "LIVE"
    cam.last_frame_time = time.monotonic() - 3.0
    cam._check_freshness()
    assert cam.stream_state == "STALE"
    cam.stop_stream()
