"""
Unit tests for telemetry session lifecycle, stale heartbeat detection,
message filtering, and per-source packet loss isolation.
"""
import time
import pytest
from unittest.mock import MagicMock
from gcs.telemetry import (
    TelemetrySession,
    start_telemetry_session,
    cancel_current_session,
    is_heartbeat_stale,
    telemetry_data,
    link_stats,
    handle_mavlink_message,
    reset_telemetry_data,
    battery_config,
    HEARTBEAT_TIMEOUT_SEC,
)

class FakeMessage:
    def __init__(self, msg_type, sys_id=1, comp_id=1, **kwargs):
        self._type = msg_type
        self._header = MagicMock()
        self._header.srcSystem = sys_id
        self._header.srcComponent = comp_id
        self._header.seq = kwargs.get('seq', 0)
        for k, v in kwargs.items():
            setattr(self, k, v)

    def get_type(self):
        return self._type

    def get_srcSystem(self):
        return self._header.srcSystem

    def get_srcComponent(self):
        return self._header.srcComponent


def test_session_lifecycle():
    session = TelemetrySession()
    assert session.is_active is True
    session.cancel()
    assert session.is_active is False

    # Test start_telemetry_session cancels previous
    s1 = start_telemetry_session()
    assert s1.is_active is True
    s2 = start_telemetry_session()
    assert s1.is_active is False
    assert s2.is_active is True
    cancel_current_session()
    assert s2.is_active is False


def test_heartbeat_stale_detection():
    # When no heartbeat received
    telemetry_data['last_heartbeat_monotonic'] = 0.0
    assert is_heartbeat_stale(timeout_sec=3.0) is True

    # When heartbeat is fresh
    telemetry_data['last_heartbeat_monotonic'] = time.monotonic()
    assert is_heartbeat_stale(timeout_sec=3.0) is False

    # When heartbeat is 4 seconds old
    telemetry_data['last_heartbeat_monotonic'] = time.monotonic() - 4.0
    assert is_heartbeat_stale(timeout_sec=3.0) is True


def test_component_filtering():
    # Target sysid=1, compid=1
    telemetry_data['sysid'] = 1
    telemetry_data['compid'] = 1
    telemetry_data['armed'] = False
    telemetry_data['last_heartbeat_monotonic'] = 0.0

    # Companion computer (comp_id=197) or camera (comp_id=200) heartbeat should NOT drive arming or primary heartbeat
    companion_hb = FakeMessage('HEARTBEAT', sys_id=1, comp_id=197, base_mode=128, custom_mode=0, system_status=4)
    handle_mavlink_message(companion_hb)
    assert telemetry_data['last_heartbeat_monotonic'] == 0.0

    # Autopilot heartbeat (comp_id=1) MUST update status
    autopilot_hb = FakeMessage('HEARTBEAT', sys_id=1, comp_id=1, base_mode=128, custom_mode=0x01030000, system_status=3) # 128 has MAV_MODE_FLAG_SAFETY_ARMED
    handle_mavlink_message(autopilot_hb)
    assert telemetry_data['last_heartbeat_monotonic'] > 0.0
    assert telemetry_data['armed'] is True
    assert telemetry_data['system_status'] == 3


def test_per_source_packet_loss_isolation():
    session = start_telemetry_session()
    telemetry_data['sysid'] = 1
    telemetry_data['compid'] = 1

    # Component 1 (autopilot) sends packets: 0, 1, 2 (no gaps)
    p0 = FakeMessage('STATUSTEXT', sys_id=1, comp_id=1, seq=0, text=b'ok\x00', severity=6)
    p1 = FakeMessage('STATUSTEXT', sys_id=1, comp_id=1, seq=1, text=b'ok\x00', severity=6)
    p2 = FakeMessage('STATUSTEXT', sys_id=1, comp_id=1, seq=2, text=b'ok\x00', severity=6)

    # Interleaved companion component (comp 197) sends packets with totally different sequence numbers
    c0 = FakeMessage('STATUSTEXT', sys_id=1, comp_id=197, seq=50, text=b'ok\x00', severity=6)
    c1 = FakeMessage('STATUSTEXT', sys_id=1, comp_id=197, seq=80, text=b'ok\x00', severity=6)

    handle_mavlink_message(p0)
    handle_mavlink_message(c0)
    handle_mavlink_message(p1)
    handle_mavlink_message(c1)
    handle_mavlink_message(p2)

    # Component 1 continues with sequence 3
    p3 = FakeMessage('STATUSTEXT', sys_id=1, comp_id=1, seq=3, text=b'ok\x00', severity=6)
    handle_mavlink_message(p3)

    # Autopilot component 1 sequence was completely contiguous: 0, 1, 2, 3 -> ZERO dropped
    assert telemetry_data['packets_lost'] == 0
    assert telemetry_data['packet_loss_pct'] == 0.0
    assert telemetry_data['packets_received'] == 4
    cancel_current_session()
