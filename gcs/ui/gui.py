import sys
import math
import threading
import time
import pyqtgraph as pg
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout, QLabel, QFrame, QMessageBox,
    QPushButton, QComboBox, QSpinBox, QListWidget, QTabWidget,
    QLineEdit, QCheckBox, QProgressDialog, QGridLayout, QGraphicsDropShadowEffect
)
from PyQt6.QtCore import QTimer, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QColor
from gcs.telemetry import telemetry_data
from gcs.commands import arm, disarm, set_mode, takeoff, set_offboard_targets, reset_offboard_targets, stop_streamer
from gcs.ui.map_view import MapView
from gcs.ui.attitude_view import AttitudeView
from gcs.ui.console_view import ConsoleView
from gcs.ui.camera_view import CameraView
from gcs.ui.setup_view import SetupView
from gcs.ui.gauge import ArcGauge

THEME = {
    'bg': '#eef2f6',           # Softer cool gray-blue background for contrast
    'panel_bg': '#ffffff',     # Pure white cards
    'panel_border': '#e2e8f0', # Lighter, softer border (slate-200)
    'primary': '#0b57d0',      # Deep aerospace royal blue
    'success': '#0f9d58',      # Emerald green
    'warning': '#e37400',      # Muted amber/orange
    'danger': '#d93025',       # Crimson red
    'muted': '#64748b',        # Slate-500 for secondary labels
    'dark_text': '#0f172a',    # Slate-900 for readable value text
    'plot_bg': '#ffffff',      # Pure white plot background
}


class ConnectionWorker(QThread):
    connected = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, connection_string):
        super().__init__()
        self.connection_string = connection_string
        self.running = True

    def run(self):
        from gcs.connection import connect
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


class MapDownloadWorker(QThread):
    progress_signal = pyqtSignal(int, int) # current, total
    finished_signal = pyqtSignal(int, int, bool) # downloaded, skipped, success
    
    def __init__(self, bounds):
        super().__init__()
        self.bounds = bounds
        self._cancelled = False
        
    def run(self):
        from gcs.ui.tile_server import download_area_task
        
        def on_progress(curr, total):
            self.progress_signal.emit(curr, total)
            
        def on_finished(dl, skip, ok):
            self.finished_signal.emit(dl, skip, ok)
            
        def is_cancelled():
            return self._cancelled
            
        download_area_task(self.bounds, on_progress, on_finished, is_cancelled)
        
    def cancel(self):
        self._cancelled = True


class StatPanel(QFrame):
    """A titled panel holding labels and values in a clean 2-column grid layout with drop shadows."""
    def __init__(self, title):
        super().__init__()
        self.setObjectName("StatPanel")
        
        # Soft shadow to feel extremely premium
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(15)
        shadow.setColor(QColor(0, 0, 0, 15))
        shadow.setOffset(0, 4)
        self.setGraphicsEffect(shadow)

        self.setStyleSheet(f"""
            #StatPanel {{
                background-color: {THEME['panel_bg']};
                border: 1px solid {THEME['panel_border']};
                border-radius: 10px;
            }}
        """)
        
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(12, 10, 12, 10)
        self._layout.setSpacing(6)

        t = QLabel(title)
        t.setStyleSheet(f"color: {THEME['primary']}; font-size: 11px; font-weight: bold; border: none; background: transparent;")
        self._layout.addWidget(t)

        self.grid_widget = QWidget()
        self.grid_widget.setStyleSheet("background: transparent;")
        self.grid_layout = QGridLayout(self.grid_widget)
        self.grid_layout.setContentsMargins(0, 0, 0, 0)
        self.grid_layout.setSpacing(6)
        self._layout.addWidget(self.grid_widget)

        self.rows = {}
        self.current_row = 0
        self.current_col = 0

    def add_row(self, key, label):
        lbl = QLabel(label)
        lbl.setStyleSheet(f"color: {THEME['muted']}; font-size: 11px; border: none; background: transparent;")
        
        val = QLabel("---")
        val.setFont(QFont("Courier New", 12, QFont.Weight.Bold))
        val.setStyleSheet(f"color: {THEME['dark_text']}; border: none; background: transparent;")
        
        # Make the active alert message full-width spanning multiple columns
        if key == 'alert_msg':
            if self.current_col != 0:
                self.current_row += 1
                self.current_col = 0
                
            val.setAlignment(Qt.AlignmentFlag.AlignLeft)
            self.grid_layout.addWidget(lbl, self.current_row, 0)
            self.grid_layout.addWidget(val, self.current_row, 1, 1, 4)
            self.current_row += 1
            self.current_col = 0
        else:
            if self.current_col == 0:
                val.setAlignment(Qt.AlignmentFlag.AlignRight)
                self.grid_layout.addWidget(lbl, self.current_row, 0)
                self.grid_layout.addWidget(val, self.current_row, 1)
                self.grid_layout.setColumnStretch(1, 2)
                self.current_col = 1
            else:
                if self.current_row == 0:
                    spacer = QWidget()
                    spacer.setFixedWidth(16)
                    self.grid_layout.addWidget(spacer, 0, 2)
                val.setAlignment(Qt.AlignmentFlag.AlignRight)
                self.grid_layout.addWidget(lbl, self.current_row, 3)
                self.grid_layout.addWidget(val, self.current_row, 4)
                self.grid_layout.setColumnStretch(4, 2)
                self.current_row += 1
                self.current_col = 0

        self.rows[key] = val

    def set(self, key, text, color=None):
        if color is None:
            color = THEME['primary']
        if key in self.rows:
            self.rows[key].setText(text)
            self.rows[key].setStyleSheet(f"color: {color}; border: none; background: transparent;")


