"""
PythonGCS Settings & Preferences Workspace (SettingsView)
Provides theme selection (Light/Dark), video stream configuration,
units configuration, battery thresholds, tile server & offline map source management.
"""

from typing import Optional
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QLineEdit, QCheckBox,
    QSpinBox, QDoubleSpinBox, QFrame, QFileDialog,
    QMessageBox, QScrollArea
)
from PyQt6.QtCore import Qt, pyqtSignal
from gcs.ui.theme import get_theme, set_active_theme, FONT_FAMILY_PRIMARY, FONT_FAMILY_MONO, get_button_style
from gcs.telemetry import battery_config
from gcs.ui.tile_server import set_mbtiles_file


class SettingsView(QWidget):
    """
    Application settings and vehicle configuration manager.
    """
    theme_changed = pyqtSignal(bool) # is_dark
    video_source_changed = pyqtSignal(str) # new url

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        t = get_theme()
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(14)

        # 1. Appearance & Theme Card
        app_card, ac_layout = self._create_card("APPEARANCE & THEME")

        theme_row = QHBoxLayout()
        theme_lbl = QLabel("Color Theme:")
        theme_lbl.setStyleSheet(f"color: {t['text']}; font-weight: bold;")
        theme_row.addWidget(theme_lbl)

        self.theme_combo = QComboBox()
        self.theme_combo.addItem("Cockpit Dark Mode (Field Optimized)", True)
        self.theme_combo.addItem("Aviation Light Mode (Direct Sunlight)", False)
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        theme_row.addWidget(self.theme_combo)
        theme_row.addStretch(1)
        ac_layout.addLayout(theme_row)
        layout.addWidget(app_card)

        # 2. Video Streaming & Camera Card
        cam_card, cc_layout = self._create_card("VIDEO STREAM & PAYLOAD CAMERA")

        src_row = QHBoxLayout()
        src_lbl = QLabel("Video Stream Source:")
        src_lbl.setStyleSheet(f"color: {t['text']}; font-weight: bold;")
        src_row.addWidget(src_lbl)

        self.video_src_input = QLineEdit()
        self.video_src_input.setPlaceholderText("rtsp://192.168.1.100:8554/live, udp://0.0.0.0:5600, or 'test'")
        self.video_src_input.setText("test")
        src_row.addWidget(self.video_src_input, stretch=1)

        self.btn_apply_video = QPushButton("APPLY STREAM")
        self.btn_apply_video.setStyleSheet(get_button_style('primary', 'sm'))
        self.btn_apply_video.clicked.connect(self._on_apply_video)
        src_row.addWidget(self.btn_apply_video)
        cc_layout.addLayout(src_row)

        desc = QLabel("Supports RTSP, UDP, HTTP, USB camera index (e.g. '0'), or 'test' for simulated test pattern.")
        desc.setStyleSheet(f"color: {t['text_muted']}; font-size: 11px;")
        cc_layout.addWidget(desc)
        layout.addWidget(cam_card)

        # 3. Battery Safety Thresholds Card
        batt_card, bc_layout = self._create_card("BATTERY SAFETY & POWER MANAGEMENT")

        cell_row = QHBoxLayout()
        cell_lbl = QLabel("Battery Chemistry & Cells:")
        cell_lbl.setStyleSheet(f"color: {t['text']}; font-weight: bold;")
        cell_row.addWidget(cell_lbl)

        self.cell_combo = QComboBox()
        for s in [1, 2, 3, 4, 5, 6, 8, 12]:
            self.cell_combo.addItem(f"{s}S LiPo ({s * 3.7:.1f}V nom, {s * 4.2:.1f}V full)", s)
        self.cell_combo.setCurrentIndex(3) # 4S default
        self.cell_combo.currentIndexChanged.connect(self._on_cells_changed)
        cell_row.addWidget(self.cell_combo)
        cell_row.addStretch(1)
        bc_layout.addLayout(cell_row)

        thresh_row = QHBoxLayout()
        w_lbl = QLabel("Warning Voltage/Cell:")
        thresh_row.addWidget(w_lbl)
        self.warn_spin = QDoubleSpinBox()
        self.warn_spin.setRange(3.0, 3.8)
        self.warn_spin.setValue(battery_config.get('warn_volt_per_cell', 3.5))
        self.warn_spin.setSingleStep(0.05)
        thresh_row.addWidget(self.warn_spin)

        c_lbl = QLabel("Critical Voltage/Cell:")
        thresh_row.addWidget(c_lbl)
        self.crit_spin = QDoubleSpinBox()
        self.crit_spin.setRange(2.8, 3.5)
        self.crit_spin.setValue(battery_config.get('crit_volt_per_cell', 3.3))
        self.crit_spin.setSingleStep(0.05)
        thresh_row.addWidget(self.crit_spin)
        thresh_row.addStretch(1)
        bc_layout.addLayout(thresh_row)
        layout.addWidget(batt_card)

        # 4. Offline Maps & MBTiles Card
        map_card, mc_layout = self._create_card("OFFLINE MAPS & TILE SOURCES")

        tile_row = QHBoxLayout()
        tile_lbl = QLabel("MBTiles Offline Archive:")
        tile_lbl.setStyleSheet(f"color: {t['text']}; font-weight: bold;")
        tile_row.addWidget(tile_lbl)

        self.mbtiles_path_input = QLineEdit()
        self.mbtiles_path_input.setPlaceholderText("Select offline .mbtiles package...")
        self.mbtiles_path_input.setReadOnly(True)
        tile_row.addWidget(self.mbtiles_path_input, stretch=1)

        btn_browse_mbtiles = QPushButton("BROWSE...")
        btn_browse_mbtiles.setStyleSheet(get_button_style('secondary', 'sm'))
        btn_browse_mbtiles.clicked.connect(self._on_browse_mbtiles)
        tile_row.addWidget(btn_browse_mbtiles)

        btn_clear_mbtiles = QPushButton("RESET TO OSM")
        btn_clear_mbtiles.setStyleSheet(get_button_style('secondary', 'sm'))
        btn_clear_mbtiles.clicked.connect(self._on_clear_mbtiles)
        tile_row.addWidget(btn_clear_mbtiles)
        mc_layout.addLayout(tile_row)
        layout.addWidget(map_card)

        layout.addStretch(1)
        scroll.setWidget(content)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

    def _create_card(self, title: str):
        t = get_theme()
        card = QFrame()
        card.setObjectName("SettingsCard")
        card.setStyleSheet(f"""
            #SettingsCard {{
                background-color: {t['surface']};
                border: 1px solid {t['border']};
                border-radius: 8px;
            }}
        """)
        c_layout = QVBoxLayout(card)
        c_layout.setContentsMargins(14, 12, 14, 12)
        c_layout.setSpacing(10)

        t_lbl = QLabel(title)
        t_lbl.setStyleSheet(f"color: {t['primary']}; font-family: {FONT_FAMILY_PRIMARY}; font-size: 11px; font-weight: bold;")
        c_layout.addWidget(t_lbl)
        return card, c_layout

    def _on_theme_changed(self):
        is_dark = self.theme_combo.currentData()
        set_active_theme(is_dark)
        self.theme_changed.emit(is_dark)

    def _on_apply_video(self):
        url = self.video_src_input.text().strip()
        self.video_source_changed.emit(url)
        QMessageBox.information(self, "Video Source Updated", f"Applied stream source: {url}")

    def _on_cells_changed(self):
        cells = self.cell_combo.currentData()
        if cells:
            battery_config['cells'] = int(cells)

    def _on_browse_mbtiles(self):
        fname, _ = QFileDialog.getOpenFileName(self, "Select MBTiles Offline Package", "", "MBTiles Files (*.mbtiles *.db)")
        if fname:
            self.mbtiles_path_input.setText(fname)
            set_mbtiles_file(fname)
            QMessageBox.information(self, "Offline Map Loaded", f"Loaded offline MBTiles package:\n{fname}")

    def _on_clear_mbtiles(self):
        self.mbtiles_path_input.clear()
        set_mbtiles_file(None)
        QMessageBox.information(self, "Reset Map Source", "Reverted tile server to OpenStreetMap online cache.")
