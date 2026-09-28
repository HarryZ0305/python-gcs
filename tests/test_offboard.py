"""
Unit tests for OffboardController, dead-man freshness timeout,
and MAVLink setpoint frame/mask encoding.
"""
import time
import pytest
from unittest.mock import MagicMock
from pymavlink import mavutil
from gcs.commands import OffboardController, send_offboard_setpoint

def test_offboard_controller_start_stop():
    mock_vehicle = MagicMock()
    mock_vehicle.target_system = 1
    mock_vehicle.target_component = 1

    ctrl = OffboardController()
    assert ctrl.vehicle is None
    ctrl.start(mock_vehicle)
    assert ctrl.vehicle is mock_vehicle

    ctrl.set_velocity(vx=2.0, vy=0.0, vz=-1.5, yaw_rate=0.5)
    assert ctrl.target_vx == 2.0
    assert ctrl.target_vy == 0.0
    assert ctrl.target_vz == -1.5
    assert ctrl.target_yaw_rate == 0.5

    ctrl.reset_to_hover()
    assert ctrl.target_vx == 0.0
    assert ctrl.target_vy == 0.0
    assert ctrl.target_vz == 0.0
    assert ctrl.target_yaw_rate == 0.0

    ctrl.stop()
    assert ctrl.vehicle is None


def test_dead_man_timeout():
    mock_vehicle = MagicMock()
    mock_vehicle.target_system = 1
    mock_vehicle.target_component = 1

    ctrl = OffboardController()
    ctrl.dead_man_timeout = 0.3 # shorten for faster unit test
    ctrl.start(mock_vehicle)

    try:
        # Set forward velocity
        ctrl.set_velocity(vx=2.0, vy=0.0, vz=0.0, yaw_rate=0.0)
        assert ctrl.target_vx == 2.0

        # Wait for dead-man timer to expire (> 0.3s)
        time.sleep(0.45)

        # Targets must have been zeroed by the streamer thread
        assert ctrl.target_vx == 0.0
        assert ctrl.target_vy == 0.0
        assert ctrl.target_vz == 0.0
        assert ctrl.target_yaw_rate == 0.0
    finally:
        ctrl.stop()


def test_warmup_stream():
    mock_vehicle = MagicMock()
    mock_vehicle.target_system = 1
    mock_vehicle.target_component = 1

    ctrl = OffboardController()
    ctrl.start(mock_vehicle)
    try:
        res = ctrl.warmup(duration_sec=0.25)
        assert res is True
        assert mock_vehicle.mav.send.call_count >= 2
    finally:
        ctrl.stop()


def test_body_ned_frame_and_mask():
    mock_vehicle = MagicMock()
    mock_vehicle.target_system = 1
    mock_vehicle.target_component = 1

    send_offboard_setpoint(mock_vehicle, vx=2.0, vy=-1.0, vz=0.5, yaw_rate=0.2)
    assert mock_vehicle.mav.send.called
    msg = mock_vehicle.mav.send.call_args[0][0]

    # Coordinate frame must be MAV_FRAME_BODY_NED (8)
    assert msg.coordinate_frame == mavutil.mavlink.MAV_FRAME_BODY_NED
    # type_mask 0b010111000111 (0x0DC7) ignores position & acceleration, controls velocity & yaw rate
    assert msg.type_mask == 0b010111000111
    assert msg.vx == 2.0
    assert msg.vy == -1.0
    assert msg.vz == 0.5
    assert msg.yaw_rate == 0.2
