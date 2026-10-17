"""Regression coverage for real operator hazards found in the desktop audit."""
import copy
import json
import threading
import time
from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import QSettings, pyqtSignal
from PyQt6.QtWidgets import QApplication, QWidget
from gcs import telemetry
from gcs.flight_state import flight_status
from gcs.command_manager import CommandManager
from gcs.plan_format import import_plan_file
from gcs.ui.plan_view import PlanView
from gcs.ui.settings_view import SettingsView


@pytest.fixture(autouse=True)
def clean_telemetry():
    old_config = copy.deepcopy(telemetry.battery_config)
    telemetry.reset_telemetry_data()
    yield
    telemetry.reset_telemetry_data()
    telemetry.battery_config.update(old_config)


@pytest.fixture(scope='module')
def qapp():
    return QApplication.instance() or QApplication([])


def fresh_data(now=100):
    data = copy.deepcopy(telemetry.telemetry_data)
    data.update(last_heartbeat_monotonic=now, last_gps_monotonic=now,
                last_gps_raw_monotonic=now, last_attitude_monotonic=now,
                last_battery_monotonic=now, last_vfr_monotonic=now,
                last_extended_sys_state_monotonic=now,
                message_rate_hz=20, fix_type=3, satellites=12,
                lat=47.4, lon=8.5, voltage=16.0, battery=90,
                armed=True, landed_state=2, has_home=True)
    return data


@pytest.mark.parametrize('heartbeat', [0, 95])
def test_lost_link_never_reenables_any_action(heartbeat):
    data = fresh_data()
    data['last_heartbeat_monotonic'] = heartbeat
    state = flight_status(data, connected=True, mission_verified=True, now=100)
    assert not any(action.enabled for action in state['actions'].values())
    assert state['alerts'][0].severity == 'danger'


def test_hold_and_land_available_when_navigation_stops():
    data = fresh_data()
    data['last_gps_monotonic'] = 80
    state = flight_status(data, True, True, 100)
    assert state['actions']['hold'].enabled
    assert state['actions']['land'].enabled
    for key in ('rtl', 'start', 'keyboard', 'takeoff'):
        assert not state['actions'][key].enabled


def test_grounded_disarm_requires_fresh_landed_state():
    data = fresh_data()
    data.update(landed_state=1, last_extended_sys_state_monotonic=80)
    assert not flight_status(data, True, now=100)['actions']['arm'].enabled
    data['last_extended_sys_state_monotonic'] = 100
    assert flight_status(data, True, now=100)['actions']['arm'].enabled


def test_critical_voltage_is_not_hidden_by_high_percentage():
    telemetry.battery_config['cells'] = 4
    data = fresh_data()
    data.update(voltage=12, battery=90, landed_state=1)
    state = flight_status(data, True, now=100)
    assert state['alerts'][0].title == 'Critical battery'
    assert not state['actions']['takeoff'].enabled


def test_gps_receiver_does_not_refresh_frozen_fused_position():
    telemetry.telemetry_data.update(fresh_data(time.monotonic()))
    telemetry.telemetry_data['last_gps_monotonic'] = time.monotonic() - 20
    msg = MagicMock()
    msg.get_type.return_value = 'GPS_RAW_INT'
    msg.get_srcSystem.return_value = 1
    msg.get_srcComponent.return_value = 1
    msg.get_seq.return_value = 1
    msg.satellites_visible, msg.fix_type, msg.eph = 12, 3, 80
    telemetry.handle_mavlink_message(msg)
    assert not telemetry.get_stream_freshness()['gps_valid']
    assert telemetry.get_stream_freshness()['gps_raw_age'] < 1


