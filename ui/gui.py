import sys
import math
import threading
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout, QLabel, QFrame, QMessageBox,
    QPushButton, QComboBox, QSpinBox, QListWidget, QTabWidget,
    QLineEdit
)
from PyQt6.QtCore import QTimer, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont
from telemetry import telemetry_data
from commands import arm, disarm, set_mode, takeoff, set_offboard_targets, reset_offboard_targets, stop_streamer
from ui.map_view import MapView
from ui.attitude_view import AttitudeView
from ui.console_view import ConsoleView
from ui.camera_view import CameraView
from ui.setup_view import SetupView


class ConnectionWorker(QThread):
    connected = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, connection_string):
        super().__init__()
        self.connection_string = connection_string
        self.running = True

    def run(self):
        from connection import connect
        try:
            while self.running:
                vehicle = connect(self.connection_string, timeout=1.0)
                if vehicle is not None:
                    if self.running:
                        self.connected.emit(vehicle)
                    return
                self.msleep(500)
        except Exception as e:
            if self.running:
                self.failed.emit(str(e))

    def stop(self):
        self.running = False


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
    def __init__(self, vehicle=None):
        super().__init__()
        self.vehicle = vehicle
        self.waypoints = []
        self.takeoff_point = None
        self.landing_point = None
        self.conn_worker = None
        self.telemetry_thread = None
        
        if self.vehicle is not None:
            from commands import _ensure_streamer
            _ensure_streamer(self.vehicle)

        self.setWindowTitle("Python GCS")
        self.resize(1280, 800)

        root = QWidget()
        root.setStyleSheet("background-color: #0d1b2a;")
        self.setCentralWidget(root)
        
        # Create Tab Widget
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #2a4a6a;
                background-color: #0d1b2a;
                border-radius: 8px;
            }
            QTabBar::tab {
                background-color: #1e2d3d;
                color: #7a9cc4;
                font-family: Courier New;
                font-weight: bold;
                font-size: 13px;
                padding: 8px 20px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                border: 1px solid #2a4a6a;
                border-bottom: none;
                margin-right: 4px;
            }
            QTabBar::tab:selected {
                background-color: #0d1b2a;
                color: #00e5ff;
                border: 2px solid #00e5ff;
                border-bottom: none;
            }
            QTabBar::tab:hover {
                background-color: #2a4a6a;
                color: #ffffff;
            }
        """)

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

        # Safety & Alerts
        self.alert_panel = StatPanel("SAFETY & ALERTS")
        self.alert_panel.add_row('status', 'Safety Status')
        self.alert_panel.add_row('alert_msg', 'Active Alerts')

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
        
        self.wp_progress_label = QLabel("Active Waypoint: ---")
        self.wp_progress_label.setStyleSheet("color: #00e5ff; font-family: Courier New; font-size: 11px; border: none;")
        mp.addWidget(self.wp_progress_label)
        
        m_row = QHBoxLayout()
        m_row.setSpacing(6)
        
        self.sync_btn = QPushButton("SYNC MAP")
        self.sync_btn.setFixedHeight(30)
        self.sync_btn.setStyleSheet(self._btn_style("#00e5ff", "#0d1b2a"))
        self.sync_btn.clicked.connect(self.on_sync_map)
        
        self.upload_btn = QPushButton("UPLOAD")
        self.upload_btn.setFixedHeight(30)
        self.upload_btn.setStyleSheet(self._btn_style("#44ff88", "#0d1b2a"))
        self.upload_btn.clicked.connect(self.on_upload_mission)

        self.clear_btn = QPushButton("CLEAR")
        self.clear_btn.setFixedHeight(30)
        self.clear_btn.setStyleSheet(self._btn_style("#ff4444", "#0d1b2a"))
        self.clear_btn.clicked.connect(self.on_clear_mission)
        
        m_row.addWidget(self.sync_btn)
        m_row.addWidget(self.upload_btn)
        m_row.addWidget(self.clear_btn)
        mp.addLayout(m_row)

        self.start_btn = QPushButton("START MISSION")
        self.start_btn.setFixedHeight(34)
        self.start_btn.setStyleSheet(self._btn_style("#44ff88", "#0d1b2a"))
        self.start_btn.clicked.connect(self.on_start_mission)
        mp.addWidget(self.start_btn)

        # ===== FLY Tab Layout =====
        fly_widget = QWidget()
        fly_layout = QVBoxLayout(fly_widget)
        fly_layout.setContentsMargins(6, 6, 6, 6)
        fly_layout.setSpacing(6)

        top = QHBoxLayout(); top.setSpacing(6)
        
        left = QVBoxLayout(); left.setSpacing(6)
        left.addWidget(self.power_panel, stretch=3)
        left.addWidget(self.gnss_panel, stretch=4)
        left.addWidget(self.alert_panel, stretch=3)
        left.addWidget(self.arm_btn, stretch=1)

        center = QVBoxLayout(); center.setSpacing(6)
        center.addWidget(self.front_cam, stretch=1)
        center.addWidget(self.bottom_cam, stretch=1)

        right = QVBoxLayout(); right.setSpacing(6)
        right.addWidget(self.map_view, stretch=5)
        right.addWidget(self.attitude_view, stretch=3)
        right.addWidget(self.attspeed_panel, stretch=2)

        top.addLayout(left, stretch=2)
        top.addLayout(center, stretch=3)
        top.addLayout(right, stretch=4)
        fly_layout.addLayout(top, stretch=5)

        bottom = QHBoxLayout(); bottom.setSpacing(6)
        bottom.addWidget(self.action_panel, stretch=1)
        bottom.addWidget(self.console_view, stretch=1)
        fly_layout.addLayout(bottom, stretch=2)

        self.tabs.addTab(fly_widget, "FLY")

        # ===== PLAN Tab Layout =====
        plan_widget = QWidget()
        plan_layout = QHBoxLayout(plan_widget)
        plan_layout.setContentsMargins(8, 8, 8, 8)
        plan_layout.setSpacing(8)
        
        self.plan_map_view = MapView()
        plan_layout.addWidget(self.plan_map_view, stretch=3)
        plan_layout.addWidget(self.mission_panel, stretch=1)
        self.tabs.addTab(plan_widget, "PLAN")

        # ===== SETUP Tab Layout =====
        self.setup_view = SetupView(self.vehicle)
        self.tabs.addTab(self.setup_view, "SETUP")

        # ===== Assemble Central Layout =====
        root = QWidget()
        root.setStyleSheet("background-color: #0d1b2a;")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(8, 8, 8, 8)

        # Connection Panel
        self.conn_panel = QFrame()
        self.conn_panel.setStyleSheet("background-color: #1e2d3d; border-radius: 8px; border: 1px solid #2a4a6a;")
        self.conn_panel.setFixedHeight(50)
        
        conn_layout = QHBoxLayout(self.conn_panel)
        conn_layout.setContentsMargins(15, 5, 15, 5)
        conn_layout.setSpacing(10)
        
        conn_lbl = QLabel("CONNECTION:")
        conn_lbl.setStyleSheet("color: #7a9cc4; font-family: Courier New; font-weight: bold; font-size: 12px; border: none;")
        conn_layout.addWidget(conn_lbl)
        
        self.conn_input = QLineEdit()
        self.conn_input.setText("udpin:0.0.0.0:14540")
        self.conn_input.setStyleSheet("""
            QLineEdit {
                background-color: #0d1b2a; color: #00e5ff;
                border: 1px solid #2a4a6a; border-radius: 4px;
                padding: 4px 8px; font-family: Courier New; font-size: 12px;
            }
        """)
        conn_layout.addWidget(self.conn_input, stretch=1)
        
        self.conn_btn = QPushButton("CONNECT")
        self.conn_btn.setFixedWidth(120)
        self.conn_btn.setFixedHeight(30)
        self.conn_btn.setStyleSheet(self._btn_style("#00e5ff", "#0d1b2a"))
        self.conn_btn.clicked.connect(self.on_connect_toggle)
        conn_layout.addWidget(self.conn_btn)
        
        self.conn_status = QLabel("DISCONNECTED")
        self.conn_status.setStyleSheet("color: #ff4444; font-weight: bold; font-family: Courier New; font-size: 12px; border: none;")
        conn_layout.addWidget(self.conn_status)

        outer.addWidget(self.conn_panel)
        outer.addWidget(self.tabs)

        # ===== Refresh timer =====
        self.timer = QTimer()
        self.timer.timeout.connect(self.refresh)
        self.timer.start(500)

        # Initialize connection states
        if self.vehicle is not None:
            self.on_connected(self.vehicle)
        else:
            self.disconnect_vehicle()

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

    def on_connect_toggle(self):
        if self.vehicle is not None:
            self.disconnect_vehicle()
        else:
            connection_string = self.conn_input.text().strip()
            if not connection_string:
                self.set_status("Error: Connection string is empty!")
                return
            
            self.set_status("Connecting to vehicle...")
            self.conn_btn.setText("CONNECTING...")
            self.conn_btn.setEnabled(False)
            self.conn_input.setEnabled(False)
            self.conn_status.setText("CONNECTING")
            self.conn_status.setStyleSheet("color: #ffaa00; font-weight: bold; font-family: Courier New; font-size: 12px; border: none;")
            
            self.conn_worker = ConnectionWorker(connection_string)
            self.conn_worker.connected.connect(self.on_connected)
            self.conn_worker.failed.connect(self.on_connection_failed)
            self.conn_worker.start()

    def on_connected(self, vehicle):
        self.vehicle = vehicle
        self.setup_view.set_vehicle(vehicle)
        
        from commands import _ensure_streamer
        _ensure_streamer(self.vehicle)
        
        from connection import request_telemetry
        from telemetry import read_telemetry
        try:
            request_telemetry(self.vehicle)
            import telemetry
            telemetry.telemetry_active = True
            
            self.telemetry_thread = threading.Thread(target=read_telemetry, args=(self.vehicle,), daemon=True)
            self.telemetry_thread.start()
        except Exception as e:
            self.set_status(f"Telemetry start failed: {e}")
            
        self.set_status("Connected to vehicle!")
        self.conn_btn.setText("DISCONNECT")
        self.conn_btn.setEnabled(True)
        self.conn_input.setEnabled(False)
        self.conn_status.setText("CONNECTED")
        self.conn_status.setStyleSheet("color: #44ff88; font-weight: bold; font-family: Courier New; font-size: 12px; border: none;")
        self.set_controls_enabled(True)

        # Automatically request all parameters upon connection
        from commands import request_all_parameters
        threading.Thread(target=request_all_parameters, args=(self.vehicle,), daemon=True).start()

    def on_connection_failed(self, error_msg):
        self.set_status(f"Connection failed: {error_msg}")
        self.disconnect_vehicle()

    def disconnect_vehicle(self):
        if self.conn_worker is not None:
            self.conn_worker.stop()
            self.conn_worker.wait()
            self.conn_worker = None
            
        import telemetry
        telemetry.telemetry_active = False
        telemetry_data['last_heartbeat_time'] = 0.0
        telemetry_data['prearm_fail'] = ""
        
        stop_streamer()
        
        if self.vehicle is not None:
            try:
                self.vehicle.close()
            except Exception:
                pass
            self.vehicle = None
            
        if hasattr(self, 'setup_view'):
            self.setup_view.set_vehicle(None)
        
        self.set_status("Disconnected.")
        self.conn_btn.setText("CONNECT")
        self.conn_btn.setEnabled(True)
        self.conn_input.setEnabled(True)
        self.conn_status.setText("DISCONNECTED")
        self.conn_status.setStyleSheet("color: #ff4444; font-weight: bold; font-family: Courier New; font-size: 12px; border: none;")
        self.set_controls_enabled(False)

    def set_controls_enabled(self, enabled):
        self.arm_btn.setEnabled(enabled)
        self.mode_btn.setEnabled(enabled)
        self.takeoff_btn.setEnabled(enabled)
        self.rtl_btn.setEnabled(enabled)
        self.land_btn.setEnabled(enabled)
        self.yawl_btn.setEnabled(enabled)
        self.fwd_btn.setEnabled(enabled)
        self.yawr_btn.setEnabled(enabled)
        self.hover_btn.setEnabled(enabled)
        self.sync_btn.setEnabled(enabled)
        self.clear_btn.setEnabled(enabled)
        self.upload_btn.setEnabled(enabled)
        self.start_btn.setEnabled(enabled)

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

    def ensure_offboard(self):
        if not self.vehicle:
            return
        current_mode = telemetry_data.get('mode', 'UNKNOWN')
        if current_mode != 'OFFBOARD':
            self.mode_combo.setCurrentText('OFFBOARD')
            telemetry_data['mode'] = 'OFFBOARD'
            threading.Thread(target=set_mode, args=(self.vehicle, 'OFFBOARD'), daemon=True).start()
            self.set_status("Auto-switching to OFFBOARD mode...")

    def on_forward(self):
        self.ensure_offboard()
        set_offboard_targets(vx=2.0, yaw_rate=0.0)
        self.set_status("Offboard target: Forward (2.0 m/s)")

    def on_yaw_left(self):
        self.ensure_offboard()
        set_offboard_targets(vx=0.0, yaw_rate=-0.5)
        self.set_status("Offboard target: Yaw Left (-0.5 rad/s)")

    def on_yaw_right(self):
        self.ensure_offboard()
        set_offboard_targets(vx=0.0, yaw_rate=0.5)
        self.set_status("Offboard target: Yaw Right (0.5 rad/s)")

    def on_hover(self):
        self.ensure_offboard()
        reset_offboard_targets()
        self.set_status("Offboard target: Hover")

    def set_status(self, msg):
        self.status_label.setText(msg)

    def on_sync_map(self):
        self.plan_map_view.get_waypoints(self.on_waypoints_received)

    def on_waypoints_received(self, data):
        self.wp_list.clear()
        if not data or not isinstance(data, dict):
            self.waypoints = []
            self.takeoff_point = None
            self.landing_point = None
            self.set_status("No mission elements to sync.")
            return

        self.takeoff_point = data.get('takeoff')
        self.waypoints = data.get('waypoints', [])
        self.landing_point = data.get('landing')

        if self.takeoff_point:
            self.wp_list.addItem(f"TAKEOFF: {self.takeoff_point[0]:.6f}, {self.takeoff_point[1]:.6f}")

        for idx, wp in enumerate(self.waypoints):
            self.wp_list.addItem(f"WP {idx+1}: {wp[0]:.6f}, {wp[1]:.6f}")

        if self.landing_point:
            self.wp_list.addItem(f"LAND: {self.landing_point[0]:.6f}, {self.landing_point[1]:.6f}")

        total_items = (1 if self.takeoff_point else 0) + len(self.waypoints) + (1 if self.landing_point else 0)
        self.set_status(f"Synced mission: {total_items} items.")

    def on_clear_mission(self):
        self.plan_map_view.clear_waypoints()
        self.wp_list.clear()
        self.waypoints = []
        self.takeoff_point = None
        self.landing_point = None
        telemetry_data['wp_current'] = -1
        self.set_status("Mission cleared.")

    def on_upload_mission(self):
        if not self.waypoints and not self.takeoff_point and not self.landing_point:
            self.set_status("Upload failed: Sync map first!")
            return
        from commands import upload_mission
        threading.Thread(target=upload_mission, args=(
            self.vehicle, self.waypoints, self.takeoff_point, self.landing_point
        ), daemon=True).start()
        self.set_status("Uploading mission...")

    def on_start_mission(self):
        if not self.vehicle:
            self.set_status("Start Mission failed: No vehicle connection.")
            return
        threading.Thread(target=set_mode, args=(self.vehicle, 'AUTO.MISSION'), daemon=True).start()
        self.set_status("Setting mode to AUTO.MISSION (Starting mission)...")

    # ---- live refresh ----
    def refresh(self):
        import time
        d = telemetry_data

        if not self.vehicle:
            self.power_panel.set('battery', "---", "#5a7a9a")
            self.power_panel.set('voltage', "---", "#5a7a9a")
            self.gnss_panel.set('fix', "DISCONNECTED", "#ff4444")
            self.gnss_panel.set('sats', "---", "#5a7a9a")
            self.gnss_panel.set('lat', "---", "#5a7a9a")
            self.gnss_panel.set('lon', "---", "#5a7a9a")
            self.gnss_panel.set('alt', "---", "#5a7a9a")
            self.attspeed_panel.set('roll', "---", "#5a7a9a")
            self.attspeed_panel.set('pitch', "---", "#5a7a9a")
            self.attspeed_panel.set('yaw', "---", "#5a7a9a")
            self.attspeed_panel.set('speed', "---", "#5a7a9a")
            self.alert_panel.set('status', "DISCONNECTED", "#ff4444")
            self.alert_panel.set('alert_msg', "NO TELEMETRY", "#5a7a9a")
            self.conn_status.setText("DISCONNECTED")
            self.conn_status.setStyleSheet("color: #ff4444; font-weight: bold; font-family: Courier New; font-size: 12px; border: none;")
            self.console_view.refresh_logs()
            return

        # Check for link loss (heartbeat older than 3 seconds)
        last_hb = d.get('last_heartbeat_time', 0.0)
        is_link_lost = last_hb == 0.0 or (time.time() - last_hb) > 3.0

        if is_link_lost:
            val_color = "#5a7a9a"
            battery_color = "#5a7a9a"
            fix_color = "#5a7a9a"
            status_text = "LINK LOST"
            status_color = "#ff4444"
            alert_text = "NO TELEMETRY"
            alert_color = "#5a7a9a"
            self.conn_status.setText("LINK LOST")
            self.conn_status.setStyleSheet("color: #ff4444; font-weight: bold; font-family: Courier New; font-size: 12px; border: none;")
        else:
            val_color = "#00e5ff"
            battery_color = "#ff4444" if d['battery'] < 20 else "#00e5ff"
            fix_labels_colors = {0: "#ff4444", 1: "#ff4444", 2: "#ffaa00", 3: "#44ff88",
                                 4: "#44ff88", 5: "#44ff88", 6: "#44ff88"}
            fix_color = fix_labels_colors.get(d['fix_type'], "#ff4444")
            
            # Check warning alerts
            active_alerts = []
            if d['battery'] > 0:
                if d['battery'] < 10:
                    active_alerts.append("CRIT BATT")
                elif d['battery'] < 20:
                    active_alerts.append("LOW BATT")
            if d['voltage'] > 0.0 and d['voltage'] < 14.4:
                active_alerts.append("LOW VOLT")
            if d['fix_type'] < 3:
                active_alerts.append("NO 3D GPS")
            elif d['satellites'] < 6:
                active_alerts.append("WEAK GPS")
            
            prearm = d.get('prearm_fail', '')
            if prearm:
                active_alerts.append(f"PREARM: {prearm}")

            if active_alerts:
                status_text = "ARM BLOCKED"
                status_color = "#ff4444"
                alert_text = ", ".join(active_alerts)
                if len(alert_text) > 22:
                    alert_text = alert_text[:19] + "..."
                alert_color = "#ff4444"
            else:
                status_text = "SAFE"
                status_color = "#44ff88"
                alert_text = "NONE"
                alert_color = "#44ff88"

            self.conn_status.setText("CONNECTED")
            self.conn_status.setStyleSheet("color: #44ff88; font-weight: bold; font-family: Courier New; font-size: 12px; border: none;")

        # Update panels
        self.power_panel.set('battery', f"{d['battery']}%", battery_color)
        self.power_panel.set('voltage', f"{d['voltage']:.1f}V", val_color)

        fix_labels = {0: "NO FIX", 1: "NO FIX", 2: "2D", 3: "3D",
                      4: "DGPS", 5: "RTK-FLT", 6: "RTK-FIX"}
        fix = d['fix_type']
        self.gnss_panel.set('fix', fix_labels.get(fix, str(fix)), fix_color)
        self.gnss_panel.set('sats', str(d['satellites']), val_color)
        self.gnss_panel.set('lat', f"{d['lat']:.6f}", val_color)
        self.gnss_panel.set('lon', f"{d['lon']:.6f}", val_color)
        self.gnss_panel.set('alt', f"{d['alt']:.1f} m", val_color)

        self.attspeed_panel.set('roll', f"{math.degrees(d['roll']):.0f}\u00b0", val_color)
        self.attspeed_panel.set('pitch', f"{math.degrees(d['pitch']):.0f}\u00b0", val_color)
        yaw_deg = math.degrees(d['yaw']) % 360
        self.attspeed_panel.set('yaw', f"{yaw_deg:.0f}\u00b0", val_color)
        self.attspeed_panel.set('speed', f"{d['groundspeed']:.1f} m/s", val_color)

        # Toggle flashing state for warnings
        self._alert_flash_toggle = getattr(self, '_alert_flash_toggle', False)
        self._alert_flash_toggle = not self._alert_flash_toggle

        self.alert_panel.set('status', status_text, status_color)
        if alert_text != "NONE" and self._alert_flash_toggle and not is_link_lost:
            self.alert_panel.set('alert_msg', alert_text, "#ffffff") # flash to white text
        else:
            self.alert_panel.set('alert_msg', alert_text, alert_color)

        if not is_link_lost:
            if d['armed']:
                self.arm_btn.setText("DISARM")
                self.arm_btn.setStyleSheet(self._btn_style("#ff4444", "#0d1b2a"))
            else:
                self.arm_btn.setText("ARM")
                self.arm_btn.setStyleSheet(self._btn_style("#44ff88", "#0d1b2a"))
            
            self.map_view.update_position(d['lat'], d['lon'])
            self.plan_map_view.update_position(d['lat'], d['lon'])
            self.attitude_view.update_attitude(d['roll'], d['pitch'], d['yaw'])
            
            # Update active waypoint highlight on map views
            wp_idx = d.get('wp_current', -1)
            self.map_view.page().runJavaScript(f"if (typeof setActiveWaypoint === 'function') setActiveWaypoint({wp_idx});")
            self.plan_map_view.page().runJavaScript(f"if (typeof setActiveWaypoint === 'function') setActiveWaypoint({wp_idx});")

        wp_idx = d.get('wp_current', -1)
        total_items = self.wp_list.count()
        if wp_idx > 0 and total_items > 0:
            if wp_idx - 1 < total_items:
                self.wp_list.setCurrentRow(wp_idx - 1)
                item_text = self.wp_list.item(wp_idx - 1).text()
                active_name = item_text.split(':')[0]
                self.wp_progress_label.setText(f"Active: {active_name} (Item {wp_idx} / {total_items})")
            else:
                self.wp_progress_label.setText("Active: ---")
                self.wp_list.clearSelection()
        elif wp_idx == 0:
            self.wp_progress_label.setText("Active: Home / Preflight")
            self.wp_list.clearSelection()
        else:
            self.wp_progress_label.setText("Active: ---")
            self.wp_list.clearSelection()

        self.console_view.refresh_logs()

    def closeEvent(self, event):  # type: ignore
        if self.vehicle is not None and telemetry_data['armed']:
            reply = QMessageBox.question(
                self, 'Warning',
                "Drone is still ARMED! Are you sure you want to exit the GCS?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                print("Closing GCS...")
                self.disconnect_vehicle()
                event.accept()
            else:
                event.ignore()
        else:
            self.disconnect_vehicle()
            event.accept()


def launch_gui(vehicle=None):
    app = QApplication(sys.argv)
    window = GCSWindow(vehicle)
    window.show()
    app.exec()