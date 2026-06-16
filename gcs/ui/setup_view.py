import json
import time
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QFileDialog, QMessageBox
)
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QColor
import gcs.telemetry as telemetry
from gcs.commands import request_all_parameters, set_parameter
import threading

class SetupView(QWidget):
    def __init__(self, vehicle=None):
        super().__init__()
        self.vehicle = vehicle
        self._last_params = {} # Cache to track what is currently shown

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # Top row: Search and Refresh
        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Filter parameters by name...")
        self.search_bar.setStyleSheet("""
            QLineEdit {
                background-color: #0f172a; color: #f8fafc;
                border: 1px solid #1e293b; border-radius: 4px;
                padding: 4px 8px; font-family: Courier New; font-size: 12px;
            }
        """)
        self.search_bar.textChanged.connect(self.on_search_changed)
        top_row.addWidget(self.search_bar, stretch=1)

        self.refresh_btn = QPushButton("REFRESH")
        self.refresh_btn.setFixedHeight(30)
        self.refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: #0f172a; color: #00e5ff;
                border: 2px solid #00e5ff; border-radius: 6px;
                font-family: Courier New; font-weight: bold;
                padding: 4px 12px;
            }
            QPushButton:hover { background-color: #00e5ff; color: #0f172a; }
            QPushButton:disabled { border-color: #1e293b; color: #64748b; }
        """)
        self.refresh_btn.clicked.connect(self.on_refresh)
        top_row.addWidget(self.refresh_btn)

        self.save_btn = QPushButton("SAVE")
        self.save_btn.setFixedHeight(30)
        self.save_btn.setStyleSheet(self.refresh_btn.styleSheet())
        self.save_btn.clicked.connect(self.on_save_params)
        top_row.addWidget(self.save_btn)

        self.load_btn = QPushButton("LOAD")
        self.load_btn.setFixedHeight(30)
        self.load_btn.setStyleSheet(self.refresh_btn.styleSheet())
        self.load_btn.clicked.connect(self.on_load_params)
        top_row.addWidget(self.load_btn)

        layout.addLayout(top_row)

        # Table widget
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Parameter Name", "Value"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #0f172a; color: #f8fafc;
                gridline-color: #1e293b;
                border: 1px solid #1e293b; border-radius: 6px;
                font-family: Courier New; font-size: 12px;
            }
            QHeaderView::section {
                background-color: #060a13; color: #00e5ff;
                padding: 4px; font-weight: bold; border: 1px solid #1e293b;
            }
        """)
        self.table.cellChanged.connect(self.on_cell_changed)
        layout.addWidget(self.table)

        # Polling timer for parameters updates (5 Hz)
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_table)
        self.timer.start(200)

        self.set_vehicle(vehicle)

    def set_vehicle(self, vehicle):
        self.vehicle = vehicle
        if vehicle is None:
            self.refresh_btn.setEnabled(False)
            self.save_btn.setEnabled(False)
            self.load_btn.setEnabled(False)
            self.table.blockSignals(True)
            self.table.setRowCount(0)
            self.table.blockSignals(False)
            self._last_params.clear()
            with telemetry.parameters_lock:
                telemetry.parameters_data.clear()
        else:
            self.refresh_btn.setEnabled(True)
            self.save_btn.setEnabled(True)
            self.load_btn.setEnabled(True)

    def on_search_changed(self):
        self.update_table(force=True)

    def on_refresh(self):
        if not self.vehicle:
            return
        import threading
        threading.Thread(target=request_all_parameters, args=(self.vehicle,), daemon=True).start()

    def on_cell_changed(self, row, column):
        if column != 1 or not self.vehicle:
            return
        
        param_name_item = self.table.item(row, 0)
        param_val_item = self.table.item(row, 1)
        if not param_name_item or not param_val_item:
            return
        
        param_name = param_name_item.text()
        new_val_str = param_val_item.text()

        with telemetry.parameters_lock:
            param_meta = telemetry.parameters_data.get(param_name)
        
        if not param_meta:
            return

        try:
            new_val = float(new_val_str)
        except ValueError:
            # Revert to old value
            self.table.blockSignals(True)
            param_val_item.setText(str(param_meta['value']))
            self.table.blockSignals(False)
            return

        if new_val == param_meta['value']:
            return

        with telemetry.parameters_lock:
            telemetry.parameters_data[param_name]['value'] = new_val

        import threading
        param_type = param_meta['type']
        threading.Thread(target=set_parameter, args=(self.vehicle, param_name, new_val, param_type), daemon=True).start()

    def update_table(self, force=False):
        with telemetry.parameters_lock:
            current_params = dict(telemetry.parameters_data)

        if not force and current_params == self._last_params:
            return

        self._last_params = current_params

        search_txt = self.search_bar.text().upper()
        filtered_names = sorted([
            name for name in current_params.keys()
            if search_txt in name.upper()
        ])

        self.table.blockSignals(True)
        self.table.setRowCount(len(filtered_names))

        for row, name in enumerate(filtered_names):
            meta = current_params[name]
            
            # Name column (Read Only)
            name_item = QTableWidgetItem(name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            name_item.setForeground(QColor("#64748b"))
            self.table.setItem(row, 0, name_item)

            # Value column (Editable)
            val_item = QTableWidgetItem(str(meta['value']))
            val_item.setForeground(QColor("#00e5ff"))
            self.table.setItem(row, 1, val_item)

        self.table.blockSignals(False)

    def on_save_params(self):
        filename, _ = QFileDialog.getSaveFileName(
            self, "Save Parameters", "", "Parameter Files (*.param);;JSON Files (*.json)"
        )
        if not filename:
            return

        with telemetry.parameters_lock:
            save_dict = {name: meta['value'] for name, meta in telemetry.parameters_data.items()}

        try:
            with open(filename, 'w') as f:
                json.dump(save_dict, f, indent=4)
            from gcs.logs import log
            log(f"Setup: Successfully saved {len(save_dict)} parameters to {filename}")
        except Exception as e:
            from gcs.logs import log
            log(f"Setup: Failed to save parameters: {e}")

    def on_load_params(self):
        if not self.vehicle:
            return
        
        filename, _ = QFileDialog.getOpenFileName(
            self, "Load Parameters", "", "Parameter Files (*.param);;JSON Files (*.json)"
        )
        if not filename:
            return

        try:
            with open(filename, 'r') as f:
                load_dict = json.load(f)
        except Exception as e:
            from gcs.logs import log
            log(f"Setup: Failed to read parameter file: {e}")
            return

        reply = QMessageBox.question(
            self, 'Confirm Load',
            f"Are you sure you want to write {len(load_dict)} parameters to the flight controller?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        threading.Thread(target=self._upload_parameters_thread, args=(load_dict,), daemon=True).start()

    def _upload_parameters_thread(self, param_dict):
        from gcs.logs import log
        log(f"Setup: Starting write of {len(param_dict)} parameters...")
        success_count = 0
        
        for param_name, target_val in param_dict.items():
            if not self.vehicle:
                break
                
            with telemetry.parameters_lock:
                param_meta = telemetry.parameters_data.get(param_name)
                
            if not param_meta:
                param_type = 9 # MAV_PARAM_TYPE_REAL32 (default float)
            else:
                param_type = param_meta['type']
                if param_meta['value'] == target_val:
                    continue

            set_parameter(self.vehicle, param_name, target_val, param_type)
            with telemetry.parameters_lock:
                if param_name in telemetry.parameters_data:
                    telemetry.parameters_data[param_name]['value'] = target_val
            success_count += 1
            time.sleep(0.05)

        log(f"Setup: Upload complete! Wrote {success_count} parameters to flight controller.")
        self.update_table(force=True)
