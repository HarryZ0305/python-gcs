from PyQt6.QtWidgets import QLabel
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

class CameraView(QLabel):
    def __init__(self, title="CAMERA"):
        super().__init__()
        self.title = title
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setText(f"{title}\n\n\u25cb  NO SIGNAL")
        self.setFont(QFont("Courier New", 11))
        self.setStyleSheet("""
            background-color: #060d15; color: #3a5a7a;
            border: 1px solid #2a4a6a; border-radius: 6px;
        """)
        self.setMinimumSize(200, 150)

    def update_frame(self, pixmap):
        # later, when you have a camera: feed live video frames here
        self.setPixmap(pixmap)