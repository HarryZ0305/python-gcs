import sys
import time
import pytest
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QObject
from gcs.ui.gui import WorkerBridge, GCSWindow
from gcs.ui.preflight_dialog import PreflightChecklistDialog
from gcs.telemetry import telemetry_data, battery_config


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def test_worker_bridge_signals(qapp):
    bridge = WorkerBridge()
    received_status = []
    received_speech = []
    received_cmd = []
    received_mission = []

    bridge.status_updated.connect(lambda msg: received_status.append(msg))
    bridge.voice_speech.connect(lambda msg: received_speech.append(msg))
    bridge.command_completed.connect(lambda sid, act, ok, msg: received_cmd.append((sid, act, ok, msg)))
    bridge.mission_uploaded.connect(lambda sid, ok, msg: received_mission.append((sid, ok, msg)))

    bridge.status_updated.emit("Status test")
    bridge.voice_speech.emit("Speech test")
    bridge.command_completed.emit("sess_123", "ARM", True, "Arm OK")
    bridge.mission_uploaded.emit("sess_123", True, "Upload OK")

    assert received_status == ["Status test"]
    assert received_speech == ["Speech test"]
    assert received_cmd == [("sess_123", "ARM", True, "Arm OK")]
    assert received_mission == [("sess_123", True, "Upload OK")]


def test_session_isolation_discards_obsolete_worker_results(qapp):
    win = GCSWindow()
    win._telemetry_session_id = "session_active_001"
    win.set_status("Initial status")

    # Result arrives for an obsolete session
    win._on_worker_command_completed("session_obsolete_999", "DISARM", True, "Disarmed late")
    # Status should remain unchanged because obsolete session was rejected
    assert win.status_label.text() == "Initial status"

    # Result arrives for the current active session
    win._on_worker_command_completed("session_active_001", "DISARM", True, "Disarmed successfully")
    assert "Disarmed successfully" in win.status_label.text()


def test_mission_upload_verification_controls_start_mission(qapp, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
    win = GCSWindow()
    win._telemetry_session_id = "session_active_002"
    win.start_btn.setEnabled(False)

    # Failed upload verification: start button remains disabled
    win._on_worker_mission_uploaded("session_active_002", False, "Readback mismatch")
    assert win.start_btn.isEnabled() is False

    # Successful upload verification: start button becomes enabled
    win._on_worker_mission_uploaded("session_active_002", True, "Verified 3 items")
    assert win.start_btn.isEnabled() is True


def test_preflight_unknown_prearm_readiness(qapp):
    telemetry_data.clear()
    telemetry_data['mode'] = 'HOLD'
    telemetry_data['last_heartbeat_time'] = time.time()
    telemetry_data['last_heartbeat_monotonic'] = time.monotonic()
    telemetry_data['system_status'] = 0  # MAV_STATE_UNINIT

    dlg = PreflightChecklistDialog()
    dlg.evaluate_checks()
    fcu_text = dlg.check_rows['fcu'].text()
    assert 'UNKNOWN' in fcu_text

    # When confirmed STANDBY, passes
    telemetry_data['system_status'] = 3  # MAV_STATE_STANDBY
    telemetry_data['prearm_fail'] = ''
    dlg.evaluate_checks()
    assert 'PASS' in dlg.check_rows['fcu'].text()


def test_preflight_battery_cell_config(qapp):
    dlg = PreflightChecklistDialog()
    # Change to 6S (index 5)
    dlg.cell_combo.setCurrentIndex(5)
    assert battery_config['cells'] == 6
    # Change to 3S (index 2)
    dlg.cell_combo.setCurrentIndex(2)
    assert battery_config['cells'] == 3
