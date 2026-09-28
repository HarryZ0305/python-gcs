import time
import math
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QComboBox, QSpinBox
)
from PyQt6.QtCore import Qt
from gcs.telemetry import telemetry_data, battery_config

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
    - Power: battery voltage and capacity using configurable battery cell count/chemistry
    - Sensors: SYS_STATUS health bits for Gyro, Accel, Mag, Baro, and level attitude
    - FCU Prearm: evaluates actual STATUSTEXT failure notices and flight controller readiness
    - Home Position: verifies confirmed HOME_POSITION or locked launch coordinates
    Strictly distinguishes PASS, FAIL, and UNKNOWN.
    UNKNOWN never produces 'GO FOR FLIGHT'.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Pre-Flight Safety Verification")
        self.setFixedSize(560, 600)
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

        # Config row: Battery cell configuration
        cfg_frame = QFrame()
        cfg_frame.setStyleSheet(f"background: {THEME['panel_bg']}; border: 1px solid {THEME['panel_border']}; border-radius: 6px;")
        cfg_layout = QHBoxLayout(cfg_frame)
        cfg_layout.setContentsMargins(10, 6, 10, 6)

        cfg_lbl = QLabel("Battery Configuration:")
        cfg_lbl.setStyleSheet(f"color: {THEME['dark_text']}; font-size: 11px; font-weight: bold; border: none;")
        cfg_layout.addWidget(cfg_lbl)

        self.cell_combo = QComboBox()
        for s in [1, 2, 3, 4, 5, 6, 8, 12]:
            self.cell_combo.addItem(f"{s}S LiPo ({s * 3.7:.1f}V nom)", s)
        current_cells = battery_config.get('cells', 4)
        idx = self.cell_combo.findData(current_cells)
        if idx >= 0:
            self.cell_combo.setCurrentIndex(idx)
        self.cell_combo.currentIndexChanged.connect(self._on_battery_config_changed)
        cfg_layout.addWidget(self.cell_combo)
        cfg_layout.addStretch()
        layout.addWidget(cfg_frame)

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
            val.setStyleSheet(f"color: {THEME['muted']}; font-size: 11px; background: transparent; border: none;")
            val.setAlignment(Qt.AlignmentFlag.AlignRight)
            row.addWidget(lbl)
            row.addWidget(val)
            ic_layout.addLayout(row)
            self.check_rows[key] = val

        layout.addWidget(self.items_container)

        self.summary_card = QFrame()
        self.summary_card.setStyleSheet(f"background: {THEME['panel_bg']}; border: 2px solid {THEME['panel_border']}; border-radius: 8px; padding: 6px;")
        sc_layout = QVBoxLayout(self.summary_card)
        self.summary_label = QLabel("AWAITING TELEMETRY VERIFICATION")
        self.summary_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.summary_label.setStyleSheet(f"font-size: 13px; font-weight: bold; color: {THEME['muted']}; border: none;")
        sc_layout.addWidget(self.summary_label)
        layout.addWidget(self.summary_card)

        btn_layout = QHBoxLayout()
        self.refresh_btn = QPushButton("Refresh Status")
        self.refresh_btn.setStyleSheet(f"background: {THEME['primary']}; color: #ffffff; padding: 8px 16px; border-radius: 6px; font-weight: bold;")
        self.refresh_btn.clicked.connect(self.evaluate_checks)
        btn_layout.addWidget(self.refresh_btn)

        self.close_btn = QPushButton("Close")
        self.close_btn.setStyleSheet(f"background: #e2e8f0; color: {THEME['dark_text']}; padding: 8px 16px; border-radius: 6px;")
        self.close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(self.close_btn)
        layout.addLayout(btn_layout)

        self.evaluate_checks()

    def _on_battery_config_changed(self):
        cells = self.cell_combo.currentData()
        if cells:
            battery_config['cells'] = int(cells)
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

        # 3. Power (Configurable Battery Voltage & Capacity)
        cells = battery_config.get('cells', 4)
        crit_v = cells * battery_config.get('crit_volt_per_cell', 3.3)
        warn_v = cells * battery_config.get('warn_volt_per_cell', 3.5)
        crit_p = battery_config.get('crit_pct', 15)
        warn_p = battery_config.get('warn_pct', 25)

        batt = d.get('battery', -1)
        volt = d.get('voltage', 0.0)

        if batt == -1 and volt == 0.0:
            self.check_rows['power'].setText("UNKNOWN: No Power Telemetry")
            self.check_rows['power'].setStyleSheet(f"color: {THEME['warning']};")
            has_unknown = True
        elif volt > 0.0 and volt < crit_v:
            self.check_rows['power'].setText(f"FAIL: Critical Voltage ({volt:.1f}V < {crit_v:.1f}V)")
            self.check_rows['power'].setStyleSheet(f"color: {THEME['danger']};")
            has_fail = True
        elif batt >= 0 and batt < crit_p:
            self.check_rows['power'].setText(f"FAIL: Critical Capacity ({batt}% < {crit_p}%)")
            self.check_rows['power'].setStyleSheet(f"color: {THEME['danger']};")
            has_fail = True
        elif (volt > 0.0 and volt < warn_v) or (batt >= 0 and batt < warn_p):
            self.check_rows['power'].setText(f"WARN: Low ({volt:.1f}V, {batt}%)")
            self.check_rows['power'].setStyleSheet(f"color: {THEME['warning']};")
            has_unknown = True
        else:
            disp_b = f"{batt}%" if batt >= 0 else "OK"
            self.check_rows['power'].setText(f"PASS: {volt:.1f}V ({disp_b} on {cells}S)")
            self.check_rows['power'].setStyleSheet(f"color: {THEME['success']};")

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

        # 6. FCU Prearm Readiness (Evidence-Based: requires confirmed STANDBY/ACTIVE state)
        prearm = d.get('prearm_fail', '')
        sys_state = d.get('system_status', 0)
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
        elif sys_state in (3, 4): # Confirmed STANDBY or ACTIVE
            self.check_rows['fcu'].setText("PASS: Standby & Armed Ready")
            self.check_rows['fcu'].setStyleSheet(f"color: {THEME['success']};")
        elif sys_state in (1, 2): # BOOT or CALIBRATING
            self.check_rows['fcu'].setText(f"UNKNOWN: FCU Initializing ({sys_state})")
            self.check_rows['fcu'].setStyleSheet(f"color: {THEME['warning']};")
            has_unknown = True
        elif sys_state in (5, 6): # CRITICAL or EMERGENCY
            self.check_rows['fcu'].setText(f"FAIL: FCU Emergency ({sys_state})")
            self.check_rows['fcu'].setStyleSheet(f"color: {THEME['danger']};")
            has_fail = True
        else:
            self.check_rows['fcu'].setText("UNKNOWN: Awaiting FCU Prearm Evidence")
            self.check_rows['fcu'].setStyleSheet(f"color: {THEME['warning']};")
            has_unknown = True

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
            self.check_rows['home'].setText("WARN: 3D Fix Active, Awaiting HOME_POSITION")
            self.check_rows['home'].setStyleSheet(f"color: {THEME['warning']};")
            has_unknown = True
        else:
            self.check_rows['home'].setText("UNKNOWN: No Home Lock")
            self.check_rows['home'].setStyleSheet(f"color: {THEME['warning']};")
            has_unknown = True

        # Overall Status Verdict
        if has_fail:
            self.summary_label.setText("NO-GO: CRITICAL PRE-FLIGHT CHECKS FAILED")
            self.summary_label.setStyleSheet(f"font-size: 13px; font-weight: bold; color: {THEME['danger']}; border: none;")
            self.summary_card.setStyleSheet(f"background: #fdf2f2; border: 2px solid {THEME['danger']}; border-radius: 8px; padding: 6px;")
        elif has_unknown:
            self.summary_label.setText("CAUTION: UNKNOWN / INCOMPLETE TELEMETRY (NO-GO)")
            self.summary_label.setStyleSheet(f"font-size: 13px; font-weight: bold; color: {THEME['warning']}; border: none;")
            self.summary_card.setStyleSheet(f"background: #fffbeb; border: 2px solid {THEME['warning']}; border-radius: 8px; padding: 6px;")
        else:
            self.summary_label.setText("GO FOR FLIGHT: ALL PRE-FLIGHT CHECKS PASSED")
            self.summary_label.setStyleSheet(f"font-size: 13px; font-weight: bold; color: {THEME['success']}; border: none;")
            self.summary_card.setStyleSheet(f"background: #f0fdf4; border: 2px solid {THEME['success']}; border-radius: 8px; padding: 6px;")
