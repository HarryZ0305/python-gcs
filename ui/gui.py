import sys
import math
import threading
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout, QLabel, QFrame, QMessageBox,
    QPushButton, QComboBox, QSpinBox, QListWidget
)
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QFont
from telemetry import telemetry_data
from commands import arm, disarm, set_mode, takeoff, set_offboard_targets, reset_offboard_targets
from ui.map_view import MapView
from ui.attitude_view import AttitudeView
from ui.console_view import ConsoleView
from ui.camera_view import CameraView


class StatPanel(QFrame):
    """A titled panel holding label:value rows that update live."""
    def __init__(self, title):
        super().__init__()
        self.setStyleSheet("background-color: #1e2d3d; border-radius: 8px;")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(10, 8, 10, 8)
        self._layout.setSpacing(4)

        t = QLabel(title)
        t.setStyleSheet("color: #7a9cc4; font-size: 11px; font-weight: bold; border: none;")
        self._layout.addWidget(t)

        self.rows = {}

    def add_row(self, key, label):
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setStyleSheet("color: #5a7a9a; font-size: 12px; border: none;")
        val = QLabel("---")
        val.setFont(QFont("Courier New", 13, QFont.Weight.Bold))
        val.setStyleSheet("color: #00e5ff; border: none;")
        val.setAlignment(Qt.AlignmentFlag.AlignRight)
        row.addWidget(lbl)
        row.addStretch()
        row.addWidget(val)
        self._layout.addLayout(row)
        self.rows[key] = val

    def set(self, key, text, color="#00e5ff"):
        if key in self.rows:
            self.rows[key].setText(text)
            self.rows[key].setStyleSheet(f"color: {color}; border: none;")


