import sys
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QGridLayout, QLabel, QFrame
)
from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QFont
from telemetry import telemetry_data # imports the shared dict so GUI can read latest values


class TelemetryCard(QFrame): # reusable widget for each data field, takes a title and displays a live updating value
    def __init__(self, title):
        super().__init__()
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet("background-color: #1e2d3d; border-radius: 8px; padding: 8px;")

        layout = QGridLayout(self)

        self.title_label = QLabel(title)
        self.title_label.setStyleSheet("color: #7a9cc4; font-size: 11px;")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.value_label = QLabel("---")        
        self.value_label.setFont(QFont("Courier New", 22, QFont.Weight.Bold))
        self.value_label.setStyleSheet("color: #00e5ff;")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(self.title_label, 0, 0)
        layout.addWidget(self.value_label, 1, 0)

    def update_value(self, text, color="#00e5ff"):
        """updates the displayed value and optionally changes color e.g. red for low battery"""
        self.value_label.setText(text)
        self.value_label.setStyleSheet(f"color: {color};")


class GCSWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Python GCS — Live Telemetry")
        self.setStyleSheet("background-color: #0d1b2a;")
        self.resize(700, 300)

        central = QWidget()
        self.setCentralWidget(central)
        grid = QGridLayout(central)
        grid.setSpacing(12)
        grid.setContentsMargins(16, 16, 16, 16)

        self.cards = { # one card per telemetry field 
            'alt':         TelemetryCard("ALTITUDE (m)"),
            'groundspeed': TelemetryCard("SPEED (m/s)"),
            'battery':     TelemetryCard("BATTERY (%)"),
            'satellites':  TelemetryCard("SATELLITES"),
            'throttle':    TelemetryCard("THROTTLE (%)"),
            'armed':       TelemetryCard("ARMED"),
        }

        positions = [ # position each card in the grid layout by row and column
            ('alt', 0, 0), ('groundspeed', 0, 1), ('battery', 0, 2),
            ('satellites', 1, 0), ('throttle', 1, 1), ('armed', 1, 2),
        ]
        for key, row, col in positions:
            grid.addWidget(self.cards[key], row, col)

        self.timer = QTimer()
        self.timer.timeout.connect(self.refresh) # calls refresh every 500ms on the main thread
        self.timer.start(500)

    def refresh(self):
        d = telemetry_data

        self.cards['alt'].update_value(f"{d['alt']:.1f}")
        self.cards['groundspeed'].update_value(f"{d['groundspeed']:.1f}")
        self.cards['battery'].update_value(
            str(d['battery']),
            color="#ff4444" if d['battery'] < 20 else "#00e5ff" # turns red when battery under 20%
        )
        self.cards['satellites'].update_value(str(d['satellites']))
        self.cards['throttle'].update_value(str(d['throttle']))
        self.cards['armed'].update_value(
            "ARMED" if d['armed'] else "DISARMED",
            color="#ff4444" if d['armed'] else "#44ff88" # red when armed, green when disarmed
        )

def launch_gui():
    app = QApplication(sys.argv)
    window = GCSWindow()
    window.show()
    app.exec_() 