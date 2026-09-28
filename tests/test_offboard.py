"""
Unit tests for OffboardController, dead-man freshness timeout,
confirmed OFFBOARD state transitions, and keyboard hold/release/disconnect lifecycle.
"""
import time
import pytest
from unittest.mock import MagicMock
from pymavlink import mavutil
from gcs.commands import OffboardController, send_offboard_setpoint, set_mode
from gcs.telemetry import telemetry_data, reset_telemetry_data

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


def test_offboard_movement_rejected_if_not_confirmed():
    mock_vehicle = MagicMock()
    mock_vehicle.target_system = 1
    mock_vehicle.target_component = 1

    ctrl = OffboardController()
    ctrl.start(mock_vehicle)
    try:
        # 1. Telemetry says mode is POSCTL (not OFFBOARD)
        telemetry_data['mode'] = 'POSCTL'
        ok = ctrl.apply_movement_if_confirmed(vx=2.0, vy=0.0, vz=0.0, yaw_rate=0.0)
        assert ok is False
        assert ctrl.target_vx == 0.0 # Must stay at zero hover

        # 2. Telemetry confirms OFFBOARD
        telemetry_data['mode'] = 'OFFBOARD'
        ok = ctrl.apply_movement_if_confirmed(vx=2.0, vy=0.0, vz=0.0, yaw_rate=0.0)
        assert ok is True
        assert ctrl.target_vx == 2.0
    finally:
        ctrl.stop()


def test_offboard_keyboard_hold_release_and_disconnect():
    mock_vehicle = MagicMock()
    mock_vehicle.target_system = 1
    mock_vehicle.target_component = 1

    ctrl = OffboardController()
    ctrl.start(mock_vehicle)
    telemetry_data['mode'] = 'OFFBOARD'

    try:
        # Sustained hold of Forward key (W)
        ok = ctrl.apply_movement_if_confirmed(vx=2.0, vy=0.0, vz=0.0, yaw_rate=0.0)
        assert ok is True
        assert ctrl.target_vx == 2.0

        # Sustained hold of Forward + Right (W + D)
        ok = ctrl.apply_movement_if_confirmed(vx=2.0, vy=2.0, vz=0.0, yaw_rate=0.0)
        assert ok is True
        assert ctrl.target_vx == 2.0 and ctrl.target_vy == 2.0

        # Release keys -> reset to hover
        ctrl.reset_to_hover()
        assert ctrl.target_vx == 0.0 and ctrl.target_vy == 0.0

        # Disconnect -> stop controller
        ctrl.stop()
        assert ctrl.vehicle is None
        assert ctrl.target_vx == 0.0
    finally:
        ctrl.stop()


def test_set_mode_unconfirmed_fails():
    reset_telemetry_data()
    mock_vehicle = MagicMock()
    mock_vehicle.target_system = 1
    mock_vehicle.target_component = 1
    mock_vehicle.mode_mapping.return_value = {'OFFBOARD': (1, 6, 0)}

    from gcs.command_manager import command_manager
    from gcs.telemetry import handle_mavlink_message
    from test_commands_ack import FakeAckMessage

    # Background thread sends ACCEPTED ACK, but telemetry mode never changes from STABILIZED
    telemetry_data['mode'] = 'STABILIZED'
    
    # We will trigger the ACK shortly after
    def send_ack():
        time.sleep(0.1)
        command_manager.handle_ack(
            FakeAckMessage(command=mavutil.mavlink.MAV_CMD_DO_SET_MODE, result=0, src_sys=1, src_comp=1)
        )

    import threading
    t = threading.Thread(target=send_ack, daemon=True)
    t.start()

    # set_mode should return False because telemetry never confirmed OFFBOARD!
    ok, msg = set_mode(mock_vehicle, 'OFFBOARD', confirm_timeout=0.4, warmup_sec=0.0)
    t.join(timeout=1.0)

    assert ok is False
    assert "unconfirmed" in msg.lower()
