"""
PythonGCS Picture-in-Picture (PiP) Workspace
Enables dominant Map workspace with floating Video window, or dominant Video
with floating Map, with instantaneous one-click swap and minimize/restore controls.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QFrame, QStackedWidget
)
from PyQt6.QtCore import Qt, QRect, QPoint, QSize, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from gcs.ui.theme import get_theme, FONT_FAMILY_PRIMARY


class PipOverlayFrame(QFrame):
    """Floating Picture-in-Picture window container with title bar and swap controls."""
    swap_requested = pyqtSignal()
    toggle_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("PipFloatingFrame")
        self.is_minimized = False
        self.default_size = QSize(320, 210)
        self.minimized_size = QSize(160, 32)
        
        t = get_theme()
        self.setStyleSheet(f"""
            #PipFloatingFrame {{
                background-color: {t['surface']};
                border: 2px solid {t['primary']};
                border-radius: 8px;
            }}
        """)

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(4, 4, 4, 4)
        self.layout.setSpacing(2)

        # Header bar
        self.header = QFrame()
        self.header.setFixedHeight(26)
        h_layout = QHBoxLayout(self.header)
        h_layout.setContentsMargins(6, 0, 4, 0)
        h_layout.setSpacing(4)

        self.title_label = QLabel("PIP FEED")
        self.title_label.setStyleSheet(f"color: {t['primary']}; font-family: {FONT_FAMILY_PRIMARY}; font-size: 10px; font-weight: bold; border: none;")
        h_layout.addWidget(self.title_label)
        h_layout.addStretch(1)

        # Swap button
        self.swap_btn = QPushButton("SWAP")
        self.swap_btn.setFixedHeight(20)
        self.swap_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {t['primary']}; color: #ffffff;
                border: none; border-radius: 3px; font-size: 9px; font-weight: bold;
                padding: 1px 6px;
            }}
            QPushButton:hover {{ background-color: {t['primary_hover']}; }}
        """)
        self.swap_btn.clicked.connect(self.swap_requested.emit)
        h_layout.addWidget(self.swap_btn)

        # Minimize button
        self.min_btn = QPushButton("—")
        self.min_btn.setFixedSize(20, 20)
        self.min_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {t['surface_elevated']}; color: {t['text_muted']};
                border: 1px solid {t['border']}; border-radius: 3px; font-size: 9px; font-weight: bold;
            }}
            QPushButton:hover {{ color: {t['text']}; }}
        """)
        self.min_btn.clicked.connect(self._toggle_minimize)
        h_layout.addWidget(self.min_btn)

        self.layout.addWidget(self.header)

        # Inner content container
        self.content_container = QWidget()
        self.content_layout = QVBoxLayout(self.content_container)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.layout.addWidget(self.content_container, stretch=1)

    def set_content_widget(self, widget: QWidget, title: str):
        # Clear existing
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        
        self.title_label.setText(title.upper())
        self.content_layout.addWidget(widget)

    def _toggle_minimize(self):
        self.is_minimized = not self.is_minimized
        if self.is_minimized:
            self.content_container.hide()
            self.min_btn.setText("+")
            self.resize(self.minimized_size)
        else:
            self.content_container.show()
            self.min_btn.setText("—")
            self.resize(self.default_size)
        self.toggle_requested.emit()

    def mouseDoubleClickEvent(self, event):
        self.swap_requested.emit()
        event.accept()


class PipWorkspace(QWidget):
    """
    Main workspace container managing Map and Video views with Picture-in-Picture layout.
    """
    def __init__(self, map_widget: QWidget, video_widget: QWidget, parent=None):
        super().__init__(parent)
        self.map_widget = map_widget
        self.video_widget = video_widget
        self.is_map_dominant = True

        # Dominant view fills the entire workspace
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        self.dominant_container = QWidget(self)
        self.dominant_layout = QVBoxLayout(self.dominant_container)
        self.dominant_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.addWidget(self.dominant_container)

        # Floating PiP overlay
        self.pip_frame = PipOverlayFrame(self)
        self.pip_frame.resize(self.pip_frame.default_size)
        self.pip_frame.swap_requested.connect(self.swap_views)
        self.pip_frame.toggle_requested.connect(self._reposition_pip)

        # Initial assignment: Map Dominant, Video PiP
        self._apply_layout()

    def _apply_layout(self):
        # Detach both views before assigning either to its new container.
        # Otherwise clearing the old PiP can detach the newly dominant widget.
        for layout in (self.dominant_layout, self.pip_frame.content_layout):
            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().setParent(None)
        # Clear dominant layout
        while self.dominant_layout.count():
            item = self.dominant_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

        if self.is_map_dominant:
            self.dominant_layout.addWidget(self.map_widget)
            self.pip_frame.set_content_widget(self.video_widget, "VIDEO HUD")
        else:
            self.dominant_layout.addWidget(self.video_widget)
            self.pip_frame.set_content_widget(self.map_widget, "TACTICAL MAP")

        self.pip_frame.raise_()
        self.map_widget.show()
        self.video_widget.show()
        self._reposition_pip()

    def swap_views(self):
        self.is_map_dominant = not self.is_map_dominant
        self._apply_layout()

    def _reposition_pip(self):
        margin = 16
        fw = self.pip_frame.width()
        fh = self.pip_frame.height()
        # Position in bottom-right corner of workspace
        x = max(10, self.width() - fw - margin)
        y = max(10, self.height() - fh - margin)
        self.pip_frame.move(x, y)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reposition_pip()
