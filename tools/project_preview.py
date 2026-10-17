"""Capture a light-theme project showcase using read-only sample data.

The local-coordinate mission illustration is a presentation fixture, not a basemap,
SITL run, video feed, or screenshot of an actual flight. No transport is opened.
"""
import argparse
import math
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('QT_QPA_PLATFORM', 'windows' if sys.platform == 'win32' else 'offscreen')
os.environ.setdefault('QTWEBENGINE_CHROMIUM_FLAGS', '--no-sandbox --disable-gpu')
os.environ.setdefault('QTWEBENGINE_DISABLE_SANDBOX', '1')

from PyQt6.QtCore import QPointF, QRectF, QSettings, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QWidget
from gcs.telemetry import reset_telemetry_data, telemetry_data
from gcs.ui.gui import GCSWindow
from gcs.ui.theme import get_pill_style
from gcs.plan_format import calculate_mission_stats


HOME = (47.3977, 8.5455)
ROUTE = [(-200, -80), (-200, 160), (-70, 160), (-70, -100),
         (60, -100), (60, 160), (190, 160), (190, -80)]


def coordinate(east, north, altitude=32):
    return [HOME[0] + north / 111320, HOME[1] + east / (111320 * math.cos(math.radians(HOME[0]))), altitude]


class MissionIllustration(QWidget):
    """A labelled, deterministic local-coordinate illustration for the showcase."""
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor('#fafbfc'))
        p.setPen(QPen(QColor('#e9edf1'), 1))
        for x in range(0, self.width(), 48):
            p.drawLine(x, 0, x, self.height())
        for y in range(0, self.height(), 48):
            p.drawLine(0, y, self.width(), y)

        def text(rect, message, size=11, color='#6b7280', bold=False, align=Qt.AlignmentFlag.AlignLeft):
            p.setPen(QColor(color))
            p.setFont(QFont('Segoe UI', size, QFont.Weight.DemiBold if bold else QFont.Weight.Normal))
            p.drawText(rect, align | Qt.AlignmentFlag.AlignVCenter, message)

        text(QRectF(30, 22, 400, 22), 'MISSION OVERVIEW', 10, '#6b7280', True)
        text(QRectF(30, 46, 600, 30), 'A clear view of every flight.', 19, '#111827', True)
        text(QRectF(30, 82, 650, 22), 'Sample survey route  /  Local coordinates  /  Altitudes relative to home', 10)

        scale = min((self.width() - 300) / 640, (self.height() - 200) / 460)
        cx, cy = self.width() * .48, self.height() * .57

        def point(pair):
            return QPointF(cx + pair[0] * scale, cy - pair[1] * scale)

        area = QRectF(point((-235, 185)), point((225, -125))).normalized()
        p.setPen(QPen(QColor('#dbe4ef'), 1, Qt.PenStyle.DashLine))
        p.setBrush(QColor('#f0f4fa'))
        p.drawRoundedRect(area, 16, 16)

        home = (-270, -180)
        route = [home, *ROUTE]
        path = QPainterPath(point(route[0]))
        for position in route[1:]:
            path.lineTo(point(position))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor('#8c9bb0'), 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawPath(path)
        p.setPen(QPen(QColor('#b0bac8'), 1.5, Qt.PenStyle.DashLine))
        p.drawLine(point(ROUTE[-1]), point(home))
        p.setPen(QPen(QColor('#2563eb'), 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(point(home), point(ROUTE[0]))
        p.drawLine(point(ROUTE[0]), point((-200, 50)))

        for number, position in enumerate(ROUTE, 1):
            center = point(position)
            p.setPen(QPen(QColor('#2563eb') if number <= 2 else QColor('#9aa8bb'), 2))
            p.setBrush(QColor('#ffffff'))
            p.drawEllipse(center, 13, 13)
            text(QRectF(center.x() - 13, center.y() - 13, 26, 26), str(number), 9,
                 '#2563eb' if number <= 2 else '#53647b', True, Qt.AlignmentFlag.AlignCenter)

        h = point(home)
        p.setPen(QPen(QColor('#16a34a'), 2))
        p.setBrush(QColor('#ffffff'))
        p.drawEllipse(h, 14, 14)
        text(QRectF(h.x() - 14, h.y() - 14, 28, 28), 'H', 10, '#15803d', True, Qt.AlignmentFlag.AlignCenter)
        text(QRectF(h.x() - 42, h.y() + 22, 84, 22), 'HOME', 9, '#6b7280', True, Qt.AlignmentFlag.AlignCenter)

        vehicle = point((-200, 50))
        p.setPen(QPen(QColor('#ffffff'), 3))
        p.setBrush(QColor('#2563eb'))
        p.drawPolygon(QPolygonF([vehicle + QPointF(0, -19), vehicle + QPointF(-13, 14),
                                vehicle + QPointF(0, 8), vehicle + QPointF(13, 14)]))
        p.setPen(QPen(QColor('#dfe3e8'), 1))
        p.setBrush(QColor('#ffffff'))
        label = QRectF(vehicle.x() + 24, vehicle.y() - 18, 150, 36)
        p.drawRoundedRect(label, 8, 8)
        text(label.adjusted(12, 0, 0, 0), 'SAMPLE VEHICLE', 9, '#2563eb', True)

        stats = calculate_mission_stats([coordinate(*pair) for pair in ROUTE], coordinate(*home), coordinate(*home, altitude=0))
        box = QRectF(self.width() - 244, 28, 216, 116)
        p.setPen(QPen(QColor('#dfe3e8'), 1))
        p.setBrush(QColor('#ffffff'))
        p.drawRoundedRect(box, 12, 12)
        text(box.adjusted(18, 6, -10, -78), 'SAMPLE MISSION', 9, '#6b7280', True)
        text(QRectF(box.x() + 18, box.y() + 38, 185, 28), f"{stats['total_distance_m'] / 1000:.2f} km   /   8 waypoints", 13, '#111827', True)
        text(QRectF(box.x() + 18, box.y() + 76, 185, 22), '32 m relative altitude', 10)

        text(QRectF(30, self.height() - 48, 700, 25), 'READ-ONLY ILLUSTRATION  ·  Planned route  ·  Active leg in blue', 9)
        p.setPen(QPen(QColor('#6b7280'), 2))
        x, y, length = self.width() - 155, self.height() - 36, 100 * scale
        p.drawLine(QPointF(x - length, y), QPointF(x, y))
        text(QRectF(x - length, y - 28, length, 20), '100 m', 9, align=Qt.AlignmentFlag.AlignCenter)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='artifacts/project-overview.png')
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    app = QApplication(sys.argv)
    # Private preferences keep the showcase from changing operator settings.
    settings = QSettings(str(output.parent / 'preview-preferences.ini'), QSettings.Format.IniFormat)
    settings.setValue('appearance/dark', False)
    win = GCSWindow(settings=settings)
    win.voice_enabled = False
    win.timer.stop()
    win.fast_timer.stop()
    win.setWindowTitle('PythonGCS — Read-only project preview')
    win.resize(1920, 1080)
    original_map = win.pip_workspace.map_widget
    win.pip_workspace.dominant_layout.removeWidget(original_map)
    original_map.hide()
    win.pip_workspace.dominant_layout.addWidget(MissionIllustration())
    win.pip_workspace.pip_frame.hide()
    win.show()

    def capture():
        win.resize(1920, 1080)
        reset_telemetry_data()
        now = time.monotonic()
        position = coordinate(-200, 50)
        telemetry_data.update({
            'last_heartbeat_monotonic': now, 'last_gps_monotonic': now,
            'last_gps_raw_monotonic': now, 'last_attitude_monotonic': now,
            'last_battery_monotonic': now, 'last_vfr_monotonic': now,
            'last_extended_sys_state_monotonic': now,
            'lat': position[0], 'lon': position[1], 'alt': 32.0,
            'groundspeed': 5.0, 'climb_rate': .0,
            'roll': math.radians(-3), 'pitch': math.radians(1), 'yaw': 0.0,
            'battery': 84, 'voltage': 16.0, 'fix_type': 3, 'satellites': 18,
            'message_rate_hz': 28.0, 'armed': True, 'landed_state': 2,
            'mode': 'AUTO.MISSION', 'autopilot_version': 'SAMPLE',
            'has_home': True, 'home_lat': HOME[0], 'home_lon': HOME[1],
        })
        win.vehicle = object()  # Display fixture only; never creates a transport.
        win.was_armed = True
        win.armed_start_time = now - 125
        win.refresh()
        win._fast_instrument_update()
        win.conn_btn.setText('READ ONLY')
        win.conn_status.setText('PROJECT PREVIEW')
        win.ribbon_arm_pill.setText('SAMPLE: AIRBORNE')
        win.alert_banner.setText('PROJECT PREVIEW  /  Sample mission and telemetry  /  No aircraft connected')
        win.alert_banner.setStyleSheet(get_pill_style('primary'))
        win.status_label.setText('Sample mission · read-only presentation')
        win.statusBar().showMessage('READ-ONLY PROJECT PREVIEW · Local-coordinate mission illustration · Sample telemetry · No vehicle transport')
        for control in (win.arm_btn, win.takeoff_btn, win.hold_btn, win.rtl_btn, win.land_btn,
                        win.mode_btn, win.start_btn, win.emer_stop_btn, win.kb_checkbox,
                        win.conn_btn, win.profile_combo, win.conn_input):
            control.setEnabled(False)
        QTest.qWait(500)
        win.grab().save(str(output))
        print(f'Saved {output} ({win.width()} × {win.height()} logical pixels)', flush=True)
        win.camera_view.shutdown()
        win.hide()
        app.quit()

    QTimer.singleShot(1500, capture)
    app.exec()


if __name__ == '__main__':
    main()
