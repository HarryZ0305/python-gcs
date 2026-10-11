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
    QGraphicsDropShadowEffect, QInputDialog, QFileDialog, QSplitter
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
    cancel_current_session, reset_telemetry_data, read_telemetry,
    get_stream_freshness
)
from gcs.commands import (
    arm, disarm, emergency_motor_stop, set_mode, takeoff, goto, emergency_hold,
    set_offboard_targets, reset_offboard_targets, stop_streamer,
    _ensure_streamer, request_all_parameters, offboard_controller,
    upload_mission
)
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
from gcs.ui.theme import (
    get_theme, set_active_theme, get_app_stylesheet,
    get_button_style, get_pill_style, FONT_FAMILY_PRIMARY, FONT_FAMILY_MONO,
    THEME_DARK, THEME_LIGHT
)
from gcs.ui.flight_instruments import InstrumentContainer
from gcs.ui.pip_workspace import PipWorkspace
from gcs.ui.plan_view import PlanView
from gcs.ui.analyze_view import AnalyzeView
from gcs.ui.settings_view import SettingsView

THEME = {
    'bg':           '#090d16',
    'panel_bg':     '#111827',
    'panel_border': '#1f2937',
    'primary':      '#38bdf8',
    'success':      '#34d399',
    'warning':      '#fbbf24',
    'danger':       '#f87171',
    'muted':        '#94a3b8',
    'dark_text':    '#f8fafc',
    'plot_bg':      '#0f172a',
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
        t = get_theme()
        self.setStyleSheet(f"""
            #StatPanelContainer {{
                background-color: {t['surface']};
                border: 1px solid {t['border']};
                border-radius: 8px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        t_lbl = QLabel(title)
        t_lbl.setStyleSheet(f"color: {t['primary']}; font-family: {FONT_FAMILY_PRIMARY}; font-size: 11px; font-weight: bold; border: none; background: transparent;")
        layout.addWidget(t_lbl)

        self.labels = {}
        for key, name, unit in items:
            row = QHBoxLayout()
            row.setSpacing(4)
            name_lbl = QLabel(name)
            name_lbl.setStyleSheet(f"color: {t['text_secondary']}; font-family: {FONT_FAMILY_PRIMARY}; font-size: 11px; font-weight: 500; border: none; background: transparent;")
            val_lbl = QLabel(f"-- {unit}".strip())
            val_lbl.setStyleSheet(f"color: {t['text']}; font-family: {FONT_FAMILY_MONO}; font-size: 11px; font-weight: bold; border: none; background: transparent;")
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
        t = get_theme()
        c = color or t['text']
        lbl.setStyleSheet(f"color: {c}; font-family: {FONT_FAMILY_MONO}; font-size: 11px; font-weight: bold; border: none; background: transparent;")


class PremiumViewContainer(QFrame):
    def __init__(self, inner_widget, object_name, parent=None):
        super().__init__(parent)
        self.setObjectName(object_name)
        t = get_theme()
        self.setStyleSheet(f"""
            #{object_name} {{
                background-color: {t['surface']};
                border: 1px solid {t['border']};
                border-radius: 8px;
            }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(inner_widget)


class TelemetryPlotPanel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("PlotPanelContainer")
        t = get_theme()
        self.setStyleSheet(f"""
            #PlotPanelContainer {{
                background-color: {t['surface']};
                border: 1px solid {t['border']};
                border-radius: 8px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        header = QHBoxLayout()
        title = QLabel("REAL-TIME ALTITUDE & SPEED")
        title.setStyleSheet(f"color: {t['primary']}; font-family: {FONT_FAMILY_PRIMARY}; font-size: 10px; font-weight: bold; border: none; background: transparent;")
        header.addWidget(title)
        header.addStretch(1)

        legend = QLabel("— Alt (Rel)  — Speed")
        legend.setStyleSheet(f"color: {t['text_muted']}; font-family: {FONT_FAMILY_MONO}; font-size: 9px; border: none; background: transparent;")
        header.addWidget(legend)
        layout.addLayout(header)

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground(t['plot_bg'])
        self.plot_widget.showGrid(x=True, y=True, alpha=0.15)
        self.plot_widget.getAxis('left').setPen(pg.mkPen(color=t['border_strong'], width=1))
        self.plot_widget.getAxis('bottom').setPen(pg.mkPen(color=t['border_strong'], width=1))
        self.plot_widget.getAxis('left').setTextPen(t['text_muted'])
        self.plot_widget.getAxis('bottom').setTextPen(t['text_muted'])

        self.alt_curve = self.plot_widget.plot(pen=pg.mkPen('#0284c7', width=1.5))
        self.speed_curve = self.plot_widget.plot(pen=pg.mkPen('#d97706', width=1.5))
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
        self.resize(1440, 920)
        self.setMinimumSize(1100, 700)

        # Apply Global Master Stylesheet
        self.setStyleSheet(get_app_stylesheet())

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

        # Fast Timer for 30 FPS Instrument Rendering
        self.fast_timer = QTimer(self)
        self.fast_timer.timeout.connect(self._fast_instrument_update)
        self.fast_timer.start(33)

        # Standard Timer for Diagnostics & Heartbeat
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(250)

        if self.vehicle:
            self.on_connected(self.vehicle)

    def _btn_style(self, text_color, bg_color):
        return get_button_style('primary', 'sm')

    def _input_style(self):
        t = get_theme()
        return f"""
            QSpinBox, QDoubleSpinBox, QComboBox, QLineEdit {{
                background-color: {t['surface']}; color: {t['text']};
                border: 1px solid {t['border']}; border-radius: 4px;
                padding: 4px 8px; font-family: {FONT_FAMILY_PRIMARY}; font-size: 11px;
            }}
        """

    def _pill_style(self, border_color, text_color, bg_color=None):
        bg = f"background-color: {bg_color};" if bg_color else "background-color: transparent;"
        return f"""
            QLabel {{
                border: 1.5px solid {border_color}; border-radius: 12px;
                color: {text_color}; {bg}
                font-family: {FONT_FAMILY_PRIMARY}; font-size: 10px; font-weight: bold;
                padding: 2px 10px;
            }}
        """

    def _build_ui(self):
        t = get_theme()
        root = QWidget()
        self.setCentralWidget(root)
        main_layout = QVBoxLayout(root)
        main_layout.setContentsMargins(10, 8, 10, 8)
        main_layout.setSpacing(6)

        # 1. Top Ribbon Strip (Brand, Vehicle ID, Connection, Status Pills, Highest Alert)
        ribbon_frame = QFrame()
        ribbon_frame.setObjectName("RibbonFrame")
        ribbon_frame.setStyleSheet(f"#RibbonFrame {{ background-color: {t['surface']}; border: 1px solid {t['border']}; border-radius: 8px; }}")
        rf_layout = QHBoxLayout(ribbon_frame)
        rf_layout.setContentsMargins(8, 4, 8, 4)
        rf_layout.setSpacing(6)

        # Brand & Vehicle Identity
        brand_lbl = QLabel("PYTHON GCS")
        brand_lbl.setStyleSheet(f"color: {t['primary']}; font-family: {FONT_FAMILY_PRIMARY}; font-size: 13px; font-weight: 800; border: none; background: transparent;")
        rf_layout.addWidget(brand_lbl)

        # Vehicle Identity Badge
        self.vehicle_id_badge = QLabel("SYS 1 PX4")
        self.vehicle_id_badge.setStyleSheet(get_pill_style('primary'))
        rf_layout.addWidget(self.vehicle_id_badge)

        # Connection Profile selector
        self.profile_combo = QComboBox()
        for name, uri in CONNECTION_PROFILES:
            self.profile_combo.addItem(name, uri)
        self.profile_combo.currentIndexChanged.connect(self._on_profile_changed)
        rf_layout.addWidget(self.profile_combo)

        # Connection input
        self.conn_input = QLineEdit("udpin:0.0.0.0:14540")
        self.conn_input.setFixedWidth(135)
        rf_layout.addWidget(self.conn_input)

        self.conn_btn = QPushButton("CONNECT")
        self.conn_btn.setFixedHeight(28)
        self.conn_btn.setStyleSheet(get_button_style('primary', 'sm'))
        self.conn_btn.clicked.connect(self.on_connect_toggle)
        rf_layout.addWidget(self.conn_btn)

        self.conn_status = QLabel("DISCONNECTED")
        self.conn_status.setStyleSheet(f"color: {t['danger']}; font-weight: bold; font-family: {FONT_FAMILY_PRIMARY}; font-size: 11px; border: none;")
        rf_layout.addWidget(self.conn_status)

        rf_layout.addStretch(1)

        # Highest Priority Alert Banner (prominently visible)
        self.alert_banner = QLabel("SYSTEM NOMINAL")
        self.alert_banner.setStyleSheet(get_pill_style('neutral'))
        rf_layout.addWidget(self.alert_banner)

        # Status Pills
        self.ribbon_fw_pill = QLabel("PX4 AUTOPILOT")
        self.ribbon_fw_pill.setStyleSheet(get_pill_style('neutral'))
        rf_layout.addWidget(self.ribbon_fw_pill)

        self.ribbon_arm_pill = QLabel("DISARMED")
        self.ribbon_arm_pill.setStyleSheet(get_pill_style('danger', filled=True))
        rf_layout.addWidget(self.ribbon_arm_pill)

        self.ribbon_mode_pill = QLabel("MODE: UNKNOWN")
        self.ribbon_mode_pill.setStyleSheet(get_pill_style('primary'))
        rf_layout.addWidget(self.ribbon_mode_pill)

        self.ribbon_gps_pill = QLabel("GPS: NO FIX (0s)")
        self.ribbon_gps_pill.setStyleSheet(get_pill_style('neutral'))
        rf_layout.addWidget(self.ribbon_gps_pill)

        self.ribbon_batt_pill = QLabel("BATT: ---% | --.-V")
        self.ribbon_batt_pill.setStyleSheet(get_pill_style('neutral'))
        rf_layout.addWidget(self.ribbon_batt_pill)

        self.ribbon_timer_pill = QLabel("TIME: 00:00")
        self.ribbon_timer_pill.setStyleSheet(get_pill_style('neutral'))
        rf_layout.addWidget(self.ribbon_timer_pill)

        self.ribbon_dist_pill = QLabel("HOME: --- m")
        self.ribbon_dist_pill.setStyleSheet(get_pill_style('neutral'))
        rf_layout.addWidget(self.ribbon_dist_pill)

        main_layout.addWidget(ribbon_frame)

        # 2. Main Workspaces Navigation (FLY, PLAN, VEHICLE SETUP, ANALYZE, SETTINGS)
        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(self._on_tab_changed)

        self._build_fly_tab()

        # Dedicated Plan Workspace
        self.plan_view = PlanView(self.vehicle)
        self.plan_map_view = self.plan_view.map_view
        self.plan_view.mission_uploaded.connect(lambda ok, msg: self._on_worker_mission_uploaded(self.current_session_id, ok, msg))
        self.tabs.addTab(self.plan_view, "PLAN")

        # Vehicle Setup Workspace
        self.setup_view = SetupView(self.vehicle)
        self.tabs.addTab(self.setup_view, "VEHICLE SETUP")

        # Flight Analytics & Log Suite
        self.analyze_view = AnalyzeView()
        self.tabs.addTab(self.analyze_view, "ANALYZE")

        # Settings Workspace
        self.settings_view = SettingsView()
        self.settings_view.theme_changed.connect(self._on_theme_toggled)
        self.settings_view.video_source_changed.connect(self.camera_view.set_stream_source)
        self.tabs.addTab(self.settings_view, "SETTINGS")

        main_layout.addWidget(self.tabs, stretch=1)

    def _on_theme_toggled(self, is_dark: bool):
        self.setStyleSheet(get_app_stylesheet())

    def _on_tab_changed(self, idx: int):
        # Safety: whenever leaving Fly tab, clear keyboard held keys and offboard targets
        if idx != 0 and hasattr(self, 'held_keys') and self.held_keys:
            self.held_keys.clear()
            self.update_keyboard_offboard()

    def _on_profile_changed(self, idx):
        uri = self.profile_combo.currentData()
        if uri:
            self.conn_input.setText(uri)

    def _build_fly_tab(self):
        t = get_theme()
        fly_widget = QWidget()
        fly_layout = QVBoxLayout(fly_widget)
        fly_layout.setContentsMargins(0, 4, 0, 0)
        fly_layout.setSpacing(6)

        # Main Flight Splitter: Left Instrument & Action Rail + Center Dominant PiP Workspace
        fly_splitter = QSplitter(Qt.Orientation.Horizontal)

        # --- LEFT RAIL: Flight Instruments & Contextual Action Controls ---
        self.left_col_widget = QWidget()
        left_col = QVBoxLayout(self.left_col_widget)
        left_col.setContentsMargins(0, 0, 0, 0)
        left_col.setSpacing(6)

        # Cockpit Primary Flight Display (PFD) / 3D CAD toggle container
        self.instrument_container = InstrumentContainer()
        self.attitude_view = self.instrument_container.cad_view
        left_col.addWidget(self.instrument_container)

        # Action Card: Flight Commands
        action_card = QFrame()
        action_card.setObjectName("FlyActionCard")
        action_card.setStyleSheet(f"#FlyActionCard {{ background-color: {t['surface']}; border: 1px solid {t['border']}; border-radius: 8px; }}")
        ac_layout = QVBoxLayout(action_card)
        ac_layout.setContentsMargins(8, 8, 8, 8)
        ac_layout.setSpacing(6)

        # Row 1: Mode Switcher
        mode_row = QHBoxLayout()
        self.mode_combo = QComboBox()
        self.mode_combo.addItems([
            "HOLD", "POSCTL", "ALTCTL", "STABILIZED", "MANUAL",
            "OFFBOARD", "AUTO.TAKEOFF", "AUTO.LOITER", "AUTO.RTL",
            "AUTO.LAND", "AUTO.MISSION"
        ])
        self.mode_btn = QPushButton("SET MODE")
        self.mode_btn.setFixedHeight(26)
        self.mode_btn.setStyleSheet(get_button_style('secondary', 'sm'))
        self.mode_btn.clicked.connect(self.on_set_mode)
        mode_row.addWidget(self.mode_combo, stretch=1)
        mode_row.addWidget(self.mode_btn)
        ac_layout.addLayout(mode_row)

        # Row 2: Arm, Altitude Spin, Takeoff
        arm_row = QHBoxLayout()
        self.arm_btn = QPushButton("ARM")
        self.arm_btn.setFixedHeight(30)
        self.arm_btn.setStyleSheet(get_button_style('success', 'sm'))
        self.arm_btn.clicked.connect(self.on_arm_disarm)

        self.alt_spin = QDoubleSpinBox()
        self.alt_spin.setRange(2.0, 100.0)
        self.alt_spin.setValue(5.0)
        self.alt_spin.setSuffix(" m")

        self.takeoff_btn = QPushButton("TAKEOFF")
        self.takeoff_btn.setFixedHeight(30)
        self.takeoff_btn.setStyleSheet(get_button_style('primary', 'sm'))
        self.takeoff_btn.clicked.connect(self.on_takeoff)

        arm_row.addWidget(self.arm_btn)
        arm_row.addWidget(self.alt_spin)
        arm_row.addWidget(self.takeoff_btn)
        ac_layout.addLayout(arm_row)

        # Row 3: Prominent HOLD, RTL, LAND
        nav_row = QHBoxLayout()
        self.hold_btn = QPushButton("HOLD (LOITER)")
        self.hold_btn.setFixedHeight(30)
        self.hold_btn.setStyleSheet(get_button_style('warning', 'sm'))
        self.hold_btn.clicked.connect(self.on_emergency_hold)

        self.rtl_btn = QPushButton("RTL")
        self.rtl_btn.setFixedHeight(30)
        self.rtl_btn.setStyleSheet(get_button_style('secondary', 'sm'))
        self.rtl_btn.clicked.connect(self.on_rtl)

        self.land_btn = QPushButton("LAND")
        self.land_btn.setFixedHeight(30)
        self.land_btn.setStyleSheet(get_button_style('secondary', 'sm'))
        self.land_btn.clicked.connect(self.on_land)

        nav_row.addWidget(self.hold_btn)
        nav_row.addWidget(self.rtl_btn)
        nav_row.addWidget(self.land_btn)
        ac_layout.addLayout(nav_row)

        # Row 4: Start Mission Button
        self.start_btn = QPushButton("START MISSION")
        self.start_btn.setFixedHeight(28)
        self.start_btn.setStyleSheet(get_button_style('primary', 'sm'))
        self.start_btn.setEnabled(False) # Enabled upon verified mission
        self.start_btn.clicked.connect(self.on_start_mission)
        ac_layout.addWidget(self.start_btn)

        # Row 5: Emergency Motor Stop
        self.emer_stop_btn = QPushButton("EMERGENCY MOTOR CUTOFF (KILL)")
        self.emer_stop_btn.setFixedHeight(28)
        self.emer_stop_btn.setStyleSheet(get_button_style('danger', 'sm'))
        self.emer_stop_btn.clicked.connect(self.on_emergency_motor_stop)
        ac_layout.addWidget(self.emer_stop_btn)

        # Row 6: Keyboard Flight Safeguard Checkbox & Banner
        kb_box = QFrame()
        kb_box.setStyleSheet(f"background-color: {t['surface_elevated']}; border: 1px solid {t['border']}; border-radius: 6px; padding: 4px;")
        kb_l = QVBoxLayout(kb_box)
        kb_l.setContentsMargins(6, 4, 6, 4)
        kb_l.setSpacing(4)

        self.kb_checkbox = QCheckBox("Enable Keyboard Flight Control")
        self.kb_checkbox.toggled.connect(self.on_kb_toggle)
        kb_l.addWidget(self.kb_checkbox)

        self.kb_banner = QLabel("KEYS INHIBITED — Opt-in required")
        self.kb_banner.setStyleSheet(f"color: {t['text_muted']}; font-size: 10px; font-weight: bold;")
        kb_l.addWidget(self.kb_banner)
        ac_layout.addWidget(kb_box)

        # Row 7: Preflight & Voice Controls
        pre_row = QHBoxLayout()
        self.preflight_btn = QPushButton("PRE-FLIGHT CHECKLIST")
        self.preflight_btn.setFixedHeight(26)
        self.preflight_btn.setStyleSheet(get_button_style('primary', 'sm'))
        self.preflight_btn.clicked.connect(self.on_open_preflight_dialog)
        pre_row.addWidget(self.preflight_btn)

        self.voice_btn = QPushButton("VOICE: ON")
        self.voice_btn.setFixedHeight(26)
        self.voice_btn.setStyleSheet(get_button_style('secondary', 'sm'))
        self.voice_btn.clicked.connect(self.on_toggle_voice)
        pre_row.addWidget(self.voice_btn)
        ac_layout.addLayout(pre_row)

        self.status_label = QLabel("System ready.")
        self.status_label.setStyleSheet(f"color: {t['text_secondary']}; font-size: 11px;")
        ac_layout.addWidget(self.status_label)

        left_col.addWidget(action_card)
        left_col.addStretch(1)

        self.left_col_widget.setMinimumWidth(320)
        self.left_col_widget.setMaximumWidth(380)
        fly_splitter.addWidget(self.left_col_widget)

        # --- CENTER / DOMINANT AREA: Tactical Map & Picture-in-Picture Video ---
        center_container = QWidget()
        center_layout = QVBoxLayout(center_container)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(4)

        self.map_view = MapView()
        self.map_view.goto_requested.connect(self.on_map_goto_requested)

        self.camera_view = CameraView()
        self.camera_view.set_stream_source("test") # Test pattern by default

        self.pip_workspace = PipWorkspace(self.map_view, self.camera_view)
        center_layout.addWidget(self.pip_workspace, stretch=1)

        # Bottom Expandable Diagnostics Drawer (Collapsible for maximum map area)
        self.diag_drawer = QFrame()
        self.diag_drawer.setObjectName("DiagnosticsDrawer")
        self.diag_drawer.setFixedHeight(180)
        self.diag_drawer.setStyleSheet(f"#DiagnosticsDrawer {{ background-color: {t['surface']}; border: 1px solid {t['border']}; border-radius: 8px; }}")
        dd_layout = QHBoxLayout(self.diag_drawer)
        dd_layout.setContentsMargins(6, 6, 6, 6)
        dd_layout.setSpacing(6)

        # Analytics Mini Plots
        self.plot_panel = TelemetryPlotPanel()
        self.analytics_plot_panel = self.plot_panel
        dd_layout.addWidget(self.plot_panel, stretch=1)

        # Real-time Console Log
        self.console_view = ConsoleView()
        dd_layout.addWidget(self.console_view, stretch=1)

        center_layout.addWidget(self.diag_drawer)

        # Drawer Collapse / Expand Button
        drawer_bar = QHBoxLayout()
        self.btn_toggle_drawer = QPushButton("▲ HIDE DIAGNOSTICS & CONSOLE")
        self.btn_toggle_drawer.setFixedHeight(22)
        self.btn_toggle_drawer.setStyleSheet(get_button_style('secondary', 'sm'))
        self.btn_toggle_drawer.clicked.connect(self._toggle_diagnostics_drawer)
        drawer_bar.addWidget(self.btn_toggle_drawer)
        drawer_bar.addStretch(1)

        self.load_mbtiles_btn = QPushButton("LOAD MBTILES")
        self.load_mbtiles_btn.setFixedHeight(22)
        self.load_mbtiles_btn.setStyleSheet(get_button_style('secondary', 'sm'))
        self.load_mbtiles_btn.clicked.connect(self.on_load_offline_mbtiles)
        drawer_bar.addWidget(self.load_mbtiles_btn)

        self.export_kml_btn = QPushButton("EXPORT KML")
        self.export_kml_btn.setFixedHeight(22)
        self.export_kml_btn.setStyleSheet(get_button_style('secondary', 'sm'))
        self.export_kml_btn.clicked.connect(self.on_export_flight_trail)
        drawer_bar.addWidget(self.export_kml_btn)

        center_layout.addLayout(drawer_bar)
        fly_splitter.addWidget(center_container)
        fly_splitter.setStretchFactor(0, 1) # Rail takes 25%
        fly_splitter.setStretchFactor(1, 4) # Dominant Map takes 75%

        fly_layout.addWidget(fly_splitter)
        self.tabs.addTab(fly_widget, "FLY")

        # Fallback gauges for test compatibility
        self.gauge_spd = ArcGauge("SPEED", "m/s", 0, 25, THEME['primary'])
        self.gauge_alt = ArcGauge("ALT REL", "m", 0, 100, THEME['primary'])
        self.gauge_throttle = ArcGauge("THROTTLE", "%", 0, 100, THEME['warning'])
        self.gauge_batt = ArcGauge("BATTERY", "%", 0, 100, THEME['success'])
        self.power_panel = StatPanel("POWER", [('battery', 'Battery', '%'), ('voltage', 'Voltage', 'V')])
        self.gnss_panel = StatPanel("GNSS", [('fix', 'Fix', ''), ('sats', 'Satellites', '')])
        self.link_panel = StatPanel("LINK", [('msg_rate', 'Rate', 'Hz'), ('loss_pct', 'Loss', '%')])

    def _toggle_diagnostics_drawer(self):
        if self.diag_drawer.isVisible():
            self.diag_drawer.hide()
            self.btn_toggle_drawer.setText("▼ SHOW DIAGNOSTICS & CONSOLE")
        else:
            self.diag_drawer.show()
            self.btn_toggle_drawer.setText("▲ HIDE DIAGNOSTICS & CONSOLE")

    def _fast_instrument_update(self):
        """High-rate 30 Hz flight attitude & PFD instrument refresh."""
        d = telemetry_data
        freshness = get_stream_freshness()
        is_stale = not freshness['attitude_valid']

        self.instrument_container.update_attitude(
            d.get('roll', 0.0),
            d.get('pitch', 0.0),
            d.get('yaw', 0.0),
            d.get('alt', 0.0),
            d.get('groundspeed', 0.0),
            climb=d.get('climb_rate', 0.0),
            mode=d.get('mode', 'UNKNOWN'),
            armed=d.get('armed', False),
            is_stale=is_stale
        )

    def on_connect_toggle(self):
        if self.vehicle:
            self.disconnect_vehicle()
        else:
            conn_str = self.conn_input.text().strip()
            if not conn_str:
                self.set_status("Please specify a valid connection string.")
                return
            self.conn_btn.setEnabled(False)
            self.conn_btn.setText("CONNECTING...")
            self.conn_status.setText("CONNECTING...")
            t = get_theme()
            self.conn_status.setStyleSheet(f"color: {t['warning']}; font-weight: bold;")
            self.set_status(f"Opening MAVLink connection to {conn_str}...")

            self.conn_worker = ConnectionWorker(conn_str)
            self.conn_worker.connected.connect(self.on_connected)
            self.conn_worker.failed.connect(self.on_connection_failed)
            self.conn_worker.start()

    def on_connected(self, vehicle):
        self.vehicle = vehicle
        self._telemetry_session_id = create_new_session()
        self.conn_btn.setEnabled(True)
        self.conn_btn.setText("DISCONNECT")
        t = get_theme()
        self.conn_btn.setStyleSheet(get_button_style('danger', 'sm'))
        self.conn_status.setText("CONNECTED")
        self.conn_status.setStyleSheet(f"color: {t['success']}; font-weight: bold;")
        self.set_status("Connected to flight controller.")

        # Update sub-views
        self.setup_view.set_vehicle(vehicle)
        self.plan_view.set_vehicle(vehicle)

        # Start telemetry reader thread
        threading.Thread(
            target=read_telemetry,
            args=(vehicle, self._telemetry_session_id),
            daemon=True
        ).start()

    def on_connection_failed(self, error_msg):
        self.conn_btn.setEnabled(True)
        self.conn_btn.setText("CONNECT")
        t = get_theme()
        self.conn_btn.setStyleSheet(get_button_style('primary', 'sm'))
        self.conn_status.setText("FAILED")
        self.conn_status.setStyleSheet(f"color: {t['danger']}; font-weight: bold;")
        self.set_status(f"Connection failed: {error_msg}")

    def disconnect_vehicle(self):
        cancel_current_session()
        stop_streamer()
        self.vehicle = None
        self._telemetry_session_id = None
        self.conn_btn.setText("CONNECT")
        t = get_theme()
        self.conn_btn.setStyleSheet(get_button_style('primary', 'sm'))
        self.conn_status.setText("DISCONNECTED")
        self.conn_status.setStyleSheet(f"color: {t['danger']}; font-weight: bold;")
        self.set_status("Disconnected from vehicle.")

        self.setup_view.set_vehicle(None)
        self.plan_view.set_vehicle(None)
        self.refresh()

    def set_controls_enabled(self, enabled: bool):
        self.arm_btn.setEnabled(enabled)
        self.takeoff_btn.setEnabled(enabled)
        self.mode_btn.setEnabled(enabled)
        self.rtl_btn.setEnabled(enabled)
        self.land_btn.setEnabled(enabled)
        self.hold_btn.setEnabled(enabled)

    @property
    def current_session_id(self) -> str:
        return self._telemetry_session_id or ""

    def _speak_slot(self, text: str):
        if self.voice_enabled and self.tts:
            try:
                self.tts.say(text)
            except Exception:
                pass

    def _on_worker_command_completed(self, session_id: str, action: str, ok: bool, msg: str):
        if session_id != self.current_session_id:
            return
        status_msg = f"{action}: {'SUCCESS' if ok else 'FAILED'} — {msg}"
        self.set_status(status_msg)
        self.analyze_view.log_event(action, "SUCCESS" if ok else f"FAILED: {msg}")

    def _on_worker_mission_uploaded(self, session_id: str, ok: bool, msg: str):
        if session_id != self.current_session_id:
            return
        self.start_btn.setEnabled(ok)
        self.plan_view.on_upload_completed(ok, msg)
        self.set_status(f"Mission Transfer: {'VERIFIED' if ok else 'FAILED'} — {msg}")
        self.analyze_view.log_event("MISSION_UPLOAD", "VERIFIED" if ok else f"FAILED: {msg}")

    def on_arm_disarm(self):
        if not self.vehicle:
            return
        is_currently_armed = telemetry_data.get('armed', False)
        session_id = self.current_session_id
        vehicle = self.vehicle

        if is_currently_armed:
            if is_vehicle_airborne():
                reply = QMessageBox.warning(
                    self,
                    "Airborne Disarm Blocked",
                    "The vehicle is currently AIRBORNE. Regular disarm is blocked for safety.\n"
                    "Use LAND or RTL, or use Emergency Motor Cutoff if an immediate crash is required.",
                    QMessageBox.StandardButton.Ok
                )
                return

            self.set_status("Requesting grounded disarm...")
            def _disarm_worker():
                ok, msg = disarm(vehicle, force=False)
                self.worker_bridge.command_completed.emit(session_id, "DISARM", ok, msg)
                if ok:
                    self.worker_bridge.voice_speech.emit("Vehicle disarmed.")
            threading.Thread(target=_disarm_worker, daemon=True).start()
        else:
            self.set_status("Requesting arm...")
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
            "CRITICAL: Emergency Motor Cutoff",
            "WARNING: This will immediately cut all motor power to the drone in mid-air!\n"
            "The aircraft will fall immediately. Are you sure you want to proceed?",
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
        self.set_status("HOLD triggered: Zeroing velocity setpoints and entering AUTO.LOITER...")
        def _hold_worker():
            ok, msg = emergency_hold(vehicle)
            self.worker_bridge.command_completed.emit(session_id, "HOLD", ok, msg)
            self.worker_bridge.voice_speech.emit("Hold engaged.")
        threading.Thread(target=_hold_worker, daemon=True).start()

    def on_start_mission(self):
        if not self.vehicle:
            return
        from gcs.commands import start_mission
        session_id = self.current_session_id
        vehicle = self.vehicle
        self.set_status("Starting mission execution...")
        def _start_worker():
            ok, msg = start_mission(vehicle)
            self.worker_bridge.command_completed.emit(session_id, "START_MISSION", ok, msg)
        threading.Thread(target=_start_worker, daemon=True).start()

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
                self.worker_bridge.status_updated.emit("OFFBOARD confirmed. Movement active.")
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
            ok = offboard_controller.apply_movement_if_confirmed(yaw_rate=-0.5)
            if ok:
                self.set_status("Offboard target: Yaw Left (-0.5 rad/s)")
        self.ensure_offboard(on_confirmed=_apply)

    def on_yaw_right(self):
        def _apply():
            ok = offboard_controller.apply_movement_if_confirmed(yaw_rate=0.5)
            if ok:
                self.set_status("Offboard target: Yaw Right (+0.5 rad/s)")
        self.ensure_offboard(on_confirmed=_apply)

    def on_hover(self):
        reset_offboard_targets()
        self.set_status("Offboard targets zeroed to hover.")

    def on_kb_toggle(self, checked: bool):
        t = get_theme()
        if checked:
            self.kb_banner.setText("⚠️ KEYBOARD FLIGHT ARMED (WASD/QE/IK/Space)")
            self.kb_banner.setStyleSheet(f"color: {t['warning']}; font-size: 10px; font-weight: bold;")
            self.ensure_offboard()
        else:
            self.kb_banner.setText("KEYS INHIBITED — Opt-in required")
            self.kb_banner.setStyleSheet(f"color: {t['text_muted']}; font-size: 10px; font-weight: bold;")
            self.held_keys.clear()
            self.update_keyboard_offboard()

    def on_map_goto_requested(self, lat: float, lon: float):
        if not self.vehicle:
            return
        alt = self.alt_spin.value()
        session_id = self.current_session_id
        vehicle = self.vehicle
        self.set_status(f"Guided Goto initiated to ({lat:.5f}, {lon:.5f}) @ {alt:.1f}m...")
        def _goto_worker():
            ok, msg = goto(vehicle, lat, lon, alt)
            self.worker_bridge.command_completed.emit(session_id, "GOTO", ok, msg)
        threading.Thread(target=_goto_worker, daemon=True).start()

    def set_status(self, msg: str):
        self.status_label.setText(msg)
        log(f"GUI: {msg}")

    def on_open_preflight_dialog(self):
        dlg = PreflightChecklistDialog(self)
        dlg.exec()

    def on_toggle_voice(self):
        self.voice_enabled = not self.voice_enabled
        self.voice_btn.setText(f"VOICE: {'ON' if self.voice_enabled else 'OFF'}")

    def on_load_offline_mbtiles(self):
        self.settings_view._on_browse_mbtiles()

    def on_export_flight_trail(self):
        fn, _ = QFileDialog.getSaveFileName(self, "Export Flight Trail KML", "", "KML Files (*.kml)")
        if fn:
            if not fn.endswith(".kml"):
                fn += ".kml"
            ok = logger_instance.export_kml(fn)
            if ok:
                QMessageBox.information(self, "KML Exported", f"Successfully exported flight trail to:\n{fn}")

    # ---- Robust Keyboard Safeguards ----
    def keyPressEvent(self, event):
        # 1. Require explicit checkbox enable and connected vehicle
        if not hasattr(self, 'kb_checkbox') or not self.kb_checkbox.isChecked() or not self.vehicle:
            super().keyPressEvent(event)
            return

        # 2. Require active tab to be FLY (index 0)
        if hasattr(self, 'tabs') and self.tabs.currentIndex() != 0:
            super().keyPressEvent(event)
            return

        # 3. Require that focus is NOT in any child text/spin/table widget
        focus_w = QApplication.focusWidget()
        if focus_w is not None:
            from PyQt6.QtWidgets import QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox, QComboBox, QAbstractItemView
            if isinstance(focus_w, (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox, QComboBox, QAbstractItemView)):
                super().keyPressEvent(event)
                return

        # 4. Require that no modal dialog is active
        if QApplication.activeModalWidget() is not None:
            super().keyPressEvent(event)
            return

        key = event.key()
        if key in [Qt.Key.Key_W, Qt.Key.Key_S, Qt.Key.Key_A, Qt.Key.Key_D,
                   Qt.Key.Key_Q, Qt.Key.Key_E, Qt.Key.Key_I, Qt.Key.Key_K]:
            self.held_keys.add(key)
            self.update_keyboard_offboard()
            event.accept()
        elif key in [Qt.Key.Key_Space, Qt.Key.Key_H]:
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
        if not hasattr(self, 'kb_checkbox') or not self.kb_checkbox.isChecked() or not self.vehicle:
            reset_offboard_targets()
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
        if Qt.Key.Key_I in self.held_keys:
            vz -= 1.0
        if Qt.Key.Key_K in self.held_keys:
            vz += 1.0
        if Qt.Key.Key_Q in self.held_keys:
            yaw_rate -= 0.5
        if Qt.Key.Key_E in self.held_keys:
            yaw_rate += 0.5

        is_moving = (vx != 0.0 or vy != 0.0 or vz != 0.0 or yaw_rate != 0.0)
        if is_moving:
            ok = offboard_controller.apply_movement_if_confirmed(vx=vx, vy=vy, vz=vz, yaw_rate=yaw_rate)
            if not ok:
                self.ensure_offboard()
        else:
            reset_offboard_targets()

    # ---- Main Refresh Loop (2-5 Hz) ----
    def refresh(self):
        d = telemetry_data
        t = get_theme()

        if not self.vehicle:
            self.conn_status.setText("DISCONNECTED")
            self.conn_status.setStyleSheet(f"color: {t['danger']}; font-weight: bold;")
            self.ribbon_gps_pill.setText("GPS: NO FIX (0s)")
            self.ribbon_batt_pill.setText("BATT: ---% | --.-V")
            self.ribbon_dist_pill.setText("HOME: --- m")
            self.ribbon_timer_pill.setText("TIME: 00:00")
            self.alert_banner.setText("NO VEHICLE CONNECTED")
            self.alert_banner.setStyleSheet(get_pill_style('neutral'))
            self.set_controls_enabled(False)
            self.console_view.refresh_logs()
            return

        freshness = get_stream_freshness()
        link_state = freshness['link_state']

        if link_state == 'LOST':
            self.conn_status.setText("LINK LOST")
            self.conn_status.setStyleSheet(f"color: {t['danger']}; font-weight: bold;")
            self.set_controls_enabled(False)
        elif link_state == 'DEGRADED':
            self.conn_status.setText("LINK DEGRADED")
            self.conn_status.setStyleSheet(f"color: {t['warning']}; font-weight: bold;")
            self.set_controls_enabled(True)
        else:
            self.conn_status.setText("CONNECTED")
            self.conn_status.setStyleSheet(f"color: {t['success']}; font-weight: bold;")
            self.set_controls_enabled(True)

        # Contextual Control Safeguards (evaluate per action)
        is_airborne = is_vehicle_airborne()
        is_armed = d.get('armed', False)

        if is_armed:
            self.arm_btn.setText("DISARM")
            self.arm_btn.setStyleSheet(get_button_style('danger', 'sm'))
            if is_airborne:
                self.ribbon_arm_pill.setText("ARMED (AIRBORNE)")
                self.ribbon_arm_pill.setStyleSheet(get_pill_style('success', filled=True))
                # Protect airborne disarm
                self.arm_btn.setToolTip("Disarm blocked while airborne. Use LAND, RTL, or Emergency Cutoff.")
                self.takeoff_btn.setEnabled(False)
                self.rtl_btn.setEnabled(True)
                self.land_btn.setEnabled(True)
            else:
                self.ribbon_arm_pill.setText("ARMED (GROUND)")
                self.ribbon_arm_pill.setStyleSheet(get_pill_style('success', filled=True))
                self.arm_btn.setToolTip("Grounded disarm available.")
                self.takeoff_btn.setEnabled(True)
        else:
            self.ribbon_arm_pill.setText("DISARMED")
            self.ribbon_arm_pill.setStyleSheet(get_pill_style('danger', filled=True))
            self.arm_btn.setText("ARM")
            self.arm_btn.setStyleSheet(get_button_style('success', 'sm'))
            self.arm_btn.setToolTip("Arm flight motors.")
            self.takeoff_btn.setEnabled(True)
            self.rtl_btn.setEnabled(False)
            self.land_btn.setEnabled(False)

        self.ribbon_mode_pill.setText(f"MODE: {d.get('mode', 'UNKNOWN')}")
        self.ribbon_fw_pill.setText(d.get('autopilot_version', 'PX4 AUTOPILOT'))

        # GPS Readout
        if freshness['gps_valid']:
            sats = d.get('satellites', 0)
            fix = d.get('fix_type', 0)
            self.ribbon_gps_pill.setText(f"GPS: {fix}D ({sats}s)")
            self.ribbon_gps_pill.setStyleSheet(get_pill_style('success'))
        else:
            self.ribbon_gps_pill.setText("GPS: UNCONFIRMED")
            self.ribbon_gps_pill.setStyleSheet(get_pill_style('warning'))

        # Battery Readout
        if freshness['battery_valid']:
            batt = d.get('battery', -1)
            volt = d.get('voltage', 0.0)
            batt_str = f"{batt}%" if batt >= 0 else "---%"
            self.ribbon_batt_pill.setText(f"BATT: {batt_str} | {volt:.1f}V")
            self.ribbon_batt_pill.setStyleSheet(get_pill_style('success' if (batt < 0 or batt > 25) else 'danger'))
        else:
            self.ribbon_batt_pill.setText("BATT: STALE")
            self.ribbon_batt_pill.setStyleSheet(get_pill_style('danger'))

        # Alert Banner: evaluate highest priority notification
        prearm = d.get('prearm_fail', '')
        if prearm:
            self.alert_banner.setText(f"PREARM: {prearm[:25]}")
            self.alert_banner.setStyleSheet(get_pill_style('danger', filled=True))
        elif link_state in ('LOST', 'DEGRADED'):
            self.alert_banner.setText(f"LINK {link_state}")
            self.alert_banner.setStyleSheet(get_pill_style('warning', filled=True))
        elif not freshness['gps_valid'] and is_armed:
            self.alert_banner.setText("WARN: GPS UNCONFIRMED")
            self.alert_banner.setStyleSheet(get_pill_style('warning', filled=True))
        else:
            self.alert_banner.setText("ALL SYSTEMS NOMINAL")
            self.alert_banner.setStyleSheet(get_pill_style('success'))

        # Flight duration timer & distance calculation
        if is_armed:
            if not self.was_armed:
                self.armed_start_time = time.monotonic()
                self.total_flight_dist = 0.0
                self.last_flight_coord = (d['lat'], d['lon'])

            if self.armed_start_time:
                elapsed_flight = time.monotonic() - self.armed_start_time
                mins = int(elapsed_flight // 60)
                secs = int(elapsed_flight % 60)
                self.ribbon_timer_pill.setText(f"TIME: {mins:02d}:{secs:02d}")

            if self.last_flight_coord and d.get('lat') != 0.0 and d.get('lon') != 0.0:
                from gcs.telemetry_logger import haversine_distance
                step_dist = haversine_distance(self.last_flight_coord[0], self.last_flight_coord[1], d['lat'], d['lon'])
                if 0.05 < step_dist < 50.0:
                    self.total_flight_dist += step_dist
                    self.last_flight_coord = (d['lat'], d['lon'])
                self.ribbon_dist_pill.setText(f"DIST: {self.total_flight_dist:.0f} m")

        self.was_armed = is_armed

        # Tactical Map Position Update
        yaw_deg = math.degrees(d.get('yaw', 0.0)) % 360
        if freshness['gps_valid']:
            self.map_view.update_position(d.get('lat', 0.0), d.get('lon', 0.0), yaw_deg, d.get('groundspeed', 0.0), d.get('alt', 0.0))
            self.plan_map_view.update_position(d.get('lat', 0.0), d.get('lon', 0.0), yaw_deg, d.get('groundspeed', 0.0), d.get('alt', 0.0))

        # Set Home ONCE on confirmed HOME_POSITION or initial arming
        if not self._home_set_on_map:
            if d.get('has_home', False) and (d.get('home_lat', 0.0) != 0.0 or d.get('home_lon', 0.0) != 0.0):
                self.map_view.set_home(d['home_lat'], d['home_lon'])
                self.plan_map_view.set_home(d['home_lat'], d['home_lon'])
                self._home_set_on_map = True
            elif is_armed and d.get('lat', 0.0) != 0.0 and d.get('lon', 0.0) != 0.0:
                self.map_view.set_home(d['lat'], d['lon'])
                self.plan_map_view.set_home(d['lat'], d['lon'])
                self._home_set_on_map = True

        # Append to plots and analytics
        elapsed = time.monotonic() - self.start_time
        self.history_time.append(elapsed)
        self.history_alt.append(d.get('alt', 0.0))
        self.history_speed.append(d.get('groundspeed', 0.0))
        if len(self.history_time) > 200:
            self.history_time.pop(0)
            self.history_alt.pop(0)
            self.history_speed.pop(0)

        self.plot_panel.update_plots(self.history_time, self.history_alt, self.history_speed)
        self.analyze_view.update_telemetry(
            elapsed,
            d.get('alt', 0.0),
            d.get('groundspeed', 0.0),
            climb=d.get('climb_rate', 0.0),
            volt=d.get('voltage', 0.0),
            loss=d.get('packet_loss_pct', 0.0)
        )

        self.console_view.refresh_logs()

    def closeEvent(self, event):
        reply = QMessageBox.question(
            self,
            "Quit PythonGCS",
            "Are you sure you want to exit PythonGCS?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            event.ignore()
        else:
            self.disconnect_vehicle()
            event.accept()


def launch_gui(vehicle=None):
    app = QApplication(sys.argv)
    # Set clean system font stack with full Unicode support
    font = QFont("Segoe UI", 9)
    font.setStyleHint(QFont.StyleHint.SansSerif)
    app.setFont(font)

    window = GCSWindow(vehicle)
    window.show()
    app.exec()