class GCSWindow(QMainWindow):
    def __init__(self, vehicle):
        super().__init__()
        self.vehicle = vehicle
        self.waypoints = []
        
        from commands import _ensure_streamer
        _ensure_streamer(self.vehicle)

        self.setWindowTitle("Python GCS")
        self.resize(1280, 800)

        root = QWidget()
        root.setStyleSheet("background-color: #0d1b2a;")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setSpacing(8)
        outer.setContentsMargins(10, 10, 10, 10)

        # ===== Build all widgets =====

        # Power Metrics
        self.power_panel = StatPanel("POWER METRICS")
        self.power_panel.add_row('battery', 'Battery')
        self.power_panel.add_row('voltage', 'Voltage')

        # GNSS & Spatial
        self.gnss_panel = StatPanel("GNSS & SPATIAL")
        self.gnss_panel.add_row('fix', 'GPS Fix')
        self.gnss_panel.add_row('sats', 'Satellites')
        self.gnss_panel.add_row('lat', 'Latitude')
        self.gnss_panel.add_row('lon', 'Longitude')
        self.gnss_panel.add_row('alt', 'Altitude')

        # Attitude / Speed
        self.attspeed_panel = StatPanel("ATTITUDE / SPEED")
        self.attspeed_panel.add_row('roll', 'Roll')
        self.attspeed_panel.add_row('pitch', 'Pitch')
        self.attspeed_panel.add_row('yaw', 'Heading')
        self.attspeed_panel.add_row('speed', 'Speed')

        # Arm button
        self.arm_btn = QPushButton("ARM")
        self.arm_btn.setFixedHeight(44)
        self.arm_btn.setFont(QFont("Courier New", 12, QFont.Weight.Bold))
        self.arm_btn.setStyleSheet(self._btn_style("#44ff88", "#0d1b2a"))
        self.arm_btn.clicked.connect(self.on_arm_disarm)

        # Cameras
        self.front_cam = CameraView("FRONT VIEW CAMERA")
        self.bottom_cam = CameraView("BOTTOM VIEW CAMERA")

        # Map + 3D
        self.map_view = MapView()
        self.attitude_view = AttitudeView()

        # Console
        self.console_view = ConsoleView()

        # Action buttons
        self.mode_combo = QComboBox()
        self.mode_combo.addItems([
            'MANUAL', 'STABILIZED', 'ALTCTL', 'POSCTL', 'OFFBOARD',
            'AUTO.LOITER', 'AUTO.RTL', 'AUTO.LAND', 'AUTO.TAKEOFF', 'AUTO.MISSION'
        ])
        self.mode_combo.setFixedHeight(34)
        self.mode_combo.setStyleSheet(self._input_style())

        self.mode_btn = QPushButton("SET MODE")
        self.mode_btn.setFixedHeight(34)
        self.mode_btn.setStyleSheet(self._btn_style("#00e5ff", "#0d1b2a"))
        self.mode_btn.clicked.connect(self.on_set_mode)

        self.alt_spin = QSpinBox()
        self.alt_spin.setRange(1, 100)
        self.alt_spin.setValue(10)
        self.alt_spin.setFixedHeight(34)
        self.alt_spin.setStyleSheet(self._input_style())

        self.takeoff_btn = QPushButton("TAKEOFF")
        self.takeoff_btn.setFixedHeight(34)
        self.takeoff_btn.setStyleSheet(self._btn_style("#ffaa00", "#0d1b2a"))
        self.takeoff_btn.clicked.connect(self.on_takeoff)

        self.rtl_btn = QPushButton("RTL")
        self.rtl_btn.setFixedHeight(34)
        self.rtl_btn.setStyleSheet(self._btn_style("#00e5ff", "#0d1b2a"))
        self.rtl_btn.clicked.connect(self.on_rtl)

        self.land_btn = QPushButton("LAND")
        self.land_btn.setFixedHeight(34)
        self.land_btn.setStyleSheet(self._btn_style("#ffaa00", "#0d1b2a"))
        self.land_btn.clicked.connect(self.on_land)

        # Manual movement (sim testing: tilt the drone, watch the 3D model)
        self.yawl_btn = QPushButton("YAW L")
        self.yawl_btn.setFixedHeight(34)
        self.yawl_btn.setStyleSheet(self._btn_style("#00e5ff", "#0d1b2a"))
        self.yawl_btn.clicked.connect(self.on_yaw_left)

        self.fwd_btn = QPushButton("FORWARD")
        self.fwd_btn.setFixedHeight(34)
        self.fwd_btn.setStyleSheet(self._btn_style("#44ff88", "#0d1b2a"))
        self.fwd_btn.clicked.connect(self.on_forward)

        self.yawr_btn = QPushButton("YAW R")
        self.yawr_btn.setFixedHeight(34)
        self.yawr_btn.setStyleSheet(self._btn_style("#00e5ff", "#0d1b2a"))
        self.yawr_btn.clicked.connect(self.on_yaw_right)

        self.hover_btn = QPushButton("HOVER")
        self.hover_btn.setFixedHeight(34)
        self.hover_btn.setStyleSheet(self._btn_style("#ffaa00", "#0d1b2a"))
        self.hover_btn.clicked.connect(self.on_hover)

        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: #7a9cc4; font-size: 11px; border: none;")

        # Action panel container
        self.action_panel = QFrame()
        self.action_panel.setStyleSheet("background-color: #1e2d3d; border-radius: 8px;")
        ap = QVBoxLayout(self.action_panel)
        ap.setContentsMargins(10, 8, 10, 8)
        ap.setSpacing(8)
        ap_title = QLabel("ACTION BUTTONS")
        ap_title.setStyleSheet("color: #7a9cc4; font-size: 11px; font-weight: bold; border: none;")
        ap.addWidget(ap_title)
        r1 = QHBoxLayout(); r1.addWidget(self.mode_combo); r1.addWidget(self.mode_btn); ap.addLayout(r1)
        r2 = QHBoxLayout(); r2.addWidget(self.alt_spin); r2.addWidget(self.takeoff_btn); ap.addLayout(r2)
        r3 = QHBoxLayout(); r3.addWidget(self.rtl_btn); r3.addWidget(self.land_btn); ap.addLayout(r3)
        r4 = QHBoxLayout()
        r4.addWidget(self.yawl_btn)
        r4.addWidget(self.fwd_btn)
        r4.addWidget(self.yawr_btn)
        r4.addWidget(self.hover_btn)
        ap.addLayout(r4)
        ap.addWidget(self.status_label)

        # Mission planning panel container
        self.mission_panel = QFrame()
        self.mission_panel.setStyleSheet("background-color: #1e2d3d; border-radius: 8px;")
        mp = QVBoxLayout(self.mission_panel)
        mp.setContentsMargins(10, 8, 10, 8)
        mp.setSpacing(6)
        
        mp_title = QLabel("MISSION PLANNING")
        mp_title.setStyleSheet("color: #7a9cc4; font-size: 11px; font-weight: bold; border: none;")
        mp.addWidget(mp_title)
        
        self.wp_list = QListWidget()
        self.wp_list.setStyleSheet("""
            QListWidget {
                background-color: #0d1b2a; color: #00e5ff;
                border: 1px solid #2a4a6a; border-radius: 4px;
                font-family: Courier New; font-size: 11px;
            }
        """)
        mp.addWidget(self.wp_list)
        
        m_row = QHBoxLayout()
        m_row.setSpacing(6)
        
        self.sync_btn = QPushButton("SYNC MAP")
        self.sync_btn.setFixedHeight(30)
        self.sync_btn.setStyleSheet(self._btn_style("#00e5ff", "#0d1b2a"))
        self.sync_btn.clicked.connect(self.on_sync_map)
        
        self.clear_btn = QPushButton("CLEAR")
        self.clear_btn.setFixedHeight(30)
        self.clear_btn.setStyleSheet(self._btn_style("#ff4444", "#0d1b2a"))
        self.clear_btn.clicked.connect(self.on_clear_mission)
        
        self.upload_btn = QPushButton("UPLOAD")
        self.upload_btn.setFixedHeight(30)
        self.upload_btn.setStyleSheet(self._btn_style("#44ff88", "#0d1b2a"))
        self.upload_btn.clicked.connect(self.on_upload_mission)
        
        m_row.addWidget(self.sync_btn)
        m_row.addWidget(self.clear_btn)
        m_row.addWidget(self.upload_btn)
        mp.addLayout(m_row)

        # ===== Assemble layout (3 columns + bottom bar) =====
        top = QHBoxLayout()
        top.setSpacing(8)

        left = QVBoxLayout(); left.setSpacing(8)
        left.addWidget(self.power_panel, stretch=3)
        left.addWidget(self.gnss_panel, stretch=4)
        left.addWidget(self.arm_btn, stretch=1)

        center = QVBoxLayout(); center.setSpacing(8)
        center.addWidget(self.front_cam, stretch=1)
        center.addWidget(self.bottom_cam, stretch=1)

        right = QVBoxLayout(); right.setSpacing(8)
        right.addWidget(self.map_view, stretch=5)
        right.addWidget(self.attitude_view, stretch=3)
        right.addWidget(self.attspeed_panel, stretch=2)

        top.addLayout(left, stretch=2)
        top.addLayout(center, stretch=3)
        top.addLayout(right, stretch=4)

        outer.addLayout(top, stretch=5)

        bottom = QHBoxLayout(); bottom.setSpacing(8)
        bottom.addWidget(self.action_panel, stretch=3)
        bottom.addWidget(self.mission_panel, stretch=4)
        bottom.addWidget(self.console_view, stretch=5)
        outer.addLayout(bottom, stretch=2)

        # ===== Refresh timer =====
        self.timer = QTimer()
        self.timer.timeout.connect(self.refresh)
        self.timer.start(500)

    # ---- styling helpers ----
    def _btn_style(self, color, bg):
        return f"""
            QPushButton {{
                background-color: {bg}; color: {color};
                border: 2px solid {color}; border-radius: 6px;
                font-family: Courier New; font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {color}; color: {bg}; }}
            QPushButton:disabled {{ border-color: #2a4a6a; color: #2a4a6a; }}
        """

    def _input_style(self):
        return """
            QComboBox, QSpinBox {
                background-color: #0d1b2a; color: #00e5ff;
                border: 1px solid #2a4a6a; border-radius: 4px;
                padding: 4px 8px; font-family: Courier New; font-size: 12px;
            }
            QComboBox QAbstractItemView {
                background-color: #0d1b2a; color: #00e5ff;
                selection-background-color: #2a4a6a;
            }
        """

    # ---- command handlers ----
    def on_arm_disarm(self):
        if telemetry_data['armed']:
            threading.Thread(target=disarm, args=(self.vehicle,), daemon=True).start()
            self.set_status("Disarm command sent...")
        else:
            threading.Thread(target=arm, args=(self.vehicle,), daemon=True).start()
            self.set_status("Arm command sent...")

    def on_set_mode(self):
        mode = self.mode_combo.currentText()
        threading.Thread(target=set_mode, args=(self.vehicle, mode), daemon=True).start()
        self.set_status(f"Setting mode to {mode}...")

    def on_takeoff(self):
        alt = self.alt_spin.value()
        threading.Thread(target=takeoff, args=(self.vehicle, alt), daemon=True).start()
        self.set_status(f"Takeoff sequence initiated — target {alt}m")

    def on_rtl(self):
        threading.Thread(target=set_mode, args=(self.vehicle, 'AUTO.RTL'), daemon=True).start()
        self.set_status("RTL command sent...")

    def on_land(self):
        threading.Thread(target=set_mode, args=(self.vehicle, 'AUTO.LAND'), daemon=True).start()
        self.set_status("LAND command sent...")

    def on_forward(self):
        set_offboard_targets(vx=2.0, yaw_rate=0.0)
        self.set_status("Offboard target: Forward (2.0 m/s)")

    def on_yaw_left(self):
        set_offboard_targets(vx=0.0, yaw_rate=-0.5)
        self.set_status("Offboard target: Yaw Left (-0.5 rad/s)")

    def on_yaw_right(self):
        set_offboard_targets(vx=0.0, yaw_rate=0.5)
        self.set_status("Offboard target: Yaw Right (0.5 rad/s)")

    def on_hover(self):
        reset_offboard_targets()
        self.set_status("Offboard target: Hover")

    def set_status(self, msg):
        self.status_label.setText(msg)

    def on_sync_map(self):
        self.map_view.get_waypoints(self.on_waypoints_received)

    def on_waypoints_received(self, wps):
        self.wp_list.clear()
        if not wps:
            self.waypoints = []
            self.set_status("No waypoints on map to sync.")
            return
        self.waypoints = wps
        for idx, wp in enumerate(wps):
            self.wp_list.addItem(f"WP {idx+1}: {wp[0]:.6f}, {wp[1]:.6f}")
        self.set_status(f"Synced {len(wps)} waypoints from map.")

    def on_clear_mission(self):
        self.map_view.clear_waypoints()
        self.wp_list.clear()
        self.waypoints = []
        self.set_status("Mission cleared.")

    def on_upload_mission(self):
        if not self.waypoints:
            self.set_status("Upload failed: Sync map first!")
            return
        from commands import upload_mission
        threading.Thread(target=upload_mission, args=(self.vehicle, self.waypoints), daemon=True).start()
        self.set_status("Uploading mission...")

    # ---- live refresh ----
    def refresh(self):
        d = telemetry_data

        self.power_panel.set('battery', f"{d['battery']}%",
            "#ff4444" if d['battery'] < 20 else "#00e5ff")
        self.power_panel.set('voltage', f"{d['voltage']:.1f}V")

        fix_labels = {0: "NO FIX", 1: "NO FIX", 2: "2D", 3: "3D",
                      4: "DGPS", 5: "RTK-FLT", 6: "RTK-FIX"}
        fix = d['fix_type']
        self.gnss_panel.set('fix', fix_labels.get(fix, str(fix)),
            "#44ff88" if fix >= 3 else "#ff4444")
        self.gnss_panel.set('sats', str(d['satellites']))
        self.gnss_panel.set('lat', f"{d['lat']:.6f}")
        self.gnss_panel.set('lon', f"{d['lon']:.6f}")
        self.gnss_panel.set('alt', f"{d['alt']:.1f} m")

        self.attspeed_panel.set('roll', f"{math.degrees(d['roll']):.0f}\u00b0")
        self.attspeed_panel.set('pitch', f"{math.degrees(d['pitch']):.0f}\u00b0")
        yaw_deg = math.degrees(d['yaw']) % 360
        self.attspeed_panel.set('yaw', f"{yaw_deg:.0f}\u00b0")
        self.attspeed_panel.set('speed', f"{d['groundspeed']:.1f} m/s")

        if d['armed']:
            self.arm_btn.setText("DISARM")
            self.arm_btn.setStyleSheet(self._btn_style("#ff4444", "#0d1b2a"))
        else:
            self.arm_btn.setText("ARM")
            self.arm_btn.setStyleSheet(self._btn_style("#44ff88", "#0d1b2a"))

        self.map_view.update_position(d['lat'], d['lon'])
        self.attitude_view.update_attitude(d['roll'], d['pitch'], d['yaw'])
        self.console_view.refresh_logs()

    def closeEvent(self, event):  # type: ignore
        if telemetry_data['armed']:
            reply = QMessageBox.question(
                self, 'Warning',
                "Drone is still ARMED! Are you sure you want to exit the GCS?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                print("Closing GCS...")
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()


def launch_gui(vehicle):
    app = QApplication(sys.argv)
    window = GCSWindow(vehicle)
    window.show()
    app.exec()