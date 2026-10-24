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
    QGraphicsDropShadowEffect, QInputDialog, QFileDialog, QSplitter, QScrollArea
)
try:
    from PyQt6.QtTextToSpeech import QTextToSpeech
    TTS_AVAILABLE = True
except ImportError:
    TTS_AVAILABLE = False

from PyQt6.QtCore import QObject, QTimer, Qt, QThread, pyqtSignal, QEvent, QSettings
from PyQt6.QtGui import QFont, QColor

import gcs.telemetry as telemetry
from gcs.telemetry import (
    telemetry_data, is_vehicle_airborne, create_new_session,
    cancel_current_session, reset_telemetry_data, read_telemetry,
    get_stream_freshness, get_telemetry_snapshot
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
from gcs.ui.status_widgets import TelemetryStrip, StreamHealthPanel
from gcs.flight_state import flight_status

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
    ("PX4 SITL / Gazebo (UDP 14540)", "udpin:0.0.0.0:14540"),
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
            deadline = time.monotonic() + 15.0
            while self.running and time.monotonic() < deadline:
                vehicle = connect(self.connection_string, timeout=1.0)
                if vehicle is not None:
                    if self.running:
                        self.connected.emit(vehicle)
                    else:
                        vehicle.close()
                    return
                self.msleep(100)
            if self.running:
                self.failed.emit("No autopilot heartbeat received within 15 seconds.")
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

        self.alt_curve = self.plot_widget.plot(pen=pg.mkPen(t['primary'], width=1.5))
        self.speed_curve = self.plot_widget.plot(pen=pg.mkPen(t['warning'], width=1.5))
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
    def __init__(self, vehicle=None, settings=None):
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
        self._closing = False
        self._connection_generation = 0
        self._connection_workers = []
        self._connecting = False
        self.settings = settings if settings is not None else QSettings('PythonGCS', 'Desktop')
        set_active_theme(self.settings.value('appearance/dark', False, type=bool))
        self._current_theme = get_theme()

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
        QApplication.instance().focusChanged.connect(self._on_focus_changed)
        self.refresh()

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
        ribbon_layout = QVBoxLayout(ribbon_frame)
        ribbon_layout.setContentsMargins(12, 10, 12, 10)
        rf_layout = QHBoxLayout()
        ribbon_layout.addLayout(rf_layout)
        rf_layout.setContentsMargins(8, 4, 8, 4)
        rf_layout.setSpacing(6)

        # Brand & Vehicle Identity
        brand_lbl = QLabel("PYTHON GCS")
        brand_lbl.setStyleSheet(f"color: {t['primary']}; font-family: {FONT_FAMILY_PRIMARY}; font-size: 13px; font-weight: 800; border: none; background: transparent;")
        rf_layout.addWidget(brand_lbl)

        # Vehicle Identity Badge
        self.vehicle_id_badge = QLabel("NO VEHICLE")
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
        self.conn_input.setMinimumWidth(170)
        self.conn_input.setMaximumWidth(280)
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
        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        ribbon_layout.addLayout(status_row)

        # Highest Priority Alert Banner (prominently visible)
        self.alert_banner = QLabel("SYSTEM NOMINAL")
        self.alert_banner.setStyleSheet(get_pill_style('neutral'))
        self.alert_banner.setWordWrap(True)

        # Status Pills
        self.ribbon_fw_pill = QLabel("PX4 AUTOPILOT")
        self.ribbon_fw_pill.setStyleSheet(get_pill_style('neutral'))
        status_row.addWidget(self.ribbon_fw_pill)

        self.ribbon_arm_pill = QLabel("DISARMED")
        self.ribbon_arm_pill.setStyleSheet(get_pill_style('danger', filled=True))
        status_row.addWidget(self.ribbon_arm_pill)

        self.ribbon_mode_pill = QLabel("MODE: UNKNOWN")
        self.ribbon_mode_pill.setStyleSheet(get_pill_style('primary'))
        status_row.addWidget(self.ribbon_mode_pill)

        self.ribbon_gps_pill = QLabel("GPS: NO FIX (0s)")
        self.ribbon_gps_pill.setStyleSheet(get_pill_style('neutral'))
        status_row.addWidget(self.ribbon_gps_pill)

        self.ribbon_batt_pill = QLabel("BATT: ---% | --.-V")
        self.ribbon_batt_pill.setStyleSheet(get_pill_style('neutral'))
        status_row.addWidget(self.ribbon_batt_pill)

        self.ribbon_timer_pill = QLabel("TIME: 00:00")
        self.ribbon_timer_pill.setStyleSheet(get_pill_style('neutral'))
        status_row.addWidget(self.ribbon_timer_pill)

        self.ribbon_dist_pill = QLabel("HOME: --- m")
        self.ribbon_dist_pill.setStyleSheet(get_pill_style('neutral'))
        status_row.addWidget(self.ribbon_dist_pill)
        status_row.addStretch(1)

        main_layout.addWidget(ribbon_frame)
        main_layout.addWidget(self.alert_banner)

        # 2. Main Workspaces Navigation (FLY, PLAN, VEHICLE SETUP, ANALYZE, SETTINGS)
        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(self._on_tab_changed)

        self._build_fly_tab()
        rf_layout.addWidget(self.preflight_btn)

        # Dedicated Plan Workspace
        self.plan_view = PlanView(self.vehicle)
        self.plan_map_view = self.plan_view.map_view
        self.plan_view.mission_uploaded.connect(self._on_plan_transfer_result)
        self.plan_view.draft_changed.connect(self._update_action_states)
        self.tabs.addTab(self.plan_view, "PLAN")

        # Vehicle Setup Workspace
        self.setup_view = SetupView(self.vehicle)
        self.tabs.addTab(self.setup_view, "VEHICLE SETUP")

        # Flight Analytics & Log Suite
        self.analyze_view = AnalyzeView()
        self.tabs.addTab(self.analyze_view, "ANALYZE")

        # Settings Workspace
        self.settings_view = SettingsView(settings=self.settings)
        self.settings_view.theme_changed.connect(self._on_theme_toggled)
        self.settings_view.settings_changed.connect(self.refresh)
        self.settings_view.video_source_changed.connect(self._set_video_source)
        self.tabs.addTab(self.settings_view, "Settings")
        self._build_diagnostics_tab(rf_layout, status_row)
        for index, name in enumerate(('Fly', 'Plan', 'Vehicle', 'Analyze', 'Settings', 'Diagnostics')):
            self.tabs.setTabText(index, name)

        self.profile_combo.setCurrentIndex(self.settings.value('connection/profile', 0, type=int))
        self.conn_input.setText(self.settings.value('connection/address', self.conn_input.text()))
        self.statusBar().showMessage('Disconnected · Flight actions inhibited')

        main_layout.addWidget(self.tabs, stretch=1)

    def _on_theme_toggled(self, is_dark: bool):
        old = self._current_theme
        new = get_theme()
        # Retheme widget-local styles as well as the root stylesheet.
        import re
        substitutions = {old[key]: new[key] for key in old if key != 'name' and old[key] != new[key]}
        pattern = re.compile('|'.join(re.escape(color) for color in sorted(substitutions, key=len, reverse=True)))
        for widget in self.findChildren(QWidget):
            sheet = widget.styleSheet()
            if sheet:
                widget.setStyleSheet(pattern.sub(lambda match: substitutions[match.group(0)], sheet))
        self._current_theme = new
        self.setStyleSheet(get_app_stylesheet())
        self.plot_panel.plot_widget.setBackground(new['plot_bg'])
        self.instrument_container.pfd.update()
        self.camera_view.update()
        self.map_view.apply_theme()
        self.plan_map_view.apply_theme()
        self.refresh()

    def _on_tab_changed(self, idx: int):
        # Safety: whenever leaving Fly tab, clear keyboard held keys and offboard targets
        if idx != 0 and hasattr(self, 'held_keys') and self.held_keys:
            self.held_keys.clear()
            self.update_keyboard_offboard()
        if idx != 0 and hasattr(self, 'kb_checkbox'):
            self.kb_checkbox.setChecked(False)

    def _on_focus_changed(self, previous, current):
        if self.held_keys:
            self.held_keys.clear()
            reset_offboard_targets()

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
        fly_splitter = self.fly_splitter = QSplitter(Qt.Orientation.Horizontal)
        fly_splitter.setChildrenCollapsible(False)

        # --- LEFT RAIL: Flight Instruments & Contextual Action Controls ---
        self.left_col_widget = QWidget()
        left_col = QVBoxLayout(self.left_col_widget)
        left_col.setContentsMargins(0, 0, 0, 0)
        left_col.setSpacing(6)

        # Cockpit Primary Flight Display (PFD) / 3D CAD toggle container
        self.instrument_container = InstrumentContainer()
        self.attitude_view = None  # 3D WebEngine view is created only on request.
        self.instrument_container.setMaximumHeight(300)
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
            "AUTO.LOITER", "POSCTL", "ALTCTL", "STABILIZED", "MANUAL",
            "OFFBOARD", "AUTO.TAKEOFF", "AUTO.LOITER", "AUTO.RTL",
            "AUTO.LAND", "AUTO.MISSION"
        ])
        self.mode_btn = QPushButton("SET MODE")
        self.mode_btn.setFixedHeight(26)
        self.mode_btn.setStyleSheet(get_button_style('secondary', 'sm'))
        self.mode_btn.clicked.connect(self.on_set_mode)
        mode_row.addWidget(self.mode_combo, stretch=1)
        mode_row.addWidget(self.mode_btn)
        self.pilot_dialog = QDialog(self)
        self.pilot_dialog.setWindowTitle("Pilot controls")
        self.pilot_dialog.setMinimumWidth(420)
        pilot_layout = QVBoxLayout(self.pilot_dialog)
        pilot_layout.setContentsMargins(20, 20, 20, 20)
        pilot_layout.setSpacing(14)
        pilot_note = QLabel("Additional flight modes and keyboard control.\nAutopilot checks and keyboard safeguards remain active.")
        pilot_note.setWordWrap(True)
        pilot_layout.addWidget(pilot_note)
        pilot_layout.addLayout(mode_row)

        # Row 2: Arm, Altitude Spin, Takeoff
        arm_row = QHBoxLayout()
        self.arm_btn = QPushButton("ARM")
        self.arm_btn.setFixedHeight(36)
        self.arm_btn.setStyleSheet(get_button_style('success', 'sm'))
        self.arm_btn.clicked.connect(self.on_arm_disarm)

        self.alt_spin = QDoubleSpinBox()
        self.alt_spin.setRange(2.0, 100.0)
        self.alt_spin.setValue(5.0)
        self.alt_spin.setSuffix(" m")

        self.takeoff_btn = QPushButton("TAKEOFF")
        self.takeoff_btn.setFixedHeight(36)
        self.takeoff_btn.setStyleSheet(get_button_style('primary', 'sm'))
        self.takeoff_btn.clicked.connect(self.on_takeoff)

        arm_row.addWidget(self.arm_btn)
        arm_row.addWidget(self.alt_spin)
        arm_row.addWidget(self.takeoff_btn)
        ac_layout.addLayout(arm_row)

        # Row 3: Prominent HOLD, RTL, LAND
        nav_row = QHBoxLayout()
        self.hold_btn = QPushButton("Hold")
        self.hold_btn.setFixedHeight(36)
        self.hold_btn.setStyleSheet(get_button_style('secondary', 'sm'))
        self.hold_btn.clicked.connect(self.on_emergency_hold)

        self.rtl_btn = QPushButton("Return")
        self.rtl_btn.setFixedHeight(36)
        self.rtl_btn.setStyleSheet(get_button_style('secondary', 'sm'))
        self.rtl_btn.clicked.connect(self.on_rtl)

        self.land_btn = QPushButton("Land")
        self.land_btn.setFixedHeight(36)
        self.land_btn.setStyleSheet(get_button_style('secondary', 'sm'))
        self.land_btn.clicked.connect(self.on_land)

        nav_row.addWidget(self.hold_btn)
        nav_row.addWidget(self.rtl_btn)
        nav_row.addWidget(self.land_btn)
        ac_layout.addLayout(nav_row)

        # Row 4: Start Mission Button
        self.start_btn = QPushButton("Start mission")
        self.start_btn.setFixedHeight(36)
        self.start_btn.setStyleSheet(get_button_style('primary', 'sm'))
        self.start_btn.setEnabled(False) # Enabled upon verified mission
        self.start_btn.clicked.connect(self.on_start_mission)
        ac_layout.addWidget(self.start_btn)

        # Emergency stop stays accessible; additional pilot controls are on demand.
        self.emer_stop_btn = QPushButton("EMERGENCY MOTOR CUTOFF (KILL)")
        self.emer_stop_btn.setFixedHeight(28)
        self.emer_stop_btn.setStyleSheet(get_button_style('danger', 'sm'))
        self.emer_stop_btn.clicked.connect(self.on_emergency_motor_stop)


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
        pilot_layout.addWidget(kb_box)

        # Row 7: Preflight & Voice Controls
        self.preflight_btn = QPushButton("Preflight checklist")
        self.preflight_btn.setFixedHeight(26)
        self.preflight_btn.setStyleSheet(get_button_style('primary', 'sm'))
        self.preflight_btn.clicked.connect(self.on_open_preflight_dialog)

        self.voice_btn = QPushButton("VOICE: ON")
        self.voice_btn.setFixedHeight(26)
        self.voice_btn.setStyleSheet(get_button_style('secondary', 'sm'))
        self.voice_btn.clicked.connect(self.on_toggle_voice)
        pilot_layout.addWidget(self.voice_btn)
        pilot_done = QPushButton("Done")
        pilot_done.setStyleSheet(get_button_style("secondary", "sm"))
        pilot_done.clicked.connect(self.pilot_dialog.accept)
        pilot_layout.addWidget(pilot_done)
        self.more_controls_btn = QPushButton("More flight controls…")
        self.more_controls_btn.setStyleSheet(get_button_style('secondary', 'sm'))
        self.more_controls_btn.clicked.connect(self.pilot_dialog.show)
        ac_layout.addWidget(self.more_controls_btn)
        self.emer_stop_btn.setText("Emergency motor stop…")
        self.emer_stop_btn.setStyleSheet(get_button_style('secondary', 'sm').replace(t['text'], t['danger']))
        ac_layout.addWidget(self.emer_stop_btn)

        self.status_label = QLabel("System ready.")
        self.status_label.setWordWrap(True)
        self.status_label.setMaximumHeight(48)
        self.status_label.setStyleSheet(f"color: {t['text_secondary']}; font-size: 11px;")
        ac_layout.addWidget(self.status_label)

        left_col.addWidget(action_card)
        self.stream_health = StreamHealthPanel()

        left_col.addStretch(1)

        rail_scroll = QScrollArea()
        rail_scroll.setWidgetResizable(True)
        rail_scroll.setFrameShape(QFrame.Shape.NoFrame)
        rail_scroll.setMinimumWidth(310)
        rail_scroll.setMaximumWidth(350)
        rail_scroll.setWidget(self.left_col_widget)
        fly_splitter.addWidget(rail_scroll)

        # --- CENTER / DOMINANT AREA: Tactical Map & Picture-in-Picture Video ---
        center_container = QWidget()
        center_layout = QVBoxLayout(center_container)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(4)
        self.telemetry_strip = TelemetryStrip(fields=('alt', 'speed', 'climb', 'home'))
        center_layout.addWidget(self.telemetry_strip)

        self.map_view = MapView(planning=False)
        self.map_view.setToolTip('OpenStreetMap with live vehicle position, mission and flight trail')
        self.map_view.goto_requested.connect(self.on_map_goto_requested)

        self.camera_view = CameraView()
        # A test feed is available explicitly in Settings; never auto-start it.

        self.pip_workspace = PipWorkspace(self.map_view, self.camera_view)
        self.pip_workspace.pip_frame.hide()
        self.empty_flight = QFrame(self.pip_workspace)
        self.empty_flight.setObjectName('FlightWelcome')
        self.empty_flight.setFixedSize(400, 174)
        self.empty_flight.setStyleSheet(f"#FlightWelcome {{background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 14px;}}")
        welcome = QVBoxLayout(self.empty_flight)
        welcome.setContentsMargins(24, 20, 24, 20)
        welcome.setSpacing(10)
        welcome_title = QLabel('Your flight starts here')
        welcome_title.setStyleSheet(f"font-size: 21px; font-weight: 600; color: {t['text']};")
        welcome.addWidget(welcome_title)
        welcome_note = QLabel('Connect your vehicle, review the preflight checklist,\nthen fly or start a verified mission.')
        welcome_note.setStyleSheet(f"color: {t['text_secondary']}; font-size: 12px;")
        welcome.addWidget(welcome_note)
        welcome_connect = QPushButton('Connect vehicle')
        welcome_connect.setStyleSheet(get_button_style('primary', 'md'))
        welcome_connect.clicked.connect(lambda: self.connection_dialog.show())
        welcome.addWidget(welcome_connect, alignment=Qt.AlignmentFlag.AlignLeft)
        center_layout.addWidget(self.pip_workspace, stretch=1)

        # Bottom Expandable Diagnostics Drawer (Collapsible for maximum map area)
        self.diag_drawer = QFrame()
        self.diag_drawer.setObjectName("DiagnosticsDrawer")
        self.diag_drawer.setMinimumHeight(300)
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



        # Drawer Collapse / Expand Button
        drawer_bar = QHBoxLayout()
        self.btn_toggle_drawer = QPushButton("Diagnostics →")
        self.btn_toggle_drawer.setFixedHeight(22)
        self.btn_toggle_drawer.setStyleSheet(get_button_style('secondary', 'sm'))
        self.btn_toggle_drawer.clicked.connect(self._toggle_diagnostics_drawer)
        drawer_bar.addWidget(self.btn_toggle_drawer)
        drawer_bar.addStretch(1)

        self.load_mbtiles_btn = QPushButton("LOAD MBTILES")
        self.load_mbtiles_btn.setFixedHeight(22)
        self.load_mbtiles_btn.setStyleSheet(get_button_style('secondary', 'sm'))
        self.load_mbtiles_btn.clicked.connect(self.on_load_offline_mbtiles)


        self.export_kml_btn = QPushButton("EXPORT KML")
        self.export_kml_btn.setFixedHeight(22)
        self.export_kml_btn.setStyleSheet(get_button_style('secondary', 'sm'))
        self.export_kml_btn.clicked.connect(self.on_export_flight_trail)
        self.video_toggle_btn = QPushButton("Show video")
        self.video_toggle_btn.setCheckable(True)
        self.video_toggle_btn.setStyleSheet(get_button_style('secondary', 'sm'))
        self.video_toggle_btn.toggled.connect(self._toggle_video)
        drawer_bar.addWidget(self.video_toggle_btn)
        map_settings = QPushButton("Map / video settings")
        map_settings.setStyleSheet(get_button_style('secondary', 'sm'))
        map_settings.clicked.connect(lambda: self.tabs.setCurrentWidget(self.settings_view))
        drawer_bar.addWidget(map_settings)

        center_layout.addLayout(drawer_bar)
        fly_splitter.addWidget(center_container)
        fly_splitter.setStretchFactor(0, 1) # Rail takes 25%
        fly_splitter.setStretchFactor(1, 4) # Dominant Map takes 75%

        fly_layout.addWidget(fly_splitter)
        self.tabs.addTab(fly_widget, "FLY")
        self.fly_splitter.setSizes([320, 1040])

        # Fallback gauges for test compatibility
        self.gauge_spd = ArcGauge("SPEED", "m/s", 0, 25, THEME['primary'])
        self.gauge_alt = ArcGauge("ALT REL", "m", 0, 100, THEME['primary'])
        self.gauge_throttle = ArcGauge("THROTTLE", "%", 0, 100, THEME['warning'])
        self.gauge_batt = ArcGauge("BATTERY", "%", 0, 100, THEME['success'])
        self.power_panel = StatPanel("POWER", [('battery', 'Battery', '%'), ('voltage', 'Voltage', 'V')])
        self.gnss_panel = StatPanel("GNSS", [('fix', 'Fix', ''), ('sats', 'Satellites', '')])
        self.link_panel = StatPanel("LINK", [('msg_rate', 'Rate', 'Hz'), ('loss_pct', 'Loss', '%')])

    def _toggle_diagnostics_drawer(self):
        self.tabs.setCurrentWidget(self.diagnostics_view)

    def _toggle_video(self, visible):
        if not visible and not self.pip_workspace.is_map_dominant:
            self.pip_workspace.swap_views()
        self.pip_workspace.pip_frame.setVisible(visible)
        self.video_toggle_btn.setText('Hide video' if visible else 'Show video')

    def _set_video_source(self, source):
        self.camera_view.set_stream_source(source)
        self.video_toggle_btn.setChecked(bool(source))

    def _build_diagnostics_tab(self, connection_row, status_row):
        t = get_theme()
        self.diagnostics_view = QWidget()
        page = QVBoxLayout(self.diagnostics_view)
        page.setContentsMargins(18, 16, 18, 16)
        page.setSpacing(16)
        heading = QHBoxLayout()
        title = QLabel('System diagnostics')
        title.setStyleSheet(f"font-size: 20px; font-weight: 600; color: {t['text']};")
        heading.addWidget(title)
        heading.addStretch()
        self.detach_diagnostics_btn = QPushButton('Open in second window ↗')
        self.detach_diagnostics_btn.setStyleSheet(get_button_style('secondary', 'sm'))
        self.detach_diagnostics_btn.clicked.connect(self._detach_diagnostics)
        heading.addWidget(self.detach_diagnostics_btn)
        page.addLayout(heading)
        description = QLabel('Stream health, live plots and command acknowledgements. Flight controls stay in Fly.')
        description.setWordWrap(True)
        page.addWidget(description)
        self.diagnostics_content = QWidget()
        content = QVBoxLayout(self.diagnostics_content)
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(16)
        overview = QHBoxLayout()
        overview.addWidget(self.stream_health, 1)
        details = QVBoxLayout()
        details.addWidget(QLabel('VEHICLE & SESSION'))
        for label in (self.ribbon_fw_pill, self.ribbon_timer_pill, self.ribbon_dist_pill):
            status_row.removeWidget(label)
            details.addWidget(label)
        details.addStretch()
        overview.addLayout(details, 1)
        content.addLayout(overview)
        content.addWidget(self.diag_drawer, 1)
        self.diag_drawer.show()
        content.addWidget(self.export_kml_btn, alignment=Qt.AlignmentFlag.AlignRight)
        page.addWidget(self.diagnostics_content, 1)
        self.diagnostics_placeholder = QLabel('Diagnostics are open in the second window. Close that window to return them here.')
        self.diagnostics_placeholder.setWordWrap(True)
        self.diagnostics_placeholder.hide()
        page.addWidget(self.diagnostics_placeholder)
        self.tabs.addTab(self.diagnostics_view, 'Diagnostics')
        self.diagnostics_window = QDialog(self, Qt.WindowType.Window)
        self.diagnostics_window.setWindowTitle('PythonGCS — System diagnostics')
        self.diagnostics_window.resize(1100, 760)
        QVBoxLayout(self.diagnostics_window)
        self.diagnostics_window.finished.connect(self._restore_diagnostics)

        # Connection details are available on demand instead of occupying Fly.
        self.connection_dialog = QDialog(self)
        self.connection_dialog.setWindowTitle('Vehicle connection')
        self.connection_dialog.setMinimumWidth(480)
        form = QVBoxLayout(self.connection_dialog)
        form.setContentsMargins(22, 22, 22, 22)
        form.setSpacing(14)
        form.addWidget(QLabel('Choose a connection profile, then connect to your vehicle or simulator.'))
        for caption, widget in [('Connection profile', self.profile_combo), ('MAVLink address', self.conn_input)]:
            connection_row.removeWidget(widget)
            form.addWidget(QLabel(caption))
            widget.setMaximumWidth(16777215)
            form.addWidget(widget)
        connection_row.removeWidget(self.conn_btn)
        form.addWidget(self.conn_btn)
        done = QPushButton('Done')
        done.setStyleSheet(get_button_style('secondary', 'sm'))
        done.clicked.connect(self.connection_dialog.accept)
        form.addWidget(done)
        self.connection_settings_btn = QPushButton('Connection…')
        self.connection_settings_btn.setStyleSheet(get_button_style('secondary', 'sm'))
        self.connection_settings_btn.clicked.connect(self.connection_dialog.show)
        connection_row.insertWidget(2, self.connection_settings_btn)

    def _detach_diagnostics(self):
        if self.diagnostics_window.isVisible():
            self.diagnostics_window.raise_()
            self.diagnostics_window.activateWindow()
            return
        self.diagnostics_view.layout().removeWidget(self.diagnostics_content)
        self.diagnostics_window.layout().addWidget(self.diagnostics_content)
        self.diagnostics_placeholder.show()
        self.diagnostics_window.show()

    def _restore_diagnostics(self, _result=0):
        self.diagnostics_window.layout().removeWidget(self.diagnostics_content)
        self.diagnostics_view.layout().insertWidget(2, self.diagnostics_content, 1)
        self.diagnostics_content.show()
        self.diagnostics_placeholder.hide()

    def _fast_instrument_update(self):
        """High-rate 30 Hz flight attitude & PFD instrument refresh."""
        d = get_telemetry_snapshot()
        freshness = get_stream_freshness(data=d)
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
            is_stale=is_stale or self.vehicle is None,
            position_valid=self.vehicle is not None and freshness['position_valid'],
            speed_valid=self.vehicle is not None and freshness['vfr_valid']
        )

    def on_connect_toggle(self):
        if self.vehicle or any(w.isRunning() for w in self._connection_workers):
            self.disconnect_vehicle()
            return
        conn_str = self.conn_input.text().strip()
        if not conn_str:
            self.set_status('Enter a MAVLink connection address.')
            return
        self._connection_generation += 1
        generation = self._connection_generation
        self._connecting = True
        self.settings.setValue('connection/profile', self.profile_combo.currentIndex())
        self.settings.setValue('connection/address', conn_str)
        self.conn_btn.setText('CANCEL')
        self.profile_combo.setEnabled(False)
        self.conn_input.setEnabled(False)
        self.set_status(f'Waiting for an autopilot heartbeat on {conn_str}…')
        worker = self.conn_worker = ConnectionWorker(conn_str)
        self._connection_workers.append(worker)
        worker.connected.connect(lambda vehicle, gen=generation: self._accept_connection(gen, vehicle))
        worker.failed.connect(lambda error, gen=generation: self._connection_failed(gen, error))
        worker.finished.connect(lambda worker=worker: self._connection_finished(worker))
        worker.start()

    def _connection_finished(self, worker):
        if worker in self._connection_workers:
            self._connection_workers.remove(worker)
        worker.deleteLater()

    def _accept_connection(self, generation, vehicle):
        if self._closing or generation != self._connection_generation:
            vehicle.close()
            return
        self.on_connected(vehicle)

    def _connection_failed(self, generation, message):
        if generation == self._connection_generation and not self._closing:
            self.on_connection_failed(message)

    def on_connected(self, vehicle):
        self._connecting = False
        self.vehicle = vehicle
        self._home_set_on_map = False
        self.was_armed = False
        self._telemetry_session_id = create_new_session()
        telemetry_data['sysid'] = vehicle.target_system
        telemetry_data['compid'] = vehicle.target_component
        self.conn_btn.setEnabled(True)
        self.conn_btn.setText('DISCONNECT')
        self.conn_btn.setStyleSheet(get_button_style('secondary', 'sm'))
        self.set_status('Transport open. Waiting for fresh vehicle telemetry.')
        self.setup_view.set_vehicle(vehicle)
        self.plan_view.set_vehicle(vehicle)
        self._telemetry_thread = threading.Thread(target=read_telemetry,
            args=(vehicle, self._telemetry_session_id), daemon=True)
        self._telemetry_thread.start()
        threading.Thread(target=request_telemetry, args=(vehicle,), daemon=True).start()
        self.refresh()

    def on_connection_failed(self, error_msg):
        self._connecting = False
        self.conn_btn.setText('CONNECT')
        self.conn_btn.setEnabled(True)
        self.profile_combo.setEnabled(True)
        self.conn_input.setEnabled(True)
        self.set_status(f'Connection failed: {error_msg}')

    def disconnect_vehicle(self):
        self._connecting = False
        self._connection_generation += 1
        for worker in self._connection_workers:
            worker.stop()
        previous_vehicle = self.vehicle
        self.held_keys.clear()
        self.kb_checkbox.setChecked(False)
        stop_streamer()
        cancel_current_session()
        self.vehicle = None
        self._telemetry_session_id = None
        self._home_set_on_map = False
        self.was_armed = False
        self.armed_start_time = None
        self.history_time.clear()
        self.history_alt.clear()
        self.history_speed.clear()
        for view in (self.map_view, self.plan_map_view):
            view.reset_vehicle()
        if previous_vehicle is not None and hasattr(previous_vehicle, 'close'):
            previous_vehicle.close()
        self.conn_btn.setEnabled(True)
        self.conn_btn.setText('CONNECT')
        self.conn_btn.setStyleSheet(get_button_style('primary', 'sm'))
        self.profile_combo.setEnabled(True)
        self.conn_input.setEnabled(True)
        self.setup_view.set_vehicle(None)
        self.plan_view.set_vehicle(None)
        self.set_status('Disconnected. Flight actions inhibited.')
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
        self.plan_view.on_upload_completed(ok, msg)
        self._update_action_states()
        self.set_status(f"Mission Transfer: {'VERIFIED' if ok else 'FAILED'} — {msg}")
        self.analyze_view.log_event("MISSION_UPLOAD", "VERIFIED" if ok else f"FAILED: {msg}")

    def on_arm_disarm(self):
        if not self.vehicle or not self._allow_action('arm'):
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
        if not self.vehicle or not self._allow_action('cutoff'):
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
        if not self.vehicle or not self._allow_action('mode'):
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
        if not self.vehicle or not self._allow_action('takeoff'):
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
        if not self.vehicle or not self._allow_action('rtl'):
            return
        session_id = self.current_session_id
        vehicle = self.vehicle
        self.set_status("Requesting AUTO.RTL (Return to Launch)...")
        def _rtl_worker():
            ok, msg = set_mode(vehicle, "AUTO.RTL")
            self.worker_bridge.command_completed.emit(session_id, "RTL", ok, msg)
        threading.Thread(target=_rtl_worker, daemon=True).start()

    def on_land(self):
        if not self.vehicle or not self._allow_action('land'):
            return
        session_id = self.current_session_id
        vehicle = self.vehicle
        self.set_status("Requesting AUTO.LAND (Landing)...")
        def _land_worker():
            ok, msg = set_mode(vehicle, "AUTO.LAND")
            self.worker_bridge.command_completed.emit(session_id, "LAND", ok, msg)
        threading.Thread(target=_land_worker, daemon=True).start()

    def on_emergency_hold(self):
        if not self.vehicle or not self._allow_action('hold'):
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
        if not self.vehicle or not self._allow_action('start'):
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
        if not self.vehicle or not self._allow_action('goto'):
            return
        reply = QMessageBox.question(self, 'Confirm reposition',
            f'Reposition vehicle SYS {telemetry_data.get("sysid")} to {lat:.6f}, {lon:.6f} '
            f'at {self.alt_spin.value():.1f} m relative to home?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if reply != QMessageBox.StandardButton.Yes or not self._allow_action('goto'):
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
        self.statusBar().showMessage(msg)
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
        if (not hasattr(self, 'kb_checkbox') or not self.kb_checkbox.isChecked() or not self.vehicle
                or not flight_status(dict(telemetry_data), True)['actions']['keyboard'].enabled
                or self.tabs.currentIndex() != 0 or QApplication.activeModalWidget() is not None):
            self.held_keys.clear()
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
    def _update_action_states(self):
        state = flight_status(get_telemetry_snapshot(), self.vehicle is not None,
                              self.plan_view.is_verified_for(self.vehicle))
        controls = {'arm': self.arm_btn, 'takeoff': self.takeoff_btn,
                    'hold': self.hold_btn, 'rtl': self.rtl_btn, 'land': self.land_btn,
                    'mode': self.mode_btn, 'start': self.start_btn,
                    'keyboard': self.kb_checkbox, 'cutoff': self.emer_stop_btn}
        for name, widget in controls.items():
            availability = state['actions'][name]
            widget.setEnabled(availability.enabled)
            widget.setToolTip(availability.reason)
        if not state['actions']['keyboard'].enabled and self.kb_checkbox.isChecked():
            self.kb_checkbox.setChecked(False)
            self.held_keys.clear()
            reset_offboard_targets()
        self.plan_view.set_link_available(state['live'])
        return state

    def _allow_action(self, action):
        availability = self._update_action_states()['actions'][action]
        if not availability.enabled:
            self.set_status(availability.reason)
        return availability.enabled

    def _on_plan_transfer_result(self, ok, msg):
        self._update_action_states()
        self.set_status(f"Mission transfer: {msg}")
        self.analyze_view.log_event('MISSION_TRANSFER', msg)

    def refresh(self):
        d = get_telemetry_snapshot()
        t = get_theme()
        connected = self.vehicle is not None
        show_welcome = not connected and self.pip_workspace.is_map_dominant
        self.empty_flight.setVisible(show_welcome)
        if show_welcome:
            self.empty_flight.move(max(12, (self.pip_workspace.width() - self.empty_flight.width()) // 2),
                                   max(12, (self.pip_workspace.height() - self.empty_flight.height()) // 2))
            self.empty_flight.raise_()
        state = self._update_action_states()
        fresh = state['freshness']
        live = state['live']
        armed = bool(d.get('armed'))
        first_alert = state['alerts'][0]
        extra = len(state['alerts']) - 1
        self.alert_banner.setVisible(first_alert.severity in ('warning', 'danger'))
        self.alert_banner.setText(f"{first_alert.title}  /  {first_alert.detail}" + (f"  (+{extra} more)" if extra else ''))
        self.alert_banner.setToolTip('\n'.join(f'{a.title}: {a.detail}' for a in state['alerts']))
        self.alert_banner.setStyleSheet(get_pill_style(first_alert.severity))
        self.stream_health.update_health(fresh, connected)

        connecting = self._connecting
        self.conn_status.setText('CONNECTING' if connecting and not connected else fresh['link_state'] if connected else 'DISCONNECTED')
        self.conn_status.setStyleSheet(f"color: {t['success'] if live and fresh['link_state'] == 'HEALTHY' else t['warning'] if connected or connecting else t['text_muted']}; font-weight: 600;")
        self.vehicle_id_badge.setText(f"SYS {d.get('sysid', '?')} / COMP {d.get('compid', '?')}" if connected else 'NO VEHICLE')
        self.ribbon_fw_pill.setText(f"PX4 {d.get('autopilot_version', 'Unknown')}" if connected else 'PX4')
        self.ribbon_mode_pill.setText(f"MODE: {d.get('mode', 'UNKNOWN')}" if live else 'MODE: UNCONFIRMED')
        arm_text = ('ARMED / AIRBORNE' if state['airborne'] else 'ARMED / GROUND' if state['grounded'] else 'ARMED / POSITION UNKNOWN') if armed else 'DISARMED'
        self.ribbon_arm_pill.setText(arm_text if live else 'ARM STATE UNKNOWN')
        self.ribbon_arm_pill.setStyleSheet(get_pill_style('warning' if armed and live else 'neutral'))
        self.arm_btn.setText('DISARM' if live and armed else 'ARM')
        self.arm_btn.setStyleSheet(get_button_style('secondary' if armed else 'primary', 'sm'))

        fix_names = {3: '3D', 4: 'DGPS', 5: 'RTK FLOAT', 6: 'RTK FIXED', 7: 'STATIC', 8: 'PPP'}
        self.ribbon_gps_pill.setText(f"GNSS: {fix_names.get(d.get('fix_type'), 'FIX')} / {d.get('satellites', 0)} SAT" if connected and fresh['gps_valid'] else 'GNSS: UNCONFIRMED')
        self.ribbon_gps_pill.setStyleSheet(get_pill_style('success' if connected and fresh['gps_valid'] else 'neutral'))
        if connected and fresh['battery_valid']:
            remaining = f"{d['battery']}%" if d.get('battery', -1) >= 0 else 'UNKNOWN %'
            volts = f"{d['voltage']:.1f} V" if d.get('voltage', 0) > 0 else 'UNKNOWN V'
            self.ribbon_batt_pill.setText(f"BATTERY: {remaining} / {volts}")
        else:
            self.ribbon_batt_pill.setText('BATTERY: UNAVAILABLE')
        self.ribbon_batt_pill.setStyleSheet(get_pill_style('neutral'))

        home_dist = None
        if connected and fresh['position_valid'] and d.get('has_home'):
            from gcs.telemetry_logger import haversine_distance
            home_dist = haversine_distance(d['lat'], d['lon'], d['home_lat'], d['home_lon'])
        self.telemetry_strip.update_values(d, fresh, connected, home_dist)
        self.ribbon_dist_pill.setText(f"HOME: {home_dist:.0f} m" if home_dist is not None else 'HOME: UNCONFIRMED')
        if live and armed:
            if not self.was_armed:
                self.armed_start_time = time.monotonic()
            elapsed = time.monotonic() - self.armed_start_time
            self.ribbon_timer_pill.setText(f"ARMED: {int(elapsed // 60):02d}:{int(elapsed % 60):02d}")
        elif not connected:
            self.ribbon_timer_pill.setText('ARMED: --:--')
        self.was_armed = armed if live else self.was_armed

        if connected and fresh['gps_valid']:
            yaw_deg = math.degrees(d.get('yaw', 0)) % 360
            for map_view in (self.map_view, self.plan_map_view):
                map_view.update_position(d['lat'], d['lon'], yaw_deg, d.get('groundspeed', 0), d.get('alt', 0))
        if connected and d.get('has_home'):
            home = (d['home_lat'], d['home_lon'])
            if self._home_set_on_map != home:
                self.map_view.set_home(*home)
                self.plan_map_view.set_home(*home)
                self._home_set_on_map = home
        if connected:
            elapsed = time.monotonic() - self.start_time
            alt = d.get('alt', 0) if fresh['position_valid'] else float('nan')
            speed = d.get('groundspeed', 0) if fresh['vfr_valid'] else float('nan')
            self.history_time.append(elapsed)
            self.history_alt.append(alt)
            self.history_speed.append(speed)
            self.history_time[:] = self.history_time[-200:]
            self.history_alt[:] = self.history_alt[-200:]
            self.history_speed[:] = self.history_speed[-200:]
            self.plot_panel.update_plots(self.history_time, self.history_alt, self.history_speed)
            self.analyze_view.update_telemetry(elapsed, alt, speed,
                climb=d.get('climb_rate', 0) if fresh['vfr_valid'] else float('nan'),
                volt=d.get('voltage', 0) if fresh['battery_valid'] else float('nan'),
                loss=d.get('packet_loss_pct', 0))
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
            self._closing = True
            self.fast_timer.stop()
            self.timer.stop()
            self.disconnect_vehicle()
            for worker in list(self._connection_workers):
                worker.wait(1500)
            self.camera_view.shutdown()
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
