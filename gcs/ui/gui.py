import sys
import math
import threading
import time
import os
import pyqtgraph as pg
from typing import List, Optional, Tuple, Dict, Any

from PyQt6.QtWidgets import (
    QDialog, QDoubleSpinBox, QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout, QLabel, QFrame, QMessageBox,
    QPushButton, QComboBox, QSpinBox, QListWidget, QTabWidget,
    QLineEdit, QCheckBox, QProgressDialog, QGridLayout,
    QGraphicsDropShadowEffect, QInputDialog, QFileDialog
)
try:
    from PyQt6.QtTextToSpeech import QTextToSpeech
    TTS_AVAILABLE = True
except ImportError:
    TTS_AVAILABLE = False

from PyQt6.QtCore import QObject, QTimer, Qt, QThread, pyqtSignal, QEvent
from PyQt6.QtGui import QFont, QColor

import gcs.telemetry as telemetry
from gcs.telemetry import (
    telemetry_data, is_vehicle_airborne, create_new_session,
    cancel_current_session, reset_telemetry_data, read_telemetry
)
from gcs.commands import (
    arm, disarm, emergency_motor_stop, set_mode, takeoff, goto, emergency_hold,
    set_offboard_targets, reset_offboard_targets, stop_streamer,
    _ensure_streamer, request_all_parameters, offboard_controller,
    upload_mission
)
from gcs.telemetry import reset_telemetry_data
from gcs.logs import log
from gcs.connection import connect, request_telemetry
from gcs.telemetry_logger import logger_instance
from gcs.plan_format import export_qgc_plan, import_plan_file
from gcs.ui.preflight_dialog import PreflightChecklistDialog
from gcs.ui.survey_dialog import SurveyGridDialog
from gcs.ui.map_view import MapView
from gcs.ui.attitude_view import AttitudeView
from gcs.ui.console_view import ConsoleView
from gcs.ui.camera_view import CameraView
from gcs.ui.setup_view import SetupView
from gcs.ui.gauge import ArcGauge
from gcs.ui.tile_server import set_mbtiles_file

THEME = {
    'bg':           '#f5f7fa',
    'panel_bg':     '#ffffff',
    'panel_border': '#cbd5e1',
    'primary':      '#0b57d0',
    'success':      '#0f9d58',
    'warning':      '#e37400',
    'danger':       '#d93025',
    'muted':        '#5f6368',
    'dark_text':    '#0f172a',
    'plot_bg':      '#f8fafc',
}

CONNECTION_PROFILES = [
    ("PX4 SITL (UDP 14540)", "udpin:0.0.0.0:14540"),
    ("QGC Port (UDP 14550)", "udpin:0.0.0.0:14550"),
    ("TCP Local (5760)", "tcp:127.0.0.1:5760"),
    ("Serial Radio (COM3 57600)", "com3:57600"),
    ("Custom Connection", "")
]


class ConnectionWorker(QThread):
    connected = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, connection_string):
        super().__init__()
        self.connection_string = connection_string
        self.running = True

    def run(self):
        try:
            while self.running:
                vehicle = connect(self.connection_string, timeout=1.0)
                if vehicle is not None:
                    if self.running:
                        self.connected.emit(vehicle)
                    return
                self.msleep(400)
        except Exception as e:
            if self.running:
                self.failed.emit(str(e))

    def stop(self):
        self.running = False


class StatPanel(QFrame):
    def __init__(self, title, items, parent=None):
        super().__init__(parent)
        self.setObjectName("StatPanelContainer")
        self.setStyleSheet(f"""
            #StatPanelContainer {{
                background-color: {THEME['panel_bg']};
                border: 1px solid {THEME['panel_border']};
                border-radius: 10px;
            }}
        """)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(15)
        shadow.setColor(QColor(0, 0, 0, 15))
        shadow.setOffset(0, 4)
        self.setGraphicsEffect(shadow)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        t = QLabel(title)
        t.setStyleSheet(f"color: {THEME['primary']}; font-family: Google Sans Code; font-size: 11px; font-weight: bold; border: none; background: transparent;")
        layout.addWidget(t)

        self.labels = {}
        for key, name, unit in items:
            row = QHBoxLayout()
            row.setSpacing(4)
            name_lbl = QLabel(name)
            name_lbl.setStyleSheet(f"color: {THEME['dark_text']}; font-family: Google Sans Code; font-size: 11px; font-weight: 500; border: none; background: transparent;")
            val_lbl = QLabel(f"-- {unit}")
            val_lbl.setStyleSheet(f"color: {THEME['muted']}; font-family: Google Sans Code; font-size: 11px; font-weight: bold; border: none; background: transparent;")
            val_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
            row.addWidget(name_lbl)
            row.addStretch(1)
            row.addWidget(val_lbl)
            layout.addLayout(row)
            self.labels[key] = (val_lbl, unit)

    def set(self, key, value, color=None):
        if key not in self.labels:
            return
        lbl, unit = self.labels[key]
        if isinstance(value, float):
            lbl.setText(f"{value:.1f} {unit}".strip())
        elif isinstance(value, int):
            lbl.setText(f"{value} {unit}".strip())
        else:
            lbl.setText(f"{value} {unit}".strip())
        if color:
            lbl.setStyleSheet(f"color: {color}; font-family: Google Sans Code; font-size: 11px; font-weight: bold; border: none; background: transparent;")


class PremiumViewContainer(QFrame):
    def __init__(self, inner_widget, object_name, parent=None):
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setStyleSheet(f"""
            #{object_name} {{
                background-color: {THEME['panel_bg']};
                border: 1px solid {THEME['panel_border']};
                border-radius: 10px;
            }}
        """)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(15)
        shadow.setColor(QColor(0, 0, 0, 15))
        shadow.setOffset(0, 4)
        self.setGraphicsEffect(shadow)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(inner_widget)


class TelemetryPlotPanel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("PlotPanelContainer")
        self.setStyleSheet(f"""
            #PlotPanelContainer {{
                background-color: {THEME['panel_bg']};
                border: 1px solid {THEME['panel_border']};
                border-radius: 10px;
            }}
        """)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(15)
        shadow.setColor(QColor(0, 0, 0, 15))
        shadow.setOffset(0, 4)
        self.setGraphicsEffect(shadow)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        header = QHBoxLayout()
        t = QLabel("REAL-TIME FLIGHT TELEMETRY (ALTITUDE & SPEED)")
        t.setStyleSheet(f"color: {THEME['primary']}; font-family: Google Sans Code; font-size: 11px; font-weight: bold; border: none; background: transparent;")
        header.addWidget(t)
        header.addStretch(1)

        legend = QLabel("— Altitude (m Rel)  — Speed (m/s)")
        legend.setStyleSheet(f"color: {THEME['muted']}; font-family: Google Sans Code; font-size: 10px; border: none; background: transparent;")
        header.addWidget(legend)
        layout.addLayout(header)

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


class WorkerBridge(QObject):
    status_updated = pyqtSignal(str)
    voice_speech = pyqtSignal(str)
    command_completed = pyqtSignal(str, str, bool, str)  # session_id, action, ok, msg
    mission_uploaded = pyqtSignal(str, bool, str)        # session_id, ok, msg


