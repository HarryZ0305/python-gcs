"""Navigation and ownership checks for the focused flight workspace."""
import pytest
from PyQt6.QtCore import QSettings, pyqtSignal
from PyQt6.QtWidgets import QApplication, QWidget
from gcs.telemetry import reset_telemetry_data
from gcs.ui.gui import GCSWindow


class MapStub(QWidget):
    # These checks exercise widget ownership, not Chromium's graphics backend.
    goto_requested = pyqtSignal(float, float)
    waypoint_added = pyqtSignal(float, float)
    takeoff_added = pyqtSignal(float, float)
    landing_added = pyqtSignal(float, float)

    def set_waypoints(self, *args): pass
    def update_position(self, *args): pass
    def set_home(self, *args): pass
    def reset_vehicle(self): pass


@pytest.fixture
def window(tmp_path, monkeypatch):
    import gcs.ui.gui as gui
    import gcs.ui.plan_view as planner
    monkeypatch.setattr(gui, 'TTS_AVAILABLE', False)
    monkeypatch.setattr(gui, 'MapView', lambda *args, **kwargs: MapStub())
    monkeypatch.setattr(planner, 'MapView', MapStub)
    app = QApplication.instance() or QApplication([])
    reset_telemetry_data()
    win = GCSWindow(settings=QSettings(str(tmp_path / 'prefs.ini'), QSettings.Format.IniFormat))
    win.timer.stop()
    win.fast_timer.stop()
    win.show()
    app.processEvents()
    yield win
    for dialog in (win.connection_dialog, win.pilot_dialog, win.diagnostics_window):
        dialog.close()
    win.camera_view.shutdown()
    win.hide()
    win.deleteLater()
    app.processEvents()
    reset_telemetry_data()


def test_secondary_tools_do_not_occupy_flight_workspace(window):
    win = window
    assert win.tabs.currentIndex() == 0
    assert win.connection_dialog.isAncestorOf(win.profile_combo)
    assert win.connection_dialog.isAncestorOf(win.conn_input)
    assert win.pilot_dialog.isAncestorOf(win.mode_combo)
    assert win.pilot_dialog.isAncestorOf(win.kb_checkbox)
    assert win.diagnostics_content.isAncestorOf(win.stream_health)
    assert win.diagnostics_content.isAncestorOf(win.console_view)
    assert not win.pip_workspace.pip_frame.isVisible()
    for control in (win.hold_btn, win.rtl_btn, win.land_btn, win.emer_stop_btn):
        assert control.isVisibleTo(win)
        assert not control.isEnabled()  # Layout changes must not bypass link checks.
    win.btn_toggle_drawer.click()
    assert win.tabs.currentWidget() is win.diagnostics_view


def test_second_window_returns_the_same_live_diagnostics(window):
    win = window
    win._detach_diagnostics()
    assert win.diagnostics_content.parentWidget() is win.diagnostics_window
    assert win.diagnostics_window.isVisible()
    win.diagnostics_window.close()
    assert win.diagnostics_content.parentWidget() is win.diagnostics_view
    assert not win.diagnostics_placeholder.isVisible()
    assert win.diagnostics_content.isAncestorOf(win.console_view)


def test_hiding_video_restores_map_as_primary_view(window):
    win = window
    win.video_toggle_btn.setChecked(True)
    assert win.pip_workspace.pip_frame.isVisible()
    win.pip_workspace.swap_views()
    assert not win.pip_workspace.is_map_dominant
    win.video_toggle_btn.setChecked(False)
    assert win.pip_workspace.is_map_dominant
    assert not win.pip_workspace.pip_frame.isVisible()