class PremiumViewContainer(QFrame):
    """A styled container to hold widgets like map view and attitude view with round borders and shadow."""
    def __init__(self, child_widget, name):
        super().__init__()
        self.setObjectName(name)
        self.setStyleSheet(f"""
            #{name} {{
                background-color: {THEME['panel_bg']};
                border: 1px solid {THEME['panel_border']};
                border-radius: 10px;
            }}
        """)
        
        # Shadow effect
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(15)
        shadow.setColor(QColor(0, 0, 0, 15))
        shadow.setOffset(0, 4)
        self.setGraphicsEffect(shadow)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.addWidget(child_widget)


class TelemetryPlotPanel(QFrame):
    """A live-updating plot panel showing historical telemetry trends."""
    def __init__(self):
        super().__init__()
        self.setObjectName("TelemetryPlotPanel")
        self.setStyleSheet(f"#TelemetryPlotPanel {{ background-color: {THEME['panel_bg']}; border-radius: 10px; border: 1px solid {THEME['panel_border']}; }}")
        
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(15)
        shadow.setColor(QColor(0, 0, 0, 15))
        shadow.setOffset(0, 4)
        self.setGraphicsEffect(shadow)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)

        t = QLabel("TELEMETRY HISTORICAL TRENDS")
        t.setStyleSheet(f"color: {THEME['primary']}; font-size: 11px; font-weight: bold; border: none; background: transparent;")
        layout.addWidget(t)

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground(THEME['plot_bg'])
        self.plot_widget.showGrid(x=True, y=True, alpha=0.15)
        self.plot_widget.getAxis('left').setPen(pg.mkPen(color=THEME['muted'], width=1))
        self.plot_widget.getAxis('bottom').setPen(pg.mkPen(color=THEME['muted'], width=1))
        self.plot_widget.getAxis('left').setTextPen(THEME['muted'])
        self.plot_widget.getAxis('bottom').setTextPen(THEME['muted'])

        self.alt_curve = self.plot_widget.plot(pen=pg.mkPen(THEME['primary'], width=1.5))
        self.speed_curve = self.plot_widget.plot(pen=pg.mkPen(THEME['warning'], width=1.5))
        layout.addWidget(self.plot_widget)

    def update_plots(self, times, alts, speeds):
        if not times:
            return
        self.alt_curve.setData(times, alts)
        self.speed_curve.setData(times, speeds)


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
            from gcs.commands import _ensure_streamer
            _ensure_streamer(self.vehicle)

        self.setWindowTitle("Python GCS")
        self.resize(1280, 800)
        
        # Create Tab Widget
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                border: 1px solid {THEME['panel_border']};
                background-color: {THEME['bg']};
                border-radius: 8px;
            }}
            QTabBar::tab {{
                background-color: {THEME['panel_border']};
                color: {THEME['muted']};
                font-family: Courier New;
                font-weight: bold;
                font-size: 13px;
                padding: 8px 20px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                border: 1px solid {THEME['panel_border']};
                border-bottom: none;
                margin-right: 4px;
            }}
            QTabBar::tab:selected {{
                background-color: {THEME['panel_bg']};
                color: {THEME['primary']};
                border: 2px solid {THEME['primary']};
                border-bottom: none;
            }}
            QTabBar::tab:hover {{
                background-color: #e2e8f0;
                color: {THEME['dark_text']};
            }}
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
        self.alert_panel.add_row('check_link', 'Link State')
        self.alert_panel.add_row('check_gps', 'GPS Checklist')
        self.alert_panel.add_row('check_batt', 'Power Checklist')

        # Attitude / Speed
        self.attspeed_panel = StatPanel("ATTITUDE / SPEED")
        self.attspeed_panel.add_row('roll', 'Roll')
        self.attspeed_panel.add_row('pitch', 'Pitch')
        self.attspeed_panel.add_row('yaw', 'Heading')
        self.attspeed_panel.add_row('speed', 'Speed')

        # Custom Arc Gauges
        self.alt_gauge = ArcGauge("ALTITUDE", "m", 0, 120, THEME['primary'])
        self.speed_gauge = ArcGauge("SPEED", "m/s", 0, 30, THEME['primary'])
        self.batt_gauge = ArcGauge("BATTERY", "%", 0, 100, THEME['success'])
        self.gps_gauge = ArcGauge("GPS SATS", "sats", 0, 20, THEME['primary'])

        # New Aircraft Status Panel
        self.aircraft_status_panel = StatPanel("AIRCRAFT STATUS")
        self.aircraft_status_panel.add_row('pitch', 'Pitch')
        self.aircraft_status_panel.add_row('roll', 'Roll')
        self.aircraft_status_panel.add_row('yaw', 'Yaw')
        self.aircraft_status_panel.add_row('mode', 'Mode')
        self.aircraft_status_panel.add_row('throttle', 'Throttle')

        # Arm button
        self.arm_btn = QPushButton("ARM")
        self.arm_btn.setFixedHeight(44)
        self.arm_btn.setFont(QFont("Courier New", 12, QFont.Weight.Bold))
        self.arm_btn.setStyleSheet(self._btn_style(THEME['success'], THEME['panel_bg']))
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
        self.mode_btn.setStyleSheet(self._btn_style(THEME['primary'], THEME['panel_bg']))
        self.mode_btn.clicked.connect(self.on_set_mode)

        self.alt_spin = QSpinBox()
        self.alt_spin.setRange(1, 100)
        self.alt_spin.setValue(10)
        self.alt_spin.setFixedHeight(34)
        self.alt_spin.setStyleSheet(self._input_style())

        self.takeoff_btn = QPushButton("TAKEOFF")
        self.takeoff_btn.setFixedHeight(34)
        self.takeoff_btn.setStyleSheet(self._btn_style(THEME['warning'], THEME['panel_bg']))
        self.takeoff_btn.clicked.connect(self.on_takeoff)

        self.rtl_btn = QPushButton("RTL")
        self.rtl_btn.setFixedHeight(34)
        self.rtl_btn.setStyleSheet(self._btn_style(THEME['primary'], THEME['panel_bg']))
        self.rtl_btn.clicked.connect(self.on_rtl)

        self.land_btn = QPushButton("LAND")
        self.land_btn.setFixedHeight(34)
        self.land_btn.setStyleSheet(self._btn_style(THEME['warning'], THEME['panel_bg']))
        self.land_btn.clicked.connect(self.on_land)

        # Manual movement (sim testing: tilt the drone, watch the 3D model)
        self.yawl_btn = QPushButton("YAW L")
        self.yawl_btn.setFixedHeight(34)
        self.yawl_btn.setStyleSheet(self._btn_style(THEME['primary'], THEME['panel_bg']))
        self.yawl_btn.clicked.connect(self.on_yaw_left)

        self.fwd_btn = QPushButton("FORWARD")
        self.fwd_btn.setFixedHeight(34)
        self.fwd_btn.setStyleSheet(self._btn_style(THEME['success'], THEME['panel_bg']))
        self.fwd_btn.clicked.connect(self.on_forward)

        self.yawr_btn = QPushButton("YAW R")
        self.yawr_btn.setFixedHeight(34)
        self.yawr_btn.setStyleSheet(self._btn_style(THEME['primary'], THEME['panel_bg']))
        self.yawr_btn.clicked.connect(self.on_yaw_right)

        self.hover_btn = QPushButton("HOVER")
        self.hover_btn.setFixedHeight(34)
        self.hover_btn.setStyleSheet(self._btn_style(THEME['warning'], THEME['panel_bg']))
        self.hover_btn.clicked.connect(self.on_hover)

        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet(f"color: {THEME['muted']}; font-size: 11px; border: none; background: transparent;")

        # Action panel container
        self.action_panel = QFrame()
        self.action_panel.setObjectName("ActionPanel")
        self.action_panel.setStyleSheet(f"#ActionPanel {{ background-color: {THEME['panel_bg']}; border: 1px solid {THEME['panel_border']}; border-radius: 10px; }}")
        
        # Soft shadow for ActionPanel
        shadow_ap = QGraphicsDropShadowEffect(self)
        shadow_ap.setBlurRadius(15)
        shadow_ap.setColor(QColor(0, 0, 0, 15))
        shadow_ap.setOffset(0, 4)
        self.action_panel.setGraphicsEffect(shadow_ap)
        
        ap = QVBoxLayout(self.action_panel)
        ap.setContentsMargins(12, 10, 12, 10)
        ap.setSpacing(8)
        ap_title = QLabel("ACTION BUTTONS")
        ap_title.setStyleSheet(f"color: {THEME['primary']}; font-size: 11px; font-weight: bold; border: none; background: transparent;")
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
        
        self.kb_checkbox = QCheckBox("Enable Keyboard Flight (W/S/A/D/Q/E/I/K)")
        self.kb_checkbox.setStyleSheet(f"""
            QCheckBox {{
                color: {THEME['muted']};
                font-family: Courier New;
                font-size: 11px;
                background: transparent;
            }}
            QCheckBox::indicator {{
                width: 13px;
                height: 13px;
                border: 1px solid {THEME['panel_border']};
                background: {THEME['panel_bg']};
            }}
            QCheckBox::indicator:checked {{
                background: {THEME['primary']};
                border-color: {THEME['primary']};
            }}
        """)
        ap.addWidget(self.kb_checkbox)
        ap.addWidget(self.status_label)

        # Mission planning panel container
        self.mission_panel = QFrame()
        self.mission_panel.setObjectName("MissionPanel")
        self.mission_panel.setStyleSheet(f"#MissionPanel {{ background-color: {THEME['panel_bg']}; border: 1px solid {THEME['panel_border']}; border-radius: 10px; }}")
        
        # Soft shadow for MissionPanel
        shadow_mp = QGraphicsDropShadowEffect(self)
        shadow_mp.setBlurRadius(15)
        shadow_mp.setColor(QColor(0, 0, 0, 15))
        shadow_mp.setOffset(0, 4)
        self.mission_panel.setGraphicsEffect(shadow_mp)
        
        mp = QVBoxLayout(self.mission_panel)
        mp.setContentsMargins(12, 10, 12, 10)
        mp.setSpacing(6)
        
        mp_title = QLabel("MISSION PLANNING")
        mp_title.setStyleSheet(f"color: {THEME['primary']}; font-size: 11px; font-weight: bold; border: none; background: transparent;")
        mp.addWidget(mp_title)
        
        self.wp_list = QListWidget()
        self.wp_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {THEME['panel_bg']}; color: {THEME['primary']};
                border: 1px solid {THEME['panel_border']}; border-radius: 4px;
                font-family: Courier New; font-size: 11px;
            }}
        """)
        mp.addWidget(self.wp_list)
        
        self.wp_progress_label = QLabel("Active Waypoint: ---")
        self.wp_progress_label.setStyleSheet(f"color: {THEME['primary']}; font-family: Courier New; font-size: 11px; border: none; background: transparent;")
        mp.addWidget(self.wp_progress_label)
        
        m_row = QHBoxLayout()
        m_row.setSpacing(6)
        
        self.sync_btn = QPushButton("SYNC MAP")
        self.sync_btn.setFixedHeight(30)
        self.sync_btn.setStyleSheet(self._btn_style(THEME['primary'], THEME['panel_bg']))
        self.sync_btn.clicked.connect(self.on_sync_map)
        
        self.upload_btn = QPushButton("UPLOAD")
        self.upload_btn.setFixedHeight(30)
        self.upload_btn.setStyleSheet(self._btn_style(THEME['success'], THEME['panel_bg']))
        self.upload_btn.clicked.connect(self.on_upload_mission)

        self.clear_btn = QPushButton("CLEAR")
        self.clear_btn.setFixedHeight(30)
        self.clear_btn.setStyleSheet(self._btn_style(THEME['danger'], THEME['panel_bg']))
        self.clear_btn.clicked.connect(self.on_clear_mission)
        
        m_row.addWidget(self.sync_btn)
        m_row.addWidget(self.upload_btn)
        m_row.addWidget(self.clear_btn)
        mp.addLayout(m_row)

        m_row2 = QHBoxLayout()
        m_row2.setSpacing(6)
        
        self.import_btn = QPushButton("IMPORT")
        self.import_btn.setFixedHeight(30)
        self.import_btn.setStyleSheet(self._btn_style(THEME['primary'], THEME['panel_bg']))
        self.import_btn.clicked.connect(self.on_import_mission)
        
        self.export_btn = QPushButton("EXPORT")
        self.export_btn.setFixedHeight(30)
        self.export_btn.setStyleSheet(self._btn_style(THEME['primary'], THEME['panel_bg']))
        self.export_btn.clicked.connect(self.on_export_mission)
        
        m_row2.addWidget(self.import_btn)
        m_row2.addWidget(self.export_btn)
        mp.addLayout(m_row2)

        self.start_btn = QPushButton("START MISSION")
        self.start_btn.setFixedHeight(34)
        self.start_btn.setStyleSheet(self._btn_style(THEME['success'], THEME['panel_bg']))
        self.start_btn.clicked.connect(self.on_start_mission)
        mp.addWidget(self.start_btn)

        # ===== FLY Tab Layout =====
        fly_widget = QWidget()
        fly_widget.setObjectName("FlyTab")
        fly_widget.setStyleSheet(f"#FlyTab {{ background-color: {THEME['bg']}; }}")
        fly_layout = QVBoxLayout(fly_widget)
        fly_layout.setContentsMargins(6, 6, 6, 6)
        fly_layout.setSpacing(6)

        # Initialize telemetry historical lists
        self.history_time = []
        self.history_alt = []
        self.history_speed = []
        self.start_time = time.time()
        self.held_keys = set()

        # Real-time Plotting
        self.plot_panel = TelemetryPlotPanel()

        # Rebuild FLY tab into a 3-column dashboard
        dashboard_layout = QHBoxLayout()
        dashboard_layout.setSpacing(8)

        # LEFT column: Arm, Action Buttons, and Safety & Alerts
        left_col = QVBoxLayout()
        left_col.setSpacing(8)
        left_col.addWidget(self.alert_panel, stretch=0)
        left_col.addWidget(self.action_panel, stretch=0)
        left_col.addWidget(self.arm_btn, stretch=0)
        left_col.addStretch(1)

        # CENTER column: Map, Download button, and Plot panel below it
        center_col = QVBoxLayout()
        center_col.setSpacing(6)
        
        self.map_container_widget = PremiumViewContainer(self.map_view, "MapContainer")
        center_col.addWidget(self.map_container_widget, stretch=5)
        
        map_bar = QHBoxLayout()
        self.download_map_btn = QPushButton("DOWNLOAD OFFLINE MAP")
        self.download_map_btn.setFixedHeight(28)
        self.download_map_btn.setStyleSheet(self._btn_style(THEME['primary'], THEME['panel_bg']))
        self.download_map_btn.clicked.connect(self.on_download_offline_area)
        map_bar.addWidget(self.download_map_btn)
        center_col.addLayout(map_bar)
        
        center_col.addWidget(self.plot_panel, stretch=2)

        # RIGHT column: Telemetry Gauges, Aircraft Status, and 3D Attitude
        right_col = QVBoxLayout()
        right_col.setSpacing(8)

        # TELEMETRY card with 2x2 grid of gauges
        self.telemetry_card = QFrame()
        self.telemetry_card.setObjectName("TelemetryCard")
        self.telemetry_card.setStyleSheet(f"""
            #TelemetryCard {{
                background-color: {THEME['panel_bg']};
                border: 1px solid {THEME['panel_border']};
                border-radius: 10px;
            }}
        """)
        shadow_tc = QGraphicsDropShadowEffect(self)
        shadow_tc.setBlurRadius(15)
        shadow_tc.setColor(QColor(0, 0, 0, 15))
        shadow_tc.setOffset(0, 4)
        self.telemetry_card.setGraphicsEffect(shadow_tc)
        
        tc_layout = QVBoxLayout(self.telemetry_card)
        tc_layout.setContentsMargins(12, 10, 12, 10)
        tc_layout.setSpacing(6)
        
        tc_title = QLabel("TELEMETRY")
        tc_title.setStyleSheet(f"color: {THEME['primary']}; font-size: 11px; font-weight: bold; border: none; background: transparent;")
        tc_layout.addWidget(tc_title)
        
        grid_widget = QWidget()
        grid_widget.setStyleSheet("background: transparent;")
        grid_layout = QGridLayout(grid_widget)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        grid_layout.setSpacing(8)
        
        grid_layout.addWidget(self.alt_gauge, 0, 0)
        grid_layout.addWidget(self.speed_gauge, 0, 1)
        grid_layout.addWidget(self.batt_gauge, 1, 0)
        grid_layout.addWidget(self.gps_gauge, 1, 1)
        tc_layout.addWidget(grid_widget)

        right_col.addWidget(self.telemetry_card, stretch=4)
        right_col.addWidget(self.aircraft_status_panel, stretch=0)
        
        self.attitude_container_widget = PremiumViewContainer(self.attitude_view, "AttitudeContainer")
        right_col.addWidget(self.attitude_container_widget, stretch=3)

        # Assemble columns into dashboard
        dashboard_layout.addLayout(left_col, stretch=2)
        dashboard_layout.addLayout(center_col, stretch=5)
        dashboard_layout.addLayout(right_col, stretch=3)

        fly_layout.addLayout(dashboard_layout, stretch=8)
        
        # Horizontal slim strip for console at the bottom
        self.console_view.setFixedHeight(110)
        fly_layout.addWidget(self.console_view, stretch=0)

        self.tabs.addTab(fly_widget, "FLY")

        # ===== PLAN Tab Layout =====
        plan_widget = QWidget()
        plan_widget.setObjectName("PlanTab")
        plan_widget.setStyleSheet(f"#PlanTab {{ background-color: {THEME['bg']}; }}")
        plan_layout = QHBoxLayout(plan_widget)
        plan_layout.setContentsMargins(8, 8, 8, 8)
        plan_layout.setSpacing(8)
        
        self.plan_map_view = MapView()
        self.plan_map_container = PremiumViewContainer(self.plan_map_view, "PlanMapContainer")
        plan_layout.addWidget(self.plan_map_container, stretch=3)
        plan_layout.addWidget(self.mission_panel, stretch=1)
        self.tabs.addTab(plan_widget, "PLAN")

        # ===== CAMERAS Tab Layout =====
        cameras_widget = QWidget()
        cameras_widget.setObjectName("CamerasTab")
        cameras_widget.setStyleSheet(f"#CamerasTab {{ background-color: {THEME['bg']}; }}")
        cameras_layout = QHBoxLayout(cameras_widget)
        cameras_layout.setContentsMargins(8, 8, 8, 8)
        cameras_layout.setSpacing(8)
        cameras_layout.addWidget(self.front_cam, stretch=1)
        cameras_layout.addWidget(self.bottom_cam, stretch=1)
        self.tabs.addTab(cameras_widget, "CAMERAS")

        # ===== SETUP Tab Layout =====
        self.setup_view = SetupView(self.vehicle)
        self.setup_view.setObjectName("SetupTab")
        self.setup_view.setStyleSheet(f"#SetupTab {{ background-color: {THEME['bg']}; }}")
        self.tabs.addTab(self.setup_view, "SETUP")

        # ===== Assemble Central Layout =====
        root = QWidget()
        root.setStyleSheet(f"background-color: {THEME['bg']};")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(8, 8, 8, 8)

        # Connection Panel
        self.conn_panel = QFrame()
        self.conn_panel.setObjectName("ConnPanel")
        self.conn_panel.setStyleSheet(f"#ConnPanel {{ background-color: {THEME['panel_bg']}; border-radius: 10px; border: 1px solid {THEME['panel_border']}; }}")
        self.conn_panel.setFixedHeight(50)
        
        # Soft shadow for ConnPanel
        shadow_conn = QGraphicsDropShadowEffect(self)
        shadow_conn.setBlurRadius(12)
        shadow_conn.setColor(QColor(0, 0, 0, 15))
        shadow_conn.setOffset(0, 3)
        self.conn_panel.setGraphicsEffect(shadow_conn)
        
        conn_layout = QHBoxLayout(self.conn_panel)
        conn_layout.setContentsMargins(15, 5, 15, 5)
        conn_layout.setSpacing(10)
        
        conn_lbl = QLabel("CONNECTION:")
        conn_lbl.setStyleSheet(f"color: {THEME['primary']}; font-family: Courier New; font-weight: bold; font-size: 12px; border: none; background: transparent;")
        conn_layout.addWidget(conn_lbl)
        
        self.conn_input = QLineEdit()
        self.conn_input.setText("udpin:0.0.0.0:14540")
        self.conn_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {THEME['panel_bg']}; color: {THEME['dark_text']};
                border: 1px solid {THEME['panel_border']}; border-radius: 4px;
                padding: 4px 8px; font-family: Courier New; font-size: 12px;
            }}
        """)
        conn_layout.addWidget(self.conn_input, stretch=1)
        
        self.conn_btn = QPushButton("CONNECT")
        self.conn_btn.setFixedWidth(120)
        self.conn_btn.setFixedHeight(30)
        self.conn_btn.setStyleSheet(self._btn_style(THEME['primary'], THEME['panel_bg']))
        self.conn_btn.clicked.connect(self.on_connect_toggle)
        conn_layout.addWidget(self.conn_btn)
        
        self.conn_status = QLabel("DISCONNECTED")
        self.conn_status.setStyleSheet(f"color: {THEME['danger']}; font-weight: bold; font-family: Courier New; font-size: 12px; border: none; background: transparent;")
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
            QPushButton:disabled {{ border-color: #cbd5e1; color: #cbd5e1; }}
        """

    def _input_style(self):
        return f"""
            QComboBox, QSpinBox {{
                background-color: {THEME['panel_bg']}; color: {THEME['dark_text']};
                border: 1px solid {THEME['panel_border']}; border-radius: 4px;
                padding: 4px 8px; font-family: Courier New; font-size: 12px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {THEME['panel_bg']}; color: {THEME['dark_text']};
                selection-background-color: {THEME['panel_border']};
            }}
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
            self.conn_status.setStyleSheet(f"color: {THEME['warning']}; font-weight: bold; font-family: Courier New; font-size: 12px; border: none;")
            
            self.conn_worker = ConnectionWorker(connection_string)
            self.conn_worker.connected.connect(self.on_connected)
            self.conn_worker.failed.connect(self.on_connection_failed)
            self.conn_worker.start()

    def on_connected(self, vehicle):
        self.vehicle = vehicle
        self.setup_view.set_vehicle(vehicle)
        
        from gcs.commands import _ensure_streamer
        _ensure_streamer(self.vehicle)
        
        from gcs.connection import request_telemetry
        from gcs.telemetry import read_telemetry
        try:
            request_telemetry(self.vehicle)
            import gcs.telemetry as telemetry
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
        from gcs.commands import request_all_parameters
        threading.Thread(target=request_all_parameters, args=(self.vehicle,), daemon=True).start()

    def on_connection_failed(self, error_msg):
        self.set_status(f"Connection failed: {error_msg}")
        self.disconnect_vehicle()

    def disconnect_vehicle(self):
        if self.conn_worker is not None:
            self.conn_worker.stop()
            self.conn_worker.wait()
            self.conn_worker = None
            
        import gcs.telemetry as telemetry
        telemetry.telemetry_active = False
        telemetry_data['last_heartbeat_time'] = 0.0
        telemetry_data['prearm_fail'] = ""
        
        stop_streamer()
        reset_offboard_targets()
        
        if self.vehicle is not None:
            try:
                self.vehicle.close()
            except Exception:
                pass
            self.vehicle = None
            
        if hasattr(self, 'setup_view'):
            self.setup_view.set_vehicle(None)
        
        self.history_time = []
        self.history_alt = []
        self.history_speed = []
        self.start_time = time.time()
        self.held_keys.clear()
        if hasattr(self, 'plot_panel'):
            self.plot_panel.plot_widget.clear()
            self.plot_panel.alt_curve = self.plot_panel.plot_widget.plot(pen=pg.mkPen(THEME['primary'], width=1.5))
            self.plot_panel.speed_curve = self.plot_panel.plot_widget.plot(pen=pg.mkPen(THEME['warning'], width=1.5))

        self.set_status("Disconnected.")
        self.conn_btn.setText("CONNECT")
        self.conn_btn.setEnabled(True)
        self.conn_input.setEnabled(True)
        self.conn_status.setText("DISCONNECTED")
        self.conn_status.setStyleSheet(f"color: {THEME['danger']}; font-weight: bold; font-family: Courier New; font-size: 12px; border: none;")
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
        self.import_btn.setEnabled(enabled)
        self.export_btn.setEnabled(enabled)
        self.kb_checkbox.setEnabled(enabled)

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
        from gcs.commands import upload_mission
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

    def on_export_mission(self):
        if not self.waypoints and not self.takeoff_point and not self.landing_point:
            self.set_status("Export failed: Synced map is empty!")
            # Fallback to sync first
            self.on_sync_map()
            if not self.waypoints and not self.takeoff_point and not self.landing_point:
                return
            
        import json
        from PyQt6.QtWidgets import QFileDialog
        filename, _ = QFileDialog.getSaveFileName(
            self, "Export Mission Plan", "", "Mission Files (*.plan);;JSON Files (*.json)"
        )
        if not filename:
            return
        mission_dict = {
            "takeoff": self.takeoff_point,
            "waypoints": self.waypoints,
            "landing": self.landing_point
        }
        try:
            with open(filename, 'w') as f:
                json.dump(mission_dict, f, indent=4)
            self.set_status(f"Mission exported to {filename}")
        except Exception as e:
            self.set_status(f"Export failed: {e}")

    def on_import_mission(self):
        import json
        from PyQt6.QtWidgets import QFileDialog
        filename, _ = QFileDialog.getOpenFileName(
            self, "Import Mission Plan", "", "Mission Files (*.plan);;JSON Files (*.json)"
        )
        if not filename:
            return
        try:
            with open(filename, 'r') as f:
                mission_dict = json.load(f)
        except Exception as e:
            self.set_status(f"Import failed: {e}")
            return
        takeoff = mission_dict.get("takeoff")
        wps = mission_dict.get("waypoints", [])
        landing = mission_dict.get("landing")
        
        self.takeoff_point = takeoff
        self.waypoints = wps
        self.landing_point = landing
        
        self.map_view.import_mission(takeoff, wps, landing)
        self.plan_map_view.import_mission(takeoff, wps, landing)
        
        self.wp_list.clear()
        if takeoff:
            self.wp_list.addItem(f"TAKEOFF: {takeoff[0]:.6f}, {takeoff[1]:.6f}")
        for idx, wp in enumerate(wps):
            self.wp_list.addItem(f"WP {idx+1}: {wp[0]:.6f}, {wp[1]:.6f}")
        if landing:
            self.wp_list.addItem(f"LAND: {landing[0]:.6f}, {landing[1]:.6f}")
            
        total_items = (1 if takeoff else 0) + len(wps) + (1 if landing else 0)
        self.set_status(f"Imported mission: {total_items} items.")

    def on_download_offline_area(self):
        # Fetch bounds from map_view
        self.map_view.get_map_bounds(self.on_bounds_retrieved)
        
    def on_bounds_retrieved(self, bounds_json):
        if not bounds_json:
            self.set_status("Download failed: Map bounds not loaded yet.")
            return
            
        import json
        try:
            bounds = json.loads(bounds_json)
        except Exception as e:
            self.set_status(f"Download failed: Could not parse bounds {e}")
            return
            
        # Create and configure progress dialog
        self.progress_dialog = QProgressDialog("Calculating offline tiles...", "Cancel", 0, 100, self)
        self.progress_dialog.setWindowTitle("Offline Map Downloader")
        self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress_dialog.setMinimumDuration(0)
        self.progress_dialog.setAutoClose(True)
        self.progress_dialog.setValue(0)
        
        # Start background thread
        self.download_worker = MapDownloadWorker(bounds)
        self.download_worker.progress_signal.connect(self.on_download_progress)
        self.download_worker.finished_signal.connect(self.on_download_finished)
        
        # Handle cancel button clicked
        self.progress_dialog.canceled.connect(self.download_worker.cancel)
        
        self.download_map_btn.setEnabled(False)
        self.download_worker.start()
        
    def on_download_progress(self, curr, total):
        if hasattr(self, 'progress_dialog') and self.progress_dialog:
            self.progress_dialog.setMaximum(total)
            self.progress_dialog.setValue(curr)
            self.progress_dialog.setLabelText(f"Downloading zoom 13-18 tile cache: {curr} of {total}...")
            
    def on_download_finished(self, dl, skip, ok):
        self.download_map_btn.setEnabled(True)
        if hasattr(self, 'progress_dialog') and self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None
            
        if ok:
            QMessageBox.information(
                self, "Success",
                f"Offline Map Download Complete!\n\nDownloaded: {dl} tiles\nSkipped (already cached): {skip} tiles\n\nThese tiles are now cached on disk and will render offline."
            )
            self.set_status(f"Offline Map Download Success: {dl} downloaded, {skip} cached.")
        else:
            self.set_status("Offline Map Download cancelled or encountered errors.")

    # ---- Keyboard Offboard Flight Controls ----
    def keyPressEvent(self, event):
        if not hasattr(self, 'kb_checkbox') or not self.kb_checkbox.isChecked() or not self.vehicle:
            super().keyPressEvent(event)
            return
        if self.conn_input.hasFocus() or self.setup_view.search_bar.hasFocus():
            super().keyPressEvent(event)
            return
        key = event.key()
        if key in [Qt.Key.Key_W, Qt.Key.Key_S, Qt.Key.Key_A, Qt.Key.Key_D, 
                   Qt.Key.Key_Q, Qt.Key.Key_E, Qt.Key.Key_I, Qt.Key.Key_K]:
            self.held_keys.add(key)
            self.update_keyboard_offboard()
            event.accept()
        elif key == Qt.Key.Key_Space or key == Qt.Key.Key_H:
            self.held_keys.clear()
            self.update_keyboard_offboard()
            event.accept()
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if not hasattr(self, 'kb_checkbox') or not self.kb_checkbox.isChecked() or not self.vehicle:
            super().keyReleaseEvent(event)
            return
        if event.isAutoRepeat():
            event.accept()
            return
        key = event.key()
        if key in self.held_keys:
            self.held_keys.remove(key)
            self.update_keyboard_offboard()
            event.accept()
        else:
            super().keyReleaseEvent(event)

    def focusOutEvent(self, event):
        if hasattr(self, 'held_keys') and self.held_keys:
            self.held_keys.clear()
            self.update_keyboard_offboard()
        super().focusOutEvent(event)

    def changeEvent(self, event):
        from PyQt6.QtCore import QEvent
        if event.type() == QEvent.Type.ActivationChange:
            if not self.isActiveWindow():
                if hasattr(self, 'held_keys') and self.held_keys:
                    self.held_keys.clear()
                    self.update_keyboard_offboard()
        super().changeEvent(event)

    def update_keyboard_offboard(self):
        if not self.vehicle:
            return
        vx = 0.0
        vy = 0.0
        vz = 0.0
        yaw_rate = 0.0
        if Qt.Key.Key_W in self.held_keys:
            vx += 2.0
        if Qt.Key.Key_S in self.held_keys:
            vx -= 2.0
        if Qt.Key.Key_A in self.held_keys:
            vy -= 2.0
        if Qt.Key.Key_D in self.held_keys:
            vy += 2.0
        if Qt.Key.Key_Q in self.held_keys:
            yaw_rate -= 0.5
        if Qt.Key.Key_E in self.held_keys:
            yaw_rate += 0.5
        if Qt.Key.Key_I in self.held_keys:
            vz -= 1.5
        if Qt.Key.Key_K in self.held_keys:
            vz += 1.5
            
        self.ensure_offboard()
        set_offboard_targets(vx=vx, vy=vy, vz=vz, yaw_rate=yaw_rate)
        if any(k in self.held_keys for k in [Qt.Key.Key_W, Qt.Key.Key_S, Qt.Key.Key_A, Qt.Key.Key_D, Qt.Key.Key_Q, Qt.Key.Key_E, Qt.Key.Key_I, Qt.Key.Key_K]):
            self.set_status(f"Keyboard flying: vx={vx:.1f}, vy={vy:.1f}, vz={vz:.1f}, yaw_rate={yaw_rate:.1f}")
        else:
            self.set_status("Keyboard offboard: Hover")

    # ---- live refresh ----
    def refresh(self):
        import time
        d = telemetry_data

        if not self.vehicle:
            self.power_panel.set('battery', "---", THEME['muted'])
            self.power_panel.set('voltage', "---", THEME['muted'])
            self.gnss_panel.set('fix', "DISCONNECTED", THEME['danger'])
            self.gnss_panel.set('sats', "---", THEME['muted'])
            self.gnss_panel.set('lat', "---", THEME['muted'])
            self.gnss_panel.set('lon', "---", THEME['muted'])
            self.gnss_panel.set('alt', "---", THEME['muted'])
            self.attspeed_panel.set('roll', "---", THEME['muted'])
            self.attspeed_panel.set('pitch', "---", THEME['muted'])
            self.attspeed_panel.set('yaw', "---", THEME['muted'])
            self.attspeed_panel.set('speed', "---", THEME['muted'])
            self.alert_panel.set('status', "DISCONNECTED", THEME['danger'])
            self.alert_panel.set('alert_msg', "NO TELEMETRY", THEME['muted'])
            self.alert_panel.set('check_link', "DISCONNECTED", THEME['danger'])
            self.alert_panel.set('check_gps', "NO TELEMETRY", THEME['muted'])
            self.alert_panel.set('check_batt', "NO TELEMETRY", THEME['muted'])
            
            # Reset aircraft status panel
            self.aircraft_status_panel.set('pitch', "---", THEME['muted'])
            self.aircraft_status_panel.set('roll', "---", THEME['muted'])
            self.aircraft_status_panel.set('yaw', "---", THEME['muted'])
            self.aircraft_status_panel.set('mode', "---", THEME['muted'])
            self.aircraft_status_panel.set('throttle', "---", THEME['muted'])
            
            # Reset gauges
            self.alt_gauge.set_value(0.0)
            self.alt_gauge.set_accent(THEME['muted'])
            self.speed_gauge.set_value(0.0)
            self.speed_gauge.set_accent(THEME['muted'])
            self.batt_gauge.set_value(0.0)
            self.batt_gauge.set_accent(THEME['muted'])
            self.gps_gauge.set_value(0.0)
            self.gps_gauge.set_accent(THEME['muted'])
            
            self.conn_status.setText("DISCONNECTED")
            self.conn_status.setStyleSheet(f"color: {THEME['danger']}; font-weight: bold; font-family: Courier New; font-size: 12px; border: none;")
            self.console_view.refresh_logs()
            return

        # Check for link loss (heartbeat older than 3 seconds)
        last_hb = d.get('last_heartbeat_time', 0.0)
        is_link_lost = last_hb == 0.0 or (time.time() - last_hb) > 3.0

        if is_link_lost:
            val_color = THEME['muted']
            battery_color = THEME['muted']
            fix_color = THEME['muted']
            status_text = "LINK LOST"
            status_color = THEME['danger']
            alert_text = "NO TELEMETRY"
            alert_color = THEME['muted']
            self.alert_panel.set('check_link', "LOST", THEME['danger'])
            self.alert_panel.set('check_gps', "NO TELEMETRY", THEME['muted'])
            self.alert_panel.set('check_batt', "NO TELEMETRY", THEME['muted'])
            
            # Link lost gauges
            self.alt_gauge.set_value(d.get('alt', 0.0))
            self.alt_gauge.set_accent(THEME['muted'])
            self.speed_gauge.set_value(d.get('groundspeed', 0.0))
            self.speed_gauge.set_accent(THEME['muted'])
            self.batt_gauge.set_value(d.get('battery', 0))
            self.batt_gauge.set_accent(THEME['muted'])
            self.gps_gauge.set_value(d.get('satellites', 0))
            self.gps_gauge.set_accent(THEME['muted'])
            
            self.aircraft_status_panel.set('pitch', "---", THEME['muted'])
            self.aircraft_status_panel.set('roll', "---", THEME['muted'])
            self.aircraft_status_panel.set('yaw', "---", THEME['muted'])
            self.aircraft_status_panel.set('mode', "---", THEME['muted'])
            self.aircraft_status_panel.set('throttle', "---", THEME['muted'])
            
            self.conn_status.setText("LINK LOST")
            self.conn_status.setStyleSheet(f"color: {THEME['danger']}; font-weight: bold; font-family: Courier New; font-size: 12px; border: none;")
        else:
            val_color = THEME['dark_text']
            battery_color = THEME['danger'] if d['battery'] < 20 else THEME['dark_text']
            fix_labels_colors = {0: THEME['danger'], 1: THEME['danger'], 2: THEME['warning'], 3: THEME['success'],
                                 4: THEME['success'], 5: THEME['success'], 6: THEME['success']}
            fix_color = fix_labels_colors.get(d['fix_type'], THEME['danger'])
            
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
                status_color = THEME['danger']
                alert_text = ", ".join(active_alerts)
                if len(alert_text) > 22:
                    alert_text = alert_text[:19] + "..."
                alert_color = THEME['danger']
            else:
                status_text = "SAFE"
                status_color = THEME['success']
                alert_text = "NONE"
                alert_color = THEME['success']

            self.alert_panel.set('check_link', "OK", THEME['success'])
            gps_ok = d['fix_type'] >= 3
            gps_text = "3D FIX" if gps_ok else f"NO 3D ({d['fix_type']}D)"
            gps_color = THEME['success'] if gps_ok else THEME['danger']
            self.alert_panel.set('check_gps', gps_text, gps_color)
            
            if d['battery'] >= 30:
                batt_text = "OK"
                batt_color = THEME['success']
            elif d['battery'] >= 20:
                batt_text = "LOW"
                batt_color = THEME['warning']
            else:
                batt_text = "CRIT"
                batt_color = THEME['danger']
            self.alert_panel.set('check_batt', f"{batt_text} ({d['battery']}%)", batt_color)

            self.conn_status.setText("CONNECTED")
            self.conn_status.setStyleSheet(f"color: {THEME['success']}; font-weight: bold; font-family: Courier New; font-size: 12px; border: none;")

            # Record history for plotting
            elapsed = time.time() - self.start_time
            self.history_time.append(elapsed)
            self.history_alt.append(d.get('alt', 0.0))
            self.history_speed.append(d.get('groundspeed', 0.0))
            if len(self.history_time) > 120:
                self.history_time.pop(0)
                self.history_alt.pop(0)
                self.history_speed.pop(0)
            self.plot_panel.update_plots(self.history_time, self.history_alt, self.history_speed)

            # Update Gauges
            alt_accent = THEME['primary']
            speed_accent = THEME['primary']
            if d['battery'] < 10:
                batt_accent = THEME['danger']
            elif d['battery'] < 20:
                batt_accent = THEME['warning']
            else:
                batt_accent = THEME['success']
            gps_accent = fix_color
            
            self.alt_gauge.set_value(d.get('alt', 0.0))
            self.alt_gauge.set_accent(alt_accent)
            self.speed_gauge.set_value(d.get('groundspeed', 0.0))
            self.speed_gauge.set_accent(speed_accent)
            self.batt_gauge.set_value(d.get('battery', 0))
            self.batt_gauge.set_accent(batt_accent)
            self.gps_gauge.set_value(d.get('satellites', 0))
            self.gps_gauge.set_accent(gps_accent)

            # Update new Aircraft Status panel
            self.aircraft_status_panel.set('pitch', f"{math.degrees(d['pitch']):.0f}\u00b0", val_color)
            self.aircraft_status_panel.set('roll', f"{math.degrees(d['roll']):.0f}\u00b0", val_color)
            yaw_deg = math.degrees(d['yaw']) % 360
            self.aircraft_status_panel.set('yaw', f"{yaw_deg:.0f}\u00b0", val_color)
            self.aircraft_status_panel.set('mode', str(d.get('mode', 'UNKNOWN')), val_color)
            self.aircraft_status_panel.set('throttle', f"{d.get('throttle', 0)}%", val_color)

        # Update panels (retaining original functionality)
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
            self.alert_panel.set('alert_msg', alert_text, THEME['dark_text']) # flash text
        else:
            self.alert_panel.set('alert_msg', alert_text, alert_color)

        if not is_link_lost:
            if d['armed']:
                self.arm_btn.setText("DISARM")
                self.arm_btn.setStyleSheet(self._btn_style(THEME['danger'], THEME['panel_bg']))
            else:
                self.arm_btn.setText("ARM")
                self.arm_btn.setStyleSheet(self._btn_style(THEME['success'], THEME['panel_bg']))
            
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