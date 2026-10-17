"""Render the real Qt workspaces with labelled, read-only sample telemetry.

This is a layout check, not a flight simulation or SITL validation.
Run with ``python tools/capture_workspace.py --output artifacts/preview``.
"""
import argparse
import math
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# Windows' offscreen Qt plugin has no font database. Use its native renderer
# for visual checks; headless CI can explicitly set QT_QPA_PLATFORM=offscreen.
os.environ.setdefault("QT_QPA_PLATFORM", "windows" if sys.platform == 'win32' else 'offscreen')
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox --disable-gpu")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
from gcs.ui.gui import GCSWindow
from gcs.telemetry import reset_telemetry_data, telemetry_data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="artifacts/preview")
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication(sys.argv)
    win = GCSWindow()
    win.voice_enabled = False
    win.timer.stop()
    win.fast_timer.stop()
    win.resize(1366, 768)
    win.show()
    print('Minimum size:', win.minimumSizeHint().width(), win.minimumSizeHint().height(), flush=True)
    for view in (win.tabs, win.plan_view, win.setup_view, win.analyze_view, win.settings_view):
        print(type(view).__name__, view.minimumSizeHint().width(), view.minimumSizeHint().height(), flush=True)

    def capture():
        win.resize(1366, 768)
        QTest.qWait(300)
        print('Map loaded:', win.map_view._is_loaded, flush=True)
        win.map_view.page().runJavaScript("JSON.stringify({ready:document.readyState, leaflet:typeof L, map:typeof map})", lambda result: print('Map JS:', result, flush=True))
        reset_telemetry_data()
        win.refresh()
        win._fast_instrument_update()
        QTest.qWait(300)
        app.processEvents()
        win.grab().save(str(output / "fly-disconnected.png"))
        print(f"Window: {win.width()} x {win.height()}", flush=True)
        now = time.monotonic()
        telemetry_data.update({
            "last_heartbeat_monotonic": now, "last_gps_monotonic": now,
            "last_position_monotonic": now, "last_gps_raw_monotonic": now,
            "last_attitude_monotonic": now, "last_battery_monotonic": now,
            "last_vfr_monotonic": now, "last_extended_sys_state_monotonic": now,
            "lat": 47.397742, "lon": 8.545594, "alt": 24.6,
            "fix_type": 3, "satellites": 14, "voltage": 15.6,
            "battery": 78, "groundspeed": 4.2, "climb_rate": 0.3,
            "roll": math.radians(-8), "pitch": math.radians(3),
            "yaw": math.radians(85), "mode": "AUTO.LOITER", "armed": True,
            "landed_state": 2, "message_rate_hz": 32.0,
            "has_home": True, "home_lat": 47.3977, "home_lon": 8.5455,
        })
        # No transport is created. All interactive flight controls are disabled.
        win.vehicle = object()
        win.setWindowTitle("READ-ONLY SAMPLE TELEMETRY — layout preview")
        win.refresh()
        win._fast_instrument_update()
        win.tabs.setEnabled(False)
        win.statusBar().showMessage('READ-ONLY SAMPLE TELEMETRY — no transport or flight simulation')
        QTest.qWait(300)
        app.processEvents()
        win.grab().save(str(output / "fly-sample.png"))
        telemetry_data["last_attitude_monotonic"] = now - 20
        telemetry_data["last_battery_monotonic"] = now - 20
        win.refresh()
        win._fast_instrument_update()
        QTest.qWait(300)
        app.processEvents()
        win.grab().save(str(output / "fly-stale-sample.png"))
        win.vehicle = None
        reset_telemetry_data()
        win.refresh()
        win.tabs.setEnabled(True)
        win.plan_view.add_waypoint(47.3980, 8.5460, 20)
        win.plan_view.add_waypoint(47.3990, 8.5475, 25)
        win.tabs.setCurrentIndex(1)
        QTest.qWait(500)
        app.processEvents()
        win.grab().save(str(output / "plan.png"))
        win.tabs.setCurrentIndex(4)
        QTest.qWait(300)
        app.processEvents()
        win.grab().save(str(output / "settings.png"))
        win.camera_view.stop_stream()
        win.hide()
        app.quit()

    QTimer.singleShot(2000, capture)
    app.exec()


if __name__ == "__main__":
    main()