def test_reset_discards_previous_vehicle_everywhere():
    telemetry.telemetry_data.update(lat=47.4, roll=1, battery_cells=[4.0],
                                    sensors_health=999, autopilot_version='old', sysid=9)
    telemetry.reset_telemetry_data()
    for key in ('lat', 'roll', 'sensors_health'):
        assert telemetry.telemetry_data[key] == 0
    assert telemetry.telemetry_data['battery_cells'] == []
    assert telemetry.telemetry_data['sysid'] == 1
    assert telemetry.telemetry_data['autopilot_version'] == 'Unknown'


def test_command_cancel_remains_cancelled():
    manager = CommandManager()
    pending = manager.register(400)
    manager.clear()
    assert pending.wait() == (False, 'CANCELLED', None)
    assert pending.state == 'CANCELLED'


@pytest.mark.parametrize('changed', ['frame', 'param2', 'param4', 'autocontinue', 'lat'])
def test_mission_verification_checks_semantics(changed):
    from gcs.commands import verify_mission_readback
    up = {'command': 16, 'frame': 6, 'autocontinue': 1, 'param1': 0,
          'param2': 2, 'param3': 0, 'param4': float('nan'), 'x': 474000000, 'y': 85000000, 'z': 20}
    down = {**up, 'lat': 47.4, 'lon': 8.5, 'alt': 20}
    assert verify_mission_readback([up], [down])[0]
    down[changed] = {'frame': 0, 'param2': 10, 'param4': 90, 'autocontinue': 0, 'lat': 47.40001}[changed]
    assert not verify_mission_readback([up], [down])[0]


@pytest.mark.parametrize('takeoff,landing', [([float('nan'), 8.5, 20], None),
                                          ([95, 8.5, 20], None),
                                          ([47.4], None), (None, [47.4, 8.5, 30])])
def test_invalid_takeoff_or_landing_never_reaches_transport(takeoff, landing):
    from gcs.commands import upload_mission
    vehicle = MagicMock()
    ok, reason = upload_mission(vehicle, [[47.4, 8.5, 20]], takeoff, landing)
    assert not ok and 'Validation error' in reason
    vehicle.mav.mission_count_send.assert_not_called()


def test_late_packet_from_previous_session_is_discarded():
    previous = telemetry.start_telemetry_session()
    current = telemetry.start_telemetry_session()
    msg = MagicMock()
    msg.get_type.return_value = 'GLOBAL_POSITION_INT'
    msg.get_srcSystem.return_value = 1
    msg.get_srcComponent.return_value = 1
    msg.lat, msg.lon, msg.relative_alt, msg.alt = 474000000, 85000000, 20000, 500000
    assert telemetry.handle_mavlink_message(msg, session_id=previous.session_id) is False
    assert telemetry.telemetry_data['lat'] == 0
    assert telemetry.is_session_active(current.session_id)


def test_real_mavlink_loopback_discovers_nondefault_vehicle():
    """Exercise encoded UDP packets and the actual connection/receive path."""
    import socket
    from pymavlink import mavutil
    from gcs.connection import connect
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    stop = threading.Event()
    sender = mavutil.mavlink_connection(f'udpout:127.0.0.1:{port}', source_system=42, source_component=1)

    def transmit():
        while not stop.is_set():
            sender.mav.heartbeat_send(2, 12, 0, 0x04030000, 3)
            sender.mav.global_position_int_send(0, 474000000, 85000000, 500000, 20000, 0, 0, 0, 0)
            sender.mav.gps_raw_int_send(0, 3, 474000000, 85000000, 500000, 80, 80, 0, 0, 12)
            sender.mav.attitude_send(0, 0.1, 0.2, 0.3, 0, 0, 0)
            stop.wait(.05)

    writer = threading.Thread(target=transmit, daemon=True)
    reader, vehicle = None, None
    writer.start()
    try:
        vehicle = connect(f'udpin:127.0.0.1:{port}', timeout=2)
        assert vehicle is not None and vehicle.target_system == 42
        session = telemetry.start_telemetry_session()
        reader = threading.Thread(target=telemetry.read_telemetry, args=(vehicle, session.session_id), daemon=True)
        reader.start()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            data = telemetry.get_telemetry_snapshot()
            if telemetry.get_stream_freshness(data=data)['gps_valid'] and data['roll'] > 0:
                break
            time.sleep(.01)
        assert data['sysid'] == 42
        assert data['lat'] == pytest.approx(47.4)
        assert data['roll'] == pytest.approx(.1)
        assert telemetry.get_stream_freshness(data=data)['gps_valid']
    finally:
        stop.set()
        telemetry.cancel_current_session()
        if reader:
            reader.join(1)
        if vehicle:
            vehicle.close()
        writer.join(1)
        sender.close()


