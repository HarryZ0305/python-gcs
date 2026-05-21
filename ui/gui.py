import sys
import threading
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QGridLayout, QLabel, QFrame, QMessageBox,
    QPushButton, QComboBox, QSpinBox, QHBoxLayout
)

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QFont
from telemetry import telemetry_data # imports the shared dict so GUI can read latest values
from commands import arm, disarm, set_mode, takeoff


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
    def __init__(self, vehicle):
        super().__init__()
        self.vehicle = vehicle

        self.setWindowTitle("Python GCS — Live Telemetry")
        self.setStyleSheet("background-color: #0d1b2a;")
        self.resize(700, 420)

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

        positions = [ # position each card in the grid layout
            ('alt', 0, 0), ('groundspeed', 0, 1), ('battery', 0, 2),
            ('satellites', 1, 0), ('throttle', 1, 1), ('armed', 1, 2),
        ]
        for key, row, col in positions:
            grid.addWidget(self.cards[key], row, col)

        # Command panel
        cmd_panel = QFrame()
        cmd_panel.setStyleSheet("background-color: #1e2d3d; border-radius: 8px; padding: 4px;")
        cmd_layout = QHBoxLayout(cmd_panel)
        cmd_layout.setSpacing(10)

        # Arm / Disarm button
        self.arm_btn = QPushButton("ARM")
        self.arm_btn.setFixedHeight(48)
        self.arm_btn.setFont(QFont("Courier New", 12, QFont.Weight.Bold))
        self.arm_btn.setStyleSheet(self._btn_style("#44ff88", "#0d1b2a"))
        self.arm_btn.clicked.connect(self.on_arm_disarm)

        # Mode selector
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(['GUIDED', 'LOITER', 'RTL', 'LAND', 'STABILIZE'])
        self.mode_combo.setFixedHeight(36)
        self.mode_combo.setStyleSheet("""
            QComboBox {
                background-color: #0d1b2a; color: #00e5ff;
                border: 1px solid #2a4a6a; border-radius: 4px;
                padding: 4px 8px; font-family: Courier New; font-size: 12px;
            }
            QComboBox QAbstractItemView {
                background-color: #0d1b2a; color: #00e5ff;
                selection-background-color: #2a4a6a;
            }
        """)

        self.mode_btn = QPushButton("SET MODE")
        self.mode_btn.setFixedHeight(48)
        self.mode_btn.setFont(QFont("Courier New", 12, QFont.Weight.Bold))
        self.mode_btn.setStyleSheet(self._btn_style("#00e5ff", "#0d1b2a"))
        self.mode_btn.clicked.connect(self.on_set_mode)

        # Takeoff — altitude spinbox + button
        self.alt_spin = QSpinBox()
        self.alt_spin.setRange(1, 100)
        self.alt_spin.setValue(10)  # default takeoff altitude
        self.alt_spin.setFixedHeight(36)
        self.alt_spin.setStyleSheet("""
            QSpinBox {
                background-color: #0d1b2a; color: #00e5ff;
                border: 1px solid #2a4a6a; border-radius: 4px;
                padding: 4px 8px; font-family: Courier New; font-size: 12px;
            }
            QSpinBox::up-button, QSpinBox::down-button { width: 20px; }
        """)

        self.takeoff_btn = QPushButton("TAKEOFF")
        self.takeoff_btn.setFixedHeight(48)
        self.takeoff_btn.setFont(QFont("Courier New", 12, QFont.Weight.Bold))
        self.takeoff_btn.setStyleSheet(self._btn_style("#ffaa00", "#0d1b2a"))
        self.takeoff_btn.clicked.connect(self.on_takeoff)

        # command panel
        cmd_layout.addWidget(self.arm_btn, stretch=2)
        cmd_layout.addSpacing(10)
        cmd_layout.addWidget(self.mode_combo, stretch=2)
        cmd_layout.addWidget(self.mode_btn, stretch=2)
        cmd_layout.addSpacing(10)
        cmd_layout.addWidget(self.alt_spin, stretch=1)
        cmd_layout.addWidget(self.takeoff_btn, stretch=2)

        grid.addWidget(cmd_panel, 2, 0, 1, 3)  # row 2, spans all 3 columns

        # Status bar 
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: #7a9cc4; font-size: 11px; padding: 2px 4px;")
        grid.addWidget(self.status_label, 3, 0, 1, 3)

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

        # Arm button label and color flips
        if d['armed']:
            self.arm_btn.setText("DISARM")
            self.arm_btn.setStyleSheet(self._btn_style("#ff4444", "#0d1b2a"))
        else:
            self.arm_btn.setText("ARM")
            self.arm_btn.setStyleSheet(self._btn_style("#44ff88", "#0d1b2a"))

    def _btn_style(self, color, bg):
        return f"""
            QPushButton {{
                background-color: {bg}; color: {color};
                border: 2px solid {color}; border-radius: 6px;
            }}
            QPushButton:hover {{ background-color: {color}; color: {bg}; }}
            QPushButton:disabled {{ border-color: #2a4a6a; color: #2a4a6a; }}
        """

    def on_arm_disarm(self):
        if telemetry_data['armed']:
            threading.Thread(target = disarm, args = (self.vehicle,), daemon = True).start()
            self.set_status("Disarm command sent...")
        else:
            threading.Thread(target = arm, args = (self.vehicle,), daemon = True).start()
            self.set_status("Arm command sent...")

    def on_set_mode(self):
        mode = self.mode_combo.currentText()
        threading.Thread(target = set_mode, args = (self.vehicle, mode), daemon = True).start()
        self.set_status(f"Setting mode to {mode}...")

    def on_takeoff(self):
        if not telemetry_data['armed']:
            QMessageBox.warning(self, "Not Armed", "Arm the drone before takeoff.")
            return
        alt = self.alt_spin.value()
        threading.Thread(target = takeoff, args = (self.vehicle, alt), daemon = True).start()
        self.set_status(f"Takeoff command sent — target {alt}m")

    def set_status(self, msg):
        self.status_label.setText(msg)

    def closeEvent(self, event): # Prevent accidental closure while the drone is active # type: ignore
        if telemetry_data['armed']:
            reply = QMessageBox.question(
                self, 'Warning', 
                "Drone is still ARMED! Are you sure you want to exit the GCS?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, 
                QMessageBox.StandardButton.No
            )

            if reply == QMessageBox.StandardButton.Yes:
                print("Closing GCS...")
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()

def launch_gui(vehicle):
    app = QApplication(sys.argv)
    window = GCSWindow(vehicle)
    window.show()
    app.exec()