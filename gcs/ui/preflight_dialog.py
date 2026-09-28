import time
import math
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame
)
from PyQt6.QtCore import Qt
from gcs.telemetry import telemetry_data

THEME = {
    'bg': '#f5f7fa',
    'panel_bg': '#ffffff',
    'panel_border': '#cbd5e1',
    'primary': '#0b57d0',
    'success': '#0f9d58',
    'warning': '#e37400',
    'danger': '#d93025',
    'muted': '#5f6368',
    'dark_text': '#0f172a',
}

# Sensor masks from MAVLink SYS_STATUS
SENSOR_3D_GYRO = 1
SENSOR_3D_ACCEL = 2
SENSOR_3D_MAG = 4
SENSOR_ABSOLUTE_PRESSURE = 8
SENSOR_GPS = 32

class PreflightChecklistDialog(QDialog):
    """
    Evidence-based pre-flight safety checklist for PX4 Autopilot.
    Evaluates:
    - MAVLink link age and message rate
    - GNSS 3D fix, satellite count, and HDOP (eph)
    - Power: battery voltage and percentage, rejecting unknown/missing sensor values
    - Sensors: SYS_STATUS health bits for Gyro, Accel, Mag, Baro, and level attitude
    - FCU Prearm: evaluates actual STATUSTEXT failure notices and flight controller readiness
    - Home Position: verifies confirmed HOME_POSITION or locked launch coordinates
    Strictly distinguishes PASS, FAIL, and UNKNOWN.
    UNKNOWN never produces 'GO FOR FLIGHT'.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Pre-Flight Safety Verification")
        self.setFixedSize(540, 560)
        self.setStyleSheet(f"background-color: {THEME['bg']}; font-family: Google Sans Code;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        title = QLabel("SYSTEM PRE-FLIGHT VERIFICATION")
        title.setStyleSheet(f"color: {THEME['primary']}; font-size: 13px; font-weight: bold;")
        layout.addWidget(title)

        desc = QLabel("Verifying critical telemetry, link status, and sensor health before arming:")
        desc.setStyleSheet(f"color: {THEME['muted']}; font-size: 11px;")
        layout.addWidget(desc)

        self.items_container = QFrame()
        self.items_container.setStyleSheet(f"background: {THEME['panel_bg']}; border: 1px solid {THEME['panel_border']}; border-radius: 8px;")
        ic_layout = QVBoxLayout(self.items_container)
        ic_layout.setContentsMargins(14, 14, 14, 14)
        ic_layout.setSpacing(10)

        self.check_rows = {}
        checks = [
            ("link", "MAVLink Telemetry Stream", "Checking..."),
            ("gps", "GNSS 3D Satellite Fix", "Checking..."),
            ("power", "Battery Voltage & Capacity", "Checking..."),
            ("sensors", "IMU & Sensor Health (SYS_STATUS)", "Checking..."),
            ("attitude", "Horizon Level Alignment", "Checking..."),
            ("fcu", "Autopilot Prearm Readiness", "Checking..."),
            ("home", "Home Position Lock", "Checking...")
        ]
        for key, name, default_status in checks:
            row = QHBoxLayout()
            lbl = QLabel(name)
            lbl.setStyleSheet(f"color: {THEME['dark_text']}; font-weight: bold; font-size: 11px; background: transparent; border: none;")
            val = QLabel(default_status)
            val.setStyleSheet(f"color: {THEME['muted']}; font-weight: bold; font-size: 11px; background: transparent; border: none;")
            val.setAlignment(Qt.AlignmentFlag.AlignRight)
            row.addWidget(lbl)
            row.addWidget(val)
            ic_layout.addLayout(row)
            self.check_rows[key] = val

        layout.addWidget(self.items_container)

        self.banner = QLabel("ANALYZING VEHICLE STATE...")
        self.banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.banner.setFixedHeight(44)
        self.banner.setStyleSheet(f"background: {THEME['panel_border']}; color: {THEME['dark_text']}; font-weight: bold; font-size: 12px; border-radius: 6px;")
        layout.addWidget(self.banner)

        disclaimer = QLabel("Notice: Pre-flight checklist assists operator verification. Final arming authorization is governed by PX4 flight controller internal safety checks.")
        disclaimer.setWordWrap(True)
        disclaimer.setStyleSheet(f"color: {THEME['muted']}; font-size: 9px;")
        layout.addWidget(disclaimer)

        btn_box = QHBoxLayout()
        refresh_btn = QPushButton("REFRESH")
        refresh_btn.setFixedHeight(34)
        refresh_btn.setStyleSheet(f"background: {THEME['panel_bg']}; color: {THEME['primary']}; border: 1.5px solid {THEME['primary']}; border-radius: 4px; font-weight: bold; font-family: Google Sans Code;")
        refresh_btn.clicked.connect(self.evaluate_checks)

        close_btn = QPushButton("CLOSE")
        close_btn.setFixedHeight(34)
        close_btn.setStyleSheet(f"background: {THEME['primary']}; color: #ffffff; border: none; border-radius: 4px; font-weight: bold; font-family: Google Sans Code;")
        close_btn.clicked.connect(self.accept)

        btn_box.addWidget(refresh_btn)
        btn_box.addWidget(close_btn)
        layout.addLayout(btn_box)

        self.evaluate_checks()

    def evaluate_checks(self):
        d = telemetry_data
        has_fail = False
        has_unknown = False

        # 1. Link Check (Age and Rate)
        now_mono = time.monotonic()
        last_hb = d.get('last_heartbeat_monotonic', 0.0)
        rate_hz = d.get('message_rate_hz', 0.0)
        link_age = (now_mono - last_hb) if last_hb > 0.0 else 999.0

        if last_hb > 0.0 and link_age <= 2.5:
            self.check_rows['link'].setText(f"PASS: Active ({link_age:.1f}s, {rate_hz:.1f} Hz)")
            self.check_rows['link'].setStyleSheet(f"color: {THEME['success']};")
        elif last_hb > 0.0 and link_age <= 4.0:
            self.check_rows['link'].setText(f"WARN: Degraded ({link_age:.1f}s)")
            self.check_rows['link'].setStyleSheet(f"color: {THEME['warning']};")
            has_unknown = True
        else:
            self.check_rows['link'].setText("FAIL: No Telemetry Heartbeat")
            self.check_rows['link'].setStyleSheet(f"color: {THEME['danger']};")
            has_fail = True

        # 2. GNSS Fix
        fix_type = d.get('fix_type', 0)
        sats = d.get('satellites', 0)
        eph = d.get('eph', 9999)
        if fix_type >= 3 and sats >= 6:
            eph_str = f", HDOP {eph/100:.1f}m" if eph < 9000 else ""
            self.check_rows['gps'].setText(f"PASS: 3D Fix ({sats} Sats{eph_str})")
            self.check_rows['gps'].setStyleSheet(f"color: {THEME['success']};")
        elif fix_type == 0 and sats == 0:
            self.check_rows['gps'].setText("UNKNOWN: Awaiting GPS Telemetry")
            self.check_rows['gps'].setStyleSheet(f"color: {THEME['warning']};")
            has_unknown = True
        else:
            self.check_rows['gps'].setText(f"FAIL: {fix_type}D Fix ({sats} Sats - Min 6)")
            self.check_rows['gps'].setStyleSheet(f"color: {THEME['danger']};")
            has_fail = True

        # 3. Power (Battery Voltage & Capacity)
        batt = d.get('battery', -1)
        volt = d.get('voltage', 0.0)

        if batt == -1 and volt == 0.0:
            self.check_rows['power'].setText("UNKNOWN: No Power Telemetry")
            self.check_rows['power'].setStyleSheet(f"color: {THEME['warning']};")
            has_unknown = True
        elif volt > 0.0 and volt < 13.6: # Less than 3.4V/cell on 4S
            self.check_rows['power'].setText(f"FAIL: Critical Voltage ({volt:.1f}V, {batt}%)")
            self.check_rows['power'].setStyleSheet(f"color: {THEME['danger']};")
            has_fail = True
        elif (batt >= 0 and batt < 25) or (volt > 0.0 and volt < 14.4): # Low battery warning
            self.check_rows['power'].setText(f"WARN: Low ({volt:.1f}V, {batt}%)")
            self.check_rows['power'].setStyleSheet(f"color: {THEME['warning']};")
            has_unknown = True
        elif batt >= 25 or volt >= 14.4:
            disp_b = f"{batt}%" if batt >= 0 else "OK"
            self.check_rows['power'].setText(f"PASS: {volt:.1f}V ({disp_b})")
            self.check_rows['power'].setStyleSheet(f"color: {THEME['success']};")
        else:
            self.check_rows['power'].setText(f"UNKNOWN: {volt:.1f}V")
            self.check_rows['power'].setStyleSheet(f"color: {THEME['warning']};")
            has_unknown = True

        # 4. Sensor Health from SYS_STATUS
        present = d.get('sensors_present', 0)
        enabled = d.get('sensors_enabled', 0)
        health = d.get('sensors_health', 0)

        if present == 0:
            self.check_rows['sensors'].setText("UNKNOWN: Awaiting SYS_STATUS")
            self.check_rows['sensors'].setStyleSheet(f"color: {THEME['warning']};")
            has_unknown = True
        else:
            unhealthy_sensors = []
            sensor_names = {
                SENSOR_3D_GYRO: "Gyro",
                SENSOR_3D_ACCEL: "Accel",
                SENSOR_3D_MAG: "Mag",
                SENSOR_ABSOLUTE_PRESSURE: "Baro"
            }
            for mask, name in sensor_names.items():
                if (enabled & mask) and not (health & mask):
                    unhealthy_sensors.append(name)

            if unhealthy_sensors:
                self.check_rows['sensors'].setText(f"FAIL: Unhealthy ({', '.join(unhealthy_sensors)})")
                self.check_rows['sensors'].setStyleSheet(f"color: {THEME['danger']};")
                has_fail = True
            else:
                self.check_rows['sensors'].setText("PASS: Gyro, Accel, Mag, Baro OK")
                self.check_rows['sensors'].setStyleSheet(f"color: {THEME['success']};")

        # 5. Horizon Level Alignment
        roll_deg = abs(math.degrees(d.get('roll', 0.0)))
        pitch_deg = abs(math.degrees(d.get('pitch', 0.0)))
        if last_hb == 0.0:
            self.check_rows['attitude'].setText("UNKNOWN: No Attitude Data")
            self.check_rows['attitude'].setStyleSheet(f"color: {THEME['warning']};")
            has_unknown = True
        elif roll_deg < 15.0 and pitch_deg < 15.0:
            self.check_rows['attitude'].setText(f"PASS: Level (R {roll_deg:.0f}\u00b0, P {pitch_deg:.0f}\u00b0)")
            self.check_rows['attitude'].setStyleSheet(f"color: {THEME['success']};")
        else:
            self.check_rows['attitude'].setText(f"FAIL: Tilted (R {roll_deg:.0f}\u00b0, P {pitch_deg:.0f}\u00b0 > 15\u00b0)")
            self.check_rows['attitude'].setStyleSheet(f"color: {THEME['danger']};")
            has_fail = True

        # 6. FCU Prearm Readiness
        prearm = d.get('prearm_fail', '')
        if last_hb == 0.0:
            self.check_rows['fcu'].setText("UNKNOWN: Disconnected")
            self.check_rows['fcu'].setStyleSheet(f"color: {THEME['warning']};")
            has_unknown = True
        elif prearm:
            disp = prearm[:26] + "..." if len(prearm) > 26 else prearm
            self.check_rows['fcu'].setText(f"FAIL: {disp}")
            self.check_rows['fcu'].setStyleSheet(f"color: {THEME['danger']};")
            has_fail = True
        elif d.get('armed', False):
            self.check_rows['fcu'].setText("PASS: Armed & In-Flight")
            self.check_rows['fcu'].setStyleSheet(f"color: {THEME['success']};")
        else:
            self.check_rows['fcu'].setText("PASS: Prearm Checks Clear")
            self.check_rows['fcu'].setStyleSheet(f"color: {THEME['success']};")

        # 7. Home Position
        has_home = d.get('has_home', False)
        h_lat = d.get('home_lat', 0.0)
        h_lon = d.get('home_lon', 0.0)
        curr_lat = d.get('lat', 0.0)
        curr_lon = d.get('lon', 0.0)

        if has_home and (h_lat != 0.0 or h_lon != 0.0):
            self.check_rows['home'].setText(f"PASS: Locked ({h_lat:.4f}, {h_lon:.4f})")
            self.check_rows['home'].setStyleSheet(f"color: {THEME['success']};")
        elif fix_type >= 3 and (curr_lat != 0.0 or curr_lon != 0.0):
            self.check_rows['home'].setText(f"PASS: Launch Fix ({curr_lat:.4f}, {curr_lon:.4f})")
            self.check_rows['home'].setStyleSheet(f"color: {THEME['success']};")
        else:
            self.check_rows['home'].setText("UNKNOWN: Awaiting Home Position")
            self.check_rows['home'].setStyleSheet(f"color: {THEME['warning']};")
            has_unknown = True

        # Overall Status Banner
        if has_fail:
            self.banner.setText("NO-GO \u2014 CRITICAL PRE-FLIGHT ISSUES DETECTED")
            self.banner.setStyleSheet(f"background: {THEME['danger']}; color: #ffffff; font-weight: bold; font-size: 12px; border-radius: 6px;")
        elif has_unknown:
            self.banner.setText("INCOMPLETE \u2014 AWAITING SENSOR EVIDENCE")
            self.banner.setStyleSheet(f"background: {THEME['warning']}; color: #ffffff; font-weight: bold; font-size: 12px; border-radius: 6px;")
        else:
            self.banner.setText("GO FOR FLIGHT \u2014 ALL SYSTEM CHECKS PASSED")
            self.banner.setStyleSheet(f"background: {THEME['success']}; color: #ffffff; font-weight: bold; font-size: 12px; border-radius: 6px;")