@pytest.mark.parametrize('mutation', ['frame', 'complex', 'nan', 'order', 'yaw', 'fence'])
def test_import_rejects_unsupported_semantics_atomically(tmp_path, mutation):
    item = {'type': 'SimpleItem', 'command': 16, 'frame': 3,
            'params': [0, 2, 0, None, 47.4, 8.5, 20]}
    data = {'fileType': 'Plan', 'version': 1, 'mission': {'version': 2, 'items': [item]}}
    if mutation == 'frame': item['frame'] = 0
    if mutation == 'complex': item['type'] = 'ComplexItem'
    if mutation == 'nan': item['params'][4] = float('nan')
    if mutation == 'order': data['mission']['items'].append({**item, 'command': 22})
    if mutation == 'yaw': item['params'][3] = 90
    if mutation == 'fence': data['geoFence'] = {'polygons': [{}]}
    filename = tmp_path / 'unsupported.plan'
    filename.write_text(json.dumps(data))
    ok, wps, takeoff, landing, altitude, msg = import_plan_file(str(filename))
    assert not ok and not wps and takeoff is None and landing is None
    assert 'cancelled' in msg.lower()


class MapStub(QWidget):
    goto_requested = pyqtSignal(float, float)
    waypoint_added = pyqtSignal(float, float)
    takeoff_added = pyqtSignal(float, float)
    landing_added = pyqtSignal(float, float)

    def set_waypoints(self, *args): pass
    def update_position(self, *args): pass
    def set_home(self, *args): pass
    def reset_vehicle(self): pass


def test_edit_during_upload_and_old_session_cannot_verify_plan(qapp):
    vehicle = object()
    view = PlanView(map_view=MapStub())
    view.set_vehicle(vehicle)
    view.add_waypoint(47.4, 8.5, 20)
    original = view._signature()
    generation = view._vehicle_generation
    view.add_waypoint(47.41, 8.51, 20)
    view._on_transfer_finished(generation, vehicle, original, True, None, 'OK')
    assert not view.is_verified_for(vehicle)
    view.on_upload_completed(True, 'OK')
    assert view.is_verified_for(vehicle)
    view.set_vehicle(None)
    view._on_transfer_finished(generation, vehicle, view._signature(), True, None, 'late OK')
    assert not view.is_verified_for(vehicle)
    assert view.sync_state == 'DRAFT'


def test_download_applies_only_on_qt_thread(qapp, monkeypatch):
    import gcs.ui.plan_view as module
    vehicle = object()
    view = PlanView(map_view=MapStub())
    view.set_vehicle(vehicle)
    view.set_link_available(True)
    item = {'command': 16, 'frame': 6, 'lat': 47.4, 'lon': 8.5,
            'alt': 20, 'param1': 0, 'param2': 2, 'param3': 0, 'param4': float('nan')}
    monkeypatch.setattr(module, 'download_mission', lambda vehicle: (True, [item], 'downloaded'))
    main_thread = threading.get_ident()
    calls = []
    view.draft_changed.connect(lambda: calls.append(threading.get_ident()))
    view.download_from_vehicle()
    deadline = time.monotonic() + 2
    while view._busy and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(.01)
    assert view.is_verified_for(vehicle)
    assert view.waypoints == [[47.4, 8.5, 20]]
    assert calls and all(thread == main_thread for thread in calls)


