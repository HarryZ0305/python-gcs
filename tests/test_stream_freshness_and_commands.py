import time
from unittest.mock import MagicMock
from gcs.telemetry import telemetry_data, get_stream_freshness, reset_telemetry_data
from gcs.command_manager import CommandManager
from tests.test_commands_ack import FakeAckMessage


def test_stream_freshness_isolation():
    reset_telemetry_data()
    now = time.monotonic()

    # Active heartbeat arriving
    telemetry_data['last_heartbeat_monotonic'] = now
    telemetry_data['message_rate_hz'] = 10.0
    telemetry_data['packet_loss_pct'] = 0.0

    # GPS is stale (last updated 15 seconds ago)
    telemetry_data['last_gps_monotonic'] = now - 15.0
    telemetry_data['fix_type'] = 3
    telemetry_data['satellites'] = 10

    # Attitude is stale (last updated 10 seconds ago)
    telemetry_data['last_attitude_monotonic'] = now - 10.0

    freshness = get_stream_freshness(now)

    assert freshness['hb_age'] < 0.1
    assert freshness['link_state'] == 'HEALTHY'

    # Stale GPS must NOT be considered valid even with healthy link
    assert freshness['gps_valid'] is False
    assert freshness['gps_age'] >= 15.0

    # Stale attitude must NOT be valid
    assert freshness['attitude_valid'] is False

    # Now simulate fresh GPS arriving
    telemetry_data['last_gps_monotonic'] = now - 0.2
    telemetry_data['last_gps_raw_monotonic'] = now - 0.2
    freshness2 = get_stream_freshness(now)
    assert freshness2['gps_valid'] is True


def test_in_progress_ack_extends_timeout():
    mgr = CommandManager()
    # 0.4s timeout
    pending = mgr.register(command_id=500, target_system=1, target_component=1, timeout=0.4)

    time.sleep(0.2)
    # IN_PROGRESS at 0.2s resets timeout window
    ack_prog = FakeAckMessage(command=500, result=5, src_sys=1, src_comp=1, progress=30)
    mgr.handle_ack(ack_prog)
    assert pending.state == 'IN_PROGRESS'
    assert pending.progress == 30

    time.sleep(0.2)
    # At 0.4s total, original timeout would have expired, but IN_PROGRESS reset it!
    assert pending.is_active() is True

    # ACCEPTED arrives
    ack_done = FakeAckMessage(command=500, result=0, src_sys=1, src_comp=1, progress=100)
    mgr.handle_ack(ack_done)

    ok, res_str, code = pending.wait()
    assert ok is True
    assert res_str == 'ACCEPTED'
    assert pending.state == 'ACKNOWLEDGED'
