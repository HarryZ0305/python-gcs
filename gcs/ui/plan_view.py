"""
PythonGCS Mission Planning Workspace (PlanView)
Provides synchronized map & mission item editor, undo/redo local edit history,
explicit altitude frames, survey generator, and verifiable vehicle mission synchronization.
"""

import copy
from typing import List, Optional, Tuple, Dict, Any
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QDoubleSpinBox, QComboBox, QFrame,
    QFileDialog, QMessageBox, QSplitter
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from gcs.ui.theme import get_theme, FONT_FAMILY_PRIMARY, FONT_FAMILY_MONO, get_button_style, get_pill_style
from gcs.ui.map_view import MapView
from gcs.plan_format import export_qgc_plan, import_plan_file, calculate_mission_stats
from gcs.ui.survey_dialog import SurveyGridDialog
from gcs.commands import upload_mission, download_mission
from gcs.logs import log


class PlanView(QWidget):
    """
    Dedicated autonomous flight planning workspace.
    Synchronizes local draft state, undo/redo history, and vehicle mission readback.
    """
    mission_uploaded = pyqtSignal(bool, str)

    def __init__(self, vehicle=None, map_view=None, parent=None):
        super().__init__(parent)
        self.vehicle = vehicle
        self._external_map_view = map_view

        # Mission Model
        self.waypoints: List[List[float]] = [] # [[lat, lon, alt], ...]
        self.takeoff_point: Optional[List[float]] = None
        self.landing_point: Optional[List[float]] = None
        self.default_alt = 15.0

        # Undo / Redo History Stack
        self._undo_stack: List[dict] = []
        self._redo_stack: List[dict] = []
        self._save_state_to_undo(record_initial=True)

        # Sync States: 'DRAFT', 'UNSAVED', 'UPLOADING', 'VERIFIED', 'MISMATCH'
        self.sync_state = 'DRAFT'
        self.verified_vehicle_items = 0

        self._build_ui()

    def _build_ui(self):
        t = get_theme()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)

        # 1. Top Mission Control Strip
        top_bar = QFrame()
        top_bar.setObjectName("PlanTopBar")
        top_bar.setStyleSheet(f"""
            #PlanTopBar {{
                background-color: {t['surface']};
                border: 1px solid {t['border']};
                border-radius: 8px;
            }}
        """)
        tb_layout = QHBoxLayout(top_bar)
        tb_layout.setContentsMargins(10, 6, 10, 6)
        tb_layout.setSpacing(8)

        # State Badge
        self.sync_badge = QLabel("LOCAL DRAFT")
        self.sync_badge.setStyleSheet(get_pill_style('neutral', filled=True))
        tb_layout.addWidget(self.sync_badge)

        # Mission Stats Summary
        self.stats_label = QLabel("0 Items | 0.0 m | 00:00 Est")
        self.stats_label.setStyleSheet(f"color: {t['text_secondary']}; font-family: {FONT_FAMILY_MONO}; font-size: 11px; font-weight: bold;")
        tb_layout.addWidget(self.stats_label)

        tb_layout.addStretch(1)

        # Undo / Redo
        self.btn_undo = QPushButton("UNDO")
        self.btn_undo.setFixedHeight(28)
        self.btn_undo.setStyleSheet(get_button_style('secondary', 'sm'))
        self.btn_undo.clicked.connect(self.undo)
        tb_layout.addWidget(self.btn_undo)

        self.btn_redo = QPushButton("REDO")
        self.btn_redo.setFixedHeight(28)
        self.btn_redo.setStyleSheet(get_button_style('secondary', 'sm'))
        self.btn_redo.clicked.connect(self.redo)
        tb_layout.addWidget(self.btn_redo)

        # Survey Grid Button
        self.btn_survey = QPushButton("SURVEY GRID")
        self.btn_survey.setFixedHeight(28)
        self.btn_survey.setStyleSheet(get_button_style('primary', 'sm'))
        self.btn_survey.clicked.connect(self.open_survey_dialog)
        tb_layout.addWidget(self.btn_survey)

        # Import / Export
        self.btn_import = QPushButton("IMPORT .PLAN")
        self.btn_import.setFixedHeight(28)
        self.btn_import.setStyleSheet(get_button_style('secondary', 'sm'))
        self.btn_import.clicked.connect(self.import_plan)
        tb_layout.addWidget(self.btn_import)

        self.btn_export = QPushButton("EXPORT .PLAN")
        self.btn_export.setFixedHeight(28)
        self.btn_export.setStyleSheet(get_button_style('secondary', 'sm'))
        self.btn_export.clicked.connect(self.export_plan)
        tb_layout.addWidget(self.btn_export)

        # Upload & Download
        self.btn_upload = QPushButton("UPLOAD TO FCU")
        self.btn_upload.setFixedHeight(28)
        self.btn_upload.setStyleSheet(get_button_style('success', 'sm'))
        self.btn_upload.clicked.connect(self.upload_to_vehicle)
        tb_layout.addWidget(self.btn_upload)

        self.btn_download = QPushButton("READ FROM FCU")
        self.btn_download.setFixedHeight(28)
        self.btn_download.setStyleSheet(get_button_style('secondary', 'sm'))
        self.btn_download.clicked.connect(self.download_from_vehicle)
        tb_layout.addWidget(self.btn_download)

        # Clear local vs clear vehicle
        self.btn_clear_draft = QPushButton("CLEAR DRAFT")
        self.btn_clear_draft.setFixedHeight(28)
        self.btn_clear_draft.setStyleSheet(get_button_style('danger', 'sm'))
        self.btn_clear_draft.clicked.connect(self.clear_local_draft)
        tb_layout.addWidget(self.btn_clear_draft)

        layout.addWidget(top_bar)

        # 2. Main Splitter: Synchronized Map (Left/Center) + Mission Item Editor (Right)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Synchronized Interactive Map
        if self._external_map_view is not None:
            self.map_view = self._external_map_view
        else:
            self.map_view = MapView()
        self.map_view.waypoint_added.connect(self._on_map_waypoint_added)
        self.map_view.takeoff_added.connect(self._on_map_takeoff_added)
        self.map_view.landing_added.connect(self._on_map_landing_added)
        if isinstance(self.map_view, QWidget):
            splitter.addWidget(self.map_view)

        # Right Panel: Mission Items Table & Selected Item Editor
        right_panel = QFrame()
        right_panel.setObjectName("PlanRightPanel")
        right_panel.setMinimumWidth(360)
        right_panel.setStyleSheet(f"""
            #PlanRightPanel {{
                background-color: {t['surface']};
                border: 1px solid {t['border']};
                border-radius: 8px;
            }}
        """)
        rp_layout = QVBoxLayout(right_panel)
        rp_layout.setContentsMargins(10, 10, 10, 10)
        rp_layout.setSpacing(8)

        rp_title = QLabel("MISSION ITEMS LIST")
        rp_title.setStyleSheet(f"color: {t['primary']}; font-family: {FONT_FAMILY_PRIMARY}; font-size: 11px; font-weight: bold;")
        rp_layout.addWidget(rp_title)

        # Table: Seq, Command, Lat, Lon, Alt (Rel)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Seq", "Type", "Lat", "Lon", "Alt (m)"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._on_table_selection_changed)
        rp_layout.addWidget(self.table, stretch=1)

        # Item Editing Actions (Delete, Move Up, Move Down)
        edit_row = QHBoxLayout()
        self.btn_del = QPushButton("DELETE ITEM")
        self.btn_del.setStyleSheet(get_button_style('danger', 'sm'))
        self.btn_del.clicked.connect(self.delete_selected_item)
        edit_row.addWidget(self.btn_del)

        self.btn_up = QPushButton("MOVE UP")
        self.btn_up.setStyleSheet(get_button_style('secondary', 'sm'))
        self.btn_up.clicked.connect(self.move_item_up)
        edit_row.addWidget(self.btn_up)

        self.btn_down = QPushButton("MOVE DOWN")
        self.btn_down.setStyleSheet(get_button_style('secondary', 'sm'))
        self.btn_down.clicked.connect(self.move_item_down)
        edit_row.addWidget(self.btn_down)
        rp_layout.addLayout(edit_row)

        # Selected Item Property Editor
        prop_frame = QFrame()
        prop_frame.setStyleSheet(f"background-color: {t['surface_elevated']}; border: 1px solid {t['border']}; border-radius: 6px; padding: 6px;")
        prop_layout = QVBoxLayout(prop_frame)
        prop_layout.setContentsMargins(8, 6, 8, 6)
        prop_layout.setSpacing(6)

        prop_title = QLabel("ITEM ALTITUDE & FRAME")
        prop_title.setStyleSheet(f"color: {t['text_secondary']}; font-weight: bold; font-size: 10px;")
        prop_layout.addWidget(prop_title)

        alt_row = QHBoxLayout()
        alt_lbl = QLabel("Altitude (m):")
        alt_lbl.setStyleSheet(f"color: {t['text']}; font-size: 11px;")
        alt_row.addWidget(alt_lbl)

        self.alt_edit = QDoubleSpinBox()
        self.alt_edit.setRange(1.0, 150.0)
        self.alt_edit.setValue(self.default_alt)
        self.alt_edit.setSingleStep(1.0)
        self.alt_edit.valueChanged.connect(self._on_selected_alt_changed)
        alt_row.addWidget(self.alt_edit)

        self.frame_combo = QComboBox()
        self.frame_combo.addItem("Alt (Rel Home)", 3)
        self.frame_combo.addItem("Alt AMSL", 0)
        alt_row.addWidget(self.frame_combo)
        prop_layout.addLayout(alt_row)

        rp_layout.addWidget(prop_frame)

        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 3) # Map takes 75%
        splitter.setStretchFactor(1, 1) # Panel takes 25%
        layout.addWidget(splitter, stretch=1)

        self._update_ui_state()

    def set_vehicle(self, vehicle):
        self.vehicle = vehicle

    def _save_state_to_undo(self, record_initial=False):
        state = {
            'waypoints': copy.deepcopy(self.waypoints),
            'takeoff_point': copy.deepcopy(self.takeoff_point),
            'landing_point': copy.deepcopy(self.landing_point)
        }
        if not record_initial:
            self._undo_stack.append(state)
            if len(self._undo_stack) > 30:
                self._undo_stack.pop(0)
            self._redo_stack.clear()
            self.sync_state = 'UNSAVED'
            self._update_ui_state()

    def undo(self):
        if not self._undo_stack:
            return
        curr = {
            'waypoints': copy.deepcopy(self.waypoints),
            'takeoff_point': copy.deepcopy(self.takeoff_point),
            'landing_point': copy.deepcopy(self.landing_point)
        }
        self._redo_stack.append(curr)
        prev = self._undo_stack.pop()
        self.waypoints = prev['waypoints']
        self.takeoff_point = prev['takeoff_point']
        self.landing_point = prev['landing_point']
        self.sync_state = 'UNSAVED'
        self._sync_all()

    def redo(self):
        if not self._redo_stack:
            return
        curr = {
            'waypoints': copy.deepcopy(self.waypoints),
            'takeoff_point': copy.deepcopy(self.takeoff_point),
            'landing_point': copy.deepcopy(self.landing_point)
        }
        self._undo_stack.append(curr)
        nxt = self._redo_stack.pop()
        self.waypoints = nxt['waypoints']
        self.takeoff_point = nxt['takeoff_point']
        self.landing_point = nxt['landing_point']
        self.sync_state = 'UNSAVED'
        self._sync_all()

    def add_waypoint(self, lat: float, lon: float, alt: Optional[float] = None):
        self._save_state_to_undo()
        self.waypoints.append([lat, lon, alt if alt is not None else self.default_alt])
        self._sync_all()

    def clear_plan(self):
        self._save_state_to_undo()
        self.waypoints.clear()
        self.takeoff_point = None
        self.landing_point = None
        self.sync_state = 'DRAFT'
        self._sync_all()

    def _on_map_waypoint_added(self, lat: float, lon: float):
        self.add_waypoint(lat, lon)

    def _on_map_takeoff_added(self, lat: float, lon: float):
        self._save_state_to_undo()
        self.takeoff_point = [lat, lon, self.default_alt]
        self._sync_all()

    def _on_map_landing_added(self, lat: float, lon: float):
        self._save_state_to_undo()
        self.landing_point = [lat, lon, 0.0]
        self._sync_all()

    def _sync_all(self):
        """Synchronizes map markers, table rows, and mission stats."""
        # Update Table
        self.table.blockSignals(True)
        items = []
        if self.takeoff_point:
            items.append(("TAKEOFF", self.takeoff_point))
        for wp in self.waypoints:
            items.append(("WAYPOINT", wp))
        if self.landing_point:
            items.append(("LAND", self.landing_point))

        self.table.setRowCount(len(items))
        for row, (itype, coord) in enumerate(items):
            self.table.setItem(row, 0, QTableWidgetItem(str(row + 1)))
            self.table.setItem(row, 1, QTableWidgetItem(itype))
            self.table.setItem(row, 2, QTableWidgetItem(f"{coord[0]:.6f}"))
            self.table.setItem(row, 3, QTableWidgetItem(f"{coord[1]:.6f}"))
            alt_val = coord[2] if len(coord) > 2 else self.default_alt
            self.table.setItem(row, 4, QTableWidgetItem(f"{alt_val:.1f}"))
        self.table.blockSignals(False)

        # Update Map
        self.map_view.set_waypoints(self.waypoints, self.takeoff_point, self.landing_point)

        # Update Stats
        stats = calculate_mission_stats(self.waypoints, self.takeoff_point, self.landing_point)
        dist_m = stats['total_distance_m']
        dur_s = stats['est_flight_time_s']
        mins = int(dur_s // 60)
        secs = int(dur_s % 60)
        wh = stats['est_energy_wh']
        self.stats_label.setText(f"{stats['item_count']} Items | {dist_m:.0f} m | {mins:02d}:{secs:02d} Est (~{wh:.1f} Wh)")

        self._update_ui_state()

    def _update_ui_state(self):
        state_map = {
            'DRAFT': ('LOCAL DRAFT', 'neutral'),
            'UNSAVED': ('UNSAVED CHANGES', 'warning'),
            'UPLOADING': ('UPLOADING TO FCU...', 'primary'),
            'VERIFIED': (f'FCU MISSION VERIFIED ({self.verified_vehicle_items} items)', 'success'),
            'MISMATCH': ('LOCAL / FCU MISMATCH', 'danger')
        }
        text, variant = state_map.get(self.sync_state, ('LOCAL DRAFT', 'neutral'))
        self.sync_badge.setText(text)
        self.sync_badge.setStyleSheet(get_pill_style(variant, filled=True))

        self.btn_undo.setEnabled(len(self._undo_stack) > 0)
        self.btn_redo.setEnabled(len(self._redo_stack) > 0)

    def _on_table_selection_changed(self):
        selected = self.table.selectedItems()
        if not selected:
            return
        row = selected[0].row()
        alt_item = self.table.item(row, 4)
        if alt_item:
            try:
                val = float(alt_item.text())
                self.alt_edit.blockSignals(True)
                self.alt_edit.setValue(val)
                self.alt_edit.blockSignals(False)
            except ValueError:
                pass

    def _on_selected_alt_changed(self, new_alt: float):
        selected = self.table.selectedItems()
        if not selected:
            return
        row = selected[0].row()
        self._save_state_to_undo()

        offset = 0
        if self.takeoff_point:
            if row == 0:
                self.takeoff_point[2] = new_alt
                self._sync_all()
                return
            offset = 1

        wp_idx = row - offset
        if 0 <= wp_idx < len(self.waypoints):
            self.waypoints[wp_idx][2] = new_alt
        elif self.landing_point and row == len(self.waypoints) + offset:
            self.landing_point[2] = new_alt

        self._sync_all()

    def delete_selected_item(self):
        row = self.table.currentRow()
        if row < 0:
            return
        self._save_state_to_undo()

        offset = 0
        if self.takeoff_point:
            if row == 0:
                self.takeoff_point = None
                self._sync_all()
                return
            offset = 1

        wp_idx = row - offset
        if 0 <= wp_idx < len(self.waypoints):
            self.waypoints.pop(wp_idx)
        elif self.landing_point and row == len(self.waypoints) + offset:
            self.landing_point = None

        self._sync_all()

    def move_item_up(self):
        row = self.table.currentRow()
        offset = 1 if self.takeoff_point else 0
        wp_idx = row - offset
        if wp_idx > 0 and wp_idx < len(self.waypoints):
            self._save_state_to_undo()
            self.waypoints[wp_idx - 1], self.waypoints[wp_idx] = self.waypoints[wp_idx], self.waypoints[wp_idx - 1]
            self._sync_all()
            self.table.selectRow(row - 1)

    def move_item_down(self):
        row = self.table.currentRow()
        offset = 1 if self.takeoff_point else 0
        wp_idx = row - offset
        if 0 <= wp_idx < len(self.waypoints) - 1:
            self._save_state_to_undo()
            self.waypoints[wp_idx], self.waypoints[wp_idx + 1] = self.waypoints[wp_idx + 1], self.waypoints[wp_idx]
            self._sync_all()
            self.table.selectRow(row + 1)

    def clear_local_draft(self):
        """Clears local plan draft ONLY. Does NOT modify the vehicle mission."""
        reply = QMessageBox.question(
            self,
            "Clear Local Draft",
            "Are you sure you want to clear your local mission draft?\n(This will not affect the mission stored on the drone)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._save_state_to_undo()
            self.waypoints.clear()
            self.takeoff_point = None
            self.landing_point = None
            self.sync_state = 'DRAFT'
            self._sync_all()

    def open_survey_dialog(self):
        dlg = SurveyGridDialog(self)
        if dlg.exec() == SurveyGridDialog.DialogCode.Accepted:
            grid_wps = dlg.get_grid_waypoints()
            if grid_wps:
                self._save_state_to_undo()
                self.waypoints.extend(grid_wps)
                self._sync_all()

    def export_plan(self):
        filename, _ = QFileDialog.getSaveFileName(self, "Export QGC .plan", "", "QGroundControl Plan (*.plan)")
        if not filename:
            return
        if not filename.endswith(".plan"):
            filename += ".plan"
        ok = export_qgc_plan(filename, self.waypoints, self.takeoff_point, self.landing_point, self.default_alt)
        if ok:
            QMessageBox.information(self, "Plan Exported", f"Successfully exported plan to:\n{filename}")

    def import_plan(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Import Plan", "", "Plan Files (*.plan *.json)")
        if not filename:
            return
        ok, wps, takeoff, landing, alt, msg = import_plan_file(filename)
        if ok:
            self._save_state_to_undo()
            self.waypoints = wps
            self.takeoff_point = takeoff
            self.landing_point = landing
            self.default_alt = alt
            self.sync_state = 'UNSAVED'
            self._sync_all()
            QMessageBox.information(self, "Plan Imported", msg)
        else:
            QMessageBox.warning(self, "Import Failed", msg)

    def upload_to_vehicle(self):
        if not self.vehicle:
            QMessageBox.warning(self, "No Vehicle", "Connect to a vehicle before uploading missions.")
            return

        if not self.waypoints and not self.takeoff_point and not self.landing_point:
            QMessageBox.warning(self, "Empty Plan", "Add waypoints or takeoff before uploading.")
            return

        self.sync_state = 'UPLOADING'
        self._update_ui_state()

        import threading
        v = self.vehicle
        wps = copy.deepcopy(self.waypoints)
        takeoff = copy.deepcopy(self.takeoff_point)
        landing = copy.deepcopy(self.landing_point)
        target_alt = self.default_alt

        def _upload_worker():
            ok, msg = upload_mission(v, wps, takeoff, landing, target_alt=target_alt, verify_after_upload=True)
            self.mission_uploaded.emit(ok, msg)

        threading.Thread(target=_upload_worker, daemon=True).start()

    def download_from_vehicle(self):
        if not self.vehicle:
            QMessageBox.warning(self, "No Vehicle", "Connect to a vehicle before downloading missions.")
            return

        import threading
        v = self.vehicle

        def _download_worker():
            ok, items, msg = download_mission(v)
            if ok:
                new_wps = []
                new_to = None
                new_land = None
                for it in items:
                    cmd = it.get('command')
                    coord = [it['lat'], it['lon'], it['alt']]
                    if cmd == 22 and new_to is None and not new_wps: # TAKEOFF
                        new_to = coord
                    elif cmd == 21: # LAND
                        new_land = coord
                    elif cmd in (16, 22): # WAYPOINT
                        new_wps.append(coord)

                self.waypoints = new_wps
                self.takeoff_point = new_to
                self.landing_point = new_land
                self.sync_state = 'VERIFIED'
                self.verified_vehicle_items = len(items)
                self._sync_all()
                self.mission_uploaded.emit(True, f"Downloaded and verified {len(items)} items from vehicle")
            else:
                self.mission_uploaded.emit(False, msg)

        threading.Thread(target=_download_worker, daemon=True).start()

    def on_upload_completed(self, ok: bool, msg: str):
        if ok:
            total = len(self.waypoints) + (1 if self.takeoff_point else 0) + (1 if self.landing_point else 0)
            self.sync_state = 'VERIFIED'
            self.verified_vehicle_items = total
        else:
            self.sync_state = 'MISMATCH'
        self._update_ui_state()