def test_settings_persist_and_invalid_limits_do_not_apply(qapp, tmp_path):
    settings = QSettings(str(tmp_path / 'prefs.ini'), QSettings.Format.IniFormat)
    view = SettingsView(settings=settings)
    view.warn_spin.setValue(3.6)
    view.crit_spin.setValue(3.2)
    view.warn_pct_spin.setValue(30)
    view.crit_pct_spin.setValue(12)
    view._save_battery_limits()
    assert telemetry.battery_config['warn_volt_per_cell'] == 3.6
    restored = SettingsView(settings=settings)
    assert restored.warn_spin.value() == 3.6
    assert restored.crit_pct_spin.value() == 12
    restored.crit_pct_spin.setValue(40)
    restored._save_battery_limits()
    assert telemetry.battery_config['crit_pct'] == 12
    assert 'Not saved' in restored.battery_status.text()


def test_analytics_buffer_rollover_preserves_all_series(qapp, monkeypatch):
    from gcs.ui.analyze_view import AnalyzeView
    view = AnalyzeView()
    monkeypatch.setattr(view, '_refresh_plot_curves', lambda: None)
    for i in range(1205):
        view.update_telemetry(i, 20, 4, .2, 16, 0)
    assert len(view.timestamps) == 1200
    assert all(len(values) == 1200 for values in view.series.values())


def test_camera_switch_discards_old_source_frames_without_blocking(qapp):
    from PyQt6.QtGui import QImage
    from gcs.ui.camera_view import CameraView
    view = CameraView()
    for _ in range(3):
        view.set_stream_source('test')
    previous_generation = view._source_generation
    started = time.monotonic()
    view.set_stream_source('')
    assert time.monotonic() - started < .2
    view._accept_frame(previous_generation, QImage(10, 10, QImage.Format.Format_RGB888))
    assert view.current_frame is None
    assert view.stream_state == 'DISCONNECTED'
    view.shutdown()
    assert all(not worker.isRunning() for worker in view._workers)
    qapp.processEvents()


def test_invalid_sensor_numbers_do_not_crash_pfd_painting(qapp):
    from PyQt6.QtGui import QImage
    from gcs.ui.flight_instruments import PrimaryFlightDisplay
    view = PrimaryFlightDisplay()
    view.set_telemetry(float('nan'), 0, float('inf'), float('nan'), float('inf'))
    assert view.is_stale and not view.position_valid and not view.speed_valid
    image = QImage(320, 240, QImage.Format.Format_ARGB32)
    view.render(image)


def test_gui_lost_link_and_draft_edit_inhibit_actions(qapp, monkeypatch):
    import gcs.ui.gui as module
    import gcs.ui.plan_view as planner
    monkeypatch.setattr(module, 'MapView', lambda *args, **kwargs: MapStub())
    monkeypatch.setattr(planner, 'MapView', MapStub)
    win = module.GCSWindow()
    win.timer.stop()
    win.fast_timer.stop()
    now = time.monotonic()
    telemetry.telemetry_data.update(fresh_data(now))
    win.vehicle = object()
    win.plan_view.set_vehicle(win.vehicle)
    win.plan_view.add_waypoint(47.4, 8.5, 20)
    win.plan_view.on_upload_completed(True, 'OK')
    win.refresh()
    assert win.start_btn.isEnabled()
    win.plan_view.add_waypoint(47.41, 8.51, 20)
    assert not win.start_btn.isEnabled()
    telemetry.telemetry_data['last_heartbeat_monotonic'] = now - 10
    win.refresh()
    for widget in (win.takeoff_btn, win.rtl_btn, win.land_btn, win.hold_btn, win.emer_stop_btn):
        assert not widget.isEnabled()
    win.vehicle = None
    win.refresh()
    assert win.ribbon_mode_pill.text() == 'MODE: UNCONFIRMED'
    assert win.telemetry_strip.values['alt'].text() == '—'
