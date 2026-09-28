import json
import time
import threading
from typing import Dict, Any, Optional, List
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QFileDialog, QMessageBox, QDialog,
    QProgressBar, QScrollArea
)
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
import gcs.telemetry as telemetry
from gcs.commands import request_all_parameters, set_parameter, request_parameter
from gcs.params import (
    decode_param_value, encode_param_value, validate_param_value,
    create_param_backup_data, compare_params_for_restore,
    PARAM_TYPE_NAMES, PARAM_TYPE_REAL32, PARAM_TYPE_INT32
)
from gcs.logs import log

class ParamDiffDialog(QDialog):
    """Dialog previewing differences between loaded file and current vehicle parameters."""
    def __init__(self, diffs: List[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Parameter Restore - Difference Preview")
        self.resize(750, 450)
        self.setStyleSheet("background-color: #ffffff; font-family: Google Sans Code;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel("PARAMETER DIFFERENCE PREVIEW")
        title.setStyleSheet("color: #0b57d0; font-size: 13px; font-weight: bold;")
        layout.addWidget(title)

        updates = [d for d in diffs if d['action'] == 'UPDATE']
        skips = [d for d in diffs if d['action'] in ('UNKNOWN_SKIP', 'TYPE_MISMATCH_SKIP')]
        same = [d for d in diffs if d['action'] == 'UNCHANGED']

        summary = QLabel(f"Total in file: {len(diffs)} | To Update: {len(updates)} | Incompatible/Skipped: {len(skips)} | Unchanged: {len(same)}")
        summary.setStyleSheet("color: #5f6368; font-size: 11px;")
        layout.addWidget(summary)

        self.table = QTableWidget(len(diffs), 5)
        self.table.setHorizontalHeaderLabels(["Parameter", "Current FCU", "New Value", "Type", "Action"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)

        for row, d in enumerate(diffs):
            name_item = QTableWidgetItem(d['name'])
            curr_item = QTableWidgetItem(str(d['current_value']) if d['current_value'] is not None else "---")
            new_item = QTableWidgetItem(str(d['target_value']))
            type_item = QTableWidgetItem(PARAM_TYPE_NAMES.get(d['type'], str(d['type'])))
            action_item = QTableWidgetItem(d['description'])

            if d['action'] == 'UPDATE':
                action_item.setForeground(QColor("#0b57d0"))
                name_item.setForeground(QColor("#0f172a"))
            elif 'SKIP' in d['action']:
                action_item.setForeground(QColor("#d93025"))
                name_item.setForeground(QColor("#5f6368"))
            else:
                action_item.setForeground(QColor("#5f6368"))
                name_item.setForeground(QColor("#5f6368"))

            self.table.setItem(row, 0, name_item)
            self.table.setItem(row, 1, curr_item)
            self.table.setItem(row, 2, new_item)
            self.table.setItem(row, 3, type_item)
            self.table.setItem(row, 4, action_item)

        layout.addWidget(self.table)

        btn_box = QHBoxLayout()
        cancel_btn = QPushButton("CANCEL")
        cancel_btn.setFixedHeight(32)
        cancel_btn.clicked.connect(self.reject)
        
        apply_btn = QPushButton(f"APPLY {len(updates)} UPDATES TO FCU")
        apply_btn.setFixedHeight(32)
        apply_btn.setStyleSheet("background-color: #0b57d0; color: #ffffff; font-weight: bold; padding: 4px 14px; border-radius: 4px;")
        apply_btn.clicked.connect(self.accept)
        apply_btn.setEnabled(len(updates) > 0)

        btn_box.addStretch(1)
        btn_box.addWidget(cancel_btn)
        btn_box.addWidget(apply_btn)
        layout.addLayout(btn_box)


class SetupSignals(QObject):
    upload_progress = pyqtSignal(int, int, str) # current, total, name
    upload_finished = pyqtSignal(int, int) # success_count, fail_count
    param_confirmed = pyqtSignal(str, object) # name, value


class SetupView(QWidget):
    def __init__(self, vehicle=None, parent=None):
        super().__init__(parent)
        self.vehicle = vehicle
        self._last_params: Dict[str, dict] = {}
        self._pending_edits: Dict[str, dict] = {} # {name: {'target_val': val, 'time': float, 'row': int}}
        self.signals = SetupSignals()
        self.signals.upload_progress.connect(self._on_upload_progress)
        self.signals.upload_finished.connect(self._on_upload_finished)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # Top Control Strip
        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Search parameters (e.g. MPC_XY, COM_ARM)...")
        self.search_bar.setFixedHeight(30)
        self.search_bar.setStyleSheet("""
            QLineEdit {
                background-color: #ffffff; color: #0f172a;
                border: 1px solid #cbd5e1; border-radius: 4px;
                padding: 4px 10px; font-family: Google Sans Code; font-size: 12px;
            }
        """)
        self.search_bar.textChanged.connect(self.on_search_changed)
        top_row.addWidget(self.search_bar, stretch=1)

        self.progress_lbl = QLabel("Parameters: 0 / 0")
        self.progress_lbl.setStyleSheet("color: #5f6368; font-family: Google Sans Code; font-size: 11px;")
        top_row.addWidget(self.progress_lbl)

        btn_style = """
            QPushButton {
                background-color: #ffffff; color: #0b57d0;
                border: 1px solid #0b57d0; border-radius: 4px;
                font-family: Google Sans Code; font-size: 11px; font-weight: bold;
                padding: 4px 12px;
            }
            QPushButton:hover { background-color: #0b57d0; color: #ffffff; }
            QPushButton:disabled { border-color: #cbd5e1; color: #5f6368; }
        """

        self.refresh_btn = QPushButton("REFRESH ALL")
        self.refresh_btn.setFixedHeight(30)
        self.refresh_btn.setStyleSheet(btn_style)
        self.refresh_btn.clicked.connect(self.on_refresh)
        top_row.addWidget(self.refresh_btn)

        self.req_missing_btn = QPushButton("REQ MISSING")
        self.req_missing_btn.setFixedHeight(30)
        self.req_missing_btn.setStyleSheet(btn_style)
        self.req_missing_btn.clicked.connect(self.on_request_missing)
        top_row.addWidget(self.req_missing_btn)

        self.save_btn = QPushButton("BACKUP")
        self.save_btn.setFixedHeight(30)
        self.save_btn.setStyleSheet(btn_style)
        self.save_btn.clicked.connect(self.on_save_params)
        top_row.addWidget(self.save_btn)

        self.load_btn = QPushButton("RESTORE")
        self.load_btn.setFixedHeight(30)
        self.load_btn.setStyleSheet(btn_style)
        self.load_btn.clicked.connect(self.on_load_params)
        top_row.addWidget(self.load_btn)

        layout.addLayout(top_row)

        # Parameter Table: Name, Value, Type, Status
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Parameter Name", "Value", "Type", "Status"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #ffffff; color: #0f172a;
                gridline-color: #cbd5e1;
                border: 1px solid #cbd5e1; border-radius: 6px;
                font-family: Google Sans Code; font-size: 12px;
            }
            QHeaderView::section {
                background-color: #f5f7fa; color: #0b57d0;
                padding: 4px; font-weight: bold; border: 1px solid #cbd5e1;
            }
        """)
        self.table.cellChanged.connect(self.on_cell_changed)
        layout.addWidget(self.table)

        # Polling timer for parameters updates (5 Hz)
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_table)
        self.timer.start(250)

        self.set_vehicle(vehicle)

    def set_vehicle(self, vehicle):
        self.vehicle = vehicle
        if vehicle is None:
            self.refresh_btn.setEnabled(False)
            self.req_missing_btn.setEnabled(False)
            self.save_btn.setEnabled(False)
            self.load_btn.setEnabled(False)
            self.table.blockSignals(True)
            self.table.setRowCount(0)
            self.table.blockSignals(False)
            self._last_params.clear()
            self._pending_edits.clear()
            self.progress_lbl.setText("Parameters: 0 / 0")
        else:
            self.refresh_btn.setEnabled(True)
            self.req_missing_btn.setEnabled(True)
            self.save_btn.setEnabled(True)
            self.load_btn.setEnabled(True)

    def on_search_changed(self):
        self.update_table(force=True)

    def on_refresh(self):
        if not self.vehicle:
            return
        threading.Thread(target=request_all_parameters, args=(self.vehicle,), daemon=True).start()

    def on_request_missing(self):
        if not self.vehicle:
            return
        with telemetry.parameters_lock:
            stats = telemetry.param_download_stats
            total = stats.get('total_count', 0)
            received = stats.get('received_indices', set())
            missing = [i for i in range(total) if i not in received]

        if not missing:
            log("Parameter manager: All parameters already received!")
            return

        log(f"Parameter manager: Requesting {len(missing)} missing parameters...")
        def _req_worker():
            for idx in missing[:50]: # Request batch of missing
                if not self.vehicle:
                    break
                request_parameter(self.vehicle, idx)
                time.sleep(0.04)
        threading.Thread(target=_req_worker, daemon=True).start()

    def on_cell_changed(self, row, column):
        if column != 1 or not self.vehicle:
            return

        param_name_item = self.table.item(row, 0)
        param_val_item = self.table.item(row, 1)
        if not param_name_item or not param_val_item:
            return

        param_name = param_name_item.text()
        new_val_str = param_val_item.text().strip()

        with telemetry.parameters_lock:
            meta = telemetry.parameters_data.get(param_name)

        if not meta:
            return

        p_type = meta.get('type', PARAM_TYPE_REAL32)
        is_valid, parsed_val, err_msg = validate_param_value(new_val_str, p_type)

        if not is_valid:
            # Revert to confirmed value
            self.table.blockSignals(True)
            param_val_item.setText(str(meta['value']))
            status_item = self.table.item(row, 3)
            if status_item:
                status_item.setText(f"ERROR: {err_msg}")
                status_item.setForeground(QColor("#d93025"))
            self.table.blockSignals(False)
            return

        # Check if identical to confirmed value
        if parsed_val == meta['value']:
            return

        # Mark as PENDING without mutating confirmed cache prematurely
        self._pending_edits[param_name] = {
            'target_val': parsed_val,
            'time': time.monotonic(),
            'orig_val': meta['value']
        }

        status_item = self.table.item(row, 3)
        if status_item:
            status_item.setText("PENDING WRITE...")
            status_item.setForeground(QColor("#e37400"))

        # Send PARAM_SET in background
        def _set_worker():
            set_parameter(self.vehicle, param_name, parsed_val, p_type)
        threading.Thread(target=_set_worker, daemon=True).start()

    def update_table(self, force=False):
        with telemetry.parameters_lock:
            current_params = dict(telemetry.parameters_data)
            stats = dict(telemetry.param_download_stats)

        total_cnt = stats.get('total_count', 0)
        recv_cnt = len(stats.get('received_indices', set()))
        if total_cnt > 0:
            pct = int((recv_cnt / total_cnt) * 100)
            self.progress_lbl.setText(f"Parameters: {recv_cnt}/{total_cnt} ({pct}%)")
        else:
            self.progress_lbl.setText(f"Parameters: {len(current_params)}")

        # Check pending edits for timeouts or confirmations
        now = time.monotonic()
        for name, pending in list(self._pending_edits.items()):
            meta = current_params.get(name)
            if meta:
                target_val = pending['target_val']
                curr_val = meta.get('value')
                # Check confirmation
                confirmed = False
                if meta.get('type') == PARAM_TYPE_REAL32:
                    confirmed = abs(float(curr_val) - float(target_val)) < 1e-5
                else:
                    confirmed = (curr_val == target_val)

                if confirmed:
                    del self._pending_edits[name]
                    log(f"Parameter {name} readback CONFIRMED = {curr_val}")
                elif now - pending['time'] > 4.0: # 4 second timeout
                    del self._pending_edits[name]
                    log(f"Parameter {name} write TIMEOUT: reverting to {pending['orig_val']}")

        if not force and current_params == self._last_params and not self._pending_edits:
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
            p_type = meta.get('type', PARAM_TYPE_REAL32)
            type_str = PARAM_TYPE_NAMES.get(p_type, f"TYPE_{p_type}")

            # Col 0: Name (Read-only)
            name_item = QTableWidgetItem(name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            name_item.setForeground(QColor("#0f172a"))
            self.table.setItem(row, 0, name_item)

            # Col 1: Value (Editable)
            val_to_show = str(meta.get('value'))
            if name in self._pending_edits:
                val_to_show = str(self._pending_edits[name]['target_val'])
            val_item = QTableWidgetItem(val_to_show)
            val_item.setForeground(QColor("#0b57d0"))
            self.table.setItem(row, 1, val_item)

            # Col 2: Type (Read-only)
            type_item = QTableWidgetItem(type_str)
            type_item.setFlags(type_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            type_item.setForeground(QColor("#5f6368"))
            self.table.setItem(row, 2, type_item)

            # Col 3: Status (Read-only)
            if name in self._pending_edits:
                status_item = QTableWidgetItem("PENDING...")
                status_item.setForeground(QColor("#e37400"))
            else:
                status_item = QTableWidgetItem("CONFIRMED")
                status_item.setForeground(QColor("#0f9d58"))
            status_item.setFlags(status_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 3, status_item)

        self.table.blockSignals(False)

    def on_save_params(self):
        filename, _ = QFileDialog.getSaveFileName(
            self, "Backup Parameters", "", "JSON Files (*.json);;Parameter Files (*.param)"
        )
        if not filename:
            return

        with telemetry.parameters_lock:
            vehicle_info = {
                'system_id': getattr(self.vehicle, 'target_system', 1),
                'component_id': getattr(self.vehicle, 'target_component', 1),
                'autopilot': 'PX4'
            }
            backup_dict = create_param_backup_data(telemetry.parameters_data, vehicle_info)

        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(backup_dict, f, indent=2)
            log(f"Setup: Successfully backed up {backup_dict['count']} parameters to {filename}")
            QMessageBox.information(self, "Backup Complete", f"Successfully saved {backup_dict['count']} parameters to {filename}")
        except Exception as e:
            log(f"Setup: Failed to save parameters: {e}")
            QMessageBox.critical(self, "Backup Failed", str(e))

    def on_load_params(self):
        if not self.vehicle:
            return

        filename, _ = QFileDialog.getOpenFileName(
            self, "Restore Parameters", "", "JSON Files (*.json);;Parameter Files (*.param)"
        )
        if not filename:
            return

        try:
            with open(filename, 'r', encoding='utf-8') as f:
                load_dict = json.load(f)
        except Exception as e:
            log(f"Setup: Failed to read parameter file: {e}")
            QMessageBox.critical(self, "Read Error", f"Failed to read file: {e}")
            return

        with telemetry.parameters_lock:
            current_params = dict(telemetry.parameters_data)

        diffs = compare_params_for_restore(current_params, load_dict)
        if not diffs:
            QMessageBox.information(self, "No Parameters", "No compatible parameters found in file.")
            return

        diff_dlg = ParamDiffDialog(diffs, self)
        if diff_dlg.exec() != QDialog.DialogCode.Accepted:
            return

        updates_to_write = [d for d in diffs if d['action'] == 'UPDATE']
        threading.Thread(target=self._upload_parameters_worker, args=(updates_to_write,), daemon=True).start()

    def _upload_parameters_worker(self, updates: List[dict]):
        total = len(updates)
        log(f"Setup: Starting restore write of {total} parameters...")
        success_cnt = 0
        fail_cnt = 0

        for idx, item in enumerate(updates):
            if not self.vehicle:
                break
            name = item['name']
            val = item['target_value']
            p_type = item['type']

            self.signals.upload_progress.emit(idx + 1, total, name)
            set_parameter(self.vehicle, name, val, p_type)
            success_cnt += 1
            time.sleep(0.06)

        self.signals.upload_finished.emit(success_cnt, fail_cnt)

    def _on_upload_progress(self, current, total, name):
        self.progress_lbl.setText(f"Restoring: {current}/{total} ({name})")

    def _on_upload_finished(self, success_cnt, fail_cnt):
        log(f"Setup: Restore upload complete! Wrote {success_cnt} parameters.")
        self.update_table(force=True)
        QMessageBox.information(
            self, "Restore Complete",
            f"Successfully dispatched {success_cnt} parameter writes to flight controller."
        )
