"""
PythonGCS Flight Analytics & Telemetry Log Suite (AnalyzeView)
Provides multi-signal selectable telemetry plots, synchronized event timeline,
log export (CSV/KML), and safeguarded flight replay mode.
"""

import time
from typing import List, Dict, Any, Optional
import pyqtgraph as pg
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QCheckBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QFileDialog, QMessageBox, QFrame, QSplitter
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QFont
from gcs.ui.theme import get_theme, FONT_FAMILY_PRIMARY, FONT_FAMILY_MONO, get_button_style
from gcs.logs import log


class AnalyzeView(QWidget):
    """
    Dedicated post-flight and real-time telemetry analytics workspace.
    Includes multi-signal selectable graphing, flight event timeline, and replay protection.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.is_replay_mode = False
        self.replay_data: List[dict] = []
        self.replay_idx = 0

        # Telemetry history buffers
        self.timestamps: List[float] = []
        self.series: Dict[str, List[float]] = {
            'alt': [],
            'alt_amsl': [],
            'speed': [],
            'climb': [],
            'voltage': [],
            'battery': [],
            'loss': [],
            'rate': []
        }

        # Flight Events: List of (timestamp, event_type, details)
        self.events: List[Tuple[float, str, str]] = []

        self._build_ui()

    def _build_ui(self):
        t = get_theme()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)

        # 1. Top Replay Banner (hidden by default)
        self.replay_banner = QFrame()
        self.replay_banner.setStyleSheet(f"background-color: {get_theme()['danger']}; border-radius: 6px; padding: 4px;")
        rb_layout = QHBoxLayout(self.replay_banner)
        rb_layout.setContentsMargins(12, 4, 12, 4)
        
        self.replay_label = QLabel("LOG REVIEW — historical plots only; live vehicle telemetry and controls are separate")
        self.replay_label.setStyleSheet(f"color: {get_theme()['surface']}; font-family: 'Segoe UI'; font-weight: bold; font-size: 11px;")
        rb_layout.addWidget(self.replay_label)
        rb_layout.addStretch(1)

        self.btn_exit_replay = QPushButton("EXIT REPLAY")
        self.btn_exit_replay.setFixedHeight(22)
        self.btn_exit_replay.setStyleSheet(f"background-color: {get_theme()['surface']}; color: {get_theme()['danger']}; font-weight: bold; font-size: 10px; border-radius: 3px; padding: 2px 8px;")
        self.btn_exit_replay.clicked.connect(self.exit_replay_mode)
        rb_layout.addWidget(self.btn_exit_replay)
        self.replay_banner.hide()
        layout.addWidget(self.replay_banner)

        # 2. Control Toolbar (Signal Checkboxes, Export, Clear, Replay)
        tool_frame = QFrame()
        tool_frame.setObjectName("AnalyzeToolbar")
        tool_frame.setStyleSheet(f"#AnalyzeToolbar {{ background-color: {t['surface']}; border: 1px solid {t['border']}; border-radius: 8px; }}")
        tf_layout = QHBoxLayout(tool_frame)
        tf_layout.setContentsMargins(10, 6, 10, 6)
        tf_layout.setSpacing(12)

        # Signal selector checkboxes
        self.cb_alt = QCheckBox("Alt (Rel)")
        self.cb_alt.setChecked(True)
        self.cb_alt.setStyleSheet(f"color: {get_theme()['info']}; font-weight: bold;")
        tf_layout.addWidget(self.cb_alt)

        self.cb_speed = QCheckBox("Speed (m/s)")
        self.cb_speed.setChecked(True)
        self.cb_speed.setStyleSheet(f"color: {get_theme()['warning']}; font-weight: bold;")
        tf_layout.addWidget(self.cb_speed)

        self.cb_climb = QCheckBox("Climb (m/s)")
        self.cb_climb.setChecked(False)
        self.cb_climb.setStyleSheet(f"color: {get_theme()['info']}; font-weight: bold;")
        tf_layout.addWidget(self.cb_climb)

        self.cb_volt = QCheckBox("Voltage (V)")
        self.cb_volt.setChecked(False)
        self.cb_volt.setStyleSheet(f"color: {get_theme()['success']}; font-weight: bold;")
        tf_layout.addWidget(self.cb_volt)

        self.cb_loss = QCheckBox("Loss (%)")
        self.cb_loss.setChecked(False)
        self.cb_loss.setStyleSheet(f"color: {get_theme()['danger']}; font-weight: bold;")
        tf_layout.addWidget(self.cb_loss)

        tf_layout.addStretch(1)

        # Action Buttons
        self.btn_export_csv = QPushButton("EXPORT CSV")
        self.btn_export_csv.setFixedHeight(28)
        self.btn_export_csv.setStyleSheet(get_button_style('secondary', 'sm'))
        self.btn_export_csv.clicked.connect(self.export_csv)
        tf_layout.addWidget(self.btn_export_csv)

        self.btn_load_log = QPushButton("LOAD LOG REPLAY")
        self.btn_load_log.setFixedHeight(28)
        self.btn_load_log.setStyleSheet(get_button_style('primary', 'sm'))
        self.btn_load_log.clicked.connect(self.load_log_for_replay)
        tf_layout.addWidget(self.btn_load_log)

        self.btn_clear = QPushButton("CLEAR PLOTS")
        self.btn_clear.setFixedHeight(28)
        self.btn_clear.setStyleSheet(get_button_style('secondary', 'sm'))
        self.btn_clear.clicked.connect(self.clear_data)
        tf_layout.addWidget(self.btn_clear)

        layout.addWidget(tool_frame)

        # 3. Main Splitter: Multi-Signal Plot (Top 65%) + Flight Event Timeline (Bottom 35%)
        splitter = QSplitter(Qt.Orientation.Vertical)

        # PyQtGraph Plot Widget
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground(t['plot_bg'])
        self.plot_widget.showGrid(x=True, y=True, alpha=0.2)
        self.plot_widget.getAxis('left').setPen(pg.mkPen(color=t['border_strong'], width=1))
        self.plot_widget.getAxis('bottom').setPen(pg.mkPen(color=t['border_strong'], width=1))
        self.plot_widget.getAxis('left').setTextPen(t['text_secondary'])
        self.plot_widget.getAxis('bottom').setTextPen(t['text_secondary'])
        self.plot_widget.addLegend(offset=(10, 10))

        # Curves
        self.curve_alt = self.plot_widget.plot(pen=pg.mkPen(get_theme()['info'], width=2), name="Alt (m Rel)")
        self.curve_speed = self.plot_widget.plot(pen=pg.mkPen(get_theme()['warning'], width=2), name="Speed (m/s)")
        self.curve_climb = self.plot_widget.plot(pen=pg.mkPen(get_theme()['info'], width=1.5), name="Climb (m/s)")
        self.curve_volt = self.plot_widget.plot(pen=pg.mkPen(get_theme()['success'], width=1.5), name="Voltage (V)")
        self.curve_loss = self.plot_widget.plot(pen=pg.mkPen(get_theme()['danger'], width=1.5), name="Packet Loss (%)")

        splitter.addWidget(self.plot_widget)

        # Bottom Frame: Synchronized Flight Event Timeline
        event_frame = QFrame()
        event_frame.setObjectName("EventFrame")
        event_frame.setStyleSheet(f"#EventFrame {{ background-color: {t['surface']}; border: 1px solid {t['border']}; border-radius: 8px; }}")
        ef_layout = QVBoxLayout(event_frame)
        ef_layout.setContentsMargins(10, 8, 10, 8)
        ef_layout.setSpacing(6)

        ef_title = QLabel("SYNCHRONIZED FLIGHT EVENT TIMELINE")
        ef_title.setStyleSheet(f"color: {t['primary']}; font-family: {FONT_FAMILY_PRIMARY}; font-size: 11px; font-weight: bold;")
        ef_layout.addWidget(ef_title)

        self.event_table = QTableWidget(0, 3)
        self.event_table.setHorizontalHeaderLabels(["Timestamp", "Event Type", "Outcome / Details"])
        self.event_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.event_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.event_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        ef_layout.addWidget(self.event_table)

        splitter.addWidget(event_frame)
        splitter.setStretchFactor(0, 3) # 70% plots
        splitter.setStretchFactor(1, 1) # 30% events
        layout.addWidget(splitter, stretch=1)

    def log_event(self, event_type: str, details: str):
        """Records a timestamped flight event in the synchronized timeline."""
        ts = time.strftime("%H:%M:%S")
        self.events.append((time.monotonic(), event_type, details))
        if len(self.events) > 1000:
            self.events.pop(0)
            self.event_table.removeRow(0)
        row = self.event_table.rowCount()
        self.event_table.insertRow(row)
        self.event_table.setItem(row, 0, QTableWidgetItem(ts))
        self.event_table.setItem(row, 1, QTableWidgetItem(event_type))
        self.event_table.setItem(row, 2, QTableWidgetItem(details))
        self.event_table.scrollToBottom()

    def update_telemetry(self, t_sec: float, alt: float, speed: float, climb: float = 0.0, volt: float = 0.0, loss: float = 0.0):
        if self.is_replay_mode:
            return

        self.timestamps.append(t_sec)
        self.series['alt'].append(alt)
        self.series['speed'].append(speed)
        self.series['climb'].append(climb)
        self.series['voltage'].append(volt)
        self.series['loss'].append(loss)
        # Fields without a source stay explicitly unavailable, but every
        # series must have the same length (including after buffer rollover).
        for key in ('alt_amsl', 'battery', 'rate'):
            self.series[key].append(float('nan'))

        # Cap memory buffer to 1200 points (~10 mins at 2Hz)
        if len(self.timestamps) > 1200:
            self.timestamps.pop(0)
            for k in self.series:
                self.series[k].pop(0)

        self._refresh_plot_curves()

    def _refresh_plot_curves(self):
        if not self.timestamps:
            for curve in (self.curve_alt, self.curve_speed, self.curve_climb, self.curve_volt, self.curve_loss):
                curve.clear()
            return

        ts = self.timestamps
        if self.cb_alt.isChecked():
            self.curve_alt.setData(ts, self.series['alt'])
        else:
            self.curve_alt.clear()

        if self.cb_speed.isChecked():
            self.curve_speed.setData(ts, self.series['speed'])
        else:
            self.curve_speed.clear()

        if self.cb_climb.isChecked():
            self.curve_climb.setData(ts, self.series['climb'])
        else:
            self.curve_climb.clear()

        if self.cb_volt.isChecked():
            self.curve_volt.setData(ts, self.series['voltage'])
        else:
            self.curve_volt.clear()

        if self.cb_loss.isChecked():
            self.curve_loss.setData(ts, self.series['loss'])
        else:
            self.curve_loss.clear()

    def clear_data(self):
        self.timestamps.clear()
        for k in self.series:
            self.series[k].clear()
        self.event_table.setRowCount(0)
        self.events.clear()
        self._refresh_plot_curves()

    def export_csv(self):
        if not self.timestamps:
            QMessageBox.information(self, "No Data", "No telemetry samples recorded yet.")
            return

        filename, _ = QFileDialog.getSaveFileName(self, "Export Telemetry CSV", "", "CSV Files (*.csv)")
        if not filename:
            return
        if not filename.endswith(".csv"):
            filename += ".csv"

        import csv
        try:
            with open(filename, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(["Time_Sec", "Alt_Rel_m", "Groundspeed_ms", "Climb_ms", "Voltage_V", "Packet_Loss_pct"])
                for i in range(len(self.timestamps)):
                    writer.writerow([
                        f"{self.timestamps[i]:.2f}",
                        f"{self.series['alt'][i]:.2f}",
                        f"{self.series['speed'][i]:.2f}",
                        f"{self.series['climb'][i]:.2f}",
                        f"{self.series['voltage'][i]:.2f}",
                        f"{self.series['loss'][i]:.2f}"
                    ])
            QMessageBox.information(self, "Export Complete", f"Successfully exported {len(self.timestamps)} rows to:\n{filename}")
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Failed to export CSV: {e}")

    def load_log_for_replay(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Load Flight Log for Replay", "", "CSV Files (*.csv)")
        if not filename:
            return

        import csv
        try:
            new_ts = []
            new_series = {key: [] for key in self.series}
            columns = {'alt': 'Alt_Rel_m', 'speed': 'Groundspeed_ms', 'climb': 'Climb_ms',
                       'voltage': 'Voltage_V', 'loss': 'Packet_Loss_pct'}
            with open(filename, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    new_ts.append(float(row['Time_Sec']))
                    for key in new_series:
                        raw = row.get(columns.get(key, ''), '')
                        new_series[key].append(float(raw) if raw else float('nan'))

            self.clear_data()
            self.timestamps = new_ts
            self.series = new_series
            self._refresh_plot_curves()

            self.is_replay_mode = True
            self.replay_banner.show()
            self.log_event("REPLAY_START", f"Loaded log file: {filename}")
        except Exception as e:
            QMessageBox.critical(self, "Load Error", f"Failed to parse log file: {e}")

    def exit_replay_mode(self):
        self.is_replay_mode = False
        self.replay_banner.hide()
        self.clear_data()
        self.log_event("REPLAY_STOP", "Exited replay mode. Live telemetry restored.")
