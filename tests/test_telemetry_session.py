"""
Unit tests for telemetry session lifecycle, stale heartbeat detection,
and message filtering.
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
    autopilot_hb = FakeMessage('HEARTBEAT', sys_id=1, comp_id=1, base_mode=128, custom_mode=0x01030000, system_status=4) # 128 has MAV_MODE_FLAG_SAFETY_ARMED
    handle_mavlink_message(autopilot_hb)
    assert telemetry_data['last_heartbeat_monotonic'] > 0.0
    assert telemetry_data['armed'] is True


def test_packet_loss_calculation():
    session = start_telemetry_session()
    telemetry_data['sysid'] = 1
    telemetry_data['compid'] = 1

    # Send packets with sequences: 0, 1, 2, then 5 (missing 3, 4)
    p0 = FakeMessage('STATUSTEXT', sys_id=1, comp_id=1, seq=0, text=b'ok\x00', severity=6)
    p1 = FakeMessage('STATUSTEXT', sys_id=1, comp_id=1, seq=1, text=b'ok\x00', severity=6)
    p2 = FakeMessage('STATUSTEXT', sys_id=1, comp_id=1, seq=2, text=b'ok\x00', severity=6)
    p5 = FakeMessage('STATUSTEXT', sys_id=1, comp_id=1, seq=5, text=b'ok\x00', severity=6)

    handle_mavlink_message(p0)
    handle_mavlink_message(p1)
    handle_mavlink_message(p2)
    handle_mavlink_message(p5)

    assert link_stats['packets_dropped'] == 2
    assert link_stats['packets_received'] == 4
    # Packet loss = 2 / (4 + 2) = 33.3%
    assert 30.0 < link_stats['packet_loss_pct'] < 35.0
    cancel_current_session()
