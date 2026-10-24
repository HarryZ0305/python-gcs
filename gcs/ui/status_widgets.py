"""Compact operator readouts and independently timestamped stream health."""
import math
from PyQt6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout
from gcs.ui.theme import get_theme, FONT_FAMILY_MONO


class TelemetryStrip(QFrame):
    def __init__(self, parent=None, fields=None):
        super().__init__(parent)
        self.setObjectName('TelemetryStrip')
        t = get_theme()
        self.setStyleSheet(f"#TelemetryStrip {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 8px; }}")
        row = QHBoxLayout(self)
        row.setContentsMargins(16, 10, 16, 10)
        self.values = {}
        for key, title in [('alt', 'ALTITUDE · REL HOME'), ('speed', 'GROUND SPEED'),
                           ('climb', 'CLIMB RATE'), ('heading', 'HEADING'), ('home', 'DISTANCE TO HOME')]:
            if fields is not None and key not in fields:
                continue
            column = QVBoxLayout()
            label = QLabel(title)
            label.setStyleSheet(f"color: {t['text_muted']}; font-size: 10px; font-weight: 600;")
            value = QLabel('—')
            value.setStyleSheet(f"font-family: {FONT_FAMILY_MONO}; font-size: 20px; font-weight: 700; color: {t['text']};")
            column.addWidget(label)
            column.addWidget(value)
            row.addLayout(column, 1)
            self.values[key] = value

    def update_values(self, data, fresh, connected, home_distance=None):
        entries = {
            'alt': (connected and fresh['position_valid'], data.get('alt', 0), '.1f', 'm'),
            'speed': (connected and fresh['vfr_valid'], data.get('groundspeed', 0), '.1f', 'm/s'),
            'climb': (connected and fresh['vfr_valid'], data.get('climb_rate', 0), '+.1f', 'm/s'),
            'heading': (connected and fresh['attitude_valid'], math.degrees(data.get('yaw', 0)) % 360, '03.0f', '°'),
            'home': (connected and fresh['position_valid'] and home_distance is not None, home_distance or 0, '.0f', 'm'),
        }
        for key, (valid, number, fmt, unit) in entries.items():
            if key not in self.values:
                continue
            self.values[key].setText(f'{number:{fmt}} {unit}' if valid else '—')
            self.values[key].setToolTip('Current telemetry' if valid else 'No fresh, valid source available')


class StreamHealthPanel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('StreamHealthPanel')
        t = get_theme()
        self.setStyleSheet(f"#StreamHealthPanel {{background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 8px;}}")
        grid = QGridLayout(self)
        grid.setContentsMargins(12, 10, 12, 10)
        heading = QLabel('TELEMETRY HEALTH')
        heading.setStyleSheet(f"color: {t['text_muted']}; font-size: 10px; font-weight: 700;")
        grid.addWidget(heading, 0, 0, 1, 2)
        self.rows = {}
        for row, (key, title) in enumerate([('hb', 'Autopilot'), ('gps', 'Fused position'),
                                           ('gps_raw', 'GNSS receiver'), ('att', 'Attitude'),
                                           ('batt', 'Battery'), ('vfr', 'Speed / climb')], 1):
            grid.addWidget(QLabel(title), row, 0)
            value = QLabel('NOT RECEIVED')
            grid.addWidget(value, row, 1)
            self.rows[key] = value

    def update_health(self, fresh, connected):
        valid_keys = {'hb': fresh['link_state'] in ('HEALTHY', 'DEGRADED'),
                      'gps': fresh['position_valid'], 'gps_raw': fresh['gps_valid'],
                      'att': fresh['attitude_valid'], 'batt': fresh['battery_valid'], 'vfr': fresh['vfr_valid']}
        t = get_theme()
        for key, label in self.rows.items():
            age = fresh[key + '_age']
            received = connected and age < 999
            valid = connected and valid_keys[key]
            label.setText(f"{'CURRENT' if valid else 'STALE / INVALID'} · {age:.1f}s" if received else 'NOT RECEIVED')
            label.setStyleSheet(f"color: {t['success'] if valid else t['text_muted'] if not received else t['warning']}; font-size: 10px;")
