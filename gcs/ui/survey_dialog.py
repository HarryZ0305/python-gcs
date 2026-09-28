import math
from typing import List, Tuple
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QSpinBox, QDoubleSpinBox, QFrame
)
from PyQt6.QtCore import Qt

THEME = {
    'bg': '#f5f7fa',
    'panel_bg': '#ffffff',
    'panel_border': '#cbd5e1',
    'primary': '#0b57d0',
    'success': '#0f9d58',
    'muted': '#5f6368',
    'dark_text': '#0f172a',
}

class SurveyGridDialog(QDialog):
    """
    Generates serpentine lawnmower survey flight trajectories.
    Fixes:
    1. Propagates configured altitude to caller and to all generated waypoints.
    2. Avoids duplicate takeoff/landing waypoints generated from the first/last grid points.
    """
    def __init__(self, center_lat: float, center_lon: float, default_alt: float = 15.0, parent=None):
        super().__init__(parent)
        self.center_lat = center_lat if (center_lat != 0.0 or center_lon != 0.0) else 32.7157
        self.center_lon = center_lon if (center_lat != 0.0 or center_lon != 0.0) else -117.1611
        self.generated_waypoints: List[List[float]] = []
        self.selected_alt: float = default_alt

        self.setWindowTitle("Aerial Survey Grid Generator")
        self.setFixedSize(400, 380)
        self.setStyleSheet(f"background-color: {THEME['bg']}; font-family: Google Sans Code;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel("SURVEY GRID GENERATOR")
        title.setStyleSheet(f"color: {THEME['primary']}; font-size: 13px; font-weight: bold;")
        layout.addWidget(title)

        sub = QLabel("Auto-generates lawnmower survey flight lines for mapping:")
        sub.setStyleSheet(f"color: {THEME['muted']}; font-size: 11px;")
        layout.addWidget(sub)

        form_frame = QFrame()
        form_frame.setStyleSheet(f"background: {THEME['panel_bg']}; border: 1px solid {THEME['panel_border']}; border-radius: 8px;")
        fl = QGridLayout(form_frame)
        fl.setContentsMargins(12, 12, 12, 12)
        fl.setSpacing(8)

        lbl_style = f"color: {THEME['dark_text']}; font-size: 11px; font-weight: bold;"

        l0 = QLabel("Width (m):")
        l0.setStyleSheet(lbl_style)
        fl.addWidget(l0, 0, 0)
        self.width_spin = QSpinBox()
        self.width_spin.setRange(20, 1000)
        self.width_spin.setValue(80)
        fl.addWidget(self.width_spin, 0, 1)

        l1 = QLabel("Height (m):")
        l1.setStyleSheet(lbl_style)
        fl.addWidget(l1, 1, 0)
        self.height_spin = QSpinBox()
        self.height_spin.setRange(20, 1000)
        self.height_spin.setValue(80)
        fl.addWidget(self.height_spin, 1, 1)

        l2 = QLabel("Lane Spacing (m):")
        l2.setStyleSheet(lbl_style)
        fl.addWidget(l2, 2, 0)
        self.spacing_spin = QSpinBox()
        self.spacing_spin.setRange(5, 200)
        self.spacing_spin.setValue(20)
        fl.addWidget(self.spacing_spin, 2, 1)

        l3 = QLabel("Altitude (m):")
        l3.setStyleSheet(lbl_style)
        fl.addWidget(l3, 3, 0)
        self.alt_spin = QDoubleSpinBox()
        self.alt_spin.setRange(2.0, 150.0)
        self.alt_spin.setValue(default_alt)
        self.alt_spin.setSuffix(" m")
        fl.addWidget(self.alt_spin, 3, 1)

        layout.addWidget(form_frame)

        self.stats_lbl = QLabel("Estimated: 0 waypoints")
        self.stats_lbl.setStyleSheet(f"color: {THEME['muted']}; font-size: 11px;")
        layout.addWidget(self.stats_lbl)

        # Wire spin changes to update estimate
        self.width_spin.valueChanged.connect(self._update_estimate)
        self.height_spin.valueChanged.connect(self._update_estimate)
        self.spacing_spin.valueChanged.connect(self._update_estimate)
        self._update_estimate()

        btn_box = QHBoxLayout()
        cancel_btn = QPushButton("CANCEL")
        cancel_btn.setFixedHeight(34)
        cancel_btn.setStyleSheet(f"background: {THEME['panel_bg']}; color: {THEME['muted']}; border: 1px solid {THEME['panel_border']}; border-radius: 4px; font-weight: bold; font-family: Google Sans Code;")
        cancel_btn.clicked.connect(self.reject)

        gen_btn = QPushButton("GENERATE GRID")
        gen_btn.setFixedHeight(34)
        gen_btn.setStyleSheet(f"background: {THEME['success']}; color: #ffffff; border: none; border-radius: 4px; font-weight: bold; font-family: Google Sans Code;")
        gen_btn.clicked.connect(self.generate_grid)

        btn_box.addWidget(cancel_btn)
        btn_box.addWidget(gen_btn)
        layout.addLayout(btn_box)

    def _update_estimate(self):
        height = self.height_spin.value()
        spacing = self.spacing_spin.value()
        num_lanes = max(2, int(height / spacing) + 1)
        wps_count = num_lanes * 2
        width = self.width_spin.value()
        approx_dist = (num_lanes * width) + ((num_lanes - 1) * spacing)
        self.stats_lbl.setText(f"Estimated: {wps_count} waypoints (~{approx_dist} m total track)")

    def generate_grid(self):
        width = self.width_spin.value()
        height = self.height_spin.value()
        spacing = self.spacing_spin.value()
        self.selected_alt = self.alt_spin.value()

        m_per_deg_lat = 111320.0
        m_per_deg_lon = 111320.0 * math.cos(math.radians(self.center_lat))

        num_lanes = max(2, int(height / spacing) + 1)
        lane_step_y = height / (num_lanes - 1)

        half_w = width / 2.0
        half_h = height / 2.0

        wps = []
        for i in range(num_lanes):
            y_offset = -half_h + i * lane_step_y
            lat_i = self.center_lat + (y_offset / m_per_deg_lat)

            if i % 2 == 0:
                lon_start = self.center_lon - (half_w / m_per_deg_lon)
                lon_end = self.center_lon + (half_w / m_per_deg_lon)
            else:
                lon_start = self.center_lon + (half_w / m_per_deg_lon)
                lon_end = self.center_lon - (half_w / m_per_deg_lon)

            # Each survey waypoint has [lat, lon, alt]
            wps.append([lat_i, lon_start, self.selected_alt])
            wps.append([lat_i, lon_end, self.selected_alt])

        self.generated_waypoints = wps
        self.accept()
