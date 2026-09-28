import pytest
import time
from unittest.mock import MagicMock
from gcs.command_manager import CommandManager, ACK_RESULT_NAMES
from gcs.commands import disarm
from gcs.telemetry import telemetry_data

class FakeAckMessage:
    def __init__(self, command, result, src_sys=1, src_comp=1, progress=0, result_param2=0):
        self.command = command
        self.result = result
        self._src_sys = src_sys
        self._src_comp = src_comp
        self.progress = progress
        self.result_param2 = result_param2

    def get_srcSystem(self):
        return self._src_sys

    def get_srcComponent(self):
        return self._src_comp

def test_command_ack_accepted():
    mgr = CommandManager()
    pending = mgr.register(command_id=400, target_system=1, target_component=1, timeout=2.0)
    
    # Simulate incoming ACCEPTED ACK
    ack = FakeAckMessage(command=400, result=0, src_sys=1, src_comp=1)
    routed = mgr.handle_ack(ack)
    assert routed is pending
    
    ok, res_str, code = pending.wait()
    assert ok is True
    assert res_str == "ACCEPTED"
    assert code == 0

def test_command_ack_denied():
    mgr = CommandManager()
    pending = mgr.register(command_id=22, target_system=1, target_component=1, timeout=2.0)
    
    # Simulate incoming DENIED ACK
    ack = FakeAckMessage(command=22, result=2, src_sys=1, src_comp=1)
    mgr.handle_ack(ack)
    
    ok, res_str, code = pending.wait()
    assert ok is False
    assert res_str == "DENIED"
    assert code == 2

def test_command_ack_in_progress_then_accepted():
    mgr = CommandManager()
    pending = mgr.register(command_id=192, target_system=1, target_component=1, timeout=2.0)
    
    # First: IN_PROGRESS
    ack_prog = FakeAckMessage(command=192, result=5, src_sys=1, src_comp=1, progress=50)
    mgr.handle_ack(ack_prog)
    assert pending.progress == 50
    assert not pending.event.is_set()
    
    # Second: ACCEPTED
    ack_done = FakeAckMessage(command=192, result=0, src_sys=1, src_comp=1, progress=100)
    mgr.handle_ack(ack_done)
    
    ok, res_str, code = pending.wait()
    assert ok is True
    assert res_str == "ACCEPTED"

def test_command_ack_timeout():
    mgr = CommandManager()
    pending = mgr.register(command_id=999, target_system=1, target_component=1, timeout=0.2)
    ok, res_str, code = pending.wait()
    assert ok is False
    assert "TIMEOUT" in res_str
    assert code is None

def test_airborne_disarm_guard():
    fake_vehicle = MagicMock()
    fake_vehicle.target_system = 1
    fake_vehicle.target_component = 1
    
    telemetry_data['armed'] = True
    telemetry_data['landed_state'] = 2 # MAV_LANDED_STATE_IN_AIR
    telemetry_data['alt'] = 15.0

    # Normal disarm must be blocked
    ok, msg = disarm(fake_vehicle, force=False)
    assert ok is False
    assert "DISARM BLOCKED" in msg
    assert not fake_vehicle.mav.command_long_send.called

    # Emergency force disarm allowed
    ok, msg = disarm(fake_vehicle, force=True)
    # The command was sent with force param2=21196.0
    assert fake_vehicle.mav.command_long_send.called
