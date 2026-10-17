"""
PythonGCS Primary Flight Display (PFD) and Cockpit Instruments.
Provides high-performance, aviation-grade 2D Primary Flight Display (Artificial Horizon,
Airspeed Tape, Altitude Tape, Heading Ribbon, Climb Rate Indicator) and view toggle to 3D CAD.
"""

import math
import time
from typing import Optional, Dict, Any
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QStackedWidget, QFrame
)
from PyQt6.QtCore import Qt, QTimer, QRectF, QPointF
from PyQt6.QtGui import (
    QPainter, QColor, QFont, QPen, QBrush,
    QLinearGradient, QPainterPath, QPolygonF
)
from gcs.ui.theme import get_theme, FONT_FAMILY_PRIMARY, FONT_FAMILY_MONO
from gcs.ui.attitude_view import AttitudeView
from gcs.telemetry import telemetry_data, get_stream_freshness


class PrimaryFlightDisplay(QWidget):
    """
    Aviation-standard Primary Flight Display (PFD) rendered natively via QPainter.
    Features:
    - Artificial horizon with pitch ladder and roll bank indicator
    - Airspeed tape (left) with rolling readout
    - Altitude tape (right) with altitude reference label and digital box
    - Heading compass ribbon (bottom)
    - Vertical Speed Indicator / Climb Rate (VSI, far right)
    - Data validity and STALE warnings
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(280, 240)
        
        # Flight variables
        self.roll = 0.0          # Radians
        self.pitch = 0.0         # Radians
        self.yaw = 0.0           # Radians
        self.altitude = 0.0      # Meters (relative to launch)
        self.altitude_amsl = 0.0 # Meters AMSL
        self.groundspeed = 0.0   # m/s
        self.climb_rate = 0.0    # m/s
        self.mode = "DISCONNECTED"
        self.armed = False
        self.is_stale = True
        self.position_valid = False
        self.speed_valid = False

        # High-rate render timer (30 Hz for fluid cockpit instruments)
        self._render_timer = QTimer(self)
        self._render_timer.timeout.connect(self.update)
        self._render_timer.start(33)

    def set_telemetry(
        self,
        roll: float,
        pitch: float,
        yaw: float,
        alt: float,
        groundspeed: float,
        climb_rate: float = 0.0,
        mode: str = "UNKNOWN",
        armed: bool = False,
        is_stale: bool = False,
        alt_amsl: float = 0.0,
        position_valid: bool = True,
        speed_valid: bool = True
    ):
        self.roll = float(roll)
        self.pitch = float(pitch)
        self.yaw = float(yaw)
        self.altitude = float(alt)
        self.altitude_amsl = float(alt_amsl)
        self.groundspeed = float(groundspeed)
        self.climb_rate = float(climb_rate)
        self.mode = str(mode)
        self.armed = bool(armed)
        self.is_stale = bool(is_stale)
        self.position_valid = position_valid
        self.speed_valid = speed_valid

    def paintEvent(self, event):
        t = get_theme()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        w = self.width()
        h = self.height()
        cx = w / 2.0
        cy = h / 2.0

        # Pitch and Roll in degrees
        pitch_deg = math.degrees(self.pitch)
        roll_deg = math.degrees(self.roll)
        yaw_deg = math.degrees(self.yaw) % 360.0

        # Clamp pitch for display
        pitch_deg = max(-45.0, min(45.0, pitch_deg))

        # 1. Background Sky and Ground (clipped to central horizon ball)
        horizon_w = w - 80.0
        horizon_h = h - 35.0
        horizon_rect = QRectF(40.0, 5.0, horizon_w, horizon_h)

        p.save()
        p.setClipRect(horizon_rect)

        # Rotate around horizon center for Roll
        p.translate(cx, cy)
        p.rotate(-roll_deg)

        # Pixels per pitch degree
        px_per_deg = horizon_h / 40.0
        pitch_offset = pitch_deg * px_per_deg

        # Draw Sky
        sky_color = QColor(t.get('pfd_sky', '#0c4a6e'))
        p.fillRect(QRectF(-w * 2, -h * 4 + pitch_offset, w * 4, h * 4), sky_color)

        # Draw Ground
        ground_color = QColor(t.get('pfd_ground', '#3b1d11'))
        p.fillRect(QRectF(-w * 2, pitch_offset, w * 4, h * 4), ground_color)

        # Draw White Horizon Line
        p.setPen(QPen(QColor('#ffffff'), 2.0))
        p.drawLine(QPointF(-w * 2, pitch_offset), QPointF(w * 2, pitch_offset))

        # Draw Pitch Ladder Lines (+/- 30 degrees in 5-degree steps)
        ladder_pen = QPen(QColor('#ffffff'), 1.5)
        p.setPen(ladder_pen)
        p.setFont(QFont(FONT_FAMILY_MONO, 8, QFont.Weight.Bold))

        for deg in range(-30, 35, 5):
            if deg == 0:
                continue
            line_y = pitch_offset - (deg * px_per_deg)
            line_w = 40.0 if deg % 10 == 0 else 24.0

            if deg > 0:
                # Sky pitch line (solid)
                p.drawLine(QPointF(-line_w, line_y), QPointF(line_w, line_y))
            else:
                # Ground pitch line (dashed)
                p.drawLine(QPointF(-line_w, line_y), QPointF(-line_w * 0.4, line_y))
                p.drawLine(QPointF(line_w * 0.4, line_y), QPointF(line_w, line_y))

            if deg % 10 == 0:
                p.drawText(QRectF(line_w + 4, line_y - 6, 24, 12), Qt.AlignmentFlag.AlignLeft, f"{abs(deg)}")
                p.drawText(QRectF(-line_w - 28, line_y - 6, 24, 12), Qt.AlignmentFlag.AlignRight, f"{abs(deg)}")

        p.restore()

        # 2. Roll Bank Arc and Pointer (top of horizon)
        p.save()
        p.setPen(QPen(QColor(t['border_strong']), 1.5))
        arc_r = min(horizon_w, horizon_h) * 0.42
        arc_rect = QRectF(cx - arc_r, cy - arc_r, arc_r * 2, arc_r * 2)

        # Roll ticks at -45, -30, -20, -10, 0, 10, 20, 30, 45
        for ang in [-45, -30, -20, -10, 0, 10, 20, 30, 45]:
            rad = math.radians(ang - 90)
            inner_r = arc_r - (8 if ang % 30 == 0 else 4)
            p.drawLine(
                QPointF(cx + arc_r * math.cos(rad), cy + arc_r * math.sin(rad)),
                QPointF(cx + inner_r * math.cos(rad), cy + inner_r * math.sin(rad))
            )

        # Fixed top zero pointer (yellow inverted triangle)
        p.setBrush(QBrush(QColor(t.get('pfd_crosshair', '#facc15'))))
        p.setPen(Qt.PenStyle.NoPen)
        top_tri = QPolygonF([
            QPointF(cx, cy - arc_r),
            QPointF(cx - 5, cy - arc_r - 8),
            QPointF(cx + 5, cy - arc_r - 8)
        ])
        p.drawPolygon(top_tri)

        # Rotating roll pointer
        p.translate(cx, cy)
        p.rotate(-roll_deg)
        roll_tri = QPolygonF([
            QPointF(0, -arc_r + 2),
            QPointF(-5, -arc_r + 10),
            QPointF(5, -arc_r + 10)
        ])
        p.drawPolygon(roll_tri)
        p.restore()

        # 3. Fixed Aircraft Reticle / Symbol (Aircraft crosshair)
        p.setPen(QPen(QColor(t.get('pfd_crosshair', '#facc15')), 2.5))
        # Left wing
        p.drawLine(QPointF(cx - 36, cy), QPointF(cx - 12, cy))
        p.drawLine(QPointF(cx - 12, cy), QPointF(cx - 12, cy + 6))
        # Right wing
        p.drawLine(QPointF(cx + 12, cy), QPointF(cx + 36, cy))
        p.drawLine(QPointF(cx + 12, cy), QPointF(cx + 12, cy + 6))
        # Center pip
        p.drawEllipse(QRectF(cx - 3, cy - 3, 6, 6))

        # 4. Airspeed Tape (Left Side, 0 to 40 px wide)
        tape_w = 40.0
        p.fillRect(QRectF(0, 5, tape_w, horizon_h), QColor(0, 0, 0, 160))
        p.setPen(QPen(QColor(t['border']), 1.0))
        p.drawRect(QRectF(0, 5, tape_w, horizon_h))

        spd_px_per_unit = horizon_h / 25.0
        p.setFont(QFont(FONT_FAMILY_MONO, 8))
        min_spd = max(0, int(self.groundspeed - 12))
        max_spd = int(self.groundspeed + 12)

        for s in range(min_spd, max_spd + 1):
            if s < 0:
                continue
            sy = cy - (s - self.groundspeed) * spd_px_per_unit
            if 5 <= sy <= horizon_h + 5:
                is_major = (s % 5 == 0)
                tick_len = 10 if is_major else 5
                p.setPen(QPen(QColor('#ffffff'), 1.0 if not is_major else 1.5))
                p.drawLine(QPointF(tape_w - tick_len, sy), QPointF(tape_w, sy))
                if is_major:
                    p.drawText(QRectF(2, sy - 6, 26, 12), Qt.AlignmentFlag.AlignRight, f"{s}")

        # Airspeed Digital Box (Black box with yellow/cyan text)
        box_h = 20.0
        p.fillRect(QRectF(0, cy - box_h / 2, tape_w + 4, box_h), QColor('#0284c7'))
        p.setPen(QPen(QColor('#ffffff'), 1.5))
        p.drawRect(QRectF(0, cy - box_h / 2, tape_w + 4, box_h))
        p.setFont(QFont(FONT_FAMILY_MONO, 9, QFont.Weight.Bold))
        spd_str = f"{self.groundspeed:.1f}" if self.speed_valid else "--"
        p.drawText(QRectF(2, cy - box_h / 2, tape_w, box_h), Qt.AlignmentFlag.AlignCenter, spd_str)

        # Label atop speed tape
        p.setFont(QFont(FONT_FAMILY_PRIMARY, 7, QFont.Weight.Bold))
        p.setPen(QPen(QColor('#94a3b8'), 1.0))
        p.drawText(QRectF(0, 6, tape_w, 12), Qt.AlignmentFlag.AlignCenter, "SPD m/s")

        # 5. Altitude Tape (Right Side, w - 40 to w)
        alt_tape_x = w - 40.0
        p.fillRect(QRectF(alt_tape_x, 5, tape_w, horizon_h), QColor(0, 0, 0, 160))
        p.setPen(QPen(QColor(t['border']), 1.0))
        p.drawRect(QRectF(alt_tape_x, 5, tape_w, horizon_h))

        alt_px_per_unit = horizon_h / 30.0
        p.setFont(QFont(FONT_FAMILY_MONO, 8))
        min_alt = int(self.altitude - 15)
        max_alt = int(self.altitude + 15)

        for a in range(min_alt, max_alt + 1):
            ay = cy - (a - self.altitude) * alt_px_per_unit
            if 5 <= ay <= horizon_h + 5:
                is_major = (a % 10 == 0)
                tick_len = 10 if is_major else 5
                p.setPen(QPen(QColor('#ffffff'), 1.0 if not is_major else 1.5))
                p.drawLine(QPointF(alt_tape_x, ay), QPointF(alt_tape_x + tick_len, ay))
                if is_major:
                    p.drawText(QRectF(alt_tape_x + tick_len + 2, ay - 6, 24, 12), Qt.AlignmentFlag.AlignLeft, f"{a}")

        # Altitude Digital Box
        p.fillRect(QRectF(alt_tape_x - 4, cy - box_h / 2, tape_w + 4, box_h), QColor('#059669'))
        p.setPen(QPen(QColor('#ffffff'), 1.5))
        p.drawRect(QRectF(alt_tape_x - 4, cy - box_h / 2, tape_w + 4, box_h))
        p.setFont(QFont(FONT_FAMILY_MONO, 9, QFont.Weight.Bold))
        alt_str = f"{self.altitude:.1f}" if self.position_valid else "--"
        p.drawText(QRectF(alt_tape_x, cy - box_h / 2, tape_w, box_h), Qt.AlignmentFlag.AlignCenter, alt_str)

        # Label atop altitude tape
        p.setFont(QFont(FONT_FAMILY_PRIMARY, 7, QFont.Weight.Bold))
        p.setPen(QPen(QColor('#94a3b8'), 1.0))
        p.drawText(QRectF(alt_tape_x, 6, tape_w, 12), Qt.AlignmentFlag.AlignCenter, "ALT REL")

        # 6. Heading Ribbon (Bottom strip, 0 to w, h - 30 to h)
        ribbon_y = h - 28.0
        p.fillRect(QRectF(0, ribbon_y, w, 28.0), QColor(0, 0, 0, 200))
        p.setPen(QPen(QColor(t['border']), 1.0))
        p.drawRect(QRectF(0, ribbon_y, w, 28.0))

        hdg_px_per_deg = w / 90.0
        cardinals = {0: "N", 45: "NE", 90: "E", 135: "SE", 180: "S", 225: "SW", 270: "W", 315: "NW"}

        for tick in range(int(math.floor((yaw_deg - 60) / 5)) * 5, int(yaw_deg + 65), 5):
            angle = tick % 360
            hx = cx + ((tick - yaw_deg) * hdg_px_per_deg)
            if 0 <= hx <= w:
                is_cardinal = int(angle) in cardinals and (angle % 45 == 0)
                is_major = (angle % 15 == 0)
                p.setPen(QPen(QColor(t.get('pfd_crosshair', '#facc15')) if is_cardinal else QColor('#ffffff'), 1.5 if is_major else 1.0))
                p.drawLine(QPointF(hx, ribbon_y), QPointF(hx, ribbon_y + (8 if is_major else 4)))

                if is_cardinal:
                    p.setFont(QFont(FONT_FAMILY_PRIMARY, 8, QFont.Weight.Bold))
                    p.drawText(QRectF(hx - 12, ribbon_y + 9, 24, 14), Qt.AlignmentFlag.AlignCenter, cardinals[int(angle)])
                elif is_major:
                    p.setFont(QFont(FONT_FAMILY_MONO, 7))
                    p.drawText(QRectF(hx - 12, ribbon_y + 9, 24, 14), Qt.AlignmentFlag.AlignCenter, f"{int(angle):03d}")

        # Heading Digital Bug Box at center
        bug_w = 44.0
        p.fillRect(QRectF(cx - bug_w / 2, ribbon_y, bug_w, 18), QColor('#1e293b'))
        p.setPen(QPen(QColor(t.get('pfd_crosshair', '#facc15')), 1.5))
        p.drawRect(QRectF(cx - bug_w / 2, ribbon_y, bug_w, 18))
        p.setFont(QFont(FONT_FAMILY_MONO, 9, QFont.Weight.Bold))
        hdg_str = f"{int(yaw_deg):03d}°" if not self.is_stale else "---°"
        p.drawText(QRectF(cx - bug_w / 2, ribbon_y, bug_w, 18), Qt.AlignmentFlag.AlignCenter, hdg_str)

        # 7. Status & Stale Warnings
        if self.is_stale:
            p.fillRect(QRectF(cx - 50, 12, 100, 20), QColor(220, 38, 38, 220))
            p.setPen(QPen(QColor('#ffffff'), 1.0))
            p.setFont(QFont(FONT_FAMILY_PRIMARY, 9, QFont.Weight.Bold))
            p.drawText(QRectF(cx - 50, 12, 100, 20), Qt.AlignmentFlag.AlignCenter, "STALE DATA")


class InstrumentContainer(QFrame):
    """
    Unified cockpit instrument card containing both the 2D Primary Flight Display
    and the 3D CAD Aircraft view, with an immediate 1-click mode toggle.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("CockpitInstrumentContainer")
        t = get_theme()
        self.setStyleSheet(f"""
            #CockpitInstrumentContainer {{
                background-color: {t['surface']};
                border: 1px solid {t['border']};
                border-radius: 8px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        # Header Strip with Title and Toggle Buttons
        header = QHBoxLayout()
        header.setContentsMargins(4, 2, 4, 2)
        
        title = QLabel("FLIGHT ATTITUDE & PFD")
        title.setStyleSheet(f"color: {t['primary']}; font-family: {FONT_FAMILY_PRIMARY}; font-size: 11px; font-weight: 700; border: none; background: transparent;")
        header.addWidget(title)
        header.addStretch(1)

        # View Toggle Buttons
        self.btn_pfd = QPushButton("2D PFD")
        self.btn_pfd.setFixedHeight(22)
        self.btn_3d = QPushButton("3D CAD")
        self.btn_3d.setFixedHeight(22)

        toggle_btn_style = f"""
            QPushButton {{
                background-color: {t['surface_elevated']};
                color: {t['text_secondary']};
                border: 1px solid {t['border']};
                border-radius: 4px;
                padding: 2px 8px;
                font-size: 10px;
                font-weight: 700;
            }}
            QPushButton:hover {{
                background-color: {t['surface_sunken']};
                color: {t['text']};
            }}
        """
        self.btn_pfd.setStyleSheet(toggle_btn_style)
        self.btn_3d.setStyleSheet(toggle_btn_style)

        self.btn_pfd.clicked.connect(lambda: self.switch_view(0))
        self.btn_3d.clicked.connect(lambda: self.switch_view(1))

        header.addWidget(self.btn_pfd)
        header.addWidget(self.btn_3d)
        layout.addLayout(header)

        # Stacked display (0: 2D PFD, 1: 3D CAD)
        self.stack = QStackedWidget()
        self.pfd = PrimaryFlightDisplay()
        self.cad_view = None

        self.stack.addWidget(self.pfd)
        layout.addWidget(self.stack, stretch=1)

        # Highlight default active view (2D PFD)
        self.switch_view(0)

    def switch_view(self, index: int):
        if index == 1 and self.cad_view is None:
            self.cad_view = AttitudeView()
            self.stack.addWidget(self.cad_view)
        self.stack.setCurrentIndex(index)
        t = get_theme()
        active_style = f"background-color: {t['primary']}; color: #ffffff; border: 1px solid {t['primary']}; border-radius: 4px; padding: 2px 8px; font-size: 10px; font-weight: 700;"
        inactive_style = f"background-color: {t['surface_elevated']}; color: {t['text_secondary']}; border: 1px solid {t['border']}; border-radius: 4px; padding: 2px 8px; font-size: 10px; font-weight: 700;"
        
        if index == 0:
            self.btn_pfd.setStyleSheet(active_style)
            self.btn_3d.setStyleSheet(inactive_style)
        else:
            self.btn_pfd.setStyleSheet(inactive_style)
            self.btn_3d.setStyleSheet(active_style)

    def update_attitude(self, roll: float, pitch: float, yaw: float, alt: float, speed: float, climb: float = 0.0, mode: str = "UNKNOWN", armed: bool = False, is_stale: bool = False, position_valid: bool = True, speed_valid: bool = True):
        self.pfd.set_telemetry(roll, pitch, yaw, alt, speed, climb_rate=climb, mode=mode, armed=armed, is_stale=is_stale, position_valid=position_valid, speed_valid=speed_valid)
        if self.stack.currentIndex() == 1 and not is_stale:
            self.cad_view.update_attitude(roll, pitch, yaw, alt, speed)