class GCSWindow(QMainWindow):
    def __init__(self, vehicle=None):
        super().__init__()
        self.vehicle = vehicle
        self.waypoints: List[List[float]] = []
        self.takeoff_point: Optional[List[float]] = None
        self.landing_point: Optional[List[float]] = None
        self.held_keys = set()
        self.is_map_expanded = False
        self._home_set_on_map = False
        self._telemetry_session_id = None
        self.was_link_lost = False
        self.was_armed = False
        self.last_spoken_mode = ""
        self.last_spoken_alert = ""
        self.armed_start_time = None
        self.total_flight_dist = 0.0
        self.last_flight_coord = None

        self.setWindowTitle("PythonGCS — Autonomous Ground Control Station for PX4")
        self.resize(1400, 900)
        self.setMinimumSize(1100, 720)
        self.setStyleSheet(f"background-color: {THEME['bg']}; font-family: Google Sans Code;")

        self.tts = None
        self.voice_enabled = True
        if TTS_AVAILABLE:
            try:
                self.tts = QTextToSpeech()
            except Exception:
                self.tts = None

        self.history_time = []
        self.history_alt = []
        self.history_speed = []
        self.start_time = time.monotonic()
        self.worker_bridge = WorkerBridge()
        self.worker_bridge.status_updated.connect(self.set_status)
        self.worker_bridge.voice_speech.connect(self._speak_slot)
        self.worker_bridge.command_completed.connect(self._on_worker_command_completed)
        self.worker_bridge.mission_uploaded.connect(self._on_worker_mission_uploaded)

        self._build_ui()

        self.timer = QTimer()
        self.timer.timeout.connect(self.refresh)
        self.timer.start(500)

        if self.vehicle:
            self.on_connected(self.vehicle)

    def _btn_style(self, text_color, bg_color):
        return f"""
            QPushButton {{
                background-color: {bg_color}; color: {text_color};
                border: 1px solid {text_color}; border-radius: 4px;
                font-family: Google Sans Code; font-size: 11px; font-weight: bold;
                padding: 4px 8px;
            }}
            QPushButton:hover {{ background-color: {text_color}; color: #ffffff; }}
            QPushButton:disabled {{ border-color: {THEME['panel_border']}; color: {THEME['muted']}; background-color: {THEME['bg']}; }}
        """

    def _input_style(self):
        return f"""
            QSpinBox, QDoubleSpinBox, QComboBox, QLineEdit {{
                background-color: {THEME['panel_bg']}; color: {THEME['dark_text']};
                border: 1px solid {THEME['panel_border']}; border-radius: 4px;
                padding: 3px 6px; font-family: Google Sans Code; font-size: 11px;
            }}
        """

    def _pill_style(self, border_color, text_color, bg_color=None):
        bg = f"background-color: {bg_color};" if bg_color else "background-color: transparent;"
        return f"""
            QLabel {{
                border: 1.5px solid {border_color}; border-radius: 12px;
                color: {text_color}; {bg}
                font-family: Google Sans Code; font-size: 10px; font-weight: bold;
                padding: 2px 10px;
            }}
        """

    def _build_ui(self):
        root = QWidget()
        root.setStyleSheet(f"background-color: {THEME['bg']};")
        self.setCentralWidget(root)
        main_layout = QVBoxLayout(root)
        main_layout.setContentsMargins(10, 8, 10, 8)
        main_layout.setSpacing(8)

        # 1. Top Ribbon Strip (Connection profiles, status, pills)
        ribbon_frame = QFrame()
        ribbon_frame.setObjectName("RibbonFrame")
        ribbon_frame.setStyleSheet(f"#RibbonFrame {{ background-color: {THEME['panel_bg']}; border: 1px solid {THEME['panel_border']}; border-radius: 10px; }}")
        rf_layout = QHBoxLayout(ribbon_frame)
        rf_layout.setContentsMargins(12, 6, 12, 6)
        rf_layout.setSpacing(10)

        # Brand
        brand_lbl = QLabel("PYTHON GCS")
        brand_lbl.setStyleSheet(f"color: {THEME['primary']}; font-family: Google Sans Code; font-size: 13px; font-weight: 800; border: none; background: transparent;")
        rf_layout.addWidget(brand_lbl)

        # Connection Profile selector
        self.profile_combo = QComboBox()
        for name, uri in CONNECTION_PROFILES:
            self.profile_combo.addItem(name, uri)
        self.profile_combo.setStyleSheet(self._input_style())
        self.profile_combo.currentIndexChanged.connect(self._on_profile_changed)
        rf_layout.addWidget(self.profile_combo)

        # Connection input
        self.conn_input = QLineEdit("udpin:0.0.0.0:14540")
        self.conn_input.setFixedWidth(200)
        self.conn_input.setStyleSheet(self._input_style())
        rf_layout.addWidget(self.conn_input)

        self.conn_btn = QPushButton("CONNECT")
        self.conn_btn.setFixedHeight(28)
        self.conn_btn.setStyleSheet(self._btn_style(THEME['primary'], THEME['panel_bg']))
        self.conn_btn.clicked.connect(self.on_connect_toggle)
        rf_layout.addWidget(self.conn_btn)

        self.conn_status = QLabel("DISCONNECTED")
        self.conn_status.setStyleSheet(f"color: {THEME['danger']}; font-weight: bold; font-family: Google Sans Code; font-size: 11px; border: none;")
        rf_layout.addWidget(self.conn_status)

        rf_layout.addStretch(1)

        # Status Pills
        self.ribbon_fw_pill = QLabel("PX4 AUTOPILOT")
        self.ribbon_fw_pill.setStyleSheet(self._pill_style(THEME['panel_border'], THEME['muted']))
        rf_layout.addWidget(self.ribbon_fw_pill)

        self.ribbon_arm_pill = QLabel("DISARMED")
        self.ribbon_arm_pill.setStyleSheet(self._pill_style(THEME['danger'], THEME['danger']))
        rf_layout.addWidget(self.ribbon_arm_pill)

        self.ribbon_mode_pill = QLabel("MODE: UNKNOWN")
        self.ribbon_mode_pill.setStyleSheet(self._pill_style(THEME['primary'], THEME['primary']))
        rf_layout.addWidget(self.ribbon_mode_pill)

        self.ribbon_gps_pill = QLabel("GPS: 0D (0s)")
        self.ribbon_gps_pill.setStyleSheet(self._pill_style(THEME['muted'], THEME['dark_text']))
        rf_layout.addWidget(self.ribbon_gps_pill)

        self.ribbon_batt_pill = QLabel("BATT: ---% | 0.0V")
        self.ribbon_batt_pill.setStyleSheet(self._pill_style(THEME['muted'], THEME['dark_text']))
        rf_layout.addWidget(self.ribbon_batt_pill)

        self.ribbon_timer_pill = QLabel("⏱ 00:00")
        self.ribbon_timer_pill.setStyleSheet(self._pill_style(THEME['muted'], THEME['muted']))
        rf_layout.addWidget(self.ribbon_timer_pill)

        self.ribbon_dist_pill = QLabel("🚩 0 m")
        self.ribbon_dist_pill.setStyleSheet(self._pill_style(THEME['muted'], THEME['muted']))
        rf_layout.addWidget(self.ribbon_dist_pill)

        main_layout.addWidget(ribbon_frame)

        # 2. Main Tabs (FLY, PLAN, ANALYTICS, CAMERAS, SETUP)
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(f"""
            QTabWidget::pane {{ border: none; }}
            QTabBar::tab {{
                background-color: {THEME['panel_bg']}; color: {THEME['muted']};
                border: 1px solid {THEME['panel_border']}; border-bottom: none;
                border-top-left-radius: 6px; border-top-right-radius: 6px;
                padding: 6px 16px; font-family: Google Sans Code; font-weight: bold; font-size: 11px;
                margin-right: 4px;
            }}
            QTabBar::tab:selected {{
                background-color: {THEME['primary']}; color: #ffffff;
                border-color: {THEME['primary']};
            }}
        """)

        self._build_fly_tab()
        self._build_plan_tab()
        self._build_analytics_tab()
        self._build_cameras_tab()
        self._build_setup_tab()

        main_layout.addWidget(self.tabs, stretch=1)

    def _on_profile_changed(self, idx):
        uri = self.profile_combo.currentData()
        if uri:
            self.conn_input.setText(uri)

    def _build_fly_tab(self):
        fly_widget = QWidget()
        fly_layout = QVBoxLayout(fly_widget)
        fly_layout.setContentsMargins(0, 4, 0, 0)
        fly_layout.setSpacing(6)

        content_layout = QHBoxLayout()
        content_layout.setSpacing(8)

        # LEFT COLUMN (Gauges, Preflight, Voice)
        self.left_col_widget = QWidget()
        left_col = QVBoxLayout(self.left_col_widget)
        left_col.setContentsMargins(0, 0, 0, 0)
        left_col.setSpacing(8)

        # Primary gauges card
        gauge_card = QFrame()
        gauge_card.setObjectName("GaugeCard")
        gauge_card.setStyleSheet(f"#GaugeCard {{ background-color: {THEME['panel_bg']}; border: 1px solid {THEME['panel_border']}; border-radius: 10px; }}")
        gc_layout = QGridLayout(gauge_card)
        gc_layout.setContentsMargins(8, 8, 8, 8)
        gc_layout.setSpacing(6)

        self.gauge_spd = ArcGauge("SPEED", "m/s", 0, 25, THEME['primary'])
        self.gauge_alt = ArcGauge("ALT REL", "m", 0, 100, THEME['primary'])
        self.gauge_throttle = ArcGauge("THROTTLE", "%", 0, 100, THEME['warning'])
        self.gauge_batt = ArcGauge("BATTERY", "%", 0, 100, THEME['success'])

        gc_layout.addWidget(self.gauge_spd, 0, 0)
        gc_layout.addWidget(self.gauge_alt, 0, 1)
        gc_layout.addWidget(self.gauge_throttle, 1, 0)
        gc_layout.addWidget(self.gauge_batt, 1, 1)
        left_col.addWidget(gauge_card)

        # Preflight Checklist Button
        self.preflight_btn = QPushButton("📋 PRE-FLIGHT CHECKLIST")
        self.preflight_btn.setFixedHeight(34)
        self.preflight_btn.setStyleSheet(f"background-color: {THEME['panel_bg']}; color: {THEME['primary']}; border: 1.5px solid {THEME['primary']}; border-radius: 6px; font-weight: bold;")
        self.preflight_btn.clicked.connect(self.on_open_preflight_dialog)
        left_col.addWidget(self.preflight_btn)

        # Voice Toggle Button
        self.voice_btn = QPushButton("🔊 VOICE: ON")
        self.voice_btn.setFixedHeight(30)
        self.voice_btn.setStyleSheet(self._btn_style(THEME['primary'], THEME['panel_bg']))
        self.voice_btn.clicked.connect(self.on_toggle_voice)
        left_col.addWidget(self.voice_btn)

        # Telemetry plot panel
        self.plot_panel = TelemetryPlotPanel()
        self.plot_panel.setFixedHeight(180)
        left_col.addWidget(self.plot_panel)

        left_col.addStretch(1)
        self.left_col_widget.setFixedWidth(280)
        content_layout.addWidget(self.left_col_widget)

        # CENTER COLUMN (Tactical Map, Map toolbar)
        center_col = QVBoxLayout()
        center_col.setSpacing(6)

        self.map_view = MapView()
        self.map_view.goto_requested.connect(self.on_map_goto_requested)
        self.map_container = PremiumViewContainer(self.map_view, "TacticalMapContainer")
        center_col.addWidget(self.map_container, stretch=1)

        # Map Toolbar
        map_bar = QHBoxLayout()
        map_bar.setSpacing(8)

        self.load_mbtiles_btn = QPushButton("🗺️ LOAD OFFLINE MBTILES")
        self.load_mbtiles_btn.setFixedHeight(28)
        self.load_mbtiles_btn.setStyleSheet(self._btn_style(THEME['primary'], THEME['panel_bg']))
        self.load_mbtiles_btn.clicked.connect(self.on_load_offline_mbtiles)
        map_bar.addWidget(self.load_mbtiles_btn)

        self.export_kml_btn = QPushButton("💾 EXPORT FLIGHT TRAIL")
        self.export_kml_btn.setFixedHeight(28)
        self.export_kml_btn.setStyleSheet(self._btn_style(THEME['primary'], THEME['panel_bg']))
        self.export_kml_btn.clicked.connect(self.on_export_flight_trail)
        map_bar.addWidget(self.export_kml_btn)

        self.expand_map_btn = QPushButton("⛶ EXPAND MAP")
        self.expand_map_btn.setFixedHeight(28)
        self.expand_map_btn.setStyleSheet(self._btn_style(THEME['primary'], THEME['panel_bg']))
        self.expand_map_btn.clicked.connect(self.on_toggle_expand_map)
        map_bar.addWidget(self.expand_map_btn)

        center_col.addLayout(map_bar)
        content_layout.addLayout(center_col, stretch=1)

        # RIGHT COLUMN (3D Attitude, Aircraft Status, Keyboard flight, Commands)
        self.right_col_widget = QWidget()
        right_col = QVBoxLayout(self.right_col_widget)
        right_col.setContentsMargins(0, 0, 0, 0)
        right_col.setSpacing(8)

        # Attitude view
        self.attitude_view = AttitudeView()
        self.attitude_view.setFixedHeight(220)
        self.att_container = PremiumViewContainer(self.attitude_view, "AttitudeContainer")
        right_col.addWidget(self.att_container)

        # Action Panel: Mode dropdown, Arm, Takeoff, Land, RTL, Hold
        action_card = QFrame()
        action_card.setObjectName("ActionCard")
        action_card.setStyleSheet(f"#ActionCard {{ background-color: {THEME['panel_bg']}; border: 1px solid {THEME['panel_border']}; border-radius: 10px; }}")
        ac_layout = QVBoxLayout(action_card)
        ac_layout.setContentsMargins(10, 8, 10, 8)
        ac_layout.setSpacing(6)

        ac_title = QLabel("FLIGHT EXECUTION")
        ac_title.setStyleSheet(f"color: {THEME['primary']}; font-size: 11px; font-weight: bold;")
        ac_layout.addWidget(ac_title)

        # Mode row
        mode_row = QHBoxLayout()
        self.mode_combo = QComboBox()
        self.mode_combo.addItems([
            "HOLD", "POSCTL", "ALTCTL", "STABILIZED", "MANUAL",
            "OFFBOARD", "AUTO.TAKEOFF", "AUTO.LOITER", "AUTO.RTL",
            "AUTO.LAND", "AUTO.MISSION"
        ])
        self.mode_combo.setStyleSheet(self._input_style())
        self.mode_btn = QPushButton("SET MODE")
        self.mode_btn.setFixedHeight(26)
        self.mode_btn.setStyleSheet(self._btn_style(THEME['primary'], THEME['panel_bg']))
        self.mode_btn.clicked.connect(self.on_set_mode)
        mode_row.addWidget(self.mode_combo, stretch=1)
        mode_row.addWidget(self.mode_btn)
        ac_layout.addLayout(mode_row)

        # Arm & Takeoff row
        arm_row = QHBoxLayout()
        self.arm_btn = QPushButton("ARM")
        self.arm_btn.setFixedHeight(30)
        self.arm_btn.setStyleSheet(self._btn_style(THEME['success'], THEME['panel_bg']))
        self.arm_btn.clicked.connect(self.on_arm_disarm)

        self.alt_spin = QDoubleSpinBox()
        self.alt_spin.setRange(2.0, 100.0)
        self.alt_spin.setValue(5.0)
        self.alt_spin.setSuffix(" m")
        self.alt_spin.setStyleSheet(self._input_style())

        self.takeoff_btn = QPushButton("TAKEOFF")
        self.takeoff_btn.setFixedHeight(30)
        self.takeoff_btn.setStyleSheet(self._btn_style(THEME['primary'], THEME['panel_bg']))
        self.takeoff_btn.clicked.connect(self.on_takeoff)

        arm_row.addWidget(self.arm_btn)
        arm_row.addWidget(self.alt_spin)
        arm_row.addWidget(self.takeoff_btn)
        ac_layout.addLayout(arm_row)

        # RTL, LAND, EMERGENCY HOLD
        rec_row = QHBoxLayout()
        self.rtl_btn = QPushButton("RTL")
        self.rtl_btn.setFixedHeight(28)
        self.rtl_btn.setStyleSheet(self._btn_style(THEME['warning'], THEME['panel_bg']))
        self.rtl_btn.clicked.connect(self.on_rtl)

        self.land_btn = QPushButton("LAND")
        self.land_btn.setFixedHeight(28)
        self.land_btn.setStyleSheet(self._btn_style(THEME['warning'], THEME['panel_bg']))
        self.land_btn.clicked.connect(self.on_land)

        self.hold_btn = QPushButton("EMERGENCY HOLD")
        self.hold_btn.setFixedHeight(28)
        self.hold_btn.setStyleSheet(self._btn_style(THEME['danger'], THEME['panel_bg']))
        self.hold_btn.clicked.connect(self.on_emergency_hold)

        rec_row.addWidget(self.rtl_btn)
        rec_row.addWidget(self.land_btn)
        rec_row.addWidget(self.hold_btn)
        ac_layout.addLayout(rec_row)

        # Separate Emergency Motor Cutoff Row
        emer_row = QHBoxLayout()
        self.emer_stop_btn = QPushButton("EMERGENCY MOTOR STOP (KILL)")
        self.emer_stop_btn.setFixedHeight(28)
        self.emer_stop_btn.setStyleSheet(f"background: {THEME['danger']}; color: #ffffff; font-weight: bold; border-radius: 4px; border: 1px solid #b71c1c;")
        self.emer_stop_btn.clicked.connect(self.on_emergency_motor_stop)
        emer_row.addWidget(self.emer_stop_btn)
        ac_layout.addLayout(emer_row)

        # Offboard Quick Targets (speeds agree with code & README: 2.0 m/s and 0.5 rad/s)
        off_row = QHBoxLayout()
        self.fwd_btn = QPushButton("FWD (2 m/s)")
        self.fwd_btn.setFixedHeight(26)
        self.fwd_btn.setStyleSheet(self._btn_style(THEME['primary'], THEME['panel_bg']))
        self.fwd_btn.clicked.connect(self.on_forward)

        self.yawl_btn = QPushButton("YAW L (-0.5)")
        self.yawl_btn.setFixedHeight(26)
        self.yawl_btn.setStyleSheet(self._btn_style(THEME['primary'], THEME['panel_bg']))
        self.yawl_btn.clicked.connect(self.on_yaw_left)

        self.yawr_btn = QPushButton("YAW R (+0.5)")
        self.yawr_btn.setFixedHeight(26)
        self.yawr_btn.setStyleSheet(self._btn_style(THEME['primary'], THEME['panel_bg']))
        self.yawr_btn.clicked.connect(self.on_yaw_right)

        self.hover_btn = QPushButton("HOVER (0 m/s)")
        self.hover_btn.setFixedHeight(26)
        self.hover_btn.setStyleSheet(self._btn_style(THEME['success'], THEME['panel_bg']))
        self.hover_btn.clicked.connect(self.on_hover)

        off_row.addWidget(self.fwd_btn)
        off_row.addWidget(self.yawl_btn)
        off_row.addWidget(self.yawr_btn)
        off_row.addWidget(self.hover_btn)
        ac_layout.addLayout(off_row)

        # Keyboard Flight Enable Checkbox
        self.kb_checkbox = QCheckBox("Enable Keyboard Flight (WASD / QE / IK / Space)")
        self.kb_checkbox.setStyleSheet(f"color: {THEME['primary']}; font-weight: bold; font-size: 11px;")
        self.kb_checkbox.toggled.connect(self.on_kb_toggle)
        ac_layout.addWidget(self.kb_checkbox)

        self.status_label = QLabel("Ready.")
        self.status_label.setStyleSheet(f"color: {THEME['muted']}; font-size: 11px;")
        ac_layout.addWidget(self.status_label)

        right_col.addWidget(action_card)
        right_col.addStretch(1)
        self.right_col_widget.setFixedWidth(330)
        content_layout.addWidget(self.right_col_widget)

        fly_layout.addLayout(content_layout, stretch=1)

        # Slim console view at bottom
        self.console_view = ConsoleView()
        self.console_view.setFixedHeight(110)
        fly_layout.addWidget(self.console_view, stretch=0)

        self.tabs.addTab(fly_widget, "FLY")


    def _build_plan_tab(self):
        plan_widget = QWidget()
        plan_layout = QHBoxLayout(plan_widget)
        plan_layout.setContentsMargins(8, 8, 8, 8)
        plan_layout.setSpacing(8)

        self.plan_map_view = MapView()
        self.plan_map_container = PremiumViewContainer(self.plan_map_view, "PlanMapContainer")
        plan_layout.addWidget(self.plan_map_container, stretch=3)

        # Mission planning side panel
        self.mission_panel = QFrame()
        self.mission_panel.setObjectName("MissionPanel")
        self.mission_panel.setStyleSheet(f"#MissionPanel {{ background-color: {THEME['panel_bg']}; border: 1px solid {THEME['panel_border']}; border-radius: 10px; }}")
        mp = QVBoxLayout(self.mission_panel)
        mp.setContentsMargins(12, 10, 12, 10)
        mp.setSpacing(6)

        mp_title = QLabel("MISSION PLANNING")
        mp_title.setStyleSheet(f"color: {THEME['primary']}; font-size: 11px; font-weight: bold;")
        mp.addWidget(mp_title)

        self.wp_list = QListWidget()
        self.wp_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {THEME['panel_bg']}; color: {THEME['primary']};
                border: 1px solid {THEME['panel_border']}; border-radius: 4px;
                font-family: Google Sans Code; font-size: 11px;
            }}
        """)
        mp.addWidget(self.wp_list)

        # Waypoint Edit Action Row (Reorder, Edit Alt, Delete)
        wp_edit_row = QHBoxLayout()
        wp_edit_row.setSpacing(4)

        self.wp_up_btn = QPushButton("▲ UP")
        self.wp_up_btn.setFixedHeight(24)
        self.wp_up_btn.setStyleSheet(self._btn_style(THEME['primary'], THEME['panel_bg']))
        self.wp_up_btn.clicked.connect(self.on_move_wp_up)

        self.wp_down_btn = QPushButton("▼ DOWN")
        self.wp_down_btn.setFixedHeight(24)
        self.wp_down_btn.setStyleSheet(self._btn_style(THEME['primary'], THEME['panel_bg']))
        self.wp_down_btn.clicked.connect(self.on_move_wp_down)

        self.wp_edit_alt_btn = QPushButton("✎ ALT")
        self.wp_edit_alt_btn.setFixedHeight(24)
        self.wp_edit_alt_btn.setStyleSheet(self._btn_style(THEME['primary'], THEME['panel_bg']))
        self.wp_edit_alt_btn.clicked.connect(self.on_edit_wp_alt)

        self.wp_del_btn = QPushButton("✕ DEL")
        self.wp_del_btn.setFixedHeight(24)
        self.wp_del_btn.setStyleSheet(self._btn_style(THEME['danger'], THEME['panel_bg']))
        self.wp_del_btn.clicked.connect(self.on_delete_wp)

        wp_edit_row.addWidget(self.wp_up_btn)
        wp_edit_row.addWidget(self.wp_down_btn)
        wp_edit_row.addWidget(self.wp_edit_alt_btn)
        wp_edit_row.addWidget(self.wp_del_btn)
        mp.addLayout(wp_edit_row)

        self.wp_progress_label = QLabel("Active Waypoint: ---")
        self.wp_progress_label.setStyleSheet(f"color: {THEME['primary']}; font-family: Google Sans Code; font-size: 11px;")
        mp.addWidget(self.wp_progress_label)

        # Sync / Upload / Clear
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

        # Import / Export
        m_row2 = QHBoxLayout()
        m_row2.setSpacing(6)

        self.import_btn = QPushButton("IMPORT .PLAN")
        self.import_btn.setFixedHeight(30)
        self.import_btn.setStyleSheet(self._btn_style(THEME['primary'], THEME['panel_bg']))
        self.import_btn.clicked.connect(self.on_import_mission)

        self.export_btn = QPushButton("EXPORT .PLAN")
        self.export_btn.setFixedHeight(30)
        self.export_btn.setStyleSheet(self._btn_style(THEME['primary'], THEME['panel_bg']))
        self.export_btn.clicked.connect(self.on_export_mission)

        m_row2.addWidget(self.import_btn)
        m_row2.addWidget(self.export_btn)
        mp.addLayout(m_row2)

        # Cruise Altitude and Survey Grid
        alt_row = QHBoxLayout()
        alt_lbl = QLabel("CRUISE ALT:")
        alt_lbl.setStyleSheet(f"color: {THEME['primary']}; font-family: Google Sans Code; font-size: 11px; font-weight: bold;")
        self.mission_alt_spin = QDoubleSpinBox()
        self.mission_alt_spin.setRange(2.0, 150.0)
        self.mission_alt_spin.setValue(10.0)
        self.mission_alt_spin.setSuffix(" m")
        self.mission_alt_spin.setStyleSheet(self._input_style())
        alt_row.addWidget(alt_lbl)
        alt_row.addWidget(self.mission_alt_spin)
        mp.addLayout(alt_row)

        self.survey_btn = QPushButton("▦ SURVEY GRID GENERATOR")
        self.survey_btn.setFixedHeight(30)
        self.survey_btn.setStyleSheet(self._btn_style(THEME['primary'], THEME['panel_bg']))
        self.survey_btn.clicked.connect(self.on_open_survey_dialog)
        mp.addWidget(self.survey_btn)

        self.mission_stats_label = QLabel("Dist: 0.0 m | Est: 00:00 | WPs: 0")
        self.mission_stats_label.setStyleSheet(f"""
            QLabel {{
                background-color: {THEME['plot_bg']};
                color: {THEME['dark_text']};
                border: 1px solid {THEME['panel_border']};
                border-radius: 4px;
                padding: 6px;
                font-family: Google Sans Code;
                font-size: 11px;
            }}
        """)
        mp.addWidget(self.mission_stats_label)

        self.start_btn = QPushButton("START MISSION (AUTO.MISSION)")
        self.start_btn.setFixedHeight(34)
        self.start_btn.setStyleSheet(f"background-color: {THEME['success']}; color: #ffffff; font-weight: bold; border-radius: 4px;")
        self.start_btn.clicked.connect(self.on_start_mission)
        self.start_btn.setEnabled(False) # Enabled only after confirmed mission upload
        mp.addWidget(self.start_btn)

        plan_layout.addWidget(self.mission_panel, stretch=1)
        self.tabs.addTab(plan_widget, "PLAN")

    def _build_analytics_tab(self):
        analytics_widget = QWidget()
        analytics_layout = QHBoxLayout(analytics_widget)
        analytics_layout.setContentsMargins(8, 8, 8, 8)
        analytics_layout.setSpacing(10)

        # Left: Strip charts
        self.analytics_plot_panel = TelemetryPlotPanel()
        analytics_layout.addWidget(self.analytics_plot_panel, stretch=2)

        # Right: Sensor diagnostics panels
        analytics_side = QVBoxLayout()
        analytics_side.setSpacing(8)

        # Power panel
        self.power_panel = StatPanel("POWER & BATTERY TELEMETRY", [
            ('battery', "Battery Remaining", "%"),
            ('voltage', "Total Voltage", "V"),
            ('cells', "Cell Balance", ""),
            ('throttle', "Throttle Level", "%")
        ])
        analytics_side.addWidget(self.power_panel)

        # GNSS panel
        self.gnss_panel = StatPanel("GNSS NAVIGATION TELEMETRY", [
            ('fix', "Fix Type", ""),
            ('sats', "Satellites Visible", ""),
            ('eph', "HDOP Precision", "m"),
            ('alt_rel', "Altitude (Launch Rel)", "m"),
            ('alt_amsl', "Altitude (AMSL)", "m")
        ])
        analytics_side.addWidget(self.gnss_panel)

        # MAVLink Link diagnostics panel
        self.link_panel = StatPanel("MAVLINK LINK & SENSOR DIAGNOSTICS", [
            ('msg_rate', "Downlink Rate", "Hz"),
            ('loss_pct', "Packet Loss", "%"),
            ('packets', "Packets Rcvd / Lost", ""),
            ('vibration', "IMU Vibration (x,y,z)", ""),
            ('clipping', "Vibration Clipping", "")
        ])
        analytics_side.addWidget(self.link_panel)

        analytics_side.addStretch(1)
        analytics_layout.addLayout(analytics_side, stretch=1)
        self.tabs.addTab(analytics_widget, "ANALYTICS")

    def _build_cameras_tab(self):
        cameras_widget = QWidget()
        cameras_layout = QHBoxLayout(cameras_widget)
        cameras_layout.setContentsMargins(8, 8, 8, 8)
        cameras_layout.setSpacing(8)
        self.front_cam = CameraView("FRONT CAMERA FEED (RTSP/MJPEG - CONFIGURE SOURCE)")
        self.bottom_cam = CameraView("BOTTOM CAMERA FEED (RTSP/MJPEG - CONFIGURE SOURCE)")
        cameras_layout.addWidget(self.front_cam, stretch=1)
        cameras_layout.addWidget(self.bottom_cam, stretch=1)
        self.tabs.addTab(cameras_widget, "CAMERAS")

    def _build_setup_tab(self):
        self.setup_view = SetupView(self.vehicle)
        self.tabs.addTab(self.setup_view, "SETUP")

    def on_toggle_expand_map(self):
        self.is_map_expanded = not self.is_map_expanded
        if self.is_map_expanded:
            self.left_col_widget.hide()
            self.right_col_widget.hide()
            self.plot_panel.hide()
            self.expand_map_btn.setText("🗗 RESTORE DASHBOARD")
            self.set_status("Expanded map mode enabled.")
        else:
            self.left_col_widget.show()
            self.right_col_widget.show()
            self.plot_panel.show()
            self.expand_map_btn.setText("⛶ EXPAND MAP")
            self.set_status("Dashboard layout restored.")

    def on_load_offline_mbtiles(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, "Load Offline MBTiles Map", "", "MBTiles Map (*.mbtiles);;All Files (*.*)"
        )
        if filename:
            set_mbtiles_file(filename)
            self.set_status(f"Loaded offline MBTiles: {os.path.basename(filename)}")
            QMessageBox.information(
                self, "MBTiles Loaded",
                f"Loaded offline map database:\n{filename}\n\n"
                "Tactical map tiles will now be served locally from this file without internet connection."
            )
        else:
            QMessageBox.information(
                self, "Offline Map Notice",
                "OpenStreetMap Foundation policy prohibits automated bulk scraping of tiles.\n\n"
                "PythonGCS automatically caches tiles on disk as you pan and zoom while online.\n\n"
                "To operate 100% offline in the field, export an .mbtiles file (e.g. via QGIS or OpenMapTiles) "
                "and load it here."
            )

    def on_export_flight_trail(self):
        filename, _ = QFileDialog.getSaveFileName(
            self, "Export Flight Trail", "", "Google Earth KML (*.kml);;GeoJSON (*.geojson)"
        )
        if not filename:
            return
        if filename.endswith(".geojson"):
            ok = logger_instance.export_geojson(filename)
        else:
            ok = logger_instance.export_kml(filename)

        if ok:
            self.set_status(f"Exported flight trail to {filename}")
            QMessageBox.information(self, "Export Success", f"Flight trail exported successfully to {filename}")
        else:
            self.set_status("Export failed: No GPS flight coordinates recorded yet.")
            QMessageBox.warning(self, "Export Failed", "No GPS flight coordinates recorded yet.")

    def on_open_survey_dialog(self):
        curr_lat = telemetry_data.get('lat', 0.0)
        curr_lon = telemetry_data.get('lon', 0.0)
        def_alt = self.mission_alt_spin.value()
        dlg = SurveyGridDialog(curr_lat, curr_lon, default_alt=def_alt, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            wps = dlg.generated_waypoints
            if wps:
                self.mission_alt_spin.setValue(dlg.selected_alt)
                # Set grid waypoints cleanly without duplicate takeoff/landing
                self.waypoints = wps
                self.takeoff_point = None
                self.landing_point = None
                self.plan_map_view.import_mission(None, wps, None)
                self.map_view.import_mission(None, wps, None)
                self.wp_list.clear()
                for idx, wp in enumerate(wps):
                    self.wp_list.addItem(f"WP {idx+1}: {wp[0]:.6f}, {wp[1]:.6f} @ {wp[2]:.1f}m")
                self.update_mission_stats()
                self.set_status(f"Generated survey grid: {len(wps)} waypoints @ {dlg.selected_alt:.1f}m.")
                if self.tts and self.voice_enabled:
                    self.tts.say("Survey grid generated.")

    def on_move_wp_up(self):
        row = self.wp_list.currentRow()
        if row > 0 and row < len(self.waypoints):
            self.waypoints[row - 1], self.waypoints[row] = self.waypoints[row], self.waypoints[row - 1]
            self._rebuild_wp_list()
            self.wp_list.setCurrentRow(row - 1)
            self._sync_plan_to_map()

    def on_move_wp_down(self):
        row = self.wp_list.currentRow()
        if row >= 0 and row < len(self.waypoints) - 1:
            self.waypoints[row + 1], self.waypoints[row] = self.waypoints[row], self.waypoints[row + 1]
            self._rebuild_wp_list()
            self.wp_list.setCurrentRow(row + 1)
            self._sync_plan_to_map()

    def on_edit_wp_alt(self):
        row = self.wp_list.currentRow()
        if 0 <= row < len(self.waypoints):
            wp = self.waypoints[row]
            curr_alt = wp[2] if len(wp) > 2 else self.mission_alt_spin.value()
            new_alt, ok = QInputDialog.getDouble(self, "Edit Altitude", f"Waypoint {row+1} Altitude (m):", curr_alt, 2.0, 150.0, 1)
            if ok:
                if len(wp) > 2:
                    wp[2] = new_alt
                else:
                    wp.append(new_alt)
                self._rebuild_wp_list()
                self.wp_list.setCurrentRow(row)
                self._sync_plan_to_map()

    def on_delete_wp(self):
        row = self.wp_list.currentRow()
        if 0 <= row < len(self.waypoints):
            del self.waypoints[row]
            self._rebuild_wp_list()
            self._sync_plan_to_map()

    def _rebuild_wp_list(self):
        self.wp_list.clear()
        if self.takeoff_point:
            t_alt = self.takeoff_point[2] if len(self.takeoff_point) > 2 else self.mission_alt_spin.value()
            self.wp_list.addItem(f"TAKEOFF: {self.takeoff_point[0]:.6f}, {self.takeoff_point[1]:.6f} @ {t_alt:.1f}m")
        for idx, wp in enumerate(self.waypoints):
            w_alt = wp[2] if len(wp) > 2 else self.mission_alt_spin.value()
            self.wp_list.addItem(f"WP {idx+1}: {wp[0]:.6f}, {wp[1]:.6f} @ {w_alt:.1f}m")
        if self.landing_point:
            self.wp_list.addItem(f"LAND: {self.landing_point[0]:.6f}, {self.landing_point[1]:.6f}")
        self.update_mission_stats()

    def _sync_plan_to_map(self):
        self.plan_map_view.import_mission(self.takeoff_point, self.waypoints, self.landing_point)
        self.map_view.import_mission(self.takeoff_point, self.waypoints, self.landing_point)

    def on_sync_map(self):
        self.plan_map_view.get_mission(self.on_mission_retrieved)

    def on_mission_retrieved(self, mission_json):
        if not mission_json:
            return
        import json
        try:
            mission = json.loads(mission_json)
        except Exception:
            return

        self.takeoff_point = mission.get("takeoff")
        self.waypoints = mission.get("waypoints", [])
        self.landing_point = mission.get("landing")
        self._rebuild_wp_list()
        self.map_view.import_mission(self.takeoff_point, self.waypoints, self.landing_point)

    def update_mission_stats(self):
        all_pts = []
        if self.takeoff_point:
            all_pts.append(self.takeoff_point[:2])
        all_pts.extend([wp[:2] for wp in self.waypoints])
        if self.landing_point:
            all_pts.append(self.landing_point[:2])

        total_dist = 0.0
        for i in range(len(all_pts) - 1):
            lat1, lon1 = all_pts[i]
            lat2, lon2 = all_pts[i+1]
            R = 6371e3
            p1, p2 = math.radians(lat1), math.radians(lat2)
            dp = math.radians(lat2 - lat1)
            dl = math.radians(lon2 - lon1)
            a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
            total_dist += 2 * R * math.asin(math.sqrt(a))

        cruise_spd = 5.0
        est_secs = total_dist / cruise_spd if cruise_spd > 0 else 0
        mins = int(est_secs // 60)
        secs = int(est_secs % 60)
        self.mission_stats_label.setText(f"Dist: {total_dist:.1f} m | Est: {mins:02d}:{secs:02d} | WPs: {len(all_pts)}")

    def on_clear_mission(self):
        self.plan_map_view.clear_waypoints()
        self.map_view.clear_waypoints()
        self.wp_list.clear()
        self.waypoints = []
        self.takeoff_point = None
        self.landing_point = None
        self.start_btn.setEnabled(False)
        self.update_mission_stats()
        self.set_status("Mission cleared.")

    def on_upload_mission(self):
        if not self.waypoints and not self.takeoff_point and not self.landing_point:
            self.set_status("Upload failed: No waypoints in plan. Add waypoints or sync map first!")
            return
        if not self.vehicle:
            self.set_status("Upload failed: No vehicle connection.")
            return

        alt_val = self.mission_alt_spin.value()
        session_id = self.current_session_id
        vehicle = self.vehicle
        self.set_status(f"Uploading mission to flight controller and verifying readback (@ {alt_val:.1f}m)...")
        self.upload_btn.setEnabled(False)
        self.start_btn.setEnabled(False)

        def _upload_worker():
            ok, msg = upload_mission(
                vehicle, self.waypoints, self.takeoff_point, self.landing_point, alt_val, verify_after_upload=True
            )
            self.worker_bridge.mission_uploaded.emit(session_id, ok, msg)

        threading.Thread(target=_upload_worker, daemon=True).start()

    def on_start_mission(self):
        if not self.vehicle:
            self.set_status("Start Mission failed: No vehicle connection.")
            return
        session_id = self.current_session_id
        vehicle = self.vehicle
        self.set_status("Setting mode to AUTO.MISSION (Starting mission)...")
        def _start_worker():
            from gcs.commands import start_mission
            ok, msg = start_mission(vehicle)
            self.worker_bridge.command_completed.emit(session_id, "START_MISSION", ok, msg)
        threading.Thread(target=_start_worker, daemon=True).start()

    def on_export_mission(self):
        if not self.waypoints and not self.takeoff_point and not self.landing_point:
            self.on_sync_map()
            if not self.waypoints and not self.takeoff_point and not self.landing_point:
                self.set_status("Export failed: Plan is empty!")
                return

        filename, _ = QFileDialog.getSaveFileName(
            self, "Export Mission Plan", "", "QGroundControl Plan (*.plan);;JSON Files (*.json)"
        )
        if not filename:
            return

        home_coord = [telemetry_data.get('home_lat', 0.0), telemetry_data.get('home_lon', 0.0)]
        alt_val = self.mission_alt_spin.value()
        export_qgc_plan(
            filename, self.waypoints, self.takeoff_point, self.landing_point,
            target_alt=alt_val, cruise_speed=5.0, planned_home=home_coord
        )
        self.set_status(f"Mission exported to {filename}")

    def on_import_mission(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, "Import Mission Plan", "", "QGroundControl Plan (*.plan);;JSON Files (*.json);;All Files (*.*)"
        )
        if not filename:
            return

        ok, wps, takeoff, landing, detected_alt, msg = import_plan_file(filename)
        if not ok:
            self.set_status(f"Import failed: {msg}")
            QMessageBox.warning(self, "Import Failed", msg)
            return

        self.takeoff_point = takeoff
        self.waypoints = wps
        self.landing_point = landing
        self.mission_alt_spin.setValue(detected_alt)

        self._sync_plan_to_map()
        self._rebuild_wp_list()
        self.set_status(f"Import success: {msg}")
        self.start_btn.setEnabled(False) # Require re-upload before start


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
            self.conn_status.setStyleSheet(f"color: {THEME['warning']}; font-weight: bold;")

            self.conn_worker = ConnectionWorker(connection_string)
            self.conn_worker.connected.connect(self.on_connected)
            self.conn_worker.failed.connect(self.on_connection_failed)
            self.conn_worker.start()

    def on_connected(self, vehicle):
        self.vehicle = vehicle
        self.setup_view.set_vehicle(vehicle)
        _ensure_streamer(self.vehicle)
        self._home_set_on_map = False

        # Create new telemetry session
        reset_telemetry_data()
        self._telemetry_session_id = create_new_session()

        try:
            request_telemetry(self.vehicle)
            self.telemetry_thread = threading.Thread(
                target=read_telemetry,
                args=(self.vehicle, self._telemetry_session_id),
                daemon=True
            )
            self.telemetry_thread.start()
        except Exception as e:
            self.set_status(f"Telemetry start failed: {e}")

        # Start telemetry CSV logging
        logger_instance.start()

        self.set_status("Connected to vehicle!")
        self.conn_btn.setText("DISCONNECT")
        self.conn_btn.setEnabled(True)
        self.conn_input.setEnabled(False)
        self.conn_status.setText("CONNECTED")
        self.conn_status.setStyleSheet(f"color: {THEME['success']}; font-weight: bold;")
        self.set_controls_enabled(True)

        # Automatically request all parameters upon connection
        threading.Thread(target=request_all_parameters, args=(self.vehicle,), daemon=True).start()

    def on_connection_failed(self, error_msg):
        self.set_status(f"Connection failed: {error_msg}")
        self.disconnect_vehicle()

    def disconnect_vehicle(self):
        if hasattr(self, 'conn_worker') and self.conn_worker:
            self.conn_worker.stop()
            self.conn_worker.wait()

        # Stop telemetry logger and streamer
        logger_instance.stop()
        stop_streamer()
        reset_offboard_targets()

        # Cancel telemetry session
        cancel_current_session()
        reset_telemetry_data()

        if self.vehicle is not None:
            try:
                self.vehicle.close()
            except Exception:
                pass
            self.vehicle = None

        if hasattr(self, 'setup_view'):
            self.setup_view.set_vehicle(None)

        self._home_set_on_map = False
        self.held_keys.clear()
        self.history_time = []
        self.history_alt = []
        self.history_speed = []
        self.start_time = time.monotonic()
        if hasattr(self, 'plot_panel'):
            self.plot_panel.plot_widget.clear()
            self.plot_panel.alt_curve = self.plot_panel.plot_widget.plot(pen=pg.mkPen(THEME['primary'], width=1.5))
            self.plot_panel.speed_curve = self.plot_panel.plot_widget.plot(pen=pg.mkPen(THEME['warning'], width=1.5))

        self.set_status("Disconnected.")
        self.conn_btn.setText("CONNECT")
        self.conn_btn.setEnabled(True)
        self.conn_input.setEnabled(True)
        self.conn_status.setText("DISCONNECTED")
        self.conn_status.setStyleSheet(f"color: {THEME['danger']}; font-weight: bold;")
        self.set_controls_enabled(False)

    def set_controls_enabled(self, enabled):
        self.arm_btn.setEnabled(enabled)
        self.mode_btn.setEnabled(enabled)
        self.takeoff_btn.setEnabled(enabled)
        self.rtl_btn.setEnabled(enabled)
        self.land_btn.setEnabled(enabled)
        self.hold_btn.setEnabled(enabled)
        if hasattr(self, "emer_stop_btn"):
            self.emer_stop_btn.setEnabled(enabled)
        self.fwd_btn.setEnabled(enabled)
        self.yawl_btn.setEnabled(enabled)
        self.yawr_btn.setEnabled(enabled)
        self.hover_btn.setEnabled(enabled)
        self.sync_btn.setEnabled(enabled)
        self.clear_btn.setEnabled(enabled)
        self.upload_btn.setEnabled(enabled)
        self.import_btn.setEnabled(enabled)
        self.export_btn.setEnabled(enabled)
        self.kb_checkbox.setEnabled(enabled)

    # ---- Flight Command Handlers with Signals and Session Isolation ----
    @property
    def current_session_id(self) -> str:
        return self._telemetry_session_id or ""

    def _speak_slot(self, text: str):
        if self.tts and getattr(self, "voice_enabled", True):
            try:
                self.tts.say(text)
            except Exception as e:
                log(f"TTS error: {e}")

    def _on_worker_command_completed(self, session_id: str, action: str, ok: bool, msg: str):
        if session_id != self.current_session_id:
            log(f"Worker command '{action}' completed for obsolete session {session_id[:8]} - discarded.")
            return
        self.set_status(f"{action}: {msg}")
        self.refresh()

    def _on_worker_mission_uploaded(self, session_id: str, ok: bool, msg: str):
        if session_id != self.current_session_id:
            return
        self.upload_btn.setEnabled(True)
        if ok:
            self.set_status(f"Mission: {msg}")
            self.start_btn.setEnabled(True)
            QMessageBox.information(
                self, "Mission Verified",
                f"Mission successfully uploaded and readback-verified on vehicle:\n\n{msg}"
            )
            self.worker_bridge.voice_speech.emit("Mission upload and verification complete.")
        else:
            self.set_status(f"Mission upload FAILED: {msg}")
            self.start_btn.setEnabled(False)
            QMessageBox.critical(
                self, "Mission Upload Failed",
                f"Mission upload or readback verification failed:\n\n{msg}"
            )

    def on_arm_disarm(self):
        if not self.vehicle:
            return

        is_armed = telemetry_data.get("armed", False)
        session_id = self.current_session_id
        vehicle = self.vehicle

        if is_armed:
            if is_vehicle_airborne():
                QMessageBox.warning(
                    self,
                    "Disarm Blocked (In Flight)",
                    "The vehicle is currently airborne.\n\n"
                    "Normal DISARM is disabled in flight to prevent accidental mid-air motor cutoff.\n\n"
                    "To land safely, click LAND or RTL.\n"
                    "For a true emergency kill switch, use 'EMERGENCY MOTOR STOP'."
                )
                return
            self.set_status("Disarming vehicle...")
            def _disarm_worker():
                ok, msg = disarm(vehicle, force=False)
                self.worker_bridge.command_completed.emit(session_id, "DISARM", ok, msg)
                if ok:
                    self.worker_bridge.voice_speech.emit("Vehicle disarmed.")
            threading.Thread(target=_disarm_worker, daemon=True).start()
        else:
            self.set_status("Arming vehicle...")
            def _arm_worker():
                ok, msg = arm(vehicle)
                self.worker_bridge.command_completed.emit(session_id, "ARM", ok, msg)
                if ok:
                    self.worker_bridge.voice_speech.emit("Vehicle armed.")
            threading.Thread(target=_arm_worker, daemon=True).start()

    def on_emergency_motor_stop(self):
        if not self.vehicle:
            return
        reply = QMessageBox.critical(
            self,
            "CONFIRM EMERGENCY MOTOR STOP",
            "DANGER: Emergency Motor Stop immediately cuts all motor power in flight!\n\n"
            "The aircraft will fall out of the sky and crash.\n\n"
            "Only use this in a genuine emergency (e.g. runaway, imminent collision, danger to persons).\n\n"
            "Do you want to CUT MOTOR POWER now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel
        )
        if reply == QMessageBox.StandardButton.Yes:
            session_id = self.current_session_id
            vehicle = self.vehicle
            self.set_status("CRITICAL: Dispatching EMERGENCY MOTOR STOP...")
            def _emer_worker():
                ok, msg = emergency_motor_stop(vehicle)
                self.worker_bridge.command_completed.emit(session_id, "EMERGENCY_STOP", ok, msg)
                self.worker_bridge.voice_speech.emit("Emergency motor cutoff dispatched.")
            threading.Thread(target=_emer_worker, daemon=True).start()

    def on_set_mode(self):
        if not self.vehicle:
            return
        mode = self.mode_combo.currentText()
        session_id = self.current_session_id
        vehicle = self.vehicle
        self.set_status(f"Requesting mode {mode}...")
        def _mode_worker():
            ok, msg = set_mode(vehicle, mode)
            self.worker_bridge.command_completed.emit(session_id, f"MODE_{mode}", ok, msg)
        threading.Thread(target=_mode_worker, daemon=True).start()

    def on_takeoff(self):
        if not self.vehicle:
            return
        alt = self.alt_spin.value()
        session_id = self.current_session_id
        vehicle = self.vehicle
        self.set_status(f"Takeoff sequence initiated - target {alt:.1f}m...")
        def _takeoff_worker():
            ok, msg = takeoff(vehicle, alt)
            self.worker_bridge.command_completed.emit(session_id, "TAKEOFF", ok, msg)
            if ok:
                self.worker_bridge.voice_speech.emit(f"Taking off to {alt:.0f} meters.")
        threading.Thread(target=_takeoff_worker, daemon=True).start()

    def on_rtl(self):
        if not self.vehicle:
            return
        session_id = self.current_session_id
        vehicle = self.vehicle
        self.set_status("Requesting AUTO.RTL (Return to Launch)...")
        def _rtl_worker():
            ok, msg = set_mode(vehicle, "AUTO.RTL")
            self.worker_bridge.command_completed.emit(session_id, "RTL", ok, msg)
        threading.Thread(target=_rtl_worker, daemon=True).start()

    def on_land(self):
        if not self.vehicle:
            return
        session_id = self.current_session_id
        vehicle = self.vehicle
        self.set_status("Requesting AUTO.LAND (Landing)...")
        def _land_worker():
            ok, msg = set_mode(vehicle, "AUTO.LAND")
            self.worker_bridge.command_completed.emit(session_id, "LAND", ok, msg)
        threading.Thread(target=_land_worker, daemon=True).start()

    def on_emergency_hold(self):
        if not self.vehicle:
            return
        session_id = self.current_session_id
        vehicle = self.vehicle
        self.set_status("EMERGENCY HOLD triggered: Zeroing velocity setpoints and entering AUTO.LOITER...")
        def _hold_worker():
            ok, msg = emergency_hold(vehicle)
            self.worker_bridge.command_completed.emit(session_id, "HOLD", ok, msg)
            self.worker_bridge.voice_speech.emit("Emergency hold engaged.")
        threading.Thread(target=_hold_worker, daemon=True).start()

    def ensure_offboard(self, on_confirmed=None):
        if not self.vehicle:
            return
        curr_mode = telemetry_data.get("mode", "UNKNOWN").upper().replace("AUTO.", "")
        if curr_mode == "OFFBOARD":
            if on_confirmed:
                on_confirmed()
            return

        session_id = self.current_session_id
        vehicle = self.vehicle
        self.set_status("Warming up stream and requesting OFFBOARD mode...")
        def _offboard_worker():
            ok, msg = set_mode(vehicle, "OFFBOARD")
            self.worker_bridge.command_completed.emit(session_id, "OFFBOARD", ok, msg)
            if ok:
                self.worker_bridge.status_updated.emit("OFFBOARD confirmed. Movement controls active.")
                if on_confirmed:
                    on_confirmed()
            else:
                self.worker_bridge.status_updated.emit(f"OFFBOARD mode switch rejected: {msg}")
        threading.Thread(target=_offboard_worker, daemon=True).start()

    def on_forward(self):
        def _apply():
            ok = offboard_controller.apply_movement_if_confirmed(vx=2.0, yaw_rate=0.0)
            if ok:
                self.set_status("Offboard target: Forward (2.0 m/s)")
        self.ensure_offboard(on_confirmed=_apply)

    def on_yaw_left(self):
        def _apply():
            ok = offboard_controller.apply_movement_if_confirmed(vx=0.0, yaw_rate=-0.5)
            if ok:
                self.set_status("Offboard target: Yaw Left (-0.5 rad/s)")
        self.ensure_offboard(on_confirmed=_apply)

    def on_yaw_right(self):
        def _apply():
            ok = offboard_controller.apply_movement_if_confirmed(vx=0.0, yaw_rate=0.5)
            if ok:
                self.set_status("Offboard target: Yaw Right (+0.5 rad/s)")
        self.ensure_offboard(on_confirmed=_apply)

    def on_hover(self):
        offboard_controller.reset_to_hover()
        self.set_status("Offboard target: Hover (0.0 m/s)")

    def on_kb_toggle(self, checked):
        if not checked:
            self.held_keys.clear()
            offboard_controller.reset_to_hover()
            self.set_status("Keyboard flight disabled: hover setpoint sent.")
        else:
            self.ensure_offboard(on_confirmed=lambda: self.set_status("Keyboard flight active: WASD / QE / IK / Space enabled."))

    def on_map_goto_requested(self, lat, lon):
        if not self.vehicle:
            self.set_status("Guided Fly-To failed: No vehicle connection.")
            return

        if not telemetry_data.get("armed", False) or not is_vehicle_airborne():
            QMessageBox.warning(
                self, "Cannot Reposition",
                "Guided Fly-To requires the vehicle to be armed and airborne.\n\nTake off before sending fly-to targets."
            )
            return

        curr_alt = telemetry_data.get("alt", 10.0)
        target_alt = max(5.0, curr_alt)

        reply = QMessageBox.question(
            self, "Confirm Guided Fly-To",
            f"Fly vehicle to clicked coordinates?\n\nLatitude: {lat:.6f}\nLongitude: {lon:.6f}\nAltitude: {target_alt:.1f} m (Launch Rel)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes
        )
        if reply == QMessageBox.StandardButton.Yes:
            session_id = self.current_session_id
            vehicle = self.vehicle
            self.set_status(f"Guided target dispatched to ({lat:.5f}, {lon:.5f}) @ {target_alt:.1f}m...")
            def _goto_worker():
                ok, msg = goto(vehicle, lat, lon, target_alt)
                self.worker_bridge.command_completed.emit(session_id, "GOTO", ok, msg)
                if ok:
                    self.worker_bridge.voice_speech.emit("Flying to reposition target.")
            threading.Thread(target=_goto_worker, daemon=True).start()

    def set_status(self, msg):
        self.status_label.setText(msg)

    def on_open_preflight_dialog(self):
        dlg = PreflightChecklistDialog(self)
        dlg.exec()

    def on_toggle_voice(self):
        self.voice_enabled = not getattr(self, 'voice_enabled', True)
        if self.voice_enabled:
            self.voice_btn.setText("🔊 VOICE: ON")
            self.voice_btn.setStyleSheet(self._btn_style(THEME['primary'], THEME['panel_bg']))
            self.set_status("Voice notifications enabled.")
        else:
            self.voice_btn.setText("🔇 VOICE: OFF")
            self.voice_btn.setStyleSheet(self._btn_style(THEME['muted'], THEME['panel_bg']))
            self.set_status("Voice notifications muted.")

    # ---- Keyboard Offboard Flight Controls (WASD / QE / IK / Space) ----
    def keyPressEvent(self, event):
        if not hasattr(self, 'kb_checkbox') or not self.kb_checkbox.isChecked() or not self.vehicle:
            super().keyPressEvent(event)
            return
        if self.conn_input.hasFocus() or (hasattr(self, 'setup_view') and self.setup_view.search_bar.hasFocus()):
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

        curr_mode = telemetry_data.get("mode", "").upper().replace("AUTO.", "")
        if curr_mode != "OFFBOARD":
            if any(k in self.held_keys for k in [Qt.Key.Key_W, Qt.Key.Key_S, Qt.Key.Key_A, Qt.Key.Key_D, Qt.Key.Key_Q, Qt.Key.Key_E, Qt.Key.Key_I, Qt.Key.Key_K]):
                self.ensure_offboard(on_confirmed=self.update_keyboard_offboard)
            return

        if any(k in self.held_keys for k in [Qt.Key.Key_W, Qt.Key.Key_S, Qt.Key.Key_A, Qt.Key.Key_D, Qt.Key.Key_Q, Qt.Key.Key_E, Qt.Key.Key_I, Qt.Key.Key_K]):
            ok = offboard_controller.apply_movement_if_confirmed(vx=vx, vy=vy, vz=vz, yaw_rate=yaw_rate)
            if ok:
                self.set_status(f"Keyboard flying: vx={vx:.1f} vy={vy:.1f} vz={vz:.1f} yaw={yaw_rate:.1f}")
        else:
            offboard_controller.reset_to_hover()
            self.set_status("Keyboard offboard: Hover (0.0 m/s)")

    # ---- Live 500ms Refresh ----
    def refresh(self):
        d = telemetry_data

        if not self.vehicle:
            self.power_panel.set('battery', "---", THEME['muted'])
            self.power_panel.set('voltage', "---", THEME['muted'])
            self.power_panel.set('cells', "---", THEME['muted'])
            self.power_panel.set('throttle', "---", THEME['muted'])

            self.gnss_panel.set('fix', "No Link", THEME['danger'])
            self.gnss_panel.set('sats', 0, THEME['muted'])
            self.gnss_panel.set('eph', "---", THEME['muted'])
            self.gnss_panel.set('alt_rel', 0.0, THEME['muted'])
            self.gnss_panel.set('alt_amsl', 0.0, THEME['muted'])

            self.link_panel.set('msg_rate', 0.0, THEME['muted'])
            self.link_panel.set('loss_pct', 0.0, THEME['muted'])
            self.link_panel.set('packets', "---", THEME['muted'])
            self.link_panel.set('vibration', "---", THEME['muted'])
            self.link_panel.set('clipping', "---", THEME['muted'])

            self.gauge_spd.set_value(0.0)
            self.gauge_alt.set_value(0.0)
            self.gauge_throttle.set_value(0.0)
            self.gauge_batt.set_value(0.0)
            self.console_view.refresh_logs()
            return

        # Heartbeat staleness detection
        now_mono = time.monotonic()
        last_hb = d.get('last_heartbeat_monotonic', 0.0)
        hb_age = now_mono - last_hb if last_hb > 0.0 else 999.0
        is_link_lost = (last_hb == 0.0 or hb_age > 3.0)

        if is_link_lost:
            self.conn_status.setText("LINK DEGRADED")
            self.conn_status.setStyleSheet(f"color: {THEME['warning']}; font-weight: bold;")
            self.set_controls_enabled(False)
        else:
            self.conn_status.setText("CONNECTED")
            self.conn_status.setStyleSheet(f"color: {THEME['success']}; font-weight: bold;")
            self.set_controls_enabled(True)

        # Update Gauges
        self.gauge_spd.set_value(d.get('groundspeed', 0.0))
        self.gauge_alt.set_value(d.get('alt', 0.0))
        self.gauge_throttle.set_value(d.get('throttle', 0))
        batt_disp = max(0, d.get('battery', 0)) if d.get('battery', -1) >= 0 else 0
        self.gauge_batt.set_value(batt_disp)

        # Update Analytics Panels
        batt_str = f"{d.get('battery')}%" if d.get('battery', -1) >= 0 else "UNKNOWN"
        self.power_panel.set('battery', batt_str, THEME['success'] if d.get('battery', -1) >= 30 else THEME['danger'])
        self.power_panel.set('voltage', f"{d.get('voltage', 0.0):.1f}", THEME['primary'])

        cells = d.get('battery_cells', [])
        if cells:
            cells_str = " | ".join([f"{c:.2f}V" for c in cells[:4]])
            self.power_panel.set('cells', cells_str, THEME['primary'])
        else:
            self.power_panel.set('cells', "Awaiting BATTERY_STATUS", THEME['muted'])
        self.power_panel.set('throttle', d.get('throttle', 0), THEME['warning'])

        fix_names = {0: "No Fix", 1: "No Fix", 2: "2D Fix", 3: "3D Fix", 4: "DGPS", 5: "RTK Float", 6: "RTK Fixed"}
        self.gnss_panel.set('fix', fix_names.get(d.get('fix_type', 0), "Unknown"), THEME['success'] if d.get('fix_type', 0) >= 3 else THEME['danger'])
        self.gnss_panel.set('sats', d.get('satellites', 0), THEME['primary'])
        eph = d.get('eph', 9999)
        self.gnss_panel.set('eph', f"{eph/100:.1f}" if eph < 9000 else "---", THEME['muted'])
        self.gnss_panel.set('alt_rel', f"{d.get('alt', 0.0):.1f}", THEME['primary'])
        self.gnss_panel.set('alt_amsl', f"{d.get('alt_amsl', 0.0):.1f}", THEME['primary'])

        self.link_panel.set('msg_rate', f"{d.get('message_rate_hz', 0.0):.1f}", THEME['primary'])
        self.link_panel.set('loss_pct', f"{d.get('packet_loss_pct', 0.0):.1f}", THEME['danger'] if d.get('packet_loss_pct', 0.0) > 5.0 else THEME['success'])
        self.link_panel.set('packets', f"{d.get('packets_received', 0)} / {d.get('packets_lost', 0)}", THEME['muted'])

        vib = d.get('vibration', (0.0, 0.0, 0.0))
        if vib != (0.0, 0.0, 0.0):
            self.link_panel.set('vibration', f"{vib[0]:.1f}, {vib[1]:.1f}, {vib[2]:.1f}", THEME['primary'])
        else:
            self.link_panel.set('vibration', "Awaiting VIBRATION", THEME['muted'])

        clip = d.get('clipping', (0, 0, 0))
        self.link_panel.set('clipping', f"{clip[0]}, {clip[1]}, {clip[2]}", THEME['muted'])

        # Update Plots
        elapsed = time.monotonic() - self.start_time
        self.history_time.append(elapsed)
        self.history_alt.append(d.get('alt', 0.0))
        self.history_speed.append(d.get('groundspeed', 0.0))
        if len(self.history_time) > 200:
            self.history_time.pop(0)
            self.history_alt.pop(0)
            self.history_speed.pop(0)
        self.plot_panel.update_plots(self.history_time, self.history_alt, self.history_speed)
        self.analytics_plot_panel.update_plots(self.history_time, self.history_alt, self.history_speed)

        # Update Map & Attitude
        yaw_deg = math.degrees(d.get('yaw', 0.0)) % 360
        self.map_view.update_position(d.get('lat', 0.0), d.get('lon', 0.0), yaw_deg, d.get('groundspeed', 0.0), d.get('alt', 0.0))
        self.plan_map_view.update_position(d.get('lat', 0.0), d.get('lon', 0.0), yaw_deg, d.get('groundspeed', 0.0), d.get('alt', 0.0))
        self.attitude_view.update_attitude(d.get('roll', 0.0), d.get('pitch', 0.0), d.get('yaw', 0.0), d.get('alt', 0.0), d.get('groundspeed', 0.0))

        # Set Home ONCE on confirmed HOME_POSITION or initial arming
        if not self._home_set_on_map:
            if d.get('has_home', False) and (d.get('home_lat', 0.0) != 0.0 or d.get('home_lon', 0.0) != 0.0):
                self.map_view.set_home(d['home_lat'], d['home_lon'])
                self.plan_map_view.set_home(d['home_lat'], d['home_lon'])
                self._home_set_on_map = True
                log(f"Map: Home position set to ({d['home_lat']:.6f}, {d['home_lon']:.6f})")
            elif d.get('armed', False) and d.get('lat', 0.0) != 0.0 and d.get('lon', 0.0) != 0.0:
                self.map_view.set_home(d['lat'], d['lon'])
                self.plan_map_view.set_home(d['lat'], d['lon'])
                self._home_set_on_map = True
                log(f"Map: Launch home position locked to ({d['lat']:.6f}, {d['lon']:.6f})")

        # Update Ribbon Pills
        if d.get('armed', False):
            if is_vehicle_airborne():
                self.ribbon_arm_pill.setText("ARMED (AIRBORNE)")
            else:
                self.ribbon_arm_pill.setText("ARMED (GROUND)")
            self.ribbon_arm_pill.setStyleSheet(self._pill_style(THEME['success'], '#ffffff', THEME['success']))
            self.arm_btn.setText("DISARM")
            self.arm_btn.setStyleSheet(self._btn_style(THEME['danger'], THEME['panel_bg']))
        else:
            self.ribbon_arm_pill.setText("DISARMED")
            self.ribbon_arm_pill.setStyleSheet(self._pill_style(THEME['danger'], THEME['danger']))
            self.arm_btn.setText("ARM")
            self.arm_btn.setStyleSheet(self._btn_style(THEME['success'], THEME['panel_bg']))

        self.ribbon_mode_pill.setText(f"MODE: {d.get('mode', 'UNKNOWN')}")
        self.ribbon_fw_pill.setText(d.get('autopilot_version', 'PX4 AUTOPILOT'))
        gps_str = f"GPS: {d.get('fix_type', 0)}D ({d.get('satellites', 0)}s)"
        self.ribbon_gps_pill.setText(gps_str)
        batt_txt = f"{d.get('battery')}%" if d.get('battery', -1) >= 0 else "---%"
        self.ribbon_batt_pill.setText(f"BATT: {batt_txt} | {d.get('voltage', 0.0):.1f}V")

        # Flight duration timer & distance calculation
        if d.get('armed', False):
            if not self.was_armed:
                self.armed_start_time = time.monotonic()
                self.total_flight_dist = 0.0
                self.last_flight_coord = (d['lat'], d['lon'])

            if self.armed_start_time:
                elapsed_flight = time.monotonic() - self.armed_start_time
                mins = int(elapsed_flight // 60)
                secs = int(elapsed_flight % 60)
                self.ribbon_timer_pill.setText(f"⏱ {mins:02d}:{secs:02d}")

            if self.last_flight_coord and d.get('lat', 0.0) != 0.0 and d.get('lon', 0.0) != 0.0:
                lat1, lon1 = self.last_flight_coord
                lat2, lon2 = d['lat'], d['lon']
                R = 6371e3
                p1, p2 = math.radians(lat1), math.radians(lat2)
                dp = math.radians(lat2 - lat1)
                dl = math.radians(lon2 - lon1)
                a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
                dist_step = 2 * R * math.asin(math.sqrt(a))
                if 0.5 <= dist_step <= 50.0:
                    self.total_flight_dist += dist_step
                    self.last_flight_coord = (lat2, lon2)
            self.ribbon_dist_pill.setText(f"🚩 {self.total_flight_dist:.0f} m")

        # Waypoint progress
        wp_idx = d.get('wp_current', -1)
        total_items = self.wp_list.count()
        if wp_idx >= 0 and total_items > 0:
            if wp_idx < total_items:
                self.wp_list.setCurrentRow(wp_idx)
                item_text = self.wp_list.item(wp_idx).text()
                active_name = item_text.split(':')[0]
                self.wp_progress_label.setText(f"Active: {active_name} (Item {wp_idx+1} / {total_items})")
            else:
                self.wp_progress_label.setText(f"Active: Item {wp_idx}")
        else:
            self.wp_progress_label.setText("Active Waypoint: ---")

        # Voice status changes
        if self.tts and self.voice_enabled:
            current_mode = d.get('mode', 'UNKNOWN')
            if current_mode != self.last_spoken_mode and current_mode not in ('UNKNOWN', 'DISCONNECTED'):
                self.tts.say(f"Flight mode {current_mode.replace('.', ' ')}.")
                self.last_spoken_mode = current_mode

        self.was_link_lost = is_link_lost
        self.was_armed = d.get('armed', False)
        self.console_view.refresh_logs()

    def closeEvent(self, event):
        if self.vehicle is not None and telemetry_data.get('armed', False):
            reply = QMessageBox.question(
                self, 'Warning',
                "Drone is still ARMED! Are you sure you want to exit the GCS?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.disconnect_vehicle()
                event.accept()
            else:
                event.ignore()
        else:
            self.disconnect_vehicle()
            event.accept()


def launch_gui(vehicle=None):
    app = QApplication(sys.argv)
    from gcs.paths import resource_path
    from PyQt6.QtGui import QFontDatabase, QFont
    font_files = [
        "GoogleSansCode-Regular.ttf",
        "GoogleSansCode-Medium.ttf",
        "GoogleSansCode-Bold.ttf"
    ]
    family_name = None
    for f in font_files:
        f_path = resource_path(os.path.join("gcs", "ui", "fonts", f))
        if os.path.exists(f_path):
            fid = QFontDatabase.addApplicationFont(f_path)
            if fid != -1 and family_name is None:
                families = QFontDatabase.applicationFontFamilies(fid)
                if families:
                    family_name = families[0]
    if family_name:
        app.setFont(QFont(family_name))

    window = GCSWindow(vehicle)
    window.show()
    app.exec()
